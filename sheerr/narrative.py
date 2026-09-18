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
from datetime import timedelta
import re

from . import llmcache
from dataclasses import dataclass

from .region import RegionDay, RegionSummary

MODEL = "claude-opus-5"

#: Numbers in the prose may differ from the source by this much and still
#: count as supported -- the model is asked to round to whole units.
TOLERANCE = 1.0

SYSTEM = """You write public regional forecasts for Sheerr Weather, in the \
style of an Environment Canada forecast.

Plain statements of fact, in order. No personality, no scene-setting, no
figures of speech, no dialect. Never address the reader. Never describe what
something feels like unless the data gives you a feels-like temperature.
Do not open with a summary line or a flourish.

Say only what the data supports. Include a subject only when the weather
warrants it: mention accumulation when there is accumulation, mention a
change in the wind only when the figures show one. Omit anything the brief
does not give you. A short forecast is correct when there is little to say.

Sky comes from the brief in words. Spell wind directions out in full
(Northwest, not NW). Temperatures in Celsius, wind in km/h.

Use ONLY figures present in the brief. Never invent, interpolate or round a
number that is not given. Quote a range as a range. Do not state a
confidence or probability the brief does not contain.

Name the local areas the brief gives you rather than the measuring points,
and only when a figure genuinely differs across the region. If the region is
uniform, do not name places at all.

Mention an active alert plainly in one short sentence if there is one.
Report conditions only. Never advise on safety, travel, closures, or
whether to go ahead with anything.

This is the register, not a template to fill. The content follows the
weather, so a different day says different things in a different order:

  Mostly cloudy with rain showers. Chance of rain 100%. Northwest winds at
  40 to 50 km/h with gusts to 90 km/h in the afternoon. Winds subside in
  the evening. High of 18. Rainfall amount: Less than 5 mm expected."""


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


def _range(spread, unit: str = "") -> str:
    """Format a spread, collapsing to one value when the bounds match.

    A single-point forecast is a region of one, so every spread collapses;
    "51 to 51 km/h" would be the giveaway.
    """
    low, high = round(spread.low.value), round(spread.high.value)
    if low == high:
        return f"{low}{unit}"
    return f"{low} to {high}{unit}"


def _clock_phrase(when):
    from .region import clock_phrase
    return clock_phrase(when)


def _far_apart(a, b):
    from .region import phrases_far_apart
    return phrases_far_apart(a, b)


