"""Build tonight's aurora graphic for Newfoundland & Labrador and the Maritimes.

  - Aurora: NOAA SWPC OVATION model (latest nowcast probability of visible aurora overhead)
  - Storm strength: NOAA planetary Kp (observed/estimated + forecast)
  - Clouds: HRDPS total cloud cover, averaged over the evening viewing window (MSC GeoMet)
  - Basemap: Mapbox dark

  MAPBOX_ACCESS_TOKEN=... python3 build.py ne_10m_admin_1_states_provinces.geojson
"""
import json
import math
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
from matplotlib.image import imsave
from scipy.ndimage import gaussian_filter, map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 800
LON0, LAT0, ZOOM = -60.6, 50.6, 4.62
NDT = timezone(timedelta(hours=-2, minutes=-30))
SWPC = "https://services.swpc.noaa.gov"
HORIZON_P, HORIZON_DEG = 10, 8            # view line: 10% overhead probability up to 8 deg latitude north

TOWNS = {
    "Nain": (56.54, -61.69), "Happy Valley-Goose Bay": (53.30, -60.42), "Labrador City": (52.95, -66.91),
    "St. Anthony": (51.36, -55.58), "Corner Brook": (48.95, -57.95), "Gander": (48.95, -54.61),
    "St. John's": (47.56, -52.71), "Sydney": (46.14, -60.19), "Halifax": (44.65, -63.57),
    "Charlottetown": (46.24, -63.13), "Moncton": (46.09, -64.78), "Fredericton": (45.96, -66.64),
}
# cloud summary boxes (lat0, lat1, lon0, lon1)
REGIONS = {
    "Labrador": [(54.5, 58.5, -64, -58), (52, 54.5, -67, -58), (51.5, 53.5, -58, -55.5)],
    "Newfoundland": [(48.5, 51.5, -59.5, -55.5), (48, 49.8, -57, -54), (46.6, 48.6, -54.5, -52.6)],
    "Maritimes": [(43.5, 46, -66, -60), (45, 48, -68, -64), (45.9, 47, -64.5, -62), (45.6, 47, -61.5, -59.8)],
}


def fetch(url, tries=5):
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def frame_lonlat(scale):
    s = 512 * 2 ** ZOOM
    cx = (LON0 + 180) / 360 * s
    cy = (1 - math.log(math.tan(math.pi / 4 + math.radians(LAT0) / 2)) / math.pi) / 2 * s
    xs = (cx - W / 2) + (np.arange(W * scale) + 0.5) / scale
    ys = (cy - H / 2) + (np.arange(H * scale) + 0.5) / scale
    return np.meshgrid(xs / s * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s)))))


def xy(lat, lon):
    s = 512 * 2 ** ZOOM
    px = lambda la, lo: ((lo + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(la) / 2)) / math.pi) / 2 * s)
    (x, y), (cx, cy) = px(lat, lon), px(LAT0, LON0)
    return [round(x - cx + W / 2), round(y - cy + H / 2)]


def lerp(c0, c1, t):
    return c0 + (c1 - c0) * t[..., None]


def aurora_layer(LON, LAT):
    o = json.loads(fetch(f"{SWPC}/json/ovation_aurora_latest.json"))
    g = np.zeros((181, 360))
    for lon, lat, v in o["coordinates"]:
        g[int(lat) + 90, int(lon) % 360] = v
    g[:90 + 30] = 0                                    # ignore stray low-latitude cells; aurora lives poleward of 30N
    g = gaussian_filter(g, 0.8)
    p = map_coordinates(g, [LAT + 90, LON % 360], order=1, mode="wrap")
    t = np.clip(p / 100, 0, 1)
    green, mint, pink = np.array([.16, .86, .55]), np.array([.62, 1, .80]), np.array([.90, .45, .85])
    rgb = np.where((t < .5)[..., None], lerp(green, mint, t / .5), lerp(mint, pink, (t - .5) / .5))
    alpha = np.clip((p - 4) / 45, 0, 1) * 0.85

    # Seen from the ground, aurora 100-300 km up shows on the northern horizon well south of the
    # oval. Horizon zone: anywhere with >= HORIZON_P% overhead probability within HORIZON_DEG of
    # latitude to the north (about 900 km). Its southern edge is the view line.
    north = np.max([np.roll(g, -k, axis=0) for k in range(HORIZON_DEG + 1)], axis=0)
    hz = gaussian_filter((north >= HORIZON_P).astype(float), 1.0)
    h = map_coordinates(hz, [LAT + 90, LON % 360], order=1, mode="wrap")
    zone = np.dstack([np.broadcast_to(green, h.shape + (3,)), np.clip((h - .5) * 4, 0, 1) * 0.22])
    # view-line latitude across Atlantic Canada (for the caption when the line falls off the map)
    edges = []
    for lon in range(-68, -51):
        col = g[:, lon % 360]
        peak = 45 + int(np.argmax(col[90 + 45:90 + 76]))              # centre of the oval
        edges.append(next(la for la in range(peak, 30, -1) if col[la + 90] < HORIZON_P) + 1 - HORIZON_DEG)
    return np.dstack([rgb, alpha]), zone, h, o["Forecast Time"], round(float(np.mean(edges)))


