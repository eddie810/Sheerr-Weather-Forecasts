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

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

ADB_HOST = "aerodatabox.p.rapidapi.com"
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
        url = (f"https://{ADB_HOST}/flights/airports/icao/{icao}/"
               f"{cursor:%Y-%m-%dT%H:%M}/{cursor + timedelta(hours=span):%Y-%m-%dT%H:%M}")
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
        flights += _parse(payload.get("departures") or [], "departure")
        flights += _parse(payload.get("arrivals") or [], "arrival")
        cursor += timedelta(hours=span)
        remaining -= span

    return sorted(flights, key=lambda f: f.scheduled)


def _parse(rows: list[dict], direction: str) -> list[Flight]:
    out = []
    for row in rows:
        movement = row.get("movement") or {}
        when = ((movement.get("scheduledTime") or {}).get("utc")
                or (movement.get("revisedTime") or {}).get("utc"))
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
            aircraft_type=aircraft.get("model"),
            registration=aircraft.get("reg"),
            status=row.get("status"),
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
