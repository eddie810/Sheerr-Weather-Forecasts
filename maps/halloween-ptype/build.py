"""Halloween precip-type story for NL: RDPS hourly precipitation type (rain / mix / snow, from the hourly change in the
Rain, Snow, FreezingRain and IcePellets accumulations), MSLP isobars, tracked low centres and town temperatures,
Saturday Oct 31 6:30 AM to 9:30 PM NDT. Writes pt-{fmt}-{HH}.png (shading per hour), data-{fmt}.js (window.HP).

  python3 build.py data/ne/adm1.geojson [run e.g. 2026-10-28T12:00:00Z] [frames e.g. tv,social,lab]
"""
import json
import math
import os
import re
import sys
import time
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.image import imsave  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates, minimum_filter  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GEOMET = "https://geo.weather.gc.ca/geomet"
BOX = dict(lat=(37.0, 64.0), lon=(-76.0, -34.0))
HOURS = [f"2026-10-31T{h:02d}:00:00Z" for h in range(9, 24)] + ["2026-11-01T00:00:00Z"]   # 6:30 AM .. 9:30 PM NDT
PREV = "2026-10-31T08:00:00Z"
FRAMES = {"tv": dict(w=1920, h=1080, lon0=-58.83, lat0=48.55, zoom=6.10),     # Island right of the text column
          "social": dict(w=1080, h=960, lon0=-55.95, lat0=48.85, zoom=5.98),
          "lab": dict(w=1080, h=960, lon0=-61.6, lat0=55.35, zoom=5.32),
          "labtv": dict(w=1920, h=1080, lon0=-66.6, lat0=55.45, zoom=5.42)}       # Labrador right of the text column
ISLAND_TOWNS = TOWNS = {"St. John's": (47.561, -52.713), "Clarenville": (48.165, -53.965), "Gander": (48.954, -54.609),
         "Grand Falls-Windsor": (48.936, -55.660), "Corner Brook": (48.951, -57.952), "Port aux Basques": (47.572, -59.136),
         "Marystown": (47.166, -55.148), "St. Anthony": (51.364, -55.580), "Burgeo": (47.617, -57.621),
         "Deer Lake": (49.174, -57.426)}
LAB_TOWNS = {"Nain": (56.542, -61.692), "Hopedale": (55.456, -60.209), "Natuashish": (55.913, -61.103), "Makkovik": (55.083, -59.172),
             "Happy Valley-Goose Bay": (53.302, -60.417), "Churchill Falls": (53.528, -63.966), "Labrador City": (52.946, -66.911),
             "Cartwright": (53.708, -57.021), "Port Hope Simpson": (52.540, -56.300), "L'Anse au Loup": (51.523, -56.830), "Rigolet": (54.180, -58.430)}
# colours: rain greens, mix magenta, snow icy blue-white (readable on the dark night map)
RAIN = [(0.2, "#2E8B57"), (1, "#3FBF5A"), (2.5, "#8BE04E"), (5, "#E8F06A"), (10, "#F07A1A")]
MIX = [(0.2, "#B0399F"), (1, "#D957C2"), (2.5, "#F08BE0")]
SNOW = [(0.1, "#3E7CC0"), (0.5, "#6FB3F0"), (1.5, "#A9DBFF"), (3, "#FFFFFF")]


def get(url, tries=5):
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 ** (k + 1))


def grid(run, valid, layer):
    url = (f"{GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={layer}&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326"
           f"&subset=lat({BOX['lat'][0]},{BOX['lat'][1]})&subset=lon({BOX['lon'][0]},{BOX['lon'][1]})"
           f"&resolution=lat(0.1)&resolution=lon(0.1)&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    body = get(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    a = np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"]))
    dy, dx = hdr.get("dy", hdr.get("cellsize")), hdr.get("dx", hdr.get("cellsize"))
    lats = hdr["yllcorner"] + (hdr["nrows"] - np.arange(a.shape[0]) - 0.5) * dy
    lons = hdr["xllcorner"] + (np.arange(a.shape[1]) + 0.5) * dx
    return lons, lats, a


def world(lat, lon, z):
    s = 512 * 2 ** z
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def colour(v, ramp):
    out = np.zeros(v.shape + (4,))
    for lo, c in ramp:
        sel = v >= lo
        out[sel, :3] = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        out[sel, 3] = 0.82
    return out


