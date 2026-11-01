"""1920x1080 "temperature drop" map for eastern Newfoundland: HRDPS 2 m temperature at two times, the change shaded on Island
land and each town labelled "11° → 4°".

Frame, land mask, outlines, highways and the page layout come from graphics/rdps-totals; the
basemap drops Mapbox's own place names (one static request per label layer, lightest pixel kept), as in woof-snow.
Writes shade.png, map.png, data.js.

  MAPBOX_ACCESS_TOKEN=... python3 build.py [from UTC, default 2026-10-31T15] [to UTC, default 2026-10-31T21]
"""
import importlib.util
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

import numpy as np
from matplotlib.image import imsave
from PIL import Image
from scipy.ndimage import binary_dilation, gaussian_filter, map_coordinates, median_filter

HERE = os.path.dirname(os.path.abspath(__file__))
ADM1 = os.path.join(HERE, "..", "..", "data", "ne", "adm1.geojson")
# temperature change (°C), banded every 2°: drops in blues, rises in warm tones
BANDS = [(-99, "#2F4FA3"), (-10, "#3F6FC0"), (-8, "#5A8FD6"), (-6, "#83B2E6"), (-4, "#B3D2F1"), (-2, "#E1ECF6"),
         (0, "#F6E3C8"), (2, "#F2C08E")]
LABELS = ["", "−10", "−8", "−6", "−4", "−2", "0", "+2"]
# eastern Newfoundland (the drop is east of Gander): frame centre, zoom, towns
CENTER, ZOOM = (-54.82, 47.68), 7.85
TOWNS = {"St. John's": (47.561, -52.713), "Carbonear": (47.737, -53.215), "Placentia": (47.245, -53.962),
         "Ferryland": (47.024, -52.890), "Trepassey": (46.737, -53.363), "Whitbourne": (47.417, -53.533),
         "Old Perlican": (48.083, -53.017), "Marystown": (47.166, -55.148), "Grand Bank": (47.100, -55.765),
         "St. Lawrence": (46.920, -55.393), "Arnold's Cove": (47.750, -53.983), "Clarenville": (48.165, -53.965),
         "Bonavista": (48.650, -53.115), "Trinity": (48.367, -53.367), "Gander": (48.954, -54.609),
         "Glovertown": (48.683, -54.033), "Grand Falls-Windsor": (48.936, -55.660), "Harbour Breton": (47.483, -55.797),
         "Swift Current": (47.883, -54.217), "Lewisporte": (49.250, -55.050), "Musgrave Harbour": (49.450, -53.967)}

spec = importlib.util.spec_from_file_location("rdps", os.path.join(HERE, "..", "rdps-totals", "build.py"))
rdps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rdps)


def tt(run, valid):
    """HRDPS 2 m temperature (°C) around the Island at one valid time (not clipped at 0 like rdps.grid)."""
    url = (f"{rdps.GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId=HRDPS.CONTINENTAL_TT"
           f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat(45.5,52.5)&subset=lon(-61,-51.5)"
           f"&resolution=lat(0.025)&resolution=lon(0.035)&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    body = rdps.fetch(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    return np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"])), hdr


def basemap(path):
    def base(layer):
        return np.asarray(Image.open(io.BytesIO(rdps.fetch(
            f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{rdps.LON0},{rdps.LAT0},{rdps.ZOOM - 1:.3f},0/960x540@2x"
            f"?attribution=false&logo=false&layer_id={layer}&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D"
            f"&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"))).convert("RGB"))
    ims = [base(l) for l in ("settlement-minor-label", "settlement-major-label", "state-label", "natural-point-label",
                             "poi-label", "country-label")]
    m = np.maximum.reduce(ims)
    diff = binary_dilation(np.ptp(np.stack(ims).astype(int), axis=0).max(2) > 6, iterations=3)
    m[diff] = median_filter(m, size=(25, 25, 1))[diff]
    Image.fromarray(m).save(path)


def main(t0="2026-10-31T15", t1="2026-10-31T21"):
    rdps.W, rdps.H = 1920, 1080
    (rdps.LON0, rdps.LAT0), rdps.ZOOM, rdps.TOWNS = CENTER, ZOOM, TOWNS
    caps = rdps.fetch(f"{rdps.GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer=HRDPS.CONTINENTAL_TT").decode()
    run = re.search(r'<Dimension name="reference_time"[^>]*default="([^"]+)"', caps).group(1)
    a, hdr = tt(run, t0 + ":00:00Z")
    b, _ = tt(run, t1 + ":00:00Z")
    a, b = gaussian_filter(a, 1.0), gaussian_filter(b, 1.0)
    top = hdr["yllcorner"] + hdr["nrows"] * hdr["dy"]
    rc = lambda la, lo: ((top - la) / hdr["dy"] - .5, (lo - hdr["xllcorner"]) / hdr["dx"] - .5)

    LON, LAT = rdps.frame_lonlat()
    rows, cols = rc(LAT, LON)
    d = map_coordinates(b - a, [rows, cols], order=1)
    land = rdps.land_mask() * rdps.nl_mask(ADM1, True)
    rgba = np.zeros(d.shape + (4,))
    for lo, col in BANDS:
        sel = d >= lo
        rgba[sel, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        rgba[sel, 3] = 0.85
    rgba[..., 3] *= land
    imsave(os.path.join(HERE, "shade.png"), rgba)

    at = lambda f, la, lo: float(map_coordinates(f, [[rc(la, lo)[0]], [rc(la, lo)[1]]], order=1)[0])
    towns = {n: [round(at(a, *ll)), round(at(b, *ll))] for n, ll in rdps.TOWNS.items()}
    ndt = lambda t: datetime.fromisoformat(t + ":00:00+00:00").astimezone(rdps.NDT).strftime("%-I:%M %p")
    out = {"run": run, "from": ndt(t0), "to": ndt(t1),
           "day": datetime.fromisoformat(t0 + ":00:00+00:00").astimezone(rdps.NDT).strftime("%A"),
           "bands": [[l, c] for l, (_, c) in zip(LABELS, BANDS)], "towns": towns,
           "xy": {n: rdps.px(*ll) for n, ll in rdps.TOWNS.items()},
           "outlines": rdps.outlines(ADM1), "roads": rdps.roads_layer("island"),
           "range": [round(float(d[land > .5].min()), 1), round(float(d[land > .5].max()), 1)]}
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.DROP = " + json.dumps(out) + ";\n")
    basemap(os.path.join(HERE, "map.png"))
    print("HRDPS run", run, out["from"], "->", out["to"], "| change on land", out["range"])
    for n, (x, y) in towns.items():
        print(f"  {n:22s} {x:3d}° -> {y:3d}°  ({y - x:+d})")


if __name__ == "__main__":
    main(*sys.argv[1:3])
