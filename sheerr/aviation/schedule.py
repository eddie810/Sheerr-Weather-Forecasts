"""Flight schedules for an airport.

AeroDataBox (via RapidAPI) publishes real forward schedules. Set
AERODATABOX_API_KEY. A free RapidAPI tier covers a few hundred calls a
month, which is ample for a twice-daily pull.

`live_sample` is a keyless stand-in that reads aircraft currently airborne
near the airport from adsb.lol. It is for demonstrating the pipeline
without a key, not a substitute for a schedule: it sees only what is flying
now, and cannot tell an arrival from an overflight.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ADB_HOST = "aerodatabox.p.rapidapi.com"

#: How long a fetched schedule chunk stays usable. Published schedules
#: barely move within a day, while the weather assessed against them changes
#: every hour — so the schedule is cached and the assessment is not. Without
#: this, hourly builds would exhaust a free API tier within a day.
SCHEDULE_TTL_SECONDS = int(os.environ.get("SHEERR_SCHEDULE_TTL", 12 * 3600))


def _cache_dir() -> Path:
    path = Path(os.environ.get("SHEERR_SCHEDULE_CACHE")
                or Path(tempfile.gettempdir()) / "sheerr-schedule-cache")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cached(key: str) -> dict | None:
    path = _cache_dir() / f"{key}.json"
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > SCHEDULE_TTL_SECONDS:
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None


def _store(key: str, payload: dict) -> None:
    try:
        (_cache_dir() / f"{key}.json").write_text(json.dumps(payload))
    except OSError:
        pass        # A cache miss is survivable; a failed build is not.
ADSB_URL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"


@dataclass
class Flight:
    """A scheduled movement."""

    callsign: str
    number: str
    airline: str | None
    direction: str               # "departure" | "arrival"
    scheduled: datetime
    other_airport: str | None    # the far end, IATA or ICAO
    other_name: str | None
    aircraft_type: str | None    # ICAO type code, e.g. DH8D
    registration: str | None
    status: str | None = None
    other_city: str | None = None    # city name, for "St. John's (YYT)"
    #: What the airline currently expects, as distinct from the schedule.
    revised: datetime | None = None

    @property
    def delay_minutes(self) -> int | None:
        """Minutes late against the published schedule, when known."""
        if not self.revised:
            return None
        return round((self.revised - self.scheduled).total_seconds() / 60)

    @property
    def cancelled(self) -> bool:
        return (self.status or "").strip().lower() in {"canceled", "cancelled"}

    @property
    def status_label(self) -> str:
        """What the airline says, in words a passenger reads on a board."""
        if self.cancelled:
            return "Cancelled"
        delay = self.delay_minutes
        if delay is not None and delay >= 15:
            hours, mins = divmod(delay, 60)
            late = f"{hours}h {mins:02d}m" if hours else f"{delay} min"
            return f"Delayed {late}"
        if delay is not None and delay <= -15:
            return "Early"
        raw = (self.status or "").strip().lower()
        return {"expected": "On time", "enroute": "En route", "en route": "En route",
                "arrived": "Landed", "departed": "Departed",
                "checkin": "On time", "boarding": "Boarding",
                "gateclosed": "Gate closed", "unknown": ""}.get(raw,
                (self.status or "").strip() or "On time")

    @property
    def status_state(self) -> str:
        """green / amber / red, for how the status is shown."""
        if self.cancelled:
            return "red"
        delay = self.delay_minutes
        if delay is not None and delay >= 60:
            return "red"
        if delay is not None and delay >= 15:
            return "amber"
        return "green"

    @property
    def other_label(self) -> str:
        """The far end as "City (CODE)", degrading to whichever part exists."""
        city, code = self.other_city, self.other_airport
        if city and code:
            return f"{city} ({code})"
        return city or code or "—"


class ScheduleError(RuntimeError):
    """Raised when a schedule cannot be retrieved."""


def fetch_schedule(icao: str, start: datetime, hours: int = 12,
                   api_key: str | None = None) -> list[Flight]:
    """Scheduled departures and arrivals in a window.

    AeroDataBox caps a single query at 12 hours, so longer windows are
    fetched in chunks.
    """
    key = api_key or os.environ.get("AERODATABOX_API_KEY") or os.environ.get("RAPIDAPI_KEY")
    if not key:
        raise ScheduleError(
            "AERODATABOX_API_KEY is not set. Get a free key at "
            "rapidapi.com/aedbx-aedbx/api/aerodatabox, or use --sample to "
            "demonstrate with live traffic instead."
        )

    flights: list[Flight] = []
    remaining, cursor = hours, start
    while remaining > 0:
        span = min(remaining, 12)
        window = f"{cursor:%Y-%m-%dT%H:%M}/{cursor + timedelta(hours=span):%Y-%m-%dT%H:%M}"
        key = hashlib.sha1(f"{icao}|{window}".encode()).hexdigest()[:16]

        payload = _cached(key)
        if payload is not None:
            flights += _parse(payload.get("departures") or [], "departure")
            flights += _parse(payload.get("arrivals") or [], "arrival")
            cursor += timedelta(hours=span)
            remaining -= span
            continue

        url = f"https://{ADB_HOST}/flights/airports/icao/{icao}/{window}"
        response = requests.get(
            url,
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": ADB_HOST},
            params={"withLeg": "false", "withCancelled": "true",
                    "withCodeshared": "false", "withLocation": "false"},
            timeout=45,
        )
        if response.status_code in (401, 403):
            raise ScheduleError("AeroDataBox rejected the key (HTTP "
                                f"{response.status_code}). Check the subscription.")
        if response.status_code == 429:
            raise ScheduleError("AeroDataBox quota exhausted (HTTP 429).")
        if not response.ok:
            raise ScheduleError(f"AeroDataBox: HTTP {response.status_code}: "
                                f"{response.text[:160]}")

        payload = response.json()
        _store(key, payload)
        flights += _parse(payload.get("departures") or [], "departure")
        flights += _parse(payload.get("arrivals") or [], "arrival")
        cursor += timedelta(hours=span)
        remaining -= span

    return sorted(flights, key=lambda f: f.scheduled)


def _parse(rows: list[dict], direction: str) -> list[Flight]:
    out = []
    for row in rows:
        movement = row.get("movement") or {}
        scheduled = (movement.get("scheduledTime") or {}).get("utc")
        revised = ((movement.get("revisedTime") or {}).get("utc")
                   or (movement.get("actualTime") or {}).get("utc"))
        when = scheduled or revised
        if not when:
            continue
        aircraft = row.get("aircraft") or {}
        airline = row.get("airline") or {}
        out.append(Flight(
            callsign=row.get("callSign") or row.get("number") or "",
            number=row.get("number") or "",
            airline=airline.get("name"),
            direction=direction,
            scheduled=_utc(when),
            other_airport=(movement.get("airport") or {}).get("iata"),
            other_name=(movement.get("airport") or {}).get("name"),
            # AeroDataBox names the city separately; fall back through the
            # short name to the full airport name when it is absent.
            other_city=((movement.get("airport") or {}).get("municipalityName")
                        or (movement.get("airport") or {}).get("shortName")
                        or (movement.get("airport") or {}).get("name")),
            aircraft_type=aircraft.get("model"),
            registration=aircraft.get("reg"),
            status=row.get("status"),
            revised=_utc(revised) if revised and scheduled else None,
        ))
    return out


def _utc(text: str) -> datetime:
    """AeroDataBox returns '2026-09-17 14:05Z'."""
    cleaned = text.replace("Z", "").strip().replace(" ", "T")
    return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)


def live_sample(latitude: float, longitude: float, distance_nm: int = 150,
                limit: int = 12) -> list[Flight]:
    """Aircraft airborne near the airport, as stand-in flights.

    Demonstrates the pipeline without a schedule key. Times are 'now', and
    an overflight is indistinguishable from an arrival, so this is never a
    real schedule.
    """
    response = requests.get(
        ADSB_URL.format(lat=latitude, lon=longitude, dist=distance_nm),
        timeout=45, headers={"User-Agent": "sheerr-weather/0.1"},
    )
    if not response.ok:
        raise ScheduleError(f"adsb.lol: HTTP {response.status_code}")

    now = datetime.now(timezone.utc)
    flights = []
    for aircraft in (response.json().get("ac") or [])[:limit]:
        callsign = (aircraft.get("flight") or "").strip()
        if not callsign:
            continue
        flights.append(Flight(
            callsign=callsign, number=callsign, airline=None,
            direction="arrival", scheduled=now,
            other_airport=None, other_name=None,
            aircraft_type=aircraft.get("t"),
            registration=aircraft.get("r"),
            status="live ADS-B",
        ))
    return flights
