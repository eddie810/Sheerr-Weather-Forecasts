# Sheerr Weather maps

The source for every Sheerr Weather (Newfoundland and Labrador) map, chart, alert graphic and video: the scripts
that build them, the page templates that draw them, the house styles, the logos, and one example image per type in
`examples/`. House style, notes and lessons learned: [`NOTES-cloud.md`](NOTES-cloud.md). Local machine setup:
[`SETUP.md`](SETUP.md).

## How every graphic works

Each graphic has its own folder (`maps/<name>/`):

1. **Build.** `build.py` (or `fetch.py`) downloads the data and writes `data*.js` plus basemap/shading PNGs next to the
   page. These outputs aren't committed, so **run the build before you render**.
2. **Draw.** `index.html` (or `social.html`, `loop.html`, ...) draws the graphic from those files. Open it in a browser
   to preview. `?export` removes the page padding for a pixel-exact capture.
3. **Render.**
   - Stills: `node ../tools/shot.js "<page>?export&..." out.png [vw vh]`.
   - Videos: `node render.js` (Playwright frames, then ffmpeg).

## One-time setup

```bash
cd maps
pip install -r requirements.txt      # requests, numpy, Pillow, shapely, matplotlib, astral, h5py, ...
npm install                          # playwright (for shot.js / render.js)
python3 tools/get_data.py            # Natural Earth layers -> maps/data/ (not committed, ~100 MB)
```

You also need ffmpeg for the videos. Fonts (Barlow Condensed and Source Sans 3) load from Google Fonts, so the
renderer needs internet. `tools/setup-mac.sh` and `tools/setup-windows.ps1` do all of the above on a fresh machine.

**Map layers after `get_data.py`:**

- `data/ne/adm1.geojson`: provinces and states.
- `data/ne/roads.geojson` and `data/ne/lakes.geojson`.
- `data/roads_na.geojson`: Island roads.

The commands below run from inside the graphic's folder, so those paths become `../data/...`.

**Viewport sizes for `shot.js`:**

| Size | Format |
|---|---|
| `1112 1400` (default) | 4:5 social, 1080x1350 |
| `1952 1130` | 16:9 broadcast, 1920x1080 |
| `1300 760` | YouTube thumbnail, 1280x720 |

**WebGL for the 3D videos:** `tools/gl.js` uses the GPU locally and SwiftShader in the cloud. Override it with
`GL=gpu|software`.

## Keys

The scripts read keys from environment variables. Only the names are listed here. Never commit a key value.

| Key name | Used for | Needed by |
|---|---|---|
| `MAPBOX_ACCESS_TOKEN` | Mapbox Static Images (outdoors / light / satellite basemaps), terrain-RGB | most map folders |
| `TWC_API_KEY` | The Weather Company: town forecasts, hourly forecasts, icons, alerts | highs/lows, alerts, Halloween, flight, overnight, thanksgiving |
| `HPFX_USER`, `HPFX_PASS` | EC HPFX private raw radar (volume scans) | `hpfx-ptype` only |
| `WOOF_KEY` | WOOF WRF 2 km runs | `woof-snow` (and `temp-drop` when using WOOF) |

These sources need no key:

- **ECCC MSC GeoMet** (`geo.weather.gc.ca`): RDPS, HRDPS and GDPS fields, plus the radar.
- **ECCC SWOB observations** (`api.weather.gc.ca`).
- **ECCC climate data**.
- **NHC**.
- **ECMWF open data**.
- **NOAA NOMADS**: GFS-Wave and RRFS.
- **Natural Earth**.

## Map types

### Temperatures

