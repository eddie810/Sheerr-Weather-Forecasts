"""Southeast Labrador Special Weather Statement graphic (first notable snowfall, Saturday).

Alert areas from The Weather Company (ECCC), shaded only on land (Mapbox Terrain-RGB mask) so
they follow the coastline. Writes map.png, alert.png, data.js for index.html.

  MAPBOX_ACCESS_TOKEN=... TWC_API_KEY=... python3 build.py ne_10m_admin_1_states_provinces.geojson
"""
import io
import json
import math
import os
import sys
import urllib.error
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.image import imread, imsave  # noqa: E402
from matplotlib.path import Path  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 640
LON0, LAT0, ZOOM = -57.75, 52.65, 6.30
EVENT = "Special Weather Statement"
# probe a grid across southeast Labrador so every alerted region is found
PROBES = [f"{la:.2f},{lo:.2f}" for la in np.arange(51.4, 54.4, 0.3) for lo in np.arange(-61.5, -55.4, 0.4)]
TOWNS = {"Cartwright": (53.708, -57.021), "Black Tickle": (53.459, -55.765), "Charlottetown": (52.766, -56.115),
         "Port Hope Simpson": (52.546, -56.300), "St. Lewis": (52.372, -55.676), "Mary's Harbour": (52.311, -55.833),
         "Red Bay": (51.726, -56.427), "L'Anse au Loup": (51.523, -56.830), "L'Anse au Clair": (51.430, -57.060),
         "Paradise River": (53.430, -57.290), "Happy Valley-Goose Bay": (53.302, -60.417), "Rigolet": (54.180, -58.430),
         "St. Anthony": (51.364, -55.580)}
INSET = dict(lon0=-60.0, lat0=52.6, zoom=3.15, w=230, h=250)


def get(url):
    with urllib.request.urlopen(url, timeout=90) as r:
        return r.read()


def world(lat, lon, z):
    s = 512 * 2 ** z
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def proj_for(lon0, lat0, z, w, h):
    cx, cy = world(lat0, lon0, z)
    return lambda la, lo: (world(la, lo, z)[0] - cx + w / 2, world(la, lo, z)[1] - cy + h / 2)


def frame_lonlat(scale):
    cx, cy = world(LAT0, LON0, ZOOM)
    s = 512 * 2 ** ZOOM
    xs = (cx - W / 2) + (np.arange(W * scale) + .5) / scale
    ys = (cy - H / 2) + (np.arange(H * scale) + .5) / scale
    return np.meshgrid(xs / s * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s)))))


def elevation(LON, LAT, tz=9):
    wx = (LON + 180) / 360 * 256 * 2 ** tz
    wy = (1 - np.log(np.tan(np.pi / 4 + np.radians(LAT) / 2)) / np.pi) / 2 * 256 * 2 ** tz
    tx0, ty0, tx1, ty1 = int(wx.min() // 256), int(wy.min() // 256), int(wx.max() // 256), int(wy.max() // 256)
    m = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
    tok = os.environ["MAPBOX_ACCESS_TOKEN"]
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            try:
                png = get(f"https://api.mapbox.com/v4/mapbox.terrain-rgb/{tz}/{tx}/{ty}.pngraw?access_token={tok}")
            except urllib.error.HTTPError:          # open ocean tile
                continue
            rgb = imread(io.BytesIO(png), format="png")[..., :3] * 255
            m[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = \
                -10000 + (rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]) * .1
    return map_coordinates(m, [wy - ty0 * 256, wx - tx0 * 256], order=1)


def edge_path(mask, scale, min_len=12):
    fig, ax = plt.subplots()
    cs = ax.contour(gaussian_filter(mask.astype(float), 1.0), levels=[.5])
    out = ["M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in poly[::scale] / scale)
           for p in cs.get_paths() for poly in p.to_polygons(closed_only=False) if len(poly) >= min_len]
    plt.close(fig)
    return "".join(out)


def basemap():
    """light-v11 with province and settlement names removed (the page draws its own towns).

    The Static API filters one layer per request, so fetch the map as-is and once with each label layer
    hidden. light-v11 is near-greyscale, so colour can't tell label from map; instead estimate the local map
    tone with a wide median filter (thin text strokes and halos drop out) and keep, per pixel, the
    candidate closest to it. Pixels where every candidate agrees are untouched."""
    url = (f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM},0/{W}x{H}@2x"
           f"?attribution=false&logo=false&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}")
    hide = '&layer_id={}&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D'
    st = np.stack([imread(io.BytesIO(get(url + (hide.format(L) if L else ""))), format="png")[..., :3]
                   for L in (None, "state-label", "settlement-major-label", "settlement-minor-label", "settlement-subdivision-label")])
    from scipy.ndimage import median_filter
    g = st.mean(-1)
    bg = median_filter(g.min(0), size=17)             # local map tone; thin label strokes and halos drop out
    pick = np.argmin(np.abs(g - bg[None]), axis=0)
    return np.take_along_axis(st, pick[None, ..., None].repeat(3, -1), 0)[0]


