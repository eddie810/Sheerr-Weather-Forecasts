"""Animated wind chill map for Newfoundland and Labrador (4:5): HRDPS 2 m temperature and 10 m wind through the
day, as Environment Canada wind chill, shaded on NL land and shown at the nl-temps province towns.

Reuses the nl-temps build (frame, land mask, coastline, roads, basemap) with its "nl" region. Hourly HRDPS fields are
blended linearly into SUB steps per hour (temperature and wind change smoothly, so a straight blend is enough), so the
shading drifts instead of jumping. Writes frames/NNN.png, data.js (times, town values), map.png.

  MAPBOX_ACCESS_TOKEN=... python3 build.py [first UTC hour, default 9] [last UTC hour, default 24]   (today, UTC date)
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "nl-temps"))
import build as nl  # noqa: E402

SUB = 6                                    # steps per model hour (10 minutes)
REGION = nl.REGIONS["nl"]
# card offsets (CSS px from the town dot) where the wider wind chill cards would overlap with the highs-map offsets
CARD = {"St. Anthony": (150, -30), "Gander": (170, -10), "St. John's": (140, 45)}
# wind chill palette: the house temperature colours, continued into purples below -10
TC = {**nl.TC, **{-12: "#BDB4E8", -14: "#B4A5E1", -16: "#AA96D9", -18: "#A087D0", -20: "#9579C6", -22: "#8A6BBB",
                    -24: "#7E5EAF", -26: "#72529F", -28: "#66478F"}}


def windchill(t, kmh):
    """Environment Canada wind chill (°C) for air temperature t (°C) and 10 m wind (km/h); the air temperature where the
    index doesn't apply (above 10 °C or wind under 5 km/h)."""
    v = np.maximum(kmh, 5) ** 0.16
    wc = 13.12 + 0.6215 * t - 11.37 * v + 0.3965 * t * v
    return np.where((t <= 10) & (kmh >= 5), np.minimum(wc, t), t)