def build_brief(summary: RegionSummary, day: RegionDay) -> tuple[str, set[float]]:
    """Render the day's aggregates as a brief, plus the figures it permits."""
    allowed: set[float] = set()
    lines = [
        f"Region: {summary.name}",
        f"Members sampled: {', '.join(summary.member_names)}",
        f"Period: {day.label or day.day_of_week}, {day.date:%-d %B %Y}"
        + (" — a night period: report the overnight low, not a daytime high"
           if day.night_only else " — a daytime period: report the high"),
        "",
    ]

    def record(*values):
        for v in values:
            if v is not None:
                allowed.add(round(float(v)))

    if day.sky:
        lines.append(f"Sky: {day.sky}")

    # Timing is given in words, never as a clock reading: a digit here
    # would be a figure the prose is then allowed to invent around.
    #
    # The same collapse the deterministic writer applies has to happen here
    # too. Handing Claude "begins: near midnight" and "ends: after midnight"
    # gets both back in the prose, which is where "beginning near midnight
    # and ending after midnight" came from.
    begins = None if day.precip_underway else _clock_phrase(day.precip_start)
    ends = _clock_phrase(day.precip_end)
    if begins and ends and not _far_apart(begins, ends):
        ends = None
    if day.precip_underway:
        lines.append("Precipitation: already underway as this period opens")
    elif begins:
        lines.append(f"Precipitation begins: {begins}")
    if ends:
        lines.append(f"Precipitation ends: {ends}")

    if day.night_only and day.low:
        record(day.low.low.value, day.low.high.value)
        lines.append(f"Low: {_range(day.low)} C")
    elif day.high:
        record(day.high.low.value, day.high.high.value)
        where = (f" (coolest {day.high.low.area}, warmest {day.high.high.area})"
                 if day.high.low.area != day.high.high.area else "")
        lines.append(f"Highs: {_range(day.high)} C{where}")

    if day.wind_speed:
        record(day.wind_speed.low.value, day.wind_speed.high.value)
        lines.append(f"Sustained wind: {_range(day.wind_speed)} km/h")

    if day.gust:
        record(day.gust.low.value, day.gust.high.value)
        where = (f" (lightest {day.gust.low.area}, strongest {day.gust.high.area})"
                 if day.gust.low.area != day.gust.high.area else "")
        lines.append(f"Peak gusts: {_range(day.gust)} km/h{where}")
        if day.peak_gust_at:
            from .region import period_of as _period
            lines.append(
                f"Strongest gusts over {day.gust.high.area}, "
                f"{_period(day.peak_gust_at)}")
        if day.peak_window:
            lines.append(_window_phrase(day.peak_window))

    if day.dominant_direction:
        from .region import direction_word, period_of
        lines.append(
            f"Wind direction: predominantly "
            f"{direction_word(day.dominant_direction) or day.dominant_direction}")

    if day.precip_amount is not None and day.precip_amount >= 0.5:
        record(day.precip_amount)
        noun = "Snowfall" if (day.precip_kind or "").startswith(("snow", "flurr")) \
            else "Rainfall"
        lines.append(f"{noun} amount: {day.precip_amount:.0f} mm")

    if day.precip_chance:
        record(day.precip_chance.low.value, day.precip_chance.high.value)
        lines.append(f"Chance of {day.precip_kind or 'precipitation'}: "
                     f"{day.precip_chance.high.value:.0f}%")

    if summary.alerts:
        lines.append("")
        lines.append("Active alerts (mention the alert type, do not quote figures "
                     "from it unless they also appear above):")
        from .region import alert_title
        for a in summary.alerts:
            lines.append("  - " + alert_title(a.get("eventDescription")
                                              or a.get("headlineText")))

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
    """Deterministic writer, in the same register as the generated text.

    Also the safety net when Claude is unavailable or its output fails
    validation, so the site always has text.
    """
    from .region import (clock_phrase, direction_word, period_of,
                         phrases_far_apart)

    headline = (day.sky or "Cloud").capitalize() + "."

    parts = []
    if day.precip_chance and day.precip_chance.high.value >= 20:
        # "Chance of rain", the way a forecast says it. The generic word is
        # only reached for when nothing names the form.
        what = day.precip_kind or "precipitation"
        chance = f"Chance of {what} {day.precip_chance.high.value:.0f}%"
        # A period can be wet without being wet throughout. Say when it
        # arrives, rather than leaving a reader to assume it is already
        # raining because the chance is high.
        timing = []
        begins = (clock_phrase(day.precip_start)
                  if day.precip_start and not day.precip_underway else None)
        ends = clock_phrase(day.precip_end) if day.precip_end else None
        # "Beginning near midnight and ending after midnight" is accurate
        # and useless. An ending is only worth giving when it is far enough
        # from the start to mean something different.
        if begins and ends and not phrases_far_apart(begins, ends):
            ends = None
        if begins:
            timing.append(f"beginning {begins}")
        if ends:
            timing.append(f"ending {ends}")
        if timing:
            chance += ", " + " and ".join(timing)
        parts.append(chance + ".")

    if day.wind_speed:
        direction = direction_word(day.dominant_direction)
        lead = f"{direction} winds" if direction else "Winds"
        wind = f"{lead} {_range(day.wind_speed)} km/h"
        if day.gust and day.gust.high.value >= 40:
            wind += f" with gusts to {_fmt(day.gust.high.value)} km/h"
            period = period_of(day.peak_gust_at)
            if period:
                wind += f" {period}"
        parts.append(wind + ".")

    if day.night_only:
        if day.low:
            parts.append(f"Low of {_fmt(day.low.low.value)}.")
    elif day.high:
        if day.high.uniform:
            parts.append(f"High of {_fmt(day.high.high.value)}.")
        else:
            parts.append(
                f"Highs {_range(day.high)}, coolest over {day.high.low.area}.")
    if day.precip_amount is not None and day.precip_amount >= 0.5:
        # Snow does not have a rainfall amount.
        noun = "Snowfall" if (day.precip_kind or "").startswith(("snow", "flurr")) \
            else "Rainfall"
        parts.append(f"{noun} amount {day.precip_amount:.0f} mm.")

    return Narrative(headline, " ".join(parts), "rule-based", [])


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

    # The same brief always produces the same forecast, so an hourly
    # rebuild of unchanged weather can reuse what it wrote last time.
    cache_key = llmcache.key_for("region", model, brief)
    cached = llmcache.get(cache_key)
    if cached:
        return Narrative(cached["headline"], cached["discussion"],
                         cached.get("source", "claude"), [])

    if not llmcache.spend():
        result = rule_based(summary, day)
        result.warnings.append(
            f"model budget of {llmcache.BUDGET} calls spent for this build; "
            "used rule-based text")
        return result

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
                    "Write the regional forecast for this day.\n"
                    "headline: the sky and precipitation in one short statement, "
                    "e.g. \"Mostly cloudy with rain showers.\"\n"
                    "discussion: the remaining conditions as plain statements — "
                    "chance of precipitation, wind and gusts, temperature, and "
                    "accumulation if there is any. Leave out whatever the brief "
                    "does not support. No summary line, no commentary."
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

        # Only store text that passed validation; caching a bad passage
        # would serve it for a week.
        llmcache.put(cache_key, {"headline": headline, "discussion": discussion,
                                 "source": "claude"})
        return Narrative(headline, discussion, "claude",
                         [key_warning] if key_warning else [])

    except Exception as exc:  # noqa: BLE001 - never fail a build on narrative
        fallback = rule_based(summary, day)
        fallback.warnings.append(f"Claude unavailable ({exc.__class__.__name__}); "
                                 "used rule-based text")
        return fallback
