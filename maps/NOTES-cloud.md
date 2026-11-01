# Sheerr Weather maps: notes (cloud sessions)

## Summary

Notes Claude keeps for building Sheerr Weather graphics, copied here so any session can use them.

- **How it works:** every graphic is a Python build that writes `data*.js` and PNG layers, plus an HTML page that
  draws them. `tools/shot.js` screenshots the page; `render.js` + ffmpeg makes the videos.
- **Keys:** they come from environment variables, by name only: `MAPBOX_ACCESS_TOKEN`, `TWC_API_KEY`,
  `HPFX_USER`, `HPFX_PASS`, `WOOF_KEY`. Never write a key value into a file or a commit.
- **House style:**
  - Barlow Condensed + Source Sans 3, paper `#EEF1F0`, ink `#10222B`, accent `#1C8CC4`, logo bottom-left.
  - Warnings are yellow on the outdoors map; Special Weather Statements are grey on a light map.
  - Times in NDT like "4:22 PM". No sponsor logo unless asked.
- **Biggest lessons:**
  - Retry flaky GeoMet / NOMADS / Overpass downloads.
  - Check labels for collisions and clipping before sending.
  - Use `WindGust_10m`, not `WindGust-Max`.
  - Strip the WMO header from HPFX files.
  - 2026 time zones: B.C., Alberta, N.W.T., Manitoba and NW Ontario west of 90°W don't fall back any more.

Below, word for word: the project `CLAUDE.md`, then the fixes and lessons recorded during the work. The paths in
`CLAUDE.md` refer to the original repo layout: `graphics/<name>/` is `maps/<name>/` here, and `tools/` is
`maps/tools/`.

---

## CLAUDE.md (verbatim)

# Sheerr Weather graphics: notes for Claude

Graphics for Sheerr Weather (Newfoundland and Labrador): maps, charts, alert graphics and 3D videos. Each lives in
`graphics/<name>/`: a Python `build.py`/`fetch.py` pulls data and writes `data*.js` + basemap images, an
`index.html` page draws the graphic, and the page is screenshotted to PNG (or rendered frame-by-frame to MP4).
Setup for a local machine: `SETUP.md` (scripts in `tools/`).

## Environment

- Python: use the project venv, `.venv/bin/python` (Mac) or `.venv\Scripts\python` (Windows). In the cloud, `python3`.
- Keys come from the environment: `MAPBOX_ACCESS_TOKEN`, `TWC_API_KEY`.
- Map layers: `data/ne/adm1.geojson` (provinces), `data/ne/roads.geojson`, `data/ne/lakes.geojson`,
  `data/roads_na.geojson` (Island roads). Fetch with `python tools/get_data.py` if missing.
- Static graphics: `node tools/shot.js "<page>?export&..." out.png [vw vh]`. Viewport 1112x1400 (default) for
  4:5 social 1080x1350; `1952 1130` for 16:9 1920x1080; `1300 760` for a 1280x720 YouTube thumbnail.
- 3D videos (three.js): serve the folder over HTTP, then run its `render.js` (needs ffmpeg).
  `tools/gl.js` picks the WebGL mode: GPU locally, SwiftShader in the cloud (override with `GL=gpu|software`).
- Commit and push finished graphics with their source; `_3d*/`, `data/`, `node_modules/`, `.venv/` are ignored.

## Common graphics

