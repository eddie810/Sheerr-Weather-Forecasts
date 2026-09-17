"""Regional forecast narrative.

Claude writes the regional discussion from a structured brief of the
aggregated figures. Because a weather product cannot afford an invented
number, every figure in the generated prose is checked back against the
source data; prose that cites an unsupported number is rejected and the
deterministic fallback is used instead.

Set ANTHROPIC_API_KEY to enable. Without it, the rule-based writer runs,
so an unattended build never fails for want of a key.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .region import RegionDay, RegionSummary

MODEL = "claude-opus-5"

#: Numbers in the prose may differ from the source by this much and still
#: count as supported -- the model is asked to round to whole units.
TOLERANCE = 1.0

SYSTEM = """You are a meteorologist writing public regional forecasts for \
Sheerr Weather, a Canadian forecasting service.

Write in the register of an Environment Canada regional forecast: plain, \
calm, specific. Short declarative sentences. No marketing language, no \
emoji, no exclamation marks, no hedging filler like "it's worth noting".

Absolute rules:
- Use ONLY figures present in the brief. Never invent, interpolate or \
round-trip a number that is not given to you.
- Quote ranges as ranges when the brief gives a range. Do not collapse a \
range to a single value.
- When the brief names where an extreme occurs, name that place.
- Do not state a confidence or probability the brief does not contain.
- Never advise on safety, closures or whether to cancel an event. Report \
conditions only.
- Metric units. Temperatures in degrees Celsius, wind in km/h."""


@dataclass
class Narrative:
    """Generated regional text, and how it was produced."""

    headline: str
    discussion: str
    source: str  # "claude" | "rule-based" | "rule-based (validation failed)"
    warnings: list[str]


#: Environment variables are case-sensitive on Linux, and a key stored under
#: the wrong casing fails *silently* -- the build falls back to rule-based
#: prose and nobody notices. Accept any casing, and say so.
KEY_NAMES = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]


def find_api_key() -> tuple[str | None, str | None]:
    """Locate the Anthropic key under any capitalisation.

    Returns (key, warning). The warning is set when the key was found under
    a non-standard name, so the page can surface the misconfiguration
    instead of quietly degrading.
    """
    for name in KEY_NAMES:
        value = os.environ.get(name)
        if value:
            return value, None

    wanted = {n.lower() for n in KEY_NAMES}
    for name, value in os.environ.items():
        if name.lower() in wanted and value:
            return value, (
                f"found the API key as {name!r}; environment variables are "
                f"case-sensitive, so rename it to {name.upper()!r}"
            )
    return None, None


def _window_phrase(window) -> str:
    """Describe a peak window, collapsing a single hour to "around"."""
    start, end = window
    if start == end:
        return f"Strongest winds around {start:%-I %p}"
    return f"Strongest winds between {start:%-I %p} and {end:%-I %p}"


def _fmt(value: float | None, unit: str = "") -> str:
    return "—" if value is None else f"{value:.0f}{unit}"


def build_brief(summary: RegionSummary, day: RegionDay) -> tuple[str, set[float]]:
    """Render the day's aggregates as a brief, plus the figures it permits."""
    allowed: set[float] = set()
    lines = [
        f"Region: {summary.name}",
        f"Members sampled: {', '.join(summary.member_names)}",
        f"Day: {day.day_of_week}, {day.date:%-d %B %Y}",
        "",
    ]

    def record(*values):
        for v in values:
            if v is not None:
                allowed.add(round(float(v)))

    if day.high and day.low:
        record(day.high.low.value, day.high.high.value,
               day.low.low.value, day.low.high.value)
        lines.append(
            f"Highs: {_fmt(day.high.low.value)} to {_fmt(day.high.high.value)} C "
            f"(coolest {day.high.low.where}, warmest {day.high.high.where})")
        lines.append(
            f"Lows: {_fmt(day.low.low.value)} to {_fmt(day.low.high.value)} C")

    if day.wind_speed:
        record(day.wind_speed.low.value, day.wind_speed.high.value)
        lines.append(
            f"Sustained wind: {_fmt(day.wind_speed.low.value)} to "
            f"{_fmt(day.wind_speed.high.value)} km/h")

    if day.gust:
        record(day.gust.low.value, day.gust.high.value)
        lines.append(
            f"Peak gusts: {_fmt(day.gust.low.value)} to {_fmt(day.gust.high.value)} km/h "
            f"(weakest {day.gust.low.where}, strongest {day.gust.high.where})")
        if day.peak_gust_at:
            lines.append(
                f"Regional peak gust {_fmt(day.gust.high.value)} km/h at "
                f"{day.peak_gust_where}, around {day.peak_gust_at:%-I %p}")
        if day.peak_window:
            lines.append(_window_phrase(day.peak_window))

    if day.dominant_direction:
        lines.append(
            f"Wind direction: predominantly {day.dominant_direction} "
            f"({day.direction_agreement:.0%} of sampled points agree)")

    if day.precip_chance:
        record(day.precip_chance.low.value, day.precip_chance.high.value)
        lines.append(
            f"Chance of precipitation: {_fmt(day.precip_chance.low.value)}% to "
            f"{_fmt(day.precip_chance.high.value)}%")

    if day.cloud_cover:
        record(day.cloud_cover.low.value, day.cloud_cover.high.value)
        lines.append(
            f"Cloud cover: {_fmt(day.cloud_cover.low.value)}% to "
            f"{_fmt(day.cloud_cover.high.value)}%")

    if summary.alerts:
        lines.append("")
        lines.append("Active alerts (mention the alert type, do not quote figures "
                     "from it unless they also appear above):")
        for a in summary.alerts:
            lines.append(f"  - {a.get('eventDescription') or a.get('headlineText')}")

    if summary.missing:
        lines.append("")
        lines.append(f"Not sampled this run: {', '.join(summary.missing)}")

    # Small integers are ordinary prose ("two areas"), not weather figures.
    allowed |= {0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0}
    allowed.add(float(day.date.day))
    return "\n".join(lines), allowed


NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def validate(text: str, allowed: set[float]) -> list[str]:
    """Every number in the prose must be supported by the brief."""
    violations = []
    for match in NUMBER.finditer(text):
        value = float(match.group())
        if not any(abs(value - ok) <= TOLERANCE for ok in allowed):
            context = text[max(0, match.start() - 35):match.end() + 35].strip()
            violations.append(f"unsupported figure {match.group()!r} in: ...{context}...")
    return violations


def rule_based(summary: RegionSummary, day: RegionDay) -> Narrative:
    """Deterministic fallback writer.

    Also the safety net when Claude is unavailable or its output fails
    validation, so the site always has text.
    """
    bits = []
    if day.cloud_cover and day.cloud_cover.high.value >= 70:
        bits.append("Cloudy")
    elif day.cloud_cover and day.cloud_cover.high.value >= 40:
        bits.append("Variable cloud")
    else:
        bits.append("Mainly sunny")

    if day.gust and day.gust.high.value >= 70:
        bits.append("and very windy")
    elif day.gust and day.gust.high.value >= 50:
        bits.append("and windy")
    headline = " ".join(bits) + f" across the {summary.name}."

    parts = [headline]
    if day.high:
        if day.high.uniform:
            parts.append(f"Highs near {_fmt(day.high.high.value)}C.")
        else:
            parts.append(
                f"Highs {_fmt(day.high.low.value)} to {_fmt(day.high.high.value)}C, "
                f"coolest around {day.high.low.where}.")
    if day.wind_speed and day.gust:
        direction = f"{day.dominant_direction} " if day.dominant_direction else ""
        parts.append(
            f"{direction}winds {_fmt(day.wind_speed.low.value)} to "
            f"{_fmt(day.wind_speed.high.value)} km/h, gusting "
            f"{_fmt(day.gust.low.value)} to {_fmt(day.gust.high.value)} km/h, "
            f"strongest around {day.gust.high.where}.")
    if day.peak_window:
        parts.append(_window_phrase(day.peak_window) + ".")
    if day.precip_chance and day.precip_chance.high.value >= 30:
        parts.append(
            f"Chance of precipitation {_fmt(day.precip_chance.low.value)} to "
            f"{_fmt(day.precip_chance.high.value)}%.")

    return Narrative(headline, " ".join(parts[1:]), "rule-based", [])


def write(summary: RegionSummary, day: RegionDay,
          api_key: str | None = None, model: str = MODEL) -> Narrative:
    """Generate the regional narrative, falling back when it cannot be trusted."""
    key_warning = None
    key = api_key
    if not key:
        key, key_warning = find_api_key()
    if not key:
        result = rule_based(summary, day)
        result.warnings.append("ANTHROPIC_API_KEY not set; used rule-based text")
        return result

    brief, allowed = build_brief(summary, day)

    try:
        import anthropic
        from pydantic import BaseModel

        class RegionalForecast(BaseModel):
            headline: str
            discussion: str

        client = anthropic.Anthropic(api_key=key)
        response = client.messages.parse(
            model=model,
            max_tokens=2000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            messages=[{
                "role": "user",
                "content": (
                    f"{brief}\n\n"
                    "Write the regional forecast.\n"
                    "headline: one sentence, under 15 words, capturing the day.\n"
                    "discussion: two short paragraphs covering temperature, wind "
                    "including gusts and their timing, and precipitation. Name the "
                    "places holding the extremes. Use only the figures above."
                ),
            }],
            output_format=RegionalForecast,
        )

        if response.stop_reason == "refusal":
            raise RuntimeError("model declined the request")

        parsed = response.parsed_output
        text = f"{parsed.headline} {parsed.discussion}"
        violations = validate(text, allowed)
        if violations:
            fallback = rule_based(summary, day)
            fallback.source = "rule-based (validation failed)"
            fallback.warnings = violations
            return fallback

        return Narrative(parsed.headline.strip(), parsed.discussion.strip(),
                         "claude", [key_warning] if key_warning else [])

    except Exception as exc:  # noqa: BLE001 - never fail a build on narrative
        fallback = rule_based(summary, day)
        fallback.warnings.append(f"Claude unavailable ({exc.__class__.__name__}); "
                                 "used rule-based text")
        return fallback
