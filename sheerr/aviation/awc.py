"""NOAA Aviation Weather Center: TAF and METAR.

Free, no key, and authoritative — a TAF is the actual terminal forecast
crews and dispatchers plan against, which makes it the right input for a
delay-risk assessment rather than a general-purpose forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import requests

BASE = "https://aviationweather.gov/api/data"

#: Ceiling and visibility thresholds for the standard flight categories.
#: NOAA supplies fltCat on METARs; TAF periods are classified here.
CATEGORIES = [
    ("LIFR", 500, 1.0),
    ("IFR", 1000, 3.0),
    ("MVFR", 3000, 5.0),
]


@dataclass
class TafPeriod:
    """One forecast period within a TAF."""

    start: datetime
    end: datetime
    change: str | None          # FM, TEMPO, BECMG, PROB30, PROB40
    probability: int | None
    wind_dir: float | None
    wind_speed: float | None
    wind_gust: float | None
    visibility: float | None    # statute miles
    ceiling: int | None         # feet AGL, lowest BKN/OVC
    weather: str | None         # raw wxString, e.g. "-SN BR"
    raw: str | None = None

    @property
    def category(self) -> str:
        """VFR / MVFR / IFR / LIFR for this period."""
        ceiling = self.ceiling if self.ceiling is not None else 99999
        visibility = self.visibility if self.visibility is not None else 99
        for name, ceil_limit, vis_limit in CATEGORIES:
            if ceiling < ceil_limit or visibility < vis_limit:
                return name
        return "VFR"

    @property
    def transient(self) -> bool:
        """Whether this is a temporary or probabilistic group.

        A TEMPO or PROB group is a possibility within the period, not the
        prevailing condition, and should be weighed differently.
        """
        return bool(self.change and self.change.upper().startswith(("TEMPO", "PROB")))


def _get(path: str, params: dict) -> list[dict]:
    response = requests.get(f"{BASE}/{path}", params={**params, "format": "json"},
                            timeout=45, headers={"User-Agent": "sheerr-weather/0.1"})
    if not response.ok:
        raise RuntimeError(f"AWC {path}: HTTP {response.status_code}")
    data = response.json()
    return data if isinstance(data, list) else []


def _ceiling(clouds: list[dict] | None) -> int | None:
    """Lowest broken or overcast layer, which is what defines a ceiling."""
    if not clouds:
        return None
    bases = [c.get("base") for c in clouds
             if c.get("cover") in ("BKN", "OVC", "OVX") and c.get("base") is not None]
    return min(bases) if bases else None


def _visibility(value) -> float | None:
    """Parse AWC visibility, which may be '6+', a number, or a fraction."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("+", "")
    try:
        if " " in text:                      # e.g. "1 1/2"
            whole, frac = text.split(" ", 1)
            num, den = frac.split("/")
            return float(whole) + float(num) / float(den)
        if "/" in text:
            num, den = text.split("/")
            return float(num) / float(den)
        return float(text)
    except (ValueError, ZeroDivisionError):
        return None


def fetch_taf(icao: str) -> tuple[str, list[TafPeriod]]:
    """Return the raw TAF text and its parsed periods."""
    rows = _get("taf", {"ids": icao})
    if not rows:
        raise RuntimeError(f"No TAF available for {icao}")
    taf = rows[0]

    periods: list[TafPeriod] = []
    for f in taf.get("fcsts") or []:
        change = f.get("fcstChange")
        periods.append(TafPeriod(
            start=datetime.fromtimestamp(f["timeFrom"], timezone.utc),
            end=datetime.fromtimestamp(f["timeTo"], timezone.utc),
            change=change,
            probability=f.get("probability"),
            wind_dir=f.get("wdir") if isinstance(f.get("wdir"), (int, float)) else None,
            wind_speed=f.get("wspd"),
            wind_gust=f.get("wgst"),
            visibility=_visibility(f.get("visib")),
            ceiling=_ceiling(f.get("clouds")),
            weather=f.get("wxString"),
        ))
    return taf.get("rawTAF", ""), periods


def fetch_metar(icao: str) -> dict:
    """Current observation, including NOAA's own flight category."""
    rows = _get("metar", {"ids": icao})
    if not rows:
        raise RuntimeError(f"No METAR available for {icao}")
    return rows[0]


def periods_covering(periods: list[TafPeriod], when: datetime) -> list[TafPeriod]:
    """Every TAF period in effect at a given time, prevailing group first."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    hits = [p for p in periods if p.start <= when < p.end]
    return sorted(hits, key=lambda p: p.transient)
