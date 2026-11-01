"""Atlantic Canada futurecast (16:9, Maritimes to northern Labrador): HRDPS precipitation by type over cloud cover,
with isobars, H/L centres and town temperatures, motion-interpolated so it moves like radar.

HRDPS 2.5 km 1-hour rain / snow / freezing rain / ice pellet amounts and total cloud cover (MSC GeoMet WCS).
Between each pair of model hours the echo motion is measured by matching tiles of the precipitation field
(FFT cross-correlation, smoothed into a flow field); each in-between step slides both hours along that motion
and blends them, so storms travel across the map instead of jumping or cross-fading. SUB steps per hour.
Clouds get their own motion (cloud decks don't always move with the rain). Sea-level pressure is blended between
hours and contoured for every step; H/L centres are matched hour to hour so they glide (and fade in or out).
Writes frames/NNN.png (cloud + radar, 5-minute steps), mask.png (model-grid fade, for the isobars) and frames.js
(times, isobars and H/L per step, towns, and a label-free basemap: land, lakes and province lines from Natural Earth,
so no basemap place names clash with the town labels).

  python3 build.py [hours] [start, UTC like 2026-10-26T15; default the next hour]

"""
import json
import math
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
from contourpy import LineType, contour_generator
from PIL import Image
from scipy.ndimage import (binary_fill_holes, binary_opening, distance_transform_edt, gaussian_filter, map_coordinates,
                           maximum_filter, minimum_filter, zoom)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "future-radar"))
import build as fr  # noqa: E402  (HRDPS WCS fetch, palette, intensity breaks)

W, H = 2000, 1700                         # map plane: tilted back in the page so Labrador recedes behind the Island
LON0, LAT0, ZOOM = -57.6, 53.6, 5.5        # Cape Breton to the northern tip of Labrador
ADT = timezone(timedelta(hours=-3))
SUB = 12                                  # in-between steps per model hour (5 minutes)
WORK = 2                                  # fields are moved on a grid at 1/WORK of the frame
TILE, STRIDE, MAXSHIFT = 48, 16, 20       # motion tiles on a 1/4-frame grid (~6 km px): ~300 km tiles, up to ~120 km/h
RES = (0.04, 0.06)                        # WCS request resolution, lat/lon degrees (~4.4 km, about the moving grid)
ISO = 4                                   # hPa between isobars
CHARTS = ["St. John's", "Corner Brook", "Goose Bay", "Labrador City"]   # towns with a temperature chart in the side panel
NE_DIR = os.path.join(HERE, "..", "..", "data", "ne")
TOWNS = {
    "St. John's": (47.561, -52.713), "Clarenville": (48.165, -53.965), "Gander": (48.954, -54.609),
    "Corner Brook": (48.951, -57.952), "Port aux Basques": (47.572, -59.136),
    "Marystown": (47.166, -55.148), "St. Anthony": (51.364, -55.580), "Blanc-Sablon": (51.426, -57.131),
    "Labrador City": (52.946, -66.911), "Churchill Falls": (53.528, -63.966), "Goose Bay": (53.302, -60.417),
    "Cartwright": (53.708, -57.021), "Mary's Harbour": (52.307, -55.833), "Makkovik": (55.083, -59.172),
    "Hopedale": (55.456, -60.209), "Nain": (56.542, -61.692), "Sydney": (46.136, -60.194), "Sept-Îles": (50.218, -66.381),
}
REGIONS = [("Labrador", 54.6, -63.2), ("Québec", 51.6, -68.0)]       # the Island needs no label this close
PROVINCES = ("Newfoundland and Labrador", "Québec", "Nova Scotia", "New Brunswick", "Prince Edward Island", "Maine",
             "Saint-Pierre", "Miquelon-Langlade", "Ontario", "New Hampshire", "Vermont", "New York", "Nunavut")


def setup():
    fr.W, fr.H, fr.LON0, fr.LAT0, fr.ZOOM = W, H, LON0, LAT0, ZOOM
    fr.BOX = dict(lat=(43.0, 62.5), lon=(-76.0, -40.8))


