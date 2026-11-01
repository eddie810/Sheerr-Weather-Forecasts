"""Northeast Avalon: lowest temperature so far this morning (observed).

Reads obs.json from fetch_obs.py (Weather Underground PWS via TWC + ECCC stations). Stations that disagree
with their neighbours by more than OUTLIER degrees are dropped. The shading interpolates the remaining
station lows (Gaussian-weighted, 2.5 km) on land only, fading out where no station is near. Each town card shows
the lowest reading among that community's stations. Writes map.png, shade.png, data.js.

  MAPBOX_ACCESS_TOKEN=... python3 build.py
"""
import io
import json
import math
import os
import urllib.error
import urllib.request
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.image import imread, imsave  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 940
FRAME = dict(lon0=-52.835, lat0=47.622, zoom=10.35)
OUTLIER = 2.5           # degrees from the median of stations within 5 km
STEP = 1                # 1 degree bands
# overnight-low palette: deep blue (coldest) to pale, warm tint above freezing; keys are band centres
TC = {-8: "#2F4F9E", -6: "#3A68B4", -4: "#5A8CCB", -2: "#8DB5DF", -1: "#B3CFEA", 0: "#D6E6F2", 1: "#EAEFE6",
      3: "#F2E7C8", 5: "#F4D9A6"}
# community anchor (town centre) and which station names belong to it
TOWNS = {
    "St. John's": ((47.561, -52.712), ["St. John's", "ST JOHNS WEST CLIMATE"]),
    "Mount Pearl": ((47.518, -52.806), ["Mount Pearl"]),
    "Paradise": ((47.532, -52.875), ["Paradise"]),
    "Conception Bay South": ((47.505, -52.985), ["Conception Bay South"]),
    "Portugal Cove–St. Philip's": ((47.615, -52.862), ["Portugal Cove-Saint Philip's", "Portugal Cove–St. Philip's"]),
    "Torbay": ((47.665, -52.732), ["Torbay"]),
    "Flatrock": ((47.708, -52.713), ["Flatrock"]),
    "Pouch Cove": ((47.766, -52.765), ["Pouch Cove"]),
    "Logy Bay": ((47.627, -52.668), ["Logy Bay"]),
    "Bell Island": ((47.630, -52.950), ["Bell Island"]),
    "YYT Airport": ((47.619, -52.752), ["St. John's International"]),
}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except Exception:
            if i == tries - 1:
                raise


def world(lat, lon, z):
    s = 512 * 2 ** z
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def hexrgb(h):
    return np.array([int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)])


def colour(v):
    """Palette colour at temperature v (band centre), interpolated between the 2-degree keys."""
    ks = sorted(TC)
    v = min(max(v, ks[0]), ks[-1])
    a = max(k for k in ks if k <= v)
    b = min([k for k in ks if k > v] or [a])
    t = 0 if b == a else (v - a) / (b - a)
    c = hexrgb(TC[a]) * (1 - t) + hexrgb(TC[b]) * t
    return "#" + "".join(f"{int(round(x * 255)):02X}" for x in c)


def basemap(tok):
    """Outdoors basemap with settlement labels removed (the page draws its own).

    The Static API filters one layer per request, so fetch the map as-is (E) and once with each settlement-label
    layer hidden, and per pixel keep the most saturated candidate (label text and halos are grey/white). Hiding
    a layer can let another symbol move into the gap, which leaves fragments; any label ink still left where the
    variants disagree is filled from the surrounding map colour."""
    from scipy.ndimage import binary_dilation
    url = (f"https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/static/{FRAME['lon0']},{FRAME['lat0']},{FRAME['zoom'] - 1:.3f},0/"
           f"{W // 2}x{H // 2}@2x?attribution=false&logo=false&access_token={tok}")
    hide = '&layer_id={}&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D'
    st = np.stack([imread(io.BytesIO(get(url + (hide.format(L) if L else ""))), format="png")[..., :3]
                   for L in (None, "settlement-major-label", "settlement-minor-label", "settlement-subdivision-label")])
    sat = st.max(-1) - st.min(-1)
    sat[0] += 0.02
    out = np.take_along_axis(st, np.argmax(sat, 0)[None, ..., None].repeat(3, -1), 0)[0]
    zone = binary_dilation((np.abs(st[1:] - st[0]).sum(-1) > 0.06).any(0), iterations=6)
    s_, v_ = out.max(-1) - out.min(-1), out.mean(-1)
    bad = binary_dilation(zone & (s_ < 0.12) & ((v_ < 0.55) | (v_ > 0.88)), iterations=4)
    good = (~bad).astype(float)
    for sig in (3, 8, 20):                                    # normalised convolution fill, widening until covered
        num = np.dstack([gaussian_filter(out[..., c] * good, sig) for c in range(3)])
        den = gaussian_filter(good, sig)[..., None]
        fill = bad & (den[..., 0] > 0.05)
        out[fill] = (num / np.maximum(den, 1e-6))[fill]
        good = np.maximum(good, fill.astype(float)); bad &= ~fill
    return out


