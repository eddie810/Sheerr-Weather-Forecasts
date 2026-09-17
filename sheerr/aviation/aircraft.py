"""Aircraft susceptibility to weather at the gate and on approach.

Crosswind limits below are the manufacturers' *demonstrated* crosswind
values in knots, which are commonly quoted but are not regulatory limits —
operators set their own, often lower, and a wet or contaminated runway
lowers them further. They are used here only to rank one airframe against
another, never as an operational figure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AircraftProfile:
    """How a type tends to fare in the weather that delays flights."""

    code: str
    name: str
    category: str               # turboprop | regional jet | narrowbody | widebody
    crosswind_kt: int           # demonstrated crosswind
    #: Turboprops and smaller regional types are more exposed to gusty wind
    #: and to ground-icing turnarounds than heavier jets.
    wind_sensitivity: float     # 1.0 = baseline; higher is more affected
    deice_burden: float         # relative time cost of a de-icing cycle


PROFILES = {
    "DH8D": AircraftProfile("DH8D", "Dash 8-400", "turboprop", 32, 1.35, 1.2),
    "DH8C": AircraftProfile("DH8C", "Dash 8-300", "turboprop", 32, 1.4, 1.2),
    "AT72": AircraftProfile("AT72", "ATR 72", "turboprop", 35, 1.35, 1.2),
    "AT75": AircraftProfile("AT75", "ATR 72-500", "turboprop", 35, 1.35, 1.2),
    "B190": AircraftProfile("B190", "Beech 1900", "turboprop", 25, 1.6, 1.3),
    "SF34": AircraftProfile("SF34", "Saab 340", "turboprop", 30, 1.5, 1.3),
    "CRJ9": AircraftProfile("CRJ9", "CRJ900", "regional jet", 32, 1.15, 1.0),
    "CRJ2": AircraftProfile("CRJ2", "CRJ200", "regional jet", 30, 1.25, 1.0),
    "E175": AircraftProfile("E175", "Embraer 175", "regional jet", 38, 1.05, 1.0),
    "E190": AircraftProfile("E190", "Embraer 190", "regional jet", 38, 1.05, 1.0),
    "E195": AircraftProfile("E195", "Embraer 195", "regional jet", 38, 1.0, 1.0),
    "E290": AircraftProfile("E290", "Embraer E190-E2", "regional jet", 38, 1.0, 1.0),
    "E295": AircraftProfile("E295", "Embraer E195-E2", "regional jet", 38, 1.0, 1.0),
    "A319": AircraftProfile("A319", "Airbus A319", "narrowbody", 38, 0.95, 0.9),
    "A320": AircraftProfile("A320", "Airbus A320", "narrowbody", 38, 0.95, 0.9),
    "A321": AircraftProfile("A321", "Airbus A321", "narrowbody", 38, 0.95, 0.9),
    "A20N": AircraftProfile("A20N", "Airbus A320neo", "narrowbody", 38, 0.95, 0.9),
    "A21N": AircraftProfile("A21N", "Airbus A321neo", "narrowbody", 38, 0.95, 0.9),
    "B737": AircraftProfile("B737", "Boeing 737", "narrowbody", 36, 0.95, 0.9),
    "B738": AircraftProfile("B738", "Boeing 737-800", "narrowbody", 36, 0.95, 0.9),
    "B38M": AircraftProfile("B38M", "Boeing 737 MAX 8", "narrowbody", 36, 0.95, 0.9),
    "B763": AircraftProfile("B763", "Boeing 767-300", "widebody", 35, 0.85, 0.8),
    "A332": AircraftProfile("A332", "Airbus A330-200", "widebody", 38, 0.85, 0.8),
    "A333": AircraftProfile("A333", "Airbus A330-300", "widebody", 38, 0.85, 0.8),
    "B788": AircraftProfile("B788", "Boeing 787-8", "widebody", 40, 0.8, 0.8),
}

#: Used when the type is unknown, deliberately mid-range rather than benign.
UNKNOWN = AircraftProfile("UNKN", "Unknown type", "unknown", 33, 1.1, 1.0)


def profile_for(type_code: str | None) -> AircraftProfile:
    """Look up a profile by ICAO type code, falling back to a neutral one."""
    if not type_code:
        return UNKNOWN
    return PROFILES.get(type_code.strip().upper(), UNKNOWN)
