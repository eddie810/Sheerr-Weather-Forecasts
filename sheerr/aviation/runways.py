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
        Runway("16", 142, 7005), Runway("34", 322, 7005),
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
