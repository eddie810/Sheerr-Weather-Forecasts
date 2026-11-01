"""1920x1080 broadcast maps: RDPS rain and snow totals from now to the end of the latest run.

Total = accumulation at the end time minus accumulation at the start time (same run); by default now to
the run's last hour. Snow is liquid equivalent x SNOW_RATIO/10 -> cm. Shading is masked to land (Mapbox
Terrain-RGB). Highways come from roads-{view}.json (OSM for Labrador, Natural Earth for the Island).
Writes {rain,snow}-shade.png, map.png, data.js.

  MAPBOX_ACCESS_TOKEN=... python3 build.py ne_10m_admin_1_states_provinces.geojson [view] [start] [end]
  start/end as UTC ISO times, e.g. 2026-10-14T21:00:00Z 2026-10-16T00:00:00Z
"""
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
from matplotlib.image import imread, imsave
from scipy.ndimage import gaussian_filter, map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
GEOMET = "https://geo.weather.gc.ca/geomet"
W, H = 1920, 1080
TOWN_EXTRA = {"avalon": {"Ferryland": (47.024, -52.890), "Trepassey": (46.737, -53.363)},
              "grandbank": {"Grand Bank": (47.100, -55.765)}}
VIEWS = {
    "nl": dict(center=(-59.6, 52.55), zoom=4.80, suffix="", towns=None),
    "island": dict(center=(-56.55, 49.22), zoom=6.50, suffix="-island", towns={
        "St. John's": (47.561, -52.713), "Carbonear": (47.737, -53.215), "Placentia": (47.245, -53.962),
        "Marystown": (47.166, -55.148), "Clarenville": (48.165, -53.965), "Bonavista": (48.650, -53.115),
        "Gander": (48.954, -54.609), "Grand Falls-Windsor": (48.936, -55.660), "Harbour Breton": (47.483, -55.797),
        "Burgeo": (47.617, -57.621), "Port aux Basques": (47.572, -59.136), "Stephenville": (48.550, -58.581),
        "Corner Brook": (48.951, -57.952), "Deer Lake": (49.174, -57.426), "Rocky Harbour": (49.660, -57.912),
        "Springdale": (49.497, -56.072), "Baie Verte": (49.932, -56.180), "Twillingate": (49.648, -54.761),
        "Port au Choix": (50.709, -57.331), "St. Anthony": (51.364, -55.580)}),
    # Friday-Saturday low: SE Labrador snow, Island + Straits rain, province-wide peak gusts
    "selab": dict(center=(-58.6, 52.85), zoom=6.75, suffix="-selab", kinds=["snow"], roads=["labrador"], towns={
        "Happy Valley-Goose Bay": (53.302, -60.417), "North West River": (53.525, -60.145), "Rigolet": (54.180, -58.430),
        "Cartwright": (53.708, -57.021), "Black Tickle": (53.459, -55.765), "Charlottetown": (52.766, -56.115),
        "Port Hope Simpson": (52.546, -56.300), "St. Lewis": (52.372, -55.676), "Mary's Harbour": (52.311, -55.833),
        "Red Bay": (51.726, -56.427), "L'Anse au Loup": (51.523, -56.830), "L'Anse au Clair": (51.430, -57.060),
        "St. Anthony": (51.364, -55.580)}),
    "nlstraits": dict(center=(-56.45, 49.55), zoom=6.40, suffix="-nlstraits", kinds=["rain"], roads=["island", "labrador"], towns={
        "St. John's": (47.561, -52.713), "Carbonear": (47.737, -53.215), "Placentia": (47.245, -53.962),
        "Marystown": (47.166, -55.148), "Clarenville": (48.165, -53.965), "Bonavista": (48.650, -53.115),
        "Gander": (48.954, -54.609), "Grand Falls-Windsor": (48.936, -55.660), "Harbour Breton": (47.483, -55.797),
        "Burgeo": (47.617, -57.621), "Port aux Basques": (47.572, -59.136), "Stephenville": (48.550, -58.581),
        "Corner Brook": (48.951, -57.952), "Deer Lake": (49.174, -57.426), "Rocky Harbour": (49.660, -57.912),
        "Springdale": (49.497, -56.072), "Baie Verte": (49.932, -56.180), "Twillingate": (49.648, -54.761),
        "Port au Choix": (50.709, -57.331), "St. Anthony": (51.364, -55.580), "L'Anse au Loup": (51.523, -56.830),
        "Red Bay": (51.726, -56.427)}),
    "wind": dict(center=(-57.8, 52.55), zoom=5.15, suffix="-wind", kinds=["gust"], only_nl=True, roads=["island", "labrador"], towns={
        "St. John's": (47.561, -52.713), "Marystown": (47.166, -55.148), "Bonavista": (48.650, -53.115),
        "Gander": (48.954, -54.609), "Grand Falls-Windsor": (48.936, -55.660), "Burgeo": (47.617, -57.621),
        "Port aux Basques": (47.572, -59.136), "Corner Brook": (48.951, -57.952), "Baie Verte": (49.932, -56.180),
        "Port au Choix": (50.709, -57.331), "St. Anthony": (51.364, -55.580), "L'Anse au Loup": (51.523, -56.830),
        "Mary's Harbour": (52.311, -55.833), "Cartwright": (53.708, -57.021), "Rigolet": (54.180, -58.430),
        "Happy Valley-Goose Bay": (53.302, -60.417), "Churchill Falls": (53.528, -63.966),
        "Labrador City": (52.946, -66.911), "Makkovik": (55.083, -59.172), "Hopedale": (55.456, -60.209),
        "Nain": (56.542, -61.692)}),
    # whole province, rain and snow on one map (dominant type per spot)
    "storm": dict(center=(-57.8, 52.55), zoom=5.15, suffix="-storm", kinds=["mix"], only_nl=True, roads=["island", "labrador"], towns={
        "St. John's": (47.561, -52.713), "Marystown": (47.166, -55.148), "Clarenville": (48.165, -53.965),
        "Gander": (48.954, -54.609), "Grand Falls-Windsor": (48.936, -55.660), "Burgeo": (47.617, -57.621),
        "Port aux Basques": (47.572, -59.136), "Corner Brook": (48.951, -57.952), "Baie Verte": (49.932, -56.180),
        "Port au Choix": (50.709, -57.331), "St. Anthony": (51.364, -55.580), "L'Anse au Loup": (51.523, -56.830),
        "Mary's Harbour": (52.311, -55.833), "Port Hope Simpson": (52.546, -56.300), "Cartwright": (53.708, -57.021),
        "Rigolet": (54.180, -58.430), "Happy Valley-Goose Bay": (53.302, -60.417), "Churchill Falls": (53.528, -63.966),
        "Labrador City": (52.946, -66.911), "Hopedale": (55.456, -60.209), "Nain": (56.542, -61.692)}),
    # same storm map as a 4:5 social post: map area 1080x990 (header and footer are in social.html)
    "storm-social": dict(center=(-60.0, 52.25), zoom=5.20, size=(1080, 990), suffix="-storm-social", kinds=["mix"],
                         only_nl=True, roads=["island", "labrador"], towns="storm"),
    # peak gusts, Island only (shading limited to NL)
    "wind-island": dict(center=(-56.45, 49.45), zoom=6.45, suffix="-wind-island", kinds=["gust"], only_nl="island",
                        roads=["island"], towns={
        "St. John's": (47.561, -52.713), "Carbonear": (47.737, -53.215), "Placentia": (47.245, -53.962),
        "Marystown": (47.166, -55.148), "Clarenville": (48.165, -53.965), "Bonavista": (48.650, -53.115),
        "Gander": (48.954, -54.609), "Grand Falls-Windsor": (48.936, -55.660), "Harbour Breton": (47.483, -55.797),
        "Burgeo": (47.617, -57.621), "Port aux Basques": (47.572, -59.136), "Stephenville": (48.550, -58.581),
        "Corner Brook": (48.951, -57.952), "Deer Lake": (49.174, -57.426), "Rocky Harbour": (49.660, -57.912),
        "Springdale": (49.497, -56.072), "Baie Verte": (49.932, -56.180), "Twillingate": (49.648, -54.761),
        "Port au Choix": (50.709, -57.331), "Roddickton": (50.866, -56.120), "St. Anthony": (51.364, -55.580),
        "Ferryland": (47.024, -52.890), "Wreckhouse": (47.706, -59.300)},
        # a 10 km model can't resolve the Wreckhouse winds, so label it with ECCC's warning value instead
        override={"gust": {"Wreckhouse": 110}}, note="Wreckhouse: Environment Canada warning value (too local for the model)"),
    # Oct 17: rain today (Island), Labrador snow through Sunday, west-coast mountain snow (HRDPS, 8:1)
    "rain-today": dict(center=(-56.55, 49.22), zoom=6.50, suffix="-rain-today", kinds=["rain"], only_nl="island",
                       roads=["island"], towns="island"),
    "rain-today-social": dict(center=(-56.45, 49.15), zoom=6.40, size=(1080, 1080), suffix="-rain-today-social",
                              kinds=["rain"], only_nl="island", roads=["island"], towns="island"),
    # Oct 23-24 storm, tighter Island view: rain totals and where snow is possible (no amounts)
    "nf-rain": dict(center=(-56.35, 49.1), zoom=6.62, suffix="-nf-rain", kinds=["rain"], only_nl="island",
                    roads=["island"], towns="island+avalon"),
    "nf-rain-social": dict(center=(-56.05, 49.08), zoom=6.52, size=(1080, 1080), suffix="-nf-rain-social",
                           kinds=["rain"], only_nl="island", roads=["island"], towns="island+avalon"),
    "nf-snowpot": dict(center=(-56.35, 49.1), zoom=6.62, suffix="-nf-snowpot", kinds=["snowpot"], only_nl="island",
                       roads=["island"], towns="island+avalon"),
    "nf-snowpot-social": dict(center=(-56.05, 49.08), zoom=6.52, size=(1080, 1080), suffix="-nf-snowpot-social",
                              kinds=["snowpot"], only_nl="island", roads=["island"], towns="island+avalon"),
    # Friday Oct 23 peak gusts (no direction overlay); Island towns + Avalon extras
    "gust-fri": dict(center=(-56.35, 49.1), zoom=6.62, suffix="-gust-fri", kinds=["gust"], only_nl="island",
                     roads=["island"], towns="island+avalon+grandbank"),
    "gust-fri-social": dict(center=(-56.05, 49.08), zoom=6.52, size=(1080, 1080), suffix="-gust-fri-social",
                            kinds=["gust"], only_nl="island", roads=["island"], towns="island+avalon+grandbank"),
    # Halloween Oct 31: rain, mix and snow through the day (HRDPS), and afternoon/evening peak gusts, Island
    "mix-hal": dict(center=(-56.35, 49.1), zoom=6.62, suffix="-mix-hal", kinds=["mix"], model="HRDPS", only_nl="island",
                    roads=["island"], towns="island+avalon"),
    "gust-hal": dict(center=(-56.35, 49.1), zoom=6.62, suffix="-gust-hal", kinds=["gust"], only_nl="island",
                     roads=["island"], towns="island+avalon+grandbank"),
    # Friday Oct 23 peak gusts, closer on southern Newfoundland
    "gust-south": dict(center=(-55.05, 47.55), zoom=7.62, suffix="-gust-south", kinds=["gust"], only_nl="island",
                       roads=["island"], towns="south"),
    "gust-south-social": dict(center=(-54.95, 47.50), zoom=7.12, size=(1080, 1080), suffix="-gust-south-social",
                              kinds=["gust"], only_nl="island", roads=["island"], towns="south"),
    "south": dict(center=(-55.85, 47.62), zoom=7.42, suffix="-south", towns={
        "St. John's": (47.561, -52.713), "Carbonear": (47.737, -53.215), "Placentia": (47.245, -53.962),
        "St. Mary's": (46.917, -53.580), "Trepassey": (46.737, -53.363), "Ferryland": (47.024, -52.890),
        "Clarenville": (48.165, -53.965), "Marystown": (47.166, -55.148), "Grand Bank": (47.100, -55.765),
        "St. Lawrence": (46.920, -55.393), "Harbour Breton": (47.483, -55.797), "St. Alban's": (47.874, -55.843),
        "Burgeo": (47.617, -57.621), "Ramea": (47.523, -57.390), "Port aux Basques": (47.572, -59.136),
        "Stephenville": (48.550, -58.581), "Grand Falls-Windsor": (48.936, -55.660), "Gander": (48.954, -54.609),
        "Bonavista": (48.650, -53.115)}),
    # Labrador snow with where it mixes or falls as rain instead (Thu Oct 29 - Fri Oct 30)
    "lab-mix-social": dict(center=(-61.3, 54.9), zoom=5.55, size=(1080, 1080), suffix="-lab-mix-social", kinds=["snowmix"],
                           roads=["labrador"], towns="labrador"),
    "lab-snow": dict(center=(-61.3, 56.0), zoom=5.49, suffix="-lab-snow", kinds=["snow"], roads=["labrador"], towns="labrador"),
    "lab-snow-social": dict(center=(-61.6, 55.85), zoom=5.38, size=(1080, 1080), suffix="-lab-snow-social", kinds=["snow"],
                            roads=["labrador"], towns="labrador"),
    "west-snow": dict(center=(-57.2, 49.45), zoom=6.95, suffix="-west-snow", kinds=["snow"], model="HRDPS", snow_ratio=8,
                      only_nl="island", roads=["island"], towns="west"),
    "west-snow-social": dict(center=(-57.35, 49.45), zoom=6.95, size=(1080, 1080), suffix="-west-snow-social", kinds=["snow"],
                             model="HRDPS", snow_ratio=8, only_nl="island", roads=["island"], towns="west"),
    "avalon-rain-social": dict(center=(-53.3, 47.4), zoom=8.35, size=(1080, 1080), suffix="-avalon-rain-social", kinds=["rain"],
                               model="HRDPS", only_nl="island", roads=["island"], towns={
        "St. John's": (47.561, -52.713), "Mount Pearl": (47.519, -52.806), "Conception Bay South": (47.505, -52.985),
        "Torbay": (47.665, -52.732), "Holyrood": (47.388, -53.135), "Bay Roberts": (47.598, -53.265),
        "Carbonear": (47.737, -53.215), "Old Perlican": (48.083, -53.017), "Whitbourne": (47.420, -53.530),
        "Placentia": (47.245, -53.962), "St. Mary's": (46.917, -53.580), "Trepassey": (46.737, -53.363),
        "Ferryland": (47.024, -52.890), "Witless Bay": (47.278, -52.818), "Heart's Content": (47.877, -53.367)}),
    "west": dict(center=(-57.2, 49.45), zoom=6.95, suffix="-west", towns={
        "Port aux Basques": (47.572, -59.136), "Stephenville": (48.550, -58.581), "Corner Brook": (48.951, -57.952),
        "Deer Lake": (49.174, -57.426), "Rocky Harbour": (49.660, -57.912), "Cow Head": (49.920, -57.801),
        "Daniel's Harbour": (50.236, -57.580), "Port au Choix": (50.709, -57.331), "St. Anthony": (51.364, -55.580),
        "Roddickton": (50.866, -56.120), "Baie Verte": (49.932, -56.180), "Springdale": (49.497, -56.072),
        "Buchans": (48.822, -56.868), "Burgeo": (47.617, -57.621), "Grand Falls-Windsor": (48.936, -55.660),
        "Gros Morne (summit)": (49.594, -57.785), "Marble Mountain": (48.950, -57.835)}),
    "labrador": dict(center=(-61.3, 56.0), zoom=5.49, suffix="-labrador", towns={
        "Nain": (56.542, -61.692), "Natuashish": (55.913, -61.103), "Hopedale": (55.456, -60.209),
        "Makkovik": (55.083, -59.172), "Postville": (54.910, -59.784), "Rigolet": (54.180, -58.430),
        "Happy Valley-Goose Bay": (53.302, -60.417), "North West River": (53.525, -60.145),
        "Churchill Falls": (53.528, -63.966), "Labrador City": (52.946, -66.911), "Cartwright": (53.708, -57.021),
        "Port Hope Simpson": (52.540, -56.300), "Mary's Harbour": (52.307, -55.833), "L'Anse au Loup": (51.523, -56.830),
        "Schefferville": (54.806, -66.819), "Kuujjuaq": (58.106, -68.399)}),
}
LON0, LAT0, ZOOM = -59.6, 52.55, 4.80
SNOW_RATIO = 10
RES = 0.08
NDT = timezone(timedelta(hours=-2, minutes=-30))
BOX = dict(lat=(41.0, 64.0), lon=(-86.0, -30.0))
KINDS = {
    "rain": dict(layer="RDPS_10km_Rain-Accum", unit="mm", scale=1.0,
                 bands=[(2, "#CFEFC4"), (5, "#94D98A"), (10, "#4DBB5A"), (15, "#1F9447"), (25, "#2F7FC1"),
                        (50, "#1F4E9E"), (75, "#6A3FA6"), (100, "#A43C9C")]),
    "snow": dict(layer="RDPS_10km_Snow-Accum", unit="cm", scale=SNOW_RATIO / 10,
                 bands=[(1, "#E3F2FB"), (2, "#C2E3F6"), (5, "#8CC8EE"), (10, "#4AA3DD"), (15, "#2367B3"),
                        (25, "#5B3FA6"), (50, "#8E3E9E")]),
    # peak gust over the period: highest hourly 10 m gust estimate (m/s -> km/h). The WindGust-Max field runs
    # ~40-60% hotter than both this and TWC's hourly gusts, so it isn't used.
    "gust": dict(layer="RDPS_10km_WindGust_10m", unit="km/h", scale=3.6, mode="max",
                 bands=[(40, "#FFF1B8"), (50, "#FFDD7A"), (60, "#FDBD4F"), (70, "#F79A3E"), (80, "#EE7136"),
                        (90, "#DC4A33"), (100, "#B8303F"), (120, "#8C2452"), (140, "#5E1F5E")]),
}
TOWNS = {"St. John's": (47.561, -52.713), "Gander": (48.954, -54.609), "Corner Brook": (48.951, -57.952), "Port aux Basques": (47.572, -59.136), "St. Anthony": (51.364, -55.580),
         "Happy Valley-Goose Bay": (53.302, -60.417), "Labrador City": (52.946, -66.911), "Nain": (56.542, -61.692),
         "Churchill Falls": (53.528, -63.966), "Cartwright": (53.708, -57.021), "Marystown": (47.166, -55.148),
         "Halifax": (44.649, -63.575), "Sydney": (46.136, -60.194), "Charlottetown": (46.238, -63.131),
         "Moncton": (46.088, -64.778)}


