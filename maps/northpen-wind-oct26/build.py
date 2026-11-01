"""Northern Peninsula East Wind Warning graphic (Mon Oct 26) (social 4:5 + broadcast 1920x1080).
Made from the graphics/southcoast-oct23 template.

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
from scipy.ndimage import distance_transform_edt, gaussian_filter, map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
PROBES = ["51.36,-55.58", "50.87,-56.12", "51.18,-56.01", "50.73,-56.11", "51.60,-55.90"]   # St. Anthony, Roddickton, Main Brook, Englee, Raleigh
FRAMES = {"social": dict(w=1080, h=700, lon0=-56.30, lat0=51.02, zoom=7.75),
          "tv": dict(w=1920, h=1080, lon0=-55.25, lat0=51.00, zoom=8.15)}
TOWNS = {"St. Anthony": (51.364, -55.580), "Roddickton": (50.866, -56.125), "Englee": (50.725, -56.108),
         "Main Brook": (51.183, -56.011), "Conche": (50.887, -55.894), "Raleigh": (51.565, -55.725),
         "Flower's Cove": (51.298, -56.735), "Port au Choix": (50.711, -57.336), "L'Anse au Loup": (51.523, -56.830)}
ZONE_LABEL = {"Northern Peninsula East": "Northern Peninsula East"}
EVENTS = {"wind": dict(match="Warning - Wind", fill=[0.96, 0.78, 0.12], alpha=0.55, sfx=""),
          "sws": dict(match="Special Weather Statement", fill=[0.42, 0.47, 0.49], alpha=0.40, sfx="-sws")}


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
            for L in (None, "settlement-major-label", "settlement-minor-label", "country-label", "state-label",
                      "natural-point-label")]
    st = np.stack(imgs)                                              # 3,h,w,3
    sat = st.max(-1) - st.min(-1)
    sat[0] += 0.02                                                   # ties go to the unfiltered map
    pick = np.argmax(sat, axis=0)
    return np.take_along_axis(st, pick[None, ..., None].repeat(3, -1), 0)[0]


def basemap_light(fr, tok):
    """light-v11 (white/grey, the house SWS look) with place labels removed: per pixel keep the candidate closest to
    a wide median of the map tone, so thin label strokes and halos drop out."""
    from scipy.ndimage import median_filter
    url = (f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{fr['lon0']},{fr['lat0']},{fr['zoom'] - 1:.3f},0/"
           f"{fr['w'] // 2}x{fr['h'] // 2}@2x?attribution=false&logo=false&access_token={tok}")
    hide = '&layer_id={}&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D'
    st = np.stack([imread(io.BytesIO(get(url + (hide.format(L) if L else ""))), format="png")[..., :3]
                   for L in (None, "state-label", "country-label", "settlement-major-label", "settlement-minor-label",
                             "natural-point-label")])
    g = st.mean(-1)
    bg = median_filter(g.min(0), size=17)
    pick = np.argmin(np.abs(g - bg[None]), axis=0)
    return np.take_along_axis(st, pick[None, ..., None].repeat(3, -1), 0)[0]


def main(roads_path, kind="wind"):
    ev = EVENTS[kind]
    key = os.environ["TWC_API_KEY"]
    alerts = {}
    for pr in PROBES:
        body = get(f"https://api.weather.com/v3/alerts/headlines?geocode={pr}&format=json&language=en-CA&apiKey={key}")
        for x in (json.loads(body)["alerts"] if body.strip() else []):        # empty body: no alerts at that point
            if x["eventDescription"].endswith(ev["match"]):
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
        tz = 9                                                   # land mask tiles (coarser: big south-coast frame)
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
        zin = [pp.contains_points(pts).reshape(LON.shape) & land for pp in polys]        # one land mask per EC zone
        inside = np.any(zin, axis=0)
        rgba = np.zeros(LON.shape + (4,))
        rgba[inside, :3] = ev["fill"]
        rgba[inside, 3] = ev["alpha"]
        imsave(os.path.join(HERE, f"alert-{name}{ev['sfx']}.png"), rgba)
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig, ax = plt.subplots(); cs = ax.contour(gaussian_filter(inside.astype(float), 1.0), levels=[.5])
        outline = "".join("M" + "L".join(f"{x / sc:.1f},{y / sc:.1f}" for x, y in pp[::2]) for p in cs.get_paths()
                          for pp in p.to_polygons(closed_only=False) if len(pp) > 12)
        # zone boundaries (drawn dashed inside the area) and a label anchor at each zone's widest land point
        zones = []
        for dd, zm in zip(dets, zin):
            if zm.sum() < 400 * sc * sc:
                continue
            cz = ax.contour(gaussian_filter(zm.astype(float), 1.0), levels=[.5])
            zp = "".join("M" + "L".join(f"{x / sc:.1f},{y / sc:.1f}" for x, y in pp[::2]) for p in cz.get_paths()
                         for pp in p.to_polygons(closed_only=False) if len(pp) > 12)
            dt = distance_transform_edt(zm)
            dt[:, :int(w * sc * .04)] = 0; dt[:, -int(w * sc * .04):] = 0; dt[:int(h * sc * .06)] = 0; dt[-int(h * sc * .06):] = 0
            iy, ix = np.unravel_index(np.argmax(dt), dt.shape)
            zones.append({"name": ZONE_LABEL.get(dd["areaName"], dd["areaName"]), "path": zp, "at": [round(ix / sc, 1), round(iy / sc, 1)]})
        plt.close(fig)
        tch = "".join("M" + "L".join("%.1f,%.1f" % tuple(proj(y, x)) for x, y in (ft["geometry"]["coordinates"] if ft["geometry"]["type"] == "LineString" else [])) for ft in roads)
        tch += "".join("M" + "L".join("%.1f,%.1f" % tuple(proj(y, x)) for x, y in line) for ft in roads
                       if ft["geometry"]["type"] == "MultiLineString" for line in ft["geometry"]["coordinates"])
        data["frames"][name] = {"outline": outline, "zones": zones, "tch": tch, "towns": {n: proj(*ll) for n, ll in TOWNS.items()}}
        light = kind == "sws"                                            # SWS: white/grey map; warnings: outdoors
        mp = os.path.join(HERE, f"map-{name}{'-light' if light else ''}.png")
        if not os.path.exists(mp):
            imsave(mp, basemap_light(fr, tok) if light else basemap(fr, tok))
    with open(os.path.join(HERE, f"data{ev['sfx']}.js"), "w") as f:
        f.write("// generated by build.py\nwindow.WH = " + json.dumps(data) + ";\n")
    print(data["event"], data["issued"], "->", data["ends"]); print({k: v["towns"] for k, v in data["frames"].items()})


if __name__ == "__main__":
    main(*sys.argv[1:3])
