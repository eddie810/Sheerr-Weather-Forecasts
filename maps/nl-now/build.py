"""Current temperatures and wind chills across Newfoundland (social 4:5): latest ECCC station observations (SWOB) at
the stations below, with Environment Canada wind chill from each station's temperature and 10-minute mean wind, over
HRDPS 2.5 km 2 m temperature for the same hour, shaded on Island land. Reuses the nl-temps build (frame, land mask,
coastline, roads, basemap, palette). Writes shade.png, map.png, data.js (window.NOW).

  MAPBOX_ACCESS_TOKEN=... python3 build.py
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
from matplotlib.image import imsave
from scipy.ndimage import gaussian_filter, map_coordinates

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(HERE, "..", "nl-temps"))
import build as nl  # noqa: E402

REGION = nl.REGIONS["island"]
# label -> (SWOB station name, card offset dx, dy from the station dot)
STATIONS = {
    "St. John's": ("St. John's International", 70, 95), "Argentia": ("ARGENTIA (AUT)", -105, 40),
    "St. Lawrence": ("ST LAWRENCE", -125, 30), "Burgeo": ("BURGEO NL", -40, 95), "Port aux Basques": ("PORT-AUX-BASQUES", -10, 95),
    "Stephenville": ("STEPHENVILLE RCS", -120, 20), "Corner Brook": ("CORNER BROOK", -120, -40), "Gros Morne": ("BERRY HILL", -120, -40),
    "St. Anthony": ("St. Anthony", 120, 30), "Twillingate": ("TWILLINGATE (AUT)", 100, -60), "Gander": ("Gander International", 110, -30),
    "Bonavista": ("BONAVISTA", 105, 15), "Terra Nova": ("TERRA NOVA NAT PARK CS", 30, 95), "Deer Lake": ("CORMACK RCS", 20, -95),
    "Badger": ("BADGER (AUT)", 10, 95),
}


def windchill(t, kmh):
    """Environment Canada wind chill; None where it doesn't apply (above 10 °C or wind under 5 km/h)."""
    if t is None or kmh is None or t > 10 or kmh < 5:
        return None
    v = kmh ** 0.16
    return min(t, 13.12 + 0.6215 * t - 11.37 * v + 0.3965 * t * v)


def swob(now):
    url = ("https://api.weather.gc.ca/collections/swob-realtime/items?f=json&limit=3000&bbox=-59.6,46.5,-52.5,51.8"
           f"&datetime={(now - timedelta(minutes=80)).strftime('%Y-%m-%dT%H:%M:00Z')}/..")
    latest = {}
    for f in json.loads(nl.fetch(url))["features"]:
        p = f["properties"]
        n, t = p.get("stn_nam-value"), p["date_tm-value"]
        if p.get("air_temp") is None:
            continue
        if n not in latest or t > latest[n]["date_tm-value"]:
            latest[n] = p
    return latest


