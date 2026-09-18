"""Command-line interface.

    sheerr forecast witless-bay --days 5
    sheerr event witless-bay --when "saturday 2pm" --name "Wedding"
    sheerr locations
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .blend import blend_hours, source_labels
from .config import Config, ConfigError
from .event import build_event, local_now, resolve_event_time
from .models import Location
from .providers import ProviderError, get_provider
from .render import RenderError, render

#: `--provider` values that expand to several sources.
PROVIDER_SETS = {
    # Default: TWC for temperature and precipitation, ECMWF open data for
    # wind, plus Open-Meteo as a fallback if the ECMWF fetch fails.
    "both": ["twc", "ecmwf", "open-meteo:ecmwf_ifs025"],
    "default": ["twc", "ecmwf", "open-meteo:ecmwf_ifs025"],
    # Only sources whose licences permit commercial redistribution outright.
    # Open-Meteo's free endpoint is non-commercial, so it is excluded here.
    "licensed": ["twc", "ecmwf"],
    "all": ["twc", "ecmwf", "open-meteo", "open-meteo:ecmwf_ifs025"],
}


def build_providers(spec: str):
    """Turn a --provider value into provider instances."""
    names = PROVIDER_SETS.get(spec, [s.strip() for s in spec.split(",") if s.strip()])
    providers = []
    for name in names:
        base, _, model = name.partition(":")
        providers.append(get_provider(base, model=model) if model else get_provider(base))
    return providers


def fetch_all(providers, location: Location, days: int, units: str, strict: bool):
    """Fetch from each provider, tolerating individual failures."""
    forecasts, failures = [], []
    for provider in providers:
        try:
            forecasts.append(provider.fetch(location, days=days, units=units))
        except ProviderError as exc:
            failures.append(str(exc))
            print(f"warning: {exc}", file=sys.stderr)
    if not forecasts:
        raise SystemExit("error: no provider returned a forecast:\n  " + "\n  ".join(failures))
    if strict and failures:
        raise SystemExit("error: --strict set and a provider failed")
    return forecasts


def units_for(forecast):
    return {"temp": forecast.temp_unit, "speed": forecast.speed_unit,
            "precip": forecast.precip_unit}


def resolve_location(args, config: Config) -> Location:
    if args.lat is not None and args.lon is not None:
        return Location(name=args.name or f"{args.lat},{args.lon}",
                        latitude=args.lat, longitude=args.lon,
                        timezone=args.timezone or "auto")
    if not args.location:
        raise SystemExit("error: give a configured location, or --lat/--lon")
    return config.location(args.location)


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if is_dataclass(obj):
        return asdict(obj)
    return str(obj)


def write_out(text: str, path: str | None) -> None:
    if not path:
        print(text)
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    print(f"Wrote {target}", file=sys.stderr)


def cmd_forecast(args, config: Config) -> None:
    location = resolve_location(args, config)
    providers = build_providers(args.provider)
    forecasts = fetch_all(providers, location, args.days, args.units, args.strict)
    primary = forecasts[0]

    if args.format == "json":
        payload = {"location": asdict(location),
                   "forecasts": [f.to_dict() for f in forecasts]}
        write_out(json.dumps(payload, indent=2, default=_json_default), args.output)
        return

    context = {
        "location": location,
        "current": primary.current,
        "days": primary.days,
        "alerts": primary.alerts,
        "forecasts": forecasts,
        "units": units_for(primary),
        "generated_at": local_now(location),
        "attributions": sorted({p.attribution for p in providers if p.attribution}),
    }
    write_out(render(args.template, args.format, context), args.output)


def day_narrative(location, forecasts, target_date, days: int = 5):
    """Written forecast for one location on one day.

    A single point is a region of one: every spread collapses to a single
    value, so the writer quotes plain figures and names no places.
    """
    from . import narrative as narrative_mod
    from .region import summarise_region

    summary = summarise_region(location.name, location.timezone, [location],
                               {location.slug: forecasts}, days=days)
    day = next((d for d in summary.days if d.date == target_date), None)
    if day is None:
        return None, None
    return narrative_mod.write(summary, day), day


def cmd_event(args, config: Config) -> None:
    location = resolve_location(args, config)
    providers = build_providers(args.provider)

    try:
        event_time = resolve_event_time(args.when, location)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}")

    forecasts = fetch_all(providers, location, args.days, args.units, args.strict)
    event = build_event(location, event_time, forecasts,
                        event_name=args.name or "Event", window_hours=args.window)

    labels = source_labels(forecasts)
    blended = blend_hours({f.provider: f.hour_at(event_time) for f in forecasts}, labels)

    if not blended:
        raise SystemExit(
            f"error: no source has hourly data for {event_time:%Y-%m-%d %H:%M}. "
            "It may be beyond the forecast range."
        )

    # Build the surrounding window, blended hour by hour.
    window = []
    for offset in range(-args.window, args.window + 1):
        slot = event_time + timedelta(hours=offset)
        row = blend_hours({f.provider: f.hour_at(slot) for f in forecasts}, labels)
        if row:
            row.is_event = (offset == 0)
            row.slot = slot
            window.append(row)

    if args.format == "json":
        payload = {
            "event": {"name": event.event_name, "time": event_time.isoformat(),
                      "location": asdict(location)},
            "at_event": {k: {"value": v.value, "source": v.label}
                         for k, v in blended.fields.items()},
            "sources": labels,
            "alerts": event.alerts,
        }
        write_out(json.dumps(payload, indent=2, default=_json_default), args.output)
        return

    forecast_text, forecast_day = day_narrative(
        location, forecasts, event_time.date(), days=max(args.days, 2))

    context = {
        "event": event,
        "blended": blended,
        "window": window,
        "forecast_text": forecast_text,
        "forecast_day": forecast_day,
        "sources": {f: blended.source_of(f) for f in
                    ["temperature", "precip_chance", "cloud_cover",
                     "wind_speed", "wind_gust", "wind_direction"]
                    if blended.source_of(f)},
        "units": units_for(forecasts[0]),
        "attributions": sorted({p.attribution for p in providers if p.attribution}),
    }
    write_out(render(args.template, args.format, context), args.output)


def cmd_locations(args, config: Config) -> None:
    if not config.locations:
        print("No locations configured. Add some to config/locations.yml.")
        return
    width = max(len(k) for k in config.locations)
    for key, loc in sorted(config.locations.items()):
        region = f", {loc.region}" if loc.region else ""
        print(f"{key:<{width}}  {loc.name}{region}  ({loc.geocode})  {loc.timezone}")


def build_region_context(config: Config, key: str, provider: str, days: int,
                         units: str, strict: bool, narrative_days: int = 3) -> dict:
    """Fetch every member of a region and summarise it."""
    from . import narrative as narrative_mod
    from .region import summarise_region

    region = config.region(key)
    providers = build_providers(provider)

    by_member: dict[str, list] = {}
    for member in region.members:
        try:
            by_member[member.slug] = fetch_all(providers, member, days, units, strict)
        except SystemExit:
            print(f"warning: no forecast for {member.name}", file=sys.stderr)

    if not by_member:
        raise SystemExit(f"error: no member of {region.name} could be fetched")

    summary = summarise_region(region.name, region.timezone, region.members,
                               by_member, days=days)

    narratives, warnings, sources = [], [], set()
    for day in summary.days[:narrative_days]:
        text = narrative_mod.write(summary, day)
        narratives.append({"day": day, "narrative": text})
        warnings.extend(text.warnings)
        sources.add(text.source)

    any_forecast = next(iter(by_member.values()))[0]
    return {
        "summary": summary,
        "narratives": narratives,
        "units": units_for(any_forecast),
        "narrative_source": ("claude" if sources == {"claude"}
                             else "mixed" if "claude" in sources else "rule-based"),
        "warnings": sorted(set(warnings)),
        "attributions": sorted({p.attribution for p in providers if p.attribution}),
    }


def cmd_region(args, config: Config) -> None:
    context = build_region_context(config, args.region, args.provider, args.days,
                                   args.units, args.strict, args.narrative_days)
    if args.format == "json":
        summary = context["summary"]
        payload = {
            "region": summary.name,
            "members": summary.member_names,
            "generated_at": summary.generated_at.isoformat(),
            "days": [{
                "date": str(e["day"].date),
                "headline": e["narrative"].headline,
                "discussion": e["narrative"].discussion,
                "written_by": e["narrative"].source,
            } for e in context["narratives"]],
        }
        write_out(json.dumps(payload, indent=2, default=_json_default), args.output)
        return
    write_out(render(args.template, args.format, context), args.output)


def cmd_aviation(args, config: Config) -> None:
    from datetime import timezone as _tz
    from zoneinfo import ZoneInfo

    from .aviation.awc import fetch_metar, fetch_taf
    from .aviation.notams import fetch_notams
    from .aviation.risk import assess_factors, write_verdict
    from .aviation.runways import CYYT
    from .aviation.schedule import (ScheduleError, board_order,
                                fetch_schedule, live_sample)

    airport = CYYT   # only CYYT is modelled so far
    if args.airport.upper() not in (airport.icao, airport.iata):
        raise SystemExit(f"error: only {airport.icao} is configured so far")

    raw_taf, periods = fetch_taf(airport.icao)
    metar = fetch_metar(airport.icao)
    notams = fetch_notams(airport.icao)

    airport_now = datetime.now(ZoneInfo(airport.timezone))
    start = airport_now.replace(hour=args.start_hour, minute=0, second=0,
                              microsecond=0).astimezone(_tz.utc)
    try:
        flights = (live_sample(airport.latitude, airport.longitude)
                   if args.sample
                   else fetch_schedule(airport.icao, start, args.hours))
    except ScheduleError as exc:
        raise SystemExit(f"error: {exc}")

    if args.direction != "all" and not args.sample:
        flights = [f for f in flights if f.direction == args.direction]

    if not flights:
        raise SystemExit("error: no flights returned for that window")
    flights = board_order(flights, datetime.now(_tz.utc))

    assessments = [write_verdict(assess_factors(f, airport, periods, notams))
                   for f in flights]

    if args.format == "json":
        payload = [{
            "flight": a.flight.callsign or a.flight.number,
            "direction": a.flight.direction,
            "scheduled_utc": a.flight.scheduled.isoformat(),
            "aircraft": a.profile.name,
            "colour": a.colour, "reason": a.reason,
            "category": a.category, "runway": a.runway,
            "crosswind_kt": round(a.crosswind), "assessed_by": a.source,
        } for a in assessments]
        write_out(json.dumps(payload, indent=2, default=_json_default), args.output)
        return

    context = {
        "airport": airport,
        "assessments": assessments,
        "metar": metar,
        "raw_taf": raw_taf, "notams": notams,
        "periods": periods,
        "tz": ZoneInfo(airport.timezone),
        "generated_at": datetime.now(ZoneInfo(airport.timezone)),
        "sample_mode": args.sample,
        "direction": args.direction,
        # A file opened directly in a browser needs a doctype, or quirks
        # mode changes how it renders.
        "standalone": bool(args.output),
        "assessed_by": ("claude" if any(a.source == "claude" for a in assessments)
                        else "rule-based"),
    }
    write_out(render(args.template, args.format, context), args.output)


def cmd_site(args, config: Config) -> None:
    from .site import build_site, load_site_config

    site_config = load_site_config(args.site_config)
    built, failed = build_site(config, site_config, Path(args.outdir),
                               build_providers, fetch_all, units_for)

    for page in built:
        print(f"  built {page.href}", file=sys.stderr)
    for failure in failed:
        print(f"  SKIPPED {failure.name}: {failure.reason}", file=sys.stderr)
    print(f"{len(built)} page(s) -> {args.outdir}"
          + (f", {len(failed)} skipped" if failed else ""), file=sys.stderr)

    if failed and args.strict:
        raise SystemExit("error: --strict set and some pages failed")
    if not built:
        raise SystemExit("error: no pages were generated")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sheerr", description="Generate custom weather forecasts.")
    parser.add_argument("--config", help="Path to locations.yml")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, default_template):
        p.add_argument("location", nargs="?", help="Configured location key")
        p.add_argument("--lat", type=float, help="Latitude for an ad-hoc location")
        p.add_argument("--lon", type=float, help="Longitude for an ad-hoc location")
        p.add_argument("--name", help="Display name for an ad-hoc location / event")
        p.add_argument("--timezone", help="IANA timezone for an ad-hoc location")
        p.add_argument("--provider", default="both",
                       help="twc | ecmwf | open-meteo[:MODEL] | both | licensed | all")
        p.add_argument("--days", type=int, default=7)
        p.add_argument("--units", choices=["metric", "imperial"], default="metric")
        p.add_argument("--template", default=default_template)
        p.add_argument("--format", default="md", choices=["md", "html", "json"])
        p.add_argument("--output", "-o", help="Write to a file instead of stdout")
        p.add_argument("--strict", action="store_true",
                       help="Fail if any provider errors")

    f = sub.add_parser("forecast", help="Multi-day forecast")
    common(f, "default")
    f.set_defaults(func=cmd_forecast)

    e = sub.add_parser("event", help="Forecast for a specific time")
    common(e, "event")
    e.add_argument("--when", required=True,
                   help="'saturday 2pm' or an ISO timestamp")
    e.add_argument("--window", type=int, default=3,
                   help="Hours either side to include (default 3)")
    e.set_defaults(func=cmd_event)

    r = sub.add_parser("region", help="Summarised forecast for a group of locations")
    r.add_argument("region", help="Configured region key")
    r.add_argument("--provider", default="licensed")
    r.add_argument("--days", type=int, default=5)
    r.add_argument("--units", choices=["metric", "imperial"], default="metric")
    r.add_argument("--template", default="region")
    r.add_argument("--format", default="md", choices=["md", "html", "json"])
    r.add_argument("--narrative-days", type=int, default=3,
                   help="How many days get written discussion (default 3)")
    r.add_argument("--output", "-o")
    r.add_argument("--strict", action="store_true")
    r.set_defaults(func=cmd_region)

    a = sub.add_parser("aviation", help="Weather-delay risk for flights at an airport")
    a.add_argument("airport", nargs="?", default="CYYT")
    a.add_argument("--hours", type=int, default=48,
                   help="Schedule window in hours (default 48)")
    a.add_argument("--start-hour", type=int, default=5,
                   help="Local hour the board starts from (default 5)")
    a.add_argument("--sample", action="store_true",
                   help="Use live ADS-B traffic instead of a schedule (no key needed)")
    a.add_argument("--direction", default="all",
                   choices=["all", "arrival", "departure"],
                   help="Limit to arrivals or departures (default both)")
    a.add_argument("--template", default="aviation")
    a.add_argument("--format", default="md", choices=["md", "html", "json"])
    a.add_argument("--output", "-o")
    a.set_defaults(func=cmd_aviation)

    s = sub.add_parser("site", help="Build the static site for hosting")
    s.add_argument("--outdir", default="_site", help="Output directory")
    s.add_argument("--site-config", help="Path to site.yml")
    s.add_argument("--strict", action="store_true",
                   help="Fail if any page could not be generated")
    s.set_defaults(func=cmd_site)

    l = sub.add_parser("locations", help="List configured locations")
    l.set_defaults(func=cmd_locations)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = Config.load(args.config)
        args.func(args, config)
    except (ConfigError, ProviderError, RenderError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
