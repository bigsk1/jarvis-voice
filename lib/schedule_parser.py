#!/usr/bin/env python3
"""
Shared schedule parsing for scheduled tasks.

This is intentionally narrower than full cron support. It focuses on the
common natural-language schedules Jarvis should create reliably.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from time_utils import (
    add_days_local,
    add_months_local,
    format_utc_db,
    get_app_timezone,
    get_timezone_by_name,
    parse_utc_timestamp,
    replace_day_safe,
)

WEEKDAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def _normalize_meridiem(text: str) -> str:
    return re.sub(r"\b([ap])\s*\.?\s*m\.?\b", r"\1m", text.lower())


def _normalize_schedule_text(text: str) -> str:
    """Normalize common schedule phrasing variants before parsing."""
    normalized = _normalize_meridiem(text).strip()
    # Treat "everyday" like "every day" so it hits the recurring daily parser.
    normalized = re.sub(r"\beveryday\b", "every day", normalized)
    return normalized


def _word_to_number(word: str) -> int | None:
    mapping = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
        "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
        "fifty": 50, "sixty": 60, "a": 1, "an": 1,
    }
    return mapping.get(word.lower())


def _normalize_time_words(text: str) -> str:
    pattern = (
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
        r"thirty|forty|fifty|sixty|a|an)\s+"
        r"(minute|min|hour|hr|day|week|month)s?\b"
    )

    def repl(match: re.Match[str]) -> str:
        value = _word_to_number(match.group(1))
        return f"{value} {match.group(2)}" if value else match.group(0)

    return re.sub(pattern, repl, text, flags=re.IGNORECASE)


def extract_time_from_expression(text: str, default_hour: int = 10) -> tuple[int, int]:
    text = _normalize_schedule_text(text)
    time_match = re.search(r"(\d+)(?::(\d+))?\s*(am|pm)\b", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        meridiem = time_match.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return hour, minute

    if "noon" in text or "midday" in text:
        return 12, 0
    if "midnight" in text:
        return 0, 0
    return default_hour, 0


def _format_human_time(hour: int, minute: int) -> str:
    display_hour = hour % 12 or 12
    meridiem = "AM" if hour < 12 else "PM"
    return f"{display_hour}:{minute:02d} {meridiem}"


def _format_human_month_day(month: int, day: int) -> str:
    month_name = datetime(2000, month, 1).strftime("%B")
    return f"{month_name} {day}"


def _resolve_absolute_local_datetime(now: datetime, *, month: int, day: int, hour: int, minute: int,
                                     explicit_year: int | None = None) -> datetime:
    year = explicit_year or now.year
    try:
        run_at = now.replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError as e:
        raise ValueError("Invalid calendar date in schedule expression") from e

    if explicit_year is None and run_at <= now:
        try:
            run_at = run_at.replace(year=run_at.year + 1)
        except ValueError as e:
            raise ValueError("Invalid calendar date in schedule expression") from e

    return run_at


def calculate_next_run(schedule_type: str, schedule_expr: dict[str, Any], from_utc: str | None = None,
                       tz_name: str | None = None) -> str | None:
    tz = get_app_timezone() if not tz_name else get_timezone_by_name(tz_name)
    base_local = (
        parse_utc_timestamp(from_utc).astimezone(tz)
        if from_utc
        else datetime.now(tz)
    )

    if schedule_type == "once":
        run_at = schedule_expr["run_at_utc"]
        run_at_dt = parse_utc_timestamp(run_at)
        return format_utc_db(run_at_dt) if run_at_dt > datetime.now(timezone.utc) else None

    if schedule_type == "interval":
        unit = schedule_expr["unit"]
        value = int(schedule_expr["value"])
        if unit == "minutes":
            next_local = base_local + timedelta(minutes=value)
        elif unit == "hours":
            next_local = base_local + timedelta(hours=value)
        elif unit == "days":
            next_local = add_days_local(base_local, value)
        elif unit == "weeks":
            next_local = add_days_local(base_local, value * 7)
        else:
            raise ValueError(f"Unsupported interval unit: {unit}")
        return format_utc_db(next_local)

    hour = int(schedule_expr.get("hour", 10))
    minute = int(schedule_expr.get("minute", 0))

    if schedule_type == "daily":
        next_local = base_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_local <= base_local:
            next_local = add_days_local(next_local, 1)
        return format_utc_db(next_local)

    if schedule_type == "weekly":
        days = schedule_expr.get("days", [])
        if not days:
            raise ValueError("Weekly schedule requires at least one weekday")
        for offset in range(0, 8):
            candidate = add_days_local(base_local, offset).replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate.weekday() in days and candidate > base_local:
                return format_utc_db(candidate)
        candidate = add_days_local(base_local, 7).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return format_utc_db(candidate)

    if schedule_type == "monthly":
        target_day = int(schedule_expr["day"])
        candidate = replace_day_safe(base_local.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0), target_day)
        if candidate <= base_local:
            candidate = replace_day_safe(add_months_local(candidate, 1), target_day)
        return format_utc_db(candidate)

    raise ValueError(f"Unsupported schedule type: {schedule_type}")


def parse_schedule_expression(when: str, tz_name: str | None = None, default_hour: int = 10) -> dict[str, Any]:
    text = _normalize_time_words(_normalize_schedule_text(when))
    tz = get_app_timezone() if not tz_name else get_timezone_by_name(tz_name)
    now = datetime.now(tz)

    if text in {"now", "right now", "immediately", "asap"}:
        run_at_utc = format_utc_db(now)
        return {
            "schedule_type": "once",
            "schedule_expr": {"run_at_utc": run_at_utc},
            "next_run_at": run_at_utc,
            "summary": "Once immediately",
        }

    weekday_match = re.search(r"every\s+weekday(?:\s+at\s+(.+))?$", text)
    if weekday_match:
        hour, minute = extract_time_from_expression(text, default_hour)
        expr = {"days": [0, 1, 2, 3, 4], "hour": hour, "minute": minute}
        return {
            "schedule_type": "weekly",
            "schedule_expr": expr,
            "next_run_at": calculate_next_run("weekly", expr, tz_name=tz.key),
            "summary": f"Every weekday at {_format_human_time(hour, minute)}",
        }

    interval_match = re.search(r"every\s+(\d+)\s+(minute|min|hour|hr|day|week)s?\b", text)
    if interval_match:
        value = int(interval_match.group(1))
        unit_raw = interval_match.group(2)
        unit = {
            "minute": "minutes", "min": "minutes",
            "hour": "hours", "hr": "hours",
            "day": "days", "week": "weeks",
        }[unit_raw]
        expr = {"value": value, "unit": unit}
        next_local = now + (
            timedelta(minutes=value) if unit == "minutes"
            else timedelta(hours=value) if unit == "hours"
            else timedelta(days=value) if unit == "days"
            else timedelta(days=value * 7)
        )
        return {
            "schedule_type": "interval",
            "schedule_expr": expr,
            "next_run_at": format_utc_db(next_local),
            "summary": f"Every {value} {unit}",
        }

    if text.startswith("every day"):
        hour, minute = extract_time_from_expression(text, default_hour)
        expr = {"hour": hour, "minute": minute}
        return {
            "schedule_type": "daily",
            "schedule_expr": expr,
            "next_run_at": calculate_next_run("daily", expr, tz_name=tz.key),
            "summary": f"Every day at {_format_human_time(hour, minute)}",
        }

    for day_name, day_num in WEEKDAY_MAP.items():
        if re.search(
            rf"(?:every\s+(?:week\s+on\s+)?|weekly\s+(?:on\s+)?){day_name}\b",
            text,
        ):
            hour, minute = extract_time_from_expression(text, default_hour)
            expr = {"days": [day_num], "hour": hour, "minute": minute}
            return {
                "schedule_type": "weekly",
                "schedule_expr": expr,
                "next_run_at": calculate_next_run("weekly", expr, tz_name=tz.key),
                "summary": f"Every {day_name.title()} at {_format_human_time(hour, minute)}",
            }

    month_match = re.search(r"every\s+month\s+(?:on\s+)?(?:the\s+)?(\d+)(?:st|nd|rd|th)?", text)
    if month_match:
        day = int(month_match.group(1))
        hour, minute = extract_time_from_expression(text, default_hour)
        expr = {"day": day, "hour": hour, "minute": minute}
        return {
            "schedule_type": "monthly",
            "schedule_expr": expr,
            "next_run_at": calculate_next_run("monthly", expr, tz_name=tz.key),
            "summary": f"Every month on day {day} at {_format_human_time(hour, minute)}",
        }

    if text.startswith("in "):
        delta = timedelta()
        if m := re.search(r"(\d+)\s*(?:minute|min|m)s?", text):
            delta += timedelta(minutes=int(m.group(1)))
        if h := re.search(r"(\d+)\s*(?:hour|hr|h)s?", text):
            delta += timedelta(hours=int(h.group(1)))
        if d := re.search(r"(\d+)\s*(?:day|d)s?", text):
            delta += timedelta(days=int(d.group(1)))
        if delta.total_seconds() <= 0:
            raise ValueError(f"Could not parse schedule expression: {when}")
        run_at = now + delta
        run_at_utc = format_utc_db(run_at)
        return {
            "schedule_type": "once",
            "schedule_expr": {"run_at_utc": run_at_utc},
            "next_run_at": run_at_utc,
            "summary": f"Once at {run_at.strftime('%Y-%m-%d %I:%M %p %Z')}",
        }

    absolute_month_match = re.search(
        r"\b("
        r"january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|"
        r"august|aug|september|sep|sept|october|oct|november|nov|december|dec"
        r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
        text,
        flags=re.IGNORECASE
    )
    if absolute_month_match:
        month_name = absolute_month_match.group(1).lower()
        month = MONTH_MAP[month_name]
        day = int(absolute_month_match.group(2))
        explicit_year = absolute_month_match.group(3)
        hour, minute = extract_time_from_expression(text, default_hour)
        run_at = _resolve_absolute_local_datetime(
            now,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            explicit_year=int(explicit_year) if explicit_year else None,
        )

        run_at_utc = format_utc_db(run_at)
        summary = (
            f"{_format_human_month_day(month, day)}, {run_at.year} at {_format_human_time(hour, minute)}"
            if explicit_year or run_at.year != now.year
            else f"{_format_human_month_day(month, day)} at {_format_human_time(hour, minute)}"
        )
        return {
            "schedule_type": "once",
            "schedule_expr": {"run_at_utc": run_at_utc},
            "next_run_at": run_at_utc,
            "summary": summary,
        }

    slash_date_match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", text)
    if slash_date_match:
        month = int(slash_date_match.group(1))
        day = int(slash_date_match.group(2))
        explicit_year = slash_date_match.group(3)
        month_label = slash_date_match.group(1)
        day_label = slash_date_match.group(2)
        hour, minute = extract_time_from_expression(text, default_hour)

        run_at = _resolve_absolute_local_datetime(
            now,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            explicit_year=int(explicit_year) if explicit_year else None,
        )

        run_at_utc = format_utc_db(run_at)
        date_label = f"{month_label}/{day_label}"
        summary = (
            f"{date_label}/{explicit_year or run_at.year} at {_format_human_time(hour, minute)}"
            if explicit_year or run_at.year != now.year
            else f"{date_label} at {_format_human_time(hour, minute)}"
        )
        return {
            "schedule_type": "once",
            "schedule_expr": {"run_at_utc": run_at_utc},
            "next_run_at": run_at_utc,
            "summary": summary,
        }

    if "tomorrow" in text:
        hour, minute = extract_time_from_expression(text, default_hour)
        run_at = add_days_local(now, 1).replace(hour=hour, minute=minute, second=0, microsecond=0)
        run_at_utc = format_utc_db(run_at)
        return {
            "schedule_type": "once",
            "schedule_expr": {"run_at_utc": run_at_utc},
            "next_run_at": run_at_utc,
            "summary": f"Tomorrow at {_format_human_time(hour, minute)}",
        }

    next_day_match = re.search(r"next\s+([a-z]+)(?:\s+at\s+(.+))?$", text)
    if next_day_match:
        day_name = next_day_match.group(1)
        if day_name in WEEKDAY_MAP:
            target_weekday = WEEKDAY_MAP[day_name]
            days_ahead = (target_weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            hour, minute = extract_time_from_expression(text, default_hour)
            run_at = add_days_local(now, days_ahead).replace(hour=hour, minute=minute, second=0, microsecond=0)
            run_at_utc = format_utc_db(run_at)
            return {
                "schedule_type": "once",
                "schedule_expr": {"run_at_utc": run_at_utc},
                "next_run_at": run_at_utc,
                "summary": f"Next {day_name.title()} at {_format_human_time(hour, minute)}",
            }

    day_of_month = re.search(r"(?:on\s+)?(?:the\s+)?(\d+)(?:st|nd|rd|th)\b", text)
    if day_of_month:
        day = int(day_of_month.group(1))
        hour, minute = extract_time_from_expression(text, default_hour)
        run_at = replace_day_safe(now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0), day)
        if run_at <= now:
            run_at = replace_day_safe(add_months_local(run_at, 1), day)
        run_at_utc = format_utc_db(run_at)
        return {
            "schedule_type": "once",
            "schedule_expr": {"run_at_utc": run_at_utc},
            "next_run_at": run_at_utc,
            "summary": f"Once on day {day} at {_format_human_time(hour, minute)}",
        }

    if re.match(r"^(?:every|weekly)\b", text):
        raise ValueError(f"Could not parse recurring schedule expression: {when}")

    if re.search(r"(\d+)(?::(\d+))?\s*(am|pm)\b", text):
        hour, minute = extract_time_from_expression(text, default_hour)
        run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if run_at <= now:
            run_at = add_days_local(run_at, 1)
        run_at_utc = format_utc_db(run_at)
        return {
            "schedule_type": "once",
            "schedule_expr": {"run_at_utc": run_at_utc},
            "next_run_at": run_at_utc,
            "summary": f"Once at {_format_human_time(hour, minute)}",
        }

    raise ValueError(f"Could not parse schedule expression: {when}")
