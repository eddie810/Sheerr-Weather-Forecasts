"""Build the Labrador total-snowfall contour map from the HRDPS model.

Pulls HRDPS 2.5 km accumulated snow (liquid equivalent, mm) from MSC GeoMet's
WCS, converts to snowfall at 10:1 (1 mm water = 1 cm snow), smooths and
contours it, and writes SVG paths projected onto a Mapbox basemap.

  MAPBOX_ACCESS_TOKEN=... python3 build.py RUN VALID ne_10m_admin_1_states_provinces.geojson
  e.g. python3 build.py 2026-10-10T06:00:00Z 2026-10-12T06:00:00Z ne.geojson
"""
import json
import math
import os
import re
import sys
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BBOX = dict(lat=(50.5, 61.2), lon=(-71.5, -52.0))       # data request
W, H = 1080, 900                                          # map frame (CSS px)
LON0, LAT0, ZOOM = -61.55, 55.75, 5.42
LEVELS = [2, 5, 10, 15, 20, 1000]                        # cm band edges
TOWNS = {
    "Labrador City": (52.946, -66.911),
    "Churchill Falls": (53.528, -63.966),
    "Happy Valley-Goose Bay": (53.302, -60.417),
    "Nain": (56.542, -61.692),
    "Hopedale": (55.456, -60.209),
    "Natuashish": (55.913, -61.103),
    "Makkovik": (55.083, -59.172),
    "Cartwright": (53.708, -57.021),
    "Mary's Harbour": (52.307, -55.833),
}


def wcs_grid(run, valid):
    url = ("https://geo.weather.gc.ca/geomet?service=WCS&version=2.0.1&request=GetCoverage"
           "&coverageId=HRDPS.CONTINENTAL_SN&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326"
           f"&subset=lat({BBOX['lat'][0]},{BBOX['lat'][1]})&subset=lon({BBOX['lon'][0]},{BBOX['lon'][1]})"
           "&resolution=lat(0.025)&resolution=lon(0.04)"
           f"&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    raw = urllib.request.urlopen(url, timeout=180).read().decode("latin1")
    body = raw.split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    a = np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"]))
    lons = hdr["xllcorner"] + hdr["dx"] * (np.arange(a.shape[1]) + 0.5)
    lats = hdr["yllcorner"] + hdr["dy"] * (np.arange(a.shape[0]) + 0.5)
    return lons, lats[::-1], a  # first row is the northern edge


def projector():
    s = 512 * 2 ** ZOOM / (2 * math.pi)
    mx = lambda lo: s * math.radians(lo)
    my = lambda la: s * math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    return lambda la, lo: (W / 2 + mx(lo) - mx(LON0), H / 2 - (my(la) - my(LAT0)))


def svg_path(rings_lonlat, proj, min_px=0.8):
    out = []
    for ring in rings_lonlat:
        pts = [proj(la, lo) for lo, la in ring]
        kept = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - kept[-1][0]) + abs(p[1] - kept[-1][1]) >= min_px:
                kept.append(p)
        if len(kept) > 2:
            out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in kept) + "Z")
    return "".join(out)


def contour_bands(lons, lats, cm, proj):
    fig, ax = plt.subplots()
    cs = ax.contourf(lons, lats, cm, levels=LEVELS)
    bands = []
    for lvl, path in zip(LEVELS[:-1], cs.get_paths()):
        # matplotlib packs all rings of a band (outer + holes) into one path; split on MOVETO
        rings = [poly.tolist() for poly in path.to_polygons()]
        bands.append({"from": lvl, "d": svg_path(rings, proj)})
    lines = []
    cl = ax.contour(lons, lats, cm, levels=LEVELS[:-1])
    for lvl, path in zip(LEVELS[:-1], cl.get_paths()):
        rings = [poly.tolist() for poly in path.to_polygons(closed_only=False)]
        d = svg_path(rings, proj).replace("Z", "")
        lines.append({"level": lvl, "d": d})
    plt.close(fig)
    return bands, lines


def main(run, valid, ne_path):
    lons, lats, mm = wcs_grid(run, valid)
    cm = gaussian_filter(mm, sigma=1.6)   # 10:1 ratio, lightly smoothed for clean contours
    proj = projector()
    bands, lines = contour_bands(lons, lats, cm, proj)

    def at(la, lo):
        r = int(np.argmin(np.abs(lats - la)))
        c = int(np.argmin(np.abs(lons - lo)))
        return float(cm[r, c])

    with open(ne_path) as f:
        provs = {ft["properties"]["name"]: ft["geometry"] for ft in json.load(f)["features"]
                 if ft["properties"].get("adm0_a3") == "CAN"}

    def geom_path(g):
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        rings = []
        for poly in polys:
            ring = poly[0]
            # Labrador only: skip the Island of Newfoundland and small islands south of 52N
            if max(la for _, la in ring) < 52.0 and min(lo for lo, _ in ring) > -60:
                continue
            if len(ring) > 30:
                rings.append(ring)
        return svg_path(rings, proj)

    data = {
        "run": run, "valid": valid,
        "bands": bands, "lines": lines,
        "labrador": geom_path(provs["Newfoundland and Labrador"]),
        "quebec": svg_path([r for p in provs["Québec"]["coordinates"] for r in p[:1]], proj, 1.5),
        "towns": {n: {"xy": [round(v) for v in proj(*ll)], "cm": round(at(*ll))} for n, ll in TOWNS.items()},
    }
    with open(os.path.join(HERE, "contours.js"), "w") as f:
        f.write("// generated by build.py\nwindow.SNOW = " + json.dumps(data) + ";\n")

    url = (f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM},0/"
           f"{W}x{H}@2x?attribution=false&logo=false&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}")
    urllib.request.urlretrieve(url, os.path.join(HERE, "map.png"))
    print({n: v["cm"] for n, v in data["towns"].items()}, "max", round(float(cm.max()), 1))


if __name__ == "__main__":
    main(*sys.argv[1:4])
