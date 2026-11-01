"""Subtropical Storm Josephine as NHC draws it: forecast cone, track and points, and the current wind field
(34-kt and 50-kt initial radii) on the house light basemap. Social 4:5 and 16:9 frames.
Writes map-{social,tv}.png and data.js (window.STORM).

  MAPBOX_ACCESS_TOKEN=... python3 build.py [advisory number]     (default: latest on nhc.noaa.gov)
"""
import glob
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone

import numpy as np
import shapefile
from matplotlib.image import imread, imsave
from scipy.ndimage import median_filter

HERE = os.path.dirname(os.path.abspath(__file__))
STORM = "al102026"
NHC = "https://www.nhc.noaa.gov/gis/forecast/archive/"
NDT = timezone(timedelta(hours=-2, minutes=-30))
FRAMES = {"social": dict(w=1080, h=900, lon0=-57.6, lat0=43.6, zoom=4.42),
          "tv": dict(w=1920, h=1080, lon0=-50.4, lat0=43.4, zoom=4.66)}
TOWNS = {"St. John's": (47.561, -52.713), "Halifax": (44.649, -63.575), "Sydney": (46.136, -60.195),
         "Boston": (42.360, -71.058), "Cape Race": (46.658, -53.073), "Gander": (48.954, -54.609)}


def get(url):
    r = subprocess.run(["curl", "-sf", "--retry", "4", "-A", "Mozilla/5.0 sheerr-weather", url], capture_output=True)
    if r.returncode:
        raise OSError(f"{url}: curl {r.returncode}")
    return r.stdout


def latest_adv():
    n = 1
    while True:
        try:
            get(f"{NHC}{STORM}_5day_{n + 1:03d}.zip")
        except OSError:
            return n
        n += 1


def unzip(url):
    d = tempfile.mkdtemp()
    zipfile.ZipFile(io.BytesIO(get(url))).extractall(d)
    return d


def world(lat, lon, z):
    s = 512 * 2 ** z
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * s


def basemap(fr):
    """light-v11 with place labels removed (median pick between label-hidden variants, as in the low maps)."""
    tok = os.environ["MAPBOX_ACCESS_TOKEN"]
    url = (f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{fr['lon0']},{fr['lat0']},{fr['zoom'] - 1:.3f},0/"
           f"{fr['w'] // 2}x{fr['h'] // 2}@2x?attribution=false&logo=false&access_token={tok}")
    hide = '&layer_id={}&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D'
    st = np.stack([imread(io.BytesIO(get(url + (hide.format(L) if L else ""))), format="png")[..., :3]
                   for L in (None, "state-label", "country-label", "settlement-major-label", "settlement-minor-label",
                             "natural-point-label", "water-point-label")])
    g = st.mean(-1)
    bg = median_filter(g.min(0), size=17)
    pick = np.argmin(np.abs(g - bg[None]), axis=0)
    return np.take_along_axis(st, pick[None, ..., None].repeat(3, -1), 0)[0]


def ndt_label(dt):
    return dt.astimezone(NDT).strftime("%a %-I:%M %p").replace("AM", "a.m.").replace("PM", "p.m.")


