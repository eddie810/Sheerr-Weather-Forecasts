"""Regional forecasts.

A region is several point forecasts summarised as one. The useful content
of a regional forecast is not any single value but the spread: the range
across the area, which point holds each extreme, and when conditions peak.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import date as Date, datetime, time, timedelta
from typing import Any

from .blend import blend_hours, source_labels
from .models import Forecast, Location


#: Environment Canada sky-condition bands, by percentage cloud cover.
#: Broadcasters say "mainly cloudy", never "83 per cent cloud".
SKY_BANDS = [
    (10, "sunny", "clear"),
    (30, "mainly sunny", "mainly clear"),
    (70, "a mix of sun and cloud", "partly cloudy"),
    (90, "mainly cloudy", "mainly cloudy"),
    (101, "cloudy", "cloudy"),
]


#: The hour a forecast stops saying "Today" and starts saying "Tonight",
#: in the region's own local time.
EVENING_HOUR = 18

#: Local hours a public forecast divides the day on: the day period runs
#: from DAY_START, the night period from NIGHT_START through to DAY_START
#: the following morning.
DAY_START = 6
NIGHT_START = 18

#: Forecasts spell wind directions out in full; "NW" is chart shorthand.
DIRECTION_WORDS = {
    "N": "North", "NNE": "North-northeast", "NE": "Northeast",
    "ENE": "East-northeast", "E": "East", "ESE": "East-southeast",
    "SE": "Southeast", "SSE": "South-southeast", "S": "South",
    "SSW": "South-southwest", "SW": "Southwest", "WSW": "West-southwest",
    "W": "West", "WNW": "West-northwest", "NW": "Northwest",
    "NNW": "North-northwest",
}


def round5(value: float | None) -> float | None:
    """Round to the nearest 5, with halves going up.

    Public forecasts quote wind and probability of precipitation in fives;
    "18 to 37 km/h" reads as false precision on a two-day forecast.

    Uses Decimal rather than round(), which is banker's rounding and would
    send 45 down to 40 — the opposite of the intended rule.
    """
    if value is None:
        return None
    return float(Decimal(value / 5).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 5)


def direction_word(cardinal: str | None) -> str | None:
    """"NW" -> "Northwest"."""
    return DIRECTION_WORDS.get(cardinal) if cardinal else None


def period_of(when) -> str | None:
    """Name the part of the day a forecast would use for a timestamp."""
    if when is None:
        return None
    hour = when.hour
    if hour < 6:
        return "overnight"
    if hour < 12:
        return "in the morning"
    if hour < 18:
        return "in the afternoon"
    return "in the evening"


#: The Weather Company colour-codes alert severity and folds it into the
#: title: "Yellow Warning - Wind". Environment Canada issues a wind
#: warning, with no colour, and that is what a Newfoundland audience is
#: told on every other channel. The colour is a vendor's internal grading,
#: so it is stripped rather than broadcast.
_ALERT_COLOUR = re.compile(
    r"^\s*(?:yellow|amber|orange|red|green)\s+(warning|watch|statement|advisory)\s*[-–—:]\s*(.+)$",
    re.I)
_ALERT_LEADING_KIND = re.compile(r"^\s*(warning|watch|statement|advisory)\s*[-–—:]\s*(.+)$", re.I)


def _parse_local(text) -> datetime | None:
    """An ISO timestamp from the provider, or nothing."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def alert_window(alert: dict) -> tuple[datetime | None, datetime | None]:
    """When the hazard is in effect.

    Onset and end describe the weather; effective and expire describe the
    bulletin, and a bulletin often expires hours before the wind does
    because it is due for reissue. Prefer the hazard, fall back to the
    bulletin.
    """
    start = (_parse_local(alert.get("onsetTimeLocal"))
             or _parse_local(alert.get("effectiveTimeLocal"))
             or _parse_local(alert.get("issueTimeLocal")))
    end = (_parse_local(alert.get("endTimeLocal"))
           or _parse_local(alert.get("expireTimeLocal")))
    return start, end


def alerts_in_effect(alerts: list[dict], start: datetime, end: datetime,
                     include_undated: bool = True) -> list[dict]:
    """The alerts covering a period, rather than every one on the page.

    A wind warning for Saturday afternoon belongs in Saturday's paragraph.
    Repeating it under every period tells a reader it applies all week.

    An alert carrying no usable times cannot be placed. Dropping it would
    lose a warning, so it goes in the nearest period and nowhere else —
    `include_undated` is set for the first period only.
    """
    covering = []
    for alert in alerts:
        a_start, a_end = alert_window(alert)
        if a_start is None and a_end is None:
            if include_undated:
                covering.append(alert)
            continue
        if a_start is not None and a_start >= end:
            continue                   # begins after this period
        if a_end is not None and a_end <= start:
            continue                   # over before this period
        covering.append(alert)
    return covering


