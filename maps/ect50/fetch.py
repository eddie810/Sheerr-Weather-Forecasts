"""ECT 50 race-day weather: route from the GPX, checkpoints by distance, arrival times for two paces, and RDPS
conditions (temp, wind, gust, precip, cloud) at each checkpoint at those times. Writes race.js (window.RACE).

  python3 fetch.py [run e.g. 2026-10-21T12:00:00Z]
"""
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.ndimage import map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
GEOMET = "https://geo.weather.gc.ca/geomet"
NDT = timezone(timedelta(hours=-2, minutes=-30))
START = datetime(2026, 10, 24, 7, 33, tzinfo=NDT)
PACES = {"lead": 5.0, "mid": 8.0}                  # finish time in hours, even pace along the course
CHECKPOINTS = [("Pouch Cove", "Start", 0.0), ("Flatrock", "Aid station", 16.5), ("Middle Cove Beach", "Aid station", 31.0),
               ("Marine Lab, Logy Bay", "Aid station", 43.0), ("Quidi Vidi", "Finish", None)]
BOX = dict(lat=(47.35, 48.05), lon=(-53.15, -52.25))
FIELDS = {"t": ("RDPS_10km_AirTemp_2m", 1), "ws": ("RDPS_10km_WindSpeed_10m", 3.6), "wd": ("RDPS_10km_WindDir_10m", 1),
          "g": ("RDPS_10km_WindGust_10m", 3.6), "cc": ("RDPS_10km_TotalCloudCover", 1),
          "rain": ("RDPS_10km_Rain-Accum", 1), "snow": ("RDPS_10km_Snow-Accum", 1)}


def get(url, tries=5):
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except (OSError, http.client.HTTPException):
            if n == tries - 1:
                raise
            time.sleep(2 ** (n + 1))


