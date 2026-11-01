"""Build the Newfoundland forecast temperature map for a given day.

Town icons and highs come from The Weather Company (one aggregated daily-forecast
call); TWC's iconCode picks a Sheerr icon. The shading underneath is the HRDPS
daytime maximum (2 m temperature, max over the afternoon) from MSC GeoMet,
painted only on NL land using a Mapbox Terrain-RGB land mask.

  MAPBOX_ACCESS_TOKEN=... TWC_API_KEY=... python3 build.py ne_10m_admin_1_states_provinces.geojson [day_offset] [region] [roads.geojson]
  day_offset 1 = tomorrow (default); region: island (default), straits or labrador.
  Roads: Natural Earth roads for the Island; roads-labrador.geojson (OSM highways) for Labrador.
"""
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
import io  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.image import imread, imsave  # noqa: E402
from matplotlib.path import Path  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 960
NDT = timezone(timedelta(hours=-2, minutes=-30))
BANDS = list(range(-10, 32, 2))            # 2 degree shading bands
# 2-degree temperature colours (cool blues -> greens -> warm yellows/oranges), keyed by band start
TC = {-10: "#C7C4EC", -8: "#C4CDF0", -6: "#C2D6F2", -4: "#C3DFF3", -2: "#C6E7F2", 0: "#C2E3EC", 2: "#B9DFE2",
      4: "#B6E0D2", 6: "#C3E5BC", 8: "#DAEBAA", 10: "#EFE8A0", 12: "#F7DA92", 14: "#F8C783", 16: "#F6B277",
      18: "#F29C6E", 20: "#EC8567", 22: "#E26E62", 24: "#D4585F", 26: "#C4475E", 28: "#B23A5F"}

