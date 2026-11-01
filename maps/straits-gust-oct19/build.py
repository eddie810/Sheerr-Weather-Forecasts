"""Peak wind gusts Monday daytime, Port Saunders and the Straits (Oct 19), on the same frames as the wind warning
graphics (../straits-wind-oct19). HRDPS 2.5 km gusts (MSC GeoMet WCS, HRDPS-WEonG_2.5km_WindGust, m/s), highest
hourly value over the window, shaded on land only. Writes gust-{social,tv}.png and data.js.

  MAPBOX_ACCESS_TOKEN=... python3 build.py [start_utc] [end_utc]      (default Mon 12Z -> Tue 00Z)
"""
import importlib.util
import io
import json
import os
import re
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone

import numpy as np
from matplotlib.image import imread, imsave
from scipy.ndimage import gaussian_filter, map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("warn", os.path.join(HERE, "..", "straits-wind-oct19", "build.py"))
warn = importlib.util.module_from_spec(spec); spec.loader.exec_module(warn)
GEOMET = "https://geo.weather.gc.ca/geomet"
LAYER = "HRDPS-WEonG_2.5km_WindGust"
NDT = timezone(timedelta(hours=-2, minutes=-30))
BANDS = [(40, "#FFF1B8"), (50, "#FFDD7A"), (60, "#FDBD4F"), (70, "#F79A3E"), (80, "#EE7136"),
         (90, "#DC4A33"), (100, "#B8303F"), (120, "#8C2452"), (140, "#5E1F5E")]
BOX = dict(lat=(49.6, 52.6), lon=(-59.6, -54.0))


def get(url, tries=5):
    for n in range(tries):
        try:
            return warn.get(url)
        except urllib.error.HTTPError:
            raise
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def grid(run, valid):
    url = (f"{GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={LAYER}"
           f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat({BOX['lat'][0]},{BOX['lat'][1]})"
           f"&subset=lon({BOX['lon'][0]},{BOX['lon'][1]})&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    body = get(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    return np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"])), hdr


def land_mask(LON, LAT, tok):
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
                continue                                                     # 404: open water
            rgb = imread(io.BytesIO(png), format="png")[..., :3] * 255
            m[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = \
                -10000 + (rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]) * .1
    return map_coordinates(m, [wy - ty0 * 256, wx - tx0 * 256], order=0) > 0.5


def main(start="2026-10-19T12:00:00Z", end="2026-10-20T00:00:00Z"):
    caps = get(f"{GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer={LAYER}").decode()
    run = re.search(r'<Dimension name="reference_time"[^>]*default="([^"]+)"', caps).group(1)
    t, t1 = (datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (start, end))
    peak, when, hdr = None, None, None
    while t <= t1:
        a, hdr = grid(run, t.strftime("%Y-%m-%dT%H:%M:%SZ"))
        a = a * 3.6
        if peak is None:
            peak, when = a, np.full(a.shape, t.timestamp())
        else:
            when = np.where(a > peak, t.timestamp(), when); peak = np.maximum(peak, a)
        t += timedelta(hours=1)
    sm = gaussian_filter(peak, 0.7)
    top = hdr["yllcorner"] + hdr["nrows"] * hdr["dy"]
    rc = lambda la, lo: [(top - la) / hdr["dy"] - .5, (lo - hdr["xllcorner"]) / hdr["dx"] - .5]
    towns = {}
    for n, (la, lo) in warn.TOWNS.items():
        r, c = rc(la, lo)
        g = round(float(map_coordinates(sm, [[r], [c]], order=1)[0]))
        tw = datetime.fromtimestamp(float(when[int(round(r)), int(round(c))]), timezone.utc).astimezone(NDT)
        towns[n] = {"gust": g, "peak": tw.strftime("%-I %p").replace("AM", "a.m.").replace("PM", "p.m.")}
    warn_data = json.loads(open(os.path.join(HERE, "..", "straits-wind-oct19", "data.js")).read().split("=", 1)[1].rstrip().rstrip(";"))
    data = {"run": run, "from": datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(NDT).strftime("%a %-I:%M %p"),
            "to": datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(NDT).strftime("%a %-I:%M %p NDT"),
            "bands": BANDS, "towns": towns, "frames": {}, "ends": warn_data["ends"]}
    tok = os.environ["MAPBOX_ACCESS_TOKEN"]
    for name, fr in warn.FRAMES.items():
        w, h, z = fr["w"], fr["h"], fr["zoom"]
        cx, cy = warn.world(fr["lat0"], fr["lon0"], z)
        s = 512 * 2 ** z
        sc = 2
        xs = cx - w / 2 + (np.arange(w * sc) + .5) / sc
        ys = cy - h / 2 + (np.arange(h * sc) + .5) / sc
        LON, LAT = np.meshgrid(xs / s * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s)))))
        v = map_coordinates(sm, rc(LAT, LON), order=1, mode="nearest")
        land = land_mask(LON, LAT, tok)
        rgba = np.zeros(v.shape + (4,))
        for lo, col in BANDS:
            sel = v >= lo
            rgba[sel, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            rgba[sel, 3] = 0.72
        rgba[..., 3] *= land
        imsave(os.path.join(HERE, f"gust-{name}.png"), rgba)
        proj = lambda la, lo: [round(warn.world(la, lo, z)[0] - cx + w / 2, 1), round(warn.world(la, lo, z)[1] - cy + h / 2, 1)]
        data["frames"][name] = {"towns": {n: proj(*ll) for n, ll in warn.TOWNS.items()},
                                "outline": warn_data["frames"][name]["outline"],
                                "max": round(float(v[land].max()))}
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.GU = " + json.dumps(data) + ";\n")
    print(run, data["from"], "->", data["to"], "land max", data["frames"]["social"]["max"])
    for n, t in sorted(towns.items(), key=lambda x: -x[1]["gust"]):
        print(f"  {n:16s} {t['gust']:4d} km/h  peak {t['peak']}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
