"""Weekly "This week at Sheerr Weather" graphic (1080x1350) for LinkedIn / Facebook.

Reads the Sheerr Stats numbers (GET /wp-json/sw-stats/v1/data, snippet 45) and the app's GA4 property
(weekly app users) with the SW_WP_AUTH secret, writes week.html next to the output and screenshots it
with the globally installed Node Playwright.

Usage: python3 tools/weekly_graphic.py <week start YYYY-MM-DD> <week end YYYY-MM-DD> <out.png> [busiest-day note]
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, timedelta

SITE = "https://sheerrweather.ca/wp-json/"
LOGO = "https://sheerrweather.ca/wp-content/uploads/2026/10/rate-card-logo.png"


def api(path, body=None, timeout=240):
    req = urllib.request.Request(SITE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Basic " + os.environ["SW_WP_AUTH"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def days_between(a, b):
    a, b = date.fromisoformat(a), date.fromisoformat(b)
    return [(a + timedelta(days=i)).strftime("%Y%m%d") for i in range((b - a).days + 1)]


def total(rows, field, keys):
    by = {str(r["k"]): r for r in rows}
    return sum((by.get(k, {}).get(field) or 0) for k in keys)


def fmt(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 100_000:
        return f"{round(n / 1000)}K"
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return f"{n:,}"


def chg(a, b):
    if not b:
        return ""
    p = (a - b) / b * 100
    return f'<em class="up">▲ {p:.0f}%</em>' if p >= 5 else ""  # a showcase graphic: only real gains


def main(start, end, out, note=""):
    d = api("sw-stats/v1/data?days=28&refresh=1")
    wk = days_between(start, end)
    pw = days_between(str(date.fromisoformat(start) - timedelta(days=7)), str(date.fromisoformat(end) - timedelta(days=7)))
    fbd, appd, webd, ytd, adsd = d["fb"]["page"]["daily"], d["app"]["daily"], d["web"]["daily"], d["yt"]["daily"], d["ads"]["daily"]
    # YouTube data runs 2-3 days behind: use the latest 7 days that have it
    yt_last = max(str(r["k"]) for r in ytd if r.get("views") is not None and str(r["k"]) <= end.replace("-", ""))
    ye = date(int(yt_last[:4]), int(yt_last[4:6]), int(yt_last[6:]))
    ywk = days_between(str(ye - timedelta(days=6)), str(ye))
    ypw = days_between(str(ye - timedelta(days=13)), str(ye - timedelta(days=7)))
    m = {
        "fb": (total(fbd, "views", wk), total(fbd, "views", pw)),
        "app": (total(appd, "views", wk), total(appd, "views", pw)),
        "web": (total(webd, "views", wk), total(webd, "views", pw)),
        "yt": (total(ytd, "views", ywk), total(ytd, "views", ypw)),
        "ads": (total(adsd, "imp", wk), total(adsd, "imp", pw)),
        "installs": (total(appd, "installs", wk), total(appd, "installs", pw)),
    }
    tot = sum(m[k][0] for k in ("fb", "app", "web", "yt"))
    ptot = sum(m[k][1] for k in ("fb", "app", "web", "yt"))
    ga = api("sw-ga/v1/report?property=498016949", {"dateRanges": [{"startDate": start, "endDate": end}], "metrics": [{"name": "totalUsers"}]})
    app_users = int(ga["rows"][0]["metricValues"][0]["value"])
    busy = max(wk, key=lambda k: sum(total(rows, "views", [k]) for rows in (fbd, appd, webd)))
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    rng = f"{s:%B} {s.day}–{e.day}, {e.year}" if s.month == e.month else f"{s:%B} {s.day} – {e:%B} {e.day}, {e.year}"
    ytsub = "views" + ("" if yt_last == end.replace("-", "") else f" · {date.fromisoformat(str(ye - timedelta(days=6))):%b} {(ye - timedelta(days=6)).day}–{ye:%b} {ye.day}")
    tiles = [("Facebook", "views", m["fb"]), ("Sheerr Weather app", "screen views", m["app"]), ("Ad impressions", "app + website", m["ads"]),
             ("YouTube", ytsub, m["yt"]), ("sheerrweather.ca", "page views", m["web"]), ("New app installs", "this week", m["installs"])]
    tiles_html = "".join(f'<div class="t"><div class="tl">{a}</div><div class="tv">{fmt(v[0])}</div><div class="ts"><span>{b}</span>{chg(*v)}</div></div>' for a, b, v in tiles)
    subs = int(d["yt"]["channel"]["subscriberCount"])
    fol = [(fmt(d["fb"]["followers"]) + "+", "Facebook followers"), (fmt(app_users) + "+", "App users this week"), (fmt(subs) + "+", "YouTube subscribers")]
    fol_html = "".join(f"<div><b>{a}</b><span>{b}</span></div>" for a, b in fol)
    bd = date(int(busy[:4]), int(busy[4:6]), int(busy[6:]))
    busy_line = f"Busiest day: <b>{bd:%A}, {bd:%B} {bd.day}</b>" + (f" · {note}" if note else "")
    big_chg = chg(tot, ptot).replace("<em", '<em style="display:block"', 1).replace("</em>", " vs. the week before</em>") if chg(tot, ptot) else ""
    html = f'''<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet"><style>
*{{box-sizing:border-box}}body{{margin:0}}
.g{{width:1080px;height:1350px;background:#EEF1F0;color:#10222B;font-family:"Source Sans 3",sans-serif;display:flex;flex-direction:column;position:relative;overflow:hidden}}
.hd{{background:#0C2236;color:#fff;padding:44px 64px 110px;position:relative}}
.hd:after{{content:"";position:absolute;right:-140px;top:-120px;width:520px;height:520px;border-radius:50%;border:2px solid rgba(43,166,222,.22)}}
.ey{{font:600 28px "Barlow Condensed";letter-spacing:.12em;text-transform:uppercase;color:#2BA6DE}}
h1{{font:800 92px/.92 "Barlow Condensed";text-transform:uppercase;margin:10px 0 0}}
.big{{margin:-84px 56px 0;background:#fff;border-radius:22px;box-shadow:0 18px 50px rgba(12,34,54,.14);padding:26px 40px;display:flex;align-items:center;justify-content:space-between;gap:24px;position:relative;z-index:2}}
.big .n{{font:800 116px/1 "Barlow Condensed";color:#0C2236}}
.big .l{{font:600 30px/1.2 "Source Sans 3";color:#4E656F;max-width:420px}}
.big .l em{{margin-top:6px;font-size:24px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:22px 56px 0}}
.t{{background:#fff;border:1px solid #D5DDDE;border-radius:18px;padding:16px 26px}}
.tl{{font:700 24px "Barlow Condensed";letter-spacing:.06em;text-transform:uppercase;color:#1C8CC4}}
.tv{{font:800 62px/1 "Barlow Condensed";color:#10222B;margin-top:4px}}
.ts{{font:600 21px "Source Sans 3";color:#6E838C;margin-top:6px;display:flex;justify-content:space-between;gap:10px}}
em{{font-style:normal;font-weight:700;white-space:nowrap}}em.up{{color:#0A7A3D}}
.fol{{display:grid;grid-template-columns:repeat(3,1fr);margin:20px 56px 0;border-top:2px solid #C9D3D4;padding-top:18px}}
.fol div{{text-align:center}}.fol b{{display:block;font:800 52px/1 "Barlow Condensed";color:#0C2236}}.fol span{{font:600 20px "Source Sans 3";color:#4E656F;text-transform:uppercase;letter-spacing:.04em}}
.busy{{margin:16px 56px 0;font:400 24px "Source Sans 3";color:#4E656F;text-align:center}}.busy b{{color:#10222B}}
.ft{{margin-top:auto;display:flex;justify-content:space-between;align-items:center;padding:0 56px 30px}}
.ft img{{height:58px}}.ft span{{font:600 20px "Source Sans 3";color:#6E838C;text-align:right;line-height:1.35}}
</style></head><body><div class="g" id="graphic">
<div class="hd"><div class="ey">{rng}</div><h1>This week at<br>Sheerr Weather</h1></div>
<div class="big"><div class="n">{fmt(tot)}+</div><div class="l">views across Facebook, the app, YouTube and sheerrweather.ca{big_chg}</div></div>
<div class="grid">{tiles_html}</div>
<div class="fol">{fol_html}</div>
<div class="busy">{busy_line}</div>
<div class="ft"><img src="{LOGO}" alt="Sheerr Weather"><span>Newfoundland and Labrador’s weather, every day<br>sheerrweather.ca</span></div>
</div></body></html>'''
    page = os.path.join(os.path.dirname(os.path.abspath(out)), "week.html")
    with open(page, "w") as f:
        f.write(html)
    shot = os.path.join(os.path.dirname(os.path.abspath(out)), "shot.js")
    with open(shot, "w") as f:
        f.write("const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:1080,height:1350}});"
                "await p.goto(process.argv[2],{waitUntil:'networkidle'});await p.evaluate(()=>document.fonts.ready);"
                "await (await p.$('#graphic')).screenshot({path:process.argv[3]});await b.close();})();")
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    subprocess.run(["node", shot, "file://" + page, os.path.abspath(out)], check=True, env=dict(os.environ, NODE_PATH=root))
    print(json.dumps({"week": [start, end], "yt": [ywk[0], yt_last], "total": tot, "prev": ptot, "m": m, "app_users": app_users, "busy": busy}))


if __name__ == "__main__":
    main(*sys.argv[1:4], *(sys.argv[4:5] or [""]))
