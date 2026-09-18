"""Weather-delay risk for a flight.

NOT AN OPERATIONAL PRODUCT. This estimates the chance that weather disrupts
a flight's schedule. It says nothing about whether a flight is safe or
legal to operate — that is the crew's and the operator's decision, made
against their own limits and current official data.

The objective factors are computed here rather than left to the model:
crosswind against the type's demonstrated limit, flight category from
ceiling and visibility, freezing and frozen precipitation, and gust spread.
The model then weighs them and writes the reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .aircraft import AircraftProfile, profile_for
from .awc import TafPeriod, periods_covering
from .runways import (Airport, approach_minima_rvr, best_runway,
                      visibility_to_rvr)
from .notams import AirportNotams, crosswind_factor
from .schedule import Flight

#: Bands the colour code maps to.
GREEN, YELLOW, ORANGE = "green", "yellow", "orange"

#: Flight categories in words. The codes are precise but meaningless to
#: anyone outside aviation, and this board is read by passengers too.
CATEGORY_PLAIN = {
    "VFR": "Clear",
    "MVFR": "Some cloud",
    "IFR": "Low cloud",
    "LIFR": "Fog or very low cloud",
}

#: Outlooks in words a passenger would use.
OUTLOOK_PLAIN = {
    "Straightforward approach": "Normal landing",
    "Instrument approach": "Cloudy landing",
    "Near minima": "Borderline to land",
    "Below minima": "May divert",
    "Normal turnaround": "Normal",
    "De-icing expected": "De-icing needed",
    "De-icing, holdover critical": "De-icing delays likely",
    "Wind-limited departure": "Strong winds",
    "Contaminated runway": "Slippery runway",
    "Beyond forecast": "Too far ahead to say",
}

#: Knots are the aviation unit; km/h is the one most readers think in.
def kmh(knots: float | None) -> float | None:
    return None if knots is None else knots * 1.852

#: Present-weather codes that drive winter delays at a Canadian airport.
FREEZING = re.compile(r"\b(FZRA|FZDZ|FZFG)\b")
FROZEN = re.compile(r"\b(\+?SN|SG|PL|GS|GR|IC|-SN|SHSN|BLSN|DRSN)\b")
OBSCURING = re.compile(r"\b(FG|BR|HZ|FU)\b")
CONVECTIVE = re.compile(r"\b(TS|TSRA|VCTS|SQ)\b")


@dataclass
class Factor:
    """One contributor to the assessment.

    `detail` is written for a passenger; `technical` keeps the aviation
    figures for anyone who wants them. The board shows one or the other.
    """

    name: str
    detail: str
    weight: float       # 0-1, how strongly it pushes toward disruption
    technical: str = ""

    def text(self, advanced: bool = False) -> str:
        return (self.technical or self.detail) if advanced else self.detail


@dataclass
class Assessment:
    """The verdict for one flight."""

    flight: Flight
    profile: AircraftProfile
    period: TafPeriod | None
    runway: str | None
    headwind: float
    crosswind: float
    crosswind_ratio: float          # crosswind as a fraction of the type's limit
    category: str
    #: Whether the TAF actually reaches the scheduled time.
    covered_by_taf: bool = True
    #: Direction-specific outlook: approach for arrivals, ground for departures.
    outlook: str = ""
    factors: list[Factor] = field(default_factory=list)
    colour: str = GREEN
    reason: str = ""
    reason_technical: str = ""
    source: str = "rule-based"

    @property
    def plain_category(self) -> str:
        return CATEGORY_PLAIN.get(self.category, self.category)

    @property
    def plain_outlook(self) -> str:
        """The outlook without the aviation vocabulary."""
        return OUTLOOK_PLAIN.get(self.outlook, self.outlook)

    @property
    def score(self) -> float:
        """Highest single factor, nudged by how many others are present.

        A flight is disrupted by its worst problem, not by the average of
        its problems — but several at once compound.
        """
        if not self.factors:
            return 0.0
        peak = max(f.weight for f in self.factors)
        others = sum(f.weight for f in self.factors) - peak
        return min(1.0, peak + others * 0.25)


def assess_factors(flight: Flight, airport: Airport, periods: list[TafPeriod],
                   notams: AirportNotams | None = None) -> Assessment:
    """Compute the objective part of the assessment."""
    profile = profile_for(flight.aircraft_type)
    covering, covered = periods_covering(periods, flight.scheduled)
    prevailing = covering[0] if covering else None

    wind_dir = wind_speed = gust = None
    for period in covering:                  # transient groups may omit wind
        wind_dir = wind_dir if wind_dir is not None else period.wind_dir
        wind_speed = wind_speed if wind_speed is not None else period.wind_speed
        gust = gust if gust is not None else period.wind_gust

    peak_wind = max(w for w in (wind_speed or 0, gust or 0)) or None
    usable = airport
    if notams and notams.runways_closed:
        from dataclasses import replace as _replace
        usable = _replace(airport, runways=[r for r in airport.runways
                                            if r.ident not in notams.runways_closed])
    runway, headwind, crosswind = best_runway(usable, wind_dir, peak_wind)
    crfi = None
    if notams and notams.crfi:
        crfi = min(notams.crfi.values())
    factor = crosswind_factor(crfi)
    effective_limit = profile.crosswind_kt * factor
    ratio = crosswind / effective_limit if effective_limit else 0.0

    factors: list[Factor] = []

    if ratio >= 0.55:
        factors.append(Factor(
            "crosswind",
            f"Strong sidewind across the runway — about {kmh(crosswind):.0f} km/h "
            f"({crosswind:.0f} kt), which is {ratio:.0%} of what a {profile.name} "
            + ("normally handles on a slippery runway"
               if crfi is not None else "normally handles"),
            min(1.0, (ratio - 0.35) * 1.6) * profile.wind_sensitivity,
            technical=(
                f"{crosswind:.0f} kt crosswind on runway "
                f"{runway.ident if runway else '?'}, {ratio:.0%} of the "
                f"{profile.name}'s "
                + (f"{effective_limit:.0f} kt contaminated limit "
                   f"(CRFI {crfi:.2f} of {profile.crosswind_kt} kt dry)"
                   if crfi is not None
                   else f"{profile.crosswind_kt} kt demonstrated crosswind")),
        ))

    if gust and wind_speed and gust - wind_speed >= 15:
        factors.append(Factor(
            "gusts",
            f"Gusty — wind jumping to about {kmh(gust):.0f} km/h from "
            f"{kmh(wind_speed):.0f} km/h, which makes landing and takeoff bumpier",
            min(0.7, (gust - wind_speed) / 40) * profile.wind_sensitivity,
            technical=f"{wind_speed:.0f}G{gust:.0f} kt, {gust - wind_speed:.0f} kt spread",
        ))

    # Worst category across every group in effect, transient ones included.
    category = "VFR"
    for period in covering:
        order = ["VFR", "MVFR", "IFR", "LIFR"]
        if order.index(period.category) > order.index(category):
            category = period.category
    weights = {"VFR": 0.0, "MVFR": 0.3, "IFR": 0.6, "LIFR": 0.85}
    if weights[category] > 0:
        worst = next((p for p in covering if p.category == category), None)
        detail = CATEGORY_PLAIN.get(category, category)
        if worst:
            bits = []
            if worst.ceiling is not None:
                bits.append(f"cloud down to {worst.ceiling:,} ft")
            if worst.visibility is not None:
                bits.append(f"visibility about {worst.visibility:g} mile"
                            + ("s" if worst.visibility != 1 else ""))
            if bits:
                detail += " — " + " and ".join(bits)
            if worst.transient:
                detail += ", though only for part of the time"
        tech = category
        if worst:
            if worst.ceiling is not None:
                tech += f", ceiling {worst.ceiling} ft"
            if worst.visibility is not None:
                tech += f", visibility {worst.visibility:g} sm"
            if worst.transient:
                tech += f" ({worst.change or 'TEMPO'} group)"
        factors.append(Factor(
            "ceiling and visibility", detail,
            weights[category] * (0.75 if worst and worst.transient else 1.0),
            technical=tech))

    # Arrivals and departures fail for different reasons. An arrival is
    # limited by whether it can complete the approach; a departure by
    # whether it can be de-iced and get airborne on a contaminated surface.
    arriving = flight.direction == "arrival"
    if arriving:
        minima_rvr = approach_minima_rvr(profile.cat3_capable)
        visibility = min((p.visibility for p in covering
                          if p.visibility is not None), default=None)
        forecast_rvr = visibility_to_rvr(visibility)
        worst = next((p for p in covering
                      if p.visibility is not None and p.visibility == visibility), None)
        capability = ("CAT III" if profile.cat3_capable else "non-CAT III")
        rvr_out = bool(notams and runway and runway.ident in notams.rvr_unserviceable)
        if rvr_out:
            factors.append(Factor(
                "RVR reporting unserviceable",
                f"The visibility sensors on runway {runway.ident} are out of service, "
                "so aircraft need clearer conditions than usual before they can land",
                0.5,
                technical=f"RVR {runway.ident} unserviceable per NOTAM"))

        if forecast_rvr is not None:
            if forecast_rvr < minima_rvr:
                factors.append(Factor(
                    "below landing minima",
                    f"Too poor to land — visibility of about {visibility:g} mile"
                    + ("s" if visibility != 1 else "")
                    + f" is below what a {profile.name} needs, so this flight may "
                    "circle and wait or divert to another airport",
                    0.9 if not (worst and worst.transient) else 0.65,
                    technical=(f"{visibility:g} sm is about {forecast_rvr} ft RVR, "
                               f"below the {minima_rvr} ft {capability} minimum")))
            elif forecast_rvr < minima_rvr * 2:
                factors.append(Factor(
                    "close to landing minima",
                    f"Borderline for landing — visibility of about {visibility:g} mile"
                    + ("s" if visibility != 1 else "")
                    + f" is close to the limit for a {profile.name}",
                    0.45,
                    technical=(f"{visibility:g} sm is about {forecast_rvr} ft RVR "
                               f"against a {minima_rvr} ft {capability} minimum")))

    weather = " ".join(p.weather for p in covering if p.weather)
    if notams and notams.contaminated and not FREEZING.search(weather):
        # Say what the NOTAM says. Calling a wet September runway "snow or
        # ice" was wrong twice over: the surface was good, and the words
        # were invented rather than read.
        factors.append(Factor(
            "runway contamination",
            f"Reduced braking — {notams.surface_description}", 0.45,
            technical="RSC " + "; ".join(
                f"{rwy} RwyCC {code} {surface}".strip()
                for rwy, (code, surface) in sorted(notams.surfaces.items()))
            or None))

    if FREEZING.search(weather):
        factors.append(Factor(
            "freezing precipitation",
            "Freezing rain or drizzle — "
            + ("the runway will be slippery" if arriving
               else "aircraft must be sprayed with de-icing fluid before takeoff, "
                    "and there is a time limit on how long it lasts"),
            (0.75 if arriving else 0.9) * profile.deice_burden))
    elif FROZEN.search(weather):
        factors.append(Factor(
            "snow",
            "Snow — "
            + ("the runway needs clearing and will be slippery" if arriving
               else "aircraft need de-icing and the runway needs clearing"),
            (0.5 if arriving else 0.6) * profile.deice_burden))
    if CONVECTIVE.search(weather):
        factors.append(Factor("thunderstorms",
                              "Thunderstorms, which stop ground handling and "
                              "can close the airspace around the airport", 0.7))

    assessment = Assessment(
        flight=flight, profile=profile, period=prevailing, covered_by_taf=covered,
        runway=runway.ident if runway else None,
        headwind=headwind, crosswind=crosswind, crosswind_ratio=ratio,
        category=category, factors=factors,
    )
    if not covered:
        factors.append(Factor(
            "outside the forecast window",
            "This flight is further ahead than the airport forecast reaches, "
            "so the assessment is a rough guide only",
            0.3))

    assessment.outlook = _outlook(assessment, arriving, weather)
    assessment.colour, assessment.reason = _rule_verdict(assessment)
    return assessment


#: Direction-specific outlook labels. An arrival's question is whether it can
#: get in; a departure's is whether it can get out on time.
def _outlook(a: Assessment, arriving: bool, weather: str) -> str:
    if not a.covered_by_taf:
        return "Beyond forecast"
    names = {f.name for f in a.factors}
    if arriving:
        if "below landing minima" in names:
            return "Below minima"
        if "close to landing minima" in names:
            return "Near minima"
        if a.category in ("IFR", "LIFR"):
            return "Instrument approach"
        return "Straightforward approach"
    if "runway contamination" in names:
        return "Contaminated runway"
    if FREEZING.search(weather):
        return "De-icing, holdover critical"
    if FROZEN.search(weather):
        return "De-icing expected"
    if "crosswind" in names or "gusts" in names:
        return "Wind-limited departure"
    return "Normal turnaround"


def _rule_verdict(a: Assessment) -> tuple[str, str]:
    """Deterministic colour and one-line reason."""
    score = a.score
    colour = ORANGE if score >= 0.6 else YELLOW if score >= 0.28 else GREEN
    if not a.factors:
        a.reason_technical = "No significant weather in the forecast period."
        return colour, "Nothing in the forecast that should affect this flight."
    lead = max(a.factors, key=lambda f: f.weight)
    label = lead.name[0].upper() + lead.name[1:]
    a.reason_technical = f"{label}: {lead.technical or lead.detail}"
    return colour, lead.detail


SYSTEM = """You assess weather-related delay risk for flights at a Canadian \
airport, for Sheerr Weather.

