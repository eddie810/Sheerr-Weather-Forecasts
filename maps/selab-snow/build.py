"""Southeast Labrador weekend snow potential (1920x1080, RDPS-totals house style; top 200 px left clear for a header).

Not amounts: each area is placed in a plain-language category from the Canadian global ensemble (GEPS,
20 members + control): the chance of at least 10 mm of snow (liquid equivalent, roughly 8-10 cm on the
ground) in 24 hours, taking the highest of the 24-hour windows from Friday through Sunday. Shaded on land only. Writes map.png, zones.png, data.js.

  MAPBOX_ACCESS_TOKEN=... python3 build.py [run] [windows]
"""
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.image import imread, imsave  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GEOMET = "https://geo.weather.gc.ca/geomet"
W, H = 1920, 1080
LON0, LAT0, ZOOM = -58.60, 53.15, 6.70
RUN = "2026-10-15T00:00:00Z"
WINDOWS = ["2026-10-17T00:00:00Z", "2026-10-17T12:00:00Z", "2026-10-18T00:00:00Z",   # 24 h windows ending Fri 9:30 p.m. NDT
           "2026-10-18T12:00:00Z", "2026-10-19T00:00:00Z"]                            # through Sun 9:30 p.m. NDT
BOX = dict(lat=(49.5, 56.5), lon=(-66.0, -50.0))
# category: (min chance of >= 10 mm, colour, label)
CATS = [("likely", "#2367B3"), ("possible", "#8CC8EE")]          # RDPS-totals snow palette
# route shields: (ref, near lat, lon) -> drawn at the closest point on that route
SHIELDS = [("510", 53.10, -58.70), ("510", 51.95, -56.55), ("516", 53.45, -57.40), ("500", 52.95, -61.60),
           ("520", 53.42, -60.20), ("430", 50.95, -56.40)]
TOWNS = {"HV-GB": (53.302, -60.417), "Rigolet": (54.180, -58.430), "Cartwright": (53.708, -57.021),
         "Black Tickle": (53.459, -55.765), "Charlottetown": (52.766, -56.115), "Port Hope Simpson": (52.546, -56.300),
         "Mary's Harbour": (52.311, -55.833), "Red Bay": (51.726, -56.427), "L'Anse au Clair": (51.430, -57.060),
         "St. Anthony": (51.364, -55.580)}


