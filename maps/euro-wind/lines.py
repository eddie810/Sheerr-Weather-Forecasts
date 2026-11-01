"""Coastline + province/state/country borders as a transparent overlay (lines.png), on the same Mercator frame as
basemap.png, so the scene can draw them on top of the gust shading.

  python3 lines.py ne_10m_admin_1_states_provinces.geojson
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TW = 4096


def merc(lat):
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def main(ne_path):
    m = json.loads(open(os.path.join(HERE, "euro.js")).read().split("=", 1)[1].rstrip().rstrip(";"))
    lon0, lat0 = m["lon0"], m["lat0"]
    lon1, lat1 = lon0 + m["dlon"] * (m["nx"] - 1), lat0 + m["dlat"] * (m["ny"] - 1)
    x0, x1, y0, y1 = np.radians(lon0), np.radians(lon1), merc(lat0), merc(lat1)
    TH = int(round(TW * (y1 - y0) / (x1 - x0)))
    segs = []
    for f in json.load(open(ne_path))["features"]:
        g = f["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            r = np.array(poly[0])
            if r[:, 0].max() < lon0 - 2 or r[:, 0].min() > lon1 + 2 or r[:, 1].max() < lat0 - 2 or r[:, 1].min() > lat1 + 2:
                continue
            segs.append(np.c_[np.radians(r[:, 0]), merc(np.clip(r[:, 1], -85, 85))])
    fig = plt.figure(figsize=(TW / 100, TH / 100), dpi=100)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1]); ax.patch.set_alpha(0); ax.axis("off")
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
    ax.add_collection(LineCollection(segs, colors="white", linewidths=3.2, alpha=.7))      # halo
    ax.add_collection(LineCollection(segs, colors="#22323A", linewidths=1.4))
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba()).copy()
    plt.close(fig)
    plt.imsave(os.path.join(HERE, "lines.png"), img)
    print("lines.png", img.shape)


if __name__ == "__main__":
    main(sys.argv[1])
