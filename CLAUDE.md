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
| 41 | Regional forecast pages (`[sw_region region="..."]`): regions in `sw_rg_regions()`, menu order in `sw_rg_menu()` (also feeds the region switcher on each page and the phone "More" menu). Homepage "Regional Forecasts" list is in Elementor (page 45) and must be updated by hand when a region is added |
| 42 | Facebook Page posting (admin-only): `GET /wp-json/sw-fb/v1/status`, `GET posts`, `GET insights/<id>`, `POST post` {message, link?, image_url?, scheduled_time?}, `DELETE post/<id>`, `GET comments/<id>` (commenter names are withheld by Facebook), `POST reply/<id>`, `POST hide/<id>`, `POST like/<id>`. Image posts need a public image URL (upload to WP media first). Show Eddie the caption/reply first unless he says to post/share it |

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
  App teasers end with "Tap here to read more." **Always give Labrador its own line in app descriptions,
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