You are given a flight, its aircraft type, the terminal forecast in effect
at its scheduled time, and pre-computed objective factors. Weigh those
factors and return a colour and one short sentence.

green   Weather is unlikely to affect the schedule.
yellow  Weather could plausibly delay this flight.
orange  Weather is likely to delay this flight, or force de-icing, holding,
        or a diversion.

Rules:
- Use ONLY the figures given. Never invent a number.
- Judge the aircraft against its own limits: the same crosswind is far more
  limiting for a Beech 1900 than for an A330.
- A TEMPO or PROB group is a possibility, not the prevailing condition.
  Weigh it, do not treat it as certain.
- Arrivals and departures fail differently. An arrival is limited by
  whether it can complete the approach: landing minima are assessed against
  runway visual range, 600 ft RVR for an aircraft equipped and certified for
  CAT III ILS and 1200 ft for everything else, and the downside is holding
  or a diversion. A departure is limited by de-icing, holdover time and
  runway state, so freezing precipitation and snow dominate.
- Never state or imply that a flight is unsafe, cannot operate, or should
  be cancelled. You assess schedule risk only. Crews and operators decide
  what flies, against their own limits and current official data.
- The reason is one sentence, plain, naming the dominant factor."""


def write_verdict(assessment: Assessment, api_key: str | None = None,
                  model: str = "claude-opus-5") -> Assessment:
    """Have Claude weigh the factors, falling back to the rule verdict."""
    from ..narrative import find_api_key, validate

    key = api_key
    if not key:
        key, _ = find_api_key()
    if not key or not assessment.factors:
        return assessment

    flight = assessment.flight
    brief = [
        f"Flight: {flight.callsign or flight.number} ({flight.direction})",
        f"Aircraft: {assessment.profile.name} ({assessment.profile.category}), "
        f"demonstrated crosswind {assessment.profile.crosswind_kt} kt",
        f"Scheduled: {flight.scheduled:%Y-%m-%d %H:%M} UTC",
        f"Flight category at that time: {assessment.category}",
        f"Runway most likely in use: {assessment.runway or 'unknown'}",
        f"Headwind {assessment.headwind:.0f} kt, crosswind {assessment.crosswind:.0f} kt "
        f"({assessment.crosswind_ratio:.0%} of the type's demonstrated crosswind)",
        "",
        "Factors:",
    ] + [f"  - {f.name}: {f.detail}" for f in assessment.factors]
    text = "\n".join(brief)

    allowed = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)}
    allowed |= set(range(0, 13))

    # A verdict follows from its factors, so the same factors give the same
    # verdict. Sixty flights reassessed hourly was the bulk of the spend and
    # almost all of it re-deciding cases that had not changed.
    from .. import llmcache
    cache_key = llmcache.key_for("verdict", model, text)
    cached = llmcache.get(cache_key)
    if cached:
        assessment.colour = cached["colour"]
        assessment.reason = cached["reason"]
        assessment.source = "claude"
        return assessment

    if not llmcache.spend():
        return assessment              # keep the rule verdict

    try:
        import anthropic
        from pydantic import BaseModel

        class Verdict(BaseModel):
            colour: str
            reason: str

        response = anthropic.Anthropic(api_key=key).messages.parse(
            model=model, max_tokens=1000, system=SYSTEM,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content":
                       f"{text}\n\nReturn colour (green, yellow or orange) "
                       "and a one-sentence reason."}],
            output_format=Verdict,
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("model declined")

        parsed = response.parsed_output
        colour = parsed.colour.strip().lower()
        if colour not in (GREEN, YELLOW, ORANGE):
            return assessment
        reason = parsed.reason.strip()
        if validate(reason, allowed):
            return assessment          # cited a figure not in the brief
        assessment.colour, assessment.reason = colour, reason
        assessment.source = "claude"
        llmcache.put(cache_key, {"colour": colour, "reason": reason})
    except Exception:                  # never fail a build on a verdict
        pass
    return assessment
