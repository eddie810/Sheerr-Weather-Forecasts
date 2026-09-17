"""Provider-neutral forecast model.

Every provider maps its own response shape into these dataclasses, so
templates can be written once and rendered from any source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date as Date, datetime
from typing import Any


@dataclass
class Location:
    """A named place a forecast can be generated for."""

    name: str
    latitude: float
    longitude: float
    timezone: str = "auto"
    region: str | None = None
    slug: str | None = None
    #: Local area a broadcaster would name instead of the point itself,
    #: e.g. "the Southern Shore" rather than "Witless Bay".
    zone: str | None = None

    def __post_init__(self) -> None:
        if not self.slug:
            cleaned = "".join(
                c if c.isalnum() else "-" for c in self.name.lower()
            )
            # Collapse runs of separators so slugs stay filename-friendly.
            self.slug = re.sub(r"-+", "-", cleaned).strip("-")

    @property
    def geocode(self) -> str:
        """`lat,lon` string, the format TWC expects."""
        return f"{self.latitude},{self.longitude}"


@dataclass
class Current:
    """Observed conditions right now."""

    temperature: float | None = None
    feels_like: float | None = None
    humidity: float | None = None
    wind_speed: float | None = None
    wind_direction: str | None = None
    pressure: float | None = None
    visibility: float | None = None
    uv_index: float | None = None
    phrase: str | None = None
    observed_at: datetime | None = None


@dataclass
class Hour:
    """A single forecast hour.

    This is what event forecasts ("what will it be like at 2 PM Saturday?")
    are built from, so it carries the full wind picture including gusts.
    """

    time: datetime
    temperature: float | None = None
    feels_like: float | None = None
    humidity: float | None = None
    precip_chance: float | None = None
    precip_amount: float | None = None
    precip_type: str | None = None
    cloud_cover: float | None = None
    wind_speed: float | None = None
    wind_gust: float | None = None
    wind_direction: str | None = None
    wind_degrees: float | None = None
    visibility: float | None = None
    uv_index: float | None = None
    phrase: str | None = None


@dataclass
class Daypart:
    """A named half-day slice (`Today`, `Tonight`, `Tomorrow`...).

    Open-Meteo has no equivalent concept, so this is populated by TWC only
    and templates should treat it as optional.
    """

    name: str
    is_daytime: bool
    temperature: float | None = None
    precip_chance: float | None = None
    precip_type: str | None = None
    wind_speed: float | None = None
    wind_direction: str | None = None
    wind_phrase: str | None = None
    humidity: float | None = None
    uv_index: float | None = None
    cloud_cover: float | None = None
    phrase: str | None = None
    narrative: str | None = None


@dataclass
class Day:
    """One calendar day of forecast."""

    date: Date
    day_of_week: str | None = None
    high: float | None = None
    low: float | None = None
    precip_chance: float | None = None
    precip_amount: float | None = None
    snow_amount: float | None = None
    wind_speed: float | None = None
    wind_direction: str | None = None
    humidity: float | None = None
    uv_index: float | None = None
    cloud_cover: float | None = None
    sunrise: datetime | None = None
    sunset: datetime | None = None
    phrase: str | None = None
    narrative: str | None = None
    dayparts: list[Daypart] = field(default_factory=list)

    @property
    def day(self) -> Daypart | None:
        """The daytime half of this day, when the provider supplies one."""
        return next((d for d in self.dayparts if d.is_daytime), None)

    @property
    def night(self) -> Daypart | None:
        """The overnight half of this day, when the provider supplies one."""
        return next((d for d in self.dayparts if not d.is_daytime), None)


@dataclass
class Forecast:
    """A complete forecast for one location from one provider."""

    location: Location
    provider: str
    issued_at: datetime
    units: str = "metric"
    current: Current | None = None
    days: list[Day] = field(default_factory=list)
    hours: list[Hour] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def today(self) -> Day | None:
        return self.days[0] if self.days else None

    def hour_at(self, when: datetime) -> Hour | None:
        """The forecast hour closest to `when`.

        Returns None when the target falls outside the provider's hourly
        range, rather than silently handing back a distant hour.
        """
        if not self.hours:
            return None

        target = when
        # Compare naive-to-naive or aware-to-aware; never mix the two.
        if target.tzinfo is None and self.hours[0].time.tzinfo is not None:
            target = target.replace(tzinfo=self.hours[0].time.tzinfo)
        elif target.tzinfo is not None and self.hours[0].time.tzinfo is None:
            target = target.replace(tzinfo=None)

        nearest = min(self.hours, key=lambda h: abs(h.time - target))
        if abs(nearest.time - target).total_seconds() > 3600 * 1.5:
            return None
        return nearest

    def hours_between(self, start: datetime, end: datetime) -> list[Hour]:
        """Every forecast hour falling within [start, end]."""
        if not self.hours:
            return []
        tz = self.hours[0].time.tzinfo
        if tz is not None:
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz)
            if end.tzinfo is None:
                end = end.replace(tzinfo=tz)
        else:
            start, end = start.replace(tzinfo=None), end.replace(tzinfo=None)
        return [h for h in self.hours if start <= h.time <= end]

    @property
    def temp_unit(self) -> str:
        return "°C" if self.units == "metric" else "°F"

    @property
    def speed_unit(self) -> str:
        return "km/h" if self.units == "metric" else "mph"

    @property
    def precip_unit(self) -> str:
        return "mm" if self.units == "metric" else "in"

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form, for `--format json`."""
        return asdict(self)


@dataclass
class ForecastBundle:
    """One or more provider forecasts for the same location.

    Single-provider runs carry exactly one entry; `--provider both` carries
    one per source so templates can show them side by side.
    """

    location: Location
    forecasts: list[Forecast]
    generated_at: datetime

    @property
    def primary(self) -> Forecast:
        """The forecast templates should lead with."""
        return self.forecasts[0]

    def by_provider(self, name: str) -> Forecast | None:
        return next((f for f in self.forecasts if f.provider == name), None)

    @property
    def providers(self) -> list[str]:
        return [f.provider for f in self.forecasts]
