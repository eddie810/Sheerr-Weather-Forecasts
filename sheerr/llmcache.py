"""Reuse of model output between builds, and a ceiling on spend.

The site rebuilds hourly so that warnings reach the page quickly. The
forecast behind those pages moves far more slowly: ECMWF publishes four
runs a day, and figures rounded to the nearest five change less often than
that. Regenerating the same prose every hour was buying nothing.

Written text is a pure function of the brief it was written from, so a
brief that has not changed can reuse what it produced last time. That
turns a rebuild into a free operation whenever the weather has not moved,
which is most of them.

The budget is the backstop. Caching fails open — a cache miss still calls
the model — so a bad day could still run away. `SHEERR_LLM_BUDGET` caps
how many calls one build may make; past it, callers fall back to their
deterministic writers.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

#: How long a cached passage stays usable. A brief that changes invalidates
#: itself, so this only bounds text whose inputs are stable for days.
TTL_SECONDS = int(os.environ.get("SHEERR_LLM_TTL", 7 * 24 * 3600))

#: Calls one build may make. Generous for a normal day, and a firm stop on
#: the bad one: sixty flights with weather factors, rebuilt hourly, is
#: forty thousand calls a month.
BUDGET = int(os.environ.get("SHEERR_LLM_BUDGET", 40))

#: Bumping this invalidates every cached passage, for when the prompt
#: changes and the old wording should not be served.
PROMPT_VERSION = "2"

_spent = 0


def _cache_dir() -> Path:
    path = Path(os.environ.get("SHEERR_LLM_CACHE")
                or Path(tempfile.gettempdir()) / "sheerr-llm-cache")
    path.mkdir(parents=True, exist_ok=True)
    return path


def key_for(*parts: str) -> str:
    """A stable key for the inputs a passage was written from."""
    digest = hashlib.sha1()
    digest.update(PROMPT_VERSION.encode())
    for part in parts:
        digest.update(b"\x00")
        digest.update((part or "").encode("utf-8", "replace"))
    return digest.hexdigest()[:20]


def get(key: str) -> dict | None:
    path = _cache_dir() / f"{key}.json"
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > TTL_SECONDS:
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None


def put(key: str, value: dict) -> None:
    try:
        (_cache_dir() / f"{key}.json").write_text(json.dumps(value))
    except OSError:
        pass        # A cache miss is survivable; a failed build is not.


def spend() -> bool:
    """Claim one call against this build's budget."""
    global _spent
    if _spent >= BUDGET:
        return False
    _spent += 1
    return True


def spent() -> int:
    return _spent


def remaining() -> int:
    return max(0, BUDGET - _spent)