def main():
    tok = os.environ["MAPBOX_ACCESS_TOKEN"]
    obs = json.load(open(os.path.join(HERE, "obs.json")))
    z = FRAME["zoom"]
    cx, cy = world(FRAME["lat0"], FRAME["lon0"], z)
    s = 512 * 2 ** z
    proj = lambda la, lo: [round(world(la, lo, z)[0] - cx + W / 2, 1), round(world(la, lo, z)[1] - cy + H / 2, 1)]
    km = lambda a, b: math.hypot((a[1] - b[1]) * 111.32 * math.cos(math.radians(47.6)), (a[0] - b[0]) * 111.32)

    # QC: drop stations far off the median of their neighbours
    sts = obs["stations"]
    for st in sts:
        nb = [o["low"] for o in sts if o is not st and km((st["lat"], st["lon"]), (o["lat"], o["lon"])) < 5]
        st["ok"] = len(nb) < 3 or abs(st["low"] - float(np.median(nb))) <= OUTLIER
        st["xy"] = proj(st["lat"], st["lon"])
    good = [st for st in sts if st["ok"]]
    print("dropped:", [(st["id"], st["name"], st["low"]) for st in sts if not st["ok"]])

    # pixel grid (1x) in lat/lon
    xs, ys = cx - W / 2 + np.arange(W) + .5, cy - H / 2 + np.arange(H) + .5
    LON, LAT = np.meshgrid(xs / s * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s)))))
    # land mask from Terrain-RGB
    tz = 12
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

    # inverse-distance field and distance to the nearest station (km)
    kx = 111.32 * math.cos(math.radians(47.6))
    num = np.zeros(LON.shape); den = np.zeros(LON.shape); dmin = np.full(LON.shape, 1e9)
    for st in good:
        d = np.hypot((LON - st["lon"]) * kx, (LAT - st["lat"]) * 111.32)
        w = np.exp(-(d / 2.5) ** 2) + 1e-4 / np.maximum(d, 0.3) ** 2   # Gaussian (2.5 km), IDW tail where sparse
        num += w * st["low"]; den += w; dmin = np.minimum(dmin, d)
    field = gaussian_filter(num / den, 10)
    alpha = np.clip((8 - dmin) / 4, 0, 1) * 0.82          # full within 4 km of a station, gone by 8 km
    alpha = gaussian_filter(alpha, 4) * land
    band = np.floor(field / STEP) * STEP
    rgba = np.zeros(LON.shape + (4,))
    used = sorted(set(int(b) for b in np.unique(band[alpha > 0.2])))
    pal = {}
    for b in used:
        pal[b] = colour(b + STEP / 2)
        rgba[band == b, :3] = hexrgb(pal[b])
    rgba[..., 3] = alpha
    imsave(os.path.join(HERE, "shade.png"), rgba)

    # coastline from the land mask
    fig, ax = plt.subplots(); cs = ax.contour(gaussian_filter(land.astype(float), 0.8), levels=[.5])
    coast = "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pp[::2]) for p in cs.get_paths()
                    for pp in p.to_polygons(closed_only=False) if len(pp) > 20)
    plt.close(fig)

    towns = {}
    for n, (ll, names) in TOWNS.items():
        mine = [st for st in good if st["name"] in names]
        if mine:
            lo = min(mine, key=lambda st: st["low"])
            towns[n] = {"xy": proj(*ll), "low": round(lo["low"], 1), "n": len(mine), "official": lo["src"] == "ECCC"}
    imsave(os.path.join(HERE, "map.png"), basemap(tok))
    fetched = datetime.fromisoformat(obs["fetched"])
    data = {"asof": fetched.strftime("%-I:%M %p").replace("AM", "a.m.").replace("PM", "p.m."),
            "weekday": fetched.strftime("%A"), "date": fetched.strftime("%b %-d"),
            "towns": towns, "coast": coast, "colours": {str(k): v for k, v in pal.items()}, "bands": used,
            "stations": [{"xy": st["xy"], "low": st["low"], "ok": st["ok"]} for st in sts
                         if 0 <= st["xy"][0] <= W and 0 <= st["xy"][1] <= H],
            "nstations": sum(1 for st in good if 0 <= st["xy"][0] <= W and 0 <= st["xy"][1] <= H)}
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.LOWS = " + json.dumps(data) + ";\n")
    for n, t in sorted(towns.items(), key=lambda kv: kv[1]["low"]):
        print(f"{t['low']:5.1f} {n:28} n={t['n']} xy={t['xy']}")
    print("bands", used)


if __name__ == "__main__":
    main()