| Map | Folder | Build (in the folder) | Render | Data | Keys |
|---|---|---|---|---|---|
| Forecast highs / lows: Island, Labrador, all of NL (TWC icons, HRDPS shading) | `nl-temps` | `python3 build.py ../data/ne/adm1.geojson <day 0=today,1=tomorrow> <island\|labrador\|nl\|nl-low\|island-low> [roads]`. Island roads: `../data/roads_na.geojson`. Labrador roads: `roads-labrador.geojson`. Towns and card offsets: `REGIONS`. | `node ../tools/shot.js "index.html?export&nosponsor[&region=labrador]" out.png` (4:5) | TWC, HRDPS (GeoMet), Mapbox, Natural Earth | MAPBOX_ACCESS_TOKEN, TWC_API_KEY |
| NL temps 3D loop | `nl-temps/3d` | Run `nl-temps` build first. | `node render.js`. The port is in the file's header. | as above | as above |
| Current temps + wind chills (live station obs) | `nl-now` | `python3 build.py` | `shot.js "index.html?export"` (4:5) | ECCC SWOB, HRDPS, Mapbox, Natural Earth | MAPBOX_ACCESS_TOKEN |
| Wind chill through the day (animated) | `nl-windchill` | `python3 build.py [first UTC hour=9] [last UTC hour=24]`. Card offsets: `CARD`. | `node render.js` (4:5 MP4, no server) | HRDPS temp + wind (EC formula), Mapbox | MAPBOX_ACCESS_TOKEN |
| Temperature drop between two times | `temp-drop` | `python3 build.py [from UTC] [to UTC]` | `shot.js "index.html?export" out.png 1952 1130` | HRDPS (or RDPS/WOOF), Mapbox | MAPBOX_ACCESS_TOKEN |
| Avalon lowest temps this morning (observed) | `avalon-lows` | `python3 build.py` (reads `obs.json` / SWOB) | `shot.js "index.html?export"` | ECCC SWOB, TWC, Mapbox | MAPBOX_ACCESS_TOKEN, TWC_API_KEY |
| Avalon highs 3D fly-over | `avalon-highs` | `python3 build.py [day]`. Towns: `AREAS`. Camera: `AREA_VIEW` in `scene.js`. | `python3 -m http.server 8768`, then `node render.js` (4:5 MP4) | TWC, HRDPS, Mapbox terrain | MAPBOX_ACCESS_TOKEN, TWC_API_KEY |
| Atlantic Canada two-day outlook (e.g. Thanksgiving) | `atlantic-thanksgiving` | `python3 build.py ../data/ne/adm1.geojson [first_day_offset]` | `shot.js "index.html?export"` | TWC, Mapbox | MAPBOX_ACCESS_TOKEN, TWC_API_KEY |
| Overnight planner (one town: temp, feels-like, cloud) | `yyt-overnight` | `python3 build.py [lat,lon] [hours]` | `shot.js "index.html?export"` | TWC hourly | TWC_API_KEY |
| YYT "days since snow" | `yyt-first-snow` | `python3 build.py [year]` | `shot.js "index.html?export"` | ECCC climate daily data | none |

### Rain, snow and precipitation type

| Map | Folder | Build | Render | Data | Keys |
|---|---|---|---|---|---|
| RDPS rain / snow totals, "where snow is possible", snow/mix/rain, peak gusts | `rdps-totals` | `python3 build.py ../data/ne/adm1.geojson <view> <startZ> <endZ>`. Views are in `VIEWS`, e.g. `nf-rain`, `nf-snowpot`, `gust-south`, `lab-mix`. `-social` variants are 4:5. | 16:9: `shot.js "index.html?export&view=<v>&kind=<rain\|snowpot\|gust\|snowmix>" out.png 1952 1130`. 4:5: `shot.js "social1.html?export&view=<v>-social&kind=...&key=tl"` | RDPS / HRDPS (GeoMet), Mapbox, Natural Earth | MAPBOX_ACCESS_TOKEN |
| Labrador total snowfall contours | `labrador-snowfall` | `python3 build.py RUN VALID ../data/ne/adm1.geojson` | `shot.js "index.html?export" out.png 1952 1130` | HRDPS, Mapbox | MAPBOX_ACCESS_TOKEN |
| Western NL snowfall (static + Long Range build-up animation) | `western-nl-snowfall` | `python3 build.py RUN VALID ../data/ne/adm1.geojson [wide\|tight]`. Animation: `python3 animate.py [until]`. | `shot.js "index.html?export"`. Animation: `node render-anim.js`. | RDPS / HRDPS, Mapbox | MAPBOX_ACCESS_TOKEN |
| Southeast Labrador snow potential | `selab-snow` | `python3 build.py [run] [windows]` | `shot.js "index.html?export" out.png 1952 1130` | RDPS, Mapbox | MAPBOX_ACCESS_TOKEN |
| WOOF (WRF 2 km) snowfall | `woof-snow` | `python3 build.py <run id> [start UTC] [end UTC]` | `shot.js "index.html?export" out.png 1952 1130` | WOOF, Mapbox | WOOF_KEY, MAPBOX_ACCESS_TOKEN |
| NL futurecast, tilted 3D (precip type over cloud, isobars, H/L, town temps, chart) | `atlantic-futurecast` | `python3 build.py [hours] [start UTC e.g. 2026-10-26T15]`. Towns: `TOWNS`. Charts: `CHARTS`. Steps: `SUB`. Tilt: `TILT` / `PERSP` / `EYE` in `index.html`. | `node render.js` (16:9) or `FMT=story node render.js` (9:16), no server | HRDPS, Natural Earth | none |
| Future radar loop (HRDPS) | `future-radar` | `python3 build.py [hours]` | `node render.js` (`loop.html`) | HRDPS, Mapbox | MAPBOX_ACCESS_TOKEN |
| RRFS future radar (precip type, isobars, H/L) | `rrfs-radar` | `python3 build.py RUN FIRST_FH LAST_FH ../data/ne/adm1.geojson` | `node render.js` | NOAA RRFS (NOMADS), Mapbox | MAPBOX_ACCESS_TOKEN |
| Observed radar loop (3 h) | `radar-loop` | `python3 build.py [hours]` | `node render.js` | ECCC radar (GeoMet `RADAR_1KM_*`), Mapbox | MAPBOX_ACCESS_TOKEN |
| Radar precip-type loop from raw HPFX volume scans | `hpfx-ptype` | `python3 build.py [lon] [lat] [zoom] [frames] [place]` | `node render.js` (16:9 MP4). Outputs are private: don't post them publicly or commit them. | EC HPFX (private), Mapbox | HPFX_USER, HPFX_PASS, MAPBOX_ACCESS_TOKEN |
| Embeddable live radar frame | `radar-embed` | none (live page) | open `frame.html` | ECCC GeoMet WMS | none |
| Graupel explainer (animated) | `graupel` | none (static page) | `FMT=story\|tv node render.js`. Still: `shot.js "index.html?export"`. | none | none |
| Storm types explainer | `storm-types` | none | `shot.js "index.html?export"` | none | none |

