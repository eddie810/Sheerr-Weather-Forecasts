"""Late-week low, closer view: RDPS sea-level pressure at the end of the run (shaded + 4 hPa isobars), H/L centres,
the low's track, and precipitation type over the Island of Newfoundland for the storm (TWC-style: rain greens,
mix pinks, snow blues, deeper with more liquid). Writes map/shade/ptype{,-tv}.png and data{,-tv}.js.

  MAPBOX_ACCESS_TOKEN=... python3 build.py ne_10m_admin_1_states_provinces.geojson [run e.g. 2026-10-20T06:00:00Z] [social|tv]
"""
import http.client
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.image import imread, imsave  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates, maximum_filter, minimum_filter  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GEOMET = "https://geo.weather.gc.ca/geomet"
LAYER = "RDPS_10km_Pressure_MSL"
NDT = timezone(timedelta(hours=-2, minutes=-30))
# map frames: social 4:5 page (map 1080x900) and broadcast 16:9 (full 1920x1080, info panel over the right third)
FRAMES = {"social": dict(w=1080, h=900, lon0=-55.6, lat0=47.75, zoom=5.70, sfx=""),
          "tv": dict(w=1920, h=1080, lon0=-52.2, lat0=47.6, zoom=6.00, sfx="-tv")}
PTYPE_FROM = "2026-10-23T00:00:00Z"          # storm window start (Thu 9:30 p.m. NDT) -> end of run
PT = {"rain": [(1, "#BFE6AE"), (5, "#86CF73"), (10, "#48AA52"), (20, "#24843D"), (40, "#11602D")],
      "mix":  [(1, "#F7C1DE"), (5, "#EF92C4"), (10, "#DE63A6"), (20, "#BD3D88")],
      "snow": [(1, "#CFE0F8"), (5, "#96BCEF"), (10, "#6194E0"), (20, "#3A68C4"), (40, "#24429C")]}
W, H, LON0, LAT0, ZOOM = 1080, 900, -60.0, 45.3, 4.98
BOX = dict(lat=(30, 60), lon=(-82, -38))
# pressure shading (hPa band start, colour): purples toward the low's centre, warm sand toward highs
BANDS = [(960, "#4B2E83"), (968, "#5E3C99"), (972, "#6F55AA"), (976, "#8470BC"), (980, "#9C8ACB"), (984, "#B3A6D9"),
         (988, "#C9C0E5"), (992, "#DCD6EE"), (996, "#EAE7F3"), (1000, "#F3F1F5"), (1004, "#F6F0E6"), (1008, "#F6E7D2"),
         (1012, "#F4DBBB"), (1016, "#F0CDA0"), (1020, "#EBBD86"), (1024, "#E4AC6E"), (1028, "#DB9A5A")]
TOWNS = {"St. John's": (47.561, -52.713), "Gander": (48.954, -54.609), "Corner Brook": (48.951, -57.952),
         "Port aux Basques": (47.572, -59.136), "Marystown": (47.166, -55.148), "Grand Falls-Windsor": (48.936, -55.660),
         "St. Anthony": (51.364, -55.580), "Sydney": (46.136, -60.195), "Halifax": (44.649, -63.575)}


def get(url, tries=5):
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except (OSError, http.client.HTTPException):         # resets and truncated reads
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def world(lat, lon):
    s = 512 * 2 ** ZOOM
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def px(lat, lon):
    (x, y), (cx, cy) = world(lat, lon), world(LAT0, LON0)
    return x - cx + W / 2, y - cy + H / 2