def wcs(coverage, run, valid):
    """One HRDPS grid (MSC GeoMet WCS, AAIGrid) over fr.BOX at RES; precipitation and cloud clipped at 0."""
    url = (f"{fr.GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={coverage}"
           f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat({fr.BOX['lat'][0]},{fr.BOX['lat'][1]})"
           f"&subset=lon({fr.BOX['lon'][0]},{fr.BOX['lon'][1]})&resolution=lat({RES[0]})&resolution=lon({RES[1]})"
           f"&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    body = fr.fetch(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    a = np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"]))
    return (np.clip(a, 0, None) if "DIAG_" in coverage or coverage.endswith("_NT") else a), hdr


def regrid(grids, hdr, LON, LAT):
    """HRDPS lat/lon grids -> frame-aligned grid."""
    top = hdr["yllcorner"] + hdr["nrows"] * hdr["dy"]
    rows, cols = (top - LAT) / hdr["dy"] - 0.5, (LON - hdr["xllcorner"]) / hdr["dx"] - 0.5
    return np.stack([map_coordinates(gaussian_filter(g, 0.6), [rows, cols], order=1) for g in grids])


def flow(a, b, cloud=False):
    """Displacement (dy, dx) in work-grid px from field a to field b, per pixel: tile cross-correlation on a
    1/4-frame grid, gaps filled from neighbouring tiles, smoothed, upsampled. Precipitation tiles need some
    precipitation in them; cloud tiles need some structure (a featureless overcast gives no motion to measure)."""
    k = 4 // WORK
    ia, ib = ((zoom(f, 1 / k, order=1) / 100) if cloud else np.log1p(zoom(f, 1 / k, order=1)) for f in (a, b))
    hh, ww = ia.shape
    win = np.outer(np.hanning(TILE), np.hanning(TILE))
    ys, xs = list(range(0, hh - TILE + 1, STRIDE)), list(range(0, ww - TILE + 1, STRIDE))
    v = np.full((len(ys), len(xs), 2), np.nan)
    wt = np.zeros((len(ys), len(xs)))
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            ta, tb = ia[y:y + TILE, x:x + TILE], ib[y:y + TILE, x:x + TILE]
            if (min(ta.std(), tb.std()) < 0.06) if cloud else ((ta > 0.05).mean() < 0.04 or (tb > 0.05).mean() < 0.04):
                continue
            fa, fb = np.fft.rfft2((ta - ta.mean()) * win), np.fft.rfft2((tb - tb.mean()) * win)
            cc = np.fft.fftshift(np.fft.irfft2(np.conj(fa) * fb, s=ta.shape))
            c = TILE // 2
            sub = cc[c - MAXSHIFT:c + MAXSHIFT + 1, c - MAXSHIFT:c + MAXSHIFT + 1]
            py, px = np.unravel_index(np.argmax(sub), sub.shape)
            if 0 < py < sub.shape[0] - 1 and 0 < px < sub.shape[1] - 1:          # sub-pixel peak
                d = lambda m1, m0, p1: 0.5 * (m1 - p1) / (m1 - 2 * m0 + p1 + 1e-9)
                dy, dx = py + d(sub[py - 1, px], sub[py, px], sub[py + 1, px]), px + d(sub[py, px - 1], sub[py, px], sub[py, px + 1])
            else:
                dy, dx = py, px
            v[i, j] = dy - MAXSHIFT, dx - MAXSHIFT
            wt[i, j] = min(ta.std(), tb.std()) if cloud else min(ta.mean(), tb.mean())
    ok = ~np.isnan(v[..., 0])
    if not ok.any():
        return np.zeros((2,) + a.shape)
    med = np.median(v[ok], 0)
    out = []
    for c in range(2):                     # normalised convolution: neighbours fill gaps, weak tiles count less
        num = gaussian_filter(np.where(ok, v[..., c] * wt, 0), 1.2)
        den = gaussian_filter(np.where(ok, wt, 0), 1.2)
        g = np.where(den > 1e-4, num / np.maximum(den, 1e-9), med[c])
        cy = (np.arange(a.shape[0]) / k - TILE / 2) / STRIDE
        cx = (np.arange(a.shape[1]) / k - TILE / 2) / STRIDE
        CY, CX = np.meshgrid(cy, cx, indexing="ij")
        out.append(gaussian_filter(map_coordinates(g, [CY, CX], order=1, mode="nearest"), 6) * k)
    return np.stack(out)


