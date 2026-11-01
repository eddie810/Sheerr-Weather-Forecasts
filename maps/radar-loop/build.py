"""Build a 3-hour radar loop for Newfoundland from Environment Canada radar (MSC GeoMet).

GeoMet serves radar only as images, so each frame is the surface precipitation-type
layer (fixed colours for rain/mix/snow/freezing rain x intensity), recoloured pixel by
pixel into the Sheerr palette. Writes frames/*.png, coverage.png, map.png and
frames.js for loop.html; render.js then screenshots each frame.

  MAPBOX_ACCESS_TOKEN=... python3 build.py [hours]
"""
import json
import math
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
from matplotlib.image import imread, imsave

HERE = os.path.dirname(os.path.abspath(__file__))
GEOMET = "https://geo.weather.gc.ca/geomet"
W, H = 1080, 860                          # map frame (CSS px)
LON0, LAT0, ZOOM = -56.35, 49.25, 6.22
NDT = timezone(timedelta(hours=-2, minutes=-30))

# Radar_1km_SfcPrecipType classes: GeoMet colour -> (Sheerr colour, label).
# One layer gives both precipitation type and intensity, so rain and snow are never confused.
PTYPE = [
    ("#9AFD9A", "#9FD58E", "Light rain"), ("#00CB00", "#4CAA52", "Moderate rain"), ("#008000", "#1F7333", "Heavy rain"),
    ("#E0BDE6", "#E6CDEB", "Light mix"), ("#C36DD2", "#B57BCB", "Moderate mix"), ("#9B27AF", "#7E3E9E", "Heavy mix"),
    ("#7FDFEB", "#C6E6F8", "Light snow"), ("#47A4F0", "#5AAEE3", "Moderate snow"), ("#0000E0", "#2160B0", "Heavy snow"),
    ("#FECBC8", "#F4A3B5", "Light freezing rain"), ("#FE1E0D", "#D7263D", "Freezing rain"),
    ("#FEC007", "#F2B630", "Hail / rain"),
]
LAYER = "Radar_1km_SfcPrecipType"

TOWNS = {
    "St. John's": (47.561, -52.713), "Clarenville": (48.165, -53.965), "Gander": (48.954, -54.609),
    "Grand Falls-Windsor": (48.936, -55.660), "Corner Brook": (48.951, -57.952),
    "Deer Lake": (49.174, -57.426), "Stephenville": (48.550, -58.581),
    "Port aux Basques": (47.572, -59.136), "St. Anthony": (51.364, -55.580),
    "Marystown": (47.166, -55.148), "Bonavista": (48.650, -53.115), "Burgeo": (47.617, -57.621),
}


def merc(lat, lon):
    r = 6378137.0
    return r * math.radians(lon), r * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def frame_bbox():
    """EPSG:3857 bbox of the Mapbox frame (512px tiles at ZOOM)."""
    mpp = 2 * math.pi * 6378137.0 / (512 * 2 ** ZOOM)
    cx, cy = merc(LAT0, LON0)
    return cx - W / 2 * mpp, cy - H / 2 * mpp, cx + W / 2 * mpp, cy + H / 2 * mpp


def projector():
    x0, y0, x1, y1 = frame_bbox()
    return lambda la, lo: ((merc(la, lo)[0] - x0) / (x1 - x0) * W, (y1 - merc(la, lo)[1]) / (y1 - y0) * H)


def get(url, path, tries=4):
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read()
            with open(path, "wb") as f:
                f.write(data)
            return
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def getmap(layer, style, when, path, scale=2):
    b = ",".join(f"{v:.1f}" for v in frame_bbox())
    url = (f"{GEOMET}?service=WMS&version=1.3.0&request=GetMap&layers={layer}&styles={style}"
           f"&crs=EPSG:3857&bbox={b}&width={W * scale}&height={H * scale}&format=image/png&transparent=true")
    if when:
        url += f"&time={when}"
    get(url, path)


def radar_times(hours):
    caps = os.path.join(HERE, "_caps.xml")
    get(f"{GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer={LAYER}", caps)
    with open(caps) as f:
        dim = re.search(r'<Dimension name="time"[^>]*>([^<]+)</Dimension>', f.read()).group(1)
    os.remove(caps)
    start, end, _ = dim.split("/")
    end = datetime.fromisoformat(end.replace("Z", "+00:00"))
    start = max(datetime.fromisoformat(start.replace("Z", "+00:00")), end - timedelta(hours=hours))
    t, out = start, []
    while t <= end:
        out.append(t)
        t += timedelta(minutes=6)
    return out


def hex2rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float)


def recolour(path):
    """Map GeoMet's precip-type class colours to the Sheerr palette; returns RGBA float array."""
    a = imread(path)
    if a.shape[2] == 3:
        a = np.dstack([a, np.ones(a.shape[:2])])
    rgb = a[..., :3] * 255
    src = np.array([hex2rgb(g) for g, _, _ in PTYPE])
    dist = ((rgb[..., None, :] - src[None, None]) ** 2).sum(-1)
    cls = dist.argmin(-1)
    out = np.zeros_like(a)
    out[..., :3] = np.array([hex2rgb(c) for _, c, _ in PTYPE])[cls] / 255
    out[..., 3] = (a[..., 3] > 0.5) & (dist.min(-1) < 60 ** 2)
    return out


def main(hours=3):
    os.makedirs(os.path.join(HERE, "frames"), exist_ok=True)
    times = radar_times(float(hours))
    get(f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM},0/{W}x{H}@2x"
        f"?attribution=false&logo=false&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}",
        os.path.join(HERE, "map.png"))
    getmap("RADAR_COVERAGE_RRAI.INV", "", times[-1].strftime("%Y-%m-%dT%H:%M:%SZ"), os.path.join(HERE, "coverage.png"))

    tmp = os.path.join(HERE, "frames", "_raw")
    os.makedirs(tmp, exist_ok=True)

    def one(i_t):
        i, t = i_t
        out = os.path.join(HERE, "frames", f"{i:02d}.png")
        if os.path.exists(out):
            return i
        iso = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        raw = os.path.join(tmp, f"{i:02d}.png")
        getmap(LAYER, "", iso, raw)
        with open(raw, "rb") as f:
            if f.read(4) != b"\x89PNG":     # GeoMet answered with an XML error (frame not published)
                return None
        imsave(out, recolour(raw))
        return i

    with ThreadPoolExecutor(3) as ex:
        ok = list(ex.map(one, enumerate(times)))
    # keep only frames that came back, renumbered so the loop has no gaps
    kept = [t for t, r in zip(times, ok) if r is not None]
    for new, old in enumerate(r for r in ok if r is not None):
        if new != old:
            os.replace(os.path.join(HERE, "frames", f"{old:02d}.png"), os.path.join(HERE, "frames", f"{new:02d}.png"))
    times = kept
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)

    proj = projector()
    data = {
        "times": [t.astimezone(NDT).strftime("%-I:%M %p") + " NDT" for t in times],
        "date": times[-1].astimezone(NDT).strftime("%A, %B %-d"),
        "towns": {n: [round(v) for v in proj(*ll)] for n, ll in TOWNS.items()},
        "classes": [[c, label] for _, c, label in PTYPE],
    }
    with open(os.path.join(HERE, "frames.js"), "w") as f:
        f.write("// generated by build.py\nwindow.LOOP = " + json.dumps(data) + ";\n")
    print(len(times), "frames", data["times"][0], "->", data["times"][-1])


if __name__ == "__main__":
    main(*sys.argv[1:2])