| Graphic | Build | Render |
|---|---|---|
| Highs/lows maps (Island, Labrador, NL), TWC icons + HRDPS shading | `graphics/nl-temps`: `build.py data/ne/adm1.geojson <day 0=today,1=tomorrow> <island\|labrador\|nl\|nl-low\|island-low> [roads]`. Island roads `data/roads_na.geojson`, Labrador `roads-labrador.geojson`. Town list + card offsets in `REGIONS`. | `index.html?export&nosponsor[&region=labrador]` (4:5) |
| RDPS rain / snow / "where snow is possible" / peak gusts | `graphics/rdps-totals`: `build.py data/ne/adm1.geojson <view> <startZ> <endZ>` (views in `VIEWS`, e.g. `nf-rain`, `nf-snowpot`, `gust-south`; `-social` variants are 4:5) | 16:9 `index.html?export&view=<v>&kind=<rain\|snowpot\|gust>`; 4:5 `social1.html?export&view=<v>-social&kind=...&key=tl` |
| Warning / special weather statement maps (EC zones) | `graphics/southcoast-oct23` (template): `build.py data/ne/roads.geojson <wind\|sws>`; probes, frames, towns and wording at the top of `build.py` / config `C` in `index.html` | `index.html?export&fmt=<social\|tv>&alert=<wind\|sws>` |
| RDPS low / pressure map | `graphics/rdps-low-oct24` | `index.html?export[&fmt=tv]` |
| Tropical storm (NHC cone/track) | `graphics/josephine` `build.py [advisory]` | `index.html?export[&fmt=tv]` |
| Observed gust bar chart | `graphics/gust-obs-oct23`: edit the `OBS` list in `index.html` | `?export&fmt=<tv\|social>` |
| Single-station hero map | `graphics/sagona-gust`: `build.py` (satellite), numbers in `index.html` | `?export&fmt=<tv\|social>` |
| ECT 50 3D fly-along | `graphics/ect50`: `fetch.py` (RDPS at checkpoints), `python -m http.server 8767` | `node render.js` (4:5) / `FMT=tv node render.js` (16:9) |
| Avalon highs 3D fly-over (NE → SE → N → SW), TWC icons + 1° HRDPS contours | `graphics/avalon-highs`: `build.py [day]` (towns per area in `AREAS`; camera per area in `AREA_VIEW` in `scene.js`), `python -m http.server 8768` | `node render.js` (4:5) |
| NL futurecast, tilted 3D map (HRDPS precip type over cloud cover, 4 hPa isobars + tracked H/L, live town temps + temperature chart, motion-interpolated, dark map, 16:9) | `graphics/atlantic-futurecast`: `build.py [hours] [start UTC e.g. 2026-10-26T15]` (latest HRDPS run, ~3 min; towns in `TOWNS`, chart towns in `CHARTS`, 5-minute steps via `SUB`; tilt in `index.html`: `TILT`, `PERSP`, `EYE`) | `node render.js` (16:9) / `FMT=story node render.js` (9:16, page `?fmt=story`); no server needed |
| Wind chill through the day, province (animated 4:5; HRDPS temp + wind, EC formula) | `graphics/nl-windchill`: `build.py [first UTC hour] [last UTC hour]` (default 9–24 today; card offsets in `CARD`) | `node render.js` (no server needed) |
| Euro wind / wave / NL temps 3D loops | `graphics/euro-wind`, `graphics/waves-3d`, `graphics/nl-temps/3d` | each has `render.js` (see its header for the port) |

Station observations (gusts, temps): ECCC SWOB via
`https://api.weather.gc.ca/collections/swob-realtime/items?f=json&bbox=...&datetime=...` (`max_pk_wnd_spd_10m_pst1hr`,
`max_pk_wnd_tm_pst1hr` give the hourly peak gust and its time).

## House style

- Fonts: Barlow Condensed (headings, labels, numbers; uppercase) + Source Sans 3 (body). Paper `#EEF1F0`, ink
  `#10222B`, secondary ink `#4E656F`/`#6E838C`, rules `#C9D3D4`, accent blue `#1C8CC4`. Logo `logo.png` bottom-left.
- Layout: eyebrow (place · day) in accent blue, big uppercase title, one-line summary, map/chart, fact boxes, footer
  with logo + small source line. Social is 4:5 (1080x1350); broadcast is 16:9 (1920x1080) with a side panel.
- Warning: yellow banner `#F2C230`, ink `#2A2100`, outline `#B98A00`, fill rgba(245,199,31,.55) on the outdoors map.
  Special weather statement: grey banner `#5B666B` with white text on the white/grey (light-v11) map.
- Gust colours: 40 `#FFF1B8`, 50 `#FFDD7A`, 60 `#FDBD4F`, 70 `#F79A3E`, 80 `#EE7136`, 90 `#DC4A33`, 100 `#B8303F`,
  120 `#8C2452`, 140 `#5E1F5E` (km/h).
