"""Open-Meteo provider.

Free, keyless, global. Supplies numbers rather than prose, so the WMO
weather codes are mapped to phrases here.
"""

from __future__ import annotations

from datetime import datetime

from ..models import Current, Day, Forecast, Hour, Location
from .base import Provider, ProviderError

API_URL = "https://api.open-meteo.com/v1/forecast"

#: WMO 4677 weather codes -> plain-language phrases.
WMO_PHRASES: dict[int, str] = {
    0: "Clear", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Cloudy",
    45: "Fog", 48: "Freezing Fog",
    51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
    56: "Light Freezing Drizzle", 57: "Freezing Drizzle",
    61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
    66: "Light Freezing Rain", 67: "Freezing Rain",
    71: "Light Snow", 73: "Snow", 75: "Heavy Snow", 77: "Snow Grains",
    80: "Light Rain Showers", 81: "Rain Showers", 82: "Heavy Rain Showers",
    85: "Light Snow Showers", 86: "Snow Showers",
    95: "Thunderstorms", 96: "Thunderstorms with Hail",
    99: "Severe Thunderstorms with Hail",
}

CARDINALS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def degrees_to_cardinal(degrees: float | None) -> str | None:
    """Compass degrees -> 16-point cardinal direction."""
    if degrees is None:
        return None
    return CARDINALS[round(degrees / 22.5) % 16]


def phrase_for(code: int | None) -> str | None:
    if code is None:
        return None
    return WMO_PHRASES.get(int(code), "Unknown")


#: Friendly names for the numerical models Open-Meteo can serve.
MODEL_LABELS = {
    "best_match": "Open-Meteo (best match)",
    "ecmwf_ifs025": "Open-Meteo (ECMWF IFS 0.25\u00b0)",
    "gfs_seamless": "Open-Meteo (NOAA GFS)",
    "icon_seamless": "Open-Meteo (DWD ICON)",
    "gem_seamless": "Open-Meteo (ECCC GEM)",
}


class OpenMeteoProvider(Provider):
    name = "open-meteo"
    label = "Open-Meteo"
    attribution = "Weather data by Open-Meteo.com (CC BY 4.0)"

    HOURLY_VARS = [
        "temperature_2m", "apparent_temperature", "relative_humidity_2m",
        "precipitation_probability", "precipitation", "cloud_cover",
        "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m",
        "visibility", "uv_index", "weather_code",
    ]
    DAILY_VARS = [
        "weather_code", "temperature_2m_max", "temperature_2m_min",
        "precipitation_sum", "snowfall_sum", "precipitation_probability_max",
        "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant",
        "uv_index_max", "sunrise", "sunset",
    ]
    CURRENT_VARS = [
        "temperature_2m", "apparent_temperature", "relative_humidity_2m",
        "cloud_cover", "wind_speed_10m", "wind_gusts_10m",
        "wind_direction_10m", "surface_pressure", "weather_code",
    ]

    def __init__(self, model: str | None = None, **kwargs):
        # ECMWF queries are noticeably slower than best_match; give them room.
        kwargs.setdefault("timeout", 90)
        super().__init__(**kwargs)
        self.model = model
        if model:
            self.label = MODEL_LABELS.get(model, f"Open-Meteo ({model})")
            self.attribution = f"{self.label} via Open-Meteo.com (CC BY 4.0)"

    @property
    def source_id(self) -> str:
        """Distinguishes model variants of the same provider."""
        return f"{self.name}:{self.model}" if self.model else self.name

    def fetch(self, location: Location, days: int = 7, units: str = "metric") -> Forecast:
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "timezone": location.timezone or "auto",
            "forecast_days": max(1, min(days, 16)),
            "current": ",".join(self.CURRENT_VARS),
            "daily": ",".join(self.DAILY_VARS),
            "hourly": ",".join(self.HOURLY_VARS),
        }
        if units == "imperial":
            params.update({
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
            })

        if self.model:
            params["models"] = self.model

        data = self._get(API_URL, params)
        if "daily" not in data:
            raise ProviderError("Open-Meteo: response contained no daily block")

        return Forecast(
            location=location,
            provider=self.source_id,
            issued_at=datetime.now().astimezone(),
            units=units,
            current=self._parse_current(data.get("current")),
            days=self._parse_days(data["daily"]),
            hours=self._parse_hours(data.get("hourly")),
        )

    def _parse_current(self, cur: dict | None) -> Current | None:
        if not cur:
            return None
        return Current(
            temperature=cur.get("temperature_2m"),
            feels_like=cur.get("apparent_temperature"),
            humidity=cur.get("relative_humidity_2m"),
            wind_speed=cur.get("wind_speed_10m"),
            wind_direction=degrees_to_cardinal(cur.get("wind_direction_10m")),
            pressure=cur.get("surface_pressure"),
            phrase=phrase_for(cur.get("weather_code")),
            observed_at=_parse_dt(cur.get("time")),
        )

    def _parse_days(self, daily: dict) -> list[Day]:
        days: list[Day] = []
        for i, iso in enumerate(daily.get("time", [])):
            get = lambda key: _at(daily.get(key), i)  # noqa: E731
            date = datetime.fromisoformat(iso).date()
            days.append(Day(
                date=date,
                day_of_week=date.strftime("%A"),
                high=get("temperature_2m_max"),
                low=get("temperature_2m_min"),
                precip_chance=get("precipitation_probability_max"),
                precip_amount=get("precipitation_sum"),
                snow_amount=get("snowfall_sum"),
                wind_speed=get("wind_speed_10m_max"),
                wind_direction=degrees_to_cardinal(get("wind_direction_10m_dominant")),
                uv_index=get("uv_index_max"),
                sunrise=_parse_dt(get("sunrise")),
                sunset=_parse_dt(get("sunset")),
                phrase=phrase_for(get("weather_code")),
            ))
        return days

    def _parse_hours(self, hourly: dict | None) -> list[Hour]:
        if not hourly:
            return []
        hours: list[Hour] = []
        for i, iso in enumerate(hourly.get("time", [])):
            get = lambda key: _at(hourly.get(key), i)  # noqa: E731
            degrees = get("wind_direction_10m")
            visibility = get("visibility")
            hours.append(Hour(
                time=_parse_dt(iso),
                temperature=get("temperature_2m"),
                feels_like=get("apparent_temperature"),
                humidity=get("relative_humidity_2m"),
                precip_chance=get("precipitation_probability"),
                precip_amount=get("precipitation"),
                cloud_cover=get("cloud_cover"),
                wind_speed=get("wind_speed_10m"),
                wind_gust=get("wind_gusts_10m"),
                wind_direction=degrees_to_cardinal(degrees),
                wind_degrees=degrees,
                # Open-Meteo reports visibility in metres; use km for parity with TWC.
                visibility=visibility / 1000 if visibility is not None else None,
                uv_index=get("uv_index"),
                phrase=phrase_for(get("weather_code")),
            ))
        return hours


def _at(values: list | None, index: int):
    """Index into a parallel array, tolerating short/absent series."""
    if not values or index >= len(values):
        return None
    return values[index]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
