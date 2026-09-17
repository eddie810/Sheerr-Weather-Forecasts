"""The Weather Company (weather.com) provider.

Needs an API key in `TWC_API_KEY`. Unlike Open-Meteo, TWC ships
human-written narratives and named dayparts, which templates can use
verbatim or override with their own wording.
"""

from __future__ import annotations

import os
from datetime import datetime

from ..models import Current, Day, Daypart, Forecast, Hour, Location
from .base import Provider, ProviderError

BASE = "https://api.weather.com"

#: Daily endpoints in preference order; not every key is cleared for each.
DAILY_ENDPOINTS = ["15day", "7day", "5day"]
HOURLY_ENDPOINTS = ["15day", "3day", "2day"]


class TWCProvider(Provider):
    name = "twc"
    label = "The Weather Company"
    attribution = "Forecast data from The Weather Company (weather.com)"

    def __init__(self, api_key: str | None = None, language: str = "en-CA", **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or os.environ.get("TWC_API_KEY")
        if not self.api_key:
            raise ProviderError(
                "TWC_API_KEY is not set. Export it or copy .env.example to .env. "
                "Use --provider open-meteo to generate without a key."
            )
        self.language = language

    def _params(self, units: str, **extra) -> dict:
        return {
            "format": "json",
            "units": "e" if units == "imperial" else "m",
            "language": self.language,
            "apiKey": self.api_key,
            **extra,
        }

    def _first_available(self, kind: str, endpoints: list[str], geocode: str,
                         units: str) -> dict:
        """Try endpoints in order, skipping ones this key cannot reach.

        Plans differ in which ranges they authorize, so a 401 on the widest
        endpoint is expected rather than fatal.
        """
        last: ProviderError | None = None
        for ep in endpoints:
            try:
                data = self._get(f"{BASE}/v3/wx/forecast/{kind}/{ep}",
                                 self._params(units, geocode=geocode))
                if data:
                    return data
            except ProviderError as exc:
                last = exc
                continue
        raise last or ProviderError(f"{self.label}: no {kind} endpoint available")

    def fetch(self, location: Location, days: int = 7, units: str = "metric") -> Forecast:
        geocode = location.geocode
        daily = self._first_available("daily", DAILY_ENDPOINTS, geocode, units)
        try:
            hourly = self._first_available("hourly", HOURLY_ENDPOINTS, geocode, units)
        except ProviderError:
            hourly = {}

        current = self._get(f"{BASE}/v3/wx/observations/current",
                            self._params(units, geocode=geocode))
        alerts = self._get(f"{BASE}/v3/alerts/headlines",
                           self._params(units, geocode=geocode))

        return Forecast(
            location=location,
            provider=self.name,
            issued_at=datetime.now().astimezone(),
            units=units,
            current=self._parse_current(current),
            days=self._parse_days(daily, limit=days),
            hours=self._parse_hours(hourly),
            alerts=self._enrich_alerts(alerts.get("alerts", []) if alerts else [], units),
        )

    def _enrich_alerts(self, alerts: list[dict], units: str) -> list[dict]:
        """Attach the full narrative text to each alert headline.

        Headlines alone say a statement exists; the detail text says what it
        actually warns about, which is what a reader needs.
        """
        for alert in alerts:
            detail_key = alert.get("detailKey")
            if not detail_key:
                continue
            try:
                detail = self._get(f"{BASE}/v3/alerts/detail",
                                   self._params(units, alertId=detail_key))
            except ProviderError:
                continue
            texts = (detail.get("alertDetail") or {}).get("texts") or []
            if texts:
                alert["description"] = texts[0].get("description")
                alert["instruction"] = texts[0].get("instruction")
        return alerts

    def _parse_current(self, cur: dict | None) -> Current | None:
        if not cur:
            return None
        return Current(
            temperature=cur.get("temperature"),
            feels_like=cur.get("temperatureFeelsLike"),
            humidity=cur.get("relativeHumidity"),
            wind_speed=cur.get("windSpeed"),
            wind_direction=cur.get("windDirectionCardinal"),
            pressure=cur.get("pressureMeanSeaLevel"),
            visibility=cur.get("visibility"),
            uv_index=cur.get("uvIndex"),
            phrase=cur.get("wxPhraseLong") or cur.get("cloudCoverPhrase"),
            observed_at=_parse_dt(cur.get("validTimeLocal")),
        )

    def _parse_days(self, daily: dict, limit: int) -> list[Day]:
        """Fold TWC's parallel arrays into Day objects.

        The `daypart` arrays are twice the length of the daily arrays: two
        entries (day, night) per calendar day. A forecast issued mid-day has
        a null first entry, because "Today" has already passed.
        """
        times = daily.get("validTimeLocal", [])
        dayparts = (daily.get("daypart") or [{}])[0]
        days: list[Day] = []

        for i, iso in enumerate(times[:limit]):
            get = lambda key: _at(daily.get(key), i)  # noqa: E731
            date = _parse_dt(iso)
            parts = [
                p for p in (self._parse_daypart(dayparts, 2 * i),
                            self._parse_daypart(dayparts, 2 * i + 1))
                if p is not None
            ]
            daytime = next((p for p in parts if p.is_daytime), None)
            days.append(Day(
                date=date.date() if date else None,
                day_of_week=get("dayOfWeek"),
                high=get("temperatureMax") or get("calendarDayTemperatureMax"),
                low=get("temperatureMin") or get("calendarDayTemperatureMin"),
                precip_chance=daytime.precip_chance if daytime else None,
                precip_amount=get("qpf"),
                snow_amount=get("qpfSnow"),
                wind_speed=daytime.wind_speed if daytime else None,
                wind_direction=daytime.wind_direction if daytime else None,
                humidity=daytime.humidity if daytime else None,
                uv_index=daytime.uv_index if daytime else None,
                cloud_cover=daytime.cloud_cover if daytime else None,
                sunrise=_parse_dt(get("sunriseTimeLocal")),
                sunset=_parse_dt(get("sunsetTimeLocal")),
                phrase=daytime.phrase if daytime else None,
                narrative=get("narrative"),
                dayparts=parts,
            ))
        return days

    def _parse_daypart(self, dp: dict, index: int) -> Daypart | None:
        name = _at(dp.get("daypartName"), index)
        if name is None:
            return None  # Elapsed daypart on a mid-day issuance.
        get = lambda key: _at(dp.get(key), index)  # noqa: E731
        return Daypart(
            name=name,
            is_daytime=get("dayOrNight") == "D",
            temperature=get("temperature"),
            precip_chance=get("precipChance"),
            precip_type=get("precipType"),
            wind_speed=get("windSpeed"),
            wind_direction=get("windDirectionCardinal"),
            wind_phrase=get("windPhrase"),
            humidity=get("relativeHumidity"),
            uv_index=get("uvIndex"),
            cloud_cover=get("cloudCover"),
            phrase=get("wxPhraseLong"),
            narrative=get("narrative"),
        )

    def _parse_hours(self, hourly: dict | None) -> list[Hour]:
        if not hourly:
            return []
        hours: list[Hour] = []
        for i, iso in enumerate(hourly.get("validTimeLocal", [])):
            get = lambda key: _at(hourly.get(key), i)  # noqa: E731
            hours.append(Hour(
                time=_parse_dt(iso),
                temperature=get("temperature"),
                feels_like=get("temperatureFeelsLike"),
                humidity=get("relativeHumidity"),
                precip_chance=get("precipChance"),
                precip_amount=get("qpf"),
                precip_type=get("precipType"),
                cloud_cover=get("cloudCover"),
                wind_speed=get("windSpeed"),
                wind_gust=get("windGust"),
                wind_direction=get("windDirectionCardinal"),
                wind_degrees=get("windDirection"),
                visibility=get("visibility"),
                uv_index=get("uvIndex"),
                phrase=get("wxPhraseLong"),
            ))
        return hours


def _at(values: list | None, index: int):
    if not values or index >= len(values):
        return None
    return values[index]


def _parse_dt(value: str | None) -> datetime | None:
    """Parse TWC's `2026-09-19T14:30:00-0230` local timestamps."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None