def fetch(url, tries=5):
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def world(lat, lon):
    s = 512 * 2 ** ZOOM
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def px(lat, lon):
    (x, y), (cx, cy) = world(lat, lon), world(LAT0, LON0)
    return [round(x - cx + W / 2, 1), round(y - cy + H / 2, 1)]


def frame_lonlat():
    cx, cy = world(LAT0, LON0)
    s = 512 * 2 ** ZOOM
    xs = cx - W / 2 + np.arange(W) + .5
    ys = cy - H / 2 + np.arange(H) + .5
    return np.meshgrid(xs / s * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s)))))


def grid(layer, run, valid):
    box = BOX if ZOOM < 5 else dict(lat=(LAT0 - 9, LAT0 + 9), lon=(LON0 - 22, LON0 + 22))
    if layer.startswith("HRDPS"):
        box = dict(lat=(LAT0 - 4.5, LAT0 + 4.5), lon=(LON0 - 8, LON0 + 8))
    url = (f"{GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={layer}"
           f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat({box['lat'][0]},{box['lat'][1]})"
           f"&subset=lon({box['lon'][0]},{box['lon'][1]})&resolution=lat({RES})&resolution=lon({RES * 1.25})"
           f"&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    body = fetch(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    a = np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"]))
    return np.clip(a, 0, None), hdr