# Each region: map frame, HRDPS request box, and towns as (lat, lon, card dx, card dy).
# The card offset (CSS px from the town dot) is set by hand so neighbours never overlap.
REGIONS = {
    "island": dict(
        title="{weekday}'s highs", place="Newfoundland", suffix="",
        summary="auto", country="CAN",
        roads=[("Major Highway", "1", "tch", 0.5), ("Secondary Highway", "430", "prov", 0.55),
               ("Secondary Highway", "410", "prov", 0.5), ("Secondary Highway", "340", "prov", 0.5),
               ("Secondary Highway", "360", "prov", 0.5), ("Secondary Highway", "480", "prov", 0.5),
               ("Secondary Highway", "210", "prov", 0.5), ("Secondary Highway", "230", "prov", 0.5)],
        center=(-56.30, 49.15), zoom=6.24, box=dict(lat=(46.3, 52.0), lon=(-60.2, -52.2)),
        towns={  # largest community in each forecast region of the Island
            "St. John's": (47.561, -52.713, 24, -65), "Marystown": (47.166, -55.148, 60, 60),
            "Clarenville": (48.165, -53.965, 67, -60), "Gander": (48.954, -54.609, 48, -54),
            "Grand Falls-Windsor": (48.936, -55.660, 3, 77), "Springdale": (49.497, -56.072, -37, -63),
            "Corner Brook": (48.951, -57.952, 90, 3), "Stephenville": (48.550, -58.581, -107, 10),
            "Port aux Basques": (47.572, -59.136, -35, 91), "Harbour Breton": (47.483, -55.797, -74, 3),
            "St. Anthony": (51.364, -55.580, 0, 60), "Rocky Harbour": (49.660, -57.912, -105, -16),
            "Trepassey": (46.737, -53.363, 95, 20)}),
    "straits": dict(
        title="{weekday} on the Straits", place="Labrador Straits", suffix="-straits",
        summary="Cool and breezy on both sides of the Strait of Belle Isle. Highs {lo} to {hi}°.",
        center=(-56.45, 51.87), zoom=7.95, box=dict(lat=(50.6, 53.0), lon=(-58.6, -54.4)),
        towns={  # one community per stretch of coast; neighbours closer than ~15 km are left out
            "L'Anse au Clair": (51.428, -57.067, -90, -40), "L'Anse au Loup": (51.523, -56.830, -40, -95),
            "Red Bay": (51.727, -56.425, -20, -95), "Mary's Harbour": (52.307, -55.833, 0, 70),
            "Port Hope Simpson": (52.540, -56.300, -10, 78), "Flower's Cove": (51.300, -56.733, -60, 85),
            "St. Anthony": (51.364, -55.580, 0, 70)},
        labels=[  # (text, x, y in CSS px, kind, rotation); placed by eye for this frame
            ("Strait of Belle Isle", 585, 655, "water", -33), ("Labrador", 290, 292, "region", 0),
            ("Québec", 160, 560, "region-faint", 0), ("Newfoundland", 625, 930, "region", 0)]),
    "labrador": dict(
        title="{weekday}'s highs", place="Labrador", suffix="-labrador", summary="auto", shade_part="labrador",
        country="CAN", roads_noclip=True,
        roads=[(("Trunk",), "500", "prov", 0.5), (("Trunk",), "510", "prov", 0.5), (("Primary",), "520", "prov", 0.5),
               (("Primary",), "516", "prov", 0.5)],
        center=(-61.6, 55.55), zoom=5.32, box=dict(lat=(50.8, 61.0), lon=(-68.5, -54.5)),
        towns={  # main community in each part of the Big Land
            "Nain": (56.542, -61.692, -190, -60), "Hopedale": (55.456, -60.209, 200, -110), "Natuashish": (55.913, -61.103, -200, 40),
            "Makkovik": (55.083, -59.172, 200, -10), "Happy Valley-Goose Bay": (53.302, -60.417, -30, 95),
            "Churchill Falls": (53.528, -63.966, 0, -95), "Labrador City": (52.946, -66.911, 0, -95),
            "Cartwright": (53.708, -57.021, 130, 0), "Port Hope Simpson": (52.540, -56.300, 60, 60),
            "L'Anse au Loup": (51.523, -56.830, -170, 30), "Rigolet": (54.180, -58.430, -160, -55)},
        labels=[("Québec", 170, 420, "region-faint", 0)]),
    "nl": dict(
        title="{weekday}'s highs", place="Newfoundland and Labrador", suffix="-nl", summary="auto", country="CAN",
        roads_noclip=True,
        roads=[("Major Highway", "1", "tch", 0.45), (("Trunk",), "500", "prov", 0.5), (("Trunk",), "510", "prov", 0.4)],
        center=(-60.4, 53.55), zoom=4.7, box=dict(lat=(45.8, 61.2), lon=(-68.8, -51.6)),
        towns={  # six across Labrador, six across the Island (close neighbours left out at this scale)
            "Nain": (56.542, -61.692, -150, -40), "Hopedale": (55.456, -60.209, 150, -40),
            "Happy Valley-Goose Bay": (53.302, -60.417, -20, 95), "Churchill Falls": (53.528, -63.966, 0, -95),
            "Labrador City": (52.946, -66.911, -110, 80), "Cartwright": (53.708, -57.021, 150, 0),
            "St. Anthony": (51.364, -55.580, 150, -20), "Corner Brook": (48.951, -57.952, -150, -30),
            "Port aux Basques": (47.572, -59.136, -140, 50), "Gander": (48.954, -54.609, 170, -60),
            "St. John's": (47.561, -52.713, 140, 10), "Marystown": (47.166, -55.148, -84, 29)},
        labels=[("Québec", 150, 400, "region-faint", 0)]),
    "colorado": dict(
        title="{weekday}'s highs", place="Colorado", suffix="-colorado",
        summary="Highs {lo} to {hi}°F across Colorado, from the mountains to the plains.",
        center=(-105.55, 39.0), zoom=6.62, box=dict(lat=(36.3, 41.7), lon=(-110.0, -101.2)),
        shade="Colorado", model="RDPS_10km_AirTemp_2m", hours_utc=(18, 21, 24), units="F",
        towns={  # largest community in each part of the state
            "Denver": (39.739, -104.990, 140, 30), "Fort Collins": (40.585, -105.084, 0, -75),
            "Colorado Springs": (38.834, -104.821, 140, 0), "Pueblo": (38.254, -104.609, 0, 85),
            "Grand Junction": (39.064, -108.551, 0, -80), "Durango": (37.275, -107.880, 0, 85),
            "Steamboat Springs": (40.485, -106.832, 0, -75), "Aspen": (39.191, -106.818, 0, -80),
            "Alamosa": (37.469, -105.870, 0, 85), "Sterling": (40.626, -103.208, 0, 80),
            "Lamar": (38.087, -102.621, 0, -90), "Gunnison": (38.546, -106.925, 0, 80)},
        relief=True,
        # (Natural Earth type, route number, interstate?, where along the route to put its shield 0-1)
        roads=[("Major Highway", "25", True, 0.55), ("Major Highway", "70", True, 0.53), ("Major Highway", "76", True, 0.5),
               ("Secondary Highway", "50", False, 0.35), ("Secondary Highway", "160", False, 0.5),
               ("Secondary Highway", "285", False, 0.45), ("Secondary Highway", "40", False, 0.3),
               ("Secondary Highway", "287", False, 0.7), ("Secondary Highway", "550", False, 0.5)],
        labels=[("Wyoming", 300, 40, "region-faint", 0), ("Nebraska", 900, 70, "region-faint", 0),
                ("Kansas", 1035, 400, "region-faint", 90), ("New Mexico", 470, 945, "region-faint", 0),
                ("Utah", 40, 300, "region-faint", 90)]),
}
REGIONS["nl-low"] = dict(REGIONS["nl"], suffix="-nl-low", kind="low", title="Tonight's lows",
                         eyebrow="Newfoundland and Labrador · {weekday} night, {date}")