def cloud_grid(times):
    grids = []
    for t in times:
        raw = fetch("https://geo.weather.gc.ca/geomet?service=WCS&version=2.0.1&request=GetCoverage"
                    "&coverageId=HRDPS.CONTINENTAL_NT&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326"
                    "&subset=lat(38,64)&subset=lon(-80,-38)&resolution=lat(0.05)&resolution=lon(0.07)"
                    f"&time={t}&format=image/x-aaigrid").decode("latin1")
        body = raw.split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
        hdr, i = {}, 0
        while re.match(r"^[a-zA-Z_]+\s", body[i]):
            k, v = body[i].split()[:2]
            hdr[k.lower()] = float(v)
            i += 1
        grids.append(np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"])))
    return np.clip(np.mean(grids, 0), 0, 100), hdr


def outlines(ne_path):
    """Province outlines (Natural Earth) as one SVG path in frame pixels."""
    with open(ne_path) as f:
        feats = [ft for ft in json.load(f)["features"] if ft["properties"].get("adm0_a3") in ("CAN", "USA")
                 and ft["properties"].get("name") in ("Newfoundland and Labrador", "Québec", "Nova Scotia",
                                                       "New Brunswick", "Prince Edward Island", "Maine")]
    out = []
    for ft in feats:
        g = ft["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            ring = poly[0]
            if len(ring) < 15:
                continue
            pts = [xy(la, lo) for lo, la in ring]
            kept = [pts[0]] + [p for a, p in zip(pts, pts[1:]) if abs(p[0] - a[0]) + abs(p[1] - a[1]) >= 1]
            if len(kept) > 3:
                out.append("M" + "L".join(f"{x},{y}" for x, y in kept) + "Z")
    return "".join(out)


def main(ne_path):
    LON, LAT = frame_lonlat(2)
    aurora, zone, h, ovation_time, viewline_lat = aurora_layer(LON, LAT)
    imsave(os.path.join(HERE, "aurora.png"), aurora)
    imsave(os.path.join(HERE, "horizon.png"), zone)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    cs = ax.contour(h[::2, ::2], levels=[0.5])           # back to CSS px (layers are 2x)
    viewline = "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in poly)
                       for path in cs.get_paths() for poly in path.to_polygons(closed_only=False) if len(poly) > 20)
    plt.close(fig)

    now = datetime.now(timezone.utc)
    t0 = (now + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    t0 += timedelta(hours=-t0.hour % 3)                          # first 3-hourly step after dark, and the next one
    times = [(t0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ") for h in (0, 3)]
    cloud, hdr = cloud_grid(times)
    top = hdr["yllcorner"] + hdr["nrows"] * hdr["dy"]
    c = map_coordinates(gaussian_filter(cloud, 2), [(top - LAT) / hdr["dy"] - .5, (LON - hdr["xllcorner"]) / hdr["dx"] - .5],
                        order=1, cval=0)
    veil = np.dstack([np.full(c.shape, .86), np.full(c.shape, .89), np.full(c.shape, .92),
                      np.clip((c - 45) / 55, 0, 1) * 0.5])
    imsave(os.path.join(HERE, "clouds.png"), veil)

    lats = (hdr["yllcorner"] + hdr["dy"] * (np.arange(cloud.shape[0]) + .5))[::-1]
    lons = hdr["xllcorner"] + hdr["dx"] * (np.arange(cloud.shape[1]) + .5)
    def box(la0, la1, lo0, lo1):
        return float(cloud[np.ix_((lats >= la0) & (lats <= la1), (lons >= lo0) & (lons <= lo1))].mean())
    region_cloud = {n: round(float(np.mean([box(*b) for b in boxes]))) for n, boxes in REGIONS.items()}

    kp = [r for r in json.loads(fetch(f"{SWPC}/products/noaa-planetary-k-index-forecast.json")) if isinstance(r, dict)]
    def block(t):
        start = datetime.fromisoformat(t["time_tag"]).replace(tzinfo=timezone.utc)
        end = start + timedelta(hours=3)
        f = lambda d: d.astimezone(NDT).strftime("%-I:%M %p").replace(":00", "")
        return {"from": f(start), "to": f(end), "kp": t["kp"], "scale": t["noaa_scale"], "kind": t["observed"],
                "start": start.isoformat()}
    tonight = [block(t) for t in kp
               if datetime.fromisoformat(t["time_tag"]).replace(tzinfo=timezone.utc) + timedelta(hours=3) > now + timedelta(hours=1)][:4]
    peak = max((t for t in kp if t["observed"] in ("observed", "estimated")
                and datetime.fromisoformat(t["time_tag"]).replace(tzinfo=timezone.utc) >= now - timedelta(hours=12)),
               key=lambda t: t["kp"])

    with open(os.path.join(HERE, "map.png"), "wb") as f:
        f.write(fetch(f"https://api.mapbox.com/styles/v1/mapbox/dark-v11/static/{LON0},{LAT0},{ZOOM},0/{W}x{H}@2x"
                      f"?attribution=false&logo=false&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"))
    ov = datetime.fromisoformat(ovation_time.replace("Z", "+00:00")).astimezone(NDT)
    data = {
        "date": now.astimezone(NDT).strftime("%A, %B %-d"),
        "peak": {"kp": peak["kp"], "scale": peak["noaa_scale"]},
        "kp": tonight, "clouds": region_cloud,
        "cloud_times": [datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(NDT).strftime("%-I:%M %p") for t in times],
        "ovation": ov.strftime("%-I:%M %p NDT"),
        "towns": {n: xy(*ll) for n, ll in TOWNS.items()},
        "outlines": outlines(ne_path), "viewline": viewline, "viewline_lat": viewline_lat,
    }
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.AURORA = " + json.dumps(data) + ";\n")
    print(json.dumps({k: data[k] for k in ("peak", "kp", "clouds", "cloud_times", "ovation")}, indent=1))


if __name__ == "__main__":
    import sys
    main(sys.argv[1])
