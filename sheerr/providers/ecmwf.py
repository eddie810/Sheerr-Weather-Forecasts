"""ECMWF Open Data provider (IFS HRES 0.25°).

Fetches straight from ECMWF's open data portal, which is licensed CC BY 4.0
and permits commercial redistribution with attribution -- unlike Open-Meteo's
free endpoint.

The catch is that open data ships as whole-globe GRIB2 files of ~138 MB per
timestep. Each file has a `.index` sidecar listing the byte offset of every
parameter inside it, so a single field is pulled with an HTTP range request
(~1.4 MB) instead of the whole file. Because the field is global, every
location in a build reads from the same download, so the cache below is keyed
by run and step, never by location.

Resolution notes that matter when reading the output:
  * Steps are 3-hourly out to 144h, so values between steps are interpolated.
  * `10fg` is the MAXIMUM gust since the previous post-processing step, i.e.
    the worst case over the preceding 3 hours, not an instantaneous value.
  * Values come from the nearest 0.25 degree gridpoint (~28 km) with no
    downscaling, so coastal terrain is not resolved.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..models import Current, Day, Forecast, Hour, Location
from .base import Provider, ProviderError

BASE = "https://data.ecmwf.int/forecasts"

#: Cycles published each day, newest first.
CYCLES = ["18", "12", "06", "00"]

#: Surface parameters this provider reads, and what they become.
PARAMS = {
    "10fg": "wind_gust",      # max gust since previous post-processing (m/s)
    "10u": "_u",              # 10m eastward wind component (m/s)
    "10v": "_v",              # 10m northward wind component (m/s)
    "2t": "temperature",      # 2m temperature (K)
    "tcc": "cloud_cover",     # total cloud cover (0-1)
}

#: Beyond this step the archive switches from 3-hourly to 6-hourly.
THREE_HOURLY_LIMIT = 144

CARDINALS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


class ECMWFOpenDataProvider(Provider):
    name = "ecmwf"
    label = "ECMWF Open Data (IFS HRES 0.25°)"
    attribution = (
        "Forecast data from ECMWF IFS open data, licensed CC BY 4.0. "
        "Source: www.ecmwf.int"
    )

    def __init__(self, cache_dir: str | None = None, max_workers: int = 8,
                 interpolate: bool = True, **kwargs):
        kwargs.setdefault("timeout", 90)
        super().__init__(**kwargs)
        self.cache_dir = Path(
            cache_dir or os.environ.get("SHEERR_ECMWF_CACHE")
            or Path(tempfile.gettempdir()) / "sheerr-ecmwf-cache"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_workers = max_workers
        self.interpolate = interpolate
        self._run: tuple[str, str] | None = None

    # ---- run discovery -------------------------------------------------

    def latest_run(self, probe_step: int = 12) -> tuple[str, str]:
        """Most recent cycle whose data has actually been published.

        Dissemination lags the cycle time by several hours and arrives
        progressively, so the newest directory is not necessarily usable.
        """
        if self._run:
            return self._run

        now = datetime.now(timezone.utc)
        for day_offset in range(3):
            date = (now - timedelta(days=day_offset)).strftime("%Y%m%d")
            for cycle in CYCLES:
                when = datetime.strptime(f"{date}{cycle}", "%Y%m%d%H").replace(
                    tzinfo=timezone.utc
                )
                if when > now:
                    continue
                if self._index_exists(date, cycle, probe_step):
                    self._run = (date, cycle)
                    return self._run
        raise ProviderError(
            f"{self.label}: no published run found in the last 3 days"
        )

    def _index_exists(self, date: str, cycle: str, step: int) -> bool:
        try:
            response = self.session.head(
                self._url(date, cycle, step, "index"), timeout=20
            )
            return response.status_code == 200
        except Exception:
            return False

    def _url(self, date: str, cycle: str, step: int, kind: str) -> str:
        return (f"{BASE}/{date}/{cycle}z/ifs/0p25/oper/"
                f"{date}{cycle}0000-{step}h-oper-fc.{kind}")

    # ---- fetching ------------------------------------------------------

    def _index(self, date: str, cycle: str, step: int) -> dict[str, tuple[int, int]]:
        """Map parameter -> (offset, length) for one timestep."""
        cached = self.cache_dir / f"{date}{cycle}-{step}.index"
        if cached.exists():
            text = cached.read_text()
        else:
            response = self.session.get(self._url(date, cycle, step, "index"),
                                        timeout=self.timeout)
            if not response.ok:
                raise ProviderError(
                    f"{self.label}: index for step {step}h unavailable "
                    f"(HTTP {response.status_code})"
                )
            text = response.text
            cached.write_text(text)

        entries: dict[str, tuple[int, int]] = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("levtype") == "sfc" and row.get("param") in PARAMS:
                entries[row["param"]] = (int(row["_offset"]), int(row["_length"]))
        return entries

    def _message(self, date: str, cycle: str, step: int, param: str,
                 offset: int, length: int) -> Path:
        """Byte-range fetch one GRIB message, cached on disk."""
        cached = self.cache_dir / f"{date}{cycle}-{step}-{param}.grib2"
        if cached.exists() and cached.stat().st_size == length:
            return cached

        headers = {"Range": f"bytes={offset}-{offset + length - 1}"}
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.session.get(self._url(date, cycle, step, "grib2"),
                                            headers=headers, timeout=self.timeout)
                if response.status_code in (200, 206) and len(response.content) == length:
                    cached.write_bytes(response.content)
                    return cached
                last = ProviderError(
                    f"HTTP {response.status_code}, {len(response.content)} bytes"
                )
            except Exception as exc:
                last = exc
        raise ProviderError(
            f"{self.label}: could not fetch {param} at step {step}h: {last}"
        )

    def _steps_for(self, days: int) -> list[int]:
        hours = min(days * 24, 360)
        steps = list(range(0, min(hours, THREE_HOURLY_LIMIT) + 1, 3))
        if hours > THREE_HOURLY_LIMIT:
            steps += list(range(THREE_HOURLY_LIMIT + 6, hours + 1, 6))
        return steps

    def prefetch(self, steps: list[int]) -> tuple[str, str]:
        """Download every needed message in parallel before decoding."""
        date, cycle = self.latest_run()

        def one(step: int):
            try:
                index = self._index(date, cycle, step)
            except ProviderError:
                return  # Step not published yet; skipped, not fatal.
            for param, (offset, length) in index.items():
                try:
                    self._message(date, cycle, step, param, offset, length)
                except ProviderError:
                    pass

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            list(pool.map(one, steps))
        return date, cycle

    # ---- decoding ------------------------------------------------------

    def fetch(self, location: Location, days: int = 7, units: str = "metric") -> Forecast:
        try:
            import eccodes
        except ImportError as exc:
            raise ProviderError(
                f"{self.label}: eccodes is required. Install it with "
                "`pip install eccodes`."
            ) from exc

        steps = self._steps_for(days)
        date, cycle = self.prefetch(steps)
        run_start = datetime.strptime(f"{date}{cycle}", "%Y%m%d%H").replace(
            tzinfo=timezone.utc
        )

        hours: list[Hour] = []
        for step in steps:
            values = self._read_step(eccodes, date, cycle, step, location)
            if not values:
                continue
            hours.append(self._to_hour(run_start + timedelta(hours=step), values, units))

        if not hours:
            raise ProviderError(
                f"{self.label}: no timesteps could be read for {location.name}"
            )

        native = list(hours)
        if self.interpolate:
            hours = _interpolate_hourly(hours)

        return Forecast(
            location=location,
            provider=self.name,
            issued_at=run_start,
            units=units,
            current=self._to_current(hours[0]),
            days=self._to_days(native, units),
            hours=hours,
        )

    def _read_step(self, eccodes, date: str, cycle: str, step: int,
                   location: Location) -> dict[str, float]:
        """Decode every cached param for one step at the nearest gridpoint."""
        values: dict[str, float] = {}
        for param, field in PARAMS.items():
            path = self.cache_dir / f"{date}{cycle}-{step}-{param}.grib2"
            if not path.exists():
                continue
            try:
                with open(path, "rb") as handle:
                    gid = eccodes.codes_grib_new_from_file(handle)
                    if gid is None:
                        continue
                    try:
                        nearest = eccodes.codes_grib_find_nearest(
                            gid, location.latitude, location.longitude
                        )[0]
                        values[field] = nearest.value
                    finally:
                        eccodes.codes_release(gid)
            except Exception:
                continue
        return values

    def _to_hour(self, when: datetime, values: dict[str, float], units: str) -> Hour:
        gust = values.get("wind_gust")
        # At step 0 there is no preceding post-processing window, so 10fg is
        # reported as zero. That is an artifact, not a calm forecast.
        if gust == 0.0:
            gust = None
        u, v = values.get("_u"), values.get("_v")
        speed = math.hypot(u, v) if u is not None and v is not None else None
        degrees = None
        if u is not None and v is not None and speed:
            # Meteorological convention: the direction the wind blows FROM.
            degrees = (math.degrees(math.atan2(-u, -v))) % 360

        temperature = values.get("temperature")
        if temperature is not None:
            temperature -= 273.15  # Kelvin -> Celsius
        cloud = values.get("cloud_cover")

        def speed_out(mps: float | None) -> float | None:
            if mps is None:
                return None
            return mps * 2.23694 if units == "imperial" else mps * 3.6

        if temperature is not None and units == "imperial":
            temperature = temperature * 9 / 5 + 32

        return Hour(
            time=when,
            temperature=round(temperature, 1) if temperature is not None else None,
            cloud_cover=round(cloud * 100, 0) if cloud is not None else None,
            wind_speed=round(speed_out(speed), 1) if speed is not None else None,
            wind_gust=round(speed_out(gust), 1) if gust is not None else None,
            wind_direction=CARDINALS[round(degrees / 22.5) % 16] if degrees is not None else None,
            wind_degrees=round(degrees, 0) if degrees is not None else None,
        )

    def _to_current(self, first: Hour) -> Current:
        return Current(
            temperature=first.temperature,
            wind_speed=first.wind_speed,
            wind_direction=first.wind_direction,
            observed_at=first.time,
        )

    def _to_days(self, hours: list[Hour], units: str) -> list[Day]:
        """Roll the 3-hourly series up into calendar days."""
        buckets: dict = {}
        for hour in hours:
            buckets.setdefault(hour.time.date(), []).append(hour)

        days = []
        for date in sorted(buckets):
            rows = buckets[date]
            temps = [h.temperature for h in rows if h.temperature is not None]
            gusts = [h.wind_gust for h in rows if h.wind_gust is not None]
            speeds = [h.wind_speed for h in rows if h.wind_speed is not None]
            clouds = [h.cloud_cover for h in rows if h.cloud_cover is not None]
            strongest = max(rows, key=lambda h: h.wind_speed or 0, default=None)
            days.append(Day(
                date=date,
                day_of_week=date.strftime("%A"),
                high=max(temps) if temps else None,
                low=min(temps) if temps else None,
                wind_speed=max(speeds) if speeds else None,
                wind_direction=strongest.wind_direction if strongest else None,
                cloud_cover=sum(clouds) / len(clouds) if clouds else None,
            ))
        return days


#: Fields safe to interpolate linearly between native timesteps.
_INTERPOLATED = ["temperature", "cloud_cover", "wind_speed", "wind_gust"]


def _interpolate_hourly(steps: list[Hour]) -> list[Hour]:
    """Fill the gaps between native 3-hourly steps with hourly values.

    Open data is 3-hourly, but events happen at arbitrary times and the other
    providers are hourly, so blending across them is cleaner on a common
    grid. Interpolation is linear, and wind direction is carried from the
    nearer step rather than averaged, since averaging compass bearings across
    north gives nonsense.

    Note that `wind_gust` is a maximum over the preceding window, so an
    interpolated gust is an estimate of that running maximum, not a new
    instantaneous reading.
    """
    if len(steps) < 2:
        return steps

    out: list[Hour] = []
    for current, following in zip(steps, steps[1:]):
        out.append(current)
        gap = int((following.time - current.time).total_seconds() // 3600)
        for offset in range(1, gap):
            fraction = offset / gap
            nearer = current if fraction < 0.5 else following
            out.append(Hour(
                time=current.time + timedelta(hours=offset),
                wind_direction=nearer.wind_direction,
                wind_degrees=nearer.wind_degrees,
                **{
                    field: _lerp(getattr(current, field), getattr(following, field), fraction)
                    for field in _INTERPOLATED
                },
            ))
    out.append(steps[-1])
    return out


def _lerp(start: float | None, end: float | None, fraction: float) -> float | None:
    if start is None or end is None:
        return start if end is None else end
    return round(start + (end - start) * fraction, 1)
