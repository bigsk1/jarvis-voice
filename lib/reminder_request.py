"""Pure checks of human notification clauses before and after reminder writes.

Schedules are separated from reminder content before interpretation. Explicit
conjunctions retain their subjects and may inherit a preceding date. Unknown
wording with visible time constraints requires validation or clarification;
appointment/event content is never silently treated as a notification clock.
This remains a bounded grammar, not a general natural-language interpreter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from lib.reminder_schedule import ScheduleError, UnsupportedScheduleError, resolve_schedule

_INTRO = re.compile(
    r"\b(?:remind\s+me|(?:set|create|add)\s+(?:me\s+)?"
    r"(?:(?:a|one|two|three|\d+)\s+)?reminders?)\b\s*:?", re.IGNORECASE,
)
_CONJOINED_INTRO = re.compile(
    r"\b(?:and(?:\s+then)?|then|also)\s+(?:(?:a|another)\s+)?reminder\b\s*:?",
    re.IGNORECASE,
)
_CONTENT = re.compile(r"\b(?:to|about|that)\b", re.IGNORECASE)
_JOIN = re.compile(r"\s*(?:,?\s+and(?:\s+then)?|,?\s+then|;|,?\s+also)\s+", re.IGNORECASE)
_DATE_ANCHOR = re.compile(
    r"^(?:on\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|today|tomorrow|tonight|"
    r"next|this|coming|upcoming|in|every|daily|weekly|monthly|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|day\s+after\s+tomorrow)\b"
    r"|^\d{4}-\d{2}-\d{2}\b", re.IGNORECASE,
)
_CLOCK_ONLY = re.compile(
    r"^(?:at\s+)?(?:\d{1,2}(?::\d{2})?\s*(?:a\.?\s*m\.?|p\.?\s*m\.?)|"
    r"\d{1,2}:\d{2}|noon|midnight|midday)$", re.IGNORECASE,
)
_CLOCK_START = re.compile(
    r"^(?:at\s+)?(?:\d{1,2}(?::\d{2})?(?:\s*[ap]\.?\s*m\b|\b)|"
    r"noon\b|midnight\b|midday\b|half\b|quarter\b)", re.IGNORECASE,
)
_CONTENT_AMBIGUITY = re.compile(
    r"\b(?:about|for|before|after|during|until|appointment|meeting|flight|event)\b",
    re.IGNORECASE,
)
_ACTION_START = re.compile(
    r"^(?:buy|call|update|pick|send|pay|check|take|book|order|collect|renew|visit|"
    r"meet|bring|finish|start|stop|review|submit|leave|feed|walk|water)\b", re.IGNORECASE,
)
_CLOCK_EVIDENCE = re.compile(
    r"\b(?:\d{1,2}(?::\d{2})?\s*[ap]\.?\s*m|\d{1,2}:\d{2}|noon|midnight|midday)\b",
    re.IGNORECASE,
)
_TIMEZONE_REPLY = re.compile(
    r"(?:(?:use\s+)|(?:(?:my\s+)?(?:timezone|time\s+zone)\s*(?:is|:)?\s*))?"
    r"(?P<zone>[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+)+|UTC|GMT|Pacific|Mountain|Central|Eastern|PT|MT|CT|ET)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Clause:
    expression: str
    subject: str
    resolved: tuple[datetime | list[datetime], str | None] | None
    error: str | None = None


def _clean(value: str) -> str:
    return " ".join(value.strip(" \t\r\n.,!?;:").casefold().split())


def _subject(value: str) -> str:
    return " ".join(word for word in re.findall(r"\w+", value.casefold())
                    if word not in {"a", "an", "the"})


def _signature(result: tuple[datetime | list[datetime], str | None]):
    targets, recurrence = result
    values = targets if isinstance(targets, list) else [targets]
    return tuple(value.astimezone(timezone.utc).replace(microsecond=0) for value in values), recurrence


def _looks_like_schedule(value: str) -> bool:
    return bool(_DATE_ANCHOR.search(value) or _CLOCK_START.search(value))


def _resolved_clause(expression: str, subject: str, now: datetime) -> _Clause | None:
    expression = re.sub(r"^for\s+", "", expression.strip(" \t\r\n.,!?;:"), flags=re.I)
    if not expression:
        return None
    try:
        return _Clause(expression, _clean(subject), resolve_schedule(expression, now=now))
    except UnsupportedScheduleError:
        return _Clause(expression, _clean(subject), None) if _looks_like_schedule(expression) else None
    except ScheduleError as exc:
        return _Clause(expression, _clean(subject), None, str(exc))


def _prefix_clause(segment: str, now: datetime) -> _Clause | None:
    for boundary in _CONTENT.finditer(segment):
        expression = segment[:boundary.start()].strip()
        if not expression:
            return None
        if boundary[0].lower() == "to" and expression.lower().endswith("quarter"):
            continue
        clause = _resolved_clause(expression, segment[boundary.end():], now)
        if clause is not None:
            return clause
    # Longest complete schedule wins over its shorter default-hour prefix.
    for boundary in reversed(list(re.finditer(r"\s+", segment))):
        subject = segment[boundary.end():].strip()
        if _ACTION_START.search(subject):
            clause = _resolved_clause(segment[:boundary.start()], subject, now)
            if clause and clause.resolved is not None:
                return clause
    return _resolved_clause(segment, "", now)


def _trailing_clause(segment: str, now: datetime) -> _Clause | None:
    body = re.sub(r"^\s*to\s+", "", segment, count=1, flags=re.I)
    if body == segment:
        return None
    for match in re.finditer(r"\S+", body):
        expression, subject = body[match.start():].strip(), body[:match.start()].strip()
        if not subject or not _looks_like_schedule(expression):
            continue
        clause = _resolved_clause(expression, subject, now)
        if clause is None or (clause.resolved is None and clause.error is None):
            continue
        if _CONTENT_AMBIGUITY.search(subject):
            return _Clause(expression, _clean(subject), None,
                           "Clarify the notification time separately from the appointment or event time")
        return clause
    return None


def _single_clause(segment: str, now: datetime) -> _Clause | None:
    segment = re.sub(r"\s+(?:and|then|also)\s*$", "", segment.strip(), flags=re.I)
    return _prefix_clause(segment, now) or _trailing_clause(segment, now)


def _inherit_clock(previous: _Clause, clause: _Clause, now: datetime) -> _Clause:
    if (previous.resolved is None or clause.resolved is None
            or not _CLOCK_ONLY.fullmatch(clause.expression)
            or not (_DATE_ANCHOR.search(previous.expression)
                    or "(same day and repetition as " in previous.expression)):
        return clause
    targets, recurrence = previous.resolved
    days = targets if isinstance(targets, list) else [targets]
    clock_targets = clause.resolved[0]
    if isinstance(clock_targets, list):
        return clause
    dates = []
    for day in days:
        # An unqualified shared clock is a wall time in the preceding clause's
        # zone, not an instant to convert from the app's default timezone.
        clock = clock_targets.strftime("%H:%M")
        try:
            target, _ = resolve_schedule(f"{day.date().isoformat()} at {clock}", now=now.astimezone(day.tzinfo))
        except ScheduleError as exc:
            return _Clause(clause.expression, clause.subject, None, str(exc))
        assert isinstance(target, datetime)
        dates.append(target)
    resolved = (dates if isinstance(targets, list) else dates[0], recurrence)
    return _Clause(f"{clause.expression} (same day and repetition as {previous.expression})",
                   clause.subject, resolved)


def _unresolved_additional_clause(segment: str, now: datetime) -> _Clause | None:
    """Retain a visible second date/clock even when its verb is unfamiliar."""
    if not _looks_like_schedule(segment):
        return None
    for boundary in reversed(list(re.finditer(r"\s+", segment))):
        expression, subject = segment[:boundary.start()], segment[boundary.end():]
        if not subject.strip() or not _CLOCK_EVIDENCE.search(expression):
            continue
        clause = _resolved_clause(expression, subject, now)
        if clause is not None and clause.resolved is not None:
            return _Clause(expression, _clean(subject), None,
                           "An additional notification needs a clear separation between its schedule and subject")
    return None


def _request_clauses(original_query: str, now: datetime) -> list[_Clause]:
    introductions = list(_INTRO.finditer(original_query))
    introductions.extend(match for match in _CONJOINED_INTRO.finditer(original_query)
                         if _looks_like_schedule(original_query[match.end():].lstrip()))
    introductions.sort(key=lambda match: match.start())
    clauses = []
    for index, introduction in enumerate(introductions):
        end = introductions[index + 1].start() if index + 1 < len(introductions) else len(original_query)
        segment = original_query[introduction.end():end].strip()
        first_content = _CONTENT.search(segment)
        action_content = first_content is not None and first_content[0].lower() == "to"
        unresolved_pieces = {}
        pieces = []
        start = 0
        for join in _JOIN.finditer(segment):
            right = segment[join.end():]
            candidate = _single_clause(right, now)
            if (action_content and (candidate is None or not candidate.subject)
                    and (candidate is None or candidate.resolved is None)):
                candidate = _unresolved_additional_clause(right, now) or candidate
            if (candidate and (candidate.resolved is not None or candidate.subject)
                    and (_looks_like_schedule(right) or right.lower().startswith("to "))):
                pieces.append((segment[start:join.start()], start))
                start = join.end()
                if candidate.error and candidate.error.startswith("An additional notification"):
                    unresolved_pieces[start] = candidate
        pieces.append((segment[start:], start))
        previous = None
        for piece, position in pieces:
            clause = unresolved_pieces.get(position) or _single_clause(piece, now)
            if clause is not None:
                clause = _inherit_clock(previous, clause, now) if previous else clause
                clauses.append(clause)
                previous = clause
    # A trailing subject can apply to several explicitly requested schedules:
    # "Friday at 11am and a reminder Tuesday at 11am to check the report".
    # Only share it when every earlier clause is a complete subjectless plan;
    # independently stated subjects and unresolved schedules keep their guards.
    if (len(clauses) > 1 and clauses[-1].subject and clauses[-1].resolved is not None
            and all(not clause.subject and clause.resolved is not None for clause in clauses[:-1])):
        clauses = [replace(clause, subject=clauses[-1].subject) for clause in clauses]
    return clauses


def _semantic_schedule(result, reference_time: datetime) -> dict[str, Any] | None:
    """Represent a resolved plan for checking recognizable source constraints."""
    targets, recurrence = result
    values = targets if isinstance(targets, list) else [targets]
    first = values[0].astimezone(reference_time.tzinfo)
    schedule: dict[str, Any] = {"time": first.strftime("%H:%M")}
    if isinstance(targets, list):
        offset = (first.date() - reference_time.date()).days
        if offset not in {0, 1}:
            return None
        schedule.update(kind="daily", count=len(values), start_offset=offset)
    elif recurrence == "DAILY":
        schedule.update(kind="daily")
    elif recurrence and recurrence.startswith("WEEKLY:"):
        schedule.update(kind="weekly", weekday=int(recurrence.partition(":")[2]))
    elif recurrence and recurrence.startswith("MONTHLY:"):
        schedule.update(kind="monthly", day=int(recurrence.partition(":")[2]))
    elif recurrence:
        return None
    else:
        schedule.update(kind="date", date=first.date().isoformat())
    return schedule


def _matches(clause: _Clause, actual, now: datetime) -> bool:
    if clause.resolved is not None:
        return _signature(clause.resolved) == _signature(actual)
    semantic = _semantic_schedule(actual, now)
    if semantic is None or clause.error:
        return False
    try:
        checked = resolve_schedule(clause.expression, now=now, schedule=semantic)
    except (ValueError, TypeError, OverflowError):
        return False
    return _signature(checked) == _signature(actual)


def reminder_request_rejection(
    original_query: str, arguments: dict[str, Any], *, reference_time: datetime,
) -> str | None:
    """Reject source constraint loss or ambiguous association before any write.

    The source must come from the trusted entrypoint, never model arguments.
    Completely unrecognized non-temporal wording returns no source verdict;
    visible notification constraints must agree or require clarification.
    """
    if not isinstance(original_query, str) or not isinstance(arguments, dict):
        return None
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("The reminder reference time must be timezone-aware")
    clauses = _request_clauses(original_query, reference_time)
    if not clauses:
        return None
    for clause in clauses:
        if clause.error and clause.error.startswith("An additional notification"):
            return f"The original request needs clarification: {clause.error}"
    try:
        actual = resolve_schedule(arguments.get("when"), now=reference_time, schedule=arguments.get("schedule"))
    except (ValueError, TypeError, OverflowError):
        return None
    if len(clauses) == 1:
        selected = clauses[0]
    else:
        title = _subject(str(arguments.get("title") or ""))
        associated = [clause for clause in clauses if title and _subject(clause.subject) == title]
        if len(associated) == 1:
            selected = associated[0]
        elif associated:
            temporal = [clause for clause in associated if _matches(clause, actual, reference_time)]
            if len(temporal) != 1:
                return "The original request contains multiple reminders with ambiguous schedule association; clarify each notification"
            selected = temporal[0]
        elif not any(clause.subject for clause in clauses):
            temporal = [clause for clause in clauses if _matches(clause, actual, reference_time)]
            if len(temporal) != 1:
                return "The original request contains multiple notification schedules; clarify which reminder this is for"
            selected = temporal[0]
        else:
            return "The original request contains multiple reminders with ambiguous subject association; clarify each notification"
    if selected.error:
        return f"The original request's notification schedule needs clarification: {selected.error}"
    if _matches(selected, actual, reference_time):
        return None
    return (
        "The proposed reminder schedule does not match the original request's notification "
        f"schedule ({selected.expression}). Preserve its date, time, timezone, and repetition."
    )


def reminder_request_timezone(original_query: str, *, reference_time: datetime) -> tzinfo | None:
    """Read a unique human notification timezone or a whole timezone-only reply.

    Content-only mentions and model-generated ``when``/``schedule`` fields never
    authorize an otherwise unconfigured timezone. No timezone or conflicting
    timezone identities returns no verdict, so the caller can request clarification.
    """
    from lib.reminder_schedule import explicit_schedule_timezone

    if not isinstance(original_query, str):
        return None
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("The reminder reference time must be timezone-aware")
    reply = _TIMEZONE_REPLY.fullmatch(original_query.strip(" \t\r\n.!"))
    if reply:
        try:
            return explicit_schedule_timezone(reply["zone"])
        except (ValueError, TypeError, OverflowError):
            return None
    zones = []
    for clause in _request_clauses(original_query, reference_time):
        try:
            zone = explicit_schedule_timezone(clause.expression)
        except (ValueError, TypeError, OverflowError):
            return None
        if zone is not None and zone not in zones:
            zones.append(zone)
    return zones[0] if len(zones) == 1 else None


def _successful_schedule(context: dict, now: datetime):
    result = context.get("result")
    if not isinstance(result, dict) or result.get("ok") is not True:
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    rows = data.get("reminders", [data])
    if isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows):
        values = []
        for row in rows:
            raw = row.get("trigger_time") or row.get("trigger_time_local")
            if not isinstance(raw, str):
                break
            try:
                target = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                break
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            values.append(target)
        if len(values) == len(rows):
            return (values if "reminders" in data else values[0], rows[0].get("recurrence_rule"))
    # Legacy receipts may have IDs/formatted speech but no machine-readable time.
    arguments = context.get("arguments") or {}
    try:
        reference = datetime.fromisoformat(str(data.get("schedule_reference_time")).replace("Z", "+00:00"))
        if reference.tzinfo is not None:
            zone = ZoneInfo(data["schedule_timezone"]) if data.get("schedule_timezone") else now.tzinfo
            now = reference.astimezone(zone)
    except (ValueError, TypeError, KeyError):
        pass
    try:
        return resolve_schedule(arguments.get("when"), now=now, schedule=arguments.get("schedule"))
    except (ValueError, TypeError, OverflowError):
        return None


def _context_reference(context: dict, fallback: datetime) -> datetime:
    result = context.get("result") or {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    try:
        reference = datetime.fromisoformat(str(data.get("schedule_reference_time")).replace("Z", "+00:00"))
        if reference.tzinfo is not None:
            zone = ZoneInfo(data["schedule_timezone"]) if data.get("schedule_timezone") else fallback.tzinfo
            return reference.astimezone(zone)
    except (ValueError, TypeError, KeyError):
        pass
    return fallback


def reminder_request_coverage_warning(
    original_query: str, conversation_context: list[dict], *, reference_time: datetime,
) -> str | None:
    """Report explicitly requested notifications absent from successful receipts.

    Do not recover after a reminder cancellation/update or a workflow whose
    mutations are not represented here. Only independently resolved source
    clauses establish missing coverage; unknown wording is not a missing date.
    """
    attempts = [ctx for ctx in conversation_context if ctx.get("tool") == "create_reminder"]
    if not attempts or any(
        ctx.get("tool") == "workflow" or (
            "reminder" in str(ctx.get("tool")) and ctx.get("tool") not in {
                "create_reminder", "list_reminders", "reminder_completion_guard",
            }
        ) for ctx in conversation_context
    ):
        return None
    clauses = _request_clauses(original_query, reference_time)
    completed = []
    for context in attempts:
        reference = _context_reference(context, reference_time)
        completed.append((context, _successful_schedule(context, reference), reference,
                          _request_clauses(original_query, reference)))
    missing = []
    for index, clause in enumerate(clauses):
        if clause.resolved is None or clause.error:
            continue
        found = False
        for context, actual, reference, local_clauses in completed:
            if actual is None:
                continue
            title = _subject(str((context.get("arguments") or {}).get("title") or ""))
            local_clause = local_clauses[index] if len(local_clauses) == len(clauses) else clause
            if ((len(clauses) == 1 or not clause.subject or title == _subject(clause.subject))
                    and _matches(local_clause, actual, reference)):
                found = True
                break
        if not found:
            missing.append(f"{clause.subject or 'reminder'} ({clause.expression})")
    if not missing:
        return None
    shown = "; ".join(missing[:3])
    remainder = f"; {len(missing) - 3} more" if len(missing) > 3 else ""
    return f"Requested reminder not confirmed: {shown}{remainder}. Saved reminders have not been changed."
