"""NOTAMs from NAV CANADA's flight planning service.

Free and Canadian-source. Matters here because the weather alone does not
decide whether an approach is available: if RVR equipment is unserviceable
you cannot use RVR-based minima, and a closed or contaminated runway
changes which runway is usable and what crosswind it will take.

Only the few NOTAM classes that bear on delay risk are extracted. Anything
not recognised is left alone rather than guessed at.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import requests

CFPS = "https://plan.navcanada.ca/weather/api/alpha/"

RVR_OUT = re.compile(r"\bRVR\s+(\d{2})\b.*?\bNOT\s+AVBL\b", re.S)
RWY_CLOSED = re.compile(r"\bRWY\s+(\d{2}[LRC]?)(?:/(\d{2}[LRC]?))?\s+CLSD\b")
#: Canadian Runway Friction Index, reported when a runway is contaminated.
CRFI = re.compile(r"\bCRFI\s+(?:RWY\s+(\d{2}[LRC]?)\s+)?\.?(\d\.\d{2}|\d{2})\b")
RSC = re.compile(r"\bRSC\b|\bSNOWTAM\b|\bCOMPACTED SNOW\b|\bICE PATCHES\b|\bSLUSH\b|\bWET SNOW\b")
ILS_OUT = re.compile(r"\bILS\s+(?:RWY\s+)?(\d{2}[LRC]?)\b.*?\b(?:U/S|NOT\s+AVBL|OTS)\b", re.S)


@dataclass
class AirportNotams:
    """The NOTAM signals that bear on delay risk."""

    raw: list[str] = field(default_factory=list)
    rvr_unserviceable: set[str] = field(default_factory=set)
    runways_closed: set[str] = field(default_factory=set)
    ils_unserviceable: set[str] = field(default_factory=set)
    crfi: dict[str, float] = field(default_factory=dict)
    contaminated: bool = False

    @property
    def significant(self) -> bool:
        return bool(self.rvr_unserviceable or self.runways_closed
                    or self.ils_unserviceable or self.crfi or self.contaminated)

    def summary(self) -> list[str]:
        """One short line per finding, for display."""
        lines = []
        if self.runways_closed:
            lines.append(f"Runway {', '.join(sorted(self.runways_closed))} closed")
        if self.rvr_unserviceable:
            lines.append("RVR reporting unserviceable on runway "
                         + ", ".join(sorted(self.rvr_unserviceable)))
        if self.ils_unserviceable:
            lines.append("ILS unserviceable on runway "
                         + ", ".join(sorted(self.ils_unserviceable)))
        for runway, value in sorted(self.crfi.items()):
            lines.append(f"CRFI {value:.2f} on runway {runway}" if runway
                         else f"CRFI {value:.2f} reported")
        if self.contaminated and not self.crfi:
            lines.append("Runway surface condition reported")
        return lines


def fetch_notams(icao: str) -> AirportNotams:
    """Read NOTAMs for an aerodrome and extract the operational signals."""
    result = AirportNotams()
    try:
        response = requests.get(CFPS, params={"site": icao, "alpha": "notam"},
                                timeout=40, headers={"User-Agent": "sheerr-weather/0.1"})
        if not response.ok:
            return result
        rows = response.json().get("data", [])
    except Exception:
        return result       # NOTAMs are enrichment; never fail the build on them

    for row in rows:
        text = row.get("text", "")
        if isinstance(text, str) and text.strip().startswith("{"):
            try:
                text = json.loads(text).get("raw", "")
            except ValueError:
                pass
        text = str(text).upper()
        result.raw.append(text)

        for match in RVR_OUT.finditer(text):
            result.rvr_unserviceable.add(match.group(1))
        for match in RWY_CLOSED.finditer(text):
            result.runways_closed.update(g for g in match.groups() if g)
        for match in ILS_OUT.finditer(text):
            result.ils_unserviceable.add(match.group(1))
        for match in CRFI.finditer(text):
            runway, value = match.group(1) or "", match.group(2)
            result.crfi[runway] = float(value) if "." in value else float(value) / 100
        if RSC.search(text):
            result.contaminated = True

    return result


#: Crosswind a contaminated runway will bear, as a fraction of the dry
#: limit, indexed by CRFI band. Canadian practice ties permissible crosswind
#: to the friction index; these are conservative planning factors for
#: estimating delay risk, not operating limits.
CRFI_CROSSWIND_FACTOR = [
    (0.20, 0.25), (0.30, 0.40), (0.40, 0.55),
    (0.50, 0.70), (0.60, 0.85), (1.00, 1.00),
]


def crosswind_factor(crfi: float | None) -> float:
    """How much of the dry crosswind limit a given CRFI leaves."""
    if crfi is None:
        return 1.0
    for limit, factor in CRFI_CROSSWIND_FACTOR:
        if crfi <= limit:
            return factor
    return 1.0
