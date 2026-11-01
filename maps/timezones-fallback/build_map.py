"""Canada + lower-48 U.S. coloured by clock (UTC offset), today (daylight) vs tomorrow (standard), Nov 1 change.
Canadian zones from build.py; U.S. states by zone with a few meridian splits (simplified). Alaska/Hawaii left out.
Writes map-data.js (window.TM).   python3 build_map.py data/ne/adm1.geojson"""
import json, os, sys
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union
import build as cz

HERE = os.path.dirname(os.path.abspath(__file__))
US = {  # state -> zone
    **{s: "PT" for s in ("Washington", "Oregon", "California", "Nevada")},
    **{s: "MT" for s in ("Montana", "Idaho", "Wyoming", "Utah", "Colorado", "New Mexico")},
    "Arizona": "AZ",
    **{s: "CT" for s in ("North Dakota", "South Dakota", "Nebraska", "Kansas", "Oklahoma", "Texas", "Minnesota", "Iowa", "Missouri",
                          "Arkansas", "Louisiana", "Wisconsin", "Illinois", "Mississippi", "Alabama", "Tennessee", "Kentucky")},
    **{s: "ET" for s in ("Michigan", "Indiana", "Ohio", "Georgia", "Florida", "South Carolina", "North Carolina", "Virginia",
                          "West Virginia", "Pennsylvania", "New York", "Vermont", "New Hampshire", "Maine", "Massachusetts",
                          "Rhode Island", "Connecticut", "New Jersey", "Delaware", "Maryland", "District of Columbia")},
}
# (state, zone for the part west of lon, lon)  -- simplified splits
SPLIT = [("Idaho", "PT", None), ("Tennessee", "ET", -85.3), ("Kentucky", "ET", -85.9), ("Florida", "CT", -85.0),
         ("Texas", "MT", -104.9), ("North Dakota", "MT", -101.0), ("South Dakota", "MT", -100.6), ("Nebraska", "MT", -101.4),
         ("Indiana", "CT", -87.1)]
# U.S.: PT, AZ, MT, CT, ET (ET merged with eastern Canada). Canada 2026: BC, YT, AB (+NWT), SK, MB (+NW Ont.), NUW, NUC, QA, AT, NT
OFF = {"today": {"PT": -7, "AZ": -7, "MT": -6, "CT": -5, "ET": -4, "BC": -7, "YT": -7, "AB": -6, "SK": -6, "MB": -5, "NUW": -6, "NUC": -5,
                 "QA": -4, "AT": -3, "NT": -2.5},
       "tomorrow": {"PT": -8, "AZ": -7, "MT": -7, "CT": -6, "ET": -5, "BC": -7, "YT": -7, "AB": -6, "SK": -6, "MB": -5, "NUW": -7, "NUC": -6,
                    "QA": -4, "AT": -4, "NT": -3.5}}


def canada_2026(ne):
    """Canadian zones as of Nov 1, 2026: B.C. (permanent UTC-7 since Mar 8), Alberta + N.W.T. (permanent UTC-6),
    Manitoba + northwestern Ontario west of 90W (permanent UTC-5), Nunavut split by its Mountain/Central/Eastern parts."""
    f = {x["properties"]["name"]: make_valid(shape(x["geometry"])) for x in json.load(open(ne))["features"] if x["properties"].get("admin") == "Canada"}
    q, lab = f["Québec"], f["Newfoundland and Labrador"]
    isl = lab.intersection(box(-60, 46, -52, 51.7)); labr = lab.difference(isl); se = labr.intersection(box(-57.1, 51.3, -55, 53.6))
    nu, on = f["Nunavut"], f["Ontario"]
    return {
        "BC": f["British Columbia"], "YT": f["Yukon"], "AB": unary_union([f["Alberta"], f["Northwest Territories"]]), "SK": f["Saskatchewan"],
        "MB": unary_union([f["Manitoba"], on.intersection(box(-100, 40, -90, 60))]),
        "NUW": nu.intersection(box(-125, 50, -102, 90)), "NUC": nu.intersection(box(-102, 50, -85, 90)),
        "ETC": unary_union([on.difference(box(-100, 40, -90, 60)), q.difference(box(-61.5, 49.8, 0, 90)).difference(box(-62.5, 46, 0, 48)),
                            nu.intersection(box(-85, 50, 0, 90))]),
        "AT": unary_union([f["New Brunswick"], f["Nova Scotia"], f["Prince Edward Island"], labr.difference(se), q.intersection(box(-62.5, 46, 0, 48))]),
        "QA": q.intersection(box(-61.5, 49.8, 0, 90)), "NT": unary_union([isl, se]),
    }


