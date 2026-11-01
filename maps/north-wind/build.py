"""Northern and northeastern Newfoundland Wind Warning graphics (social 4:5 + broadcast 1920x1080).

Warning area and text from The Weather Company (ECCC), shaded on land only (Mapbox Terrain-RGB),
TCH from Natural Earth roads. Writes map-{social,tv}.png, alert-{social,tv}.png, data.js.

  MAPBOX_ACCESS_TOKEN=... TWC_API_KEY=... python3 build.py roads.geojson
"""
import io
import json
import math
import os
import sys
import urllib.error
import urllib.request

import numpy as np
from matplotlib.image import imread, imsave
from matplotlib.path import Path
from scipy.ndimage import gaussian_filter, map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
PROBES = [f"{la:.2f},{lo:.2f}" for la in (48.9 + 0.3 * i for i in range(10)) for lo in (-58.4 + 0.35 * j for j in range(13))]   # grid over northern NL
FRAMES = {"social": dict(w=1080, h=700, lon0=-56.35, lat0=50.17, zoom=6.70),
          "tv": dict(w=1920, h=1080, lon0=-55.15, lat0=50.20, zoom=7.35)}
TOWNS = {"St. Anthony": (51.364, -55.580), "Flower's Cove": (51.300, -56.733), "Port Saunders": (50.645, -57.298),
         "Roddickton": (50.866, -56.120), "Parson's Pond": (50.030, -57.712), "Baie Verte": (49.932, -56.180),
         "Springdale": (49.497, -56.072), "Botwood": (49.142, -55.348), "Lewisporte": (49.248, -55.051),
         "Twillingate": (49.648, -54.761), "Deer Lake": (49.174, -57.426), "Grand Falls-Windsor": (48.936, -55.660)}


def get(url):
    with urllib.request.urlopen(url, timeout=90) as r:
        return r.read()


def world(lat, lon, z):
    s = 512 * 2 ** z
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def basemap(fr, tok):
    """Outdoors basemap with the place-name labels removed (the page draws its own).

    The Static API can filter only one layer per request, so fetch the map as-is plus once with each
    settlement-label layer hidden (POI labels stay: hiding them lets shields move in), and per pixel keep the most saturated candidate: label text and halos are grey/white,
    the map under them is green/blue/beige. Shields and roads are untouched."""
    url = (f"https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/static/{fr['lon0']},{fr['lat0']},{fr['zoom'] - 1:.3f},0/"
           f"{fr['w'] // 2}x{fr['h'] // 2}@2x?attribution=false&logo=false&access_token={tok}")
    hide = '&layer_id={}&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D'
    imgs = [imread(io.BytesIO(get(url + (hide.format(L) if L else ""))), format="png")[..., :3]
            for L in (None, "settlement-major-label", "settlement-minor-label")]
    st = np.stack(imgs)                                              # 3,h,w,3
    sat = st.max(-1) - st.min(-1)
    sat[0] += 0.02                                                   # ties go to the unfiltered map
    pick = np.argmax(sat, axis=0)
    return np.take_along_axis(st, pick[None, ..., None].repeat(3, -1), 0)[0]


