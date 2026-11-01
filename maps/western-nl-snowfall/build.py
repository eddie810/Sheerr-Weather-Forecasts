"""Build the western Newfoundland snowfall contour map from the RDPS model.

Pulls RDPS 10 km accumulated snow (liquid equivalent, mm) from MSC GeoMet's WCS,
converts to snowfall at SNOW_RATIO:1, weights it by elevation, contours it, and lays it over a Mapbox basemap with
hillshading computed from Mapbox Terrain-RGB so the Long Range Mountains show.

  MAPBOX_ACCESS_TOKEN=... python3 build.py RUN VALID ne_10m_admin_1_states_provinces.geojson [wide|tight]
  e.g. python3 build.py 2026-10-10T06:00:00Z 2026-10-13T00:00:00Z ne.geojson tight
"""
import io
import json
import math
import os
import re
import sys
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.image import imread  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LAYER = "RDPS_10km_Snow-Accum"
BBOX = dict(lat=(46.0, 53.0), lon=(-62.5, -52.0))       # data request
W, H = 1080, 900                                          # map frame (CSS px)
LEVELS = [2, 5, 10, 15, 20, 30, 1000]                    # cm band edges
SNOW_RATIO = 8                                           # cm of snow per mm of water x10 (wet snow near 0C)
# Elevation weighting: the 10 km model can't resolve terrain, so snow is scaled from
# 0 at SNOW_FLOOR_M up to the full model amount at SNOW_FULL_M (rain/melt near sea level).
SNOW_FLOOR_M, SNOW_FULL_M = 150, 350
VIEWS = {
    # whole western half of the Island
    "wide": dict(center=(-57.35, 49.42), zoom=6.55, terrain_zoom=9, suffix="",
        towns={
            "Port aux Basques": (47.572, -59.136), "Stephenville": (48.550, -58.581),
            "Corner Brook": (48.951, -57.952), "Deer Lake": (49.174, -57.426),
            "Rocky Harbour": (49.660, -57.912), "Port au Choix": (50.709, -57.331),
            "St. Anthony": (51.364, -55.580), "Baie Verte": (49.932, -56.180),
            "Burgeo": (47.617, -57.621)},
        peaks={"Gros Morne": (49.594, -57.785), "Lewis Hills": (48.829, -58.490)}),
    # Long Range Mountains, Corner Brook to Port au Choix
    "tight": dict(center=(-57.30, 49.78), zoom=7.62, terrain_zoom=10, suffix="-tight",
        towns={
            "Corner Brook": (48.951, -57.952), "Deer Lake": (49.174, -57.426),
            "Woody Point": (49.503, -57.917), "Rocky Harbour": (49.660, -57.912),
            "Cow Head": (49.920, -57.801), "Parson's Pond": (50.030, -57.712),
            "Daniel's Harbour": (50.236, -57.580), "Port au Choix": (50.709, -57.331),
            "Hampden": (49.546, -56.853), "Jackson's Arm": (49.870, -56.780),
            "Baie Verte": (49.932, -56.180)},
        peaks={"Gros Morne": (49.594, -57.785), "Tablelands": (49.468, -57.958),
               "Lewis Hills": (48.829, -58.490)}),
}
LON0, LAT0, ZOOM, TOWNS, PEAKS = None, None, None, {}, {}


