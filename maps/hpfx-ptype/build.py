"""Radar precipitation-type loop from EC's HPFX server (private data: credentials from HPFX_USER / HPFX_PASS).

Fetches the last N 6-minute frames of the 1 km surface precipitation-type composite (sptp), reprojects them to a
Mapbox Web-Mercator frame, smooths the class edges, and writes pt-NNN.png, map.png and data.js for index.html.
Outputs are git-ignored (private data).

  HPFX_USER=... HPFX_PASS=... MAPBOX_ACCESS_TOKEN=... python3 build.py [lon] [lat] [zoom] [frames] [place]
  e.g. python3 build.py -67.8 48.6 6.3 20 "Lower St. Lawrence & Gaspé"
"""
import base64
import io
import json
import math
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
import rasterio
from matplotlib.image import imsave
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject
from scipy.ndimage import median_filter

HERE = os.path.dirname(os.path.abspath(__file__))
HPFX = "https://hpfx.collab.science.gc.ca"
W, H = 1920, 1080
# EC sptp codes -> (label, colour); 510/520 inferred from the code pattern
CLASSES = [(110, "Light snow", "#7FDDEA"), (120, "Moderate snow", "#3E9BEA"), (130, "Heavy snow", "#1B3FD0"),
           (210, "Light mix", "#E6C4EE"), (220, "Moderate mix", "#C46AD4"), (230, "Heavy mix", "#8E1FA6"),
           (310, "Light rain", "#9BE38F"), (320, "Moderate rain", "#2DB84A"), (330, "Heavy rain", "#0E7A2E"),
           (410, "Hail / rain", "#F2C230"), (510, "Light freezing rain", "#F7A6B4"), (520, "Freezing rain", "#E0234B")]


def get(url, auth=None, tries=5):
    req = urllib.request.Request(url)
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    for k in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 ** (k + 1))


def world(lat, lon, z):
    s = 512 * 2 ** z
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def main(lon0=-67.8, lat0=48.6, zoom=6.3, nframes=20, place="Lower St. Lawrence & Gaspé"):
    lon0, lat0, zoom, nframes = float(lon0), float(lat0), float(zoom), int(nframes)
    auth = f"{os.environ['HPFX_USER']}:{os.environ['HPFX_PASS']}"
    now = datetime.now(timezone.utc)
    files = []
    for day in sorted({(now - timedelta(hours=h)).strftime("%Y%m%d") for h in (0, 3)}):
        idx = get(f"{HPFX}/{day}/radar/sptp/", auth).decode()
        files += [f"{day}/radar/sptp/{f}" for f in re.findall(r'href="([^"?/]*SfcPrecipType_1km\.tif)"', idx)]
    files = sorted(set(files), key=lambda p: p.rsplit("/", 1)[1])[-nframes:]
    # Mercator frame
    s = 512 * 2 ** zoom
    cx, cy = world(lat0, lon0, zoom)
    x0, y0 = cx - W / 2, cy - H / 2
    to_lon = lambda x: x / s * 360 - 180
    to_lat = lambda y: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / s))))
    W3857 = lambda lon: lon * 20037508.34 / 180
    N3857 = lambda lat: math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 20037508.34 / math.pi
    bounds = (W3857(to_lon(x0)), N3857(to_lat(y0 + H)), W3857(to_lon(x0 + W)), N3857(to_lat(y0)))
    sc = 2
    dst_t = from_bounds(*bounds, W * sc, H * sc)
    lut = {v: i for i, (v, _, _) in enumerate(CLASSES)}
    rgb = np.array([[int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)] for _, _, c in CLASSES])
    frames = []
    for k, p in enumerate(files):
        with rasterio.open(io.BytesIO(get(f"{HPFX}/{p}", auth))) as r:
            dst = np.full((H * sc, W * sc), -999, np.float32)
            reproject(r.read(1), dst, src_transform=r.transform, src_crs=r.crs, dst_transform=dst_t, dst_crs="EPSG:3857",
                      resampling=Resampling.nearest, src_nodata=-999, dst_nodata=-999)
        cls = np.full(dst.shape, -1, int)
        for v, i in lut.items():
            cls[dst == v] = i
        cls = median_filter(cls, size=5)                       # round off the 1 km pixel steps
        rgba = np.zeros(dst.shape + (4,))
        m = cls >= 0
        rgba[m, :3] = rgb[cls[m]]
        rgba[m, 3] = 0.9
        imsave(os.path.join(HERE, f"pt-{k:03d}.png"), rgba)
        t = datetime.strptime(p.rsplit("/", 1)[1][:14], "%Y%m%dT%H%MZ").replace(tzinfo=timezone.utc)
        frames.append({"png": f"pt-{k:03d}.png", "utc": t.isoformat(), "counts": {CLASSES[i][1]: int((cls == i).sum()) for i in range(len(CLASSES)) if (cls == i).any()}})
        print(k, p.rsplit("/", 1)[1], frames[-1]["counts"], flush=True)
    # house white/grey basemap with Mapbox place labels removed (same helper as the SWS maps); we draw our own towns
    import importlib.util
    spec = importlib.util.spec_from_file_location("sc", os.path.join(HERE, "..", "southcoast-oct23", "build.py"))
    sc_mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc_mod)
    imsave(os.path.join(HERE, "map.png"), sc_mod.basemap_light(dict(w=W, h=H, lon0=lon0, lat0=lat0, zoom=zoom), os.environ["MAPBOX_ACCESS_TOKEN"]))
    towns = {"Rimouski": (48.449, -68.524), "Matane": (48.843, -67.531), "Baie-Comeau": (49.217, -68.150), "Sept-Îles": (50.210, -66.381),
             "Gaspé": (48.832, -64.486), "Québec": (46.813, -71.208), "Saguenay": (48.428, -71.068), "Campbellton": (48.005, -66.673),
             "Edmundston": (47.373, -68.325), "Rivière-du-Loup": (47.830, -69.536), "Bathurst": (47.618, -65.651)}
    proj = lambda la, lo: [round(world(la, lo, zoom)[0] - x0), round(world(la, lo, zoom)[1] - y0)]
    data = {"place": place, "frames": frames, "classes": [[l, c] for _, l, c in CLASSES],
            "towns": {n: proj(*ll) for n, ll in towns.items() if 30 < proj(*ll)[0] < W - 30 and 30 < proj(*ll)[1] < H - 30}}
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.PT = " + json.dumps(data) + ";\n")


if __name__ == "__main__":
    main(*sys.argv[1:6])
