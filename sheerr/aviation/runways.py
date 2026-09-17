"""Runway geometry and wind components.

Crosswind is the main wind-driven cause of delays and diversions, and it
depends on the angle between the wind and the runway in use. Headings here
are degrees TRUE, which is what METAR and TAF wind directions are referenced
to. (Tower and ATIS report magnetic; do not mix the two.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Runway:
    ident: str
    heading_true: float
    length_ft: int
    closed: bool = False
    #: Whether a precision approach serves this end. Used only to pick a
    #: generic minima benchmark, never as a substitute for the charted
    #: procedure.
    precision_approach: bool = False


#: Landing minima expressed as runway visual range in feet, which is what
#: the approach ban is actually assessed against.
#:
#:   600 ft RVR  — aircraft equipped and certified for CAT III ILS
#:  1200 ft RVR  — everything else
#:
#: Certification is per operator and per airframe fit, so the capability
#: flag on each aircraft profile is "commonly equipped", not a statement
#: about any particular aeroplane. Only current official data is
#: authoritative; this estimates diversion risk, nothing more.
CAT3_MINIMA_RVR = 600
STANDARD_MINIMA_RVR = 1200

#: Statute miles to RVR feet, the conversion used operationally.
#: Between table points the value is interpolated.
SM_TO_RVR = [
    (0.125, 600), (0.25, 1200), (0.375, 1600), (0.5, 2400),
    (0.625, 3200), (0.75, 4000), (1.0, 5000), (1.25, 6000), (1.5, 6000),
]


@dataclass
class Airport:
    icao: str
    iata: str
    name: str
    latitude: float
    longitude: float
    elevation_ft: int
    timezone: str
    runways: list[Runway]

    @property
    def usable(self) -> list[Runway]:
        return [r for r in self.runways if not r.closed]


#: St. John's International. Runway data from OurAirports; 02/20 is closed.
CYYT = Airport(
    icao="CYYT", iata="YYT", name="St. John's International",
    latitude=47.627, longitude=-52.748, elevation_ft=128,
    timezone="America/St_Johns",
    runways=[
        Runway("10", 86, 8502), Runway("28", 266, 8502),
        Runway("16", 142, 7005, precision_approach=True),
        Runway("34", 322, 7005),
        Runway("02", 356, 5028, closed=True),
        Runway("20", 176, 5028, closed=True),
    ],
)


def wind_components(wind_dir: float, wind_speed: float,
                    runway_heading: float) -> tuple[float, float]:
    """Headwind and crosswind components for one runway, in the wind's units.

    Positive headwind means wind down the runway; negative is a tailwind.
    Crosswind is returned unsigned, since the limit applies either way.
    """
    angle = math.radians(wind_dir - runway_heading)
    return wind_speed * math.cos(angle), abs(wind_speed * math.sin(angle))


def best_runway(airport: Airport, wind_dir: float | None,
                wind_speed: float | None) -> tuple[Runway | None, float, float]:
    """The runway a crew would most likely use, and its wind components.

    Picks the lowest crosswind, breaking ties toward a headwind — which is
    how a runway actually gets chosen when the wind is light.
    """
    if wind_dir is None or wind_speed is None or not airport.usable:
        return None, 0.0, 0.0

    scored = []
    for runway in airport.usable:
        head, cross = wind_components(wind_dir, wind_speed, runway.heading_true)
        # Penalise a tailwind: it is limiting long before crosswind is.
        scored.append((cross, -head, runway, head))

    cross, _, runway, head = min(scored, key=lambda s: (round(s[0], 1), s[1]))
    return runway, head, cross


def visibility_to_rvr(statute_miles: float | None) -> int | None:
    """Convert a TAF visibility in statute miles to RVR in feet."""
    if statute_miles is None:
        return None
    if statute_miles >= SM_TO_RVR[-1][0]:
        return SM_TO_RVR[-1][1]
    if statute_miles <= SM_TO_RVR[0][0]:
        return SM_TO_RVR[0][1]
    for (lo_sm, lo_rvr), (hi_sm, hi_rvr) in zip(SM_TO_RVR, SM_TO_RVR[1:]):
        if lo_sm <= statute_miles <= hi_sm:
            span = hi_sm - lo_sm
            frac = 0 if span == 0 else (statute_miles - lo_sm) / span
            return round(lo_rvr + (hi_rvr - lo_rvr) * frac)
    return SM_TO_RVR[-1][1]


def approach_minima_rvr(cat3_capable: bool) -> int:
    """Landing minima in feet of RVR for an aircraft's capability."""
    return CAT3_MINIMA_RVR if cat3_capable else STANDARD_MINIMA_RVR