### Wind, gusts and pressure

| Map | Folder | Build | Render | Data | Keys |
|---|---|---|---|---|---|
| Peak gust map (Straits, day window) | `straits-gust-oct19` | `python3 build.py [start_utc] [end_utc]` | `shot.js "index.html?export&fmt=<social\|tv>"` | HRDPS, Mapbox | MAPBOX_ACCESS_TOKEN |
| RRFS gust animation | `rrfs-wind` | `python3 build.py RUN FIRST_FH LAST_FH ../data/ne/adm1.geojson` | `node render.js` | RRFS, RDPS, Mapbox | MAPBOX_ACCESS_TOKEN |
| Observed gust bar chart | `gust-obs-oct23` | Edit the `OBS` list in `index.html` (values from ECCC SWOB). | `shot.js "index.html?export&fmt=<tv\|social>"` | ECCC SWOB | none |
| Single-station hero map (e.g. Sagona Island gust) | `sagona-gust` | `python3 build.py` (satellite basemaps). The numbers are in `index.html`. | `shot.js "index.html?export&fmt=<tv\|social>"` | Mapbox satellite, ECCC SWOB | MAPBOX_ACCESS_TOKEN |
| RDPS low / pressure map | `rdps-low-oct24` (closer view), `rdps-low-oct23` | `python3 build.py ../data/ne/adm1.geojson [run] [social\|tv]` | `shot.js "index.html?export[&fmt=tv]"` | RDPS MSLP (GeoMet), Mapbox | MAPBOX_ACCESS_TOKEN |
| Euro (ECMWF) wind / MSLP 3D loop | `euro-wind` | `python3 fetch.py [YYYYMMDDHH] [first_step] [last_step]` | `python3 -m http.server 8768`, then `node render.js` | ECMWF open data | none |
| Waves 3D loop | `waves-3d` | `python3 fetch.py [YYYYMMDDHH] [first_hour] [last_hour]` | `python3 -m http.server 8766`, then `node render.js` | NOAA GFS-Wave + GFS MSLP | none |
| Tropical storm cone / track (NHC) | `josephine` | `python3 build.py [advisory]` | `shot.js "index.html?export[&fmt=tv]"` | NHC, Mapbox | MAPBOX_ACCESS_TOKEN |

### Alert graphics (Wind Warnings and Special Weather Statements, EC zones)

All alert graphics follow the same pattern. Probes, frames, towns and wording are at the top of `build.py`, and the
config is `C` in `index.html`.

- **Template:** `southcoast-oct23`.
  - Build: `python3 build.py ../data/ne/roads.geojson <wind|sws>`.
  - Render: `shot.js "index.html?export&fmt=<social|tv>&alert=<wind|sws>"`.
- **Earlier copies:** `wreckhouse`, `wreckhouse-oct16`, `avalon-wind-oct17`, `east-wind`, `north-wind`,
  `northpen-wind-oct26`, `straits-wind-oct19`.
  - Build: `python3 build.py ../data/ne/roads.geojson`.
  - Render: `shot.js "index.html?export&fmt=<social|tv>"`.
- **SWS pages:** `western-nl-sws`, `selab-sws`, `labrador-west-sws`.
  - Build: `python3 build.py ../data/ne/adm1.geojson`.
  - Render: `shot.js "index.html?export[&fmt=tv]"`.

