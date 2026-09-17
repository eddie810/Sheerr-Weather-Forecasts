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

    context = {
        "event": event,
        "blended": blended,
        "window": window,
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
