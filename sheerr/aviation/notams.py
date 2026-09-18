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
import time
from dataclasses import dataclass, field

import requests

CFPS = "https://plan.navcanada.ca/weather/api/alpha/"

RVR_OUT = re.compile(r"\bRVR\s+(\d{2})\b.*?\bNOT\s+AVBL\b", re.S)
RWY_CLOSED = re.compile(r"\bRWY\s+(\d{2}[LRC]?)(?:/(\d{2}[LRC]?))?\s+CLSD\b")
#: Canadian Runway Friction Index, reported when a runway is contaminated.
CRFI = re.compile(r"\bCRFI\s+(?:RWY\s+(\d{2}[LRC]?)\s+)?\.?(\d\.\d{2}|\d{2})\b")
#: A runway surface condition report under GRF/TALPA:
#: "RSC 10 5/5/5 100 PCT WET, 100 PCT WET, 100 PCT WET."
#: The triple is the runway condition code for each third of the runway.
RSC_REPORT = re.compile(
    r"\bRSC\s+(\d{2}[LRC]?)\s+(\d)/(\d)/(\d)\s*([^.]*)")
#: A contaminant named without condition codes, which still deserves notice.
CONTAMINANT = re.compile(
    r"\bSNOWTAM\b|\bCOMPACTED SNOW\b|\bICE PATCHES\b|\bSLUSH\b"
    r"|\bWET SNOW\b|\bDRY SNOW\b|\bGLARE ICE\b|\bFROZEN RUTS\b")

#: ICAO runway condition codes. 6 is dry and 5 is good — a wet runway in
#: summer reports 5/5/5 and is not contaminated in any sense that delays a
#: flight. Braking only becomes a factor from 4 down.
RWYCC_MEANING = {
    6: "dry", 5: "good", 4: "good to medium", 3: "medium",
    2: "medium to poor", 1: "poor", 0: "less than poor",
}
#: At or below this code the surface is worth reporting as a delay factor.
RWYCC_SIGNIFICANT = 4
ILS_OUT = re.compile(r"\bILS\s+(?:RWY\s+)?(\d{2}[LRC]?)\b.*?\b(?:U/S|NOT\s+AVBL|OTS)\b", re.S)


@dataclass
class AirportNotams:
    """The NOTAM signals that bear on delay risk."""

    raw: list[str] = field(default_factory=list)
    rvr_unserviceable: set[str] = field(default_factory=set)
    runways_closed: set[str] = field(default_factory=set)
    ils_unserviceable: set[str] = field(default_factory=set)
    crfi: dict[str, float] = field(default_factory=dict)
    #: runway -> (worst condition code across its thirds, reported surface)
    surfaces: dict[str, tuple[int, str]] = field(default_factory=dict)
    #: A contaminant named in a NOTAM that carried no condition codes.
    contaminant_reported: bool = False

    @property
    def worst_code(self) -> int | None:
        """Lowest runway condition code reported anywhere on the field."""
        return min((c for c, _ in self.surfaces.values()), default=None)

    @property
    def contaminated(self) -> bool:
        """Is the surface degraded enough to bear on a delay?

        A wet runway is not. In St. John's it reports 5/5/5 for much of the
        year, and treating that as contamination put snow and ice on the
        board in September.
        """
        worst = self.worst_code
        return (worst is not None and worst <= RWYCC_SIGNIFICANT) or self.contaminant_reported

    @property
    def surface_description(self) -> str:
        """What is actually on the runway, in the NOTAM's own words."""
        worst = self.worst_code
        if worst is None:
            return "contaminant reported on the runway"
        for runway, (code, surface) in sorted(self.surfaces.items()):
            if code == worst:
                text = surface.strip().lower() or RWYCC_MEANING.get(code, "degraded")
                return f"runway {runway} {text} (braking {RWYCC_MEANING[code]})"
        return "degraded runway surface"

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
            lines.append("Runway surface: " + self.surface_description)
        return lines


def fetch_notams(icao: str) -> AirportNotams:
    """Read NOTAMs for an aerodrome and extract the operational signals."""
    result = AirportNotams()
    rows = []
    for attempt in range(3):
        try:
            response = requests.get(CFPS, params={"site": icao, "alpha": "notam"},
                                    timeout=40,
                                    headers={"User-Agent": "sheerr-weather/0.1"})
            if response.ok:
                rows = response.json().get("data", [])
                break
        except Exception:
            pass            # NOTAMs are enrichment; never fail the build on them
        if attempt < 2:
            time.sleep(2 ** attempt)
    if not rows:
        return result

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
        for match in RSC_REPORT.finditer(text):
            runway = match.group(1)
            codes = [int(match.group(i)) for i in (2, 3, 4)]
            # The thirds are reported separately; the worst one governs.
            worst = min(codes)
            surface = _first_surface(match.group(5))
            previous = result.surfaces.get(runway)
            if previous is None or worst < previous[0]:
                result.surfaces[runway] = (worst, surface)
        if CONTAMINANT.search(text):
            result.contaminant_reported = True

    return result


def _first_surface(text: str) -> str:
    """The surface wording from an RSC report, e.g. "100 PCT WET"."""
    parts = [p.strip() for p in (text or "").split(",") if p.strip()]
    return parts[0].lower() if parts else ""


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
