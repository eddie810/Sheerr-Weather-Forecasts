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
from .runways import Airport, best_runway
from .schedule import Flight

#: Bands the colour code maps to.
GREEN, YELLOW, ORANGE = "green", "yellow", "orange"

#: Present-weather codes that drive winter delays at a Canadian airport.
FREEZING = re.compile(r"\b(FZRA|FZDZ|FZFG)\b")
FROZEN = re.compile(r"\b(\+?SN|SG|PL|GS|GR|IC|-SN|SHSN|BLSN|DRSN)\b")
OBSCURING = re.compile(r"\b(FG|BR|HZ|FU)\b")
CONVECTIVE = re.compile(r"\b(TS|TSRA|VCTS|SQ)\b")


@dataclass
class Factor:
    """One contributor to the assessment."""

    name: str
    detail: str
    weight: float       # 0-1, how strongly it pushes toward disruption


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
    factors: list[Factor] = field(default_factory=list)
    colour: str = GREEN
    reason: str = ""
    source: str = "rule-based"

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


def assess_factors(flight: Flight, airport: Airport,
                   periods: list[TafPeriod]) -> Assessment:
    """Compute the objective part of the assessment."""
    profile = profile_for(flight.aircraft_type)
    covering = periods_covering(periods, flight.scheduled)
    prevailing = covering[0] if covering else None

    wind_dir = wind_speed = gust = None
    for period in covering:                  # transient groups may omit wind
        wind_dir = wind_dir if wind_dir is not None else period.wind_dir
        wind_speed = wind_speed if wind_speed is not None else period.wind_speed
        gust = gust if gust is not None else period.wind_gust

    peak_wind = max(w for w in (wind_speed or 0, gust or 0)) or None
    runway, headwind, crosswind = best_runway(airport, wind_dir, peak_wind)
    ratio = crosswind / profile.crosswind_kt if profile.crosswind_kt else 0.0

    factors: list[Factor] = []

    if ratio >= 0.55:
        factors.append(Factor(
            "crosswind",
            f"{crosswind:.0f} kt across runway {runway.ident if runway else '?'}, "
            f"{ratio:.0%} of the {profile.name}'s {profile.crosswind_kt} kt "
            "demonstrated crosswind",
            min(1.0, (ratio - 0.35) * 1.6) * profile.wind_sensitivity,
        ))

    if gust and wind_speed and gust - wind_speed >= 15:
        factors.append(Factor(
            "gusts",
            f"gusting {gust:.0f} kt against {wind_speed:.0f} kt sustained",
            min(0.7, (gust - wind_speed) / 40) * profile.wind_sensitivity,
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
        detail = f"{category}"
        if worst:
            if worst.ceiling is not None:
                detail += f", ceiling {worst.ceiling} ft"
            if worst.visibility is not None:
                detail += f", visibility {worst.visibility:g} sm"
            if worst.transient:
                detail += " (temporary or probable group)"
        factors.append(Factor("ceiling and visibility", detail,
                              weights[category] * (0.75 if worst and worst.transient else 1.0)))

    weather = " ".join(p.weather for p in covering if p.weather)
    if FREEZING.search(weather):
        factors.append(Factor("freezing precipitation",
                              f"{weather.strip()} — de-icing and possible holdover limits",
                              0.9 * profile.deice_burden))
    elif FROZEN.search(weather):
        factors.append(Factor("snow",
                              f"{weather.strip()} — de-icing and runway clearing",
                              0.6 * profile.deice_burden))
    if CONVECTIVE.search(weather):
        factors.append(Factor("thunderstorms", weather.strip(), 0.7))

    assessment = Assessment(
        flight=flight, profile=profile, period=prevailing,
        runway=runway.ident if runway else None,
        headwind=headwind, crosswind=crosswind, crosswind_ratio=ratio,
        category=category, factors=factors,
    )
    assessment.colour, assessment.reason = _rule_verdict(assessment)
    return assessment


def _rule_verdict(a: Assessment) -> tuple[str, str]:
    """Deterministic colour and one-line reason."""
    score = a.score
    colour = ORANGE if score >= 0.6 else YELLOW if score >= 0.28 else GREEN
    if not a.factors:
        return colour, "No significant weather expected around the scheduled time."
    lead = max(a.factors, key=lambda f: f.weight)
    return colour, f"{lead.name.capitalize()}: {lead.detail}."


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
    except Exception:                  # never fail a build on a verdict
        pass
    return assessment