def main(ne_path, run="2026-10-28T12:00:00Z", only=None):
    global TOWNS
    frames_wanted = only.split(",") if only else list(FRAMES)
    acc = {}
    for t in [PREV] + HOURS:
        acc[t] = {k: grid(run, t, f"RDPS_10km_{l}-Accum")[2] for k, l in
                  (("r", "Rain"), ("s", "Snow"), ("z", "FreezingRain"), ("i", "IcePellets"))}
        print("accum", t, flush=True)
    lons, lats, _ = grid(run, PREV, "RDPS_10km_Rain-Accum")
    P = {t: grid(run, t, "RDPS_10km_Pressure_MSL")[2] for t in HOURS}
    P = {t: (a / 100 if a.max() > 2000 else a) for t, a in P.items()}
    TT = {t: grid(run, t, "RDPS_10km_AirTemp_2m")[2] for t in HOURS}
    with open(ne_path) as f:
        land = [ft for ft in json.load(f)["features"]]
    out = {}
    for name, fr in FRAMES.items():
        if name not in frames_wanted:
            continue
        TOWNS = LAB_TOWNS if name.startswith("lab") else ISLAND_TOWNS
        W, H, z = fr["w"], fr["h"], fr["zoom"]
        cx, cy = world(fr["lat0"], fr["lon0"], z)
        s = 512 * 2 ** z
        proj = lambda la, lo: (world(la, lo, z)[0] - cx + W / 2, world(la, lo, z)[1] - cy + H / 2)
        sc = 1
        xs = cx - W / 2 + (np.arange(W * sc) + .5) / sc
        ys = cy - H / 2 + (np.arange(H * sc) + .5) / sc
        LON, LAT = np.meshgrid(xs / s * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s)))))
        rr, cc = (lats[0] - LAT) / (lats[0] - lats[1]), (LON - lons[0]) / (lons[1] - lons[0])
        frames, prev = [], acc[PREV]
        for t in HOURS:
            a = acc[t]
            inc = {k: gaussian_filter(np.clip(a[k] - prev[k], 0, None), 1.0) for k in a}
            prev = a
            up = {k: np.clip(map_coordinates(v, [rr, cc], order=3), 0, None) for k, v in inc.items()}
            tot = up["r"] + up["s"] + up["z"] + up["i"]
            fs = up["s"] / np.maximum(tot, 1e-6)
            ice = (up["z"] + up["i"]) / np.maximum(tot, 1e-6)
            kind = np.where(tot < 0.15, 0, np.where(ice > 0.3, 2, np.where(fs >= 0.65, 3, np.where(fs > 0.3, 2, 1))))
            rgba = np.zeros((H, W, 4))
            for k, ramp in ((1, RAIN), (2, MIX), (3, SNOW)):
                m = kind == k
                c = colour(np.where(m, tot, 0), ramp)
                rgba[m] = c[m]
            hh = t[11:13] if t.startswith("2026-10-31") else "24"
            imsave(os.path.join(HERE, f"pt-{name}-{hh}.png"), rgba)
            # isobars every 4 hPa
            p = gaussian_filter(P[t], 2.0)
            pi = map_coordinates(p, [rr[::4, ::4], cc[::4, ::4]], order=1)
            fig, ax = plt.subplots()
            cs = ax.contour(pi, levels=np.arange(960, 1044, 4))
            iso = []
            for lev, seg in zip(cs.levels, cs.allsegs):
                for pts in seg:
                    if len(pts) < 8:
                        continue
                    iso.append({"p": int(lev), "d": "M" + "L".join(f"{x * 4:.0f},{y * 4:.0f}" for x, y in pts[::2])})
            plt.close(fig)
            # low centres: local minima below 1006 hPa (also off-frame; the page points to those)
            mn = minimum_filter(p, size=25)
            lows = []
            for (i, j) in zip(*np.where((p == mn) & (p < 1006))):
                if 2 < i < p.shape[0] - 3 and 2 < j < p.shape[1] - 3:
                    x, y = proj(lats[i], lons[j])
                    lows.append({"x": round(x), "y": round(y), "p": round(float(p[i, j])), "lat": round(float(lats[i]), 1), "lon": round(float(lons[j]), 1)})
            temps = {}
            for n, (la, lo) in TOWNS.items():
                ii, jj = np.argmin(abs(lats - la)), np.argmin(abs(lons - lo))
                px, py = proj(la, lo)                       # icon from the same smoothed field as the shading
                yy, xx = int(np.clip(py, 0, H - 1)), int(np.clip(px, 0, W - 1))
                win = kind[max(0, yy - 6):yy + 7, max(0, xx - 6):xx + 7]
                vals, cnt = np.unique(win[win > 0], return_counts=True)
                kd = "dry" if (win > 0).mean() < .3 else {1: "rain", 2: "mix", 3: "snow"}[int(vals[np.argmax(cnt)])]
                temps[n] = {"t": round(float(TT[t][ii, jj]), 1), "k": kd, "mm": round(float(tot[yy, xx]), 1)}
            frames.append({"utc": t, "png": f"pt-{name}-{hh}.png", "iso": iso, "lows": lows, "towns": temps})
            print(name, t, "lows", [(l["p"], l["lat"], l["lon"]) for l in lows], flush=True)
        # land: every polygon in view as dark silhouettes, NL highlighted
        def path(geom):
            polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            o = []
            for poly in polys:
                ring = poly[0]
                if len(ring) < 4:
                    continue
                pts = [proj(la, lo) for lo, la in ring]
                if max(x for x, _ in pts) < -50 or min(x for x, _ in pts) > W + 50 or max(y for _, y in pts) < -50 or min(y for _, y in pts) > H + 50:
                    continue
                kept = [pts[0]]
                for q in pts[1:]:
                    if abs(q[0] - kept[-1][0]) + abs(q[1] - kept[-1][1]) > 1.2:
                        kept.append(q)
                o.append("M" + "L".join(f"{x:.0f},{y:.0f}" for x, y in kept) + "Z")
            return "".join(o)
        nl = "".join(path(f["geometry"]) for f in land if f["properties"].get("name") == "Newfoundland and Labrador")
        other = "".join(path(f["geometry"]) for f in land if f["properties"].get("name") != "Newfoundland and Labrador"
                        and f["properties"].get("admin") in ("Canada", "United States of America", "France", "Greenland", "Denmark"))
        out[name] = {"w": W, "h": H, "nl": nl, "other": other, "frames": frames,
                     "towns": {n: [round(v) for v in proj(*ll)] for n, ll in TOWNS.items()}, "run": run}
        with open(os.path.join(HERE, f"data-{name}.js"), "w") as f:
            f.write("// generated by build.py\nwindow.HP = " + json.dumps(out[name]) + ";\n")


if __name__ == "__main__":
    main(*sys.argv[1:4])
