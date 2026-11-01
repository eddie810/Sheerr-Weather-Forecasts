"""RRFS future radar for Newfoundland & Labrador: precipitation type, MSLP isobars, H/L centres.

NOAA RRFS (parallel, NOMADS) 13 km North America grid, hourly. Per frame, byte-range downloads of just
PRATE (precipitation rate), MSLET and the categorical precip types (CRAIN/CSNOW/CFRZR/CICEP).
Writes frames/NN.png (precip), frames.js (times, isobar paths, H/L), map.png.

  MAPBOX_ACCESS_TOKEN=... python3 build.py RUN FIRST_FH LAST_FH [ne_admin1.geojson]      e.g. 2026101618 7 33 adm1.geojson
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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pygrib  # noqa: E402
from matplotlib.image import imsave  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates, maximum_filter, minimum_filter  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/rrfs/para"
W, H = 1080, 860
LON0, LAT0, ZOOM = -58.6, 49.6, 5.32
NDT = timezone(timedelta(hours=-2, minutes=-30))
TOWNS = {"St. John's": (47.561, -52.713), "Gander": (48.954, -54.609), "Corner Brook": (48.951, -57.952),
         "Port aux Basques": (47.572, -59.136), "St. Anthony": (51.364, -55.580), "Marystown": (47.166, -55.148),
         "Goose Bay": (53.302, -60.417), "Cartwright": (53.708, -57.021), "Labrador City": (52.946, -66.911),
         "Sydney": (46.136, -60.194)}
FIELDS = {"PRATE": ":PRATE:surface:%d hour fcst:", "MSLET": ":MSLET:mean sea level:", "CRAIN": ":CRAIN:surface:",
          "CSNOW": ":CSNOW:surface:", "CFRZR": ":CFRZR:surface:", "CICEP": ":CICEP:surface:"}
PALETTE = {  # same Sheerr radar colours as the HRDPS future radar
    "rain": ["#9FD58E", "#4CAA52", "#1F7333"], "mix": ["#E6CDEB", "#B57BCB", "#7E3E9E"],
    "snow": ["#C6E6F8", "#5AAEE3", "#2160B0"], "freezing": ["#F4A3B5", "#D7263D", "#D7263D"],
}
# light / moderate / heavy break points, mm/h liquid equivalent (same as the HRDPS future radar)
BREAKS = {"rain": (0.2, 1.0, 4.0), "mix": (0.15, 0.7, 2.5), "snow": (0.1, 0.5, 1.5), "freezing": (0.1, 1.0, 99)}


def fetch(url, rng=None, tries=5):
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **({"Range": f"bytes={rng}"} if rng else {})})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def world(lat, lon):
    s = 512 * 2 ** ZOOM
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def px(lat, lon):
    (x, y), (cx, cy) = world(lat, lon), world(LAT0, LON0)
    return [round(x - cx + W / 2, 1), round(y - cy + H / 2, 1)]


def frame_lonlat(scale=1):
    cx, cy = world(LAT0, LON0)
    s = 512 * 2 ** ZOOM
    xs = cx - W / 2 + (np.arange(W * scale) + .5) / scale
    ys = cy - H / 2 + (np.arange(H * scale) + .5) / scale
    return np.meshgrid(xs / s * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s)))))


def get_fields(run, fh):
    url = f"{BASE}/rrfs.{run[:8]}/{run[8:]}/rrfs.t{run[8:]}z.2dfld.13km.f{fh:03d}.na.grib2"
    idx = fetch(url + ".idx").decode().splitlines()
    out = {}
    for k, pat in FIELDS.items():
        pat = pat % fh if "%d" in pat else pat
        i = next(j for j, l in enumerate(idx) if pat in l)
        a = int(idx[i].split(":")[1]); b = int(idx[i + 1].split(":")[1]) - 1
        g = pygrib.fromstring(fetch(url, f"{a}-{b}"))
        out[k] = g.values.filled(np.nan) if hasattr(g.values, "filled") else g.values
        if "latlons" not in out:
            out["latlons"] = g.latlons()
    return out


class Regrid:
    """Inverse-distance interpolation from the rotated RRFS grid to the frame (4 nearest points)."""
    def __init__(self, la, lo, LAT, LON):
        sub = (la > 38) & (la < 62) & (lo > -80) & (lo < -40)
        self.sub = sub

        def xyz(a, b):
            a, b = np.radians(a), np.radians(b)
            return np.column_stack([np.cos(a) * np.cos(b), np.cos(a) * np.sin(b), np.sin(a)])
        d, self.i = cKDTree(xyz(la[sub], lo[sub])).query(xyz(LAT.ravel(), LON.ravel()), k=4)
        w = 1 / np.maximum(d, 1e-9) ** 2
        self.w = w / w.sum(1, keepdims=True)
        self.shape = LAT.shape

    def __call__(self, f):
        return (f[self.sub][self.i] * self.w).sum(1).reshape(self.shape)


def paint(F, rg):
    rate = gaussian_filter(rg(np.nan_to_num(F["PRATE"]) * 3600), 1.2)          # kg m-2 s-1 -> mm/h
    sn, rn, fz, ip = (gaussian_filter(rg(F[k].astype(float)), 2) for k in ("CSNOW", "CRAIN", "CFRZR", "CICEP"))
    kind = np.where(fz > 0.4, "freezing", np.where(ip > 0.4, "mix",
                    np.where((sn > 0.3) & (rn > 0.3), "mix", np.where(sn > rn, "snow", "rain"))))
    rgba = np.zeros(rate.shape + (4,))
    for k, (b0, b1, b2) in BREAKS.items():
        for lvl, (lo, hi) in enumerate([(b0, b1), (b1, b2), (b2, 1e9)]):
            sel = (kind == k) & (rate >= lo) & (rate < hi)
            c = PALETTE[k][lvl]
            rgba[sel, :3] = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            rgba[sel, 3] = 0.88
    return rgba


def isobars(p):
    """4 hPa isobars as SVG paths with label spots, plus H/L centres."""
    fig, ax = plt.subplots()
    lev = np.arange(960, 1048, 4)
    cs = ax.contour(p, levels=lev)
    lines = []
    for lv, path in zip(cs.levels, cs.get_paths()):
        for poly in path.to_polygons(closed_only=False):
            if len(poly) < 40:
                continue
            d = "M" + "L".join(f"{x:.0f},{y:.0f}" for x, y in poly[::3])
            m = poly[len(poly) // 2]
            lab = [round(float(m[0])), round(float(m[1]))] if 40 < m[0] < W - 40 and 40 < m[1] < H - 40 else None
            lines.append({"d": d, "v": int(lv), "lab": lab})
    plt.close(fig)
    centres = []
    for kind, f in (("L", minimum_filter), ("H", maximum_filter)):
        ext = (p == f(p, size=161)) & (np.abs(p - gaussian_filter(p, 60)) > 3.0)
        for y, x in zip(*np.nonzero(ext)):
            if 18 < x < W - 18 and 18 < y < H - 18:
                centres.append({"k": kind, "x": int(x), "y": int(y), "v": int(round(p[y, x]))})
    return lines, centres


def borders(ne_path):
    """Province/state outlines (incl. coastlines) from Natural Earth admin-1, as one SVG path."""
    keep = ("Newfoundland and Labrador", "Québec", "Nova Scotia", "New Brunswick", "Prince Edward Island", "Maine", "Nunavut")
    with open(ne_path) as f:
        feats = [ft for ft in json.load(f)["features"] if ft["properties"].get("name") in keep]
    out = []
    for ft in feats:
        g = ft["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            if len(poly[0]) < 12:
                continue
            pts = [px(la, lo) for lo, la in poly[0]]
            kept = [pts[0]] + [p for a, p in zip(pts, pts[1:]) if abs(p[0] - a[0]) + abs(p[1] - a[1]) >= 1.2]
            if any(-50 < x < W + 50 and -50 < y < H + 50 for x, y in kept):
                out.append("M" + "L".join(f"{x:.0f},{y:.0f}" for x, y in kept) + "Z")
    return "".join(out)


def main(run, f0, f1, ne_path=None):
    f0, f1 = int(f0), int(f1)
    os.makedirs(os.path.join(HERE, "frames"), exist_ok=True)
    for f in os.listdir(os.path.join(HERE, "frames")):
        os.remove(os.path.join(HERE, "frames", f))
    LON, LAT = frame_lonlat(1)
    first = get_fields(run, f0)
    rg = Regrid(*first["latlons"], LAT, LON)
    hours = list(range(f0, f1 + 1))
    with ThreadPoolExecutor(4) as ex:
        allf = list(ex.map(lambda fh: first if fh == f0 else get_fields(run, fh), hours))
    rt = datetime.strptime(run, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    frames = []
    for i, (fh, F) in enumerate(zip(hours, allf)):
        imsave(os.path.join(HERE, "frames", f"{i:02d}.png"), paint(F, rg))
        p = gaussian_filter(rg(F["MSLET"] / 100), 6)
        lines, centres = isobars(p)
        frames.append({"t": (rt + timedelta(hours=fh)).astimezone(NDT).strftime("%a %-I %p"), "iso": lines, "hl": centres})
        print(fh, frames[-1]["t"], [(c["k"], c["v"]) for c in centres])
    with open(os.path.join(HERE, "map.png"), "wb") as f:
        f.write(fetch(f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM - 1:.3f},0/{W // 2}x{H // 2}@2x"
                      f"?attribution=false&logo=false&layer_id=state-label&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D"
                      f"&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"))
    t0, t1 = (rt + timedelta(hours=h) for h in (f0, f1))
    data = {"frames": frames, "run": f"RRFS {rt:%HZ} {rt:%b %-d} (parallel)",
            "date": f"{t0.astimezone(NDT):%A %-I:%M %p} to {t1.astimezone(NDT):%A %-I:%M %p} NDT",
            "towns": {n: px(*ll) for n, ll in TOWNS.items()}, "borders": borders(ne_path) if ne_path else "",
            "classes": [[PALETTE[k][i], k] for k in ("rain", "mix", "snow") for i in range(3)] + [[PALETTE["freezing"][0], "fz"], [PALETTE["freezing"][1], "fz"]]}
    with open(os.path.join(HERE, "frames.js"), "w") as f:
        f.write("// generated by build.py\nwindow.LOOP = " + json.dumps(data) + ";\n")
    print(len(frames), "frames", data["date"])


if __name__ == "__main__":
    main(*sys.argv[1:5])