def mslp(run, valid, layer=LAYER):
    url = (f"{GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={layer}"
           f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat({BOX['lat'][0]},{BOX['lat'][1]})"
           f"&subset=lon({BOX['lon'][0]},{BOX['lon'][1]})&resolution=lat(0.1)&resolution=lon(0.1)"
           f"&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    body = get(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    dy, dx = hdr.get("dy", hdr.get("cellsize")), hdr.get("dx", hdr.get("cellsize"))
    a = np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"]))
    a = a / 100 if layer == LAYER and a.max() > 2000 else a
    lats = hdr["yllcorner"] + (hdr["nrows"] - np.arange(a.shape[0]) - 0.5) * dy      # north -> south rows
    lons = hdr["xllcorner"] + (np.arange(a.shape[1]) + 0.5) * dx
    return lons, lats, a


def basemap():
    """light-v11 with place labels removed (median-filter pick between label-hidden variants, as selab-sws)."""
    url = (f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM - 1:.3f},0/{W // 2}x{H // 2}@2x"
           f"?attribution=false&logo=false&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}")
    hide = '&layer_id={}&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D'
    st = np.stack([imread(io.BytesIO(get(url + (hide.format(L) if L else ""))), format="png")[..., :3]
                   for L in (None, "state-label", "country-label", "settlement-major-label", "settlement-minor-label",
                             "natural-point-label")])
    from scipy.ndimage import median_filter
    g = st.mean(-1)
    bg = median_filter(g.min(0), size=17)
    pick = np.argmin(np.abs(g - bg[None]), axis=0)
    return np.take_along_axis(st, pick[None, ..., None].repeat(3, -1), 0)[0]


def centres(lons, lats, P, kind, size=45):
    sm = gaussian_filter(P, 3)
    f = minimum_filter if kind == "L" else maximum_filter
    ext = (sm == f(sm, size=size)) & ((sm < 1004) if kind == "L" else (sm > 1016))
    ext[:4], ext[-4:], ext[:, :4], ext[:, -4:] = False, False, False, False
    return [(float(lats[i]), float(lons[j]), float(P[i, j])) for i, j in zip(*np.nonzero(ext))]


def borders(ne_path):
    """Coast + province/state lines (Natural Earth admin-1) in frame pixels, so land reads through the shading."""
    out = []
    for f in json.load(open(ne_path))["features"]:
        if f["properties"].get("adm0_a3") not in ("CAN", "USA", "SPM"):
            continue
        g = f["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            ring = np.array(poly[0])
            if ring[:, 0].max() < -80 or ring[:, 0].min() > -40 or ring[:, 1].max() < 33 or ring[:, 1].min() > 56:
                continue
            xy = [px(la, lo) for lo, la in ring[::2]]
            if len(xy) > 6:
                out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in xy) + "Z")
    return "".join(out)


def island_mask(ne_path, LON, LAT):
    """True on the Island of Newfoundland (Natural Earth admin-1 rings south of the Strait)."""
    from matplotlib.path import Path
    g = next(f["geometry"] for f in json.load(open(ne_path))["features"] if f["properties"].get("name") == "Newfoundland and Labrador")
    rings = [np.array(p[0]) for p in g["coordinates"] if len(p[0]) > 20]
    rings = [r for r in rings if r[:, 1].max() < 51.7 and r[:, 0].min() > -59.6]
    pts = np.column_stack([LON.ravel(), LAT.ravel()])
    hit = np.zeros(len(pts), bool)
    for r in rings:
        bb = (pts[:, 0] >= r[:, 0].min()) & (pts[:, 0] <= r[:, 0].max()) & (pts[:, 1] >= r[:, 1].min()) & (pts[:, 1] <= r[:, 1].max())
        hit[bb] |= Path(r).contains_points(pts[bb])
    return hit.reshape(LON.shape)


