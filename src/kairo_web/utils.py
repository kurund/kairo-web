"""Small pure helpers — iso-week math, tag-pill color picker, hour formatting."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from kairo_web.config import get_settings

# Deterministic palette for tag pills. Stable hash → palette index. Keeps tags
# visually consistent across page loads.
_TAG_PALETTE = ["red", "teal", "indigo", "amber", "pink", "slate"]

# Common semantic names get hand-picked colors so they always look "right".
_TAG_OVERRIDES = {
    "urgent": "red",
    "blocked": "red",
    "important": "red",
    "shipping": "teal",
    "review": "teal",
    "done": "teal",
    "writing": "indigo",
    "planning": "indigo",
    "design": "indigo",
    "meeting": "amber",
    "call": "amber",
    "1:1": "amber",
    "bills": "amber",
    "admin": "slate",
    "ops": "slate",
    "family": "pink",
    "personal": "pink",
}


def tag_color_for(name: str) -> str:
    """Return a stable Tailwind color name for a tag pill."""
    key = (name or "").lower().strip()
    if key in _TAG_OVERRIDES:
        return _TAG_OVERRIDES[key]
    # Stable, deterministic hash → palette index. (Built-in hash() varies per process.)
    h = sum(ord(c) for c in key) if key else 0
    return _TAG_PALETTE[h % len(_TAG_PALETTE)]


# ----- ISO-week helpers ----------------------------------------------------


def _local_today() -> date:
    """Today's date in the configured local timezone."""
    tz = ZoneInfo(get_settings().KAIRO_TIMEZONE)
    return datetime.now(tz).date()


def get_current_iso_week() -> tuple[int, int]:
    """Return today's (iso_year, iso_week) in the configured timezone."""
    iso = _local_today().isocalendar()
    return iso.year, iso.week


def iso_week_dates(year: int, week: int) -> tuple[date, date]:
    """Return (Monday, Sunday) for the given ISO week."""
    monday = date.fromisocalendar(year, week, 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_week_label(year: int, week: int) -> str:
    """e.g. 'Week 19 · May 4 – 10'  (or 'May 30 – Jun 5' across month boundary)."""
    monday, sunday = iso_week_dates(year, week)
    if monday.month == sunday.month:
        return f"Week {week} · {_MONTH_ABBR[monday.month]} {monday.day} – {sunday.day}"
    return (
        f"Week {week} · {_MONTH_ABBR[monday.month]} {monday.day} – "
        f"{_MONTH_ABBR[sunday.month]} {sunday.day}"
    )


def format_today_label(d: date | None = None) -> str:
    """e.g. 'Tue May 5'."""
    d = d or _local_today()
    weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()]
    return f"{weekday} {_MONTH_ABBR[d.month]} {d.day}"


def shift_iso_week(year: int, week: int, delta_weeks: int) -> tuple[int, int]:
    """Shift an ISO week by ±N weeks, handling year boundaries via real dates."""
    monday, _ = iso_week_dates(year, week)
    target = monday + timedelta(weeks=delta_weeks)
    iso = target.isocalendar()
    return iso.year, iso.week


# ----- Hour formatting -----------------------------------------------------


def format_hours(h: float | None) -> str | None:
    """Format hours for display: 0.5 → '30m', 0.75 → '45m', 2 → '2.0h'."""
    if h is None:
        return None
    if h == 0:
        return "0h"
    if h < 1:
        return f"{int(round(h * 60))}m"
    return f"{h:.1f}h"
