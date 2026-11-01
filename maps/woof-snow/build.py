"""1920x1080 snowfall map for the Island from a WOOF run (WRF, 2 km): total snow between two forecast hours.

WRF's SNOWNC is snow (liquid equivalent, mm) accumulated since the run started, so the total is SNOWNC at the end
minus SNOWNC at the start, converted to cm at SNOW_RATIO:1. The curvilinear WRF grid is interpolated onto the frame,
shaded on Island land only (Terrain-RGB land inside the NL outline). Basemap, land mask, outlines, highways and the
page come from graphics/rdps-totals (same frame and town list as its "island" view). Writes snow-shade.png, map.png,
data.js; wrfout fields are cached in _cache/.

  WOOF_KEY=... MAPBOX_ACCESS_TOKEN=... python3 build.py <run id> [start UTC, e.g. 2026-10-30T10] [end UTC, default run end]
"""
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

import httpx
import numpy as np
from matplotlib.image import imsave
from scipy.interpolate import LinearNDInterpolator
from scipy.ndimage import gaussian_filter
from scipy.spatial import Delaunay

HERE = os.path.dirname(os.path.abspath(__file__))
WOOF = "https://woof.recastsystems.com/api/v1"
FIELDS = ("SNOWNC", "RAINNC", "RAINC", "SNOWH", "T2")
SNOW_RATIO = 10
BANDS = [(0.5, "#D2EAF8"), (1, "#AAD7F2"), (2, "#7DBFEA"), (5, "#4AA3DD"), (10, "#2367B3"), (15, "#1B4C8F"),
         (25, "#5B3FA6"), (50, "#8E3E9E")]       # the rdps-totals snow scale, deepened at the low end to show on white land

spec = importlib.util.spec_from_file_location("rdps", os.path.join(HERE, "..", "rdps-totals", "build.py"))
rdps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rdps)


def hour(rid, man, when):
    """Surface fields at one valid time (from the cache, or downloaded from the run)."""
    from scipy.io import netcdf_file
    path = os.path.join(HERE, "_cache", rid, when.replace(":", "") + ".npz")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        H = {"Authorization": f"Bearer {os.environ['WOOF_KEY']}"}
        r = httpx.get(f"{WOOF}/runs/{rid}/files/{man['files'][when]}", headers=H, follow_redirects=False, timeout=60)
        tmp = path + ".nc"
        with httpx.stream("GET", r.headers["location"], timeout=900) as s, open(tmp, "wb") as f:   # signed link, no key
            s.raise_for_status()
            for chunk in s.iter_bytes(1 << 20):
                f.write(chunk)
        with netcdf_file(tmp, "r", mmap=False) as nc:
            np.savez_compressed(path, **{k: np.array(nc.variables[k][0], np.float32) for k in FIELDS + ("XLAT", "XLONG")})
        os.remove(tmp)
    return np.load(path)


