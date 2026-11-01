"""Avalon Peninsula highs fly-over (3D): TWC town forecasts (icons + highs) and HRDPS afternoon-max shading
with contour lines, draped on Mapbox terrain. The camera visits each part of the Avalon in AREAS order.

Reuses the nl-temps build (TWC call, HRDPS fetch, colour bands) on a frame twice the usual size, so the map
stays sharp when the camera is close. Writes data.js (window.TEMPS), terrain.js (window.TERRAIN), texture.jpg.

  MAPBOX_ACCESS_TOKEN=... TWC_API_KEY=... python3 build.py [day 0=today]
"""
import base64
import io
import json
import math
import os
import sys
import urllib.error
from datetime import datetime

import numpy as np
from matplotlib.image import imread
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter, map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "nl-temps"))
import build as nl  # noqa: E402

# Frame: 1080x960 scene units (the 4:5 map area), built at 2160x1920 and textured at 4320x3840.
LON0, LAT0, ZOOM = -53.40, 47.40, 8.15
TEX = 4                                    # texture px per scene unit
STEP = 1                                   # degrees per shading band (the Avalon's range is usually narrow)
# Camera stops in order, each with its towns (lat, lon, show on the closing overview?)
AREAS = [
    ("Northeast Avalon", {"St. John's": (47.561, -52.713, True), "Pouch Cove": (47.766, -52.765, False),
                          "Conception Bay South": (47.517, -52.998, False), "Petty Harbour": (47.466, -52.716, False)}),
    ("Southeast Avalon", {"Bay Bulls": (47.316, -52.812, False), "Ferryland": (47.016, -52.890, True),
                          "Cappahayden": (46.862, -52.947, False), "Trepassey": (46.737, -53.363, True)}),
    ("Avalon North", {"Old Perlican": (48.084, -53.017, True), "Heart's Content": (47.875, -53.370, False),
                      "Carbonear": (47.734, -53.215, True), "Bay Roberts": (47.599, -53.264, False)}),
    ("Avalon Southwest", {"Placentia": (47.243, -53.962, True), "Colinet": (47.222, -53.552, False),
                          "St. Mary's": (46.917, -53.583, True), "St. Bride's": (46.919, -54.180, False)}),
]


def setup():
    nl.W, nl.H = 2160, 1920
    nl.LON0, nl.LAT0, nl.ZOOM = LON0, LAT0, ZOOM + 1
    nl.BOX = dict(lat=(46.2, 48.6), lon=(-55.3, -51.5))
    nl.TOWNS = {n: ll[:2] for _, towns in AREAS for n, ll in towns.items()}


def band_colour(c):
    """House temperature palette at c degrees: nl.TC keys are 2-degree band starts, so colours sit at k + 1."""
    keys = sorted(nl.TC)
    c = float(np.clip(c, keys[0] + 1, keys[-1] + 1))
    k0 = max(k for k in keys if k + 1 <= c)
    k1 = min([k for k in keys if k + 1 > c] or [k0])
    f = 0 if k1 == k0 else (c - k0 - 1) / (k1 - k0)
    a0, a1 = ([int(nl.TC[k][i:i + 2], 16) for i in (1, 3, 5)] for k in (k0, k1))
    return "#" + "".join(f"{round(x + (y - x) * f):02X}" for x, y in zip(a0, a1))


