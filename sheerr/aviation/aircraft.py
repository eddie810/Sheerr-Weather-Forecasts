"""Aircraft susceptibility to weather at the gate and on approach.

Crosswind limits below are the manufacturers' *demonstrated* crosswind
values in knots, which are commonly quoted but are not regulatory limits —
operators set their own, often lower, and a wet or contaminated runway
lowers them further. They are used here only to rank one airframe against
another, never as an operational figure.
"""

from __future__ import annotations

import re
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
    #: Commonly equipped and certified for CAT III ILS. Fit and certification
    #: vary by operator, so this ranks types, it does not describe a tail.
    cat3_capable: bool = False


def CAT3(profile: AircraftProfile) -> AircraftProfile:
    """Mark a type as commonly CAT III capable."""
    profile.cat3_capable = True
    return profile


PROFILES = {
    "DH8D": AircraftProfile("DH8D", "Dash 8-400", "turboprop", 32, 1.35, 1.2),
    "DH8C": AircraftProfile("DH8C", "Dash 8-300", "turboprop", 32, 1.4, 1.2),
    "AT72": AircraftProfile("AT72", "ATR 72", "turboprop", 35, 1.35, 1.2),
    "AT75": AircraftProfile("AT75", "ATR 72-500", "turboprop", 35, 1.35, 1.2),
    "B190": AircraftProfile("B190", "Beech 1900", "turboprop", 25, 1.6, 1.3),
    "SF34": AircraftProfile("SF34", "Saab 340", "turboprop", 30, 1.5, 1.3),
    "CRJ9": CAT3(AircraftProfile("CRJ9", "CRJ900", "regional jet", 32, 1.15, 1.0)),
    "CRJ2": AircraftProfile("CRJ2", "CRJ200", "regional jet", 30, 1.25, 1.0),
    "E175": AircraftProfile("E175", "Embraer 175", "regional jet", 38, 1.05, 1.0),
    "E190": CAT3(AircraftProfile("E190", "Embraer 190", "regional jet", 38, 1.05, 1.0)),
    "E195": CAT3(AircraftProfile("E195", "Embraer 195", "regional jet", 38, 1.0, 1.0)),
    "E290": CAT3(AircraftProfile("E290", "Embraer E190-E2", "regional jet", 38, 1.0, 1.0)),
    "E295": CAT3(AircraftProfile("E295", "Embraer E195-E2", "regional jet", 38, 1.0, 1.0)),
    "A319": CAT3(AircraftProfile("A319", "Airbus A319", "narrowbody", 38, 0.95, 0.9)),
    "A320": CAT3(AircraftProfile("A320", "Airbus A320", "narrowbody", 38, 0.95, 0.9)),
    "A321": CAT3(AircraftProfile("A321", "Airbus A321", "narrowbody", 38, 0.95, 0.9)),
    "A20N": CAT3(AircraftProfile("A20N", "Airbus A320neo", "narrowbody", 38, 0.95, 0.9)),
    "A21N": CAT3(AircraftProfile("A21N", "Airbus A321neo", "narrowbody", 38, 0.95, 0.9)),
    "B737": CAT3(AircraftProfile("B737", "Boeing 737", "narrowbody", 36, 0.95, 0.9)),
    "B738": CAT3(AircraftProfile("B738", "Boeing 737-800", "narrowbody", 36, 0.95, 0.9)),
    "B38M": CAT3(AircraftProfile("B38M", "Boeing 737 MAX 8", "narrowbody", 36, 0.95, 0.9)),
    "B763": CAT3(AircraftProfile("B763", "Boeing 767-300", "widebody", 35, 0.85, 0.8)),
    "A332": CAT3(AircraftProfile("A332", "Airbus A330-200", "widebody", 38, 0.85, 0.8)),
    "A333": CAT3(AircraftProfile("A333", "Airbus A330-300", "widebody", 38, 0.85, 0.8)),
    "B788": CAT3(AircraftProfile("B788", "Boeing 787-8", "widebody", 40, 0.8, 0.8)),
    "BCS1": CAT3(AircraftProfile("BCS1", "Airbus A220-100", "narrowbody", 35, 1.0, 0.95)),
    "BCS3": CAT3(AircraftProfile("BCS3", "Airbus A220-300", "narrowbody", 35, 1.0, 0.95)),
}

#: Schedule providers report a human-readable model ("Boeing 737-800"), while
#: ADS-B reports an ICAO type code ("B738"). Map the former onto the latter.
#: Ordered most specific first: a MAX 8 must not fall through to plain 737.
MODEL_PATTERNS: list[tuple[str, str]] = [
    (r"737.*max\s*8|737-8\s*max|\bb38m\b", "B38M"),
    (r"737-?800|737-8\b", "B738"),
    (r"\b737\b", "B737"),
    (r"a220-?300|\bbcs3\b|cs300", "BCS3"),
    (r"a220-?100|\bbcs1\b|cs100", "BCS1"),
    (r"a321.*neo|\ba21n\b", "A21N"),
    (r"a320.*neo|\ba20n\b", "A20N"),
    (r"\ba321\b", "A321"),
    (r"\ba320\b", "A320"),
    (r"\ba319\b", "A319"),
    (r"a330-?300|\ba333\b", "A333"),
    (r"a330-?200|\ba332\b", "A332"),
    (r"767-?300|\bb763\b", "B763"),
    (r"787-?8|\bb788\b", "B788"),
    (r"(dhc-?8|dash\s*8|q)-?400|\bdh8d\b", "DH8D"),
    (r"(dhc-?8|dash\s*8|q)-?300|\bdh8c\b", "DH8C"),
    (r"195[\s-]*e2|e195-?e2|\be295\b", "E295"),
    (r"190[\s-]*e2|e190-?e2|\be290\b", "E290"),
    (r"e-?195|embraer\s*195", "E195"),
    (r"e-?190|embraer\s*190", "E190"),
    (r"e-?175|embraer\s*175", "E175"),
    (r"crj.*900|\bcrj9\b", "CRJ9"),
    (r"crj.*200|\bcrj2\b", "CRJ2"),
    (r"atr.*72|\bat7[25]\b", "AT72"),
    (r"saab.*340|\bsf34\b", "SF34"),
    (r"beech.*1900|\bb190\b", "B190"),
]

#: Used when the type is unknown, deliberately mid-range rather than benign.
UNKNOWN = AircraftProfile("UNKN", "Unknown type", "unknown", 33, 1.1, 1.0)


def profile_for(type_or_model: str | None) -> AircraftProfile:
    """Look up a profile from an ICAO type code or a model name.

    ADS-B gives codes like "DH8D"; schedule providers give names like
    "De Havilland Canada DHC-8-400". Both must resolve, or every flight
    reads as an unknown type and the per-airframe assessment is pointless.
    """
    if not type_or_model:
        return UNKNOWN

    text = type_or_model.strip()
    exact = PROFILES.get(text.upper())
    if exact:
        return exact

    lowered = text.lower()
    for pattern, code in MODEL_PATTERNS:
        if re.search(pattern, lowered):
            return PROFILES[code]
    return UNKNOWN