def nl_mask(ne_path, island_only=False):
    """1 inside Newfoundland and Labrador (Natural Earth admin-1, dilated a little so coasts aren't clipped)."""
    from matplotlib.path import Path
    from scipy.ndimage import binary_dilation
    with open(ne_path) as f:
        ft = next(ft for ft in json.load(f)["features"] if ft["properties"].get("name") == "Newfoundland and Labrador")
    g = ft["geometry"]
    LON, LAT = frame_lonlat()
    pts = np.column_stack([LON.ravel(), LAT.ravel()])
    inside = np.zeros(LON.size, bool)
    for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
        if len(poly[0]) >= 12 and not (island_only and max(la for lo, la in poly[0]) > 51.8):   # island: drop Labrador
            inside |= Path(np.array(poly[0])).contains_points(pts)
    return binary_dilation(inside.reshape(LON.shape), iterations=4).astype(float)


def outlines(ne_path):
    keep = ("Newfoundland and Labrador", "Québec", "Nova Scotia", "New Brunswick", "Prince Edward Island",
            "Maine", "Ontario", "Nunavut", "New Hampshire", "Vermont", "New York", "Massachusetts")
    with open(ne_path) as f:
        feats = [ft for ft in json.load(f)["features"] if ft["properties"].get("name") in keep]
    out = []
    for ft in feats:
        g = ft["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            if len(poly[0]) < 12:
                continue
            pts = [px(la, lo) for lo, la in poly[0]]
            kept = [pts[0]] + [p for a, p in zip(pts, pts[1:]) if abs(p[0] - a[0]) + abs(p[1] - a[1]) >= 1.2]
            out.append("M" + "L".join(f"{x:.0f},{y:.0f}" for x, y in kept) + "Z")
    return "".join(out)


def land_mask():
    """Soft land mask on the frame grid from Terrain-RGB (ocean tiles 404 and stay 0)."""
    LON, LAT = frame_lonlat()
    tz = int(min(9, max(6, round(ZOOM + 1.5))))
    wx = (LON + 180) / 360 * 256 * 2 ** tz
    wy = (1 - np.log(np.tan(np.pi / 4 + np.radians(LAT) / 2)) / np.pi) / 2 * 256 * 2 ** tz
    tx0, ty0, tx1, ty1 = int(wx.min() // 256), int(wy.min() // 256), int(wx.max() // 256), int(wy.max() // 256)
    m = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
    tok = os.environ["MAPBOX_ACCESS_TOKEN"]
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            try:
                png = fetch(f"https://api.mapbox.com/v4/mapbox.terrain-rgb/{tz}/{tx}/{ty}.pngraw?access_token={tok}")
            except urllib.error.HTTPError:
                continue
            rgb = imread(io.BytesIO(png), format="png")[..., :3] * 255
            m[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = -10000 + (rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]) * .1
    land = map_coordinates(m, [wy - ty0 * 256, wx - tx0 * 256], order=0) > 0.5
    return gaussian_filter(land.astype(float), 0.7)


SHIELD_REFS = {"1", "430", "360", "320", "210", "230", "480", "100", "500", "510", "520", "389", "516"}   # the rest drawn unlabelled


def roads_layer(view):
    """Highway paths (frame px) and shield candidates per route from roads-{view}.json."""
    path = os.path.join(HERE, f"roads-{view}.json")
    if not os.path.exists(path):
        return []
    out = {}
    for r in json.load(open(path)):
        pts = [px(la, lo) for lo, la in r["pts"]]
        if not any(-100 < x < W + 100 and -100 < y < H + 100 for x, y in pts):
            continue
        o = out.setdefault(r["ref"] or "", {"ref": r["ref"], "major": r["major"], "d": "", "cands": []})
        o["d"] += "M" + "L".join("%.1f,%.1f" % (x, y) for x, y in pts)
        o["major"] = o["major"] or r["major"]
        o["cands"] += [[round(x), round(y)] for x, y in pts[::4] if 40 < x < W - 40 and 40 < y < H - 40]
    for o in out.values():
        if o["ref"] not in SHIELD_REFS:
            o["cands"] = []
    for o in out.values():                                  # middle of the route first
        if o["cands"]:
            mx = sum(c[0] for c in o["cands"]) / len(o["cands"]); my = sum(c[1] for c in o["cands"]) / len(o["cands"])
            o["cands"].sort(key=lambda c: (c[0] - mx) ** 2 + (c[1] - my) ** 2)
            o["cands"] = o["cands"][:200]
    return list(out.values())


# on the combined map heavy rain stays green (the stock rain scale turns blue at 25 mm, which reads as snow)
MIX_RAIN_BANDS = [(2, "#CFEFC4"), (5, "#94D98A"), (10, "#4DBB5A"), (15, "#1F9447"), (25, "#0E6E36"),
                  (50, "#0A4A26"), (75, "#6A3FA6"), (100, "#A43C9C")]


SNOWPOT_CATS = [("Could accumulate", "#2367B3"), ("Flakes possible", "#8CC8EE")]   # RDPS-totals snow palette, no amounts


def snowpot_layer(run, t0, end, land, LON, LAT, sfx):
    """Where snow is possible, as categories only. Possible: any RDPS snow (>= 0.3 mm liquid) over the window, or a
    >= 20% GEPS chance of measurable snow (>= 2.5 mm snowfall in 24 h) in any 24 h window inside it. Likely: the RDPS
    accumulates wet snow (>= 2 mm liquid, roughly 2 cm) -- labelled "could accumulate", since the ensemble is less sure.
    Small specks are dropped."""
    from scipy.ndimage import label
    a1, hdr = grid("RDPS_10km_Snow-Accum", run, end)
    a0, _ = grid("RDPS_10km_Snow-Accum", run, t0)
    snow = np.clip(a1 - a0, 0, None)
    top = hdr["yllcorner"] + hdr["nrows"] * hdr["dy"]
    rows, cols = (top - LAT) / hdr["dy"] - .5, (LON - hdr["xllcorner"]) / hdr["dx"] - .5
    sv = map_coordinates(gaussian_filter(snow, 1.0), [rows, cols], order=1)
    caps = fetch(f"{GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer=GEPS.DIAG.24_SNMM.ERGE2.5").decode()
    grun = re.search(r'<Dimension name="reference_time"[^>]*default="([^"]+)"', caps).group(1)
    pmax = np.zeros(LON.shape)
    t = datetime.fromisoformat(t0.replace("Z", "+00:00")) + timedelta(hours=24)
    tend = datetime.fromisoformat(end.replace("Z", "+00:00"))
    while t <= tend:
        try:
            body = fetch(f"{GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId=GEPS.DIAG.24_SNMM.ERGE2.5"
                         f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat(44,54)&subset=lon(-62,-50)"
                         f"&time={t.strftime('%Y-%m-%dT%H:%M:%SZ')}&DIM_REFERENCE_TIME={grun}&format=image/x-aaigrid").decode("latin1")
            g = body.split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
            h, i = {}, 0
            while re.match(r"^[a-zA-Z_]+\s", g[i]):
                k, v = g[i].split()[:2]; h[k.lower()] = float(v); i += 1
            cs = h.get("cellsize", h.get("dy"))
            ga = np.array(" ".join(g[i:]).split(), float).reshape(int(h["nrows"]), int(h["ncols"]))
            gt = h["yllcorner"] + h["nrows"] * cs
            pmax = np.maximum(pmax, map_coordinates(gaussian_filter(ga, 1.0), [(gt - LAT) / cs - .5, (LON - h["xllcorner"]) / cs - .5], order=1))
        except (IndexError, urllib.error.HTTPError):
            print("GEPS window missing", t)
        t += timedelta(hours=12)
    cat = np.zeros(LON.shape, int)                                  # 0 none, 1 possible, 2 likely
    cat[(sv >= 0.3) | (pmax >= 20)] = 1
    cat[sv >= 2.0] = 2
    cat[land < .5] = 0
    for k in (1, 2):                                                # drop specks smaller than ~25 km across
        comps, n = label(cat >= k)
        for i in range(1, n + 1):
            m = comps == i
            if m.sum() < 1500:
                cat[m & (cat >= k)] = k - 1
    rgba = np.zeros(LON.shape + (4,))
    for k, (name, col) in zip((2, 1), SNOWPOT_CATS):
        rgba[cat == k, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        rgba[cat == k, 3] = 0.82
    rgba[..., 3] *= land
    imsave(os.path.join(HERE, f"snowpot-shade{sfx}.png"), rgba)
    towns = {}
    for n, (la, lo) in TOWNS.items():
        x, y = px(la, lo)
        xi, yi = int(min(max(x, 0), W - 1)), int(min(max(y, 0), H - 1))
        towns[n] = int(cat[yi, xi])
    print("snowpot: GEPS run", grun, "max chance", round(float(pmax[land > .5].max()), 1), "%  RDPS snow max",
          round(float(sv[land > .5].max()), 1), "mm  cells possible/likely", int((cat == 1).sum()), int((cat == 2).sum()))
    return {"cats": SNOWPOT_CATS, "towns": towns, "geps_run": grun}


def mix_layer(run, t0, end, land, LON, LAT, sfx, layers=None):
    """Rain and snow on one map. Each spot takes the type that dominates by liquid equivalent and is shaded
    on that type's scale (rain mm / snow cm). Also returns the rain/snow boundary and per-town rain + snow."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    tot = {}
    for kind in ("rain", "snow"):
        layer = (layers or {}).get(kind, KINDS[kind]["layer"])     # HRDPS views pass their own accumulation layers
        a1, hdr = grid(layer, run, end)
        a0, _ = grid(layer, run, t0)
        tot[kind] = np.clip(a1 - a0, 0, None)                     # liquid mm
    top = hdr["yllcorner"] + hdr["nrows"] * hdr["dy"]
    rows, cols = (top - LAT) / hdr["dy"] - .5, (LON - hdr["xllcorner"]) / hdr["dx"] - .5
    rain = map_coordinates(gaussian_filter(tot["rain"], 0.8), [rows, cols], order=1)
    snow_liq = map_coordinates(gaussian_filter(tot["snow"], 0.8), [rows, cols], order=1)
    snow_cm = snow_liq * KINDS["snow"]["scale"]
    is_snow = snow_liq > rain
    rgba = np.zeros(rain.shape + (4,))
    for bands, field, sel in ((MIX_RAIN_BANDS, rain, ~is_snow), (KINDS["snow"]["bands"], snow_cm, is_snow)):
        for lo, col in bands:
            m = sel & (field >= lo)
            rgba[m, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            rgba[m, 3] = 0.85
    rgba[..., 3] *= land
    imsave(os.path.join(HERE, f"mix-shade{sfx}.png"), rgba)
    # rain/snow line: where the dominant type flips, drawn only across land (not around the coast/border)
    fig, ax = plt.subplots()
    cs = ax.contour(gaussian_filter(is_snow.astype(float), 2.0), levels=[.5])
    on = gaussian_filter(land, 3) > .6
    segs = []
    for p in cs.get_paths():
        for pp in p.to_polygons(closed_only=False):
            cur = []
            for x, y in pp[::3]:
                xi, yi = int(min(max(x, 0), W - 1)), int(min(max(y, 0), H - 1))
                if on[yi, xi] and (rain[yi, xi] + snow_liq[yi, xi]) >= 2:
                    cur.append((x, y))
                else:
                    if len(cur) > 6:
                        segs.append(cur)
                    cur = []
            if len(cur) > 6:
                segs.append(cur)
    line = "".join("M" + "L".join(f"{x:.0f},{y:.0f}" for x, y in sg) for sg in segs)
    plt.close(fig)
    towns = {}
    for n, (la, lo) in TOWNS.items():
        r, c = (top - la) / hdr["dy"] - .5, (lo - hdr["xllcorner"]) / hdr["dx"] - .5
        rv, sv = (float(map_coordinates(gaussian_filter(tot[k], 0.8), [[r], [c]], order=1)[0]) for k in ("rain", "snow"))
        towns[n] = [round(rv), round(sv * KINDS["snow"]["scale"])]
    print("mix", towns)
    return {"rain_bands": MIX_RAIN_BANDS, "snow_bands": KINDS["snow"]["bands"], "line": line, "towns": towns}


SNOWMIX_CATS = [("Mix possible", "#B565C9"), ("Rain likely", "#7FCB7A")]


def snowmix_layer(run, t0, end, land, LON, LAT, sfx):
    """Snow amounts where snow dominates, and where precipitation is a mix or mostly rain instead.
    By liquid equivalent over the window: snow >= 70% of it (and ice under 30%) -> snow, shaded in cm; under 30% snow
    -> rain likely; in between, or freezing rain / ice pellets >= 30% -> mix possible. Under 0.3 mm total: nothing."""
    tot = {}
    for k, layer in (("r", "RDPS_10km_Rain-Accum"), ("s", "RDPS_10km_Snow-Accum"),
                     ("z", "RDPS_10km_FreezingRain-Accum"), ("i", "RDPS_10km_IcePellets-Accum")):
        a1, hdr = grid(layer, run, end)
        a0, _ = grid(layer, run, t0)
        tot[k] = np.clip(a1 - a0, 0, None)
    top = hdr["yllcorner"] + hdr["nrows"] * hdr["dy"]
    rows, cols = (top - LAT) / hdr["dy"] - .5, (LON - hdr["xllcorner"]) / hdr["dx"] - .5
    up = {k: np.clip(map_coordinates(gaussian_filter(v, 1.0), [rows, cols], order=3), 0, None) for k, v in tot.items()}
    T = up["r"] + up["s"] + up["z"] + up["i"]
    fs, fi = up["s"] / np.maximum(T, 1e-6), (up["z"] + up["i"]) / np.maximum(T, 1e-6)
    wet = T >= 0.3
    snow = wet & (fs >= .7) & (fi < .3)
    rain = wet & (fs < .3) & (fi < .3)
    mix = wet & ~snow & ~rain
    cm = up["s"] * KINDS["snow"]["scale"]
    rgba = np.zeros(T.shape + (4,))
    for lo, col in [(0, "#EEF7FC")] + KINDS["snow"]["bands"]:      # under 1 cm: a faint wash, so snow areas read as snow
        m = snow & (cm >= lo)
        rgba[m, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        rgba[m, 3] = 0.85
    yy, xx = np.indices(T.shape)
    stripe = ((xx + yy) // 7) % 3 == 0                              # diagonal hatching for the mix zone
    for m, col, a in ((mix & stripe, "#8E3E9E", .9), (mix & ~stripe, SNOWMIX_CATS[0][1], .55), (rain, SNOWMIX_CATS[1][1], .7)):
        rgba[m, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        rgba[m, 3] = a
    rgba[..., 3] *= land
    imsave(os.path.join(HERE, f"snowmix-shade{sfx}.png"), rgba)
    towns = {}
    for n, (la, lo) in TOWNS.items():
        r, c = (top - la) / hdr["dy"] - .5, (lo - hdr["xllcorner"]) / hdr["dx"] - .5
        tv = {k: float(map_coordinates(gaussian_filter(v, 1.0), [[r], [c]], order=1)[0]) for k, v in tot.items()}
        t = sum(tv.values())
        f_s, f_i = tv["s"] / max(t, 1e-6), (tv["z"] + tv["i"]) / max(t, 1e-6)
        cls = "dry" if t < .3 else "snow" if f_s >= .7 and f_i < .3 else "rain" if f_s < .3 and f_i < .3 else "mix"
        towns[n] = [round(tv["s"] * KINDS["snow"]["scale"], 1), round(tv["r"] + tv["z"] + tv["i"], 1), cls]
    print("snowmix", towns)
    return {"unit": "cm", "bands": KINDS["snow"]["bands"], "cats": SNOWMIX_CATS, "towns": towns}


def main(ne_path, view="nl", start_at=None, end_at=None):
    global LON0, LAT0, ZOOM, TOWNS, W, H
    v = VIEWS[view]
    W, H = v.get("size", (1920, 1080))
    if isinstance(v.get("towns"), str):                    # share another view's town list ("+avalon": add Ferryland, Trepassey)
        base, *extra = v["towns"].split("+")
        v = dict(v, towns=dict(VIEWS[base]["towns"], **{k: ll for e in extra for k, ll in TOWN_EXTRA[e].items()}))
    (LON0, LAT0), ZOOM = v["center"], v["zoom"]
    if v["towns"]:
        TOWNS = v["towns"]
    sfx = v["suffix"]
    global RES
    RES = 0.08 if ZOOM < 5.5 else 0.05
    hr = VIEWS[view].get("model") == "HRDPS"
    if hr:
        RES = 0.025
    caps = fetch(f"{GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer="
                 f"{'HRDPS.CONTINENTAL_SN' if hr else 'RDPS_10km_Rain-Accum'}").decode()
    run = re.search(r'<Dimension name="reference_time"[^>]*default="([^"]+)"', caps).group(1)
    end = re.search(r'<Dimension name="time"[^>]*>([^<]+)</Dimension>', caps).group(1).split("/")[1]
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = max(now, datetime.fromisoformat(run.replace("Z", "+00:00")) + timedelta(hours=1))
    if start_at:
        start = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
    if end_at:
        end = end_at
    t0 = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    land = land_mask()
    if VIEWS[view].get("only_nl"):
        land = land * nl_mask(ne_path, VIEWS[view].get("only_nl") == "island")

    LON, LAT = frame_lonlat()
    out = {"run": run, "from": start.astimezone(NDT).strftime("%a %-I:%M %p NDT"),
           "to": datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(NDT).strftime("%a %-I:%M %p NDT"),
           "towns": {}, "kinds": {}}
    for kind in VIEWS[view].get("kinds", ["rain", "snow"]):
        if kind == "mix":
            out["kinds"]["mix"] = mix_layer(run, t0, end, land, LON, LAT, sfx,
                                            {"rain": "HRDPS.CONTINENTAL_RN", "snow": "HRDPS.CONTINENTAL_SN"} if hr else None)
            continue
        if kind == "snowmix":
            out["kinds"]["snowmix"] = snowmix_layer(run, t0, end, land, LON, LAT, sfx)
            continue
        if kind == "snowpot":
            out["kinds"]["snowpot"] = snowpot_layer(run, t0, end, land, LON, LAT, sfx)
            continue
        k = dict(KINDS[kind])
        if hr:
            k["layer"] = {"rain": "HRDPS.CONTINENTAL_RN", "snow": "HRDPS.CONTINENTAL_SN"}.get(kind, k["layer"])
        if kind == "snow" and VIEWS[view].get("snow_ratio"):
            k["scale"] = VIEWS[view]["snow_ratio"] / 10
        if k.get("mode") == "max":
            t, tend, tot = start + timedelta(hours=1), datetime.fromisoformat(end.replace("Z", "+00:00")), None
            while t <= tend:
                a, hdr = grid(k["layer"], run, t.strftime("%Y-%m-%dT%H:%M:%SZ"))
                tot = a if tot is None else np.maximum(tot, a)
                t += timedelta(hours=1)
            tot = tot * k["scale"]
        else:
            a1, hdr = grid(k["layer"], run, end)
            a0, _ = grid(k["layer"], run, t0)
            tot = np.clip(a1 - a0, 0, None) * k["scale"]
        top = hdr["yllcorner"] + hdr["nrows"] * hdr["dy"]
        rows, cols = (top - LAT) / hdr["dy"] - .5, (LON - hdr["xllcorner"]) / hdr["dx"] - .5
        v = map_coordinates(gaussian_filter(tot, 0.8), [rows, cols], order=1)
        rgba = np.zeros(v.shape + (4,))
        for lo, col in k["bands"]:
            sel = v >= lo
            rgba[sel, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            rgba[sel, 3] = 0.82
        rgba[..., 3] *= land
        imsave(os.path.join(HERE, f"{kind}-shade{sfx}.png"), rgba)
        towns = {}
        for n, (la, lo) in TOWNS.items():
            r, c = (top - la) / hdr["dy"] - .5, (lo - hdr["xllcorner"]) / hdr["dx"] - .5
            towns[n] = round(float(map_coordinates(gaussian_filter(tot, 0.8), [[r], [c]], order=1)[0]), 1)
        towns.update(VIEWS[view].get("override", {}).get(kind, {}))
        out["kinds"][kind] = {"unit": k["unit"], "bands": k["bands"], "towns": towns}
        print(kind, "max", round(float(v.max()), 1), towns)
    out["xy"] = {n: px(*ll) for n, ll in TOWNS.items()}
    out["note"] = VIEWS[view].get("note", "")
    out["model"] = "HRDPS 2.5 km" if hr else "RDPS 10 km"
    out["ratio"] = VIEWS[view].get("snow_ratio", SNOW_RATIO)
    out["outlines"] = outlines(ne_path)
    out["roads"] = sum((roads_layer(r) for r in VIEWS[view].get("roads", [view])), [])
    with open(os.path.join(HERE, f"data{sfx}.js"), "w") as f:
        f.write("// generated by build.py\nwindow.TOT = " + json.dumps(out) + ";\n")
    with open(os.path.join(HERE, f"map{sfx}.png"), "wb") as f:   # (W/2)x(H/2) @2x == WxH at ZOOM
        f.write(fetch(f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM - 1:.3f},0/{W // 2}x{H // 2}@2x"
                      f"?attribution=false&logo=false&layer_id=state-label&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D"   # hide province/state names
                      f"&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"))
    print(out["from"], "->", out["to"], "run", run)


if __name__ == "__main__":
    main(*sys.argv[1:5])
