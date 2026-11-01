"""Build a "future radar" loop for Newfoundland from HRDPS (MSC GeoMet).

For each forecast hour, pulls HRDPS 1-hour rain, snow, freezing rain and ice
pellet amounts as raw grids (WCS), works out precipitation type and intensity
for every pixel, and paints it with the same 12-colour palette as the real
radar loop (graphics/radar-loop), so the two read as a set.

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
from matplotlib.image import imsave
from scipy.ndimage import gaussian_filter, map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
GEOMET = "https://geo.weather.gc.ca/geomet"
W, H = 1080, 860                          # same frame as the radar loop
LON0, LAT0, ZOOM = -56.35, 49.25, 6.22
NDT = timezone(timedelta(hours=-2, minutes=-30))
BOX = dict(lat=(46.0, 52.6), lon=(-61.8, -50.8))
TOWNS = {  # same towns as the radar loop
    "St. John's": (47.561, -52.713), "Clarenville": (48.165, -53.965), "Gander": (48.954, -54.609),
    "Grand Falls-Windsor": (48.936, -55.660), "Corner Brook": (48.951, -57.952),
    "Deer Lake": (49.174, -57.426), "Stephenville": (48.550, -58.581),
    "Port aux Basques": (47.572, -59.136), "St. Anthony": (51.364, -55.580),
    "Marystown": (47.166, -55.148), "Bonavista": (48.650, -53.115), "Burgeo": (47.617, -57.621),
}
KINDS = ["RN", "SN", "FR", "PE"]          # rain, snow, freezing rain, ice pellets (mm in the hour)

# Same Sheerr colours as the radar loop: (colour, label)
PALETTE = {
    "rain": ["#9FD58E", "#4CAA52", "#1F7333"], "mix": ["#E6CDEB", "#B57BCB", "#7E3E9E"],
    "snow": ["#C6E6F8", "#5AAEE3", "#2160B0"], "freezing": ["#F4A3B5", "#D7263D", "#D7263D"],
}
# light / moderate / heavy break points in mm per hour (liquid equivalent)
BREAKS = {"rain": (0.2, 1.0, 4.0), "mix": (0.15, 0.7, 2.5), "snow": (0.1, 0.5, 1.5), "freezing": (0.1, 1.0, 99)}


def fetch(url, tries=5):
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def latest_run():
    caps = fetch(f"{GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer=HRDPS.CONTINENTAL.DIAG_PR_PT1H").decode()
    ref = re.search(r'<Dimension name="reference_time"[^>]*default="([^"]+)"', caps).group(1)
    times = re.search(r'<Dimension name="time"[^>]*>([^<]+)</Dimension>', caps).group(1).split("/")
    return ref, datetime.fromisoformat(times[1].replace("Z", "+00:00"))


def grid(kind, run, valid):
    url = (f"{GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId=HRDPS.CONTINENTAL.DIAG_{kind}_PT1H"
           f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat({BOX['lat'][0]},{BOX['lat'][1]})"
           f"&subset=lon({BOX['lon'][0]},{BOX['lon'][1]})&resolution=lat(0.02)&resolution=lon(0.03)"
           f"&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    body = fetch(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    a = np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"]))
    return np.clip(a, 0, None), hdr


def frame_lonlat(scale):
    cx = (LON0 + 180) / 360 * 512 * 2 ** ZOOM
    cy = (1 - math.log(math.tan(math.pi / 4 + math.radians(LAT0) / 2)) / math.pi) / 2 * 512 * 2 ** ZOOM
    s = 512 * 2 ** ZOOM
    xs = (cx - W / 2) + (np.arange(W * scale) + 0.5) / scale
    ys = (cy - H / 2) + (np.arange(H * scale) + 0.5) / scale
    return np.meshgrid(xs / s * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s)))))


def town_xy(lat, lon):
    s = 512 * 2 ** ZOOM
    px = lambda la, lo: ((lo + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(la) / 2)) / math.pi) / 2 * s)
    (x, y), (cx, cy) = px(lat, lon), px(LAT0, LON0)
    return [round(x - cx + W / 2), round(y - cy + H / 2)]


def paint(fields, hdr, LON, LAT):
    """Type + intensity for every frame pixel -> RGBA."""
    top = hdr["yllcorner"] + hdr["nrows"] * hdr["dy"]
    rows = (top - LAT) / hdr["dy"] - 0.5
    cols = (LON - hdr["xllcorner"]) / hdr["dx"] - 0.5
    f = {k: map_coordinates(gaussian_filter(v, 0.8), [rows, cols], order=1) for k, v in fields.items()}
    total = f["RN"] + f["SN"] + f["FR"] + f["PE"]
    snowfrac = (f["SN"] + f["PE"]) / np.maximum(total, 1e-6)
    kind = np.where(f["FR"] > 0.3 * total, "freezing",
                    np.where(snowfrac > 0.75, "snow", np.where(snowfrac < 0.25, "rain", "mix")))
    rgba = np.zeros(total.shape + (4,))
    for k, (b0, b1, b2) in BREAKS.items():
        for lvl, (lo, hi) in enumerate([(b0, b1), (b1, b2), (b2, 1e9)]):
            sel = (kind == k) & (total >= lo) & (total < hi)
            c = PALETTE[k][lvl]
            rgba[sel, :3] = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            rgba[sel, 3] = 0.9
    return rgba


def main(hours=24):
    hours = int(hours)
    run, last = latest_run()
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    times = [now + timedelta(hours=h) for h in range(hours) if now + timedelta(hours=h) <= last]
    os.makedirs(os.path.join(HERE, "frames"), exist_ok=True)
    for f in os.listdir(os.path.join(HERE, "frames")):
        os.remove(os.path.join(HERE, "frames", f))
    LON, LAT = frame_lonlat(2)

    def one(i_t):
        i, t = i_t
        iso = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        fields, hdr = {}, None
        for k in KINDS:
            fields[k], hdr = grid(k, run, iso)
        imsave(os.path.join(HERE, "frames", f"{i:02d}.png"), paint(fields, hdr, LON, LAT))
        return i

    with ThreadPoolExecutor(3) as ex:
        list(ex.map(one, enumerate(times)))

    with open(os.path.join(HERE, "map.png"), "wb") as f:
        f.write(fetch(f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM},0/{W}x{H}@2x"
                      f"?attribution=false&logo=false&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"))
    run_t = datetime.fromisoformat(run.replace("Z", "+00:00"))
    data = {
        "times": [t.astimezone(NDT).strftime("%a %-I:%M %p") for t in times],
        "date": f"{times[0].astimezone(NDT):%A %-I:%M %p} to {times[-1].astimezone(NDT):%A %-I:%M %p} NDT",
        "run": f"HRDPS {run_t:%HZ} run {run_t:%b %-d}",
        "towns": {n: town_xy(*ll) for n, ll in TOWNS.items()},
        "classes": [[PALETTE[k][i], f"{['Light', 'Moderate', 'Heavy'][i]} {k}"] for k in ("rain", "mix", "snow") for i in range(3)]
                   + [[PALETTE["freezing"][0], "Light freezing rain"], [PALETTE["freezing"][1], "Freezing rain"]],
    }
    with open(os.path.join(HERE, "frames.js"), "w") as f:
        f.write("// generated by build.py\nwindow.LOOP = " + json.dumps(data) + ";\n")
    print(len(times), "frames", data["date"], "|", data["run"])


if __name__ == "__main__":
    main(*sys.argv[1:2])