REGIONS["island-low"] = dict(REGIONS["island"], suffix="-island-low", kind="low", title="Tonight's lows",
                             eyebrow="Newfoundland · {weekday} night, {date}")
LON0, LAT0, ZOOM, TOWNS, BOX = None, None, None, {}, {}
MODEL, HOURS, UNITS = "HRDPS.CONTINENTAL_TT", (15, 17, 19, 21), "C"

# TWC iconCode -> Sheerr icon name
ICONS = {}
for codes, name in [((32, 34, 36), "sun"), ((30,), "partly"), ((28,), "mostly"), ((26, 44), "cloud"),
                    ((39, 45), "showers"), ((9, 11, 12, 40), "rain"), ((5, 6, 7, 8, 10, 17, 18, 35), "mix"),
                    ((13, 14, 15, 16, 41, 42, 43, 46), "snow"), ((3, 4, 37, 38, 47), "thunder"),
                    ((19, 20, 21, 22), "fog"), ((23, 24, 25), "wind"),
                    ((31, 33), "sun"), ((27, 29), "partly")]:
    for c in codes:
        ICONS[c] = name


def fetch(url, tries=4):
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def world_px(lat, lon, z):
    s = 512 * 2 ** z
    return ((lon + 180) / 360 * s,
            (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s)


def projector():
    cx, cy = world_px(LAT0, LON0, ZOOM)
    return lambda la, lo: (world_px(la, lo, ZOOM)[0] - cx + W / 2, world_px(la, lo, ZOOM)[1] - cy + H / 2)


def svg_path(rings, proj, min_px=0.8):
    out = []
    for ring in rings:
        pts = [proj(la, lo) for lo, la in ring]
        kept = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - kept[-1][0]) + abs(p[1] - kept[-1][1]) >= min_px:
                kept.append(p)
        if len(kept) > 2:
            out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in kept) + "Z")
    return "".join(out)


