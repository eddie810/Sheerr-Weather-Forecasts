#!/usr/bin/env python3
"""Build the data file for the Island Ops Weather Desk prototype
(prototypes/nl-hydro-island-dashboard.html).

Sources (all public, no keys):
  * MSC Datamart RDPS 10 km (GRIB2): hourly 0-48 h at each site
      2 m temp, 10 m wind / gust / direction, RH, MSLP, hourly precip split
      into rain / freezing rain / ice pellets / snow, snow depth, plus
      3-hourly upper-air temps + heights for freezing level / warm layer.
  * MSC Datamart NAEFS point ensembles (XML): 16-day temp, precip, wind at
      the nearest NAEFS point (GEPS + GEFS members).
  * NL Water Resources real-time stations (ADRS CSV): reservoir / river
      levels and flows, plus provincial weather stations.

Live parts (radar, ECCC alerts, ECCC station obs) are fetched by the page
itself; the page reads this file for everything that needs processing.

Usage:  python tools/hydro_dashboard_data.py [--out PATH] [--reuse URL]
"""
from __future__ import annotations

import argparse
import bz2
import concurrent.futures as cf
import csv
import datetime as dt
import html as htmlmod
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET

import eccodes

DD = "https://dd.weather.gc.ca"
MAE = "https://www.mae.gov.nl.ca/wrmd/adrs/v6/Data"
UA = {"User-Agent": "island-ops-weather-desk/0.1"}
NST = dt.timezone(dt.timedelta(hours=-3, minutes=-30))

# Approximate positions. "naefs" = nearest NAEFS point forecast.
SITES = {
    "bde": {"lat": 47.99, "lon": -55.80, "naefs": "BADGER",
            "mae": ["02YN005", "02ZE004"], "mae_wx": None},
    "cat": {"lat": 50.10, "lon": -56.80, "naefs": "DANIELS_HARBOUR",
            "mae": ["02YF002"], "mae_wx": None},
    "hin": {"lat": 49.38, "lon": -56.95, "naefs": "DEER_LAKE",
            "mae": ["02YK010", "02YK008"], "mae_wx": "NLENCL0005"},
    "par": {"lat": 47.66, "lon": -54.40, "naefs": "ARGENTIA",
            "mae": ["02ZH001"], "mae_wx": "NLENCL0013"},
    "gra": {"lat": 48.17, "lon": -56.35, "naefs": "BADGER",
            "mae": ["02ZC004", "02ZD003"], "mae_wx": "NLENCL0014"},
    "hol": {"lat": 47.43, "lon": -53.10, "naefs": "ST_JOHNS",
            "mae": ["02ZM016"], "mae_wx": "NLENCL0015"},
    "sol": {"lat": 47.40, "lon": -52.97, "naefs": "ST_JOHNS",
            "mae": ["NF02ZM0009"], "mae_wx": "NLENCL0001"},
    "sun": {"lat": 47.86, "lon": -53.92, "naefs": "ARGENTIA",
            "mae": ["NF02ZH0009"], "mae_wx": "NLENCL0013"},
}

HOURS = 60  # always covers 48 h ahead even when the newest run is ~10 h old
SFC = {  # key -> (RDPS variable, scale, offset)
    "t": ("AirTemp_AGL-2m", 1, -273.15),
    "ws": ("WindSpeed_AGL-10m", 3.6, 0),
    "wd": ("WindDir_AGL-10m", 1, 0),
    "wg": ("WindGust_AGL-10m", 3.6, 0),
    "rh": ("RelativeHumidity_AGL-2m", 1, 0),
    "p": ("Pressure_MSL", 0.01, 0),
    "pcp": ("Precip-Accum1h_Sfc", 1, 0),
    "fzra": ("FreezingRain-Accum1h_Sfc", 1, 0),
    "pl": ("IcePellets-Accum1h_Sfc", 1, 0),
    "sn": ("Snow-Accum1h_Sfc", 1, 0),
    "ra": ("Rain-Accum1h_Sfc", 1, 0),
}
LEVELS = ["1000", "0950", "0925", "0900", "0850", "0800", "0750", "0700"]
NAEFS_VARS = ["TMP-SFC", "APCP-SFC", "WIND-SFC"]


def get(url: str, tries: int = 4, timeout: int = 60) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 ** i)
    raise RuntimeError(url)


