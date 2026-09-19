"""Rendering forecasts through Jinja templates.

Templates live in `templates/` and are chosen by name + format, so
`--template event --format html` renders `templates/event.html.j2`.
Editing those files is how forecast wording gets customised; no Python
changes required.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

#: Compass arrows for wind direction, by 16-point cardinal.
_ARROWS = {
    "N": "↓", "NNE": "↓", "NE": "↙", "ENE": "←", "E": "←", "ESE": "←",
    "SE": "↖", "SSE": "↑", "S": "↑", "SSW": "↑", "SW": "↗", "WSW": "→",
    "W": "→", "WNW": "→", "NW": "↘", "NNW": "↓",
}


class RenderError(RuntimeError):
    """Raised when a template is missing or cannot be rendered."""


def num(value: Any, digits: int = 0, dash: str = "—") -> str:
    """Format a number, falling back to an em dash when absent."""
    if value is None:
        return dash
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def pct(value: Any, dash: str = "—") -> str:
    return dash if value is None else f"{float(value):.0f}%"


def clock(value: Any, fmt: str = "%-I:%M %p") -> str:
    """Format a datetime as a local clock time."""
    if not isinstance(value, datetime):
        return "—"
    return value.strftime(fmt)


def alert_title(value: Any) -> str:
    """Name an alert the way it is issued, without a vendor's colour code."""
    from .region import alert_title as _title
    return _title(value)


def clock_words(value: Any) -> str:
    """Time of day in words, for a forecast's own way of timing things."""
    from .region import clock_phrase
    return clock_phrase(value) or ""


def datestr(value: Any, fmt: str = "%A, %B %-d") -> str:
    if not isinstance(value, datetime):
        try:
            return value.strftime(fmt)
        except AttributeError:
            return "—"
    return value.strftime(fmt)


def arrow(cardinal: Any) -> str:
    """Arrow showing the direction the wind is blowing *towards*."""
    return _ARROWS.get(str(cardinal).upper(), "") if cardinal else ""


def wind_desc(speed: Any, unit: str = "km/h") -> str:
    """Plain-language wind strength, for templates that prefer words."""
    if speed is None:
        return "unknown"
    s = float(speed)
    if unit == "mph":
        s *= 1.609
    for limit, word in ((1, "calm"), (12, "light"), (20, "a light breeze"),
                        (29, "a moderate breeze"), (39, "a fresh breeze"),
                        (50, "a strong breeze"), (62, "near gale"), (75, "gale")):
        if s < limit:
            return word
    return "storm force"


def direction(cardinal: Any) -> str:
    """Spell a cardinal direction out in full for display."""
    from .region import direction_word
    return direction_word(cardinal) or (cardinal or "")


def alert_locations(alert: Any) -> list:
    """Expose the alert's named places to templates."""
    from .region import alert_locations as _locs
    return _locs(alert if isinstance(alert, dict) else {})


def alert_lead(alert: Any) -> str:
    """Expose the alert lead line to templates."""
    from .region import alert_lead as _lead
    return _lead(alert if isinstance(alert, dict) else {})


def build_env(template_dir: Path | str | None = None) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(template_dir or TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    # Templates gate on the same floor the prose does, rather than each
    # carrying its own number.
    from .region import POP_FLOOR
    env.globals["pop_floor"] = POP_FLOOR
    env.filters.update({
        "num": num, "pct": pct, "clock": clock, "datestr": datestr,
        "arrow": arrow, "wind_desc": wind_desc, "direction": direction, "alert_lead": alert_lead, "alert_locations": alert_locations,
        "clock_words": clock_words, "alert_title": alert_title,
    })
    return env


def template_name(name: str, fmt: str) -> str:
    """`event` + `html` -> `event.html.j2`."""
    if name.endswith(".j2"):
        return name
    extension = {"md": "md", "markdown": "md", "text": "md",
                 "html": "html", "htm": "html"}.get(fmt, fmt)
    return f"{name}.{extension}.j2"


def render(name: str, fmt: str, context: dict[str, Any],
           template_dir: Path | str | None = None) -> str:
    env = build_env(template_dir)
    filename = template_name(name, fmt)
    try:
        template = env.get_template(filename)
    except TemplateNotFound:
        available = sorted(p.name for p in Path(template_dir or TEMPLATE_DIR).glob("*.j2"))
        raise RenderError(
            f"Template {filename!r} not found. Available: {', '.join(available)}"
        )
    return template.render(**context)
