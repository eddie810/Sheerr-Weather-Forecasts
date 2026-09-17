"""Static site generation.

Renders every page in `config/site.yml` into a directory that GitHub Pages
can serve. One page failing does not fail the build -- the index reports
what was skipped, so a transient upstream outage degrades the site rather
than taking it down.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
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


def _build_page(config: Config, entry: dict, outdir: Path, build_providers,
                fetch_all, units_for, attributions: set[str],
                site_defaults: dict | None = None) -> BuiltPage | None:
    site_defaults = site_defaults or {}
    kind = entry.get("type", "forecast")
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

        html = render(entry.get("template", "event"), "html", {
            "event": event,
            "blended": blended,
            "window": window,
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