NIGHT = {31: "moon", 33: "moon", 29: "moonpartly", 27: "moonmostly"}


def twc_forecast(day, kind="high"):
    geos = ";".join(f"{t[0]},{t[1]}" for t in TOWNS.values())
    url = (f"https://api.weather.com/v3/aggcommon/v3-wx-forecast-daily-5day?geocodes={geos}"
           f"&format=json&units={'e' if UNITS == 'F' else 'm'}&language=en-CA&apiKey={os.environ['TWC_API_KEY']}")
    rows = json.loads(fetch(url))
    out = {}
    for name, row in zip(TOWNS, rows):
        d = row["v3-wx-forecast-daily-5day"]
        dp = d["daypart"][0]
        i = day * 2 + (kind == "low")     # daypart index of that day's daytime (or night, for lows)
        code = dp["iconCode"][i]
        out[name] = {"high": d["temperatureMax"][day], "low": d["temperatureMin"][day],
                     "temp": d["temperatureMin"][day] if kind == "low" else d["temperatureMax"][day],
                     "icon": (kind == "low" and NIGHT.get(code)) or ICONS.get(code, "cloud"), "code": code, "phrase": dp["wxPhraseLong"][i],
                     "pop": dp["precipChance"][i], "wind": f"{dp['windDirectionCardinal'][i]} {dp['windSpeed'][i]}"}
    return out, d["validTimeLocal"][day][:10]


def hrdps_daytime_max(date, hours=None, pick=np.maximum):
    """Max 2 m temperature over the local afternoon (MODEL, at HOURS UTC) on a lat/lon grid
    (or, with hours/pick, e.g. the overnight minimum)."""
    grid = None
    d0 = datetime.fromisoformat(date)
    for hh in hours or HOURS:
        when = (d0 + timedelta(hours=hh)).strftime("%Y-%m-%dT%H:00:00Z")
        url = ("https://geo.weather.gc.ca/geomet?service=WCS&version=2.0.1&request=GetCoverage"
               f"&coverageId={MODEL}&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326"
               f"&subset=lat({BOX['lat'][0]},{BOX['lat'][1]})&subset=lon({BOX['lon'][0]},{BOX['lon'][1]})"
               "&resolution=lat(0.025)&resolution=lon(0.035)"
               f"&time={when}&format=image/x-aaigrid")
        raw = fetch(url).decode("latin1")
        body = raw.split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
        hdr, i = {}, 0
        while re.match(r"^[a-zA-Z_]+\s", body[i]):
            k, v = body[i].split()[:2]
            hdr[k.lower()] = float(v)
            i += 1
        a = np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"]))
        grid = a if grid is None else pick(grid, a)
    lons = hdr["xllcorner"] + hdr["dx"] * (np.arange(grid.shape[1]) + 0.5)
    lats = (hdr["yllcorner"] + hdr["dy"] * (np.arange(grid.shape[0]) + 0.5))[::-1]
    return lons, lats, grid


def frame_lonlat(scale):
    """Lon/lat of every pixel centre in the frame (at scale x the CSS size)."""
    cx, cy = world_px(LAT0, LON0, ZOOM)
    s = 512 * 2 ** ZOOM
    xs = (cx - W / 2) + (np.arange(W * scale) + 0.5) / scale
    ys = (cy - H / 2) + (np.arange(H * scale) + 0.5) / scale
    lon = xs / s * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s))))
    return np.meshgrid(lon, lat)