def tiles(url, tz, ts, LON, LAT, decode, channels, dtype):
    """Sample a Web-Mercator tile pyramid (zoom tz, tiles ts px) at every LON/LAT; each tile fetched once."""
    wx = (LON + 180) / 360 * ts * 2 ** tz
    wy = (1 - np.log(np.tan(np.pi / 4 + np.radians(LAT) / 2)) / np.pi) / 2 * ts * 2 ** tz
    tx0, ty0, tx1, ty1 = int(wx.min() // ts), int(wy.min() // ts), int(wx.max() // ts), int(wy.max() // ts)
    m = np.zeros(((ty1 - ty0 + 1) * ts, (tx1 - tx0 + 1) * ts, channels), dtype)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            try:
                m[(ty - ty0) * ts:(ty - ty0 + 1) * ts, (tx - tx0) * ts:(tx - tx0 + 1) * ts] = \
                    decode(nl.fetch(url.format(z=tz, x=tx, y=ty))).reshape(ts, ts, channels)
            except urllib.error.HTTPError:     # no tile = open water
                continue
    return np.stack([map_coordinates(m[..., c], [wy - ty0 * ts - 0.5, wx - tx0 * ts - 0.5], order=1, mode="nearest",
                                     output=np.float32) for c in range(channels)], -1)


def main(day="0"):
    setup()
    tok = os.environ["MAPBOX_ACCESS_TOKEN"]
    towns, date = nl.twc_forecast(int(day))
    lons, lats, tmax = nl.hrdps_daytime_max(date)

    # every texture pixel: elevation (land mask, terrain) and the basemap colour
    LON, LAT = nl.frame_lonlat(2)                                     # 4320 x 3840
    rgb_elev = lambda b: (lambda a: -10000 + (a[..., 0] * 65536 + a[..., 1] * 256 + a[..., 2]) * 0.1)(
        imread(io.BytesIO(b), format="png")[..., :3].astype(np.float64) * 255)
    elev = tiles("https://api.mapbox.com/v4/mapbox.terrain-rgb/{z}/{x}/{y}.pngraw?access_token=" + tok, 11, 256,
                 LON, LAT, rgb_elev, 1, np.float32)[..., 0]
    land = elev > 0.5
    base = tiles("https://api.mapbox.com/styles/v1/mapbox/light-v11/tiles/512/{z}/{x}/{y}@2x?access_token=" + tok, 10, 1024,
                 LON, LAT, lambda b: np.asarray(Image.open(io.BytesIO(b)).convert("RGB")), 3, np.uint8) / 255
    sea = np.median(base[~land][::97], 0)

    # HRDPS afternoon max in STEP-degree bands on land, thin line on each band edge. The basemap's own detail
    # (roads, lakes, labels) is kept by scaling the band colour by the basemap's brightness relative to bare land.
    t = gaussian_filter(tmax, 1.2)
    ti = map_coordinates(t, [(lats[0] - LAT) / (lats[0] - lats[1]), (LON - lons[0]) / (lons[1] - lons[0])], order=1)
    del LON, LAT
    band = np.clip((np.floor(ti / STEP) * STEP).astype(int), -10, 29)
    colours = {b: band_colour(b + STEP / 2) for b in range(-10, 30, STEP)}
    col = np.zeros(band.shape + (3,), np.float32)
    for b in np.unique(band):
        col[band == b] = [int(colours[b][i:i + 2], 16) / 255 for i in (1, 3, 5)]
    edge = np.zeros(band.shape, bool)
    edge[:-1] |= band[:-1] != band[1:]
    edge[:, :-1] |= band[:, :-1] != band[:, 1:]
    edge = gaussian_filter(edge.astype(np.float32), 1.1) > 0.12
    detail = np.clip(base / np.median(base[land][::97], 0), 0.55, 1.08)
    shaded = land & (np.abs(base - sea).sum(-1) > 0.04)               # lakes keep the basemap's water colour
    img = np.where(shaded[..., None], col * detail, base)
    img = np.where((edge & shaded)[..., None], img * 0.78, img)

    # coastline: white halo under a dark ink line
    d = np.where(land, distance_transform_edt(land), distance_transform_edt(~land))
    img = img * (1 - np.clip(4.5 - d, 0, 1)[..., None]) + np.clip(4.5 - d, 0, 1)[..., None]
    ink = np.array([0x10, 0x22, 0x2B]) / 255
    a = np.clip(2.2 - d, 0, 1)[..., None]
    img = img * (1 - a) + ink * a

    # fade to open water at the frame edges so the map melts into the sea plane
    hh, ww = land.shape
    yy, xx = np.mgrid[0:hh, 0:ww]
    fade = np.clip(np.minimum.reduce([xx, ww - 1 - xx, yy, hh - 1 - yy]) / (60 * TEX), 0, 1)
    img = img * fade[..., None] + sea * (1 - fade[..., None])
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(os.path.join(HERE, "texture.jpg"), quality=90)

    # terrain grid, one cell per scene unit, shoreline softened and flattened toward the frame edges
    z = gaussian_filter(np.clip(elev, 0, None), 5)[TEX // 2::TEX, TEX // 2::TEX] * \
        fade[TEX // 2::TEX, TEX // 2::TEX] ** 2
    km_per_unit = 40075 * math.cos(math.radians(LAT0)) / (512 * 2 ** ZOOM)
    with open(os.path.join(HERE, "terrain.js"), "w") as f:
        f.write("// generated by build.py\nwindow.TERRAIN = " + json.dumps(
            {"w": z.shape[1], "h": z.shape[0], "km_per_px": km_per_unit,
             "data": base64.b64encode(np.round(z).astype("<i2").tobytes()).decode()}) + ";\n")

    proj = nl.projector()
    used = sorted(set(band[land & (fade > 0.5)].tolist()))
    data = {
        "date": datetime.fromisoformat(date).strftime("%A, %B %-d"),
        "weekday": datetime.fromisoformat(date).strftime("%A"),
        "issued": datetime.now(nl.NDT).strftime("%-I:%M %p NDT %a %b %-d"),
        "sea": "#" + "".join(f"{round(v * 255):02X}" for v in sea),
        "areas": [{"name": a, "towns": list(ts)} for a, ts in AREAS],
        "towns": {n: {**towns[n], "area": i, "final": ll[2], "xy": [round(v / 2, 1) for v in proj(*ll[:2])]}
                  for i, (_, ts) in enumerate(AREAS) for n, ll in ts.items()},
        "colours": {str(k): v for k, v in colours.items()}, "bands_used": used, "step": STEP,
    }
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.TEMPS = " + json.dumps(data) + ";\n")
    for n, t in towns.items():
        print(f"{n:22s} {t['high']:>3}  {t['icon']:10s} ({t['code']}) {t['phrase']}")
    print("HRDPS daytime max over grid:", round(float(tmax.min()), 1), "to", round(float(tmax.max()), 1),
          "| land max", int(elev.max()), "m | bands", used)


if __name__ == "__main__":
    main(*sys.argv[1:2])