def between(A, B, u, f):
    """Fields at fraction f of the hour: A pushed forward and B pulled back along u, blended."""
    hh, ww = A.shape[1:]
    Y, X = np.mgrid[0:hh, 0:ww].astype(np.float32)
    wa = [Y - f * u[0], X - f * u[1]]
    wb = [Y + (1 - f) * u[0], X + (1 - f) * u[1]]
    return np.stack([(1 - f) * map_coordinates(A[c], wa, order=1, mode="constant")
                     + f * map_coordinates(B[c], wb, order=1, mode="constant") for c in range(len(A))])


def paint(F, C, fade):
    """Cloud cover under precipitation type + intensity (work grid) -> RGBA uint8 at frame size, soft edges.
    fade (frame size, 0-1) dims everything toward the edge of the model's grid."""
    F = np.stack([gaussian_filter(zoom(f, WORK, order=1), 0.7) for f in F])
    rn, sn, fz, pe = F
    total = rn + sn + fz + pe
    snowfrac = (sn + pe) / np.maximum(total, 1e-6)
    kind = np.where(fz > 0.3 * total, "freezing", np.where(snowfrac > 0.75, "snow", np.where(snowfrac < 0.25, "rain", "mix")))
    rgba = np.zeros(total.shape + (4,), np.uint8)
    for k, (b0, b1, b2) in fr.BREAKS.items():
        for lvl, (lo, hi) in enumerate([(b0 * 0.6, b1), (b1, b2), (b2, 1e9)]):     # light band reaches into the rim
            sel = (kind == k) & (total >= lo) & (total < hi)
            c = fr.PALETTE[k][lvl]
            rgba[sel, :3] = [int(c[i:i + 2], 16) for i in (1, 3, 5)]
    # alpha fades in over the lightest band's lower edge, so echoes have soft rims instead of pixel steps
    lo = np.select([kind == k for k in fr.BREAKS], [fr.BREAKS[k][0] for k in fr.BREAKS])
    ar = np.clip((total - lo * 0.6) / (lo * 0.4), 0, 1) * 0.92
    # clouds: soft white, thin cover barely there, overcast a milky veil; radar laid over them
    ac = np.clip((gaussian_filter(zoom(C, WORK, order=1), 1.5) - 25) / 75, 0, 1) ** 1.5 * 0.5
    ar, ac = ar * fade, ac * fade
    a = ar + ac * (1 - ar)
    rgb = (rgba[..., :3] * ar[..., None] + np.array([244, 247, 248]) * (ac * (1 - ar))[..., None]) / np.maximum(a, 1e-6)[..., None]
    return np.dstack([np.clip(rgb, 0, 255), a * 255]).astype(np.uint8)


def isobars(P, ok):
    """ISO-hPa isobars of P (work grid, NaN outside the model) as SVG paths in frame px, each with a label spot where it
    meets the left or bottom edge (those spots slide along smoothly as the lines move)."""
    # pressure is smooth, so contour a half-size grid: far fewer points, same lines (thread-safe, unlike pyplot)
    gen = contour_generator(z=np.ma.masked_where(~ok[::2, ::2], P[::2, ::2]), line_type=LineType.Separate)
    out = []
    for lv in range(940, 1064, ISO):
        for poly in gen.lines(lv):
            poly = poly * WORK * 2
            if len(poly) < 8 or np.hypot(*np.ptp(poly, 0)) < 120:
                continue
            kept = [poly[0]]
            for q in poly[1:]:
                if abs(q[0] - kept[-1][0]) + abs(q[1] - kept[-1][1]) >= 9:
                    kept.append(q)
            kept = np.array(kept)
            lab = None
            inside = kept[(kept[:, 0] > 50) & (kept[:, 0] < W - 50) & (kept[:, 1] > 50) & (kept[:, 1] < H - 40)]
            if len(inside):
                left, low = inside[np.argmin(inside[:, 0])], inside[np.argmax(inside[:, 1])]
                lab = left if left[0] < 140 else (low if low[1] > H - 130 else None)
            out.append(["M" + "L".join(f"{x:.0f},{y:.0f}" for x, y in kept), lv,
                        None if lab is None else [round(float(lab[0])), round(float(lab[1]))]])
    return out


def centres(P, ok):
    """Highs and lows of P (work grid): (kind, x, y, hPa) in frame px."""
    found = []
    filled = np.where(ok, P, np.nanmean(P[ok]))
    for kind, f in (("L", minimum_filter), ("H", maximum_filter)):
        ext = (filled == f(filled, size=61)) & (np.abs(filled - gaussian_filter(filled, 40)) > 1.5) & ok
        for y, x in zip(*np.nonzero(ext)):
            if 20 < x * WORK < W - 20 and 20 < y * WORK < H - 20:
                found.append((kind, int(x) * WORK, int(y) * WORK, int(round(float(filled[y, x])))))
    return found


