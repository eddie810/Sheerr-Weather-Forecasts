"""3D still of the final snowfall total over the Long Range Mountains.

Terrain: Mapbox Terrain-RGB (vertically exaggerated). Snow: the final HRDPS frame,
8:1 and elevation-weighted exactly like the loop, draped over the terrain in the
same band colours. Renders long-range-3d-scene.png for long-range-3d.html.

  MAPBOX_ACCESS_TOKEN=... python3 render3d.py [elev] [azim] [exaggeration]
"""
import io
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LightSource  # noqa: E402
from matplotlib.image import imread  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates  # noqa: E402

import animate  # noqa: E402
import build  # noqa: E402

HERE = build.HERE
BOX = dict(lat=(48.80, 50.90), lon=(-58.25, -55.95))
STEP = 0.008                                   # ~0.9 km surface mesh
BANDS = [(2, "#D4ECF8"), (5, "#93CDEE"), (10, "#4AA3DD"), (15, "#2367B3"), (20, "#5B3FA6"), (30, "#8E3E9E")]
TOWNS = {"Rocky Harbour": (49.660, -57.912), "Cow Head": (49.920, -57.801), "Daniel's Harbour": (50.236, -57.580),
         "Deer Lake": (49.174, -57.426), "Corner Brook": (48.951, -57.952), "Hampden": (49.546, -56.853),
         "Port au Choix": (50.709, -57.331)}
PEAKS = {"Gros Morne": (49.594, -57.785)}


def terrain(lats, lons, tz=10):
    """Elevation (m) on a regular lat/lon mesh from Terrain-RGB tiles."""
    LO, LA = np.meshgrid(lons, lats)
    wx = (LO + 180) / 360 * 256 * 2 ** tz
    wy = (1 - np.log(np.tan(np.pi / 4 + np.radians(LA) / 2)) / np.pi) / 2 * 256 * 2 ** tz
    tx0, tx1, ty0, ty1 = int(wx.min() // 256), int(wx.max() // 256), int(wy.min() // 256), int(wy.max() // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = build.terrain_tile(tz, tx, ty)
    return map_coordinates(mosaic, [wy - ty0 * 256, wx - tx0 * 256], order=1)


def hexrgb(h):
    return np.array([int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)])


def main(elev="26", azim="-106", exag="11"):
    elev, azim, exag = float(elev), float(azim), float(exag)
    lats = np.arange(BOX["lat"][1], BOX["lat"][0], -STEP)
    lons = np.arange(BOX["lon"][0], BOX["lon"][1], STEP)
    z = terrain(lats, lons)
    land = z > 0.5

    # final snowfall: last hour of the newest HRDPS run (capped at Monday evening)
    run, last = animate.latest_run()
    end = min(last, animate.datetime.fromisoformat(animate.UNTIL.replace("Z", "+00:00")))
    glons, glats, mm = animate.sn_grid(run, end.strftime("%Y-%m-%dT%H:%M:%SZ"), dict(lat=(48.5, 51.2), lon=(-59.0, -55.6)))
    LO, LA = np.meshgrid(lons, lats)
    rows = (glats[0] - LA) / (glats[0] - glats[1])
    cols = (LO - glons[0]) / (glons[1] - glons[0])
    snow = map_coordinates(gaussian_filter(mm, 1.0), [rows, cols], order=1) * build.SNOW_RATIO / 10
    snow *= np.clip((z - build.SNOW_FLOOR_M) / (build.SNOW_FULL_M - build.SNOW_FLOOR_M), 0, 1)
    snow[~land] = 0

    # colours: pale land, snow bands on top, flat water
    rgb = np.ones(z.shape + (3,)) * hexrgb("#F3F5F4")
    for lo, col in BANDS:
        rgb[snow >= lo] = hexrgb(col)
    water = hexrgb("#AFC3CC")
    rgb[~land] = water
    ls = LightSource(azdeg=290, altdeg=32)
    shaded = ls.shade_rgb(rgb, gaussian_filter(np.where(land, z, 0), 0.6), vert_exag=4, dx=900, dy=900,
                          blend_mode="soft", fraction=1.0)
    shaded[~land] = water

    # metric x/y so the map isn't stretched; z exaggerated
    kx = 111.32 * math.cos(math.radians(np.mean(lats)))
    X, Y = (LO - lons[0]) * kx, (LA - lats[-1]) * 111.32
    Z = np.where(land, gaussian_filter(np.where(land, z, 0), 1.6), 0) / 1000 * exag   # light smoothing: no spikes

    fig = plt.figure(figsize=(10.8, 8.6), dpi=200)
    ax = fig.add_axes([-0.12, -0.16, 1.24, 1.32], projection="3d")
    ax.plot_surface(X, Y, Z, facecolors=shaded, rstride=1, cstride=1, linewidth=0, antialiased=False, shade=False)

    # solid base: dark side walls from the terrain edge down to a slab, so it reads as a 3D block
    base = -Z.max() * 0.35
    for xs, ys, zs, tone in [(X[0, :], Y[0, :], Z[0, :], .30), (X[-1, :], Y[-1, :], Z[-1, :], .42),
                             (X[:, 0], Y[:, 0], Z[:, 0], .36), (X[:, -1], Y[:, -1], Z[:, -1], .24)]:
        WX, WY = np.vstack([xs, xs]), np.vstack([ys, ys])
        WZ = np.vstack([np.full_like(zs, base), zs])
        col = np.array([0.20, 0.27, 0.31]) + tone * np.array([0.25, 0.25, 0.25])
        ax.plot_surface(WX, WY, WZ, color=col, linewidth=0, antialiased=False, shade=False)
    ax.set_box_aspect((X.max(), Y.max(), Z.max() * 1.35), zoom=1.22)
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    ax.set_facecolor("none")
    fig.patch.set_alpha(0)
    ax.set_zlim(base, Z.max() * 1.05)

    # label anchors: project each place (on the terrain surface) to image pixels; the page draws the labels
    from mpl_toolkits.mplot3d import proj3d
    fig.canvas.draw()
    labels = {}
    for kind, places in (("town", TOWNS), ("peak", PEAKS)):
        for n, (la, lo) in places.items():
            x, y = (lo - lons[0]) * kx, (la - lats[-1]) * 111.32
            zz = float(map_coordinates(Z, [[(lats[0] - la) / STEP], [(lo - lons[0]) / STEP]], order=1)[0])
            px = []
            for zlev in (zz, zz + 2.5):
                x2, y2, _ = proj3d.proj_transform(x, y, zlev, ax.get_proj())
                dx, dy = ax.transData.transform((x2, y2))
                px.append([round(dx / 2, 1), round((fig.bbox.height - dy) / 2, 1)])   # CSS px (image is 2x)
            cm = float(map_coordinates(snow, [[(lats[0] - la) / STEP], [(lo - lons[0]) / STEP]], order=1)[0])
            labels[n] = {"kind": kind, "ground": px[0], "top": px[1], "cm": round(cm)}

    out = os.path.join(HERE, "long-range-3d-scene.png")
    fig.savefig(out, dpi=200, transparent=True)
    import json
    with open(os.path.join(HERE, "long-range-3d.js"), "w") as f:
        f.write("// generated by render3d.py\nwindow.SCENE = " + json.dumps(
            {"labels": labels, "max": round(float(snow.max())), "valid": end.isoformat(), "run": run}) + ";\n")
    plt.close(fig)
    print("max snow", round(float(snow.max()), 1), "cm | valid", end.isoformat(), "| run", run)


if __name__ == "__main__":
    main(*sys.argv[1:4])