def grid(layer, run, valid):
    url = (f"{GEOMET}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={layer}"
           f"&subsettingcrs=EPSG:4326&outputcrs=EPSG:4326&subset=lat({BOX['lat'][0]},{BOX['lat'][1]})"
           f"&subset=lon({BOX['lon'][0]},{BOX['lon'][1]})&time={valid}&DIM_REFERENCE_TIME={run}&format=image/x-aaigrid")
    body = get(url).decode("latin1").split("filename=result.grd", 1)[1].split("--wcs")[0].strip().splitlines()
    hdr, i = {}, 0
    while re.match(r"^[a-zA-Z_]+\s", body[i]):
        k, v = body[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    dy, dx = hdr.get("dy", hdr.get("cellsize")), hdr.get("dx", hdr.get("cellsize"))
    a = np.array(" ".join(body[i:]).split(), float).reshape(int(hdr["nrows"]), int(hdr["ncols"]))
    top = hdr["yllcorner"] + hdr["nrows"] * dy
    return lambda la, lo: float(map_coordinates(a, [[(top - la) / dy - .5], [(lo - hdr["xllcorner"]) / dx - .5]], order=1, mode="nearest")[0])


def route():
    r = ET.parse(os.path.join(HERE, "ect50.gpx")).getroot()
    ns = {"g": r.tag.split("}")[0].strip("{")}
    pts = [(float(p.get("lat")), float(p.get("lon")), float(p.find("g:ele", ns).text)) for p in r.findall(".//g:trkpt", ns)]
    km = [0.0]
    for a, b in zip(pts, pts[1:]):
        h = math.sin(math.radians(b[0] - a[0]) / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
        km.append(km[-1] + 2 * 6371 * math.asin(math.sqrt(h)))
    return pts, km


def main(run=None):
    pts, km = route()
    total = km[-1]
    caps = get(f"{GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer=RDPS_10km_AirTemp_2m").decode()
    run = run or re.search(r'<Dimension name="reference_time"[^>]*default="([^"]+)"', caps).group(1)
    cps = []
    for name, kind, k in CHECKPOINTS:
        k = total if k is None else k
        i = int(np.searchsorted(km, k))
        la, lo = pts[min(i, len(pts) - 1)][:2]
        cps.append({"name": name, "kind": kind, "km": round(k, 1), "ll": [la, lo], "ele": round(pts[min(i, len(pts) - 1)][2]),
                    "eta": {p: START + timedelta(hours=h * k / total) for p, h in PACES.items()}})
    # hourly grids over the race window (one hour either side), interpolated in time to each arrival
    t0 = START.astimezone(timezone.utc).replace(minute=0) - timedelta(hours=1)
    t1 = (START + timedelta(hours=max(PACES.values()) + 1)).astimezone(timezone.utc)
    hours, cache = [], {}
    t = t0
    while t <= t1:
        hours.append(t)
        for f, (layer, sc) in FIELDS.items():
            cache[f, t] = (grid(layer, run, t.strftime("%Y-%m-%dT%H:%M:%SZ")), sc)
        t += timedelta(hours=1)
    def at(f, la, lo, when):
        when = when.astimezone(timezone.utc)
        a = max(h for h in hours if h <= when)
        b = min([h for h in hours if h > a] or [a])
        fa, sc = cache[f, a]
        fb, _ = cache[f, b]
        w = 0 if b == a else (when - a).total_seconds() / 3600
        va, vb = fa(la, lo), fb(la, lo)
        if f == "wd":                                   # interpolate direction on the circle
            d = ((vb - va + 180) % 360) - 180
            return (va + d * w) % 360
        return (va + (vb - va) * w) * sc
    def rate(la, lo, when):                            # precip mm/h over the hour ending at `when`
        prev = when - timedelta(hours=1)
        return max(0.0, sum(at(k, la, lo, when) - at(k, la, lo, prev) for k in ("rain", "snow")))
    for c in cps:
        c["wx"] = {}
        for p, when in c["eta"].items():
            la, lo = c["ll"]
            c["wx"][p] = {"t": round(at("t", la, lo, when)), "ws": round(at("ws", la, lo, when)), "g": round(at("g", la, lo, when)),
                          "wd": round(at("wd", la, lo, when)), "cc": round(at("cc", la, lo, when)), "pr": round(rate(la, lo, when), 1)}
        c["eta"] = {p: w.strftime("%-I:%M %p").replace("AM", "a.m.").replace("PM", "p.m.") for p, w in c["eta"].items()}
    # hourly series at mid-course for the wind/rain effects in the scene
    mid = pts[len(pts) // 2]
    series = [{"t": h.astimezone(NDT).strftime("%-I %p"), "ws": round(at("ws", mid[0], mid[1], h)), "wd": round(at("wd", mid[0], mid[1], h)),
               "pr": round(rate(mid[0], mid[1], h), 1)} for h in hours[1:]]
    out = {"run": run, "start": START.strftime("%A, %B %-d · %-I:%M %p"), "km": round(total, 1), "paces": PACES,
           "route": [[round(a, 6), round(b, 6), round(e, 1)] for a, b, e in pts], "routeKm": [round(x, 3) for x in km],
           "checkpoints": cps, "series": series}
    with open(os.path.join(HERE, "race.js"), "w") as f:
        f.write("// generated by fetch.py\nwindow.RACE = " + json.dumps(out) + ";\n")
    print(run, "route", round(total, 1), "km")
    for c in cps:
        print(f"{c['name']:22s} {c['km']:5.1f} km  {c['ll'][0]:.4f},{c['ll'][1]:.4f}  ele {c['ele']} m")
        for p in PACES:
            w = c["wx"][p]
            print(f"     {p:4s} {c['eta'][p]:>11s}  {w['t']:3d}°C  {w['wd']:3d}° {w['ws']:3d} g{w['g']:3d} km/h  cloud {w['cc']}%  {w['pr']} mm/h")


if __name__ == "__main__":
    main(*sys.argv[1:2])