ZOOM_IN = 7.6          # close-up on the snowiest area (about 6 degrees of longitude across)
ADM1 = os.path.join(HERE, "..", "..", "data", "ne", "adm1.geojson")
# extra communities for the close-up (the app's town list is thin away from the big centres)
MORE = {"Pasadena": (49.016, -57.598), "Cormack": (49.317, -57.383), "Howley": (49.167, -57.117), "Woody Point": (49.503, -57.917),
        "Trout River": (49.481, -58.124), "Cow Head": (49.917, -57.800), "Parson's Pond": (50.033, -57.700),
        "Daniel's Harbour": (50.237, -57.583), "Hawke's Bay": (50.600, -57.167), "Roddickton": (50.866, -56.120),
        "Englee": (50.727, -56.110), "Flower's Cove": (51.300, -56.733), "Plum Point": (51.067, -56.883),
        "Main Brook": (51.183, -56.017), "Raleigh": (51.567, -55.733), "Benoit's Cove": (49.017, -58.117),
        "Lark Harbour": (49.100, -58.367), "Lourdes": (48.650, -59.000), "Kippens": (48.550, -58.633),
        "St. George's": (48.433, -58.483), "Robinsons": (48.267, -58.783), "Codroy": (47.883, -59.383),
        "Doyles": (47.833, -59.217), "Rose Blanche": (47.617, -58.700), "Ramea": (47.523, -57.390),
        "Buchans": (48.817, -56.867), "Millertown": (48.817, -56.533), "Badger": (49.000, -56.067),
        "Botwood": (49.144, -55.348), "Bishop's Falls": (49.017, -55.483), "Lewisporte": (49.250, -55.050),
        "Robert's Arm": (49.483, -55.817), "King's Point": (49.583, -56.183), "La Scie": (49.967, -55.583),
        "Fleur de Lys": (50.117, -56.133), "Jackson's Arm": (49.867, -56.783), "Hampden": (49.550, -56.850),
        "Gambo": (48.783, -54.217), "Glovertown": (48.683, -54.033), "Musgrave Harbour": (49.450, -53.967),
        "Fogo": (49.717, -54.267), "Change Islands": (49.667, -54.417), "New-Wes-Valley": (49.150, -53.583),
        "Port Blandford": (48.350, -54.167), "Trinity": (48.367, -53.367), "Arnold's Cove": (47.750, -53.983),
        "Swift Current": (47.883, -54.217), "Burin": (47.033, -55.167), "Grand Bank": (47.100, -55.765),
        "St. Lawrence": (46.920, -55.393), "Belleoram": (47.517, -55.417), "St. Alban's": (47.874, -55.843),
        "Conne River": (47.817, -55.800), "Gaultois": (47.600, -55.900), "McCallum": (47.633, -56.233),
        "Francois": (47.583, -56.750), "Burnt Islands": (47.600, -58.883), "Whitbourne": (47.417, -53.533),
        "St. Mary's": (46.917, -53.580), "Trepassey": (46.737, -53.363), "Ferryland": (47.024, -52.890),
        "Harbour Grace": (47.700, -53.217), "Old Perlican": (48.083, -53.017), "Heart's Content": (47.883, -53.367),
        "Torbay": (47.667, -52.733), "Holyrood": (47.383, -53.133), "Gallants": (48.700, -58.233),
        "Stephenville Crossing": (48.500, -58.433), "Port au Port": (48.550, -58.717),
        "Gros Morne Mountain": (49.596, -57.784)}
PEAKS = ["Gros Morne Mountain"]           # drawn with a mountain marker instead of a town dot


def frame(center, zoom, towns):
    rdps.W, rdps.H = 1920, 1080
    (rdps.LON0, rdps.LAT0), rdps.ZOOM, rdps.TOWNS = center, zoom, towns


def render(sfx, at, snow_s, rain, b, meta):
    """Shading, town values, basemap and data file for the current frame."""
    LON, LAT = rdps.frame_lonlat()
    s = np.nan_to_num(at(snow_s, LON, LAT))
    land = rdps.land_mask() * rdps.nl_mask(ADM1, True)
    rgba = np.zeros(s.shape + (4,))
    for lo, col in BANDS:
        sel = s >= lo
        rgba[sel, :3] = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        rgba[sel, 3] = 0.85
    rgba[..., 3] *= land
    imsave(os.path.join(HERE, f"snow-shade{sfx}.png"), rgba)

    lat_t = [ll[0] for ll in rdps.TOWNS.values()]
    lon_t = [ll[1] for ll in rdps.TOWNS.values()]
    tv = at(snow_s, lon_t, lat_t)
    rv = at(gaussian_filter(rain, 1.0), lon_t, lat_t)
    depth = at(b["SNOWH"] * 100, lon_t, lat_t)
    out = dict(meta, **{
        "kinds": {"snow": {"unit": "cm", "bands": BANDS, "towns": {n: round(float(x), 1) for n, x in zip(rdps.TOWNS, tv)}}},
        "xy": {n: rdps.px(*ll) for n, ll in rdps.TOWNS.items()},
        "outlines": rdps.outlines(ADM1), "roads": rdps.roads_layer("island"), "peaks": PEAKS,
        "max": round(float((s * (land > .5)).max()), 1)})
    with open(os.path.join(HERE, f"data{sfx}.js"), "w") as f:
        f.write("// generated by build.py\nwindow.TOT = " + json.dumps(out) + ";\n")
    # basemap without Mapbox's town and province names (they'd clash with ours): the static API hides one layer per
    # request, so fetch it once per label layer and keep the lightest pixel
    import io
    from PIL import Image
    def base(layer):
        return np.asarray(Image.open(io.BytesIO(rdps.fetch(
            f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{rdps.LON0},{rdps.LAT0},{rdps.ZOOM - 1:.3f},0/960x540@2x"
            f"?attribution=false&logo=false&layer_id={layer}&setfilter=%5B%22%3D%3D%22%2C%22class%22%2C%22none%22%5D"
            f"&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"))).convert("RGB"))
    from scipy.ndimage import binary_dilation, median_filter
    ims = [base(l) for l in ("settlement-minor-label", "settlement-major-label", "state-label", "natural-point-label", "poi-label", "country-label")]
    m = np.maximum.reduce(ims)                                  # each label is missing from one image, so max drops it
    diff = binary_dilation(np.ptp(np.stack(ims).astype(int), axis=0).max(2) > 6, iterations=3)   # where any had a label
    bg = median_filter(m, size=(25, 25, 1))                                                   # its halo goes too
    m[diff] = bg[diff]
    Image.fromarray(m).save(os.path.join(HERE, f"map{sfx}.png"))
    print(f"[{sfx or 'island'}]", out["from"], "->", out["to"], "| max", out["max"], "cm")
    for n, x, r_, dp in zip(rdps.TOWNS, tv, rv, depth):
        print(f"  {n:22s} snow {x:5.1f} cm  rain {r_:5.1f} mm  on ground at end {dp:5.1f} cm")
    return s, land


