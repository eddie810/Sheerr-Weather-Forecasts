"""Event forecasts — conditions at a specific place and time.

A wedding, a shoot, a game: the question is not "what's the week like"
but "what will it be doing at 2 PM Saturday", plus enough of a window
either side to see the trend.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Forecast, Hour, Location


@dataclass
class ProviderReading:
    """One provider's answer for the event hour, plus its surrounding window."""

    provider: str
    label: str
    hour: Hour | None
    window: list[Hour]
    in_range: bool


@dataclass
class EventForecast:
    """Everything a template needs to describe conditions at event time."""

    location: Location
    event_name: str
    event_time: datetime
    window_hours: int
    readings: list[ProviderReading]
    forecasts: list[Forecast]
    generated_at: datetime

    @property
    def window_start(self) -> datetime:
        return self.event_time - timedelta(hours=self.window_hours)

    @property
    def window_end(self) -> datetime:
        return self.event_time + timedelta(hours=self.window_hours)

    @property
    def available(self) -> list[ProviderReading]:
        """Readings that actually reached the event time."""
        return [r for r in self.readings if r.hour is not None]

    def _values(self, attr: str) -> list[float]:
        vals = [getattr(r.hour, attr) for r in self.available]
        return [v for v in vals if v is not None]

    def consensus(self, attr: str) -> float | None:
        """Mean of the providers that reported `attr` at the event hour."""
        vals = self._values(attr)
        return sum(vals) / len(vals) if vals else None

    def spread(self, attr: str) -> float | None:
        """Max-minus-min across providers — how much they disagree."""
        vals = self._values(attr)
        return max(vals) - min(vals) if len(vals) > 1 else None

    def agreement(self, attr: str, threshold: float) -> bool | None:
        """Whether providers agree on `attr` within `threshold`."""
        s = self.spread(attr)
        return None if s is None else s <= threshold

    @property
    def alerts(self) -> list[dict]:
        """Active alerts from any provider that reports them."""
        seen, out = set(), []
        for f in self.forecasts:
            for a in f.alerts:
                key = a.get("headlineText") or a.get("eventDescription") or str(a)
                if key not in seen:
                    seen.add(key)
                    out.append(a)
        return out


def resolve_event_time(when: str, location: Location,
                       reference: datetime | None = None) -> datetime:
    """Turn a human time expression into a concrete local datetime.

    Accepts an ISO timestamp (`2026-09-19T14:00`) or a weekday-and-time
    phrase (`saturday 2pm`, `sat 14:00`), resolved in the location's own
    timezone and always forward-looking.
    """
    tz = _zone(location.timezone)
    now = reference or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)

    text = when.strip().lower()

    try:
        parsed = datetime.fromisoformat(when.strip())
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)
    except ValueError:
        pass

    parts = text.replace(",", " ").split()
    weekdays = ["monday", "tuesday", "wednesday", "thursday",
                "friday", "saturday", "sunday"]
    target_dow = None
    time_token = None

    for part in parts:
        match = next((i for i, d in enumerate(weekdays)
                      if d.startswith(part) and len(part) >= 3), None)
        if match is not None:
            target_dow = match
        elif part in ("today", "tonight"):
            target_dow = now.weekday()
        elif part == "tomorrow":
            target_dow = (now.weekday() + 1) % 7
        elif any(c.isdigit() for c in part):
            time_token = part

    hour, minute = _parse_time(time_token) if time_token else (12, 0)

    if target_dow is None:
        raise ValueError(
            f"Could not understand the time {when!r}. "
            "Try an ISO timestamp (2026-09-19T14:00) or 'saturday 2pm'."
        )

    ahead = (target_dow - now.weekday()) % 7
    candidate = (now + timedelta(days=ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    # "Saturday 2pm" on a Saturday afternoon means next Saturday.
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def _parse_time(token: str) -> tuple[int, int]:
    """Parse `2pm`, `14:00`, `2:30pm`, `1400`."""
    t = token.strip().lower()
    meridiem = None
    if t.endswith(("am", "pm")):
        meridiem, t = t[-2:], t[:-2].strip()

    if ":" in t:
        hh, _, mm = t.partition(":")
        hour, minute = int(hh), int(mm or 0)
    elif len(t) == 4 and t.isdigit():
        hour, minute = int(t[:2]), int(t[2:])
    else:
        hour, minute = int(t), 0

    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not 0 <= hour <= 23:
        raise ValueError(f"Hour out of range in {token!r}")
    return hour, minute


def _zone(name: str | None):
    if not name or name == "auto":
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo


def build_event(location: Location, event_time: datetime, forecasts: list[Forecast],
                event_name: str = "Event", window_hours: int = 3) -> EventForecast:
    """Assemble the per-provider readings for an event."""
    readings = []
    for f in forecasts:
        hour = f.hour_at(event_time)
        readings.append(ProviderReading(
            provider=f.provider,
            label=_label(f.provider),
            hour=hour,
            window=f.hours_between(
                event_time - timedelta(hours=window_hours),
                event_time + timedelta(hours=window_hours),
            ),
            in_range=hour is not None,
        ))

    return EventForecast(
        location=location,
        event_name=event_name,
        event_time=event_time,
        window_hours=window_hours,
        readings=readings,
        forecasts=forecasts,
        generated_at=datetime.now().astimezone(),
    )


def _label(provider: str) -> str:
    from .providers import PROVIDERS
    cls = PROVIDERS.get(provider)
    return cls.label if cls else provider
