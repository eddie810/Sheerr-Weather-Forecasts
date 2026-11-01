"""RRFS wind-gust animation for Newfoundland: shaded gust contours (land only), labelled contour lines,
and streamlines of the 10 m wind for direction. NOAA RRFS parallel, 13 km North America grid, hourly.

  MAPBOX_ACCESS_TOKEN=... python3 build.py RUN FIRST_FH LAST_FH ne_admin1.geojson     e.g. 2026101712 5 24 adm1.geojson
Writes frames/NN.png, frames.js, map.png.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pygrib  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
import importlib.util  # noqa: E402


def _load(name, folder):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", folder, "build.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


RR = _load("rrfs_radar", "rrfs-radar")     # fetch, Regrid, px, borders
TOT = _load("totals", "rdps-totals")       # land_mask, nl_mask

W, H = 1080, 860
LON0, LAT0, ZOOM = -56.35, 49.25, 6.22          # same frame as the future radar loops
NDT = timezone(timedelta(hours=-2, minutes=-30))
BANDS = [(40, "#FFF1B8"), (50, "#FFDD7A"), (60, "#FDBD4F"), (70, "#F79A3E"), (80, "#EE7136"),
         (90, "#DC4A33"), (100, "#B8303F"), (120, "#8C2452"), (140, "#5E1F5E")]   # house gust palette, km/h
TOWNS = {"St. John's": (47.561, -52.713), "Clarenville": (48.165, -53.965), "Gander": (48.954, -54.609),
         "Grand Falls-Windsor": (48.936, -55.660), "Corner Brook": (48.951, -57.952), "Deer Lake": (49.174, -57.426),
         "Stephenville": (48.550, -58.581), "Port aux Basques": (47.572, -59.136), "St. Anthony": (51.364, -55.580),
         "Marystown": (47.166, -55.148), "Bonavista": (48.650, -53.115), "Burgeo": (47.617, -57.621),
         "Port au Choix": (50.709, -57.331), "Baie Verte": (49.932, -56.180)}
FIELDS = {"GUST": ":GUST:surface:", "U": ":UGRD:10 m above ground:", "V": ":VGRD:10 m above ground:"}


def get(run, fh):
    url = f"{RR.BASE}/rrfs.{run[:8]}/{run[8:]}/rrfs.t{run[8:]}z.2dfld.13km.f{fh:03d}.na.grib2"
    idx = RR.fetch(url + ".idx").decode().splitlines()
    out = {}
    for k, pat in FIELDS.items():
        i = next(j for j, l in enumerate(idx) if pat in l and ("hour fcst" in l and "max" not in l))
        a = int(idx[i].split(":")[1]); b = int(idx[i + 1].split(":")[1]) - 1
        g = pygrib.fromstring(RR.fetch(url, f"{a}-{b}"))
        out[k] = np.asarray(g.values, float)
        if k == "U":
            out["latlons"] = g.latlons()
    return out


def main(run, f0, f1, ne_path):
    f0, f1 = int(f0), int(f1)
    for m in (TOT, RR):
        m.LON0, m.LAT0, m.ZOOM = LON0, LAT0, ZOOM
        m.W, m.H = W, H
    LON, LAT = RR.frame_lonlat(1)
    land = TOT.land_mask() * TOT.nl_mask(ne_path, island_only=True)
    os.makedirs(os.path.join(HERE, "frames"), exist_ok=True)
    for f in os.listdir(os.path.join(HERE, "frames")):
        os.remove(os.path.join(HERE, "frames", f))
    hours = list(range(f0, f1 + 1))
    with ThreadPoolExecutor(4) as ex:
        data = list(ex.map(lambda fh: get(run, fh), hours))
    rg = RR.Regrid(*data[0]["latlons"], LAT, LON)
    # the 13 km grid is rotated: rotate grid-relative U/V to earth-relative using the local grid bearing
    la, lo = data[0]["latlons"]
    dlat, dlon = np.gradient(la, axis=1), np.gradient(lo, axis=1) * np.cos(np.radians(la))
    ang = np.arctan2(dlat, dlon)                                  # bearing of the grid's x axis from east
    cmap = ListedColormap([c for _, c in BANDS]); norm = BoundaryNorm([b for b, _ in BANDS] + [300], cmap.N)
    step = 8
    ys, xs = np.arange(0, H, step), np.arange(0, W, step)
    seeds = np.array([[x, y] for y in range(25, H - 20, 62) for x in range(25, W - 20, 62)], float)
    rt = datetime.strptime(run, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    frames = []
    for i, (fh, F) in enumerate(zip(hours, data)):
        gust = gaussian_filter(rg(F["GUST"]) * 3.6, 3)
        ue = F["U"] * np.cos(ang) - F["V"] * np.sin(ang)
        ve = F["U"] * np.sin(ang) + F["V"] * np.cos(ang)
        U, V = gaussian_filter(rg(ue), 2), -gaussian_filter(rg(ve), 2)          # screen y down
        fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
        ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
        fig.patch.set_alpha(0); ax.patch.set_alpha(0)
        g_land = np.ma.array(gust, mask=land < 0.5)
        ax.contourf(np.arange(W), np.arange(H), g_land, levels=[b for b, _ in BANDS] + [300], cmap=cmap, norm=norm, alpha=0.85)
        cs = ax.contour(np.arange(W), np.arange(H), g_land, levels=[60, 80, 100, 120], colors="#3A2A22", linewidths=1.1, alpha=0.75)
        ax.clabel(cs, fmt="%d", fontsize=11, inline=True, inline_spacing=4)
        sp = np.hypot(U, V)[::step, ::step]
        lw = 0.9 + 1.6 * np.clip((sp - 5) / 15, 0, 1)
        for col, wm, asz, al in (("white", 2.3, 0.01, .6), ("#10222B", 1.0, 1.2, .7)):
            ax.streamplot(xs, ys, U[::step, ::step], V[::step, ::step], start_points=seeds, color=col, linewidth=lw * wm,
                          arrowsize=asz, arrowstyle="-|>" if col != "white" else "-", integration_direction="both", maxlength=0.28,
                          density=3, broken_streamlines=True)
            for c in ax.get_children():
                if hasattr(c, "set_alpha") and type(c).__name__ in ("LineCollection", "FancyArrowPatch"):
                    if c.get_alpha() is None:
                        c.set_alpha(al)
        fig.savefig(os.path.join(HERE, "frames", f"{i:02d}.png"), transparent=True, dpi=100)
        plt.close(fig)
        vals = {}
        for n, (tla, tlo) in TOWNS.items():
            x, y = RR.px(tla, tlo)
            vals[n] = int(round(gust[int(min(max(y, 0), H - 1)), int(min(max(x, 0), W - 1))]))
        frames.append({"t": (rt + timedelta(hours=fh)).astimezone(NDT).strftime("%a %-I:%M %p"), "v": vals})
        print(fh, frames[-1]["t"], "max", int(np.nanmax(np.where(land > .5, gust, 0))))
    with open(os.path.join(HERE, "map.png"), "wb") as f:
        f.write(RR.fetch(f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{LON0},{LAT0},{ZOOM - 1:.3f},0/{W // 2}x{H // 2}@2x"
                         f"?attribution=false&logo=false&layer_id=state-label&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D"
                         f"&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"))
    t0, t1 = (rt + timedelta(hours=h) for h in (f0, f1))
    out = {"frames": frames, "run": f"RRFS {rt:%HZ} {rt:%b %-d} (parallel)", "bands": BANDS,
           "date": f"{t0.astimezone(NDT):%A %-I:%M %p} to {t1.astimezone(NDT):%A %-I:%M %p} NDT",
           "towns": {n: RR.px(*ll) for n, ll in TOWNS.items()}, "borders": RR.borders(ne_path)}
    with open(os.path.join(HERE, "frames.js"), "w") as f:
        f.write("// generated by build.py\nwindow.LOOP = " + json.dumps(out) + ";\n")
    print(len(frames), "frames", out["date"])


if __name__ == "__main__":
    main(*sys.argv[1:5])