def land_mask(scale):
    """True where Mapbox Terrain-RGB is above sea level, so shading follows the basemap coastline."""
    tz = int(ZOOM) + 2
    LON, LAT = frame_lonlat(scale)
    wx = (LON + 180) / 360 * 256 * 2 ** tz
    wy = (1 - np.log(np.tan(np.pi / 4 + np.radians(LAT) / 2)) / np.pi) / 2 * 256 * 2 ** tz
    tx0, ty0 = int(wx.min() // 256), int(wy.min() // 256)
    tx1, ty1 = int(wx.max() // 256), int(wy.max() // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
    token = os.environ["MAPBOX_ACCESS_TOKEN"]
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            try:
                png = fetch(f"https://api.mapbox.com/v4/mapbox.terrain-rgb/{tz}/{tx}/{ty}.pngraw?access_token={token}")
            except urllib.error.HTTPError:     # no tile = open water
                continue
            rgb = imread(io.BytesIO(png), format="png")[..., :3] * 255
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = \
                -10000 + (rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]) * 0.1
    elev = map_coordinates(mosaic, [wy - ty0 * 256, wx - tx0 * 256], order=0)
    return elev > 0.5, LON, LAT


def in_rings(rings, LON, LAT, where):
    """Point-in-polygon for the pixels flagged in `where` (lon/lat rings)."""
    out = np.zeros(LON.shape, bool)
    pts = np.column_stack([LON[where], LAT[where]])
    hit = np.zeros(len(pts), bool)
    for ring in rings:
        hit |= Path(np.array(ring)).contains_points(pts)
    out[where] = hit
    return out


def coast_path(mask, scale):
    """SVG path (CSS px) tracing the edge of a pixel mask."""
    fig, ax = plt.subplots()
    cs = ax.contour(gaussian_filter(mask.astype(float), 1.0), levels=[0.5])
    out = []
    for path in cs.get_paths():
        for poly in path.to_polygons(closed_only=False):
            if len(poly) < 12:
                continue
            pts = poly[:: max(1, scale)] / scale
            out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts))
    plt.close(fig)
    return "".join(out)


def relief_layer(scale, inside, tz=9):
    """Hillshade overlay (shadows + highlights) from Terrain-RGB, only where `inside` is True."""
    LON, LAT = frame_lonlat(scale)
    wx = (LON + 180) / 360 * 256 * 2 ** tz
    wy = (1 - np.log(np.tan(np.pi / 4 + np.radians(LAT) / 2)) / np.pi) / 2 * 256 * 2 ** tz
    tx0, ty0, tx1, ty1 = int(wx.min() // 256), int(wy.min() // 256), int(wx.max() // 256), int(wy.max() // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
    token = os.environ["MAPBOX_ACCESS_TOKEN"]
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            try:
                png = fetch(f"https://api.mapbox.com/v4/mapbox.terrain-rgb/{tz}/{tx}/{ty}.pngraw?access_token={token}")
            except urllib.error.HTTPError:     # no tile = open water
                continue
            rgb = imread(io.BytesIO(png), format="png")[..., :3] * 255
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = \
                -10000 + (rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]) * 0.1
    mpp = 40075016.686 * math.cos(math.radians(LAT0)) / (256 * 2 ** tz)
    dy, dx = np.gradient(gaussian_filter(mosaic, 0.8), mpp)
    az, alt = math.radians(315), math.radians(42)
    slope = np.arctan(np.hypot(dx, dy) * 2.2)
    aspect = np.arctan2(-dx, dy)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    sh = map_coordinates(shade, [wy - ty0 * 256, wx - tx0 * 256], order=1)
    flat = math.sin(alt)
    dark = np.clip((flat - sh) * 2.4, 0, 1)
    light = np.clip((sh - flat) * 1.6, 0, 1)
    rgba = np.zeros(sh.shape + (4,))
    rgba[..., :3] = np.where(dark[..., None] > 0, [0.16, 0.12, 0.18], [1, 1, 0.97])
    rgba[..., 3] = np.maximum(dark * 0.72, light * 0.45) * inside
    return rgba