def alert_title(text: str | None) -> str:
    """The alert as a forecast would name it."""
    if not text:
        return "Weather alert"
    value = str(text).strip()
    for pattern in (_ALERT_COLOUR, _ALERT_LEADING_KIND):
        match = pattern.match(value)
        if match:
            kind, topic = match.group(1).lower(), match.group(2).strip()
            # "Wind" + "warning", the way it is issued and spoken.
            return f"{topic[:1].upper()}{topic[1:]} {kind}"
    return value


def clock_phrase(when) -> str | None:
    """Name a time the way a forecast times the start of precipitation.

    Coarser than a clock and deliberately so: "near midnight" carries the
    uncertainty an hourly timestamp pretends away.
    """
    if when is None:
        return None
    hour = when.hour
    if hour >= 23 or hour == 0:
        return "near midnight"
    if hour < 5:
        return "after midnight"
    if hour < 8:
        return "early in the morning"
    if hour < 12:
        return "in the morning"
    if hour < 17:
        return "in the afternoon"
    if hour < 20:
        return "in the evening"
    return "late in the evening"


#: "Near midnight" and "after midnight" both name the same moment, so a
#: spell running 23:30 to 03:30 would otherwise be timed twice over. Every
#: other pair of phrases marks a real difference — morning to afternoon is
#: worth saying — so only these two collapse.
_MIDNIGHT_PHRASES = {"near midnight", "after midnight"}


def phrases_far_apart(start_phrase: str | None, end_phrase: str | None) -> bool:
    """Are these two times of day distinct enough to be worth saying both?"""
    if not start_phrase or not end_phrase or start_phrase == end_phrase:
        return False
    return not (start_phrase in _MIDNIGHT_PHRASES
                and end_phrase in _MIDNIGHT_PHRASES)


#: What a forecast calls each form, steady and showery. Environment Canada
#: says "chance of showers", never "chance of precipitation"; the generic
#: word belongs in a definition, not a forecast.
PRECIP_WORDS = {
    "rain": ("rain", "showers"),
    "drizzle": ("drizzle", "drizzle"),
    "snow": ("snow", "flurries"),
    "freezing rain": ("freezing rain", "freezing rain"),
    "freezing drizzle": ("freezing drizzle", "freezing drizzle"),
    "sleet": ("ice pellets", "ice pellets"),
    "ice": ("ice pellets", "ice pellets"),
    "wintry mix": ("wet snow or rain", "wet snow or rain"),
}


def precip_word(kinds: list[str], showery: bool) -> str:
    """Name what is falling, the way a forecast names it.

    The provider reports a type on every hour, fair or not — it is the form
    precipitation would take, not a statement that any is falling — so this
    is only ever asked about hours already known to be wet.
    """
    counts: dict[str, int] = {}
    for kind in kinds:
        key = (kind or "").strip().lower()
        if key:
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "showers" if showery else "precipitation"
    leading = max(counts, key=counts.get)
    steady, shower = PRECIP_WORDS.get(leading, (leading, leading))
    return shower if showery else steady


#: How far apart the wettest and driest points must be before the forecast
#: says where it is more likely. Below this the region is close enough to
#: quote one figure and leave it there.
POP_GRADIENT = 25

#: The lowest chance a forecast quotes. Below it a period is not described
#: as a chance of anything — a five per cent chance of rain is a dry
#: forecast, and printing the figure invites a reader to plan around it.
#: One constant, because the prose, the brief behind it and the figure
#: panel disagreeing is how "Chance of precipitation 5%" reached the page.
POP_FLOOR = 20

#: An hour counts as wet at this much accumulation, or at this chance when
#: no amount is given. Below it the hour is damp at most.
WET_MM = 0.1
WET_POP = 60


def _is_wet(hour) -> bool:
    """Is precipitation actually falling in this hour?"""
    if hour.precip_amount is not None and hour.precip_amount >= WET_MM:
        return True
    if hour.precip_amount is None and (hour.precip_chance or 0) >= WET_POP:
        return True
    return False