def grid(coverage, when):
    url = (f"https://geo.weather.gc.ca/geomet?service=WCS&version=2.0.1&request=GetCoverage&coverageId={coverage}"
           f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat({nl.BOX['lat'][0]},{nl.BOX['lat'][1]})"
           f"&subset=lon({nl.BOX['lon'][0]},{nl.BOX['lon'][1]})&resolution=lat(0.025)&resolution=lon(0.035)"
           f"&time={when}&format=image/x-aaigrid")
    body = nl.fetch(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    return np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"])), hdr


def main(h0="9", h1="24", ne_path=os.path.join(HERE, "..", "..", "data", "ne", "adm1.geojson")):
    (nl.LON0, nl.LAT0), nl.ZOOM, nl.TOWNS, nl.BOX = REGION["center"], REGION["zoom"], REGION["towns"], REGION["box"]
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    times = [day + timedelta(hours=h) for h in range(int(h0), int(h1) + 1)]

    def hour(t):
        iso = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        (tt, hdr), (ws, _) = grid("HRDPS.CONTINENTAL_TT", iso), grid("HRDPS.CONTINENTAL_WSPD", iso)
        return gaussian_filter(tt, 1.0), gaussian_filter(ws * 3.6, 1.0), hdr          # wind m/s -> km/h
    with ThreadPoolExecutor(4) as ex:
        G = list(ex.map(hour, times))
    hdr = G[0][2]
    lats0 = hdr["yllcorner"] + hdr["dy"] * (hdr["nrows"] - 0.5)

    # NL land in the frame (Terrain-RGB land inside the province outline), as in the nl-temps maps
    land, LON, LAT = nl.land_mask(1)
    with open(ne_path) as f:
        rings = [p[0] for ft in json.load(f)["features"] if ft["properties"].get("name") == "Newfoundland and Labrador"
                 for p in ft["geometry"]["coordinates"] if len(p[0]) > 20]
    nl_land = nl.in_rings(rings, LON, LAT, land)
    rows, cols = (lats0 - LAT) / hdr["dy"], (LON - hdr["xllcorner"]) / hdr["dx"]
    proj = nl.projector()
    txy = {n: proj(*ll[:2]) for n, ll in nl.TOWNS.items()}
    trc = {n: ((lats0 - ll[0]) / hdr["dy"], (ll[1] - hdr["xllcorner"]) / hdr["dx"]) for n, ll in nl.TOWNS.items()}

    fdir = os.path.join(HERE, "frames")
    os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir):
        os.remove(os.path.join(fdir, f))
    steps = [(i, s) for i in range(len(G) - 1) for s in range(SUB)] + [(len(G) - 2, SUB)]
    colours = {b: [int(TC[b][i:i + 2], 16) for i in (1, 3, 5)] for b in TC}
    keys = sorted(TC)

    def one(n_is):
        n, (i, s) = n_is
        f = s / SUB
        t = (1 - f) * G[i][0] + f * G[i + 1][0]
        w = (1 - f) * G[i][1] + f * G[i + 1][1]
        wc = windchill(t, w)
        img = map_coordinates(wc, [rows, cols], order=1)
        band = np.clip(np.floor(img / 2) * 2, keys[0], keys[-1]).astype(int)
        rgba = np.zeros(band.shape + (4,), np.uint8)
        for b in np.unique(band[nl_land]):
            rgba[(band == b) & nl_land, :3] = colours[b]
        rgba[..., 3] = nl_land * 200
        Image.fromarray(rgba).save(os.path.join(fdir, f"{n:03d}.png"), compress_level=1)
        at = lambda a, rc: float(map_coordinates(a, [[rc[0]], [rc[1]]], order=1)[0])
        return n, {nm: [round(at(wc, rc), 1), round(at(t, rc), 1), round(at(w, rc))] for nm, rc in trc.items()}, \
            sorted(set(band[nl_land].tolist()))
    with ThreadPoolExecutor(6) as ex:
        res = sorted(ex.map(one, enumerate(steps)))
    vals = [r[1] for r in res]
    used = sorted(set(b for r in res for b in r[2]))

    with open(os.path.join(HERE, "map.png"), "wb") as f:
        f.write(nl.fetch(f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{nl.LON0},{nl.LAT0},{nl.ZOOM},0/"
                         f"{nl.W}x{nl.H}@2x?attribution=false&logo=false&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"))
    # TCH from Natural Earth (Island), Routes 500/510 from the OSM Labrador file, as on the province highs map
    spec = REGION["roads"]
    roads = nl.roads_layer(os.path.join(HERE, "..", "..", "data", "roads_na.geojson"), [r for r in spec if r[1] == "1"], proj, None, "CAN") + \
        nl.roads_layer(os.path.join(HERE, "..", "nl-temps", "roads-labrador.geojson"), [r for r in spec if r[1] != "1"], proj, None, "CAN")
    wcs_all = [v[0] for st in vals for v in st.values()]
    diff = [v[1] - v[0] for st in vals for v in st.values()]
    data = {
        "sub": SUB, "date": f"{times[0].astimezone(nl.NDT):%A, %B %-d}", "weekday": f"{times[0].astimezone(nl.NDT):%A}",
        "times": [(times[i] + timedelta(minutes=60 * s / SUB)).astimezone(nl.NDT).strftime("%-I:%M %p") for i, s in steps],
        "range": [round(min(wcs_all)), round(max(wcs_all))], "colder": round(float(np.median(diff))),
        "towns": {n: {"xy": [round(v) for v in txy[n]],
                      "card": [round(txy[n][0] + CARD.get(n, ll[2:])[0]), round(txy[n][1] + CARD.get(n, ll[2:])[1])]}
                  for n, ll in nl.TOWNS.items()},
        "vals": vals, "colours": TC, "bands_used": used,
        "coast": nl.coast_path(nl_land, 1),
        "roads": roads,
        "labels": [list(l) for l in REGION.get("labels", [])],
    }
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.WC = " + json.dumps(data) + ";\n")
    print(len(steps), "frames", data["times"][0], "to", data["times"][-1], "| wind chill", data["range"],
          "| median", data["colder"], "° colder than the air")
    for n in nl.TOWNS:
        print(f"  {n:24s}", " ".join(f"{vals[k][n][0]:5.0f}" for k in range(0, len(vals), SUB * 3)))


if __name__ == "__main__":
    main(*sys.argv[1:3])