def roads_layer(roads_path, spec, proj, clip_rings, country="USA"):
    """SVG paths + shield positions for the chosen highways, clipped to the region outline (or not, if
    clip_rings is None). spec rows: (road type or tuple of types, route number, shield style, shield position 0-1);
    shield style is "interstate", "us", "tch" or "prov" (True/False still mean interstate/us)."""
    with open(roads_path) as f:
        feats = json.load(f)["features"]
    clip = [Path(np.array(r)) for r in clip_rings] if clip_rings else None
    inside = (lambda x, y: any(p.contains_point((x, y)) for p in clip)) if clip else (lambda x, y: True)
    out = []
    for kind, num, style, frac in spec:
        kinds = kind if isinstance(kind, tuple) else (kind,)
        style = {True: "interstate", False: "us"}.get(style, style)
        lines = []
        for ft in feats:
            p = ft["properties"]
            if p.get("sov_a3") != country or p.get("name") != num or p.get("type") not in kinds:
                continue
            g = ft["geometry"]
            for line in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
                seg = []
                for x, y in line:
                    if inside(x, y):
                        seg.append(proj(y, x))
                    elif seg:
                        lines.append(seg); seg = []
                if len(seg) > 1:
                    lines.append(seg)
        if not lines:
            continue
        d = "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in l) for l in lines)
        longest = max(lines, key=len)
        sx, sy = longest[min(len(longest) - 1, int(len(longest) * frac))]
        # fallback spots along every piece, nearest the preferred one first; the page picks the first clear one
        allpts = [pt for l in lines for pt in l[::3]]
        allpts.sort(key=lambda pt: (pt[0] - sx) ** 2 + (pt[1] - sy) ** 2)
        out.append({"num": num, "style": style, "interstate": style in ("interstate", "tch"), "d": d,
                    "shield": [round(sx), round(sy)], "cands": [[round(x), round(y)] for x, y in allpts[::2][:1500]]})
    return out


