# Sheerr Weather — working notes for Claude

Eddie Sheerr runs Sheerr Weather (Newfoundland & Labrador forecasts). Most day-to-day work is on the
WordPress site, not the Python code in this repo. Write to Eddie in plain language; he is not a developer.

## The website: sheerrweather.ca

- WordPress + Elementor on Hostinger. Moved off Squarespace on Oct 12, 2026 (all ~640 old posts and
  ~3,800 comments imported). Old `sheerrweather.ca/forecasts/<slug>` links redirect to the new posts.
- Domain is registered at Squarespace Domains; only the website A/CNAME records point at Hostinger.
  **Never touch the Google Workspace MX, google-site-verification TXT or _dmarc records** (email).
- Site timezone is America/St_Johns. Times Eddie gives are NDT/NST.

### Access

- REST API: `curl -H "Authorization: Basic $SW_WP_AUTH" https://sheerrweather.ca/wp-json/...`
  (`SW_WP_AUTH` is an environment secret = base64 of `admin:<application password>`). Never print it,
  never ask Eddie to paste passwords or tokens into the chat.
- Elementor MCP server is configured in `.mcp.json` (same secret). Use it for Elementor page layouts.
- Custom code lives in the **Code Snippets** plugin: `GET/POST /wp-json/code-snippets/v1/snippets[/<id>]`.
  Lint PHP locally (`php -l`, prefix `<?php`) before saving a snippet.
- Purge the LiteSpeed page cache after changes: `POST /wp-json/code-snippets/v1/snippets/23/activate`
  (single-use snippet that runs `litespeed_purge_all`).
- Private keys are stored as WordPress options and never exposed: `sw_twc_api_key` (weather.com / TWC),
  `sw_smg_token` (Streamology), `sw_fb_page_id` + `sw_fb_page_token` (Facebook Page "Meteorologist Eddie Sheerr", set in
  Settings → General; Page token expires Dec 18, 2026 unless Eddie swaps in a never-expiring one).
- To read TWC data (Eddie prefers TWC over other sources): add a temporary admin-only, read-only snippet
  that calls `api.weather.com` with `get_option('sw_twc_api_key')`, use it, then **delete it**.
  Useful endpoints: `/v3/wx/forecast/daily/5day`, `/v3/wx/forecast/hourly/2day`,
  `/v3/wx/observations/current`, `/v3/location/near?product=pws`, `/v2/pws/observations/current`.
- Environment Canada alerts (public): `https://api.weather.gc.ca/collections/weather-alerts/items?lang=en&province=NL&f=json`.

### Key snippets (Code Snippets IDs)

