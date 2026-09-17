"""Regional forecasts.

A region is several point forecasts summarised as one. The useful content
of a regional forecast is not any single value but the spread: the range
across the area, which point holds each extreme, and when conditions peak.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date, datetime, timedelta
from typing import Any

from .blend import blend_hours, source_labels
from .models import Forecast, Location


@dataclass
class Extreme:
    """A value and the member location that holds it."""

    value: float
    where: str


@dataclass
class Spread:
    """The range of one field across a region."""

    low: Extreme
    high: Extreme

    @property
    def range(self) -> float:
        return self.high.value - self.low.value

    @property
    def uniform(self) -> bool:
        """Whether the region is close enough to quote a single value."""
        return self.range < max(2.0, abs(self.high.value) * 0.12)


@dataclass
class RegionDay:
    """One day summarised across every member of a region."""

    date: Date
    day_of_week: str
    high: Spread | None = None
    low: Spread | None = None
    gust: Spread | None = None
    wind_speed: Spread | None = None
    precip_chance: Spread | None = None
    cloud_cover: Spread | None = None
    dominant_direction: str | None = None
    direction_agreement: float = 0.0
    peak_gust_at: datetime | None = None
    peak_gust_where: str | None = None
    peak_window: tuple[datetime, datetime] | None = None


@dataclass
class RegionSummary:
    """A whole region, summarised."""

    name: str
    timezone: str
    members: list[Location]
    days: list[RegionDay]
    generated_at: datetime
    alerts: list[dict[str, Any]] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @property
    def member_names(self) -> list[str]:
        return [m.name for m in self.members]


def _spread(values: list[tuple[str, float]]) -> Spread | None:
    """Build a Spread from (location name, value) pairs."""
    clean = [(n, v) for n, v in values if v is not None]
    if not clean:
        return None
    lo = min(clean, key=lambda p: p[1])
    hi = max(clean, key=lambda p: p[1])
    return Spread(Extreme(lo[1], lo[0]), Extreme(hi[1], hi[0]))


def _dominant_direction(dirs: list[str]) -> tuple[str | None, float]:
    """Most common wind direction and the fraction of members agreeing.

    Compass bearings cannot be averaged, so this takes a mode over the
    16-point cardinals instead.
    """
    present = [d for d in dirs if d]
    if not present:
        return None, 0.0
    counts: dict[str, int] = {}
    for d in present:
        counts[d] = counts.get(d, 0) + 1
    best = max(counts, key=counts.get)
    return best, counts[best] / len(present)


def summarise_region(name: str, timezone: str, members: list[Location],
                     forecasts_by_member: dict[str, list[Forecast]],
                     days: int = 5, tz=None) -> RegionSummary:
    """Fold per-member forecasts into a regional summary."""
    from zoneinfo import ZoneInfo

    zone = tz or ZoneInfo(timezone)
    now = datetime.now(zone)

    # Blend each member's sources into one hourly series per member.
    blended: dict[str, list] = {}
    labels: dict[str, str] = {}
    alerts: list[dict] = []
    seen_alerts: set[str] = set()

    for member in members:
        fs = forecasts_by_member.get(member.slug) or []
        if not fs:
            continue
        labels.update(source_labels(fs))
        hours = []
        reference = max(fs, key=lambda f: len(f.hours))
        for hour in reference.hours:
            row = blend_hours({f.provider: f.hour_at(hour.time) for f in fs}, labels)
            if row:
                row.slot = hour.time
                hours.append(row)
        blended[member.name] = hours
        for f in fs:
            for a in f.alerts:
                key = a.get("headlineText") or a.get("eventDescription") or str(a)
                if key not in seen_alerts:
                    seen_alerts.add(key)
                    alerts.append(a)

    region_days: list[RegionDay] = []
    for offset in range(days):
        day = (now + timedelta(days=offset)).date()
        highs, lows, gusts, speeds, pops, clouds, dirs = [], [], [], [], [], [], []
        peak: tuple[float, datetime, str] | None = None

        for member_name, hours in blended.items():
            rows = [h for h in hours if h.slot.astimezone(zone).date() == day]
            if not rows:
                continue
            temps = [h.temperature for h in rows if h.temperature is not None]
            g = [(h.wind_gust, h.slot) for h in rows if h.wind_gust is not None]
            s = [h.wind_speed for h in rows if h.wind_speed is not None]
            p = [h.precip_chance for h in rows if h.precip_chance is not None]
            c = [h.cloud_cover for h in rows if h.cloud_cover is not None]

            if temps:
                highs.append((member_name, max(temps)))
                lows.append((member_name, min(temps)))
            if g:
                top = max(g, key=lambda x: x[0])
                gusts.append((member_name, top[0]))
                if peak is None or top[0] > peak[0]:
                    peak = (top[0], top[1], member_name)
                strongest = max(rows, key=lambda h: h.wind_gust or 0)
                dirs.append(strongest.wind_direction)
            if s:
                speeds.append((member_name, max(s)))
            if p:
                pops.append((member_name, max(p)))
            if c:
                clouds.append((member_name, sum(c) / len(c)))

        if not (highs or gusts):
            continue

        direction, agreement = _dominant_direction(dirs)
        window = None
        if peak:
            # Hours within 85% of the regional peak, to describe when it bites.
            hot = [h.slot for hours in blended.values() for h in hours
                   if h.slot.astimezone(zone).date() == day
                   and (h.wind_gust or 0) >= peak[0] * 0.85]
            if hot:
                window = (min(hot).astimezone(zone), max(hot).astimezone(zone))

        region_days.append(RegionDay(
            date=day,
            day_of_week=day.strftime("%A"),
            high=_spread(highs), low=_spread(lows),
            gust=_spread(gusts), wind_speed=_spread(speeds),
            precip_chance=_spread(pops), cloud_cover=_spread(clouds),
            dominant_direction=direction, direction_agreement=agreement,
            peak_gust_at=peak[1].astimezone(zone) if peak else None,
            peak_gust_where=peak[2] if peak else None,
            peak_window=window,
        ))

    return RegionSummary(
        name=name, timezone=timezone, members=members, days=region_days,
        generated_at=now, alerts=alerts, sources=labels,
        missing=[m.name for m in members if m.name not in blended],
    )
