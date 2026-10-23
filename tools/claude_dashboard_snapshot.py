"""Snapshot of the Sheerr Stats numbers for the "Sheerr Weather Audience" dashboard on claude.ai.

Reads the admin-only endpoint GET /wp-json/sw-stats/v1/data (snippet 45) with the SW_WP_AUTH secret and
writes one JSON file per dashboard dataset into the output folder:

  daily.json        one row per finished day (NL time), last 90 days: views and people per platform, ad impressions
  top_pages.json    top website pages
  fb_top.json       top Facebook posts (posted in the period)
  yt_top.json       top YouTube videos (YouTube's period ends on its latest day of data)
  web_sources.json  where website visits come from
  yt_sources.json   where YouTube views come from
  ad_places.json    Sheerr Weather ad impressions and clicks by app page / website placement

The six lists have a `period` column (1, 7 or 28): yesterday, the last 7 and the last 28 finished days
(GET /wp-json/sw-stats/v1/tops?start=&end=).

Usage: python3 tools/claude_dashboard_snapshot.py <output folder>
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

API = "https://sheerrweather.ca/wp-json/sw-stats/v1/"
PERIODS = (1, 7, 28)


def get(path):
    req = urllib.request.Request(API + path, headers={"Authorization": "Basic " + os.environ["SW_WP_AUTH"]})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.load(r)


def fetch(days):
    return get(f"data?days={days}&refresh=1")


def iso(k):
    k = str(k)
    return f"{k[:4]}-{k[4:6]}-{k[6:8]}"


def main(out):
    os.makedirs(out, exist_ok=True)
    now = datetime.now(ZoneInfo("America/St_Johns"))
    today = now.strftime("%Y-%m-%d")
    d90 = fetch(90)
    for k in ("web", "app", "fb", "yt", "ads"):
        if isinstance(d90.get(k), dict) and d90[k].get("error"):
            sys.exit(f"{k}: {d90[k]['error']}")

    days = {}
    def put(rows, cols):
        for r in rows:
            day = iso(r["k"])
            if day < today:  # finished days only
                row = days.setdefault(day, {"day": day})
                for src, dst in cols.items():
                    row[dst] = r.get(src)
    put(d90["web"]["daily"], {"views": "web_views", "users": "web_people"})
    put(d90["app"]["daily"], {"views": "app_views", "users": "app_people"})
    put(d90["fb"]["page"]["daily"], {"views": "fb_views", "viewers": "fb_people"})
    put(d90["yt"]["daily"], {"views": "yt_views", "hours": "yt_hours"})
    put(d90["ads"]["daily"], {"app": "ads_app", "web": "ads_web", "clicks": "ad_clicks"})
    cols = ["day", "web_views", "web_people", "app_views", "app_people", "fb_views", "fb_people", "yt_views", "yt_hours", "ads_app", "ads_web", "ad_clicks"]
    daily = [{c: days[d].get(c) for c in cols} for d in sorted(days)]
    daily = [r for r in daily if r["web_views"] is not None]  # YouTube reports start a few days earlier

    yesterday = now.date() - timedelta(days=1)
    files = {k: [] for k in ("top_pages.json", "fb_top.json", "yt_top.json", "web_sources.json", "yt_sources.json", "ad_places.json")}
    for n in PERIODS:
        t = get(f"tops?start={yesterday - timedelta(days=n - 1)}&end={yesterday}")
        files["top_pages.json"] += [{"period": n, "page": p["title"] or p["path"], "path": p["path"], "views": p["views"], "people": p["users"]} for p in t.get("pages", [])]
        files["fb_top.json"] += [{"period": n, "post": p["message"] or "(no text)", "posted": p["when"], "url": p["url"], "reach": p["reach"], "views": p["views"], "link_clicks": p["link"], "reactions": p["reactions"], "comments": p["comments"], "shares": p["shares"]} for p in t.get("fb_top", [])]
        files["yt_top.json"] += [{"period": n, "video": v["title"], "url": "https://youtu.be/" + v["id"], "published": v.get("published"), "views": v["views"], "watch_hours": v["hours"], "avg_view_seconds": v["avgdur"], "yt_start": t.get("yt_start"), "yt_end": t.get("yt_end")} for v in t.get("yt_top", [])]
        files["web_sources.json"] += [{"period": n, "source": s["name"], "visits": s["sessions"]} for s in t.get("sources", [])]
        files["yt_sources.json"] += [{"period": n, "source": s["name"], "views": s["views"], "yt_start": t.get("yt_start"), "yt_end": t.get("yt_end")} for s in t.get("yt_sources", [])]
        files["ad_places.json"] += [{"period": n, "placement": a["name"], "where": "App" if a["where"] == "app" else "Website", "impressions": a["imp"], "clicks": a["clicks"]} for a in t.get("ad_places", [])]
    files["daily.json"] = daily
    for name, rows in files.items():
        with open(os.path.join(out, name), "w") as f:
            json.dump(rows, f, ensure_ascii=False)
    print(json.dumps({"today": today, "last_day": daily[-1]["day"] if daily else None, "rows": {k: len(v) for k, v in files.items()}}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dashboard-snapshot")
