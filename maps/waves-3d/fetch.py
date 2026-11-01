"""GFS-Wave significant wave height + peak wave direction/period and GFS MSLP, every 3 h for 5 days,
off the US East Coast and Atlantic Canada (NOMADS grib filter, subregion only).

Writes waves.bin (Float32 [step][lat][lon][4] = Hs m, MSLP hPa, u, v where (u, v) is the peak-wave travel
direction scaled by peak period in s) and waves.js (window.WAVES: grid, times, ocean mask, H/L tracks).

  python3 fetch.py [YYYYMMDDHH run] [first_hour] [last_hour]
"""
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pygrib
from scipy.ndimage import distance_transform_edt, gaussian_filter, maximum_filter, minimum_filter

HERE = os.path.dirname(os.path.abspath(__file__))
W, E, S, N = -90, -30, 22, 66
NOMADS = "https://nomads.ncep.noaa.gov/cgi-bin/"
BOX = f"&subregion=&leftlon={W}&rightlon={E}&toplat={N}&bottomlat={S}"


def get(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1000:     # cached from an earlier, interrupted run
        return path
    for k in range(5):
        r = subprocess.run(["curl", "-s", "--http1.1", "-A", "Mozilla/5.0 sheerr-weather", "-o", path + ".part", url])
        if r.returncode == 0 and os.path.getsize(path + ".part") > 1000:
            os.replace(path + ".part", path)
            return path
        time.sleep(2 ** (k + 1))
    raise RuntimeError("download failed: " + url)


def latest_run():
    now = datetime.now(timezone.utc)
    for back in range(0, 48, 6):
        t = now - timedelta(hours=back)
        run = t.replace(hour=t.hour // 6 * 6, minute=0, second=0, microsecond=0)
        idx = (f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{run:%Y%m%d}/{run:%H}/wave/gridded/"
               f"gfswave.t{run:%H}z.global.0p25.f132.grib2.idx")
        r = subprocess.run(["curl", "-s", "--http1.1", "-A", "Mozilla/5.0", "-o", "/dev/null", "-w", "%{http_code}", idx],
                           capture_output=True, text=True)
        if r.stdout == "200":
            return run
    raise RuntimeError("no complete GFS-Wave run found")


def tracks(press, lat, lon, kind):
    """Lows/highs per step (smoothed local extrema), linked step to step by nearest match."""
    found = []
    for P in press:
        sm = gaussian_filter(P, 2)
        f = minimum_filter if kind == "L" else maximum_filter
        ext = (sm == f(sm, size=25)) & ((sm < 1004) if kind == "L" else (sm > 1018))
        ext[:3], ext[-3:], ext[:, :3], ext[:, -3:] = False, False, False, False
        found.append([(float(lon[j]), float(lat[i]), float(P[i, j])) for i, j in zip(*np.nonzero(ext))])
    out, live = [], []
    for s, pts in enumerate(found):
        nxt, used = [], set()
        for tr in live:
            lo, la, _ = tr["pts"][-1][1:]
            best = min(((np.hypot((p[0] - lo) * np.cos(np.radians(la)), p[1] - la), k) for k, p in enumerate(pts)
                        if k not in used), default=None)
            if best and best[0] < 5.5:
                used.add(best[1]); tr["pts"].append([s, *pts[best[1]]]); nxt.append(tr)
            else:
                out.append(tr)
        for k, p in enumerate(pts):
            if k not in used:
                nxt.append({"kind": kind, "pts": [[s, *p]]})
        live = nxt
    out += live
    return [t for t in out if len(t["pts"]) >= 3]       # drop flickers


def main(run=None, h0="12", h1="132"):
    run = datetime.strptime(run, "%Y%m%d%H").replace(tzinfo=timezone.utc) if run else latest_run()
    hours = list(range(int(h0), int(h1) + 1, 3))
    tmp = os.path.join(os.environ.get("WAVES_CACHE", "/tmp"), f"gfswave-{run:%Y%m%d%H}")
    os.makedirs(tmp, exist_ok=True)
    steps, press, times = [], [], []
    for h in hours:
        wf = get(f"{NOMADS}filter_gfswave.pl?dir=%2Fgfs.{run:%Y%m%d}%2F{run:%H}%2Fwave%2Fgridded"
                 f"&file=gfswave.t{run:%H}z.global.0p25.f{h:03d}.grib2&var_HTSGW=on&var_DIRPW=on&var_PERPW=on{BOX}",
                 os.path.join(tmp, f"w{h:03d}.grb"))
        pf = get(f"{NOMADS}filter_gfs_0p25.pl?dir=%2Fgfs.{run:%Y%m%d}%2F{run:%H}%2Fatmos"
                 f"&file=gfs.t{run:%H}z.pgrb2.0p25.f{h:03d}&var_PRMSL=on&lev_mean_sea_level=on{BOX}",
                 os.path.join(tmp, f"p{h:03d}.grb"))
        g = {m.shortName: m for m in pygrib.open(wf)}
        lat, lon = g["swh"].latlons()
        lat, lon = lat[:, 0], lon[0] - 360
        hs, dp, tp = (np.ma.filled(g[k].values.astype("f8"), np.nan) for k in ("swh", "dirpw", "perpw"))
        P = pygrib.open(pf)[1].values[:, :len(lon)] / 100
        if lat[0] > lat[-1]:
            raise RuntimeError("expected south-to-north rows")
        sea = np.isfinite(hs)
        # fill land from the nearest sea cell so colours/heights reach right to the drawn coastline
        _, (ii, jj) = distance_transform_edt(~sea, return_indices=True)
        hs, dp, tp = hs[ii, jj], dp[ii, jj], tp[ii, jj]
        to = np.radians(dp + 180)                               # DIRPW is where waves come from
        steps.append(np.stack([hs, P, np.sin(to) * tp, np.cos(to) * tp], -1).astype("<f4"))
        press.append(P)
        times.append((run + timedelta(hours=h)).isoformat())
        print(f"f{h:03d}  Hs max {np.nanmax(hs[sea]):5.1f} m  MSLP {P.min():6.1f}-{P.max():6.1f}", flush=True)
    data = np.stack(steps)
    data.tofile(os.path.join(HERE, "waves.bin"))
    meta = {"run": run.isoformat(), "times": times, "nx": len(lon), "ny": len(lat),
            "lon0": float(lon[0]), "lat0": float(lat[0]), "dlon": float(lon[1] - lon[0]), "dlat": float(lat[1] - lat[0]),
            "sea": base64.b64encode(np.packbits(sea.ravel()).tobytes()).decode(),
            "tracks": tracks(press, lat, lon, "L") + tracks(press, lat, lon, "H"),
            "hsmax": [float(np.nanmax(s[..., 0][sea])) for s in steps]}
    with open(os.path.join(HERE, "waves.js"), "w") as f:
        f.write("// generated by fetch.py\nwindow.WAVES = " + json.dumps(meta) + ";\n")
    print(data.shape, len(meta["tracks"]), "H/L tracks")


if __name__ == "__main__":
    main(*sys.argv[1:4])