def sky_condition(cloud_percent: float | None, night: bool = False) -> str | None:
    """Turn a cloud-cover percentage into the phrase a forecast would use."""
    if cloud_percent is None:
        return None
    for limit, day_phrase, night_phrase in SKY_BANDS:
        if cloud_percent < limit:
            return night_phrase if night else day_phrase
    return "cloudy"


@dataclass
class Extreme:
    """A value, and both the point and the local area holding it."""

    value: float
    where: str
    zone: str | None = None

    @property
    def area(self) -> str:
        """Prefer the local area name; fall back to the point."""
        return self.zone or self.where


@dataclass
class Spread:
    """The range of one field across a region."""

    low: Extreme
    high: Extreme

    @property
    def range(self) -> float:
        return self.high.value - self.low.value

    @property
    def uniform(self) -> bool:
        """Whether the region is close enough to quote a single value."""
        return self.range < max(2.0, abs(self.high.value) * 0.12)


@dataclass
class RegionDay:
    """One day summarised across every member of a region."""

    date: Date
    day_of_week: str
    high: Spread | None = None
    low: Spread | None = None
    gust: Spread | None = None
    wind_speed: Spread | None = None
    precip_chance: Spread | None = None
    cloud_cover: Spread | None = None
    sky: str | None = None
    precip_amount: float | None = None
    #: What is falling, named as a forecast names it: rain, showers, snow,
    #: flurries, freezing rain.
    precip_kind: str | None = None
    #: The alerts in effect during this period, not every alert on the page.
    alerts: list[dict[str, Any]] = field(default_factory=list)
    #: The figure to quote: the region's average, not its wettest corner.
    #: The maximum read as 100% across the Avalon while St. John's sat at
    #: 55%, which is true of one point and wrong as a regional statement.
    precip_chance_typical: float | None = None
    #: Where precipitation is more likely, when the region disagrees enough
    #: to be worth saying.
    precip_gradient: str | None = None
    #: When precipitation starts and stops within this period, local time.
    #: A period reading "chance of rain 100%" with nothing falling for six
    #: hours is telling the truth badly.
    precip_start: datetime | None = None
    precip_end: datetime | None = None
    #: Already raining when the period opened, so there is no start to give.
    precip_underway: bool = False
    #: "Today", "Tonight" or the weekday, as a public forecast labels it.
    label: str = ""
    #: True once the day's high has passed and only the overnight low is
    #: still ahead, so the page stops leading with a temperature that
    #: already happened.
    night_only: bool = False

    @property
    def icon(self) -> str:
        """Which icon best describes the day.

        Precipitation wins over sky when it is likely enough to be the
        story; below that the sky condition decides. Snow is chosen on the
        day's high rather than its low, since what falls during the day is
        what people see.
        """
        pop = self.precip_chance.high.value if self.precip_chance else 0
        high = self.high.high.value if self.high else None
        wet = pop >= 60 and (self.precip_amount or 0) >= 0.5

        if wet:
            if high is not None and high <= 1:
                return "snow"
            if high is not None and high <= 3:
                return "rain-snow"
            return "rain"

        sky = (self.sky or "").lower()
        if pop >= 40 and "cloud" in sky:
            return "showers"
        if sky.startswith("sunny"):
            return "sun"
        if sky.startswith("mainly sunny"):
            return "sun-cloud"
        if sky.startswith("a mix"):
            return "part-cloud"
        if sky.startswith("mainly cloudy"):
            return "mostly-cloud"
        if sky.startswith("cloudy"):
            return "cloud"
        return "part-cloud"
    dominant_direction: str | None = None
    direction_agreement: float = 0.0
    peak_gust_at: datetime | None = None
    peak_gust_where: str | None = None
    peak_window: tuple[datetime, datetime] | None = None


@dataclass
class RegionSummary:
    """A whole region, summarised."""

    name: str
    timezone: str
    members: list[Location]
    #: Day and night periods, the way a public forecast is issued.
    days: list[RegionDay]
    #: Whole calendar days, for the seven-day strip. A strip wants one
    #: column per day with a high and a low, not a run of half-periods.
    outlook: list[RegionDay] = field(default_factory=list)
    generated_at: datetime = None       # type: ignore[assignment]
    alerts: list[dict[str, Any]] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @property
    def member_names(self) -> list[str]:
        return [m.name for m in self.members]


#: Lines in an Environment Canada statement that carry the actual threat,
#: in preference order. Used for the one-line summary when an alert is
#: collapsed.
ALERT_LEAD_KEYS = ("Maximum wind gusts", "Potential wind gusts", "Wind gusts",
                   "Rainfall", "Snowfall", "Total snowfall", "Hazard",
                   "Time span", "Locations")


