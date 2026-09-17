"""Loading locations and defaults from `config/locations.yml`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Location

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "locations.yml"

BUILTIN_DEFAULTS: dict[str, Any] = {
    "units": "metric",
    "days": 7,
    "provider": "both",
    "template": "default",
}


class ConfigError(RuntimeError):
    """Raised when the config file is missing or malformed."""


class Region:
    """A named group of locations summarised as one forecast."""

    def __init__(self, key: str, name: str, members: list[Location],
                 timezone: str, region: str | None = None):
        self.key, self.name, self.members = key, name, members
        self.timezone, self.region = timezone, region


class Config:
    def __init__(self, defaults: dict[str, Any], locations: dict[str, Location],
                 regions: dict[str, "Region"] | None = None):
        self.defaults = {**BUILTIN_DEFAULTS, **(defaults or {})}
        self.locations = locations
        self.regions = regions or {}

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        path = Path(path) if path else DEFAULT_CONFIG
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")

        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Could not parse {path}: {exc}") from exc

        locations: dict[str, Location] = {}
        for key, entry in (raw.get("locations") or {}).items():
            if not isinstance(entry, dict):
                raise ConfigError(f"Location {key!r} must be a mapping")
            missing = {"name", "latitude", "longitude"} - set(entry)
            if missing:
                raise ConfigError(
                    f"Location {key!r} is missing: {', '.join(sorted(missing))}"
                )
            locations[key] = Location(
                name=entry["name"],
                latitude=float(entry["latitude"]),
                longitude=float(entry["longitude"]),
                timezone=entry.get("timezone", "auto"),
                region=str(entry["region"]) if entry.get("region") is not None else None,
                zone=entry.get("zone"),
                slug=key,
            )

        regions: dict[str, Region] = {}
        for key, entry in (raw.get("regions") or {}).items():
            members = []
            for slug in entry.get("members") or []:
                if slug not in locations:
                    raise ConfigError(
                        f"Region {key!r} lists unknown location {slug!r}"
                    )
                members.append(locations[slug])
            if not members:
                raise ConfigError(f"Region {key!r} has no members")
            regions[key] = Region(
                key=key, name=entry.get("name", key), members=members,
                timezone=entry.get("timezone") or members[0].timezone,
                region=str(entry["region"]) if entry.get("region") else None,
            )

        return cls(raw.get("defaults") or {}, locations, regions)

    def region(self, key: str) -> "Region":
        if key in self.regions:
            return self.regions[key]
        known = ", ".join(sorted(self.regions)) or "(none configured)"
        raise ConfigError(f"Unknown region {key!r}. Configured: {known}")

    def location(self, key: str) -> Location:
        if key in self.locations:
            return self.locations[key]
        known = ", ".join(sorted(self.locations)) or "(none configured)"
        raise ConfigError(f"Unknown location {key!r}. Configured: {known}")