def track(a, b, f):
    """H/L centres partway (f) from hour a to hour b: matched pairs glide, the rest fade out or in."""
    out, used = [], set()
    for k, x, y, v in a:
        cand = [(np.hypot(x - x2, y - y2), j) for j, (k2, x2, y2, _) in enumerate(b) if k2 == k and j not in used]
        d, j = min(cand) if cand else (1e9, None)
        if d < 160:
            used.add(j)
            k2, x2, y2, v2 = b[j]
            out.append([k, round(x + (x2 - x) * f), round(y + (y2 - y) * f), int(round(v + (v2 - v) * f)), 1])
        else:
            out.append([k, x, y, v, round(1 - f, 2)])
    out += [[k, x, y, v, round(f, 2)] for j, (k, x, y, v) in enumerate(b) if j not in used]
    return [c for c in out if c[4] > 0.01]


def outline(path, keep, min_pts=4):
    """Polygon rings from a Natural Earth file (features passing keep), as one SVG path in frame px."""
    with open(path) as f:
        feats = [ft for ft in json.load(f)["features"] if keep(ft["properties"])]
    out = []
    for ft in feats:
        g = ft["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            for ring in poly:
                if len(ring) < min_pts:
                    continue
                pts = [fr.town_xy(la, lo) for lo, la in ring]
                kept = [pts[0]] + [p for a, p in zip(pts, pts[1:]) if abs(p[0] - a[0]) + abs(p[1] - a[1]) >= 1.2]
                if len(kept) > 2 and any(-50 < x < W + 50 and -50 < y < H + 50 for x, y in kept):
                    out.append("M" + "L".join(f"{x:.0f},{y:.0f}" for x, y in kept) + "Z")
    return "".join(out)


def main(hours="24", start=None, ne_dir=NE_DIR):
    setup()
    hours = int(hours)
    run, last = fr.latest_run()
    t0 = (datetime.strptime(start, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc) if start else
          datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    times = [t0 + timedelta(hours=h) for h in range(hours + 1) if t0 + timedelta(hours=h) <= last]
    fdir = os.path.join(HERE, "frames")
    os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir):
        os.remove(os.path.join(fdir, f))
    LON, LAT = fr.frame_lonlat(1 / WORK)

    def hour(t):
        iso = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        grids = [wcs(f"HRDPS.CONTINENTAL.DIAG_{k}_PT1H", run, iso) for k in fr.KINDS] + \
                [wcs(c, run, iso) for c in ("HRDPS.CONTINENTAL_NT", "HRDPS.CONTINENTAL_PN-SLP", "HRDPS.CONTINENTAL_TT")]
        return regrid([g for g, _ in grids], grids[0][1], LON, LAT)

    with ThreadPoolExecutor(5) as ex:
        G = list(ex.map(hour, times))
    F, C = [g[:4] for g in G], [g[4:5] for g in G]
    # 2 m temperature (°C) at each town, every model hour (TT is not clipped at 0 like the precip amounts)
    temps = {n: [round(float(map_coordinates(g[6], [[xy[1] / WORK], [xy[0] / WORK]], order=1)[0]), 1) for g in G]
             for n, xy in ((n, fr.town_xy(*ll)) for n, ll in TOWNS.items())}
    # the model's grid: anywhere that shows some cloud during the period (outside it GeoMet returns zeros);
    # eased out over ~200 px inside its edge so the data thins away instead of stopping at a straight line
    dom = binary_fill_holes(binary_opening((np.stack([c[0] for c in C]) > 0.5).any(0), iterations=3))
    d = np.clip(distance_transform_edt(dom) / (200 / WORK), 0, 1)
    fade = gaussian_filter(zoom(d * d * (3 - 2 * d), WORK, order=1), 6)
    Image.fromarray(np.dstack([np.full(fade.shape + (3,), 255), fade * 255]).astype(np.uint8)).save(os.path.join(HERE, "mask.png"))
    # sea-level pressure, hPa, smoothed (the 2.5 km field is wiggly over terrain) using only points inside the model grid
    ok = dom & (distance_transform_edt(dom) > 8)
    P = [gaussian_filter(np.where(dom, g[5] / 100, 0), 8) / np.maximum(gaussian_filter(dom.astype(float), 8), 1e-6) for g in G]
    HL = [centres(p, ok & (distance_transform_edt(dom) > 60 / WORK)) for p in P]
    print(len(F), "model hours fetched; measuring motion")
    ease = lambda U: [0.25 * U[max(i - 1, 0)] + 0.5 * U[i] + 0.25 * U[min(i + 1, len(U) - 1)] for i in range(len(U))]
    U = ease([flow(F[i].sum(0), F[i + 1].sum(0)) for i in range(len(F) - 1)])       # eases speed changes hour to hour
    UC = ease([flow(C[i][0], C[i + 1][0], cloud=True) for i in range(len(C) - 1)])
    for i, (u, uc) in enumerate(zip(U, UC)):
        sp, sc = (np.hypot(*v) * WORK * fr_km() for v in (u, uc))
        print(f"  {times[i].astimezone(fr.NDT):%a %-I %p}: precip moving {np.median(sp):.0f} km/h (max {sp.max():.0f}), "
              f"cloud {np.median(sc):.0f} km/h")

    steps = [(i, s) for i in range(len(U)) for s in range(SUB)] + [(len(U) - 1, SUB)]

    def one(n_is):
        n, (i, s) = n_is
        f = s / SUB
        PS = (1 - f) * P[i] + f * P[min(i + 1, len(P) - 1)]
        iso[n], hl[n] = isobars(np.where(ok, PS, np.nan), ok), track(HL[i], HL[min(i + 1, len(P) - 1)], f)
        if 0 < s < SUB:
            Fs, Cs = between(F[i], F[i + 1], U[i], s / SUB), between(C[i], C[i + 1], UC[i], s / SUB)
        else:
            Fs, Cs = F[i + (s == SUB)], C[i + (s == SUB)]
        Image.fromarray(paint(Fs, Cs[0], fade)).save(os.path.join(fdir, f"{n:03d}.png"), compress_level=1)

    iso, hl = [None] * len(steps), [None] * len(steps)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, enumerate(steps)))

    run_t = datetime.fromisoformat(run.replace("Z", "+00:00"))
    stamp = lambda t: {"ndt": t.astimezone(fr.NDT).strftime("%-I:%M %p"), "adt": t.astimezone(ADT).strftime("%-I:%M %p"),
                       "day": t.astimezone(fr.NDT).strftime("%A")}
    data = {
        "sub": SUB, "hours": len(U),
        "times": [stamp(times[i] + timedelta(minutes=60 * s / SUB)) for i, s in steps],
        "iso": iso, "hl": hl, "temps": temps, "charts": CHARTS,
        "ticks": [{"i": h * SUB, "lab": (times[0] + timedelta(hours=h)).astimezone(fr.NDT).strftime(
                      "%a %-I %p" if h == 0 or (times[0] + timedelta(hours=h)).astimezone(fr.NDT).hour < 6 else "%-I %p")}
                  for h in range(0, len(U) + 1, 6)],
        "date": f"{times[0].astimezone(fr.NDT):%A %-I:%M %p} to {times[-1].astimezone(fr.NDT):%A %-I:%M %p} NDT",
        "run": f"HRDPS {run_t:%HZ} {run_t:%b %-d}",
        "size": [W, H], "towns": {n: fr.town_xy(*ll) for n, ll in TOWNS.items()},
        "regions": [[n] + fr.town_xy(la, lo) for n, la, lo in REGIONS],
        "land": outline(os.path.join(ne_dir, "adm1.geojson"), lambda p: p.get("name") in PROVINCES),
        "lakes": outline(os.path.join(ne_dir, "lakes.geojson"), lambda p: (p.get("scalerank") or 0) <= 9, 8),
    }
    with open(os.path.join(HERE, "frames.js"), "w") as f:
        f.write("// generated by build.py\nwindow.LOOP = " + json.dumps(data) + ";\n")
    print(len(steps), "frames", data["date"], "|", data["run"])


def fr_km():
    """km per frame px at the frame centre."""
    return 40075 * math.cos(math.radians(LAT0)) / (512 * 2 ** ZOOM)


if __name__ == "__main__":
    main(*sys.argv[1:3])