def main(rid, start=None, end=None):
    d = httpx.get(f"{WOOF}/runs/{rid}/manifest", headers={"Authorization": f"Bearer {os.environ['WOOF_KEY']}"},
                  timeout=60).json()["manifest"]
    man = {"init": d["init"], "times": d["validTimes"], "files": {a["validTime"]: a["key"] for a in d["artifacts"]["wrfout"]}}
    pick = lambda s, dflt: next(t for t in man["times"] if t.startswith(s)) if s else dflt
    t0, t1 = pick(start, man["times"][0]), pick(end, man["times"][-1])
    a, b = hour(rid, man, t0), hour(rid, man, t1)
    snow = np.clip(b["SNOWNC"] - a["SNOWNC"], 0, None) * SNOW_RATIO / 10                      # cm
    rain = np.clip((b["RAINNC"] + b["RAINC"]) - (a["RAINNC"] + a["RAINC"]), 0, None) - np.clip(b["SNOWNC"] - a["SNOWNC"], 0, None)
    # WRF grid -> any lon/lat (linear on a Delaunay triangulation of the model grid)
    tri = Delaunay(np.column_stack([b["XLONG"].ravel(), b["XLAT"].ravel()]))
    at = lambda f, x, y: LinearNDInterpolator(tri, f.ravel())(x, y)
    snow_s = gaussian_filter(snow, 1.0)
    ndt = lambda t: datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(rdps.NDT).strftime("%a %-I:%M %p NDT")
    meta = {"run": man["init"], "from": ndt(t0), "to": ndt(t1), "model": "Sheerrcast 2 km",
            "ratio": SNOW_RATIO,                                   # ECMWF open data is CC BY 4.0: this notice is required
            "note": f"Contains modified ECMWF open data © {t1[:4]} ECMWF, CC BY 4.0"}

    v = rdps.VIEWS["island"]
    frame(v["center"], v["zoom"], v["towns"])
    s, land = render("", at, snow_s, rain, b, meta)

    # close-up: centre on the snowiest area over Island land (smoothed widely, so one spike doesn't steer it)
    heavy = gaussian_filter(s * (land > .5), 60)
    iy, ix = np.unravel_index(heavy.argmax(), heavy.shape)
    LON, LAT = rdps.frame_lonlat()
    c = (round(float(LON[iy, ix]), 3), round(float(LAT[iy, ix]), 3))
    near = {t["name"]: (t["lat"], t["lon"]) for t in json.load(open(os.path.join(HERE, "..", "..", "app", "towns.json")))}
    near.update(MORE)
    near.update(v["towns"])
    frame(c, ZOOM_IN, {})
    inside = lambda la, lo: 60 < rdps.px(la, lo)[0] < 1860 and 60 < rdps.px(la, lo)[1] < 1020
    rdps.TOWNS = {n: ll for n, ll in near.items() if inside(*ll) and n not in ("Port Saunders",)}   # too close to Port au Choix
    print("close-up centre", c, len(rdps.TOWNS), "towns")
    render("-zoom", at, snow_s, rain, b, meta)


if __name__ == "__main__":
    main(*sys.argv[1:4])