def main(ne_path=os.path.join(ROOT, "data", "ne", "adm1.geojson"), roads_path=os.path.join(ROOT, "data", "roads_na.geojson")):
    (nl.LON0, nl.LAT0), nl.ZOOM, nl.BOX = REGION["center"], REGION["zoom"], REGION["box"]
    now = datetime.now(timezone.utc)
    obs = swob(now)
    proj = nl.projector()
    stations, times = {}, []
    for label, (sn, dx, dy) in STATIONS.items():
        p = obs.get(sn)
        if not p or (now - datetime.fromisoformat(p["date_tm-value"].replace("Z", "+00:00"))) > timedelta(minutes=45):
            print("no recent obs:", label, sn)                # keep every card to the same ~hour
            continue
        ws = p.get("avg_wnd_spd_10m_pst10mts") or p.get("avg_wnd_spd_10m_pst2mts")
        t = float(p["air_temp"])
        wc = windchill(t, ws)
        lat, lon = p["lat-value"] if "lat-value" in p else None, None
        stations[label] = {"t": round(t), "wc": None if wc is None else round(wc), "wind": None if ws is None else round(ws),
                           "dir": p.get("avg_wnd_dir_10m_pst10mts"), "gust": p.get("max_wnd_gst_spd_10m_pst10mts"),
                           "time": p["date_tm-value"], "stn": sn, "off": [dx, dy]}
        times.append(p["date_tm-value"])
    # station coordinates from the feature geometry
    url = ("https://api.weather.gc.ca/collections/swob-realtime/items?f=json&limit=3000&bbox=-59.6,46.5,-52.5,51.8"
           f"&datetime={(now - timedelta(minutes=80)).strftime('%Y-%m-%dT%H:%M:00Z')}/..")
    geo = {f["properties"].get("stn_nam-value"): f["geometry"]["coordinates"] for f in json.loads(nl.fetch(url))["features"]}
    for label, s in stations.items():
        lon, lat = geo[s["stn"]][:2]
        x, y = proj(lat, lon)
        s["xy"] = [round(x), round(y)]
        s["card"] = [round(x + s["off"][0]), round(y + s["off"][1])]
    # HRDPS 2 m temperature at the hour of the observations
    hour = max(times)[:13] + ":00:00Z"
    d0 = hour[:10]
    lons, lats, tt = nl.hrdps_daytime_max(d0, (int(hour[11:13]),))
    with open(ne_path) as f:
        feats = {ft["properties"].get("name"): ft["geometry"] for ft in json.load(f)["features"]}
    rings = [p[0] for p in feats["Newfoundland and Labrador"]["coordinates"] if len(p[0]) > 20]
    island = [g for g in rings if max(la for _, la in g) < 51.7 and min(lo for lo, _ in g) > -59.6]
    scale = 2
    land, LON, LAT = nl.land_mask(scale)
    isl = nl.in_rings(island, LON, LAT, land)
    ti = map_coordinates(gaussian_filter(tt, 1.0), [(lats[0] - LAT) / (lats[0] - lats[1]), (LON - lons[0]) / (lons[1] - lons[0])], order=1)
    band = np.clip((np.floor(ti / 2) * 2).astype(int), nl.BANDS[0], nl.BANDS[-2])
    rgba = np.zeros(band.shape + (4,))
    for b, c in nl.TC.items():
        rgba[band == b, :3] = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    rgba[..., 3] = isl * 0.78
    imsave(os.path.join(HERE, "shade.png"), rgba)
    with open(os.path.join(HERE, "map.png"), "wb") as f:
        f.write(nl.fetch(f"https://api.mapbox.com/styles/v1/mapbox/light-v11/static/{nl.LON0},{nl.LAT0},{nl.ZOOM},0/"
                         f"{nl.W}x{nl.H}@2x?attribution=false&logo=false&access_token={os.environ['MAPBOX_ACCESS_TOKEN']}"))
    obs_time = datetime.fromisoformat(max(times).replace("Z", "+00:00")).astimezone(nl.NDT)
    data = {"stations": stations, "colours": nl.TC, "bands_used": sorted(set(band[isl].tolist())),
            "coast": nl.coast_path(isl, scale), "obs_time": obs_time.strftime("%-I:%M %p NDT"),
            "obs_date": obs_time.strftime("%A, %B %-d"), "hrdps_valid": hour,
            "roads": nl.roads_layer(roads_path, REGION["roads"], proj, island, REGION.get("country", "CAN")),
            "labels": [list(l) for l in REGION.get("labels", [])]}
    with open(os.path.join(HERE, "data.js"), "w") as f:
        f.write("// generated by build.py\nwindow.NOW = " + json.dumps(data) + ";\n")
    print("obs", data["obs_time"], "| HRDPS", hour, "|", "HRDPS range", round(float(tt.min()), 1), round(float(tt.max()), 1))
    for k, s in stations.items():
        print(f"  {k:18s} {s['t']:>3}°  feels {s['wc']}  wind {s['wind']}  {s['time'][11:16]}Z  xy {s['xy']}")


if __name__ == "__main__":
    main()
