#!/usr/bin/env python3
"""
Shared timezone helpers for Jarvis.

The app generally treats scheduled times as:
- parsed in the configured local timezone
- stored in the DB as UTC ISO strings (naive UTC for reminder compatibility)
- converted back to local time only for display
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config_loader import get_config_value


def get_app_timezone_name(default: str = "America/Los_Angeles") -> str:
    """Return the configured application timezone name."""
    return get_config_value("JARVIS_TIMEZONE", default) or default


def get_app_timezone(default: str = "America/Los_Angeles") -> ZoneInfo:
    """Return the configured application timezone object."""
    return ZoneInfo(get_app_timezone_name(default))


def get_timezone_by_name(name: str) -> ZoneInfo:
    """Return a ZoneInfo object for an explicit IANA timezone name."""
    return ZoneInfo(name)


def now_utc() -> datetime:
    """Current UTC time as an aware datetime."""
    return datetime.now(timezone.utc)


def now_local(default: str = "America/Los_Angeles") -> datetime:
    """Current local app time as an aware datetime."""
    return datetime.now(get_app_timezone(default))


def ensure_local(dt: datetime, tz: ZoneInfo | None = None) -> datetime:
    """Attach or convert a datetime into the configured local timezone."""
    tz = tz or get_app_timezone()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def parse_utc_timestamp(value: str) -> datetime:
    """
    Parse a stored UTC timestamp.

    Supports both explicit UTC strings (with `Z` or `+00:00`) and legacy
    reminder rows that store naive UTC strings.
    """
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_utc_db(dt: datetime) -> str:
    """
    Format a datetime for DB storage as naive UTC ISO.

    This preserves reminder DB compatibility and SQLite string ordering while
    keeping all conversion logic centralized.
    """
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def format_utc_z(dt: datetime) -> str:
    """Format a datetime as explicit UTC with a trailing Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_display_datetime(dt: datetime) -> str:
    """Format an aware datetime for compact human display with timezone."""
    text = dt.strftime("%Y-%m-%d %I:%M %p %Z")
    return text.replace(" 0", " ", 1)


def utc_string_display_fields(value: str, tz: ZoneInfo | None = None) -> dict[str, str]:
    """Return local and UTC display fields for a stored UTC timestamp string."""
    tz = tz or get_app_timezone()
    utc_dt = parse_utc_timestamp(value)
    local_dt = utc_dt.astimezone(tz)
    return {
        "utc": format_utc_z(utc_dt),
        "utc_display": format_display_datetime(utc_dt),
        "local": local_dt.isoformat(),
        "local_display": format_display_datetime(local_dt),
        "timezone": getattr(tz, "key", str(tz)),
    }


def to_local_from_utc_string(value: str, tz: ZoneInfo | None = None) -> datetime:
    """Convert a stored UTC string into an aware local datetime."""
    tz = tz or get_app_timezone()
    return parse_utc_timestamp(value).astimezone(tz)


def safe_iso_to_local_datetime(iso_text: str | None, tz: ZoneInfo | None = None) -> datetime | None:
    """
    Parse an ISO timestamp string and normalize to local time.

    Used for message timestamps, tool execution times, and other mixed ISO inputs:
    - Suffix ``Z`` is treated as UTC.
    - Naive values are interpreted in ``tz`` (default: app timezone).
    - Aware values are converted to ``tz``.
    Returns None when empty or unparsable.
    """
    if not iso_text:
        return None
    tz = tz or get_app_timezone()
    try:
        dt = datetime.fromisoformat(str(iso_text).replace("Z", "+00:00"))
        if getattr(dt, "tzinfo", None) is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except Exception:
        return None


def add_months_local(dt: datetime, months: int = 1) -> datetime:
    """Add months while preserving local wall-clock time when possible."""
    year = dt.year
    month = dt.month + months
    while month > 12:
        year += 1
        month -= 12

    day = dt.day
    while day >= 28:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1

    return dt.replace(year=year, month=month, day=day)


def add_days_local(dt: datetime, days: int) -> datetime:
    """Add days in local time to preserve wall-clock scheduling semantics."""
    return dt + timedelta(days=days)


def replace_day_safe(dt: datetime, target_day: int) -> datetime:
    """Set day-of-month, clamping down to the last valid day if needed."""
    day = target_day
    while day >= 28:
        try:
            return dt.replace(day=day)
        except ValueError:
            day -= 1
    return dt.replace(day=day)