def main(ne_path):
    key = os.environ["TWC_API_KEY"]
    alerts = {}
    for g in PROBES:
        try:
            raw = get(f"https://api.weather.com/v3/alerts/headlines?geocode={g}&format=json&language=en-CA&apiKey={key}")
        except urllib.error.HTTPError:          # open water / no zone at this point
            continue
        for a in (json.loads(raw)["alerts"] if raw.strip() else []):
            if a["eventDescription"] == EVENT and a["adminDistrictCode"] == "NL":
                alerts[a["detailKey"]] = a
    details = [json.loads(get(f"https://api.weather.com/v3/alerts/detail?alertId={k}&format=json&language=en-CA&apiKey={key}"))["alertDetail"]
               for k in alerts]
    polys = [[(p["lon"], p["lat"]) for p in d["polygon"]] for d in details]

    scale = 2
    LON, LAT = frame_lonlat(scale)
    elev = elevation(LON, LAT)
    land = elev > 0.5
    pts = np.column_stack([LON.ravel(), LAT.ravel()])
    inside = np.zeros(LON.size, bool)
    for poly in polys:
        inside |= Path(np.array(poly)).contains_points(pts)
    inside = inside.reshape(LON.shape) & land

    rgba = np.zeros(LON.shape + (4,))
    rgba[inside, :3] = [0.42, 0.47, 0.49]
    rgba[inside, 3] = 0.40
    imsave(os.path.join(HERE, "alert.png"), rgba)

    proj = proj_for(LON0, LAT0, ZOOM, W, H)
    iproj = proj_for(INSET["lon0"], INSET["lat0"], INSET["zoom"], INSET["w"], INSET["h"])
    with open(ne_path) as f:
        nl = next(ft["geometry"] for ft in json.load(f)["features"] if ft["properties"].get("name") == "Newfoundland and Labrador")
    def ipath(rings):
        return "".join("M" + "L".join("%.1f,%.1f" % iproj(la, lo) for lo, la in r) + "Z" for r in rings)
    a0 = details[0]
    data = {
        "issued": a0["issueTimeLocal"], "ends": a0.get("endTimeLocal") or a0["expireTimeLocal"],
        "areas": sorted(d["areaName"] for d in details), "text": a0["texts"][0]["description"],
        "outline": edge_path(inside, scale),
        "towns": {n: [round(v) for v in proj(*ll)] for n, ll in TOWNS.items()},
        "inset": {"nl": ipath([p[0] for p in nl["coordinates"] if len(p[0]) > 30]), "alert": ipath(polys),
                  "frame": [round(v, 1) for v in (*iproj(*_corner(1)), *iproj(*_corner(-1)))]},
    }
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.SWS = " + json.dumps(data) + ";\n")
    imsave(os.path.join(HERE, "map.png"), basemap())
    print(data["areas"], data["issued"], "->", data["ends"])
    print(data["towns"])


def _corner(sign):
    s = 512 * 2 ** ZOOM / (2 * math.pi)
    my0 = s * math.log(math.tan(math.pi / 4 + math.radians(LAT0) / 2))
    return (math.degrees(2 * math.atan(math.exp((my0 + sign * H / 2) / s)) - math.pi / 2),
            LON0 - sign * math.degrees((W / 2) / s))


if __name__ == "__main__":
    main(sys.argv[1])