def exists(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- RDPS
def rdps_url(run: dt.datetime, h: int, var: str) -> str:
    d, hh = run.strftime("%Y%m%d"), run.strftime("%H")
    return (f"{DD}/{d}/WXO-DD/model_rdps/10km/{hh}/{h:03d}/"
            f"{d}T{hh}Z_MSC_RDPS_{var}_RLatLon0.09_PT{h:03d}H.grib2")


def latest_rdps_run(now: dt.datetime) -> dt.datetime:
    base = now.replace(minute=0, second=0, microsecond=0)
    base = base.replace(hour=base.hour // 6 * 6)
    for k in range(0, 6):
        run = base - dt.timedelta(hours=6 * k)
        if exists(rdps_url(run, HOURS, "Precip-Accum1h_Sfc")) and exists(rdps_url(run, HOURS, "AirTemp_AGL-2m")):
            return run
    raise RuntimeError("no complete RDPS run found")


class Grid:
    """Nearest-grid-point indices, worked out once (all RDPS fields share the grid)."""

    def __init__(self):
        self.idx: dict[str, int] = {}
        self.where: dict[str, dict] = {}

    def values(self, blob: bytes) -> dict[str, float]:
        gid = eccodes.codes_new_from_message(blob)
        try:
            if not self.idx:
                for k, s in SITES.items():
                    n = eccodes.codes_grib_find_nearest(gid, s["lat"], s["lon"])[0]
                    self.idx[k] = n["index"]
                    self.where[k] = {"lat": round(n["lat"], 3), "lon": round(n["lon"], 3), "km": round(n["distance"], 1)}
            vals = eccodes.codes_get_values(gid)
            return {k: float(vals[i]) for k, i in self.idx.items()}
        finally:
            eccodes.codes_release(gid)


def fetch_rdps(run: dt.datetime) -> dict:
    grid = Grid()
    # one warm-up download fixes the grid indices before the pool starts
    grid.values(get(rdps_url(run, 1, "AirTemp_AGL-2m")))

    jobs = []
    for key, (var, _, _) in SFC.items():
        start = 1 if key in ("pcp", "fzra", "pl", "sn", "ra") else 0
        for h in range(start, HOURS + 1):
            jobs.append((key, h, var))
    for h in range(0, HOURS + 1, 6):
        jobs.append(("sd", h, "SnowDepth_Sfc"))
    for h in range(0, HOURS + 1, 3):
        for lv in LEVELS:
            jobs.append((f"tt{lv}", h, f"AirTemp_IsbL-{lv}"))
            jobs.append((f"gz{lv}", h, f"GeopotentialHeight_IsbL-{lv}"))

    out: dict[str, dict[int, dict[str, float]]] = {}

    def work(job):
        key, h, var = job
        return key, h, grid.values(get(rdps_url(run, h, var)))

    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        for key, h, vals in ex.map(work, jobs):
            out.setdefault(key, {})[h] = vals

    hours = [(run + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ") for h in range(1, HOURS + 1)]
    sites = {}
    for k in SITES:
        rec: dict[str, list] = {}
        for key, (_, scale, off) in SFC.items():
            rec[key] = [round(out[key][h][k] * scale + off, 2) for h in range(1, HOURS + 1)]
        rec["wd"] = [round(v) % 360 for v in rec["wd"]]
        rec["rh"] = [round(min(100, max(0, v))) for v in rec["rh"]]
        # snow depth (cm), linear between 6-hourly values
        sd = {h: out["sd"][h][k] * 100 for h in out["sd"]}
        rec["sd"] = [round(_interp(sd, h), 1) for h in range(1, HOURS + 1)]
        # freezing level / warm layer from 3-hourly soundings
        fz, warm, warmz = {}, {}, {}
        for h in range(0, HOURS + 1, 3):
            prof = sorted(((out[f"gz{lv}"][h][k], out[f"tt{lv}"][h][k] - 273.15) for lv in LEVELS))
            t2 = out["t"][h][k] - 273.15 if h in out["t"] else prof[0][1]
            fz[h], warm[h], warmz[h] = _freezing(t2, prof)
        rec["fzl"] = [_round_none(_interp(fz, h), -1) for h in range(1, HOURS + 1)]
        rec["warm"] = [round(_interp(warm, h), 1) for h in range(1, HOURS + 1)]
        rec["warmz"] = [_round_none(_interp(warmz, h), -1) for h in range(1, HOURS + 1)]
        sites[k] = rec
    return {"run": run.strftime("%Y-%m-%dT%HZ"), "hours": hours, "grid": grid.where, "sites": sites}


def _round_none(v, nd):
    return None if v is None else int(round(v, nd))


def _interp(series: dict[int, float | None], h: int):
    if h in series:
        return series[h]
    lo = max(x for x in series if x < h)
    hi = min(x for x in series if x > h)
    a, b = series[lo], series[hi]
    if a is None or b is None:
        return a if b is None else b
    return a + (b - a) * (h - lo) / (hi - lo)


def _freezing(t2: float, prof: list[tuple[float, float]]):
    """Return (freezing level m ASL or 0 for 'surface', warmest temp aloft, its height)."""
    warm_t, warm_z = max(((t, z) for z, t in prof), key=lambda x: x[0])
    if t2 > 0:
        prev_z, prev_t = 0.0, t2
        for z, t in prof:
            if z <= prev_z:
                continue
            if t <= 0 < prev_t:
                return prev_z + (z - prev_z) * prev_t / (prev_t - t), warm_t, warm_z
            prev_z, prev_t = z, t
        return prof[-1][0], warm_t, warm_z
    return 0.0, warm_t, warm_z


# ---------------------------------------------------------------- NAEFS
def latest_naefs_run(now: dt.datetime):
    base = now.replace(minute=0, second=0, microsecond=0)
    base = base.replace(hour=base.hour // 12 * 12)
    for k in range(0, 6):
        run = base - dt.timedelta(hours=12 * k)
        url = (f"{DD}/{run:%Y%m%d}/WXO-DD/ensemble/naefs/xml/{run:%Y%m%d}/{run:%H}/APCP-SFC/raw/"
               f"{run:%Y%m%d%H}_GEPS-NAEFS-RAW_ST_JOHNS_NL_CA_APCP-SFC_000-384.xml.bz2")
        if exists(url):
            return run
    raise RuntimeError("no NAEFS run found")


def fetch_naefs(run: dt.datetime) -> dict:
    points = sorted({s["naefs"] for s in SITES.values()})
    res: dict[str, dict] = {}

    def work(job):
        pt, var = job
        url = (f"{DD}/{run:%Y%m%d}/WXO-DD/ensemble/naefs/xml/{run:%Y%m%d}/{run:%H}/{var}/raw/"
               f"{run:%Y%m%d%H}_GEPS-NAEFS-RAW_{pt}_NL_CA_{var}_000-384.xml.bz2")
        root = ET.fromstring(bz2.decompress(get(url)))
        times, members = [], []
        for fc in root.iter("forecast"):
            vt = fc.get("valid_time")
            times.append(dt.datetime.strptime(vt, "%Y%m%d%H").strftime("%Y-%m-%dT%HZ"))
            members.append([float(m.text) for m in fc.iter("model") if m.text not in (None, "")])
        return pt, var, times, members

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for pt, var, times, members in ex.map(work, [(p, v) for p in points for v in NAEFS_VARS]):
            r = res.setdefault(pt, {"times": times})
            if var == "APCP-SFC":
                # accumulated since t0 -> 6-hour amounts per member
                prev = [0.0] * len(members[0])
                inc = []
                for row in members:
                    inc.append([max(0.0, a - b) for a, b in zip(row, prev + [0.0] * (len(row) - len(prev)))])
                    prev = row
                members = inc
                r["apcp6"] = _stats(members)
                # chance of >= 25 mm in the 24 h ending at each step
                r["p24ge25"] = _prob_window(members, 4, 25)
                r["p24ge50"] = _prob_window(members, 4, 50)
                r["p24ge1"] = _prob_window(members, 4, 1)
            elif var == "TMP-SFC":
                r["t"] = _stats(members)
            elif var == "WIND-SFC":
                r["wind"] = _stats(members)  # already km/h
            r["members"] = len(members[0])
    return {"run": run.strftime("%Y-%m-%dT%HZ"), "points": res}


def _pct(vals, q):
    v = sorted(vals)
    i = (len(v) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def _stats(rows):
    return {
        "mean": [round(sum(r) / len(r), 2) for r in rows],
        "p10": [round(_pct(r, 0.1), 2) for r in rows],
        "p90": [round(_pct(r, 0.9), 2) for r in rows],
    }


def _prob_window(rows, n, thr):
    out = []
    for i in range(len(rows)):
        win = rows[max(0, i - n + 1): i + 1]
        tot = [sum(col) for col in zip(*win)]
        out.append(round(100 * sum(1 for t in tot if t >= thr) / len(tot)))
    return out


# ---------------------------------------------------------------- NL Water Resources
WATER_COLS = ("STAGE", "FLOW", "WATER_TEMP")
WX_COLS = ("AIR_TEMP", "REL_HUMIDITY", "PRECIP_TB", "SNOW_DEPTH", "WIND_SPEED", "WIND_DIR", "WIND_SPEED_GUST")
SANE = {"AIR_TEMP": (-45, 40), "REL_HUMIDITY": (0, 100.5), "SNOW_DEPTH": (0, 5), "WIND_SPEED": (0, 250),
        "WIND_SPEED_GUST": (0, 300), "WIND_DIR": (0, 360), "PRECIP_TB": (0, 100), "FLOW": (0, 1e5),
        "WATER_TEMP": (-1, 35)}


def fetch_mae(sid: str, weather: bool = False) -> dict | None:
    try:
        raw = get(f"{MAE}/{sid}_Line.csv").decode("latin-1")
        page = get(f"https://www.mae.gov.nl.ca/wrmd/adrs/v6/Template_Station.asp?station={sid}").decode("latin-1")
    except Exception as e:  # noqa: BLE001
        print(f"  MAE {sid}: {e}", file=sys.stderr)
        return None
    m = re.search(r"Line Data for past 7 days - ([^<|]+)", page)
    lines = [l for l in raw.splitlines() if l.strip()]
    hdr_i = next(i for i, l in enumerate(lines) if l.startswith("STAT_NUM"))
    rows = list(csv.reader(lines[hdr_i:]))
    cols, units = rows[0], rows[1]
    keep = [c for c in cols if c in (WX_COLS if weather else WATER_COLS)]
    hourly: dict[str, dict] = {}
    for r in rows[2:]:
        if len(r) < len(cols):
            continue
        try:
            t = dt.datetime.strptime(r[2].strip(), "%m/%d/%Y %I:%M:%S %p").replace(tzinfo=NST)
        except ValueError:
            continue
        key = t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:00Z")
        rec = hourly.setdefault(key, {})
        for c in keep:
            v = r[cols.index(c)].strip()
            if v not in ("", "-"):
                try:
                    f = float(v)
                except ValueError:
                    continue
                lo, hi = SANE.get(c, (-1e9, 1e9))
                if not lo <= f <= hi:
                    continue
                if c == "PRECIP_TB":  # tipping bucket: sum within the hour
                    rec[c] = rec.get(c, 0) + f
                else:
                    rec[c] = f
                rec["_t"] = t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    times = sorted(hourly)
    series = {c: [[t, round(hourly[t][c], 3)] for t in times if c in hourly[t]] for c in keep}
    series = {c: s for c, s in series.items() if s}
    name = re.sub(r"^\s*\w+\s*-\s*", "", (m.group(1).strip() if m else sid))
    return {
        "kind": "weather" if weather else "water",
        "id": sid,
        "units": {c: units[cols.index(c)].strip("()") for c in series},
        "last": max((s[-1][0] for s in series.values()), default=None),
        "series": series,
        "name": name if name and name != sid else None,
    }


def station_names() -> dict[str, str]:
    try:
        html = get("https://www.mae.gov.nl.ca/wrmd/adrs/v6/graphs_list.asp").decode("latin-1")
    except Exception:  # noqa: BLE001
        return {}
    names = {}
    for row in re.findall(r"<tr.*?</tr>", html, re.S | re.I):
        sid = re.search(r"station=([A-Z0-9]+)", row)
        if not sid:
            continue
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<td.*?</td>", row, re.S | re.I)]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            names[sid.group(1)] = htmlmod.unescape(cells[1]).replace("\xa0", " ").strip()
    return names


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="prototypes/data/hydro-dashboard.json")
    ap.add_argument("--reuse", help="URL of the previous file; model sections are reused when the run is unchanged")
    a = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    prev = {}
    if a.reuse:
        try:
            prev = json.loads(get(a.reuse))
        except Exception as e:  # noqa: BLE001
            print(f"no previous file: {e}", file=sys.stderr)

    t0 = time.time()
    run = latest_rdps_run(now)
    if prev.get("rdps", {}).get("run") == run.strftime("%Y-%m-%dT%HZ"):
        rdps = prev["rdps"]
        print(f"RDPS {rdps['run']} unchanged, reused")
    else:
        rdps = fetch_rdps(run)
        print(f"RDPS {rdps['run']} in {time.time() - t0:.0f}s")

    t1 = time.time()
    nrun = latest_naefs_run(now)
    if prev.get("naefs", {}).get("run") == nrun.strftime("%Y-%m-%dT%HZ"):
        naefs = prev["naefs"]
        print(f"NAEFS {naefs['run']} unchanged, reused")
    else:
        naefs = fetch_naefs(nrun)
        print(f"NAEFS {naefs['run']} in {time.time() - t1:.0f}s")

    names = station_names()
    jobs = sorted({(i, False) for s in SITES.values() for i in s["mae"]}
                  | {(s["mae_wx"], True) for s in SITES.values() if s["mae_wx"]})
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        mae = {r["id"]: r for r in ex.map(lambda j: fetch_mae(*j), jobs) if r}
    ids = jobs
    for sid, r in mae.items():
        r["name"] = names.get(sid) or r.get("name") or sid
    print(f"MAE {len(mae)}/{len(ids)} stations")

    data = {
        "generated": now.strftime("%Y-%m-%dT%H:%MZ"),
        "rdps": rdps,
        "naefs": naefs,
        "mae": mae,
        "sites": {k: {"naefs": s["naefs"], "mae": s["mae"], "mae_wx": s["mae_wx"]} for k, s in SITES.items()},
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"wrote {a.out} ({os.path.getsize(a.out) / 1024:.0f} KB) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
