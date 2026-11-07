"""Check saved reminder receipts against their deterministic scheduling inputs."""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from lib.reminder_schedule import resolve_schedule


def _aware_iso(value: Any, *, naive_utc: bool = False) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc) if naive_utc else None
    return parsed


def _display(value: datetime, zone: tzinfo) -> str:
    return value.astimezone(zone).strftime("%A, %B %d, %Y at %I:%M %p %Z")


def reminder_schedule_warning(
    arguments: dict[str, Any], result: dict[str, Any], *, local_timezone: tzinfo,
) -> str | None:
    """Report a proven receipt mismatch without changing any saved reminder.

    Re-resolve the actual tool arguments at the recorded pre-parse clock rather
    than trusting model commentary or using a later wall clock. Legacy receipts
    without that clock cannot safely be checked for relative schedules.
    """
    data = result.get("data")
    if not result.get("ok") or not isinstance(data, dict):
        return None
    reference = _aware_iso(data.get("schedule_reference_time"))
    if reference is None:
        return None
    zone = local_timezone
    if isinstance(data.get("schedule_timezone"), str):
        try:
            zone = ZoneInfo(data["schedule_timezone"])
        except (ValueError, KeyError):
            return None
    try:
        expected, recurrence = resolve_schedule(
            arguments.get("when"),
            now=reference.astimezone(zone),
            schedule=arguments.get("schedule"),
        )
    except (ValueError, TypeError, OverflowError):
        # An unsupported/malformed input is not evidence of a particular date.
        return None
    expected_times = expected if isinstance(expected, list) else [expected]
    rows = data.get("reminders", [data])
    if not isinstance(rows, list) or not expected_times:
        return None
    if len(rows) != len(expected_times):
        return (
            "Warning: the saved reminders do not match the requested schedule. "
            f"Expected {len(expected_times)} reminders; the receipt reports {len(rows)}. "
            "The saved reminders have not been changed."
        )
    for index, (expected_time, row) in enumerate(zip(expected_times, rows, strict=True), 1):
        if not isinstance(row, dict):
            continue
        for field in ("trigger_time", "trigger_time_local"):
            actual_time = _aware_iso(row.get(field), naive_utc=field == "trigger_time")
            if actual_time is None:
                continue
            expected_utc = expected_time.astimezone(timezone.utc).replace(microsecond=0)
            actual_utc = actual_time.astimezone(timezone.utc).replace(microsecond=0)
            if actual_utc != expected_utc:
                label = f"reminder {index}" if len(rows) > 1 else "reminder"
                return (
                    f"Warning: the saved {label} time does not match the requested schedule. "
                    f"Requested: {_display(expected_time, zone)}. "
                    f"The saved receipt reports: {_display(actual_time, zone)}. "
                    "The saved reminders have not been changed."
                )
        if row.get("recurrence_rule") != recurrence or (
            "recurring" in row and bool(row["recurring"]) != bool(recurrence)
        ):
            return (
                "Warning: the saved reminder recurrence does not match the requested schedule. "
                f"Requested: {recurrence or 'one-time'}. "
                f"The saved receipt reports: {row.get('recurrence_rule') or 'one-time'}. "
                "The saved reminders have not been changed."
            )
    return None
