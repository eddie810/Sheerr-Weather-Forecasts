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


class Config:
    def __init__(self, defaults: dict[str, Any], locations: dict[str, Location]):
        self.defaults = {**BUILTIN_DEFAULTS, **(defaults or {})}
        self.locations = locations

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
                slug=key,
            )

        return cls(raw.get("defaults") or {}, locations)

    def location(self, key: str) -> Location:
        if key in self.locations:
            return self.locations[key]
        known = ", ".join(sorted(self.locations)) or "(none configured)"
        raise ConfigError(f"Unknown location {key!r}. Configured: {known}")
