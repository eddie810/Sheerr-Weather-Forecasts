"""Field-level source routing.

Different models are better at different things, so a blended forecast
takes each field from a nominated source rather than trusting one
provider end to end. Every value carries the source it came from, so
rendered output can always be attributed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Forecast, Hour

#: Fields that can be routed to a specific source.
BLENDABLE_FIELDS = [
    "temperature", "feels_like", "humidity", "precip_chance", "precip_amount",
    "precip_type", "cloud_cover", "wind_speed", "wind_gust", "wind_direction",
    "wind_degrees", "visibility", "uv_index", "phrase",
]

#: Sheerr house defaults: TWC for temperature and precipitation, ECMWF open
#: data for the wind picture. Wind speed and direction follow gusts to the
#: same model on purpose -- mixing sustained wind and gusts across models can
#: yield a gust weaker than the sustained wind, which is not physical.
#:
#: Wind routes to `ecmwf` (ECMWF's own open data, CC BY 4.0) rather than to
#: ECMWF via Open-Meteo. If the `ecmwf` fetch fails, blending falls back to
#: whichever other source is present and records that on the page.
DEFAULT_FIELD_SOURCES: dict[str, str] = {
    "temperature": "twc",
    "feels_like": "twc",
    "humidity": "twc",
    "precip_chance": "twc",
    "precip_amount": "twc",
    "precip_type": "twc",
    "cloud_cover": "twc",
    "phrase": "twc",
    "visibility": "twc",
    "uv_index": "twc",
    "wind_speed": "ecmwf",
    "wind_gust": "ecmwf",
    "wind_direction": "ecmwf",
    "wind_degrees": "ecmwf",
}


@dataclass
class BlendedValue:
    """A single field value plus where it came from."""

    value: Any
    source: str | None = None
    label: str | None = None
    fallback: bool = False

    def __bool__(self) -> bool:
        return self.value is not None

    def __str__(self) -> str:
        return "—" if self.value is None else str(self.value)


@dataclass
class BlendedHour:
    """An hour assembled from several sources."""

    time: Any
    fields: dict[str, BlendedValue]
    sources_used: dict[str, str]
    notes: list[str]

    def __getattr__(self, name: str) -> Any:
        """Expose `hour.temperature` as the plain value for templates."""
        fields = self.__dict__.get("fields", {})
        if name in fields:
            return fields[name].value
        raise AttributeError(name)

    def source_of(self, field: str) -> str | None:
        v = self.fields.get(field)
        return v.label or v.source if v else None

    def is_fallback(self, field: str) -> bool:
        v = self.fields.get(field)
        return bool(v and v.fallback)


def blend_hours(hours_by_source: dict[str, Hour | None],
                labels: dict[str, str],
                field_sources: dict[str, str] | None = None) -> BlendedHour | None:
    """Combine one hour from each source into a single blended hour.

    A field falls back to any other source that has it when the preferred
    source is missing or absent, and the fallback is recorded.
    """
    available = {k: v for k, v in hours_by_source.items() if v is not None}
    if not available:
        return None

    routing = {**DEFAULT_FIELD_SOURCES, **(field_sources or {})}
    fields: dict[str, BlendedValue] = {}
    used: dict[str, str] = {}
    notes: list[str] = []

    for field in BLENDABLE_FIELDS:
        preferred = routing.get(field)
        value, source, fallback = None, None, False

        if preferred and preferred in available:
            value = getattr(available[preferred], field, None)
            source = preferred

        if value is None:
            for name, hour in available.items():
                candidate = getattr(hour, field, None)
                if candidate is not None:
                    value, source = candidate, name
                    fallback = preferred is not None and name != preferred
                    break

        if fallback:
            notes.append(
                f"{field} fell back to {labels.get(source, source)} "
                f"({labels.get(preferred, preferred)} had no value)"
            )
        fields[field] = BlendedValue(value, source, labels.get(source), fallback)
        if source:
            used[field] = source

    _check_wind_consistency(fields, labels, notes)

    reference = next(iter(available.values()))
    return BlendedHour(time=reference.time, fields=fields,
                       sources_used=used, notes=notes)


def _check_wind_consistency(fields: dict[str, BlendedValue], labels: dict[str, str],
                            notes: list[str]) -> None:
    """Warn when gusts and sustained wind come from different models and clash."""
    gust, speed = fields.get("wind_gust"), fields.get("wind_speed")
    if not (gust and speed) or gust.value is None or speed.value is None:
        return
    if gust.source != speed.source and gust.value < speed.value:
        notes.append(
            f"gust ({labels.get(gust.source, gust.source)}) is below sustained wind "
            f"({labels.get(speed.source, speed.source)}); sources disagree"
        )


def source_labels(forecasts: list[Forecast]) -> dict[str, str]:
    """Map source ids to display labels."""
    from .providers import PROVIDERS

    labels = {}
    for f in forecasts:
        base = f.provider.split(":")[0]
        cls = PROVIDERS.get(base)
        if ":" in f.provider:
            from .providers.openmeteo import MODEL_LABELS
            model = f.provider.split(":", 1)[1]
            labels[f.provider] = MODEL_LABELS.get(model, f"{cls.label if cls else base} ({model})")
        else:
            labels[f.provider] = cls.label if cls else base
    return labels