def main(ne):
    feats = [f for f in json.load(open(ne))["features"]]
    us = {f["properties"]["name"]: make_valid(shape(f["geometry"])) for f in feats if f["properties"].get("admin") == "United States of America"}
    z = {k: [] for k in ("PT", "AZ", "MT", "CT", "ET")}
    for st, zone in US.items():
        g = us[st]
        sp = next((s for s in SPLIT if s[0] == st), None)
        if sp and sp[0] == "Idaho":                                   # north Idaho panhandle on Pacific time
            z["PT"].append(g.intersection(box(-120, 45.6, -110, 50))); z["MT"].append(g.difference(box(-120, 45.6, -110, 50)))
        elif sp:
            z[sp[1]].append(g.intersection(box(-130, 20, sp[2], 55))); z[zone].append(g.difference(box(-130, 20, sp[2], 55)))
        else:
            z[zone].append(g)
    zones = {k: unary_union(v) for k, v in z.items()}
    zones.update(canada_2026(ne))
    zones["ET"] = unary_union([zones["ET"], zones.pop("ETC")])
    zones = {k: make_valid(g.intersection(box(-140, 24, -50, 70))) for k, g in zones.items()}
    usa = make_valid(unary_union([us[st] for st in US])).intersection(box(-140, 24, -50, 70))
    canada = make_valid(unary_union(list(canada_2026(ne).values()))).intersection(box(-140, 24, -50, 70))
    tr = Transformer.from_crs("EPSG:4326", "+proj=lcc +lat_1=33 +lat_2=60 +lat_0=45 +lon_0=-96 +datum=WGS84", always_xy=True)
    proj = {k: make_valid(transform(lambda x, y, z=None: tr.transform(x, y), g)) for k, g in zones.items()}
    P = lambda g: make_valid(transform(lambda x, y, z=None: tr.transform(x, y), g))
    pu, pc = P(usa), P(canada)
    border = pc.boundary.intersection(pu.buffer(15000))                 # the shared land border (15 km tolerance)
    bb = [g.bounds for g in proj.values()]
    minx, miny, maxx, maxy = min(b[0] for b in bb), min(b[1] for b in bb), max(b[2] for b in bb), max(b[3] for b in bb)
    PW, PH = 860, 620
    s = min(PW / (maxx - minx), PH / (maxy - miny))
    ox, oy = (PW - (maxx - minx) * s) / 2, (PH - (maxy - miny) * s) / 2
    px = lambda x, y: (ox + (x - minx) * s, oy + (maxy - y) * s)

    def svg(g):
        out, stack = [], [g]
        while stack:
            h = stack.pop()
            if h.geom_type == "Polygon":
                if h.area * s * s < 4: continue
                for ring in [h.exterior] + list(h.interiors):
                    pts = [px(a, b) for a, b in ring.coords]; kept = [pts[0]]
                    for q in pts[1:]:
                        if abs(q[0] - kept[-1][0]) + abs(q[1] - kept[-1][1]) > .8: kept.append(q)
                    if len(kept) > 3: out.append("M" + "L".join(f"{a:.1f},{b:.1f}" for a, b in kept) + "Z")
            elif hasattr(h, "geoms"):
                stack.extend(h.geoms)
        return "".join(out)
    cities = {"Vancouver": (49.28, -123.12), "Los Angeles": (34.05, -118.24), "Whitehorse": (60.72, -135.06), "Phoenix": (33.45, -112.07),
              "Calgary": (51.05, -114.07), "Denver": (39.74, -104.99), "Regina": (50.45, -104.62), "Winnipeg": (49.90, -97.14),
              "Chicago": (41.88, -87.63), "Toronto": (43.65, -79.38), "New York": (40.71, -74.01), "Blanc-Sablon": (51.43, -57.13),
              "Halifax": (44.65, -63.57), "St. John's": (47.56, -52.71)}
    tags = {"YT": (-135.5, 63.0), "BC": (-123.5, 54.5), "PT": (-120.5, 39.0), "AZ": (-111.7, 34.3), "AB": (-115.0, 56.5),
            "AB2": (-121.0, 64.5), "MT": (-107.5, 42.5), "SK": (-105.8, 54.0), "MB": (-97.5, 55.5), "NUW": (-108.0, 67.0),
            "NUC": (-94.0, 63.5), "CT": (-96.5, 36.5), "ET": (-84.5, 50.5), "ET2": (-80.5, 37.5), "ET3": (-73.0, 53.5),
            "QA": (-59.6, 51.0), "AT": (-62.5, 54.5), "AT2": (-64.0, 46.0), "NT": (-55.8, 48.7)}
    def line(g):
        out, stack = [], [g]
        while stack:
            h = stack.pop()
            if h.geom_type == "LineString" and h.length * s > 3:
                out.append("M" + "L".join(f"{a:.1f},{b:.1f}" for a, b in (px(*c) for c in h.coords)))
            elif hasattr(h, "geoms"):
                stack.extend(h.geoms)
        return "".join(out)
    lab = {"CANADA": (-100.0, 59.0), "UNITED STATES": (-99.0, 40.5)}
    data = {"w": PW, "h": PH, "border": line(border), "countries": {k: [round(v, 1) for v in px(*tr.transform(*ll))] for k, ll in lab.items()}, "tags": {k: [round(v, 1) for v in px(*tr.transform(lo, la))] for k, (lo, la) in tags.items()}, "zones": {k: svg(g) for k, g in proj.items()}, "off": OFF,
            "cities": {n: [round(v, 1) for v in px(*tr.transform(lo, la))] for n, (la, lo) in cities.items()}}
    open(os.path.join(HERE, "map-data.js"), "w").write("window.TM = " + json.dumps(data) + ";\n")
    print(data["cities"])


if __name__ == "__main__":
    main(sys.argv[1])