def main(roads_path):
    key = os.environ["TWC_API_KEY"]
    alerts = {}
    for pr in PROBES:
        try:
            raw = get(f"https://api.weather.com/v3/alerts/headlines?geocode={pr}&format=json&language=en-CA&apiKey={key}")
        except urllib.error.HTTPError:               # open water / no forecast zone
            continue
        for x in (json.loads(raw)["alerts"] if raw.strip() else []):
            if x["eventDescription"].endswith("Warning - Wind") and x.get("adminDistrictCode") == "NL":
                alerts[x["detailKey"]] = x
    a = next(iter(alerts.values()))
    dets = [json.loads(get(f"https://api.weather.com/v3/alerts/detail?alertId={k}&format=json&language=en-CA&apiKey={key}"))["alertDetail"] for k in alerts]
    d = dets[0]
    polys = [Path(np.array([(p["lon"], p["lat"]) for p in dd["polygon"]])) for dd in dets]
    with open(roads_path) as f:
        roads = [ft for ft in json.load(f)["features"] if ft["properties"].get("sov_a3") == "CAN"
                 and ft["properties"].get("name") == "1" and ft["properties"].get("type") == "Major Highway"]
    tok = os.environ["MAPBOX_ACCESS_TOKEN"]
    data = {"event": a["eventDescription"], "area": [dd["areaName"] for dd in dets], "issued": d["issueTimeLocal"],
            "ends": d.get("endTimeLocal") or d["expireTimeLocal"], "text": d["texts"][0]["description"], "frames": {}}
    for name, fr in FRAMES.items():
        w, h, z = fr["w"], fr["h"], fr["zoom"]
        cx, cy = world(fr["lat0"], fr["lon0"], z)
        s = 512 * 2 ** z
        proj = lambda la, lo: [round(world(la, lo, z)[0] - cx + w / 2, 1), round(world(la, lo, z)[1] - cy + h / 2, 1)]
        # land-masked warning area at 2x
        sc = 2
        xs = cx - w / 2 + (np.arange(w * sc) + .5) / sc
        ys = cy - h / 2 + (np.arange(h * sc) + .5) / sc
        LON, LAT = np.meshgrid(xs / s * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s)))))
        tz = 11
        wx = (LON + 180) / 360 * 256 * 2 ** tz
        wy = (1 - np.log(np.tan(np.pi / 4 + np.radians(LAT) / 2)) / np.pi) / 2 * 256 * 2 ** tz
        tx0, ty0, tx1, ty1 = int(wx.min() // 256), int(wy.min() // 256), int(wx.max() // 256), int(wy.max() // 256)
        m = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                try:
                    png = get(f"https://api.mapbox.com/v4/mapbox.terrain-rgb/{tz}/{tx}/{ty}.pngraw?access_token={tok}")
                except urllib.error.HTTPError:
                    continue
                rgb = imread(io.BytesIO(png), format="png")[..., :3] * 255
                m[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = -10000 + (rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]) * .1
        land = map_coordinates(m, [wy - ty0 * 256, wx - tx0 * 256], order=0) > 0.5
        pts = np.column_stack([LON.ravel(), LAT.ravel()])
        inside = np.any([pp.contains_points(pts) for pp in polys], axis=0).reshape(LON.shape) & land
        rgba = np.zeros(LON.shape + (4,))
        rgba[inside, :3] = [0.96, 0.78, 0.12]
        rgba[inside, 3] = 0.55
        imsave(os.path.join(HERE, f"alert-{name}.png"), rgba)
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig, ax = plt.subplots(); cs = ax.contour(gaussian_filter(inside.astype(float), 1.0), levels=[.5])
        outline = "".join("M" + "L".join(f"{x / sc:.1f},{y / sc:.1f}" for x, y in pp[::2]) for p in cs.get_paths()
                          for pp in p.to_polygons(closed_only=False) if len(pp) > 12)
        plt.close(fig)
        tch = "".join("M" + "L".join("%.1f,%.1f" % tuple(proj(y, x)) for x, y in (ft["geometry"]["coordinates"] if ft["geometry"]["type"] == "LineString" else [])) for ft in roads)
        tch += "".join("M" + "L".join("%.1f,%.1f" % tuple(proj(y, x)) for x, y in line) for ft in roads
                       if ft["geometry"]["type"] == "MultiLineString" for line in ft["geometry"]["coordinates"])
        data["frames"][name] = {"outline": outline, "tch": tch, "towns": {n: proj(*ll) for n, ll in TOWNS.items()}}
        imsave(os.path.join(HERE, f"map-{name}.png"), basemap(fr, tok))
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.WH = " + json.dumps(data) + ";\n")
    print(data["event"], data["issued"], "->", data["ends"]); print({k: v["towns"] for k, v in data["frames"].items()})


if __name__ == "__main__":
    main(sys.argv[1])
