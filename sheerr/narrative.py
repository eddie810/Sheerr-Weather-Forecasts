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

SYSTEM = """You are a seasoned broadcast meteorologist in Newfoundland, \
writing the regional forecast for Sheerr Weather. You have called weather on \
this island for twenty years and you talk like it.

VOICE
Short sentences. Often very short. Break things up — this is written to be
read aloud, not scanned. Lead with what people will feel when they step
outside, then fill in the detail.

Confident and plain. No hedging, no filler, no "it's worth noting". You are
telling people what the weather is doing, not presenting a data summary.

LOCAL GEOGRAPHY
Name the local areas, not the measuring points. Say "the Southern Shore",
"the northeast Avalon", "Conception Bay North", "the Cape Shore" — the areas
the brief gives you. Do not name individual communities unless the brief
gives you no area for that figure. A forecaster says "windiest on the
northeast Avalon", never "windiest at the St. John's sampling point".

Use the island's own weather language where it fits naturally and is
accurate: a blow, a good blow, blowing hard, nor'westerly, sou'westerly,
sou'easterly, dirty, mauzy, RDF (rain, drizzle and fog), lop on the water,
a civil day. Never force it. One or two of these in a forecast is plenty —
a forecast stuffed with dialect sounds like a tourist wrote it.

SKY
The brief gives you the sky condition in words — sunny, mainly sunny, a mix
of sun and cloud, mainly cloudy, cloudy. Use those words. Never quote a
cloud percentage. Nobody says "83 per cent cloud cover" on air.

FIGURES
Use ONLY figures present in the brief. Never invent or interpolate a number.
Quote ranges as ranges. Temperatures in Celsius, wind in km/h.
Do not state a confidence or probability the brief does not contain.

Mention an active alert plainly if there is one. Report conditions only —
never advise on safety, closures, travel, or whether to cancel anything."""


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

    if day.sky:
        lines.append(f"Sky: {day.sky}")

    if day.high and day.low:
        record(day.high.low.value, day.high.high.value,
               day.low.low.value, day.low.high.value)
        lines.append(
            f"Highs: {_fmt(day.high.low.value)} to {_fmt(day.high.high.value)} C "
            f"(coolest {day.high.low.area}, warmest {day.high.high.area})")
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
            f"(lightest {day.gust.low.area}, strongest {day.gust.high.area})")
        if day.peak_gust_at:
            lines.append(
                f"Strongest gusts over {day.gust.high.area}, around "
                f"{day.peak_gust_at:%-I %p}")
        if day.peak_window:
            lines.append(_window_phrase(day.peak_window))

    if day.dominant_direction:
        lines.append(
            f"Wind direction: predominantly {day.dominant_direction}")

    if day.precip_chance:
        record(day.precip_chance.low.value, day.precip_chance.high.value)
        lines.append(
            f"Chance of precipitation: {_fmt(day.precip_chance.low.value)}% to "
            f"{_fmt(day.precip_chance.high.value)}%")

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

#: Literal \uXXXX / \xXX sequences that survived JSON decoding. Structured
#: output occasionally double-escapes punctuation such as an em dash. Left
#: alone they render as garbage on the page, and their digits look like
#: forecast figures to the validator.
ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})")


def decode_escapes(text: str) -> str:
    """Turn any surviving literal escape sequences into real characters."""
    def swap(match: re.Match) -> str:
        return chr(int(match.group(1) or match.group(2), 16))

    return ESCAPE.sub(swap, text)


def validate(text: str, allowed: set[float]) -> list[str]:
    """Every number in the prose must be supported by the brief."""
    text = decode_escapes(text)
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
    sky = (day.sky or "Cloud").capitalize()
    wind = None
    if day.gust and day.gust.high.value >= 70:
        wind = "very windy"
    elif day.gust and day.gust.high.value >= 50:
        wind = "windy"

    if wind:
        # A comma keeps "a mix of sun and cloud" from colliding with "and windy".
        joiner = ", and " if " and " in sky.lower() else " and "
        headline = f"{sky}{joiner}{wind} across the {summary.name}."
    else:
        headline = f"{sky} across the {summary.name}."

    parts = [headline]
    if day.high:
        if day.high.uniform:
            parts.append(f"Highs near {_fmt(day.high.high.value)}C.")
        else:
            parts.append(
                f"Highs {_fmt(day.high.low.value)} to {_fmt(day.high.high.value)}C, "
                f"coolest over {day.high.low.area}.")
    if day.wind_speed and day.gust:
        direction = f"{day.dominant_direction} " if day.dominant_direction else ""
        parts.append(
            f"{direction}winds {_fmt(day.wind_speed.low.value)} to "
            f"{_fmt(day.wind_speed.high.value)} km/h, gusting "
            f"{_fmt(day.gust.low.value)} to {_fmt(day.gust.high.value)} km/h, "
            f"strongest over {day.gust.high.area}.")
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
                    "discussion: two short paragraphs, as you would read them on "
                    "air. Cover the sky, temperature, the wind including gusts and "
                    "when they peak, and the chance of rain. Name the local areas "
                    "holding the extremes, not the measuring points. Short "
                    "sentences. Use only the figures above, and the sky in words."
                ),
            }],
            output_format=RegionalForecast,
        )

        if response.stop_reason == "refusal":
            raise RuntimeError("model declined the request")

        parsed = response.parsed_output
        headline = decode_escapes(parsed.headline).strip()
        discussion = decode_escapes(parsed.discussion).strip()
        text = f"{headline} {discussion}"
        violations = validate(text, allowed)
        if violations:
            fallback = rule_based(summary, day)
            fallback.source = "rule-based (validation failed)"
            fallback.warnings = violations
            return fallback

        return Narrative(headline, discussion, "claude",
                         [key_warning] if key_warning else [])

    except Exception as exc:  # noqa: BLE001 - never fail a build on narrative
        fallback = rule_based(summary, day)
        fallback.warnings.append(f"Claude unavailable ({exc.__class__.__name__}); "
                                 "used rule-based text")
        return fallback
