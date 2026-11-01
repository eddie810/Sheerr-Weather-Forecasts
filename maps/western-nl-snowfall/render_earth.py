"""Google Earth-style 3D view of the final Long Range snowfall total.

Satellite imagery (Mapbox) draped on Terrain-RGB elevation, perspective camera,
atmospheric haze toward the horizon, snowfall bands as a translucent overlay.
Writes long-range-earth-scene.png and long-range-earth.js for long-range-earth.html.

  MAPBOX_ACCESS_TOKEN=... python3 render_earth.py [elev] [azim] [exaggeration]
"""
import io
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LightSource  # noqa: E402
from matplotlib.image import imread  # noqa: E402
from mpl_toolkits.mplot3d import proj3d  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates  # noqa: E402

import animate  # noqa: E402
import build  # noqa: E402
import render3d  # noqa: E402

HERE = build.HERE
BOX = dict(lat=(48.75, 51.60), lon=(-58.30, -55.40))      # runs on past the view so the far edge fades into haze
STEP = 0.004                                               # ~0.5 km mesh
HAZE = np.array([0.80, 0.86, 0.91])
TOWNS = render3d.TOWNS
PEAKS = render3d.PEAKS


def satellite(lats, lons, tz=11):
    """RGB satellite imagery sampled on the lat/lon mesh."""
    LO, LA = np.meshgrid(lons, lats)
    wx = (LO + 180) / 360 * 256 * 2 ** tz
    wy = (1 - np.log(np.tan(np.pi / 4 + np.radians(LA) / 2)) / np.pi) / 2 * 256 * 2 ** tz
    tx0, tx1, ty0, ty1 = int(wx.min() // 256), int(wx.max() // 256), int(wy.min() // 256), int(wy.max() // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3))
    tok = os.environ["MAPBOX_ACCESS_TOKEN"]
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            png = animate.fetch(f"https://api.mapbox.com/v4/mapbox.satellite/{tz}/{tx}/{ty}.jpg90?access_token={tok}")
            img = imread(io.BytesIO(png), format="jpg")[..., :3] / 255.0
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = img
    return np.dstack([map_coordinates(mosaic[..., c], [wy - ty0 * 256, wx - tx0 * 256], order=1) for c in range(3)])


def main(elev="18", azim="-112", exag="4"):
    elev, azim, exag = float(elev), float(azim), float(exag)
    lats = np.arange(BOX["lat"][1], BOX["lat"][0], -STEP)
    lons = np.arange(BOX["lon"][0], BOX["lon"][1], STEP)
    z = render3d.terrain(lats, lons, tz=11)
    land = z > 0.5
    LO, LA = np.meshgrid(lons, lats)

    # snow: final HRDPS frame, same treatment as the loop
    run, last = animate.latest_run()
    end = min(last, animate.datetime.fromisoformat(animate.UNTIL.replace("Z", "+00:00")))
    glons, glats, mm = animate.sn_grid(run, end.strftime("%Y-%m-%dT%H:%M:%SZ"), dict(lat=(48.4, 51.5), lon=(-59.0, -55.2)))
    snow = map_coordinates(gaussian_filter(mm, 1.0), [(glats[0] - LA) / (glats[0] - glats[1]), (LO - glons[0]) / (glons[1] - glons[0])],
                           order=1) * build.SNOW_RATIO / 10
    snow *= np.clip((z - build.SNOW_FLOOR_M) / (build.SNOW_FULL_M - build.SNOW_FLOOR_M), 0, 1)
    snow[~land] = 0

    # imagery, gently relit so the relief reads, then the snow bands laid over it translucently
    img = satellite(lats, lons)
    img = np.clip((img - 0.02) * 1.18, 0, 1) ** 0.92                       # a little lift and contrast
    ls = LightSource(azdeg=290, altdeg=35)
    img = ls.shade_rgb(img, gaussian_filter(z, 1.0), vert_exag=2.5, dx=550, dy=550, blend_mode="overlay", fraction=0.55)
    over = np.zeros(z.shape + (3,))
    alpha = np.zeros(z.shape)
    for lo, col in render3d.BANDS:
        sel = snow >= lo
        over[sel] = render3d.hexrgb(col)
        alpha[sel] = [0.22, 0.38, 0.52, 0.60, 0.66, 0.70][render3d.BANDS.index((lo, col))]
    alpha = gaussian_filter(alpha, 0.7)
    rgb = img * (1 - alpha[..., None]) + over * alpha[..., None]

    kx = 111.32 * math.cos(math.radians(np.mean(lats)))
    X, Y = (LO - lons[0]) * kx, (LA - lats[-1]) * 111.32
    Z = np.where(land, gaussian_filter(np.where(land, z, 0), 1.0), 0) / 1000 * exag

    # aerial perspective: blend toward haze with distance from the camera's near edge
    a = math.radians(azim)
    view = np.array([math.cos(a), math.sin(a)])                  # direction the camera sits in, seen from the scene
    d = -(X * view[0] + Y * view[1])
    d = (d - d.min()) / (d.max() - d.min())
    haze = np.clip((d - 0.15) / 0.85, 0, 1) ** 1.3 * 0.92
    rgb = rgb * (1 - haze[..., None]) + HAZE * haze[..., None]

    fig = plt.figure(figsize=(10.8, 9.0), dpi=200)
    ax = fig.add_axes([-0.25, -0.25, 1.5, 1.5], projection="3d", computed_zorder=False)
    ax.set_proj_type("persp", focal_length=0.42)
    ax.plot_surface(X, Y, Z, facecolors=rgb, rstride=1, cstride=1, linewidth=0, antialiased=False, shade=False)
    ax.set_box_aspect((X.max(), Y.max(), Z.max() * 1.6), zoom=2.05)
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    ax.set_facecolor("none")
    fig.patch.set_alpha(0)
    ax.set_zlim(0, Z.max() * 1.05)

    fig.canvas.draw()
    labels = {}
    for kind, places in (("town", TOWNS), ("peak", PEAKS)):
        for n, (la, lo) in places.items():
            x, y = (lo - lons[0]) * kx, (la - lats[-1]) * 111.32
            iy, ix = (lats[0] - la) / STEP, (lo - lons[0]) / STEP
            zz = float(map_coordinates(Z, [[iy], [ix]], order=1)[0])
            px = []
            for zlev in (zz, zz + 1.6):
                x2, y2, _ = proj3d.proj_transform(x, y, zlev, ax.get_proj())
                dx, dy = ax.transData.transform((x2, y2))
                px.append([round(dx / 2, 1), round((fig.bbox.height - dy) / 2, 1)])
            labels[n] = {"kind": kind, "ground": px[0], "top": px[1],
                         "cm": round(float(map_coordinates(snow, [[iy], [ix]], order=1)[0]))}

    fig.savefig(os.path.join(HERE, "long-range-earth-scene.png"), dpi=200, transparent=True)
    plt.close(fig)
    with open(os.path.join(HERE, "long-range-earth.js"), "w") as f:
        f.write("// generated by render_earth.py\nwindow.SCENE = " + json.dumps(
            {"labels": labels, "max": round(float(snow.max())), "valid": end.isoformat(), "run": run, "exag": exag}) + ";\n")
    print("max", round(float(snow.max()), 1), "cm | mesh", z.shape)


if __name__ == "__main__":
    main(*sys.argv[1:4])