def alert_locations(alert: dict) -> list[str]:
    """The places an alert names, as a list.

    Split on commas only. "St. John's and vicinity" is one place, and so is
    "Coastal Newfoundland from Green Bay to the Baie de Verde Peninsula" —
    treating "and" as a separator would break both. A trailing Oxford "and"
    is dropped once commas have already established a list.
    """
    text = (alert.get("description") or "")
    line = next((ln.strip() for ln in text.splitlines()
                 if ln.strip().lower().startswith("locations")), "")
    if not line:
        return []
    body = line.split(":", 1)[1].strip().rstrip(".") if ":" in line else ""
    if not body:
        return []
    if "," not in body:
        return [body]
    parts = []
    for chunk in body.split(","):
        chunk = chunk.strip()
        if chunk.lower().startswith("and "):
            chunk = chunk[4:].strip()
        if chunk:
            parts.append(chunk)
    return parts


def alert_lead(alert: dict) -> str:
    """One line describing what an alert actually warns about."""
    text = (alert.get("description") or "").strip()
    if not text:
        return alert.get("headlineText") or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for key in ALERT_LEAD_KEYS:
        for line in lines:
            if line.lower().startswith(key.lower()):
                return line
    return lines[0] if lines else ""


def pop_gradient(values: list[tuple[str, float, str | None]]) -> str | None:
    """Name where precipitation is more likely, by local area.

    Averages each area first so a zone with two points does not outvote one
    with a single point, then names the wettest against the driest.
    """
    by_zone: dict[str, list[float]] = {}
    for name, value, zone in values:
        if value is None:
            continue
        by_zone.setdefault(zone or name, []).append(value)
    if len(by_zone) < 2:
        return None
    means = {z: sum(v) / len(v) for z, v in by_zone.items()}
    ranked = sorted(means, key=means.get, reverse=True)
    top, bottom = ranked[0], ranked[-1]
    if means[top] - means[bottom] < POP_GRADIENT:
        return None
    # A second area worth grouping with the first.
    leaders = [z for z in ranked if means[z] >= means[top] - 10][:2]
    laggards = [z for z in reversed(ranked) if means[z] <= means[bottom] + 10][:2]
    lead = " and ".join(leaders)
    lag = " and ".join(laggards)
    return f"more likely over {lead} than {lag}"


def _spread(values: list[tuple[str, float, str | None]]) -> Spread | None:
    """Build a Spread from (location name, value, zone) triples."""
    clean = [t for t in values if t[1] is not None]
    if not clean:
        return None
    lo = min(clean, key=lambda p: p[1])
    hi = max(clean, key=lambda p: p[1])
    return Spread(Extreme(lo[1], lo[0], lo[2]), Extreme(hi[1], hi[0], hi[2]))


def _dominant_direction(dirs: list[str]) -> tuple[str | None, float]:
    """Most common wind direction and the fraction of members agreeing.

    Compass bearings cannot be averaged, so this takes a mode over the
    16-point cardinals instead.
    """
    present = [d for d in dirs if d]
    if not present:
        return None, 0.0
    counts: dict[str, int] = {}
    for d in present:
        counts[d] = counts.get(d, 0) + 1
    best = max(counts, key=counts.get)
    return best, counts[best] / len(present)