def fetch(url, tries=5):
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def grid(layer, valid):
    url = (f"{GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={layer}"
           f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat({BOX['lat'][0]},{BOX['lat'][1]})"
           f"&subset=lon({BOX['lon'][0]},{BOX['lon'][1]})&resolution=lat(0.1)&resolution=lon(0.1)"
           f"&time={valid}&DIM_REFERENCE_TIME={RUN}&format=image/x-aaigrid")
    body = fetch(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    return np.clip(np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"])), 0, None), hdr


def world(lat, lon):
    s = 512 * 2 ** ZOOM
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def px(lat, lon):
    (x, y), (cx, cy) = world(lat, lon), world(LAT0, LON0)
    return [round(x - cx + W / 2, 1), round(y - cy + H / 2, 1)]


def main():
    tok = os.environ["MAPBOX_ACCESS_TOKEN"]
    cx, cy = world(LAT0, LON0)
    s = 512 * 2 ** ZOOM
    LON, LAT = np.meshgrid((cx - W / 2 + np.arange(W) + .5) / s * 360 - 180,
                           np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (cy - H / 2 + np.arange(H) + .5) / s)))))

    def sample(layer):
        best = None
        for v in WINDOWS:
            a, h = grid(layer, v)
            top = h["yllcorner"] + h["nrows"] * h["cellsize"]
            f = map_coordinates(gaussian_filter(a, 1.0), [(top - LAT) / h["cellsize"] - .5, (LON - h["xllcorner"]) / h["cellsize"] - .5], order=1)
            best = f if best is None else np.maximum(best, f)
        return best
    p10, p25 = sample("GEPS.DIAG.24_SNMM.ERGE10"), sample("GEPS.DIAG.24_SNMM.ERGE2.5")

    # land mask (Terrain-RGB, z8)
    tz = 8
    wx = (LON + 180) / 360 * 256 * 2 ** tz
    wy = (1 - np.log(np.tan(np.pi / 4 + np.radians(LAT) / 2)) / np.pi) / 2 * 256 * 2 ** tz
    tx0, ty0, tx1, ty1 = int(wx.min() // 256), int(wy.min() // 256), int(wx.max() // 256), int(wy.max() // 256)
    m = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            try:
                png = fetch(f"https://api.mapbox.com/v4/mapbox.terrain-rgb/{tz}/{tx}/{ty}.pngraw?access_token={tok}")
            except urllib.error.HTTPError:
                continue
            rgb = imread(io.BytesIO(png), format="png")[..., :3] * 255
            m[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = -10000 + (rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]) * .1
    land = map_coordinates(m, [wy - ty0 * 256, wx - tx0 * 256], order=0) > 0.5

    cat = np.zeros(LON.shape, int)                         # 0 unlikely, 2 possible, 3 likely
    cat[p10 >= 30] = 2
    cat[p10 >= 55] = 3
    cat[~land] = 0
    from scipy.ndimage import label
    for k in (2, 3):                                      # drop specks: isolated patches under ~6000 px (~50 km across)
        comps, n = label(cat >= k)
        for i in range(1, n + 1):
            if (comps == i).sum() < 6000:
                cat[(comps == i) & (cat >= k)] = k - 1 if k == 3 else 0
    rgba = np.zeros(LON.shape + (4,))
    for k, (name, col) in zip((3, 2), CATS):
        rgba[cat == k, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        rgba[cat == k, 3] = 0.82
    imsave(os.path.join(HERE, "zones.png"), rgba)

    # zone edges + coastline as SVG paths
    def paths(field, lev, step=2, minlen=20):
        fig, ax = plt.subplots(); cs = ax.contour(gaussian_filter(field.astype(float), 1.2), levels=[lev])
        d = "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pp[::step]) for p in cs.get_paths()
                    for pp in p.to_polygons(closed_only=False) if len(pp) > minlen)
        plt.close(fig); return d
    data = {"run": RUN, "windows": WINDOWS, "coast": paths(land, .5, 2, 30),
            "edges": {k: paths((cat >= k) & land, .5) for k in (2, 3)},
            "towns": {n: px(*ll) for n, ll in TOWNS.items()},
            "chance": {n: [round(float(map_coordinates(f, [[px(*ll)[1]], [px(*ll)[0]]], order=1)[0])) for f in (p10, p25)]
                       for n, ll in TOWNS.items()}}
    # roads (OSM trunk/primary, roads.json) and the Quebec-Labrador border (Natural Earth, border.json)
    roads = json.load(open(os.path.join(HERE, "roads.json")))
    seg = lambda pts: "M" + "L".join("%.1f,%.1f" % tuple(px(la, lo)) for lo, la in pts)
    data["roads"] = [{"trunk": r["hw"] == "trunk", "d": seg(r["pts"])} for r in roads
                     if any(-200 < px(la, lo)[0] < W + 200 and -200 < px(la, lo)[1] < H + 200 for lo, la in r["pts"])]
    data["border"] = "".join(seg(line) for line in json.load(open(os.path.join(HERE, "border.json"))))
    data["shields"] = []
    for ref, la0, lo0 in SHIELDS:
        pts = [(la, lo) for r in roads if r["ref"] == ref for lo, la in r["pts"]]
        if pts:
            la, lo = min(pts, key=lambda q: (q[0] - la0) ** 2 + ((q[1] - lo0) * 0.6) ** 2)
            data["shields"].append({"ref": ref, "xy": px(la, lo)})
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.SNOWPOT = " + json.dumps(data) + ";\n")
    with open(os.path.join(HERE, "map.png"), "wb") as f:
        f.write(fetch(f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM - 1:.3f},0/"
                      f"{W // 2}x{H // 2}@2x?attribution=false&logo=false"
                      f"&layer_id=state-label&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D&access_token={tok}"))
    print({n: c for n, c in data["chance"].items()})


if __name__ == "__main__":
    if len(sys.argv) > 1:
        RUN = sys.argv[1]
    if len(sys.argv) > 2:
        WINDOWS = sys.argv[2].split(",")
    main()
