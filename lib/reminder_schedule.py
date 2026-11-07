"""Resolve reminder schedules without silently discarding date or time qualifiers.

The natural-language grammar deliberately consumes the complete expression.  A
caller may additionally supply a semantic schedule produced by its existing
language model; recognizable dates and clocks remain independent constraints.
This module has no clock, storage, model, or network side effects.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal
from typing import TypeAlias
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ScheduleResult: TypeAlias = tuple[datetime | list[datetime], str | None]
MAX_EXPRESSION_LENGTH = 1024
MAX_OCCURRENCES = 366
MAX_DELAY_SECONDS = 366 * 10 * 24 * 60 * 60
_US_ZONE_OFFSETS = {
    "pst": -8, "pdt": -7, "mst": -7, "mdt": -6,
    "cst": -6, "cdt": -5, "est": -5, "edt": -4,
}
_REGIONAL_ZONES = {
    "pt": "America/Los_Angeles", "pacific": "America/Los_Angeles",
    "mt": "America/Denver", "mountain": "America/Denver",
    "ct": "America/Chicago", "central": "America/Chicago",
    "et": "America/New_York", "eastern": "America/New_York",
}

_WEEKDAYS = {
    name: index
    for index, names in enumerate(
        (
            ("monday", "mon"), ("tuesday", "tue", "tues"),
            ("wednesday", "wed"), ("thursday", "thu", "thur", "thurs"),
            ("friday", "fri"), ("saturday", "sat"), ("sunday", "sun"),
        )
    )
    for name in names
}
_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("january", "jan"), ("february", "feb"), ("march", "mar"),
            ("april", "apr"), ("may",), ("june", "jun"), ("july", "jul"),
            ("august", "aug"), ("september", "sep", "sept"),
            ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ), start=1,
    )
    for name in names
}
_SMALL_NUMBERS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(), range(21),
    strict=True,
))
_SMALL_NUMBERS.update({
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "a": 1, "an": 1,
})
_ORDINALS = dict(zip(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
    "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth"
    .split(), range(1, 21), strict=True,
))
_WEEKDAY_PATTERN = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_CLOCK_PATTERN = re.compile(
    r"(?<![\w:+-])(?:"
    r"(?P<h12>\d{1,2})(?::(?P<m12>\d{2}))?\s*(?P<ampm>am|pm)\b"
    r"|(?P<h24>\d{1,2}):(?P<m24>\d{2})(?::(?P<s24>\d{2}))?(?![\d:])"
    r"|(?P<named>noon|midday|midnight)\b)"
)
_ISO_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[tT ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?"
    r"(?:[zZ]|[+-]\d{2}:\d{2})?"
)


class ScheduleError(ValueError):
    """A requested schedule cannot be saved safely or without guessing."""


class UnsupportedScheduleError(ScheduleError):
    """The complete expression is outside the deterministic grammar."""


def _future(target: datetime, now: datetime) -> datetime:
    if target.astimezone(timezone.utc) <= now.astimezone(timezone.utc):
        raise ScheduleError("The requested notification time is in the past")
    return target


def _localize(day: date, clock: time, zone: tzinfo) -> datetime:
    """Reject nonexistent and ambiguous wall times rather than choosing a DST fold."""
    naive = datetime.combine(day, clock)
    candidates: dict[datetime, datetime] = {}
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        instant = candidate.astimezone(timezone.utc)
        round_trip = instant.astimezone(zone)
        if round_trip.replace(tzinfo=None) == naive:
            candidates.setdefault(instant, candidate)
    if not candidates:
        raise ScheduleError("That local time does not exist because of a daylight-saving change")
    if len(candidates) > 1:
        raise ScheduleError(
            "That local time occurs twice because of a daylight-saving change; "
            "provide an ISO datetime with an explicit UTC offset"
        )
    return next(iter(candidates.values()))


def _zone(value: str) -> tzinfo:
    if value.lower() in {"utc", "gmt", "z"}:
        return timezone.utc
    if value.lower() in _US_ZONE_OFFSETS:
        return timezone(timedelta(hours=_US_ZONE_OFFSETS[value.lower()]), value.upper())
    if value.lower() in _REGIONAL_ZONES:
        return ZoneInfo(_REGIONAL_ZONES[value.lower()])
    offset = re.fullmatch(r"(?:utc|gmt)?([+-])(\d{2})(?::?(\d{2}))?", value, re.I)
    if offset:
        hour, minute = int(offset[2]), int(offset[3] or 0)
        if hour > 14 or minute > 59 or (hour == 14 and minute):
            raise ScheduleError("Invalid UTC offset")
        delta = timedelta(hours=hour, minutes=minute)
        return timezone(delta if offset[1] == "+" else -delta)
    try:
        return ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ScheduleError("Use an IANA timezone name or an explicit UTC offset") from exc


def _split_zone(expression: str, default: tzinfo) -> tuple[str, tzinfo]:
    match = re.search(
        r"\s+(?:(?:in|timezone|tz)\s+)?\[?(?P<zone>"
        r"[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+)+|(?:UTC|GMT)(?:[+-]\d{2}(?::?\d{2})?)?"
        r"|PST|PDT|MST|MDT|CST|CDT|EST|EDT|PT|MT|CT|ET|Pacific|Mountain|Central|Eastern"
        r"|[+-]\d{2}:\d{2})\]?$", expression, re.I,
    )
    if match:
        return expression[:match.start()].strip(), _zone(match["zone"])
    return expression, default


def explicit_schedule_timezone(when: str) -> tzinfo | None:
    """Return only a timezone explicitly written in the notification schedule.

    This never reads configuration or invents a default.  Fixed-offset values
    are returned as fixed offsets; callers that need an IANA zone must check
    for ``ZoneInfo`` (or UTC) rather than substituting a regional timezone.
    Multiple differing zones are rejected instead of choosing one.
    """
    if not isinstance(when, str) or not when.strip():
        return None
    if len(when) > MAX_EXPRESSION_LENGTH:
        raise ScheduleError("The notification schedule is too long")
    text = re.sub(r"\b(?:please|kindly)\b", "", when, flags=re.I).strip()
    tokens = re.findall(
        r"\b[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+)+\b"
        r"|\b(?:UTC|GMT)(?:[+-]\d{2}(?::?\d{2})?)?\b"
        r"|\b(?:PST|PDT|MST|MDT|CST|CDT|EST|EDT|PT|MT|CT|ET|Pacific|Mountain|Central|Eastern)\b",
        text, re.I,
    )
    zones = [_zone(token) for token in tokens]
    for iso in _ISO_PATTERN.finditer(text):
        try:
            parsed = datetime.fromisoformat(iso[0].upper())
        except ValueError as exc:
            raise ScheduleError("Invalid explicit ISO notification timezone") from exc
        if parsed.tzinfo is not None:
            zones.append(parsed.tzinfo)
    stripped, suffix_zone = _split_zone(text, timezone.utc)
    if stripped != text:
        zones.append(suffix_zone)
    if not zones:
        return None
    first = zones[0]
    if any(zone != first for zone in zones[1:]):
        # UTC is commonly represented both as ZoneInfo("UTC") and timezone.utc.
        if not all(str(zone).upper() in {"UTC", "GMT"} for zone in zones):
            raise ScheduleError("The notification schedule contains conflicting timezones")
    return first


def _ordinal_number(value: int) -> str:
    suffix = "th" if 10 <= value % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _number_words(text: str) -> str:
    # Number words are replaced only when a run forms a complete small number.
    text = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", text)
    # Compound ordinals must be handled before their cardinal prefix is replaced.
    text = re.sub(
        r"\b(twenty|thirty) (first|second|third|fourth|fifth|sixth|seventh|eighth|ninth)\b",
        lambda match: _ordinal_number(_SMALL_NUMBERS[match[1]] + _ORDINALS[match[2]]), text,
    )
    number_tokens = "|".join((*_SMALL_NUMBERS, "hundred", "thousand"))
    pattern = rf"\b(?:{number_tokens})(?:\s+(?:{number_tokens}))*\b"

    def convert(match: re.Match[str]) -> str:
        words = match[0].split()
        # An indefinite article before a non-number is left alone ("in a row").
        if words == ["a"] and text[match.end():].lstrip().startswith("row"):
            return match[0]
        def small(parts: list[str]) -> int:
            if not parts:
                return 0
            if len(parts) == 1 and parts[0] in _SMALL_NUMBERS:
                return _SMALL_NUMBERS[parts[0]]
            if len(parts) == 2 and parts[0] in _SMALL_NUMBERS and parts[1] in _SMALL_NUMBERS:
                tens, ones = _SMALL_NUMBERS[parts[0]], _SMALL_NUMBERS[parts[1]]
                if tens >= 20 and tens % 10 == 0 and 1 <= ones <= 9:
                    return tens + ones
            raise ScheduleError("Invalid number words in the notification schedule")

        total = 0
        if "thousand" in words:
            if words.count("thousand") != 1:
                raise ScheduleError("Invalid number words in the notification schedule")
            index = words.index("thousand")
            total = small(words[:index]) * 1000
            words = words[index + 1:]
        if "hundred" in words:
            if words.count("hundred") != 1:
                raise ScheduleError("Invalid number words in the notification schedule")
            index = words.index("hundred")
            hundreds = small(words[:index])
            if not 1 <= hundreds <= 9:
                raise ScheduleError("Invalid number words in the notification schedule")
            total += hundreds * 100
            words = words[index + 1:]
        return str(total + small(words))

    text = re.sub(pattern, convert, text)
    for word, number in _ORDINALS.items():
        if word == "second":
            # "Second" is also the smallest relative-duration unit.
            text = re.sub(rf"\b({_MONTH_PATTERN}|the) second\b", rf"\1 {_ordinal_number(number)}", text)
            text = re.sub(rf"\bsecond (of )?({_MONTH_PATTERN})\b", rf"{_ordinal_number(number)} \1\2", text)
            text = re.sub(r"\bsecond of (next|this) month\b", r"2nd of \1 month", text)
            text = re.sub(r"\bon second\b", "on 2nd", text)
        else:
            text = re.sub(rf"\b{word}\b", _ordinal_number(number), text)
    text = re.sub(r"\b(thirtieth)\b", "30th", text)
    return text


def _spoken_clock_minutes(text: str) -> str:
    hour_words = "|".join(
        word for word, value in _SMALL_NUMBERS.items() if 0 <= value <= 20 and word not in {"a", "an"}
    )
    ones = "|".join(word for word, value in _SMALL_NUMBERS.items() if 1 <= value <= 9 and word not in {"a", "an"})
    teens = "|".join(word for word, value in _SMALL_NUMBERS.items() if 10 <= value <= 19)
    minute_words = rf"(?:(?:twenty|thirty|forty|fifty)(?:[ -](?:{ones}))?|{teens}|oh[ -](?:{ones}))"

    def convert(match: re.Match[str]) -> str:
        tail = text[match.end():]
        if re.match(r"\s*(?:minutes?|hours?|days?|weeks?|seconds?)\b", tail):
            return match[0]
        hour = int(match[1]) if match[1].isdigit() else _SMALL_NUMBERS[match[1]]
        if hour <= 12 and not re.match(r"\s*(?:am|pm)\b", tail) and _daypart(text) is None:
            raise ScheduleError("Please specify AM or PM for the notification clock")
        minute_parts = match[2].replace("-", " ").split()
        minute = sum(_SMALL_NUMBERS[word] for word in minute_parts if word != "oh")
        return f"{hour}:{minute:02d}"

    return re.sub(rf"\b({hour_words}|\d{{1,2}}) ({minute_words})\b", convert, text)


def _normalize(expression: str) -> str:
    expression = expression.lower().strip()
    expression = re.sub(r"\b([ap])\s*\.?\s*m\.?(?![a-z])", r"\1m", expression)
    expression = re.sub(r"\bmid-day\b", "midday", expression)
    expression = _spoken_clock_minutes(expression)
    expression = _number_words(expression)
    expression = re.sub(r"(?<![\w.])\.(\d+)\b", r"0.\1", expression)
    unit = r"weeks?|days?|hours?|minutes?|seconds?"
    fractions = {"half": Decimal("0.5"), "quarter": Decimal("0.25")}
    expression = re.sub(
        rf"\b(\d+(?:\.\d+)?)\s+({unit})\s+and\s+(?:1\s+)?(half|quarter)\b",
        lambda match: f"{Decimal(match[1]) + fractions[match[3]]} {match[2]}", expression,
    )
    expression = re.sub(
        rf"\b(\d+)\s+and\s+(?:1\s+)?(half|quarter)\s+({unit})\b",
        lambda match: f"{Decimal(match[1]) + fractions[match[2]]} {match[3]}", expression,
    )
    expression = re.sub(rf"\bhalf\s+(?:1\s+)?({unit})\b", r"0.5 \1", expression)
    expression = re.sub(
        rf"\b(?:1\s+)?quarter\s+(?:of\s+)?(?:1\s+)?({unit})\b", r"0.25 \1", expression,
    )
    def clock_idiom(match: re.Match[str]) -> str:
        hour = int(match[3])
        if not 1 <= hour <= 12:
            raise ScheduleError("Invalid 12-hour clock time")
        hour = hour % 12 + (12 if match[4] == "pm" else 0)
        minutes = 30 if match[1] == "half" else 15
        value = hour * 60 + (minutes if match[2] == "past" else -minutes)
        if value < 0:
            raise ScheduleError("A clock phrase crossing midnight requires an explicit date and time")
        return f"{value // 60:02d}:{value % 60:02d}"

    expression = re.sub(
        r"\b(?:1 )?(half|quarter) (past|to) (\d{1,2})\s*(am|pm)\b", clock_idiom, expression,
    )
    expression = re.sub(r"\beveryday\b", "every day", expression)
    expression = re.sub(r"\b(?:please|kindly)\b", "", expression)
    expression = expression.replace("@", " at ").replace(",", " ")
    expression = re.sub(r"\s+", " ", expression).strip()
    return _normalize_clock_constraints(expression)


def _daypart(text: str) -> str | None:
    parts = {"night" if match[0] == "tonight" else match[0] for match in re.finditer(
        r"\b(?:morning|afternoon|evening|night|tonight)\b", text,
    )}
    if len(parts) > 1:
        raise ScheduleError("The notification schedule contains conflicting parts of the day")
    return next(iter(parts), None)


def _check_daypart(clock: time, part: str | None) -> None:
    compatible = {
        "morning": clock.hour < 12,
        "afternoon": 12 <= clock.hour <= 18,
        "evening": clock.hour >= 17,
        "night": clock.hour >= 17 or clock.hour < 6,
    }
    if part is not None and not compatible[part]:
        raise ScheduleError("The notification clock conflicts with the stated part of the day")


def _normalize_clock_constraints(text: str) -> str:
    """Make every human-stated clock a checked constraint, including bare hours.

    A model-supplied structured clock cannot supply a missing human AM/PM choice.
    Date numbers, duration quantities, ISO offsets and existing explicit clocks
    are masked before looking for otherwise-unconsumed numeric clock tokens.
    """
    without_dates = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", _ISO_PATTERN.sub("", text))
    if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", without_dates):
        raise ScheduleError("Ambiguous numeric dates require an explicit YYYY-MM-DD date")
    if re.match(r"^(?:in|after)\b", text) and re.search(
        r"\b(?:half|halves|quarter|quarters)\b", text,
    ) and not re.search(r"\b(?:half|quarter) (?:past|to)\b", text):
        raise ScheduleError("The complete fractional duration was not understood")
    part = _daypart(text)
    saw_clock = False

    def clock(hour: int, minute: int = 0, second: int = 0, *, meridiem: str | None = None,
              explicit_24: bool = False) -> time:
        if minute > 59 or hour > 23:
            raise ScheduleError("Invalid notification clock time")
        if meridiem is not None:
            if not 1 <= hour <= 12:
                raise ScheduleError("Invalid 12-hour clock time")
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        elif not explicit_24 and 1 <= hour <= 12:
            if part is None or (part == "night" and 1 <= hour <= 5):
                raise ScheduleError("Please specify AM or PM for the notification clock")
            hour = hour % 12 + (0 if part == "morning" or (part == "night" and hour == 12) else 12)
        result = time(hour, minute, second)
        _check_daypart(result, part)
        return result

    def explicit(match: re.Match[str]) -> str:
        nonlocal saw_clock
        saw_clock = True
        value = _clock_from_match(match)
        # A single-digit colon clock can use a stated daypart, while 05:30 and
        # hours above twelve remain explicit 24-hour clocks.
        if match["h24"] and part:
            hour_text = match["h24"]
            value = clock(int(hour_text), value.minute, value.second,
                          explicit_24=len(hour_text) == 2 and hour_text.startswith("0"))
        else:
            _check_daypart(value, part)
        return value.strftime("%H:%M:%S") if value.second else value.strftime("%H:%M")

    text = _CLOCK_PATTERN.sub(explicit, text)

    def idiom(match: re.Match[str]) -> str:
        nonlocal saw_clock
        saw_clock = True
        anchor = clock(int(match[3]), meridiem=match[4])
        delta = 30 if match[1] == "half" else 15
        minutes = anchor.hour * 60 + (delta if match[2] == "past" else -delta)
        if minutes < 0:
            raise ScheduleError("A clock phrase crossing midnight requires an explicit date and time")
        value = time(minutes // 60, minutes % 60)
        _check_daypart(value, part)
        return value.strftime("%H:%M")

    text = re.sub(r"\b(?:1 )?(half|quarter) (past|to) (\d{1,2})(?![\d:])(?:\s*(am|pm))?\b", idiom, text)

    def oclock(match: re.Match[str]) -> str:
        nonlocal saw_clock
        saw_clock = True
        return clock(int(match[1]), meridiem=match[2],
                     explicit_24=len(match[1]) == 2 and match[1].startswith("0")).strftime("%H:%M")

    text = re.sub(r"\b(\d{1,2})\s*o[’']?\s*clock(?:\s*(am|pm))?\b", oclock, text)
    masked = text
    patterns = (
        _ISO_PATTERN.pattern,
        _CLOCK_PATTERN.pattern,
        r"\b\d{4}-\d{2}-\d{2}\b",
        rf"\b(?:{_MONTH_PATTERN}) \d+(?:st|nd|rd|th)?(?: ?\d{{4}})?\b",
        rf"\b(?:the )?\d+(?:st|nd|rd|th)? (?:of )?(?:{_MONTH_PATTERN})(?: ?\d{{4}})?\b",
        r"\b(?:the )?\d+(?:st|nd|rd|th)\b",
        r"\bthe \d+\b",
        r"\b(?:next|this|every|each) month(?: on)?(?: the)? \d+(?:st|nd|rd|th)?\b",
        r"\b(?:the )?\d+(?:st|nd|rd|th)? of (?:next|this) month\b",
        r"(?<![\w.])\d+(?:\.\d+)?\s*(?:weeks?|days?|hours?|hrs?|minutes?|mins?|seconds?|secs?|[wdhms])\b",
        r"(?:utc|gmt)?[+-]\d{2}(?::?\d{2})?\b",
    )
    for pattern in patterns:
        masked = re.sub(pattern, lambda match: " " * len(match[0]), masked)
    replacements: list[tuple[int, int, str]] = []
    for match in re.finditer(r"(?<![\w.])\d+(?![\w.])", masked):
        saw_clock = True
        value = clock(int(match[0]), explicit_24=len(match[0]) == 2 and match[0].startswith("0"))
        replacements.append((match.start(), match.end(), value.strftime("%H:%M")))
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    if re.search(r"\b(?:half|quarter) (?:past|to)\b", text):
        raise ScheduleError("Please specify the complete notification clock and AM or PM")
    if saw_clock and part:
        text = re.sub(r"\b(?:every|each) (?:morning|afternoon|evening|night)\b", "every day", text)
        text = re.sub(r"\bthis (?:morning|afternoon|evening|night)\b", "today", text)
        text = re.sub(r"\b(?:in|during) (?:the )?(?:morning|afternoon|evening|night)\b", "", text)
        text = re.sub(r"\b(?:morning|afternoon|evening|night)\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _clock_from_match(match: re.Match[str]) -> time:
    if match["named"]:
        return time(0 if match["named"] == "midnight" else 12)
    if match["h12"]:
        hour, minute = int(match["h12"]), int(match["m12"] or 0)
        if not 1 <= hour <= 12 or minute > 59:
            raise ScheduleError("Invalid 12-hour clock time")
        return time(hour % 12 + (12 if match["ampm"] == "pm" else 0), minute)
    try:
        return time(int(match["h24"]), int(match["m24"]), int(match["s24"] or 0))
    except ValueError as exc:
        raise ScheduleError("Invalid 24-hour clock time") from exc


def _extract_clock(text: str, default_hour: int) -> tuple[str, time, bool]:
    aliases = re.search(r"\s*\(([^()]+)\)$", text)
    alias_clock: time | None = None
    if aliases:
        alias_match = _CLOCK_PATTERN.fullmatch(aliases[1])
        if alias_match:
            alias_clock = _clock_from_match(alias_match)
            text = text[:aliases.start()].strip()
    matches = list(_CLOCK_PATTERN.finditer(text))
    if len(matches) > 1:
        raise ScheduleError("The notification schedule contains multiple clock times")
    if not matches:
        if alias_clock is not None:
            raise ScheduleError("A clock alias requires a primary notification time")
        return text, time(default_hour), False
    match = matches[0]
    clock = _clock_from_match(match)
    if alias_clock is not None and alias_clock != clock:
        raise ScheduleError("Conflicting notification clock times")
    before, after = text[:match.start()].strip(), text[match.end():].strip()
    before = re.sub(r"\bat$", "", before).strip()
    if not before:
        after = re.sub(r"^on\s+", "", after)
    return " ".join(part for part in (before, after) if part), clock, True


def _bounded_daily(text: str, *, partial: bool = False) -> tuple[int, bool] | None:
    patterns = (
        (r"every day (?:for )?(?:the )?next (\d+) (days?|weeks?)", True),
        (r"every day for (\d+) (days?|weeks?)", True),
        (r"(?:for )?(?:the )?next (\d+) (days?)", False),
        (r"(\d+) (days?) in a row", False),
        (r"for (?:the )?(?:next )?(\d+) (weeks?)", True),
    )
    for pattern, include_today in patterns:
        match = re.search(rf"\b(?:{pattern})\b", text) if partial else re.fullmatch(pattern, text)
        if match:
            count = int(match[1]) * (7 if match[2].startswith("week") else 1)
            if not 1 <= count <= MAX_OCCURRENCES:
                raise ScheduleError(f"A bounded schedule must contain 1–{MAX_OCCURRENCES} dates")
            return count, include_today
    return None


def _week_span(text: str, now: datetime, clock: time, *, partial: bool = False) -> list[datetime] | None:
    pattern = r"(?:every day|daily) (?:for )?(this|next) week"
    match = re.search(rf"\b(?:{pattern})\b", text) if partial else re.fullmatch(pattern, text)
    if not match:
        return None
    assert now.tzinfo is not None
    if match[1] == "next":
        offset, count = 7 - now.weekday(), 7
    else:
        today_future = datetime.combine(now.date(), clock) > now.replace(tzinfo=None)
        offset = 0 if today_future else 1
        count = 7 - now.weekday() - offset
        if not count:
            raise ScheduleError("There are no future occurrences remaining this week")
    return [
        _localize(now.date() + timedelta(days=offset + index), clock, now.tzinfo)
        for index in range(count)
    ]


def _duration(text: str, now: datetime) -> datetime | None:
    if text.startswith("after "):
        text = "in " + text[6:]
    from_now = re.fullmatch(r"(.+?) from now", text)
    if from_now:
        text = "in " + from_now[1]
    if not text.startswith("in "):
        return None
    body = text[3:]
    units = {
        "week": 604800, "weeks": 604800, "w": 604800,
        "day": 86400, "days": 86400, "d": 86400,
        "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600, "h": 3600,
        "minute": 60, "minutes": 60, "min": 60, "mins": 60, "m": 60,
        "second": 1, "seconds": 1, "sec": 1, "secs": 1, "s": 1,
    }
    pattern = r"(?<![\w.])(\d+(?:\.\d+)?)\s*(" + "|".join(sorted(units, key=len, reverse=True)) + r")\b"
    position = calendar_days = 0
    seconds = Decimal(0)
    seen: set[int] = set()
    for match in re.finditer(pattern, body):
        separator = body[position:match.start()]
        if separator.strip(" ,") not in {"", "and"}:
            raise UnsupportedScheduleError("The complete relative duration was not understood")
        multiplier = units[match[2]]
        if multiplier in seen:
            raise ScheduleError("A relative duration repeats the same time unit")
        seen.add(multiplier)
        quantity = Decimal(match[1])
        if multiplier >= 86400:
            days = quantity * (multiplier // 86400)
            whole_days = int(days)
            calendar_days += whole_days
            seconds += (days - whole_days) * 86400
        else:
            seconds += quantity * multiplier
        position = match.end()
    if not seen or body[position:].strip():
        raise UnsupportedScheduleError("The complete relative duration was not understood")
    if not 0 < calendar_days * 86400 + seconds <= MAX_DELAY_SECONDS:
        raise ScheduleError("The relative delay must be positive and no more than ten years")
    if seconds != seconds.to_integral_value():
        raise ScheduleError("A reminder delay must resolve to a whole number of seconds")
    # Calendar days/weeks preserve the wall clock; smaller units are elapsed time.
    base = now
    if calendar_days:
        assert now.tzinfo is not None
        base = _localize(now.date() + timedelta(days=calendar_days), now.time(), now.tzinfo)
    return (base.astimezone(timezone.utc) + timedelta(seconds=int(seconds))).astimezone(now.tzinfo)


def _month_date(text: str, now: datetime, clock: time) -> date | None:
    ordinal = re.fullmatch(r"(?:the (\d+)(?:st|nd|rd|th)?|(\d+)(?:st|nd|rd|th))", text)
    if ordinal:
        requested_day = int(ordinal[1] or ordinal[2])
        if not 1 <= requested_day <= 31:
            raise ScheduleError("The day of the month must be between 1 and 31")
        for increment in range(13):
            index = now.year * 12 + now.month - 1 + increment
            year, month = divmod(index, 12)
            month += 1
            if requested_day > calendar.monthrange(year, month)[1]:
                continue
            candidate = date(year, month, requested_day)
            if datetime.combine(candidate, clock) > now.replace(tzinfo=None):
                return candidate
        raise ScheduleError("No valid upcoming day of the month was found")
    day_first_month = re.fullmatch(
        r"(?:the )?(\d+)(?:st|nd|rd|th)? of (next|this) month", text,
    )
    if day_first_month:
        text = f"{day_first_month[2]} month on the {day_first_month[1]}"
    next_month = re.fullmatch(
        r"(next|this) month(?: on)? (?:the )?(\d+)(?:st|nd|rd|th)?", text,
    )
    if next_month:
        month_index = now.year * 12 + now.month - 1 + (next_month[1] == "next")
        try:
            return date(month_index // 12, month_index % 12 + 1, int(next_month[2]))
        except ValueError as exc:
            raise ScheduleError("That day does not exist in the requested month") from exc
    match = re.fullmatch(
        rf"(?P<month>{_MONTH_PATTERN}) (?P<day>\d+)(?:st|nd|rd|th)?"
        r"(?:,? (?P<year>\d{4}))?", text,
    )
    if not match:
        match = re.fullmatch(
            rf"(?:the )?(?P<day>\d+)(?:st|nd|rd|th)? (?:of )?(?P<month>{_MONTH_PATTERN})"
            r"(?:,? (?P<year>\d{4}))?", text,
        )
    if not match:
        return None
    month, day = _MONTHS[match["month"]], int(match["day"])
    year = int(match["year"]) if match["year"] else now.year
    # A yearless February 29 means the next real leap day, never February 28.
    for candidate_year in range(year, min(year + 9, 10000)):
        try:
            candidate = date(candidate_year, month, day)
        except ValueError as exc:
            if not match["year"] and month == 2 and day == 29:
                continue
            raise ScheduleError("Invalid calendar date; explicit dates are never clamped") from exc
        if match["year"] or datetime.combine(candidate, clock) > now.replace(tzinfo=None):
            return candidate
    raise ScheduleError("No valid future calendar date was found")


def _weekday_date(text: str, now: datetime, clock: time) -> date | None:
    week_from = re.fullmatch(
        rf"(?:(\d+) )?weeks? from ((?:(?:this|next|coming|upcoming) )?(?:{_WEEKDAY_PATTERN}))", text,
    )
    if week_from:
        weeks = int(week_from[1] or 1)
        if not 1 <= weeks <= 520:
            raise ScheduleError("A weekday offset must be between one and 520 weeks")
        anchor = _weekday_date(week_from[2], now, clock)
        assert anchor is not None
        return anchor + timedelta(weeks=weeks)
    match = re.fullmatch(rf"(?:(this|next|coming|upcoming) )?({_WEEKDAY_PATTERN})", text)
    if match:
        qualifier, target = match[1], _WEEKDAYS[match[2]]
        # "This Monday" commonly means the upcoming Monday even on a weekend.
        days = (target - now.weekday()) % 7
        if days == 0 and (qualifier == "next" or clock <= now.time().replace(tzinfo=None)):
            days = 7
        return now.date() + timedelta(days=days)
    match = re.fullmatch(
        rf"(?:next week(?: on)? ({_WEEKDAY_PATTERN})|({_WEEKDAY_PATTERN}) next week)", text,
    )
    if match:
        weekday = _WEEKDAYS[match[1] or match[2]]
        return now.date() + timedelta(days=7 - now.weekday() + weekday)
    return None


def _recurring(text: str, now: datetime, clock: time) -> ScheduleResult | None:
    zone = now.tzinfo
    assert zone is not None
    if text in {"every day", "daily", "each day", "every night"}:
        return _localize(now.date() + timedelta(days=1), clock, zone), "DAILY"
    weekly = re.fullmatch(
        rf"(?:(?:every|each) (?:week on )?|weekly(?: on)? )({_WEEKDAY_PATTERN})", text,
    )
    if weekly:
        weekday = _WEEKDAYS[weekly[1]]
        days = (weekday - now.weekday()) % 7 or 7
        return _localize(now.date() + timedelta(days=days), clock, zone), f"WEEKLY:{weekday}"
    monthly = re.fullmatch(
        r"(?:every month(?: on)?|monthly(?: on)?) (?:the )?(\d+)(?:st|nd|rd|th)?", text,
    )
    if monthly:
        day = int(monthly[1])
        if not 1 <= day <= 31:
            raise ScheduleError("The monthly day must be between 1 and 31")
        for increment in (0, 1):
            index = now.year * 12 + now.month - 1 + increment
            year, month = divmod(index, 12)
            month += 1
            candidate_day = min(day, calendar.monthrange(year, month)[1])
            naive = datetime.combine(date(year, month, candidate_day), clock)
            if naive > now.replace(tzinfo=None):
                return _localize(naive.date(), clock, zone), f"MONTHLY:{day}"
    return None


def _parse_natural(expression: str, now: datetime, default_hour: int) -> ScheduleResult:
    assert now.tzinfo is not None
    expression = re.sub(r"\b(?:please|kindly)\b", "", expression, flags=re.I).strip()
    expression, zone = _split_zone(expression, now.tzinfo)
    now = now.astimezone(zone)
    if _ISO_PATTERN.fullmatch(expression):
        try:
            target = datetime.fromisoformat(expression.upper())
        except ValueError as exc:
            raise ScheduleError("Invalid ISO notification datetime") from exc
        if target.tzinfo is None:
            target = _localize(target.date(), target.time(), zone)
        elif abs(target.utcoffset() or timedelta()) > timedelta(hours=14):
            raise ScheduleError("Invalid UTC offset")
        return _future(target, now), None
    text = _normalize(expression)
    # A deadline or interval is not an exact notification instant.  Keep this
    # check before the unsupported-grammar fallback so a semantic interpretation
    # cannot silently turn a bound into its endpoint.  "After a duration" is an
    # exact relative delay only when the complete duration grammar consumes it.
    qualifier_text = re.sub(r"\b(?:the )?day after tomorrow\b", "", text)
    if re.search(
        r"\b(?:before|within|until|between|by|under|over|less than|more than|"
        r"at least|at most|up to|earlier than|later than|no earlier|no later)\b",
        qualifier_text,
    ) or (re.search(r"\bafter\b", qualifier_text) and not text.startswith("after ")):
        raise ScheduleError("That time range or comparison needs an exact notification time")
    without_iso_dates = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", _ISO_PATTERN.sub("", text))
    if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", without_iso_dates):
        raise ScheduleError("Ambiguous numeric dates require an explicit YYYY-MM-DD date")
    try:
        duration = _duration(text, now)
    except UnsupportedScheduleError as exc:
        if text.startswith("after "):
            raise ScheduleError("After must specify one complete relative delay, not a date boundary") from exc
        raise
    if duration is not None:
        return duration, None
    # An ISO datetime annotation must agree as an instant, including its offset.
    annotation = re.search(r"\s*\(([^()]+)\)$", expression)
    if annotation and _ISO_PATTERN.fullmatch(annotation[1]):
        natural = _parse_natural(expression[:annotation.start()], now, default_hour)
        annotated = _parse_natural(annotation[1], now, default_hour)
        if _signature(natural) != _signature(annotated):
            raise ScheduleError("The ISO datetime annotation conflicts with the notification schedule")
        return natural
    date_text, clock, has_clock = _extract_clock(text, default_hour)
    week_dates = _week_span(date_text, now, clock)
    if week_dates is not None:
        return week_dates, None
    bounded = _bounded_daily(date_text)
    if bounded:
        count, include_today = bounded
        today_future = datetime.combine(now.date(), clock) > now.replace(tzinfo=None)
        offset = 0 if include_today and today_future else 1
        return [
            _localize(now.date() + timedelta(days=offset + index), clock, zone)
            for index in range(count)
        ], None
    recurring = _recurring(date_text, now, clock)
    if recurring is not None:
        return recurring
    date_text = re.sub(r"^on\s+", "", date_text)
    if not date_text and has_clock:
        day = now.date()
        if datetime.combine(day, clock) <= now.replace(tzinfo=None):
            day += timedelta(days=1)
    elif date_text in {"today", "tomorrow", "the day after tomorrow", "day after tomorrow"}:
        offset = {"today": 0, "tomorrow": 1}.get(date_text, 2)
        day = now.date() + timedelta(days=offset)
    elif date_text == "tonight":
        if not has_clock:
            clock = time(20)
        if clock.hour == 0:
            day = now.date() + timedelta(days=1)
        elif clock.hour < 12:
            raise ScheduleError("A morning clock time conflicts with tonight")
        else:
            day = now.date()
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
        try:
            day = date.fromisoformat(date_text)
        except ValueError as exc:
            raise ScheduleError("Invalid calendar date") from exc
    else:
        day = _weekday_date(date_text, now, clock) or _month_date(date_text, now, clock)
        if day is None:
            raise UnsupportedScheduleError(
                "The complete notification schedule was not understood; use a semantic "
                "schedule or an ISO datetime with an explicit UTC offset"
            )
    return _future(_localize(day, clock, zone), now), None


def _signature(result: ScheduleResult) -> tuple[tuple[datetime, ...], str | None]:
    targets, recurrence = result
    values = targets if isinstance(targets, list) else [targets]
    return tuple(value.astimezone(timezone.utc) for value in values), recurrence


def _validate_input(when: str, now: datetime, default_hour: int) -> None:
    if not isinstance(when, str) or not when.strip() or len(when) > MAX_EXPRESSION_LENGTH:
        raise ScheduleError(f"when must contain 1–{MAX_EXPRESSION_LENGTH} characters")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ScheduleError("The schedule reference time must include a timezone")
    if type(default_hour) is not int or not 0 <= default_hour <= 23:
        raise ScheduleError("The default reminder hour must be between 0 and 23")


def parse_time_expression(when: str, *, now: datetime, default_hour: int = 10) -> ScheduleResult:
    """Parse a complete supported expression against an explicit aware reference time."""
    _validate_input(when, now, default_hour)
    try:
        result = _parse_natural(when.strip(), now, default_hour)
        _check_recurrence_zone(result, now)
        return result
    except OverflowError as exc:
        raise ScheduleError("The requested date is outside the supported calendar") from exc


def _integer(schedule: dict[str, object], key: str, minimum: int, maximum: int) -> int:
    value = schedule.get(key)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ScheduleError(f"schedule.{key} must be an integer from {minimum} to {maximum}")
    return value


def _structured(schedule: dict[str, object], now: datetime, default_hour: int) -> ScheduleResult:
    fields = {
        "relative": {"delay_seconds"}, "date": {"date", "time"},
        "weekday": {"weekday", "time"}, "daily": {"time", "count", "start_offset"},
        "weekly": {"weekday", "time"}, "monthly": {"day", "time"},
    }
    kind = schedule.get("kind")
    if not isinstance(kind, str) or kind not in fields:
        raise ScheduleError("Unknown semantic schedule kind")
    if set(schedule) - fields[kind] - {"kind", "timezone"}:
        raise ScheduleError("The semantic schedule contains fields that do not apply to its kind")
    zone_name = schedule.get("timezone")
    if zone_name is not None:
        if not isinstance(zone_name, str) or ("/" not in zone_name and zone_name not in {"UTC", "GMT"}):
            raise ScheduleError("schedule.timezone must be an IANA timezone name")
        try:
            zone = ZoneInfo(zone_name)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ScheduleError("schedule.timezone must be an IANA timezone name") from exc
        now = now.astimezone(zone)
    zone = now.tzinfo
    assert zone is not None
    if kind == "relative":
        seconds = _integer(schedule, "delay_seconds", 1, MAX_DELAY_SECONDS)
        return (now.astimezone(timezone.utc) + timedelta(seconds=seconds)).astimezone(zone), None
    clock_value = schedule.get("time", f"{default_hour:02d}:00")
    if not isinstance(clock_value, str) or not re.fullmatch(r"\d{2}:\d{2}", clock_value):
        raise ScheduleError("schedule.time must be a 24-hour HH:MM clock")
    try:
        clock = time.fromisoformat(clock_value)
    except ValueError as exc:
        raise ScheduleError("Invalid semantic schedule clock") from exc
    if kind == "date":
        date_value = schedule.get("date")
        if not isinstance(date_value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
            raise ScheduleError("schedule.date must be YYYY-MM-DD")
        try:
            day = date.fromisoformat(date_value)
        except ValueError as exc:
            raise ScheduleError("Invalid semantic schedule date") from exc
        return _future(_localize(day, clock, zone), now), None
    if kind in {"weekday", "weekly"}:
        weekday = _integer(schedule, "weekday", 0, 6)
        days = (weekday - now.weekday()) % 7
        if days == 0 and (kind == "weekly" or clock <= now.time().replace(tzinfo=None)):
            days = 7
        target = _localize(now.date() + timedelta(days=days), clock, zone)
        return target, f"WEEKLY:{weekday}" if kind == "weekly" else None
    if kind == "monthly":
        day = _integer(schedule, "day", 1, 31)
        result = _recurring(f"every month on the {day}", now, clock)
        assert result is not None
        return result
    if "count" in schedule:
        count = _integer(schedule, "count", 1, MAX_OCCURRENCES)
        offset = _integer(schedule, "start_offset", 0, 1) if "start_offset" in schedule else 0
        if not offset and datetime.combine(now.date(), clock) <= now.replace(tzinfo=None):
            offset = 1
        return [
            _localize(now.date() + timedelta(days=offset + index), clock, zone)
            for index in range(count)
        ], None
    if "start_offset" in schedule:
        raise ScheduleError("schedule.start_offset requires a bounded daily count")
    return _localize(now.date() + timedelta(days=1), clock, zone), "DAILY"


def _check_recognizable_constraints(
    when: str, result: ScheduleResult, now: datetime, default_hour: int,
) -> None:
    """Constrain semantic interpretations of phrasing outside the small grammar."""
    targets, recurrence = result
    values = targets if isinstance(targets, list) else [targets]
    first = values[0]
    assert first.tzinfo is not None
    text, explicit_zone = _split_zone(when, first.tzinfo)
    zone_tokens = re.findall(r"\b[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+)+\b", when)
    zone_tokens += re.findall(r"\b(?:UTC|GMT)(?:[+-]\d{2}(?::?\d{2})?)?\b", when, re.I)
    zone_tokens += re.findall(
        r"\b(?:PST|PDT|MST|MDT|CST|CDT|EST|EDT|PT|MT|CT|ET|Pacific|Mountain|Central|Eastern)\b",
        when, re.I,
    )
    if zone_tokens:
        if len(set(zone_tokens)) != 1:
            raise ScheduleError("The notification schedule contains conflicting timezones")
        explicit_zone = _zone(zone_tokens[0])
    local_first = first.astimezone(explicit_zone)
    normalized = _normalize(text)
    _check_daypart(local_first.time(), _daypart(normalized))
    if re.search(
        r"\b(?:except|unless|until|through|between|either|or|not|ago|yesterday|previous|holidays)\b",
        normalized,
    ):
        raise ScheduleError("That date qualifier requires clarification; no part was ignored")
    if re.search(r"\b(?:fortnightly|biweekly|yearly|annually|weekdays?|weekends?|business days)\b",
                 normalized) or re.search(r"\bevery\s+(?:\d+|other|alternate)\b", normalized):
        raise ScheduleError("That recurrence pattern is not supported; no schedule was guessed")
    bounded = _bounded_daily(normalized, partial=True)
    week_dates = _week_span(normalized, now.astimezone(explicit_zone), local_first.time(), partial=True)
    if week_dates is not None and _signature((week_dates, None)) != _signature(result):
        raise ScheduleError("The semantic schedule conflicts with the requested calendar-week dates")
    if bounded:
        count, include_today = bounded
        if not isinstance(targets, list) or len(targets) != count:
            raise ScheduleError("The semantic schedule conflicts with the bounded occurrence count")
        local_now = now.astimezone(explicit_zone)
        clock = local_first.time()
        today_future = datetime.combine(local_now.date(), clock) > local_now.replace(tzinfo=None)
        expected_offset = 0 if include_today and today_future else 1
        if local_first.date() != local_now.date() + timedelta(days=expected_offset):
            raise ScheduleError("The semantic schedule conflicts with the bounded first date")
    recurring_words = bool(re.search(r"\b(?:every|daily|weekly|monthly|each)\b", normalized))
    if bool(recurring_words or bounded or week_dates) != bool(recurrence or isinstance(targets, list)):
        raise ScheduleError("The semantic schedule conflicts with the requested repetition")
    weekdays = {_WEEKDAYS[m[0]] for m in re.finditer(rf"\b(?:{_WEEKDAY_PATTERN})\b", normalized)}
    if weekdays and (len(weekdays) > 1 or local_first.weekday() not in weekdays):
        raise ScheduleError("The semantic schedule conflicts with the requested weekday")
    if recurring_words and not bounded and week_dates is None:
        expected_frequency = None
        if re.search(r"\b(?:monthly|(?:every|each) month)\b", normalized):
            expected_frequency = "MONTHLY:"
        elif re.search(r"\b(?:weekly|(?:every|each) week)\b", normalized) or weekdays:
            expected_frequency = "WEEKLY:"
        elif re.search(r"\b(?:daily|(?:every|each) day)\b", normalized):
            expected_frequency = "DAILY"
        if expected_frequency and (recurrence is None or not recurrence.startswith(expected_frequency)):
            raise ScheduleError("The semantic schedule conflicts with the requested recurrence frequency")
    if weekdays and not recurrence and not isinstance(targets, list):
        weekday_phrase = re.search(
            rf"\b(?:(?:\d+ )?weeks? from (?:(?:this|next|coming|upcoming) )?(?:{_WEEKDAY_PATTERN})"
            rf"|next week(?: on)? (?:{_WEEKDAY_PATTERN})|(?:{_WEEKDAY_PATTERN}) next week"
            rf"|(?:(?:this|next|coming|upcoming) )?(?:{_WEEKDAY_PATTERN}))\b", normalized,
        )
        assert weekday_phrase is not None
        expected = _weekday_date(weekday_phrase[0], now.astimezone(explicit_zone), local_first.time())
        if expected != local_first.date():
            raise ScheduleError("The semantic schedule conflicts with the requested weekday date")
    clocks = [_clock_from_match(match) for match in _CLOCK_PATTERN.finditer(normalized)]
    if clocks and any(clock != local_first.timetz().replace(tzinfo=None) for clock in clocks):
        raise ScheduleError("The semantic schedule conflicts with the requested notification time")
    for iso in _ISO_PATTERN.finditer(when):
        expected_iso = _parse_natural(iso[0], now, default_hour)
        if _signature(expected_iso) != _signature(result):
            raise ScheduleError("The semantic schedule conflicts with the explicit ISO datetime")
    without_iso_dates = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", _ISO_PATTERN.sub("", normalized))
    if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", without_iso_dates):
        raise ScheduleError("Ambiguous numeric dates require an explicit YYYY-MM-DD date")
    for match in re.finditer(r"\b\d{4}-\d{2}-\d{2}\b", normalized):
        if match[0] != local_first.date().isoformat():
            raise ScheduleError("The semantic schedule conflicts with the explicit date")
    for label, offset in (("day after tomorrow", 2), ("tomorrow", 1), ("today", 0)):
        if label in normalized:
            expected_day = now.astimezone(explicit_zone).date() + timedelta(days=offset)
            if local_first.date() != expected_day:
                raise ScheduleError("The semantic schedule conflicts with the relative date")
            break
    if "next year" in normalized and local_first.year != now.astimezone(explicit_zone).year + 1:
        raise ScheduleError("The semantic schedule conflicts with next year")
    month_qualifier = re.search(r"\b(this|next) month\b", normalized)
    if month_qualifier:
        local_now = now.astimezone(explicit_zone)
        expected_month = local_now.year * 12 + local_now.month - 1 + (month_qualifier[1] == "next")
        if local_first.year * 12 + local_first.month - 1 != expected_month:
            raise ScheduleError("The semantic schedule conflicts with the requested month")
    month_day = re.search(
        rf"\b(?:{_MONTH_PATTERN}) \d+(?:st|nd|rd|th)?(?:,? \d{{4}})?\b", normalized,
    )
    mentioned_months = {
        _MONTHS[match[0]] for match in re.finditer(rf"\b(?:{_MONTH_PATTERN})\b", normalized)
    }
    if mentioned_months and (len(mentioned_months) > 1 or local_first.month not in mentioned_months):
        raise ScheduleError("The semantic schedule conflicts with the requested calendar month")
    ordinal = re.search(r"\b(?:the )?(\d+)(?:st|nd|rd|th)\b", normalized)
    if ordinal and not month_day:
        requested_day = int(ordinal[1])
        if not 1 <= requested_day <= 31:
            raise ScheduleError("Invalid day of the month")
        if recurrence and recurrence.startswith("MONTHLY:"):
            if recurrence != f"MONTHLY:{requested_day}":
                raise ScheduleError("The semantic schedule conflicts with the monthly day")
        elif local_first.day != requested_day:
            raise ScheduleError("The semantic schedule conflicts with the day of the month")
    relative_words = re.match(r"^(?:(?:please|kindly) )?(?:in|after)\b", normalized)
    relative_words = relative_words or re.search(r"\bfrom now\b", normalized)
    if relative_words and not recurring_words and not bounded and week_dates is None:
        if re.search(r"\b(?:half|halves|quarter|quarters)\b", normalized):
            raise ScheduleError("The complete fractional duration was not understood")
        duration_parts = list(re.finditer(
            r"(?<![\w.])\d+(?:\.\d+)?\s*(?:weeks?|days?|hours?|hrs?|minutes?|mins?|seconds?|secs?|[wdhms])\b",
            normalized,
        ))
        if duration_parts:
            if clocks or weekdays:
                raise ScheduleError("A relative delay combined with a date or clock requires clarification")
            complete_duration = "in " + " ".join(match[0] for match in duration_parts)
            expected_duration = _duration(complete_duration, now.astimezone(explicit_zone))
            if expected_duration != first:
                raise ScheduleError("The semantic schedule conflicts with the requested relative delay")
    if re.search(r"\b(?:ist|bst|cet|cest)\b", normalized):
        raise ScheduleError("Use an IANA timezone or explicit UTC offset instead of an abbreviation")
    # Compare any intact month/day phrase, even when surrounded by conversational words.
    if month_day:
        expected = _month_date(month_day[0], now.astimezone(explicit_zone), local_first.time())
        if expected != local_first.date():
            raise ScheduleError("The semantic schedule conflicts with the calendar date")


def _check_recurrence_zone(result: ScheduleResult, now: datetime) -> None:
    targets, recurrence = result
    first = targets[0] if isinstance(targets, list) else targets
    if recurrence and first.tzinfo != now.tzinfo:
        first_offset = first.tzinfo.utcoffset(None) if first.tzinfo is not None else None
        reference_offset = now.tzinfo.utcoffset(None) if now.tzinfo is not None else None
        if first_offset is not None and reference_offset is not None and first_offset == reference_offset:
            return
        raise ScheduleError(
            "Recurring reminders currently require the configured application timezone; "
            "a different recurrence timezone cannot be preserved"
        )


def resolve_schedule(
    when: str, *, now: datetime, default_hour: int = 10,
    schedule: dict[str, object] | None = None,
) -> ScheduleResult:
    """Resolve natural or semantic input, rejecting contradictory visible constraints.

    Known grammar must resolve identically in both representations.  For other
    phrasing, the existing language model owns interpretation, while this module
    checks structured types, future dates, repetition, recognizable qualifiers,
    and DST before a caller may write anything.
    """
    _validate_input(when, now, default_hour)
    if schedule is None:
        return parse_time_expression(when, now=now, default_hour=default_hour)
    if not isinstance(schedule, dict):
        raise ScheduleError("schedule must be an object")
    try:
        interpreted = _structured(schedule, now, default_hour)
    except OverflowError as exc:
        raise ScheduleError("The requested date is outside the supported calendar") from exc
    _check_recurrence_zone(interpreted, now)
    # Removing politeness and separator punctuation is safe only because the
    # semantic schedule is independently validated and then compared in full.
    canonical = re.sub(r"\b(?:please|kindly)\b", "", when, flags=re.I)
    canonical = re.sub(r",", " ", canonical)
    canonical = re.sub(r"\s+", " ", canonical).strip()
    try:
        natural = parse_time_expression(canonical, now=now, default_hour=default_hour)
    except UnsupportedScheduleError:
        _check_recognizable_constraints(when, interpreted, now, default_hour)
    else:
        if _signature(natural) != _signature(interpreted):
            raise ScheduleError("The semantic schedule conflicts with the requested notification schedule")
    return interpreted