def wcs_grid(run, valid):
    url = ("https://geo.weather.gc.ca/geomet?service=WCS&version=2.0.1&request=GetCoverage"
           f"&coverageId={LAYER}&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326"
           f"&subset=lat({BBOX['lat'][0]},{BBOX['lat'][1]})&subset=lon({BBOX['lon'][0]},{BBOX['lon'][1]})"
           "&resolution=lat(0.03)&resolution=lon(0.045)"
           f"&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    raw = urllib.request.urlopen(url, timeout=180).read().decode("latin1")
    body = raw.split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    a = np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"]))
    a[a < -1000] = 0  # NODATA over the frame edge
    lons = hdr["xllcorner"] + hdr["dx"] * (np.arange(a.shape[1]) + 0.5)
    lats = hdr["yllcorner"] + hdr["dy"] * (np.arange(a.shape[0]) + 0.5)
    return lons, lats[::-1], a  # first row is the northern edge


# --- Web Mercator helpers (Mapbox static zoom is 512px-tile based) ---
def world_px(lat, lon, z):
    s = 512 * 2 ** z
    x = (lon + 180) / 360 * s
    y = (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s
    return x, y


def projector():
    cx, cy = world_px(LAT0, LON0, ZOOM)
    return lambda la, lo: (world_px(la, lo, ZOOM)[0] - cx + W / 2, world_px(la, lo, ZOOM)[1] - cy + H / 2)


def terrain_tile(tz, tx, ty):
    """Elevation (m) for one 256px Mapbox Terrain-RGB tile."""
    url = f"https://api.mapbox.com/v4/mapbox.terrain-rgb/{tz}/{tx}/{ty}.pngraw?access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"
    rgb = imread(io.BytesIO(urllib.request.urlopen(url, timeout=60).read()), format="png")[..., :3] * 255
    return -10000 + (rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]) * 0.1


def elevation_grid(lons, lats, tz=8):
    """Elevation (m) at each point of the model grid, sampled from Terrain-RGB."""
    wx = lambda lo: (lo + 180) / 360 * 256 * 2 ** tz
    wy = lambda la: (1 - np.log(np.tan(np.pi / 4 + np.radians(la) / 2)) / np.pi) / 2 * 256 * 2 ** tz
    tx0, tx1 = int(wx(lons.min()) // 256), int(wx(lons.max()) // 256)
    ty0, ty1 = int(wy(lats.max()) // 256), int(wy(lats.min()) // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = terrain_tile(tz, tx, ty)
    LO, LA = np.meshgrid(lons, lats)
    return np.maximum(map_coordinates(mosaic, [wy(LA) - ty0 * 256, wx(LO) - tx0 * 256], order=1), 0)


def hillshade(path, scale=2, tz=9):
    """Hillshade PNG for the frame from Mapbox Terrain-RGB (256px tiles at zoom tz)."""
    cx, cy = world_px(LAT0, LON0, ZOOM)
    k = 2 ** (tz - ZOOM) / 2                      # frame CSS px -> 256px-tile world px at tz
    x0, y0 = (cx - W / 2) * k, (cy - H / 2) * k
    x1, y1 = (cx + W / 2) * k, (cy + H / 2) * k
    tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = terrain_tile(tz, tx, ty)
    mosaic = np.maximum(mosaic, 0)
    # metres per pixel at the frame's latitude
    mpp = 40075016.686 * math.cos(math.radians(LAT0)) / (256 * 2 ** tz)
    dy, dx = np.gradient(gaussian_filter(mosaic, 1.0), mpp)
    az, alt = math.radians(315), math.radians(40)
    slope = np.arctan(np.hypot(dx, dy) * 1.6)     # mild vertical exaggeration
    aspect = np.arctan2(-dx, dy)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    # resample to the output frame
    ys, xs = np.mgrid[0:H * scale, 0:W * scale]
    wx = x0 + xs / scale * k - tx0 * 256
    wy = y0 + ys / scale * k - ty0 * 256
    sh = map_coordinates(shade, [wy, wx], order=1)
    el = map_coordinates(mosaic, [wy, wx], order=1)
    flat = math.sin(alt)
    dark = np.clip((flat - sh) * 2.2, 0, 1)        # shadows only, flat ground transparent
    light = np.clip((sh - flat) * 1.2, 0, 1)
    rgba = np.zeros((H * scale, W * scale, 4))
    rgba[..., :3] = np.where(dark[..., None] > 0, [0.18, 0.24, 0.27], [1, 1, 1])
    rgba[..., 3] = np.where(el > 0, np.maximum(dark * 0.8, light * 0.45), 0)
    plt.imsave(path, rgba)


def svg_path(rings_lonlat, proj, min_px=0.8):
    out = []
    for ring in rings_lonlat:
        pts = [proj(la, lo) for lo, la in ring]
        kept = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - kept[-1][0]) + abs(p[1] - kept[-1][1]) >= min_px:
                kept.append(p)
        if len(kept) > 2:
            out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in kept) + "Z")
    return "".join(out)