| ID | What it does |
|----|--------------|
| 5  | Live alert ticker, 24/7 channel slot fallback |
| 6  | App-style mobile layout and bottom tab bar |
| 7  | Google Ad Manager sponsor slots on posts (Morning Briefings: HPSL banner under the title; 300×250 units only when the post has a "sponsored by" line) |
| 11 | Homepage feeds: latest post, top stories, briefings, Latest Videos (YouTube playlist RSS, falls back to scraping the playlist page, then the last good list) |
| 16 | Blog page (/blog/) with compact pager |
| 18 | Storm Centre (YouTube live on top + `storm-centre-cams` 3-camera Streamology player) |
| 19 | Streamology camera players + camera weather banners (TWC currents per camera spot, temperature from nearest healthy PWS, one decimal) and the YouTube live embed (`SW_TV_YOUTUBE_ID`) on the homepage and /live/ (tap to play) |
| 21 | Info pages, contact form, footer, old Squarespace URL redirects |
| 27 | Streamology Player Builder (Tools → Player Builder; players stored in option `sw_players`) |
| 32 | Site search page |
| 34 | App feed at the old Squarespace address (`/forecasts?format=rss`) — the mobile app reads this |
| 39 | Facebook Page settings fields |
| 40 | Wreckhouse Wind Gauge page (/wreckhouse/): ECCC station + HRDPS forecast, warning level 100 km/h |
| 41 | Regional forecast pages (`[sw_region region="..."]`): next 3 periods + the 2 days after (TWC 5-day, 1-hour cache); regions in `sw_rg_regions()`, menu order in `sw_rg_menu()` (also feeds the region switcher on each page and the phone "More" menu). Homepage "Regional Forecasts" list is in Elementor (page 45) and must be updated by hand when a region is added |
| 42 | Facebook Page posting (admin-only): `GET /wp-json/sw-fb/v1/status`, `GET posts`, `GET insights/<id>`, `POST post` {message, link?, image_url?, scheduled_time?}, `DELETE post/<id>`, `GET comments/<id>` (commenter names are withheld by Facebook), `POST reply/<id>`, `POST hide/<id>`, `POST like/<id>`. Image posts need a public image URL (upload to WP media first). Show Eddie the caption/reply first unless he says to post/share it |
| 43 | Facebook link previews for scheduled posts: Facebook's crawler gets og: tags (title, excerpt, featured image) for a `future` post; everyone else still gets an uncached 404. So a Facebook link post can be scheduled with Facebook before the blog goes live (set the featured image first) |
| 44 | Google Analytics (GA4 Data API, read-only, admin-only): property `496478054`, service account key + property ID in Settings → General (never shown back). `GET /wp-json/sw-ga/v1/status`, `POST /wp-json/sw-ga/v1/report` (runReport body), `POST /wp-json/sw-ga/v1/realtime` (runRealtimeReport body). Eddie's own logged-in visits aren't tracked (snippet 35). `?property=498016949` reads the **app's** GA4 property (iOS + Android streams; events first_open, app_remove, NotificationClickthrough = push opens, PageView = app views/impressions, VideoView, WebView; no ad_impression events) |
| 45 | **Sheerr Stats** admin dashboard (WP admin → Sheerr Stats): "Today so far" box on top with a day picker (website page views + app views + Facebook views, plus people reached per platform and an "up to" total, vs. the day before; `GET /wp-json/sw-stats/v1/day?date=YYYY-MM-DD`; GA's today numbers fill in hours late) + GA website stats + App section + Ads section (snippet 51) (GA property 498016949) + Facebook Page-wide daily insights (page_media_view = Views/impressions, page_total_media_view_unique, engagements, follows, visits) + per-post stats; 7/28/90 days, by day/week; `GET /wp-json/sw-stats/v1/data?days=` (kept ready: 10-minute cron `sw_stats_warm_all` rebuilds 7 days every 10 min, 28 every 30, 90 every hour (API limits: GA tokens, Facebook app time) + today/yesterday; the endpoint returns the last good copy from option `sw_stats_last_<days>` at once and queues a background rebuild when it's over 15 min old; `&refresh=1` rebuilds now, 15–45 s). FB post insights via field expansion return lifetime + day rows: use lifetime |
| 51 | Google Ad Manager (read-only, admin-only): network `23311632740`, signs in as the GA service account (Executive role in Ad Manager). `GET /wp-json/sw-gam/v1/status`, `POST /wp-json/sw-gam/v1/report` {dimensions, metrics, start, end, filters?: {ADVERTISER_ID: [..]}} (REST API v1 report, runs ~4 s), `POST /wp-json/sw-gam/v1/call` {path, body?}. **Peak 2 Plains** units (names containing "peak") belong to a separate app and are left out of all Sheerr numbers. Feeds the Ads section of Sheerr Stats (`sw_stats_ads`, placements grouped by app page / website spot) |
| 53 | **Sponsor report pages**: private link per Ad Manager advertiser, `https://sheerrweather.ca/sponsor-report/<token>/` (noindex, uncached). Shows ads shown/clicks/where it ran (GAM, filtered by ADVERTISER_ID, Peak 2 Plains left out), Facebook posts + YouTube videos matching the sponsor's keywords or Page tag, and a written summary; periods yesterday / 7 / 28 days / campaign to date (from the latest order's start). Admin: Sheerr Stats → Sponsor Reports (create link, new link, turn off, keywords, campaign start override for sponsorships that began before their Ad Manager order, a note for the sponsor; option `sw_sponsors`). Also counts website posts naming the sponsor. Report cache key includes option `sw_sp_cache_v` (bumped on save; the object cache ignores direct DB deletes) and the REST data is marked no-cache for LiteSpeed. RMM: 2026-04-26 to 2026-10-19 (end override; ended campaigns open on "Full campaign"), keywords "Roebothan, MakeTheCall" (banner only from Oct 4). **Hickman Motors** = "HML" in Ad Manager (ID 5875242911): shown as Hickman Motors via `display` in its `sw_sponsors` entry, keyword "Hickman", campaign 2025-08-27 to 2026-09-02 (ended on all platforms). Post/video lists: options `sw_sp_fb_index` (since Aug 2025) + `sw_sp_yt_index`, topped up by daily cron `sw_sp_daily`; `POST /wp-json/sw-sponsor/v1/reindex` (admin). Public data: `GET /wp-json/sw-sponsor/v1/report?t=&period=` (3-hour cache). Never send a sponsor link without Eddie saying so |
| 55 | **Advertising Rate Card** at `/rate-card/` (redesigned web page, HTML in `sw_ratecard_html()`; images = media 3524 logo, 3525 Eddie photo; no phone number). Audience strip updates itself (12-h cache, last good copy in `sw_rc_stats_last`): FB followers, FB views / 28 days, weekly active app users, ad impressions / 28 days (Sheerr units), YouTube views / 28 days; TikTok is typed in Sheerr Stats → Rate Card (`sw_rc_tiktok`). "Who we reach" section: Facebook age/gender + top towns from a Meta Business Suite Audience CSV uploaded on that admin page (UTF-16; option `sw_rc_fb_aud`, Oct 2026 numbers built in), YouTube age/gender live (viewerPercentage), % of ad impressions in NL live (GAM REGION_NAME, shown rounded down to 5%). Stats cache transient is `sw_ratecard_stats`. Admins always see it; others need the password set there (`sw_rc_pass`, hashed; 30-day cookie; 10 tries / 15 min); no password = admins only. Noindex, uncached. **Function prefix `sw_rc_` is taken by the road-cams code — use `sw_ratecard_`** |
| 68 | **Sponsor proposals**: private page per proposal at `/sponsor-report/<token>/proposal/`, linked by a "View proposal" banner on that sponsor's report (snippet 53). Text/price per advertiser ID in `sw_prop_list()` (RMM 2026–27 winter renewal, with price); live audience numbers from `sw_ratecard_stats()`, results recap from `sw_sp_report(id,'campaign')`. Bottom form has two buttons: "Approve this proposal" (records name/date once in option `sw_prop_approvals`) and "I have questions" (question required, logged in `sw_prop_questions`, last 50); both email eddie@sheerrweather.ca with Reply-To set to the sponsor's email if given |
| 78 | **Partner reports** (content partners with no Ad Manager ads): private page `/partner-report/<token>/` (noindex, uncached), Last 28 days / since-start switch, Facebook reach/views/engagement + YouTube views per post. Config in option `sw_partners` (name, token, since, keywords, fb_ids / yt_ids to always include, exclude); posts come from the sponsor-report indexes (snippet 53), stats cached 6 h. **Best Kind Giving** (CFNL; videos since May 2026; keywords "Best Kind Giving, BestKindGiving, bestkindgiving.ca" — never plain "best kind", Eddie says it in forecasts). Never send a partner link without Eddie saying so |
| 48 | YouTube (Analytics + Data API, OAuth as eddie.sheerr@gmail.com, Google Cloud project "Sheerr Weather Website", app published/External): client ID/secret + Connect button in Settings → General, refresh token in option `sw_yt_refresh`. `GET /wp-json/sw-yt/v1/status`, `POST /wp-json/sw-yt/v1/report` (reports.query params), `POST /wp-json/sw-yt/v1/data` {path, params}. Data lags 2–3 days; thumbnail impressions/CTR not available via API. Also feeds the YouTube section of Sheerr Stats |

