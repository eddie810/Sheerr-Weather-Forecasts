"""Halloween night forecast for Newfoundland and Labrador (16:9 video): 7 PM Saturday, Oct 31.

Town temperatures, conditions and wind come from The Weather Company hourly forecast (the 7:30 PM NDT hour, the one
nearest 7 PM, since TWC's NL hours fall on the half hour). The rain / snow shading is RDPS (ECCC) precipitation in the
hour 6:30-7:30 PM (21Z-22Z), split by type, masked to land. The basemap is drawn in the page from Natural Earth, so it
stays sharp while the camera pushes in. Writes data.js and precip.png.

  TWC_API_KEY=... python3 build.py [valid UTC hour, default 2026-10-31T21] ["local slot", default 2026-10-31T19]
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

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "data", "ne")
GEOMET = "https://geo.weather.gc.ca/geomet"
NDT = timezone(timedelta(hours=-2, minutes=-30))
W, H = 1920, 1080
LON0, LAT0, ZOOM = -51.64, 53.195, 4.72     # frame centre: NL sits in the left ~1300 px, the panel takes the right
SCALE = 1.5                                  # precip raster at 1.5x so it holds up through the push-in

# (lat, lon, card dx, card dy): card offset in px from the town dot, set by hand so nothing overlaps
TOWNS = {
    "Nain": (56.542, -61.692, -140, -40), "Hopedale": (55.456, -60.209, 150, -20),
    "Happy Valley-Goose Bay": (53.302, -60.417, 10, 105), "Churchill Falls": (53.528, -63.966, 0, -105),
    "Labrador City": (52.946, -66.911, 0, 100), "Cartwright": (53.708, -57.021, 160, -10),
    "St. Anthony": (51.364, -55.580, 170, -20), "Corner Brook": (48.951, -57.952, -170, -20),
    "Port aux Basques": (47.572, -59.136, -150, 75), "Gander": (48.954, -54.609, 180, -40),
    "St. John's": (47.561, -52.713, 160, 30), "Marystown": (47.166, -55.148, -10, 95)}

# TWC iconCode -> icon (night versions, it's dark by 7 PM)
ICONS = {}
for codes, name in [((31, 32, 33, 34, 36), "moon"), ((29, 30), "moonpartly"), ((27, 28), "moonmostly"),
                    ((26, 44), "cloud"), ((39, 45), "showers"), ((9, 11, 12, 40), "rain"),
                    ((5, 6, 7, 8, 10, 17, 18, 35), "mix"), ((13, 14, 15, 16, 41, 42, 43, 46), "snow"),
                    ((3, 4, 37, 38, 47), "thunder"), ((19, 20, 21, 22), "fog"), ((23, 24, 25), "wind")]:
    for c in codes:
        ICONS[c] = name


def fetch(url, tries=4):
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def world(lat, lon):
    s, lat = 512 * 2 ** ZOOM, max(-85, min(85, lat))
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def px(lat, lon):
    (x, y), (cx, cy) = world(lat, lon), world(LAT0, LON0)
    return x - cx + W / 2, y - cy + H / 2


def frame_lonlat(scale):
    cx, cy = world(LAT0, LON0)
    s = 512 * 2 ** ZOOM
    xs = cx - W / 2 + (np.arange(int(W * scale)) + .5) / scale
    ys = cy - H / 2 + (np.arange(int(H * scale)) + .5) / scale
    return np.meshgrid(xs / s * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ys / s)))))


def polys(path, keep=None):
    with open(path) as f:
        feats = json.load(f)["features"]
    for ft in feats:
        name = ft["properties"].get("name")
        if keep and not keep(name):
            continue
        g = ft["geometry"]
        for p in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            yield name, p[0]


def svg(rings, min_px=0.9):
    out = []
    for ring in rings:
        pts = [px(la, lo) for lo, la in ring]
        if max(x for x, _ in pts) < -300 or min(x for x, _ in pts) > W + 300 or \
                max(y for _, y in pts) < -300 or min(y for _, y in pts) > H + 300:
            continue
        kept = [pts[0]] + [p for a, p in zip(pts, pts[1:]) if abs(p[0] - a[0]) + abs(p[1] - a[1]) >= min_px]
        if len(kept) > 2:
            out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in kept) + "Z")
    return "".join(out)


def rdps(layer, run, valid):
    url = (f"{GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={layer}"
           f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat(43,63)&subset=lon(-82,-44)"
           f"&resolution=lat(0.05)&resolution=lon(0.0625)&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    body = fetch(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    return np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"])), hdr


def twc(slot):
    geos = ";".join(f"{t[0]},{t[1]}" for t in TOWNS.values())
    rows = json.loads(fetch(f"https://api.weather.com/v3/aggcommon/v3-wx-forecast-hourly-3day?geocodes={geos}"
                            f"&format=json&units=m&language=en-CA&apiKey={os.environ['TWC_API_KEY']}"))
    out = {}
    for name, row in zip(TOWNS, rows):
        d = row["v3-wx-forecast-hourly-3day"]
        i = next(k for k, t in enumerate(d["validTimeLocal"]) if t.startswith(slot))
        out[name] = {k: d[k][i] for k in ("temperature", "temperatureFeelsLike", "iconCode", "wxPhraseLong",
                                          "windDirection", "windDirectionCardinal", "windSpeed", "windGust",
                                          "precipChance", "validTimeLocal")}
        out[name]["icon"] = ICONS.get(d["iconCode"][i], "cloud")
    return out


# precipitation in the hour (mm): rain greens that glow on the dark map, snow in ghostly whites
RAIN = [(0.2, "#3E8E4E"), (1, "#5FC25B"), (2.5, "#9BE35A"), (5, "#D9F36A")]
SNOW = [(0.2, "#8E8AB8"), (0.6, "#B9B4E0"), (1.2, "#E2DFFA"), (2.5, "#FFFFFF")]   # liquid equivalent


def main(valid="2026-10-31T21", slot="2026-10-31T19"):
    v0 = datetime.fromisoformat(valid + ":00:00+00:00")
    t0, t1 = (v0 - timedelta(hours=0)).strftime("%Y-%m-%dT%H:00:00Z"), (v0 + timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00Z")
    caps = fetch(f"{GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer=RDPS_10km_Rain-Accum").decode()
    run = re.search(r'<Dimension name="reference_time"[^>]*default="([^"]+)"', caps).group(1)

    # land: provinces + states from Natural Earth, drawn onto the frame raster
    from PIL import ImageDraw
    LON, LAT = frame_lonlat(SCALE)
    rings = list(polys(os.path.join(DATA, "adm1.geojson")))
    mask = Image.new("L", LON.shape[::-1], 0)
    dr = ImageDraw.Draw(mask)
    for _, ring in rings:
        if len(ring) >= 8:
            dr.polygon([(px(la, lo)[0] * SCALE, px(la, lo)[1] * SCALE) for lo, la in ring], fill=255)
    land = gaussian_filter(np.asarray(mask, float) / 255, 0.8)

    def field(layer):
        a1, hdr = rdps(layer, run, t1)
        a0, _ = rdps(layer, run, t0)
        top = hdr["yllcorner"] + hdr["nrows"] * hdr["dy"]
        g = gaussian_filter(np.clip(a1 - a0, 0, None), 1.0)
        return map_coordinates(g, [(top - LAT) / hdr["dy"] - .5, (LON - hdr["xllcorner"]) / hdr["dx"] - .5], order=1)
    rain, snow = field("RDPS_10km_Rain-Accum"), field("RDPS_10km_Snow-Accum")
    rgba = np.zeros(LON.shape + (4,))
    for arr, bands, other in ((rain, RAIN, snow), (snow, SNOW, rain)):
        for lo, col in bands:
            sel = (arr >= lo) & (arr >= other)
            rgba[sel, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            rgba[sel, 3] = 0.78
    rgba[..., 3] *= land
    Image.fromarray((rgba * 255).astype(np.uint8)).save(os.path.join(HERE, "precip.png"))

    towns = twc(slot)
    for n, (la, lo, dx, dy) in TOWNS.items():
        x, y = px(la, lo)
        towns[n].update(xy=[round(x, 1), round(y, 1)], card=[round(x + dx), round(y + dy)])

    nl_rings = [r for n, r in rings if n == "Newfoundland and Labrador" and len(r) > 20]
    other = [r for n, r in rings if n != "Newfoundland and Labrador" and len(r) > 8]
    lakes = [r for _, r in polys(os.path.join(DATA, "lakes.geojson"))]
    temps = [t["temperature"] for t in towns.values()]
    wet = [n for n, t in towns.items() if t["icon"] in ("rain", "showers", "snow", "mix", "thunder")]
    data = {
        "run": run, "issued": datetime.now(NDT).strftime("%-I:%M %p %a %b %-d"),
        "valid": v0.astimezone(NDT).strftime("%A %-I:%M %p"),
        "towns": towns, "range": [min(temps), max(temps)], "wet": wet,
        "rain_max": round(float((rain * (land > .5)).max()), 1), "snow_max": round(float((snow * (land > .5)).max()), 1),
        "nl": svg(nl_rings), "other": svg(other), "lakes": svg(lakes, 1.5),
        "rain": RAIN, "snow": SNOW, "w": W, "h": H, "scale": SCALE,
    }
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.HW = " + json.dumps(data) + ";\n")
    print("RDPS run", run, "hour", t0, "->", t1, "| rain max", data["rain_max"], "mm, snow max", data["snow_max"], "mm")
    for n, t in towns.items():
        print(f"  {n:24s} {t['temperature']:>3}° feels {t['temperatureFeelsLike']:>3}  {t['icon']:11s} "
              f"{t['windDirectionCardinal']:>3} {t['windSpeed']:>2} g{t['windGust'] or '-'}  {t['precipChance']}%  {t['wxPhraseLong']}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