- Times in NDT, written like "4:22 PM". Check labels don't collide and nothing is clipped before sending.
- No sponsor logo unless asked.

---

## Fixes and lessons learned (verbatim from Claude's saved session notes)

### Notes 1

- **GeoMet/Overpass connection resets:** added retries; used the mail.ru Overpass mirror for Labrador roads.
- **Mapbox Terrain-RGB 404 over ocean:** caught HTTPError and skipped the tile.
- **TWC alert headlines 404 over water:** skipped those points.
- **Missing alert regions:** found them with a grid probe.
- **User corrections:**
  - Statements are grey, not yellow.
  - Baie Verte is low elevation (led to the elevation adjustment).
  - Use 8:1.
  - Use 150 m, not 300.
  - Parson's Pond–Hawke's Bay was missing.
  - The Northern Peninsula top was cut off.
  - The hatching was confusing (removed).
  - Headline is "Days between snowflakes".
  - "We don't need NL labeled" (hid province names via setfilter).
  - The aurora map implied no visibility in the Maritimes and Newfoundland (added a horizon zone).
  - The sponsor slot was asked for.
- **HRDPS doesn't cover Colorado:** used RDPS for the shading.

Snow ratio, elevation weighting, label collision avoidance and shield placement were all solved as covered above. In verified ECCC data, YYT Oct 12 was a trace, not measurable snow; the user chose the "first flakes in 133 days" framing.

### Notes 2

| Error | Fix |
|---|---|
| OSM Overpass down | Used Natural Earth roads for the Island. |
| `streamplot` "start point outside data" | Kept seeds inside bounds. |
| Module name clash (two `build.py`) | importlib `_load()` with explicit paths. |
| Rotated-grid U/V | Rotated using the grid bearing. |
| REFD 1000 m too weak in RRFS | Switched to PRATE mm/h with BREAKS. |
| NOMADS listings empty | `--http1.1` plus a User-Agent. |
| ES module blocked on `file://` (CORS) | Serve via `python3 -m http.server 8765`. |
| 3D coast smeared on cliffs | Gaussian-smoothed heights into the sea. |
| Board edges and sea-colour seam | Big sea plane `#DCDCDD`, fog. |
| Final camera clipping towns | Moved to [30,1230,780]. |
| RDPS WindGust-Max too hot | Used WindGust_10m (matches TWC). |
| Wreckhouse underrepresented by the model | Override to EC's 110 with a note. |
| Labrador highs map lacks roads | NE has no Trunk types; mentioned to the user. |
| Stop hook flagged pycache | Removed from tracking; `.gitignore`. |

Other user-driven corrections: remove arrows; the headline text "Wind Warning" only; key placement; social not broadcast; borders over precipitation type.

### Notes 3

- **Deleted texture.png** with `rm t*.png`: regenerated it with texture.js. Later cleanups used specific names.
- **Labrador Terrain-RGB at z9 too slow:** tz = 7 when zoom < 6.5.
- **NOMADS curl exit 35 / IncompleteRead, GeoMet connection resets:** retry loops catching OSError and http.client.HTTPException, plus a download cache.
- **TWC empty alert response:** skip empty bodies.
- **RDPS 16:9 build failed** (time outside the pinned run): end = min(caps end, run + 84 h).
- **ECMWF StopIteration:** gust is `10fg3` after 90 h; accept either name and take pygrib messages in order.
- **pkill pattern killed its own shell:** reran the steps separately.
- **Southcoast land mask at tz 11 very slow:** tz = 9.
- **Burgeo-Ramea zone missed:** added inland probes.
- **Social footers clipped** (low map confidence box, SWS facts): shortened text and trimmed padding.
- **Stray Mapbox labels:** hid more label layers.
- **ECT runner offset from tags:** arc-length km mapping.
- **User: "map shake":** Gaussian-smoothed camera track; jerk was about 7× smaller.
- **User: "stuttery":** slower travel, 60 fps, effects stepped every frame.
- **User: "the big circles are not right, use the NHC track":** removed the merged forecast 34-kt radii; show only NHC's current wind field (34/50 kt) with the cone and track.
- **Post-tropical labels:** the shapefile STORMTYPE disagreed with the NHC discussion; used STORMSRC so every point from Thursday afternoon on is labelled P.
- **Euro wind:** labels cut at the edge (removed Dublin and Lisbon); Gander/Corner Brook label clash (dropped Gander).
- **Josephine:** label overlaps and framing; first point given the advisory time; closest time rounded.
- **User: "The SWS is normally done a white/gray map":** added `basemap_light` for the SWS.

