"""Shared provider plumbing."""

from __future__ import annotations

import time

import requests

from ..models import Forecast, Location


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a forecast."""


class Provider:
    """Base class for weather data sources."""

    #: Short identifier used on the CLI and in config.
    name: str = "base"
    #: Human-readable name for attribution in rendered output.
    label: str = "Base Provider"
    #: Attribution line templates are encouraged to surface.
    attribution: str = ""

    def __init__(self, timeout: int = 30, session: requests.Session | None = None,
                 retries: int = 3):
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()

    @property
    def source_id(self) -> str:
        """Stable identifier for this source, including any model variant."""
        return self.name

    def fetch(self, location: Location, days: int = 7, units: str = "metric") -> Forecast:
        raise NotImplementedError

    def _get(self, url: str, params: dict) -> dict:
        """GET returning JSON, with provider-flavoured error messages."""
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                break
            except requests.RequestException as exc:
                # Large model queries are occasionally cut off mid-transfer;
                # back off and retry rather than failing the whole forecast.
                last = exc
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)
        else:
            raise ProviderError(
                f"{self.label}: request failed after {self.retries} attempts: {last}"
            ) from last

        if response.status_code == 401:
            raise ProviderError(
                f"{self.label}: unauthorized (401). Check the API key."
            )
        if response.status_code == 403:
            raise ProviderError(
                f"{self.label}: forbidden (403). The key may not cover this endpoint."
            )
        if response.status_code == 204:
            # TWC uses 204 for "nothing to report" (e.g. no active alerts).
            return {}
        if not response.ok:
            raise ProviderError(
                f"{self.label}: HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.label}: response was not valid JSON") from exc
