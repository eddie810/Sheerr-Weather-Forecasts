"""Trick-or-treat regions map (1920x1080, Halloween style): the Island split into the blog's forecast regions,
each tinted and labelled from the written forecast (no model data), plus a Labrador card.

Regions are drawn by nearest seed point (a few seeds per region, set by hand) inside the Island outline from Natural
Earth, so the boundaries are approximate on purpose. Writes regions.png and data.js; the wording and card positions
live in index.html.

  python3 build.py
"""
import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_dilation
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
ADM1 = os.path.join(HERE, "..", "..", "data", "ne", "adm1.geojson")
W, H = 1920, 1080
LON0, LAT0, ZOOM = -53.39, 49.12, 6.29          # whole Island between the card columns; panel on the right
REGIONS = {   # name: (fill rgba, seeds as (lat, lon))
    "avalon": ((255, 122, 26, 70), [(47.45, -53.15), (47.0, -53.25), (47.8, -53.25), (47.35, -53.75), (47.95, -53.05)]),
    "burin": ((150, 90, 210, 70), [(47.15, -55.2), (47.45, -55.0), (47.6, -55.9), (47.65, -56.8), (47.65, -57.6)]),
    "clarenville": ((120, 200, 90, 62), [(48.2, -53.9), (48.55, -53.4), (48.6, -53.9), (47.85, -54.05), (48.45, -54.15)]),
    "central": ((90, 150, 230, 66), [(48.95, -54.6), (48.9, -55.7), (49.4, -55.3), (49.55, -56.1), (49.9, -56.0),
                                     (48.5, -55.6), (48.35, -56.4), (49.5, -54.3), (48.75, -54.7)]),
    "west": ((235, 200, 70, 58), [(48.95, -57.9), (48.5, -58.5), (49.55, -57.8), (50.4, -57.2), (51.2, -56.1),
                                  (47.8, -59.2), (48.2, -58.2), (49.0, -57.2), (50.8, -56.5)]),
}


def world(lat, lon):
    s, lat = 512 * 2 ** ZOOM, max(-85, min(85, lat))
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def px(lat, lon):
    (x, y), (cx, cy) = world(lat, lon), world(LAT0, LON0)
    return x - cx + W / 2, y - cy + H / 2


def svg(rings, min_px=0.9):
    out = []
    for ring in rings:
        pts = [px(la, lo) for lo, la in ring]
        if max(x for x, _ in pts) < -200 or min(x for x, _ in pts) > W + 200 or max(y for _, y in pts) < -200 or min(y for _, y in pts) > H + 200:
            continue
        kept = [pts[0]] + [p for a, p in zip(pts, pts[1:]) if abs(p[0] - a[0]) + abs(p[1] - a[1]) >= min_px]
        if len(kept) > 2:
            out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in kept) + "Z")
    return "".join(out)


def main():
    with open(ADM1) as f:
        feats = json.load(f)["features"]
    rings = [(ft["properties"].get("name"), p[0]) for ft in feats
             for p in (ft["geometry"]["coordinates"] if ft["geometry"]["type"] == "MultiPolygon" else [ft["geometry"]["coordinates"]])]
    is_island = lambda r: max(la for _, la in r) < 51.7 and min(lo for lo, _ in r) > -59.6
    island = [r for n, r in rings if n == "Newfoundland and Labrador" and is_island(r) and len(r) > 8]
    labrador = [r for n, r in rings if n == "Newfoundland and Labrador" and not is_island(r) and len(r) > 20]
    other = [r for n, r in rings if n != "Newfoundland and Labrador" and len(r) > 8]

    mask = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(mask)
    for r in island:
        dr.polygon([px(la, lo) for lo, la in r], fill=255)
    land = np.asarray(mask) > 0
    # nearest seed, with longitude scaled for latitude so distances are roughly true
    seeds, owner = [], []
    for k, (_, pts) in enumerate(REGIONS.values()):
        for la, lo in pts:
            x, y = px(la, lo)
            seeds.append((x, y)); owner.append(k)
    yy, xx = np.mgrid[0:H, 0:W]
    _, idx = cKDTree(np.array(seeds)).query(np.column_stack([xx[land], yy[land]]))
    lab = np.full((H, W), -1)
    lab[land] = np.array(owner)[idx]
    rgba = np.zeros((H, W, 4), np.uint8)
    for k, (fill, _) in enumerate(REGIONS.values()):
        rgba[lab == k] = fill
    edge = land & (binary_dilation(lab != np.roll(lab, 1, 0)) | binary_dilation(lab != np.roll(lab, 1, 1)))
    edge &= binary_dilation(lab >= 0, iterations=1) & (lab >= 0)
    inner = edge & ~binary_dilation(~land, iterations=3)               # boundaries between regions, not the coast
    rgba[inner] = (255, 236, 210, 150)
    Image.fromarray(rgba).save(os.path.join(HERE, "regions.png"))

    centre = {}
    for k, name in enumerate(REGIONS):
        ys, xs = np.nonzero(lab == k)
        centre[name] = [round(float(np.median(xs))), round(float(np.median(ys)))]
    data = {"island": svg(island), "labrador": svg(labrador), "other": svg(other), "centre": centre,
            "towns": {n: [round(v, 1) for v in px(*ll)] for n, ll in {
                "St. John's": (47.561, -52.713), "Marystown": (47.166, -55.148), "Clarenville": (48.165, -53.965),
                "Gander": (48.954, -54.609), "Grand Falls-Windsor": (48.936, -55.660), "Corner Brook": (48.951, -57.952),
                "Port aux Basques": (47.572, -59.136), "St. Anthony": (51.364, -55.580)}.items()}}
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.TT = " + json.dumps(data) + ";\n")
    print("region centres", centre)


if __name__ == "__main__":
    main()
