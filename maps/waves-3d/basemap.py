"""Basemap texture for the 3D wave scene: land, state/province borders and lakes on the same Mercator
frame as the wave grid; open sea is left transparent for the wave-height shader.
Needs waves.js (for the frame and sea mask).

  python3 basemap.py ne_10m_admin_1_states_provinces.geojson [ne_50m_lakes.geojson]
"""
import base64
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from scipy.ndimage import distance_transform_edt, map_coordinates  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LAND, LAKE, PROV, COAST = "#EEF0EC", "#D3DCE0", "#B4BEC2", "#55666E"
TW = 2048


def merc(lat):
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def main(ne_path, lakes_path=None):
    meta = json.loads(open(os.path.join(HERE, "waves.js")).read().split("=", 1)[1].rstrip().rstrip(";"))
    nx, ny = meta["nx"], meta["ny"]
    lon0, lat0, dlon, dlat = meta["lon0"], meta["lat0"], meta["dlon"], meta["dlat"]
    lon1, lat1 = lon0 + dlon * (nx - 1), lat0 + dlat * (ny - 1)
    x0, x1, y0, y1 = np.radians(lon0), np.radians(lon1), merc(lat0), merc(lat1)
    TH = int(round(TW * (y1 - y0) / (x1 - x0)))

    def rings_of(path):
        out = []
        for f in json.load(open(path))["features"]:
            g = f["geometry"]
            rings = [p[0] for p in g["coordinates"]] if g["type"] == "MultiPolygon" else [g["coordinates"][0]]
            for r in rings:
                a = np.array(r)
                if a[:, 0].max() < lon0 - 5 or a[:, 0].min() > lon1 + 5 or a[:, 1].max() < lat0 - 5 or a[:, 1].min() > lat1 + 5:
                    continue
                out.append(np.c_[np.radians(a[:, 0]), merc(np.clip(a[:, 1], -85, 85))])
        return out
    polys = rings_of(ne_path)

    def figure():
        fig = plt.figure(figsize=(TW / 100, TH / 100), dpi=100)
        fig.patch.set_alpha(0)
        ax = fig.add_axes([0, 0, 1, 1]); ax.patch.set_alpha(0); ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.axis("off")
        return fig, ax

    def grab(fig):
        fig.canvas.draw(); img = np.asarray(fig.canvas.buffer_rgba()).copy(); plt.close(fig); return img

    # land mask first (plain fill), to find lakes
    fig, ax = figure()
    ax.add_collection(PolyCollection(polys, facecolors="k", edgecolors="none", antialiased=False))
    land = grab(fig)[..., 3] > 0
    lakes = np.zeros_like(land)
    if lakes_path:                                               # Great Lakes etc. sit inside the province shapes
        fig, ax = figure()
        ax.add_collection(PolyCollection(rings_of(lakes_path), facecolors="k", edgecolors="none", antialiased=False))
        lakes = grab(fig)[..., 3] > 0
        land &= ~lakes

    # lakes: water pixels more than ~1 grid cell from any wave-model sea cell
    sea = np.unpackbits(np.frombuffer(base64.b64decode(meta["sea"]), np.uint8))[:nx * ny].reshape(ny, nx).astype(bool)
    dist = distance_transform_edt(~sea)                          # cells to nearest sea cell
    px = np.linspace(x0, x1, TW)
    py = np.linspace(y1, y0, TH)                                 # image rows run north -> south
    LON = np.degrees(px)[None, :].repeat(TH, 0)
    LAT = np.degrees(np.arctan(np.sinh(py)))[:, None].repeat(TW, 1)
    d = map_coordinates(dist, [(LAT - lat0) / dlat, (LON - lon0) / dlon], order=1)
    lake = (~land & (d > 1.2)) | lakes

    # final: land + lakes opaque, then borders
    fig, ax = figure()
    ax.add_collection(PolyCollection(polys, facecolors=LAND, edgecolors=PROV, linewidths=1.1))
    img = grab(fig)
    if lakes_path:
        fig, ax = figure()
        ax.add_collection(PolyCollection(rings_of(lakes_path), facecolors=LAKE, edgecolors="none"))
        lk = grab(fig).astype(float) / 255
        img = (img * (1 - lk[..., 3:]) + lk * 255 * lk[..., 3:]).astype(np.uint8)
    img[lake & ~lakes] = [int(LAKE[i:i + 2], 16) for i in (1, 3, 5)] + [255]
    img[..., 3] = np.where(land | lake, 255, 0)
    fig, ax = figure()                                           # coastline on its own layer, composited on top
    ax.contour(px, py[::-1], (land | lake)[::-1].astype(float), [0.5], colors=COAST, linewidths=1.6)
    line = grab(fig).astype(float) / 255
    a = line[..., 3:]
    out = img.astype(float) / 255
    out[..., :3] = line[..., :3] * a + out[..., :3] * (1 - a)
    out[..., 3:] = np.maximum(out[..., 3:], a)
    out = (out * 255).round().astype(np.uint8)
    plt.imsave(os.path.join(HERE, "basemap.png"), out)
    print("basemap.png", out.shape, "lake px", int(lake.sum()))


if __name__ == "__main__":
    main(*sys.argv[1:3])
