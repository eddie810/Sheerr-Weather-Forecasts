"""Snapshot of the Sheerr Stats numbers for the "Sheerr Weather Audience" dashboard on claude.ai.

Reads the admin-only endpoint GET /wp-json/sw-stats/v1/data (snippet 45) with the SW_WP_AUTH secret and
writes one JSON file per dashboard dataset into the output folder:

  daily.json        one row per finished day (NL time), last 90 days: views and people per platform
  top_pages.json    top website pages, last 28 days
  fb_top.json       top Facebook posts, last 28 days
  yt_top.json       top YouTube videos, last 28 days
  web_sources.json  where website visits come from, last 28 days
  yt_sources.json   where YouTube views come from, last 28 days
  ad_places.json    Sheerr Weather ad impressions and clicks by app page / website placement, last 28 days

Usage: python3 tools/claude_dashboard_snapshot.py <output folder>
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

API = "https://sheerrweather.ca/wp-json/sw-stats/v1/data"


def fetch(days):
    req = urllib.request.Request(f"{API}?days={days}&refresh=1", headers={"Authorization": "Basic " + os.environ["SW_WP_AUTH"]})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def iso(k):
    k = str(k)
    return f"{k[:4]}-{k[4:6]}-{k[6:8]}"


def main(out):
    os.makedirs(out, exist_ok=True)
    today = datetime.now(ZoneInfo("America/St_Johns")).strftime("%Y-%m-%d")
    d90, d28 = fetch(90), fetch(28)
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

    files = {
        "daily.json": daily,
        "top_pages.json": [{"page": p["title"] or p["path"], "path": p["path"], "views": p["views"], "people": p["users"]} for p in d28["web"]["pages"]],
        "fb_top.json": [{"post": p["message"] or "(no text)", "posted": p["when"], "url": p["url"], "reach": p["reach"], "views": p["views"], "link_clicks": p["link"], "reactions": p["reactions"], "comments": p["comments"], "shares": p["shares"]} for p in d28["fb"]["top"]],
        "yt_top.json": [{"video": v["title"], "url": "https://youtu.be/" + v["id"], "published": v.get("published"), "views": v["views"], "watch_hours": v["hours"], "avg_view_seconds": v["avgdur"]} for v in d28["yt"]["top"]],
        "web_sources.json": [{"source": s["name"], "visits": s["sessions"]} for s in d28["web"]["sources"]],
        "yt_sources.json": [{"source": s["name"], "views": s["views"]} for s in d28["yt"]["sources"]],
        "ad_places.json": [{"placement": a["name"], "where": "App" if a["where"] == "app" else "Website", "impressions": a["imp"], "clicks": a["clicks"]} for a in d28["ads"]["places"]],
    }
    for name, rows in files.items():
        with open(os.path.join(out, name), "w") as f:
            json.dump(rows, f, ensure_ascii=False)
    print(json.dumps({"today": today, "last_day": daily[-1]["day"] if daily else None, "rows": {k: len(v) for k, v in files.items()}}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dashboard-snapshot")
