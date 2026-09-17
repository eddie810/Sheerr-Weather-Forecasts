"""Weather data providers.

Each provider fetches from one upstream API and returns the neutral
`Forecast` model, so adding a source means adding a module here and
registering it in `PROVIDERS`.
"""

from __future__ import annotations

from .base import Provider, ProviderError
from .openmeteo import OpenMeteoProvider
from .twc import TWCProvider

PROVIDERS: dict[str, type[Provider]] = {
    OpenMeteoProvider.name: OpenMeteoProvider,
    TWCProvider.name: TWCProvider,
}


def get_provider(name: str, **kwargs) -> Provider:
    """Instantiate a provider by name."""
    try:
        return PROVIDERS[name](**kwargs)
    except KeyError:
        known = ", ".join(sorted(PROVIDERS))
        raise ProviderError(f"Unknown provider {name!r}. Known providers: {known}")


__all__ = [
    "Provider",
    "ProviderError",
    "OpenMeteoProvider",
    "TWCProvider",
    "PROVIDERS",
    "get_provider",
]