def contour_bands(lons, lats, cm, proj):
    fig, ax = plt.subplots()
    cs = ax.contourf(lons, lats, cm, levels=LEVELS)
    bands = [{"from": lvl, "d": svg_path([p.tolist() for p in path.to_polygons()], proj)}
             for lvl, path in zip(LEVELS[:-1], cs.get_paths())]
    cl = ax.contour(lons, lats, cm, levels=LEVELS[:-1])
    lines = [{"level": lvl, "d": svg_path([p.tolist() for p in path.to_polygons(closed_only=False)], proj).replace("Z", "")}
             for lvl, path in zip(LEVELS[:-1], cl.get_paths())]
    plt.close(fig)
    return bands, lines


def main(run, valid, ne_path, view="wide"):
    global LON0, LAT0, ZOOM, TOWNS, PEAKS
    v = VIEWS[view]
    (LON0, LAT0), ZOOM, TOWNS, PEAKS = v["center"], v["zoom"], v["towns"], v["peaks"]
    out = lambda name, ext: os.path.join(HERE, f"{name}{v['suffix']}.{ext}")
    lons, lats, mm = wcs_grid(run, valid)
    cm = gaussian_filter(mm, sigma=1.0) * SNOW_RATIO / 10   # RDPS is already smooth at 10 km
    elev = elevation_grid(lons, lats)
    cm = cm * np.clip((elev - SNOW_FLOOR_M) / (SNOW_FULL_M - SNOW_FLOOR_M), 0, 1)
    proj = projector()
    bands, lines = contour_bands(lons, lats, cm, proj)

    def at(la, lo):
        return float(cm[int(np.argmin(np.abs(lats - la))), int(np.argmin(np.abs(lons - lo)))])

    with open(ne_path) as f:
        nl = next(ft["geometry"] for ft in json.load(f)["features"]
                  if ft["properties"].get("name") == "Newfoundland and Labrador")
    island, labrador = [], []
    for poly in nl["coordinates"]:
        ring = poly[0]
        if len(ring) < 30:
            continue
        (island if max(la for _, la in ring) < 51.7 and min(lo for lo, _ in ring) > -59.6 else labrador).append(ring)

    data = {
        "run": run, "valid": valid, "ratio": SNOW_RATIO, "floor_m": SNOW_FLOOR_M, "full_m": SNOW_FULL_M,
        "bands": bands, "lines": lines,
        "island": svg_path(island, proj),
        "labrador": svg_path(labrador, proj),
        "towns": {n: {"xy": [round(v) for v in proj(*ll)], "cm": round(at(*ll))} for n, ll in TOWNS.items()},
        "peaks": {n: {"xy": [round(v) for v in proj(*ll)], "cm": round(at(*ll))} for n, ll in PEAKS.items()},
    }
    with open(out("contours", "js"), "w") as f:
        f.write("// generated by build.py\nwindow.SNOW = " + json.dumps(data) + ";\n")

    url = (f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM},0/"
           f"{W}x{H}@2x?attribution=false&logo=false&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}")
    urllib.request.urlretrieve(url, out("map", "png"))
    hillshade(out("hillshade", "png"), tz=v["terrain_zoom"])
    print({n: v["cm"] for n, v in {**data["towns"], **data["peaks"]}.items()}, "max", round(float(cm.max()), 1))


if __name__ == "__main__":
    main(*sys.argv[1:5])
