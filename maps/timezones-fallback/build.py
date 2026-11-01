"""Canada's time zones today (daylight time) vs tomorrow (standard time), for the Nov 1 clock change.
Zones are built from Natural Earth provinces split along approximate zone boundaries (meridians); small local
exceptions are not shown. Canada Atlas Lambert projection (EPSG:3978). Writes data.js (window.TZ).

  python3 build.py data/ne/adm1.geojson
"""
import json
import os
import sys

from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely import make_valid
from shapely.ops import transform, unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1920, 1080
# zone key -> (label, today abbr, today UTC offset, tomorrow abbr, tomorrow offset, colour)
ZONES = {
    "PT": ("Pacific", "PDT", -7, "PST", -8, "#B9D7EA"),
    "YT": ("Yukon", "MST", -7, "MST", -7, "#F2C230"),
    "MT": ("Mountain", "MDT", -6, "MST", -7, "#C7E3C1"),
    "SK": ("Saskatchewan", "CST", -6, "CST", -6, "#F2C230"),
    "CT": ("Central", "CDT", -5, "CST", -6, "#F3D9B1"),
    "ET": ("Eastern", "EDT", -4, "EST", -5, "#D8CDEB"),
    "AT": ("Atlantic", "ADT", -3, "AST", -4, "#F2C3C3"),
    "QA": ("Lower North Shore", "AST", -4, "AST", -4, "#F2C230"),
    "NT": ("Newfoundland", "NDT", -2.5, "NST", -3.5, "#BFE3DE"),
}
CITY = {"PT": "Vancouver", "YT": "Whitehorse", "MT": "Calgary", "SK": "Regina", "CT": "Winnipeg", "ET": "Toronto",
        "AT": "Halifax", "QA": "Blanc-Sablon", "NT": "St. John's"}
# label anchor (lon, lat) per zone
ANCHOR = {"PT": (-125.5, 54.5), "YT": (-135.5, 63.2), "MT": (-114.5, 56.5), "SK": (-105.8, 53.8), "CT": (-97.0, 55.5),
          "ET": (-79.5, 50.0), "AT": (-64.5, 46.4), "QA": (-58.6, 50.9), "NT": (-55.8, 48.6)}
CLIP_N = 72.5


def zone_geoms(ne_path):
    feats = {f["properties"]["name"]: make_valid(shape(f["geometry"])) for f in json.load(open(ne_path))["features"]
             if f["properties"].get("admin") == "Canada"}
    W_, E_ = -180, 0
    west = lambda lon: box(W_, 0, lon, 90)
    east = lambda lon: box(lon, 0, E_, 90)
    q = feats["Québec"]
    lab = feats["Newfoundland and Labrador"]
    isl = lab.intersection(box(-60, 46, -52, 51.7))                       # island of Newfoundland
    labr = lab.difference(isl)
    se_lab = labr.intersection(box(-57.1, 51.3, -55, 53.6))               # southeastern Labrador: Newfoundland time
    z = {
        "PT": feats["British Columbia"],
        "YT": feats["Yukon"],
        "MT": unary_union([feats["Alberta"], feats["Northwest Territories"], feats["Nunavut"].intersection(west(-102))]),
        "SK": feats["Saskatchewan"],
        "CT": unary_union([feats["Manitoba"], feats["Ontario"].intersection(west(-90)), feats["Nunavut"].intersection(box(-102, 0, -85, 90))]),
        "ET": unary_union([feats["Ontario"].intersection(east(-90)), q.difference(box(-61.5, 49.8, 0, 90)).difference(box(-62.5, 46, 0, 48)),
                           feats["Nunavut"].intersection(east(-85))]),
        "AT": unary_union([feats["New Brunswick"], feats["Nova Scotia"], feats["Prince Edward Island"], labr.difference(se_lab),
                           q.intersection(box(-62.5, 46, 0, 48))]),        # + Magdalen Islands
        "QA": q.intersection(box(-61.5, 49.8, 0, 90)),
        "NT": unary_union([isl, se_lab]),
    }
    return {k: g.intersection(box(-150, 40, -50, CLIP_N)) for k, g in z.items()}


def main(ne_path):
    tr = Transformer.from_crs("EPSG:4326", "EPSG:3978", always_xy=True)
    geoms = zone_geoms(ne_path)
    proj = {k: make_valid(transform(lambda x, y, z=None: tr.transform(x, y), g)) for k, g in geoms.items()}
    bb = [g.bounds for g in proj.values()]
    minx, miny, maxx, maxy = min(b[0] for b in bb), min(b[1] for b in bb), max(b[2] for b in bb), max(b[3] for b in bb)
    MX0, MY0, MX1, MY1 = 770, 110, 1800, 1040                          # map box in the frame (text column on the left)
    s = min((MX1 - MX0) / (maxx - minx), (MY1 - MY0) / (maxy - miny))
    ox = MX0 + ((MX1 - MX0) - (maxx - minx) * s) / 2
    oy = MY0 + ((MY1 - MY0) - (maxy - miny) * s) / 2
    px = lambda x, y: (ox + (x - minx) * s, oy + (maxy - y) * s)

    def svg(g):
        out = []
        polys = []
        stack = [g]
        while stack:                                                   # flatten Multi/GeometryCollection to polygons
            h = stack.pop()
            if h.geom_type == "Polygon":
                polys.append(h)
            elif hasattr(h, "geoms"):
                stack.extend(h.geoms)
        for p in polys:
            if p.area * s * s < 6:
                continue
            for ring in [p.exterior] + list(p.interiors):
                pts = [px(x, y) for x, y in ring.coords]
                kept = [pts[0]]
                for q in pts[1:]:
                    if abs(q[0] - kept[-1][0]) + abs(q[1] - kept[-1][1]) > .9:
                        kept.append(q)
                if len(kept) > 3:
                    out.append("M" + "L".join(f"{a:.1f},{b:.1f}" for a, b in kept) + "Z")
        return "".join(out)
    data = {"zones": {}, "w": W, "h": H}
    for k, g in proj.items():
        label, a0, o0, a1, o1, col = ZONES[k]
        ax, ay = px(*tr.transform(*ANCHOR[k]))
        data["zones"][k] = {"label": label, "city": CITY[k], "today": [a0, o0], "tomorrow": [a1, o1], "colour": col,
                            "d": svg(g), "anchor": [round(ax), round(ay)], "nochange": o0 == o1}
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.TZ = " + json.dumps(data) + ";\n")
    print({k: v["anchor"] for k, v in data["zones"].items()}, round(s * 1e6, 2))


if __name__ == "__main__":
    main(sys.argv[1])