def main(adv=None):
    adv = int(adv) if adv else latest_adv()
    d5 = unzip(f"{NHC}{STORM}_5day_{adv:03d}.zip")
    df = unzip(f"{NHC}{STORM}_fcst_{adv:03d}.zip")
    pts = shapefile.Reader(glob.glob(f"{d5}/*_pts.shp")[0])
    flds = [f[0] for f in pts.fields[1:]]
    points = []
    for rec, sh in zip(pts.records(), pts.shapes()):
        r = dict(zip(flds, rec))
        day, hm = r["VALIDTIME"].split("/")                                   # "21/1800" (UTC)
        adv_dt = datetime.strptime(r["ADVDATE"].split(" ", 3)[3], "%a %b %d %Y")
        vt = datetime(adv_dt.year, adv_dt.month, int(day), int(hm[:2]), tzinfo=timezone.utc)
        lon, lat = sh.points[0]
        points.append({"tau": r["TAU"], "lat": lat, "lon": lon, "kt": r["MAXWIND"], "kmh": round(r["MAXWIND"] * 1.852 / 5) * 5,
                       "type": r["STORMTYPE"],
                       # STORMSRC follows the NHC discussion (post-tropical from 24 h on); STORMTYPE in the file can lag
                       "label": "P" if r["STORMSRC"].startswith("Post") or r["STORMTYPE"] == "PTC" else "S" if r["STORMTYPE"] in ("TS", "STS") else r["DVLBL"],
                       "when": ndt_label(vt), "valid": vt.isoformat()})
    cone = shapefile.Reader(glob.glob(f"{d5}/*_pgn.shp")[0]).shapes()[0]
    cone_rings = [cone.points[a:b] for a, b in zip(cone.parts, list(cone.parts[1:]) + [len(cone.points)])]
    rad = shapefile.Reader(glob.glob(f"{df}/*forecastradii.shp")[0])
    rflds = [f[0] for f in rad.fields[1:]]
    ini = shapefile.Reader(glob.glob(f"{df}/*initialradii.shp")[0])          # current wind field, as on NHC's cone graphic
    iflds = [f[0] for f in ini.fields[1:]]
    now_r = {dict(zip(iflds, rec))["RADII"]: sh.points for rec, sh in zip(ini.records(), ini.shapes())}
    first = points[0]
    adv_time = datetime.fromisoformat(first["valid"]) + timedelta(hours=3)          # advisory issued 3 h after synoptic time
    first["when"] = ndt_label(adv_time)                                             # the current position is as of the advisory
    # closest forecast approach to Cape Race along the track (densified)
    tr = np.array([[p["lat"], p["lon"]] for p in points])
    dense = np.concatenate([np.linspace(tr[i], tr[i + 1], 40) for i in range(len(tr) - 1)])
    def km(a, b):
        h = math.sin(math.radians(b[0] - a[0]) / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
        return 2 * 6371 * math.asin(math.sqrt(h))
    dists = [km(TOWNS["Cape Race"], p) for p in dense]
    i = int(np.argmin(dists))
    seg = i // 40
    t0, t1 = (datetime.fromisoformat(points[k]["valid"]) for k in (seg, min(seg + 1, len(points) - 1)))
    t_close = t0 + (t1 - t0) * ((i % 40) / 39)
    t_close = (t_close + timedelta(minutes=15)).replace(minute=0, second=0, microsecond=0) + timedelta(minutes=30)   # nearest NDT half hour
    data = {"adv": adv, "issued": ndt_label(adv_time), "points": points, "frames": {},
            "now": {"kmh": first["kmh"], "mph": round(first["kt"] * 1.15078 / 5) * 5, "mslp": pts.records()[0][flds.index("MSLP")],
                    "dir": pts.records()[0][flds.index("TCDIR")], "spd_kmh": round(pts.records()[0][flds.index("TCSPD")] * 1.852)},
            "peak": max(points, key=lambda p: p["kt"]),
            "closest": {"km": round(min(dists) / 10) * 10, "when": ndt_label(t_close), "to": "Cape Race"}}
    for name, fr in FRAMES.items():
        cx, cy = world(fr["lat0"], fr["lon0"], fr["zoom"])
        proj = lambda la, lo: [round(world(la, lo, fr["zoom"])[0] - cx + fr["w"] / 2, 1), round(world(la, lo, fr["zoom"])[1] - cy + fr["h"] / 2, 1)]
        path = lambda ring: "M" + "L".join("%.1f,%.1f" % tuple(proj(y, x)) for x, y in ring) + "Z"
        data["frames"][name] = {
            "w": fr["w"], "h": fr["h"],
            "cone": "".join(path(r) for r in cone_rings),
            "wind_now": {str(k): path(v) for k, v in now_r.items()},
            "track": [proj(p["lat"], p["lon"]) for p in points],
            "towns": {n: proj(*ll) for n, ll in TOWNS.items()}}
        imsave(os.path.join(HERE, f"map-{name}.png"), basemap(fr))
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.STORM = " + json.dumps(data) + ";\n")
    shutil.rmtree(d5); shutil.rmtree(df)
    print("advisory", adv, "issued", data["issued"], "now", data["now"], "closest", data["closest"])
    for p in points:
        print(f"  {p['when']:>16s}  {p['lat']:5.1f} {p['lon']:6.1f}  {p['kmh']:3d} km/h  {p['type']}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
