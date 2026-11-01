"""Overnight lows on the Northeast Avalon: Weather Underground PWS (via TWC) + ECCC stations (GeoMet SWOB).

Finds every PWS in the box, drops those failing TWC QC or not reporting in the last 30 min, and takes the
lowest temperature since midnight NDT. Writes obs.json.

  TWC_API_KEY=... python3 fetch_obs.py
"""
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = os.environ["TWC_API_KEY"]
BOX = dict(lat=(47.22, 47.80), lon=(-53.30, -52.60))
NDT = timezone(timedelta(hours=-2, minutes=-30))


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1 + i)


def near(p):
    b = get(f"https://api.weather.com/v3/location/near?geocode={p[0]:.3f},{p[1]:.3f}&product=pws&format=json&apiKey={KEY}")
    if not b:
        return []
    L = json.loads(b)["location"]
    return [dict(id=L["stationId"][i], name=L["stationName"][i], qc=L["qcStatus"][i], upd=L["updateTimeUtc"][i],
                 lat=L["latitude"][i], lon=L["longitude"][i]) for i in range(len(L["stationId"]))]


def day_obs(st):
    b = get(f"https://api.weather.com/v2/pws/observations/all/1day?stationId={st['id']}&format=json&units=m&numericPrecision=decimal&apiKey={KEY}")
    return st, (json.loads(b)["observations"] if b else [])


def main():
    now = time.time()
    midnight = datetime.now(NDT).replace(hour=0, minute=0, second=0, microsecond=0)
    grid = [(BOX["lat"][0] + 0.04 * i, BOX["lon"][0] + 0.05 * j)
            for i in range(int((BOX["lat"][1] - BOX["lat"][0]) / 0.04) + 1)
            for j in range(int((BOX["lon"][1] - BOX["lon"][0]) / 0.05) + 1)]
    stations = {}
    with ThreadPoolExecutor(12) as ex:
        for res in ex.map(near, grid):
            for s in res:
                stations[s["id"]] = s
    live = [s for s in stations.values() if s["qc"] != -1
            and BOX["lat"][0] <= s["lat"] <= BOX["lat"][1] and BOX["lon"][0] <= s["lon"] <= BOX["lon"][1]]
    print(len(stations), "stations found,", len(live), "not failing QC")
    out = []
    with ThreadPoolExecutor(12) as ex:
        for st, obs in ex.map(day_obs, live):
            lows = [o["metric"]["tempLow"] for o in obs
                    if o.get("metric") and o["metric"].get("tempLow") is not None
                    and datetime.fromisoformat(o["obsTimeUtc"].replace("Z", "+00:00")) >= midnight]
            cur = [o["metric"]["tempAvg"] for o in obs if o.get("metric") and o["metric"].get("tempAvg") is not None]
            last = datetime.fromisoformat(obs[-1]["obsTimeUtc"].replace("Z", "+00:00")).timestamp() if obs else 0
            if len(lows) >= 12 and now - last < 1800:           # a reasonably full night, and still reporting
                out.append(dict(st, low=min(lows), n=len(lows), now=cur[-1] if cur else None, src="PWS"))
    # ECCC stations
    b = get(f"https://api.weather.gc.ca/collections/swob-realtime/items?bbox={BOX['lon'][0]},{BOX['lat'][0]},{BOX['lon'][1]},{BOX['lat'][1]}"
            f"&datetime={midnight.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%SZ}/..&limit=2000&f=json")
    eccc = {}
    for f in json.loads(b)["features"] if b else []:
        p = f["properties"]
        vals = [v for v in (p.get("air_temp"), p.get("min_air_temp_pst1hr")) if v is not None]
        if not vals:
            continue
        k = p["stn_nam-value"]
        e = eccc.setdefault(k, dict(id=p["msc_id-value"], name=k, lat=f["geometry"]["coordinates"][1],
                                    lon=f["geometry"]["coordinates"][0], low=99, src="ECCC", n=0))
        e["low"] = min(e["low"], *vals); e["n"] += 1
    out += [e for e in eccc.values() if e["n"] >= 3]
    with open(os.path.join(HERE, "obs.json"), "w") as f:
        json.dump(dict(fetched=datetime.now(NDT).isoformat(timespec="minutes"), since=midnight.isoformat(), stations=out), f, indent=1)
    for s in sorted(out, key=lambda s: s["low"]):
        print(f"{s['low']:6.1f}  {s['src']:4} {s['id']:12} {s['name']:20} {s['lat']:.3f},{s['lon']:.3f} n={s['n']}")


if __name__ == "__main__":
    main()