**Data:** TWC alerts and town forecasts, EC zone wording, Mapbox outdoors (warning) / light (SWS).
**Keys:** MAPBOX_ACCESS_TOKEN, TWC_API_KEY.

### Halloween / trick-or-treat

| Map | Folder | Build | Render | Data | Keys |
|---|---|---|---|---|---|
| Trick-or-treat regions map | `trick-or-treat` | `python3 build.py` | `shot.js "index.html?export" out.png 1952 1130` | Natural Earth | none |
| Trick-or-treat forecast (7 PM icons + temps) | `halloween-nl` | `python3 build.py ../data/ne/adm1.geojson` | `shot.js "index.html?export[&fmt=tv]"` | TWC hourly, GDPS / HRDPS | MAPBOX_ACCESS_TOKEN, TWC_API_KEY |
| Halloween precip-type story (rain / mix / snow) | `halloween-ptype` | `python3 build.py ../data/ne/adm1.geojson [run] [tv,social,lab,labtv]` | `shot.js "index.html?export&fmt=<tv\|social\|lab\|labtv>[&at=19]"`. Movie: `node render.js`. | RDPS (GeoMet) | none |
| Halloween night video (16:9) | `halloween-video` | `python3 build.py [valid UTC hour] [local slot]` | `node render.js` | TWC, RDPS | TWC_API_KEY |
| YouTube thumbnail | `yt-halloween` | none | `shot.js "index.html?export" thumb.png 1300 760` | none | none |

### Time change (clocks fall back)

| Map | Folder | Build | Render | Data | Keys |
|---|---|---|---|---|---|
| Sunrise/sunset before and after the change, NL towns | `fall-back` | `python3 build.py` (astral) | `shot.js "index.html?export"`. Hero: `shot.js "social.html?export[&fmt=tv]"`. | calculated (astral) | none |
| "What if we stopped changing clocks?" | `clock-whatif` | `python3 build.py` (astral) | `shot.js "index.html?export[&fmt=tv]"` | calculated | none |
| Canada + U.S. time zones today vs tomorrow (clock at a fixed instant) | `timezones-fallback` | `python3 build_map.py ../data/ne/adm1.geojson` | `shot.js "social-map.html?export[&fmt=tv]"`. This is the current 2026-correct page. `index.html`, `map.html` and `ladder.html` are older drafts that show B.C., Alberta, Manitoba and the N.W.T. falling back, which is wrong for 2026. | Natural Earth + zone table in the script | none |

### Other

| Map | Folder | Build | Render | Data | Keys |
|---|---|---|---|---|---|
| ECT 50 race fly-along (3D) | `ect50` | `python3 fetch.py [run]` (RDPS at checkpoints, `ect50.gpx`) | `python3 -m http.server 8767`, then `node render.js` (4:5) or `FMT=tv node render.js` | RDPS, Mapbox terrain | MAPBOX_ACCESS_TOKEN |
| Aurora tonight | `aurora` | `python3 build.py ../data/ne/adm1.geojson` | `shot.js "index.html?export"` | HRDPS cloud (GeoMet), Mapbox | MAPBOX_ACCESS_TOKEN |
| Flight forecast (YYT → MCO) | `flight` | `python3 build.py 2026-10-12` | `shot.js "index.html?export"` | TWC, Mapbox | MAPBOX_ACCESS_TOKEN, TWC_API_KEY |
| Locator overlay for a viewer video | `bonavista-locator` | `python3 build.py [../data/ne/adm1.geojson]` | `node render.js "<input video>" [out.mp4]` | Natural Earth | none |
| YouTube thumbnail (Avalon rain) | `yt-avalon-rain` | none | `shot.js "index.html?export" thumb.png 1300 760` | none | none |

Each `build.py` / `fetch.py` / `render.js` has a header docstring with its full usage and options.

## Examples

`examples/<folder>.jpg` holds one rendered example per folder (JPEG copies of the delivered PNG/MP4 frames).
`hpfx-ptype` has no example because its output is private radar data.

## Shared files

| File | What it is |
|---|---|
| `tools/shot.js` | Playwright screenshot of a page to PNG. Give it an absolute path, or run it from the graphic folder. |
| `tools/gl.js` | WebGL mode picker for the three.js renders |
| `tools/get_data.py` | Downloads the Natural Earth layers |
| `tools/setup-mac.sh`, `tools/setup-windows.ps1` | Fresh-machine setup |
| `*/logo.png`, `*/logo-white.png` | Sheerr Weather logo (dark ink / white), bottom-left on every graphic |
| `package.json`, `requirements.txt` | Node and Python dependencies |