def main(ne_path, day="1", region="island", roads_path=None):
    global LON0, LAT0, ZOOM, TOWNS, BOX, MODEL, HOURS, UNITS
    day, r = int(day), REGIONS[region]
    (LON0, LAT0), ZOOM, TOWNS, BOX = r["center"], r["zoom"], r["towns"], r["box"]
    MODEL, HOURS, UNITS = r.get("model", MODEL), r.get("hours_utc", HOURS), r.get("units", UNITS)
    low = r.get("kind") == "low"
    towns, date = twc_forecast(day, r.get("kind", "high"))
    proj = projector()

    # lows: coldest of 9:30 p.m., 12:30, 3:30, 6:30 and 8:30 a.m. NDT that night
    lons, lats, tmax = hrdps_daytime_max(date, (24, 27, 30, 33, 35), np.minimum) if low else hrdps_daytime_max(date)

    with open(ne_path) as f:
        feats = {ft["properties"].get("name"): ft["geometry"] for ft in json.load(f)["features"]}
    if "shade" in r:                                        # any other state/province: shade the whole of it
        g = feats[r["shade"]]
        shade_rings = [p[0] for p in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]])]
    else:
        rings = [p[0] for p in feats["Newfoundland and Labrador"]["coordinates"] if len(p[0]) > 20]
        is_island = lambda g: max(la for _, la in g) < 51.7 and min(lo for lo, _ in g) > -59.6
        island = [g for g in rings if is_island(g)]
        shade_rings = island if region == "island" else (
            [g for g in rings if not is_island(g)] if r.get("shade_part") == "labrador" else rings)

    # Shading as a raster: HRDPS temperature at every pixel, banded every 2 degrees, painted only
    # on NL land (Terrain-RGB land mask inside the province outline), so it follows the coastline.
    scale = 2
    land, LON, LAT = land_mask(scale)
    nl_land = in_rings(shade_rings, LON, LAT, land)
    t = gaussian_filter(tmax, 1.2)
    ti = map_coordinates(t, [(lats[0] - LAT) / (lats[0] - lats[1]), (LON - lons[0]) / (lons[1] - lons[0])], order=1)
    if UNITS == "F":       # 5 F bands, each coloured like the 2 C band its middle falls in
        step, ti = 5, ti * 9 / 5 + 32
        keys = sorted(TC)
        def mix(c):                                    # interpolate the C palette at the band's middle
            c = float(np.clip(c, keys[0], keys[-1]))
            k0 = max(k for k in keys if k <= c); k1 = min([k for k in keys if k > c] or [k0])
            f = 0 if k1 == k0 else (c - k0) / (k1 - k0)
            a0 = [int(TC[k0][i:i + 2], 16) for i in (1, 3, 5)]; a1 = [int(TC[k1][i:i + 2], 16) for i in (1, 3, 5)]
            return "#" + "".join(f"{round(x + (y - x) * f):02X}" for x, y in zip(a0, a1))
        colours = {f: mix((f + 2.5 - 32) * 5 / 9 - 1) for f in range(-10, 111, 5)}
        band = np.clip((np.floor(ti / 5) * 5).astype(int), -10, 110)
    else:
        step, colours = 2, TC
        band = np.clip((np.floor(ti / 2) * 2).astype(int), BANDS[0], BANDS[-2])
    rgba = np.zeros(band.shape + (4,))
    for b, c in colours.items():
        sel = band == b
        rgba[sel, :3] = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    rgba[..., 3] = nl_land * 0.78
    imsave(os.path.join(HERE, f"shade{r['suffix']}.png"), rgba)
    if r.get("relief"):
        imsave(os.path.join(HERE, f"relief{r['suffix']}.png"), relief_layer(scale, nl_land))
    used = sorted(set(band[nl_land].tolist()))

    data = {
        "date": datetime.fromisoformat(date).strftime("%A, %B %-d"),
        "weekday": datetime.fromisoformat(date).strftime("%A"),
        "issued": datetime.now(NDT).strftime("%-I:%M %p NDT %a %b %-d"),
        "title": r["title"], "summary": r["summary"], "place": r["place"], "kind": r.get("kind", "high"),
        "eyebrow": r.get("eyebrow", "").replace("{weekday}", datetime.fromisoformat(date).strftime("%A"))
                    .replace("{date}", datetime.fromisoformat(date).strftime("%B %-d")),
        "towns": {n: {**towns[n], "xy": [round(v) for v in proj(*TOWNS[n][:2])],
                      "card": [round(proj(*TOWNS[n][:2])[0] + TOWNS[n][2]), round(proj(*TOWNS[n][:2])[1] + TOWNS[n][3])]}
                  for n in TOWNS},
        "colours": {str(k): v for k, v in colours.items()}, "bands_used": used, "step": step, "unit": UNITS,
        "model": "HRDPS (ECCC)" if MODEL.startswith("HRDPS") else "RDPS (ECCC)",
        "labels": [list(l) for l in r.get("labels", [])],
        "coast": coast_path(nl_land, scale),
        "relief": bool(r.get("relief")),
        "roads": roads_layer(roads_path, r["roads"], proj, None if r.get("roads_noclip") else shade_rings,
                             r.get("country", "USA")) if r.get("roads") and roads_path else [],
    }
    with open(os.path.join(HERE, f"data{r['suffix']}.js"), "w") as f:
        f.write("// generated by build.py\nwindow.TEMPS = " + json.dumps(data) + ";\n")
    with open(os.path.join(HERE, f"map{r['suffix']}.png"), "wb") as f:
        f.write(fetch(f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM},0/"
                      f"{W}x{H}@2x?attribution=false&logo=false&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"))
    for n, t in towns.items():
        print(f"{n:22s} {t['temp']:>3}  {t['icon']:10s} ({t['code']}) {t['phrase']}")
    print(MODEL, "overnight min" if low else "daytime max", "over grid:", round(float(tmax.min()), 1), "to", round(float(tmax.max()), 1))


if __name__ == "__main__":
    main(*sys.argv[1:5])