def summarise_region(name: str, timezone: str, members: list[Location],
                     forecasts_by_member: dict[str, list[Forecast]],
                     days: int = 5, tz=None) -> RegionSummary:
    """Fold per-member forecasts into a regional summary."""
    from zoneinfo import ZoneInfo

    zone_tz = tz or ZoneInfo(timezone)
    now = datetime.now(zone_tz)

    # Blend each member's sources into one hourly series per member.
    blended: dict[str, list] = {}
    zones: dict[str, str | None] = {}
    labels: dict[str, str] = {}
    alerts: list[dict] = []
    seen_alerts: set[str] = set()

    for member in members:
        fs = forecasts_by_member.get(member.slug) or []
        if not fs:
            continue
        labels.update(source_labels(fs))
        hours = []
        reference = max(fs, key=lambda f: len(f.hours))
        for hour in reference.hours:
            row = blend_hours({f.provider: f.hour_at(hour.time) for f in fs}, labels)
            if row:
                row.slot = hour.time
                hours.append(row)
        blended[member.name] = hours
        zones[member.name] = member.zone
        for f in fs:
            for a in f.alerts:
                key = a.get("headlineText") or a.get("eventDescription") or str(a)
                if key not in seen_alerts:
                    seen_alerts.add(key)
                    alerts.append(a)

    def aggregate(start: datetime, end: datetime, kind: str) -> RegionDay | None:
        """Summarise every member across one period.

        `start` and `end` are local, end-exclusive. A day period runs from
        DAY_START to NIGHT_START; a night period runs from NIGHT_START to
        DAY_START the following morning, so it belongs to the evening it
        began in rather than the date most of it falls on.
        """
        highs, lows, gusts, speeds, pops, clouds, dirs = [], [], [], [], [], [], []
        rain_totals: list[float] = []
        peak: tuple[float, datetime, str] | None = None

        for member_name, hours in blended.items():
            rows = [h for h in hours if start <= h.slot.astimezone(zone_tz) < end]
            if not rows:
                continue
            temps = [h.temperature for h in rows if h.temperature is not None]
            g = [(h.wind_gust, h.slot) for h in rows if h.wind_gust is not None]
            s = [h.wind_speed for h in rows if h.wind_speed is not None]
            p = [h.precip_chance for h in rows if h.precip_chance is not None]
            c = [h.cloud_cover for h in rows if h.cloud_cover is not None]

            zone = zones.get(member_name)
            rain = [h.precip_amount for h in rows if h.precip_amount is not None]
            if rain:
                rain_totals.append(sum(rain))
            g = [(round5(v), t) for v, t in g]
            s = [round5(v) for v in s]
            p = [round5(v) for v in p]
            if temps:
                highs.append((member_name, max(temps), zone))
                lows.append((member_name, min(temps), zone))
            if g:
                top = max(g, key=lambda x: x[0])
                gusts.append((member_name, top[0], zone))
                if peak is None or top[0] > peak[0]:
                    peak = (top[0], top[1], member_name)
                strongest = max(rows, key=lambda h: h.wind_gust or 0)
                dirs.append(strongest.wind_direction)
            if s:
                speeds.append((member_name, max(s), zone))
            if p:
                pops.append((member_name, max(p), zone))
            if c:
                clouds.append((member_name, sum(c) / len(c), zone))

        if not (highs or gusts):
            return None

        # Sky is described from the daylight hours; at night it is the
        # period's own cloud, since there is no daytime to speak of.
        cloud_hours = [h.cloud_cover for hours in blended.values() for h in hours
                       if start <= h.slot.astimezone(zone_tz) < end
                       and h.cloud_cover is not None
                       and (kind == "night"
                            or 9 <= h.slot.astimezone(zone_tz).hour <= 17)]
        # At night the sky is described as clear or cloudy, never as a mix
        # of sun and cloud.
        sky = (sky_condition(sum(cloud_hours) / len(cloud_hours), night=(kind == "night"))
               if cloud_hours else None)

        # Take the wettest point: a regional figure quoting the driest would
        # understate what to expect.
        rain_mm = max(rain_totals) if rain_totals else None

        # When precipitation arrives, on the hour that most of the region
        # has it rather than the first point to see a shower. The earliest
        # single member would time the whole Avalon off one drizzly hour on
        # the Cape Shore.
        reporting = [h for h in blended.values() if h]
        wet_by_hour: dict[datetime, int] = {}
        for hours in reporting:
            for h in hours:
                local = h.slot.astimezone(zone_tz)
                if start <= local < end and _is_wet(h):
                    wet_by_hour[local] = wet_by_hour.get(local, 0) + 1
        needed = max(1, len(reporting) // 2)
        wet_hours = sorted(t for t, n in wet_by_hour.items() if n >= needed)
        # Name the precipitation from the hours it is actually falling in.
        # The provider reports a type on fair hours too, so reading it off
        # the whole period would call a clear night "rain".
        # Prefer the hours precipitation is actually falling in. Where a
        # period only carries a chance and no accumulation — half the
        # forecast days — read the hours most likely to see it instead. A
        # fifty per cent chance of rain is still a chance of rain, and
        # naming it "precipitation" is the thing this exists to stop.
        wet_set = set(wet_hours)
        naming = [h for hours in reporting for h in hours
                  if start <= h.slot.astimezone(zone_tz) < end
                  and h.slot.astimezone(zone_tz) in wet_set]
        if not naming:
            naming = [h for hours in reporting for h in hours
                      if start <= h.slot.astimezone(zone_tz) < end
                      and (h.precip_chance or 0) >= POP_FLOOR]
        kinds, showery_hits, phrases = [], 0, 0
        for h in naming:
            if h.precip_type:
                kinds.append(h.precip_type)
            if h.phrase:
                phrases += 1
                if "shower" in h.phrase.lower():
                    showery_hits += 1
        showery = bool(phrases) and showery_hits * 2 >= phrases
        precip_kind = precip_word(kinds, showery) if naming else None

        # The regional figure is the average of the points, rounded to five
        # like the rest. Where they disagree widely, say where it is more
        # likely rather than quoting one number for the whole peninsula.
        typical = round5(sum(v for _, v, _ in pops) / len(pops)) if pops else None
        gradient = pop_gradient(pops) if pops else None

        precip_start = wet_hours[0] if wet_hours else None
        precip_end = None
        if wet_hours:
            last = wet_hours[-1]
            # Only call it an ending if it stops before the period does.
            if last + timedelta(hours=1) < end:
                precip_end = last + timedelta(hours=1)
        # Raining as the period opened: there is no beginning to report.
        underway = bool(precip_start and precip_start <= start)

        direction, agreement = _dominant_direction(dirs)
        window = None
        if peak:
            # Hours within 85% of the regional peak, to describe when it bites.
            hot = [h.slot for hours in blended.values() for h in hours
                   if start <= h.slot.astimezone(zone_tz) < end
                   and (h.wind_gust or 0) >= peak[0] * 0.85]
            if hot:
                window = (min(hot).astimezone(zone_tz), max(hot).astimezone(zone_tz))

        return RegionDay(
            date=start.date(),
            day_of_week=start.strftime("%A"),
            night_only=(kind == "night"),
            high=_spread(highs), low=_spread(lows),
            gust=_spread(gusts), wind_speed=_spread(speeds),
            precip_chance=_spread(pops), cloud_cover=_spread(clouds),
            sky=sky, precip_amount=rain_mm, dominant_direction=direction,
            direction_agreement=agreement,
            precip_start=precip_start, precip_end=precip_end,
            precip_underway=underway, precip_kind=precip_kind,
            precip_chance_typical=typical, precip_gradient=gradient,
            peak_gust_at=peak[1].astimezone(zone_tz) if peak else None,
            peak_gust_where=peak[2] if peak else None,
            peak_window=window,
        )

    def at(day: Date, hour: int) -> datetime:
        return datetime.combine(day, time(hour), tzinfo=zone_tz)

    # A public forecast is a run of day and night periods, not calendar
    # days: Today, Tonight, Saturday, Saturday night. The first period is
    # whichever one is still ahead — after the evening there is no "Today"
    # left to issue.
    region_days: list[RegionDay] = []
    local_today = now.astimezone(zone_tz).date()
    for offset in range(days + 1):
        day = local_today + timedelta(days=offset)
        for kind in ("day", "night"):
            if kind == "day":
                start, end = at(day, DAY_START), at(day, NIGHT_START)
            else:
                start = at(day, NIGHT_START)
                end = at(day + timedelta(days=1), DAY_START)
            # Periods already over are not forecast.
            if end <= now.astimezone(zone_tz):
                continue
            period = aggregate(start, end, kind)
            if period is None:
                continue
            period.alerts = alerts_in_effect(alerts, start, end,
                                             include_undated=not region_days)
            # Today's own periods are named for the present, not the
            # weekday: a forecast issued this morning says "Today" and
            # "Tonight", never "Friday" and "Friday night".
            if day == local_today:
                period.label = "Tonight" if kind == "night" else "Today"
            elif kind == "night":
                period.label = f"{day:%A} night"
            else:
                period.label = day.strftime("%A")
            region_days.append(period)
        if len(region_days) >= days * 2:
            break
    # The first day may contribute only a night period, so the loop can run
    # one day long. `days` means days, not periods.
    region_days = region_days[:days * 2]

    # The seven-day strip is a different shape: one entry per calendar day,
    # carrying both the high and the low.
    outlook: list[RegionDay] = []
    for offset in range(days):
        day = local_today + timedelta(days=offset)
        whole = aggregate(at(day, 0), at(day + timedelta(days=1), 0), "day")
        if whole is None:
            continue
        whole.label = "Today" if offset == 0 else day.strftime("%A")
        outlook.append(whole)
    return RegionSummary(
        name=name, timezone=timezone, members=members, days=region_days,
        outlook=outlook, generated_at=now, alerts=alerts, sources=labels,
        missing=[m.name for m in members if m.name not in blended],
    )