def ptype_layer(ne_path, run, end):
    """Dominant precipitation type over the storm window on the Island, shaded by total liquid (mm)."""
    t0, t1 = PTYPE_FROM, end.strftime("%Y-%m-%dT%H:%M:%SZ")
    tot = {}
    for k, layer in (("rain", "RDPS_10km_Rain-Accum"), ("snow", "RDPS_10km_Snow-Accum"),
                     ("zr", "RDPS_10km_FreezingRain-Accum"), ("pl", "RDPS_10km_IcePellets-Accum")):
        lons, lats, a1 = mslp(run, t1, layer)
        _, _, a0 = mslp(run, t0, layer)
        tot[k] = gaussian_filter(np.clip(a1 - a0, 0, None), 0.8)
    rain, snow, ice = tot["rain"], tot["snow"], tot["zr"] + tot["pl"]
    total = rain + snow + ice
    fs = snow / np.maximum(total, 1e-6)
    kind = np.where(ice > 0.3 * total, 2, np.where(fs >= 0.7, 3, np.where(fs > 0.3, 2, 1)))   # 1 rain, 2 mix, 3 snow
    sc = 2
    xs = (np.arange(W * sc) + .5) / sc
    ys = (np.arange(H * sc) + .5) / sc
    s = 512 * 2 ** ZOOM
    cx, cy = world(LAT0, LON0)
    LON = (cx - W / 2 + xs) / s * 360 - 180
    LAT = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (cy - H / 2 + ys) / s))))
    LON, LAT = np.meshgrid(LON, LAT)
    r, c = (lats[0] - LAT) / (lats[0] - lats[1]), (LON - lons[0]) / (lons[1] - lons[0])
    # classify per pixel from smoothly interpolated fields, so type boundaries curve instead of following 10 km cells
    up = {k: map_coordinates(gaussian_filter(v, 1.2), [r, c], order=3) for k, v in tot.items()}
    ri, si, ii = (np.clip(up[k], 0, None) for k in ("rain", "snow", "zr"))
    ii = ii + np.clip(up["pl"], 0, None)
    tv = ri + si + ii
    fsv = si / np.maximum(tv, 1e-6)
    kv = np.where(ii > 0.3 * tv, 2, np.where(fsv >= 0.7, 3, np.where(fsv > 0.3, 2, 1)))
    isl = island_mask(ne_path, LON, LAT)
    rgba = np.zeros(tv.shape + (4,))
    for code, name in ((1, "rain"), (2, "mix"), (3, "snow")):
        for lo, col in PT[name]:
            m = isl & (kv == code) & (tv >= lo)
            rgba[m, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            rgba[m, 3] = 0.9
    share = {name: round(float(((kv == code) & (tv >= 1) & isl).sum() / max(isl.sum(), 1)), 2)
             for code, name in ((1, "rain"), (2, "mix"), (3, "snow"))}
    towns = {}
    for n, (la, lo) in TOWNS.items():
        rr, cc = (lats[0] - la) / (lats[0] - lats[1]), (lo - lons[0]) / (lons[1] - lons[0])
        v = {k: float(map_coordinates(tot[k], [[rr], [cc]], order=1)[0]) for k in tot}
        towns[n] = {k: round(x, 1) for k, x in v.items()}
    return rgba, share, towns


def main(ne_path, run=None, frame="social"):
    global W, H, LON0, LAT0, ZOOM
    fr = FRAMES[frame]
    W, H, LON0, LAT0, ZOOM = fr["w"], fr["h"], fr["lon0"], fr["lat0"], fr["zoom"]
    caps = get(f"{GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer={LAYER}").decode()
    run = run or re.search(r'<Dimension name="reference_time"[^>]*default="([^"]+)"', caps).group(1)
    end = min(datetime.fromisoformat(re.search(r'<Dimension name="time"[^>]*>([^<]+)</Dimension>', caps).group(1)
                                     .split("/")[1].replace("Z", "+00:00")),
              datetime.fromisoformat(run.replace("Z", "+00:00")) + timedelta(hours=84))   # last hour of *this* run
    lons, lats, P = mslp(run, end.strftime("%Y-%m-%dT%H:%M:%SZ"))
    lows = centres(lons, lats, P, "L")
    main_low = min(lows, key=lambda c: (c[0] - 44) ** 2 + (c[1] + 55) ** 2)      # the one nearest NL's south coast
    # track: step back in time from the end, following the nearest minimum (within ~4 degrees)
    track, (la, lo) = [], main_low[:2]
    for h in range(0, 31, 6):
        t = end - timedelta(hours=h)
        _, _, Pt = mslp(run, t.strftime("%Y-%m-%dT%H:%M:%SZ")) if h else (lons, lats, P)
        sm = gaussian_filter(Pt, 2)
        LA, LO = np.meshgrid(lats, lons, indexing="ij")
        near = np.hypot((LO - lo) * math.cos(math.radians(la)), LA - la) < 4.0
        i, j = np.unravel_index(np.where(near, sm, np.inf).argmin(), sm.shape)
        la, lo = float(lats[i]), float(lons[j])
        track.append({"t": t.astimezone(NDT).strftime("%a %-I %p").replace("AM", "a.m.").replace("PM", "p.m."),
                      "p": round(float(Pt[i, j])), "xy": [round(v, 1) for v in px(la, lo)], "ll": [la, lo]})
    track.reverse()

    # shading + isobars in frame pixel space (2x)
    sc = 2
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    X, Y = np.vectorize(px)(LA, LO)
    Ps = gaussian_filter(P, 1.2)
    fig = plt.figure(figsize=(W * sc / 100, H * sc / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    fig.patch.set_alpha(0); ax.patch.set_alpha(0)
    levels = [b[0] for b in BANDS] + [1100]
    ax.contourf(X, Y, Ps, levels=[900] + levels[1:], colors=[b[1] for b in BANDS], alpha=0.5, antialiased=True)
    fig.canvas.draw()
    imsave(os.path.join(HERE, f"shade{fr['sfx']}.png"), np.asarray(fig.canvas.buffer_rgba()))
    plt.close(fig)
    fig, ax = plt.subplots()
    cs = ax.contour(X, Y, Ps, levels=np.arange(940, 1060, 4))
    isobars = []
    for lev, segs in zip(cs.levels, cs.allsegs):
        for seg in segs:
            inside = (seg[:, 0] > -20) & (seg[:, 0] < W + 20) & (seg[:, 1] > -20) & (seg[:, 1] < H + 20)
            if inside.sum() < 25:
                continue
            isobars.append({"p": int(lev), "d": "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in seg[::2]),
                            "pts": [[round(x), round(y)] for x, y in seg[inside][::6]]})
    plt.close(fig)
    hl = [{"k": "L", "p": round(c[2]), "xy": [round(v, 1) for v in px(c[0], c[1])]} for c in lows] + \
         [{"k": "H", "p": round(c[2]), "xy": [round(v, 1) for v in px(c[0], c[1])]} for c in centres(lons, lats, P, "H")]
    hl = [c for c in hl if 30 < c["xy"][0] < W - 30 and 30 < c["xy"][1] < H - 30]
    nearest = min(TOWNS, key=lambda n: (TOWNS[n][0] - main_low[0]) ** 2 + ((TOWNS[n][1] - main_low[1]) * 0.7) ** 2)
    data = {"run": run, "valid": end.astimezone(NDT).strftime("%A %-I:%M %p NDT"),
            "valid_short": end.astimezone(NDT).strftime("%a %-I:%M %p").replace("AM", "a.m.").replace("PM", "p.m."),
            "date": end.astimezone(NDT).strftime("%A, %B %-d"), "hours": int((end - datetime.fromisoformat(run.replace("Z", "+00:00"))).total_seconds() // 3600),
            "low": {"p": round(main_low[2]), "xy": [round(v, 1) for v in px(*main_low[:2])], "ll": main_low[:2]},
            "track": track, "isobars": isobars, "centres": hl, "bands": BANDS,
            "towns": {n: [round(v, 1) for v in px(*ll)] for n, ll in TOWNS.items()}, "borders": borders(ne_path),
            "w": W, "h": H, "fmt": frame, "pt": PT}
    with open(os.path.join(HERE, f"data{fr['sfx']}.js"), "w") as f:
        f.write("// generated by build.py\nwindow.LOW = " + json.dumps(data) + ";\n")
    imsave(os.path.join(HERE, f"map{fr['sfx']}.png"), basemap())
    rgba, share, ptowns = ptype_layer(ne_path, run, end)
    imsave(os.path.join(HERE, f"ptype{fr['sfx']}.png"), rgba)
    print("ptype share of the Island", share)
    for n, v in ptowns.items():
        print(f"  {n:20s} rain {v['rain']:5.1f}  snow {v['snow']:5.1f}  zr {v['zr']:4.1f}  pl {v['pl']:4.1f} mm")
    print(run, "->", data["valid"], "low", main_low, "nearest", nearest)
    print("track", [(t["t"], t["p"], [round(v, 1) for v in t["ll"]]) for t in track])
    print("centres", [(c["k"], c["p"], c["xy"]) for c in hl])


if __name__ == "__main__":
    main(*sys.argv[1:4])