### Notes 4

- **Timezone maps were wrong for 2026:** they showed B.C., Alberta, Manitoba and the N.W.T. falling back. The user said "Look up the lat st time zone changes...". After researching, I rebuilt build_map.py with canada_2026() zones and an OFF table, and set the striped set in social-map.html to NONE = {BC, YT, AB, SK, MB, AZ, QA}.
- **The user wanted times relative to noon Eastern, not NL** ("make sure NL is the only half hour"). Changed to UTC = 16 in social-map.html.
- **Country distinction:** the user said "make sure we know canada and the US are two different countries". Added a heavy border line computed as the shared Canada/US boundary, plus country labels.
- **Colour keying:** colours keyed by offset made every zone change colour. For the AccuWeather-style map, colour now follows the clock reading at a fixed instant.
- **shot.js path error:** running from a subfolder failed. Fixed by using absolute paths ($R/tools/shot.js).
- **Fall-back hero style collision:** the class "sun" collided with the sun disc. Renamed it.
- **HPFX files:** they have a WMO header before the HDF5 data. Fixed by stripping everything before `\x89HDF`.
- **A blocked chained sleep:** used an until-loop or background run instead.

---

## Other saved notes

- **2026 Canadian time zones (checked against official sources, Nov 1 2026 change):**
  - B.C. has been on permanent UTC−7 since Mar 8, 2026.
  - Alberta and the N.W.T. are on permanent UTC−6.
  - Manitoba and northwestern Ontario west of 90°W are on permanent UTC−5.
  - Yukon (−7), Saskatchewan (−6) and Quebec's Lower North Shore (−4) don't change.
  - Everyone else falls back. Newfoundland (UTC−3:30 tomorrow) is the only half-hour zone.
  - `timezones-fallback/social-map.html` + `build_map.py` is the correct version. The older `index.html`,
    `map.html` and `ladder.html` predate the 2026 changes.
- **Time comparisons:** compare clocks against a fixed instant (noon Eastern, `UTC = 16`), not against NL time. Show
  Canada and the U.S. as clearly different countries (heavy border line, country labels).
- **Gusts:** use `WindGust_10m` (matches TWC), not `WindGust-Max`. Each build script lists its exact GeoMet layer names.
- **SWOB observations:** `https://api.weather.gc.ca/collections/swob-realtime/items?f=json&bbox=...&datetime=...`.
  - `max_pk_wnd_spd_10m_pst1hr` and `max_pk_wnd_tm_pst1hr` give the hourly peak gust and its time.
  - Wind chill uses the 10-minute mean wind.
- **Snow:** use an 8:1 ratio for western NL wet snow, weighted by elevation. Low-elevation places (e.g. Baie Verte)
  get little or none.
- **SWS elevation:** use 150 m, not 300 m.
- **Mapbox:**
  - Hide basemap place/province labels with layer filters.
  - `basemap_light` (light-v11) is for Special Weather Statements.
  - Terrain-RGB tiles 404 over the ocean: skip them.
- **TWC:** alert headline lookups 404 over water, so skip those points. Find all alert zones with a grid of probes,
  plus inland probes.
- **HPFX:** the username and password come only from `HPFX_USER` / `HPFX_PASS`. The outputs are private: keep them
  git-ignored and don't post them.
- **Rendering:**
  - Call `tools/shot.js` with absolute paths when running from a subfolder.
  - ES-module pages (three.js scenes) need `python3 -m http.server <port>`, not `file://`.
  - Smooth camera tracks to avoid shake. Use 60 fps for fly-alongs.
  - Delete files by exact name.
- **Generated files:** `data*.js`, basemaps, renders, `data/`, `_3d*/`, `node_modules/`, `.venv/` and
  `__pycache__/` aren't committed. Rebuild before rendering.
