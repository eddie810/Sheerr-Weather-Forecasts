# Sheerr Weather Forecasts

Generate custom weather forecasts from the command line — for named locations
you configure, using wording you control.

Two data sources are blended field by field, so each number comes from the
source that does it best:

| Field | Source |
|---|---|
| Temperature, feels-like | The Weather Company |
| Chance of rain, precipitation | The Weather Company |
| Cloud cover, conditions, humidity | The Weather Company |
| Wind speed, gusts, direction | Open-Meteo (ECMWF IFS 0.25°) |
| Weather alerts | The Weather Company / Environment Canada |

Rendered output always states which source each number came from.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env     # then add your TWC API key
export TWC_API_KEY=...   # Open-Meteo needs no key
```

## Usage

```bash
# List configured locations
python -m sheerr.cli locations

# 7-day forecast
python -m sheerr.cli forecast witless-bay --days 7

# Conditions at a specific time — the reason this exists
python -m sheerr.cli event witless-bay --when "saturday 2pm" --name "Wedding"

# A shareable HTML page
python -m sheerr.cli event witless-bay --when "saturday 2pm" --name "Wedding" \
    --format html -o output/wedding.html

# Anywhere, without adding it to the config first
python -m sheerr.cli forecast --lat 47.28 --lon -52.83 --name "Witless Bay" \
    --timezone America/St_Johns
```

### Useful flags

| Flag | Does |
|---|---|
| `--when` | `"saturday 2pm"`, `"tomorrow 9am"`, or `2026-09-19T14:00` |
| `--window N` | Hours either side of the event to tabulate (default 3) |
| `--provider` | `twc`, `open-meteo`, `open-meteo:ecmwf_ifs025`, `both`, `all` |
| `--format` | `md`, `html`, `json` |
| `--units` | `metric` or `imperial` |
| `--template` | Template name, without extension |
| `--strict` | Fail instead of continuing when a provider errors |

## Customising

**Locations** live in `config/locations.yml`. Add an entry and it becomes a CLI
name. Quote region codes — unquoted `ON` is a YAML boolean.

```yaml
locations:
  witless-bay:
    name: Witless Bay
    region: "NL"
    latitude: 47.2814
    longitude: -52.8306
    timezone: America/St_Johns
```

**Wording** lives in `templates/`. Templates are Jinja, named
`<name>.<format>.j2`, so `--template event --format html` renders
`templates/event.html.j2`. Copy one, edit the prose, and pass `--template
yourname`. No Python changes needed.

Filters available in templates: `num`, `pct`, `clock`, `datestr`, `arrow`,
`wind_desc`.

**Field routing** lives in `DEFAULT_FIELD_SOURCES` in `sheerr/blend.py`. Wind
speed and direction deliberately follow gusts to the same model — mixing
sustained wind and gusts across models can produce a gust weaker than the
sustained wind, which is not physical.

## Layout

```
sheerr/
  cli.py          Command-line entry point
  config.py       Loads config/locations.yml
  models.py       Provider-neutral Forecast / Day / Hour model
  event.py        "Saturday 2pm" -> conditions at that hour
  blend.py        Field-level source routing, with provenance
  render.py       Jinja rendering and filters
  providers/      One module per upstream API
templates/        Forecast wording — edit these
config/           Your locations
```

Adding a source means adding a module under `providers/` that returns the
shared `Forecast` model, then registering it in `providers/__init__.py`.

## Notes

- `TWC_API_KEY` is read from the environment and never committed; `.env` is
  gitignored.
- Not every TWC plan authorises every endpoint. The provider tries the widest
  range first and falls back, so a 401 on one endpoint is not fatal.
- Providers can disagree substantially. That is signal, not noise — the
  `--provider both` output shows each source's attribution so you can see it.