### Claude dashboard
"Sheerr Weather Audience" on claude.ai (https://claude.ai/artifact/3gv4M658YNsnyBcT5cR3Mv, Dashboard type): a snapshot of the
Sheerr Stats numbers (finished days only). `python3 tools/claude_dashboard_snapshot.py <dir>` writes its seven JSON files
(daily incl. ad impressions, top_pages, fb_top, yt_top, web_sources, yt_sources, ad_places; the six lists carry a `period` column 1/7/28
from `GET /wp-json/sw-stats/v1/tops?start=&end=`); upload each as an asset and point `datasets/<id>` at it. The page has a
Yesterday / 7 days / 28 days switch (`dash/params` period, default 28).
A scheduled task refreshes it every morning at 6:47 AM NL time.

## Blog posts

Always save as **draft** unless Eddie says publish/schedule. Show him what you wrote and flag guesses.

**Build posts from normal editor blocks** (`wp:paragraph`, `wp:heading`, `wp:list`/`wp:list-item`, `wp:image`,
`wp:separator`, `wp:embed`), **never Custom HTML (`wp:html`) blocks**, so Eddie can edit the text in the visual
editor without touching code. (The centred sponsor heading in Evening Forecasts can be a centred `wp:heading`.)

**Before editing a post Eddie may have open in the editor:** check its `modified` time, and ask him to
close or reload the editor first. Saving from a stale editor tab overwrites API changes (this happened).
Make targeted find/replace edits on the current content rather than rewriting the whole post.

### Morning Briefing (category 3)
- Title `Tuesday Morning’s Weather Briefing — October 13, 2026`, slug `tuesday-mornings-weather-briefing-october-13-2026`,
  excerpt `A detailed outlook about what to expect today across Newfoundland and Labrador.`
- Layout: title image (featured image too) → `Good <Day> Morning!` + 4–6 bullets → separator → discussion →
  (sponsor lines, when there's a sponsor) → regional forecasts → `Looking ahead:` → footer (app / 📍 Regional Forecast pages teaser linking every region page / Map Room / Highway Cams links).
- **No sponsor lines for now** (RMM's run ended Oct 19, 2026). Without a "sponsored by" line the post gets only the HPSL banner under the title, no 300×250 squares (snippet 7).
- Past sponsor: **Roebothan, McKay, Marshall** — `This morning’s update is sponsored by Roebothan, McKay, Marshall.`
  then `Visit MakeTheCall.ca today to learn more about how the law firm can help you!` (the ad unit lands between them, mid-post).
  Both sponsor lines are **centred** (`wp:paragraph {"align":"center"}`), with a separator line above and below the pair.
- Regions, in order: Eastern Newfoundland / the Avalon · Central · West Coast · South Coast ·
  Southwest / Wreckhouse · GNP and the Straits · Labrador / the Big Land.
- Usually scheduled for **5:00 AM NDT**; Eddie sends an app push alert around 6:30 AM with the link.
  App alert **description** is a short tease (2–3 sentences, not a full summary) and always ends with
  `Tap "see more" to read the update.` The push notification ends with "Tap here to read more." **Always give Labrador its own line in app descriptions,
  push alerts and social captions** (Eddie flagged that it kept getting left out).

### Evening Forecast (category 4)
- Usually written from Eddie's YouTube video captions. Fix caption mishearings and list the guesses.
- Layout: separator → YouTube embed → separator → centred `This evening’s forecast is sponsored by:` +
  sponsor banner → separator → write-up with `<h3>` sections → separator → "Don’t forget to…" footer.
- Sponsor: **Medicuro** banner (media ID 3310), linked to https://medicuro.ca/.
  Oct 20–21, 2026 videos were sponsored by **Amplifon** (banner media ID 3444, shown at 316px wide, linked to https://www.amplifon.com/).
  Use whichever sponsor Eddie's video names; ask if unsure.
- Featured image = the YouTube thumbnail Eddie sends.

### Voice
First person, conversational, practical ("give yourself a few extra minutes"), NL place names, °C, km/h, mm/cm.
Say "below freezing" or "below the freezing mark", never "below zero".
Quote Environment Canada warning details exactly (areas, gusts, timing).

## YouTube
Channel @EddieSheerr (`UCx20u4KYgqx3XGLuBm1Uabw`), forecasts playlist "Sheerr Weather"
(`PLRhEYLjVM6T3zn3xS6MN-1RUuyw2H4-lm`), 24/7 stream "Sheerr Weather 24" (ID in snippet 19).

## This repo
Python forecast generator (`sheerr/`, `templates/`, `config/`) — see README.md.
