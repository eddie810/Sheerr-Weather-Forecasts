#!/usr/bin/env python3
"""Build the map shapes for prototypes/nl-hydro-island-dashboard.html.

Downloads Natural Earth 10 m public-domain GeoJSON (via the
nvkelso/natural-earth-vector GitHub mirror), clips it to the Island and
Labrador map frames, simplifies it and writes compact arrays into the HTML
between the  /* GEOMETRY:START */  and  /* GEOMETRY:END */  markers.

Run once (or whenever the map frames change):
    pip install shapely
    python tools/build_nl_geometry.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

from shapely.geometry import box, shape, mapping, Polygon, MultiPolygon, LineString, MultiLineString
from shapely.ops import unary_union

BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
HTML = os.path.join(os.path.dirname(__file__), "..", "prototypes", "nl-hydro-island-dashboard.html")
CACHE = os.environ.get("NE_CACHE", "/tmp/ne-cache")

# frame (lonMin, latMin, lonMax, latMax) + margin, simplify tolerance (deg), min polygon area (deg²)
FRAMES = {
    "island":   {"box": (-59.85, 46.45, -52.35, 51.95), "tol": 0.006, "min_area": 0.0004},
    "labrador": {"box": (-67.6, 51.05, -55.1, 57.15),     "tol": 0.012, "min_area": 0.0015},
}
MARGIN = 0.4
LAKE_MIN_AREA = {"island": 0.004, "labrador": 0.006}
RIVERS = {"island": {"Exploits"}, "labrador": {"Churchill"}}


def load(name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name + ".geojson")
    if not os.path.exists(path):
        print("downloading", name, file=sys.stderr)
        with urllib.request.urlopen(BASE + name + ".geojson", timeout=300) as r, open(path, "wb") as f:
            f.write(r.read())
    with open(path) as f:
        return json.load(f)["features"]


def polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def lines(g):
    if g.is_empty:
        return []
    if isinstance(g, LineString):
        return [g]
    if isinstance(g, MultiLineString):
        return list(g.geoms)
    return [l for l in getattr(g, "geoms", []) if isinstance(l, LineString)]


def ring(coords):
    return [[round(x, 3), round(y, 3)] for x, y in coords]


def poly_rings(p):
    return [ring(p.exterior.coords)] + [ring(i.coords) for i in p.interiors]


def main():
    adm1 = load("ne_10m_admin_1_states_provinces")
    lakes = load("ne_10m_lakes") + load("ne_10m_lakes_north_america")
    rivers = load("ne_10m_rivers_lake_centerlines")
    out = {}
    for key, fr in FRAMES.items():
        x0, y0, x1, y1 = fr["box"]
        clip = box(x0 - MARGIN, y0 - MARGIN, x1 + MARGIN, y1 + MARGIN)
        nl, other = [], []
        for f in adm1:
            if not f["geometry"]:
                continue
            g = shape(f["geometry"])
            if not g.intersects(clip):
                continue
            c = g.intersection(clip)
            (nl if f["properties"].get("name") == "Newfoundland and Labrador" else other).append(c)
        def prep(geoms, tol, min_area):
            res = []
            for p in polys(unary_union(geoms)) if geoms else []:
                if p.area < min_area:
                    continue
                s = p.simplify(tol, preserve_topology=True)
                if not s.is_empty:
                    for q in polys(s):
                        res.append(poly_rings(q))
            return res
        lake_geoms = []
        for f in lakes:
            if not f["geometry"]:
                continue
            g = shape(f["geometry"])
            if g.intersects(clip) and g.area >= LAKE_MIN_AREA[key]:
                lake_geoms.append(g.intersection(clip))
        river_lines = []
        for f in rivers:
            if not f["geometry"] or f["properties"].get("name") not in RIVERS[key]:
                continue
            g = shape(f["geometry"])
            if g.intersects(clip):
                for l in lines(g.intersection(clip)):
                    river_lines.append(ring(l.simplify(fr["tol"]).coords))
        # NL / Quebec border: shared edge of the two land areas
        border = []
        if key == "labrador":
            qc = [shape(f["geometry"]) for f in adm1 if f["geometry"] and f["properties"].get("name") == "Québec"]
            nlg = [shape(f["geometry"]) for f in adm1 if f["geometry"] and f["properties"].get("name") == "Newfoundland and Labrador"]
            shared = unary_union(nlg).boundary.intersection(unary_union(qc).buffer(0.01)).intersection(clip)
            for l in lines(shared.simplify(fr["tol"]) if not shared.is_empty else shared):
                if l.length > 0.05:
                    border.append(ring(l.coords))
        out[key] = {
            "nl": prep(nl, fr["tol"], fr["min_area"]),
            "other": prep(other, fr["tol"] * 1.5, fr["min_area"] * 2),
            "lakes": prep(lake_geoms, fr["tol"], 0),
            "rivers": river_lines,
            "border": border,
        }
        print(key, {k: len(v) for k, v in out[key].items()}, file=sys.stderr)

    js = "/* GEOMETRY:START — Natural Earth 10 m (public domain), built by tools/build_nl_geometry.py */\nconst GEO = " + \
        json.dumps(out, separators=(",", ":")) + ";\n/* GEOMETRY:END */"
    html = open(HTML).read()
    if "/* GEOMETRY:START" in html:
        html = re.sub(r"/\* GEOMETRY:START.*?/\* GEOMETRY:END \*/", lambda m: js, html, flags=re.S)
    else:
        sys.exit("markers not found in HTML; add /* GEOMETRY:START */ /* GEOMETRY:END */ first")
    open(HTML, "w").write(html)
    print(f"wrote geometry ({len(js) / 1024:.0f} KB) into {HTML}", file=sys.stderr)


if __name__ == "__main__":
    main()
