"""Static site generation.

Renders every page in `config/site.yml` into a directory that GitHub Pages
can serve. One page failing does not fail the build -- the index reports
what was skipped, so a transient upstream outage degrades the site rather
than taking it down.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from .blend import blend_hours, source_labels
from .config import Config, ConfigError
from .event import build_event, local_now, resolve_event_time
from .models import Location
from .providers import ProviderError
from .render import render

DEFAULT_SITE_CONFIG = Path(__file__).resolve().parent.parent / "config" / "site.yml"


@dataclass
class BuiltPage:
    location: Location
    title: str
    subtitle: str
    href: str
    kind: str


@dataclass
class FailedPage:
    name: str
    reason: str


def load_site_config(path: Path | str | None = None) -> dict[str, Any]:
    path = Path(path) if path else DEFAULT_SITE_CONFIG
    if not path.exists():
        raise ConfigError(f"Site config not found: {path}")
    return yaml.safe_load(path.read_text()) or {}


def build_site(config: Config, site_config: dict[str, Any], outdir: Path,
               build_providers, fetch_all, units_for) -> tuple[list[BuiltPage], list[FailedPage]]:
    """Render every configured page into `outdir`."""
    outdir = Path(outdir)
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)

    meta = site_config.get("site") or {}
    pages = site_config.get("pages") or []
    built: list[BuiltPage] = []
    failed: list[FailedPage] = []
    attributions: set[str] = set()

    for entry in pages:
        label = f"{entry.get('type', '?')}:{entry.get('location', '?')}"
        try:
            page = _build_page(config, entry, outdir, build_providers,
                               fetch_all, units_for, attributions, meta)
            if page:
                built.append(page)
        except (ProviderError, ConfigError, ValueError, SystemExit) as exc:
            failed.append(FailedPage(label, str(exc) or exc.__class__.__name__))

    index = render("index", "html", {
        "site": {"title": meta.get("title", "Forecasts"),
                 "description": meta.get("description"),
                 "refresh_hours": meta.get("refresh_hours", 3)},
        "events": [p for p in built if p.kind == "event"],
        "regions": [p for p in built if p.kind == "region"],
        "aviation": [p for p in built if p.kind == "aviation"],
        "forecasts": [p for p in built if p.kind == "forecast"],
        "failures": failed,
        "built_at": _index_time(built, config),
        "attributions": sorted(attributions),
        "standalone": True,
    })
    (outdir / "index.html").write_text(index)

    # Pages serves paths verbatim; this stops Jekyll touching the output.
    (outdir / ".nojekyll").write_text("")
    return built, failed


def _index_time(built: list[BuiltPage], config: Config) -> datetime:
    """Stamp the index in the timezone of the first location it lists."""
    if built:
        return local_now(built[0].location)
    if config.locations:
        return local_now(next(iter(config.locations.values())))
    return datetime.now().astimezone()


def _redirect(target: str, title: str) -> str:
    """A standing-still page that sends a reader on to `target`.

    GitHub Pages serves static files only, so a moved page needs a stub
    rather than a 301. The link is spelled out for anyone who arrives with
    JavaScript off or a redirect blocked.
    """
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n"
        f"<meta http-equiv=\"refresh\" content=\"0; url={target}\">\n"
        f"<link rel=\"canonical\" href=\"{target}\">\n"
        f"<title>{title}</title>\n</head>\n"
        f"<body><p>This board has moved to <a href=\"{target}\">{title}</a>.</p></body></html>\n"
    )


def _build_page(config: Config, entry: dict, outdir: Path, build_providers,
                fetch_all, units_for, attributions: set[str],
                site_defaults: dict | None = None) -> BuiltPage | None:
    site_defaults = site_defaults or {}
    kind = entry.get("type", "forecast")

    if kind == "aviation":
        from zoneinfo import ZoneInfo

        from .aviation.awc import fetch_metar, fetch_taf
        from .aviation.notams import fetch_notams
        from .aviation.risk import assess_factors, write_verdict
        from .aviation.runways import CYYT
        from .aviation.schedule import (ScheduleError, board_order, day_sections,
                                fetch_schedule, live_sample)
        from .models import Location as _Loc

        ap = CYYT
        raw_taf, periods = fetch_taf(ap.icao)
        metar = fetch_metar(ap.icao)
        notams = fetch_notams(ap.icao)
        # A board shows the day, not a rolling window: start at a fixed
        # local hour so this morning's flights stay on it.
        airport_now = datetime.now(ZoneInfo(ap.timezone))
        start_hour = int(entry.get("start_hour", 5))
        start = airport_now.replace(hour=start_hour, minute=0, second=0,
                                    microsecond=0).astimezone(timezone.utc)
        sample = bool(entry.get("sample"))
        try:
            flights = fetch_schedule(ap.icao, start, int(entry.get("hours", 12)))
        except ScheduleError as exc:
            # No key or quota exhausted: show live traffic rather than nothing.
            # Say so loudly — this fallback is a degraded page that still
            # builds green, so a silent one hid a broken schedule for a day.
            print(f"::warning::schedule unavailable at {ap.icao}, falling back "
                  f"to live traffic: {exc}")
            flights = live_sample(ap.latitude, ap.longitude)
            sample = True

        direction = str(entry.get("direction", "all"))
        if not flights:
            raise ProviderError(f"no flights in the window at {ap.icao}")

        # Live ADS-B cannot tell an arrival from a departure, so splitting a
        # sampled list by direction would empty the board rather than degrade
        # it. Show the sample whole and let the banner explain what it is.
        if direction == "both" and not sample:
            wanted = [("departure", "Departures"), ("arrival", "Arrivals")]
        elif direction in ("arrival", "departure") and not sample:
            wanted = [(direction, "Arrivals" if direction == "arrival" else "Departures")]
        else:
            wanted = [("all", "All movements")]

        now_utc = datetime.now(timezone.utc)
        tz = ZoneInfo(ap.timezone)
        assessments, boards = [], []
        for which, title in wanted:
            subset = (flights if which == "all"
                      else [f for f in flights if f.direction == which])
            if not subset:
                raise ProviderError(f"no {which} flights in the window at {ap.icao}")
            rows = [write_verdict(assess_factors(f, ap, periods, notams))
                    for f in board_order(subset, now_utc)]
            assessments += rows
            boards.append({
                "direction": which, "title": title,
                "sections": day_sections(rows, now_utc, tz,
                                         lambda a: a.flight.revised or a.flight.scheduled),
                "count": len(rows),
            })
        # Name the types the table could not resolve, so they can be added
        # rather than quietly graded as unknown.
        from .aviation.aircraft import unmatched_models
        unknown_types = unmatched_models()
        if unknown_types:
            print("::warning::unrecognised aircraft models at "
                  f"{ap.icao}: {', '.join(unknown_types)}")
        html = render(entry.get("template", "aviation"), "html", {
            "airport": ap, "assessments": assessments, "boards": boards,
            "metar": metar,
            "raw_taf": raw_taf, "notams": notams, "periods": periods,
            "tz": tz,
            "generated_at": datetime.now(ZoneInfo(ap.timezone)),
            "sample_mode": sample, "direction": direction,
            "assessed_by": ("claude" if any(a.source == "claude" for a in assessments)
                            else "rule-based"),
            "home": "./index.html", "standalone": True,
        })
        suffix = "" if direction in ("all", "both") else f"-{direction}s"
        href = f"aviation-{ap.iata.lower()}{suffix}.html"
        (outdir / href).write_text(html)
        # Pages this one replaced. A link already shared should still land
        # here rather than on a 404.
        for old_name in entry.get("also_at") or []:
            if old_name != href:
                (outdir / str(old_name)).write_text(_redirect(href, f"{ap.iata} flights"))
        pseudo = _Loc(name=ap.name, latitude=ap.latitude, longitude=ap.longitude,
                      timezone=ap.timezone, slug=href[:-5])
        flagged = sum(1 for a in assessments if a.colour != "green")
        label = {"arrival": "arrivals", "departure": "departures",
                 "both": "arrivals and departures"}.get(direction, "delay risk")
        return BuiltPage(pseudo, f"{ap.iata} {label}",
                         f"{len(assessments)} movements"
                         + (f", {flagged} flagged" if flagged else ", all clear"),
                         href, "aviation")

    if kind == "region":
        from .cli import build_region_context
        from .models import Location as _Loc

        provider = entry.get("provider") or site_defaults.get("provider") or "licensed"
        context = build_region_context(
            config, entry["region"], provider, int(entry.get("days", 5)),
            entry.get("units", "metric"), False,
            int(entry.get("narrative_days", 3)),
        )
        attributions.update(context["attributions"])
        context.update({"home": "./index.html", "standalone": True,
                        "attributions": sorted(attributions)})
        summary = context["summary"]
        html = render(entry.get("template", "region"), "html", context)
        href = f"region-{entry['region']}.html"
        (outdir / href).write_text(html)

        # A scoped fragment for embedding in another site (Squarespace and
        # the like cannot run this build, but can fetch a fragment).
        if entry.get("embed", True):
            embed_dir = outdir / "embed"
            embed_dir.mkdir(exist_ok=True)
            fragment = dict(context)
            fragment.update({"standalone": False, "home": None})
            body = render("region-embed", "html", fragment)
            (embed_dir / f"region-{entry['region']}.html").write_text(body)

            # A standalone document for iframing. Squarespace's editor
            # mangles pasted <style> and <link> tags, so an iframe is the
            # robust route: nothing can leak in either direction. It posts
            # its height to the parent so the frame can size itself.
            (embed_dir / f"region-{entry['region']}-frame.html").write_text(
                "<!doctype html>\n<html lang=\"en\">\n<head>\n"
                "<meta charset=\"utf-8\">\n"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
                f"<title>{summary.name} forecast</title>\n"
                "<style>html,body{margin:0;padding:0;background:#fff;"
                "color:#1b2733}body{padding:2px 0}</style>\n</head>\n<body>\n"
                + body +
                "\n<script>\n"
                "  (function () {\n"
                "    function send() {\n"
                "      var h = document.documentElement.scrollHeight;\n"
                "      parent.postMessage({ sheerrForecastHeight: h }, '*');\n"
                "    }\n"
                "    window.addEventListener('load', send);\n"
                "    window.addEventListener('resize', send);\n"
                "    // Expanding an alert changes the height.\n"
                "    document.addEventListener('toggle', send, true);\n"
                "    setTimeout(send, 400); setTimeout(send, 1500);\n"
                "  })();\n"
                "</script>\n</body>\n</html>\n")
        lead = summary.days[0] if summary.days else None
        subtitle = (f"{len(summary.members)} points"
                    + (f" · gusts to {lead.gust.high.value:.0f}" if lead and lead.gust else ""))
        pseudo = _Loc(name=summary.name, latitude=summary.members[0].latitude,
                      longitude=summary.members[0].longitude,
                      timezone=summary.timezone, slug=f"region-{entry['region']}")
        return BuiltPage(pseudo, summary.name, subtitle, href, "region")

    location = config.location(entry["location"])
    providers = build_providers(
        entry.get("provider") or site_defaults.get("provider") or "both"
    )
    days = int(entry.get("days", 7))
    units = entry.get("units", "metric")

    forecasts = fetch_all(providers, location, days, units, False)
    attributions.update(p.attribution for p in providers if p.attribution)
    unit_map = units_for(forecasts[0])

    if kind == "forecast":
        primary = forecasts[0]
        html = render(entry.get("template", "default"), "html", {
            "location": location,
            "current": primary.current,
            "days": primary.days,
            "alerts": primary.alerts,
            "units": unit_map,
            "generated_at": local_now(location),
            "attributions": sorted(attributions),
            "home": "./index.html",
            "standalone": True,
        })
        href = f"{location.slug}.html"
        (outdir / href).write_text(html)
        today = primary.days[0] if primary.days else None
        subtitle = (f"{today.phrase}, {today.high:.0f}{unit_map['temp']}"
                    if today and today.phrase and today.high is not None
                    else f"{days}-day forecast")
        return BuiltPage(location, location.name, subtitle, href, "forecast")

    if kind == "event":
        event_time = resolve_event_time(str(entry["when"]), location)
        if entry.get("expires_after") and event_time < local_now(location) - timedelta(hours=12):
            return None  # Event has passed; drop the page.

        event = build_event(location, event_time, forecasts,
                            event_name=entry.get("name", "Event"),
                            window_hours=int(entry.get("window", 3)))
        labels = source_labels(forecasts)
        blended = blend_hours({f.provider: f.hour_at(event_time) for f in forecasts}, labels)
        if not blended:
            raise ProviderError(
                f"no hourly data for {event_time:%Y-%m-%d %H:%M} at {location.name}"
            )

        window = []
        for offset in range(-int(entry.get("window", 3)), int(entry.get("window", 3)) + 1):
            slot = event_time + timedelta(hours=offset)
            row = blend_hours({f.provider: f.hour_at(slot) for f in forecasts}, labels)
            if row:
                row.is_event = offset == 0
                row.slot = slot
                window.append(row)

        from .cli import day_narrative
        forecast_text, forecast_day = day_narrative(
            location, forecasts, event_time.date(), days=max(days, 2))

        html = render(entry.get("template", "event"), "html", {
            "event": event,
            "blended": blended,
            "window": window,
            "forecast_text": forecast_text,
            "forecast_day": forecast_day,
            "sources": {f: blended.source_of(f) for f in
                        ["temperature", "precip_chance", "cloud_cover",
                         "wind_speed", "wind_gust", "wind_direction"]
                        if blended.source_of(f)},
            "units": unit_map,
            "attributions": sorted(attributions),
            "home": "./index.html",
            "standalone": True,
        })
        href = f"{location.slug}-{event.event_name.lower().replace(' ', '-')}.html"
        (outdir / href).write_text(html)
        return BuiltPage(location, event.event_name,
                         f"{event_time:%A, %B %-d} at {event_time:%-I:%M %p}",
                         href, "event")

    raise ConfigError(f"Unknown page type {kind!r}")
