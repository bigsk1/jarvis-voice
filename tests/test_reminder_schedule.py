"""Reminder schedule grammar and pre-write semantic consistency regressions."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from lib.reminder_schedule import (
    MAX_OCCURRENCES,
    ScheduleError,
    explicit_schedule_timezone,
    parse_time_expression,
    resolve_schedule,
)

PACIFIC = ZoneInfo("America/Los_Angeles")
SATURDAY = datetime(2026, 11, 7, 8, 30, tzinfo=PACIFIC)


def parsed(when: str, now: datetime = SATURDAY):
    return parse_time_expression(when, now=now)


@pytest.mark.parametrize("prefix", ["", "on ", "next ", "coming ", "upcoming "])
@pytest.mark.parametrize("weekday,day", [
    ("Monday", 9), ("Tuesday", 10), ("Wednesday", 11), ("Thursday", 12),
    ("Friday", 13), ("Saturday", 7), ("Sunday", 8),
])
def test_every_single_weekday_is_respected(prefix, weekday, day):
    result, rule = parsed(f"{prefix}{weekday} at 5pm")
    if prefix == "next " and weekday == "Saturday":
        day = 14
    assert result == datetime(2026, 11, day, 17, tzinfo=PACIFIC)
    assert rule is None


@pytest.mark.parametrize("weekday,day", [
    ("Mon", 9), ("Tue", 10), ("Tues", 10), ("Wed", 11), ("Thu", 12),
    ("Thur", 12), ("Thurs", 12), ("Fri", 13), ("Sat", 7), ("Sun", 8),
])
def test_weekday_aliases_and_clock_first(weekday, day):
    result, _ = parsed(f"5pm on {weekday}")
    assert result == datetime(2026, 11, day, 17, tzinfo=PACIFIC)


@pytest.mark.parametrize("expression,day", [
    ("this Saturday at 5pm", 7), ("this Sunday at 5pm", 8),
    ("next week on Monday at 5pm", 9), ("Monday next week at 5pm", 9),
    ("this Monday at 5pm", 9),
])
def test_this_week_and_next_week_have_explicit_calendar_semantics(expression, day):
    result, _ = parsed(expression)
    assert result == datetime(2026, 11, day, 17, tzinfo=PACIFIC)


@pytest.mark.parametrize("expression", ["today at 7am", "November 1st, 2026 at 5pm"])
def test_explicit_past_qualifiers_are_not_silently_rolled(expression):
    with pytest.raises(ScheduleError, match="past"):
        parsed(expression)


@pytest.mark.parametrize("expression,day,hour,minute", [
    ("today at 5pm", 7, 17, 0), ("tomorrow at 17:15", 8, 17, 15),
    ("the day after tomorrow at noon", 9, 12, 0),
    ("day after tomorrow at midnight", 9, 0, 0),
    ("tonight", 7, 20, 0), ("tonight at midnight", 8, 0, 0),
    ("at 5pm", 7, 17, 0), ("07:00", 8, 7, 0),
    ("tomorrow at 12:05 p.m.", 8, 12, 5),
    ("tomorrow at 12 a m", 8, 0, 0),
    ("tomorrow at noon (12pm)", 8, 12, 0),
    ("tomorrow at 14:00 (2pm)", 8, 14, 0),
    ("tomorrow at five pm", 8, 17, 0),
])
def test_relative_dates_and_clock_variants(expression, day, hour, minute):
    result, rule = parsed(expression)
    assert result == datetime(2026, 11, day, hour, minute, tzinfo=PACIFIC)
    assert rule is None


@pytest.mark.parametrize("expression,expected", [
    ("in thirty minutes", timedelta(minutes=30)),
    ("in one hour and thirty minutes", timedelta(minutes=90)),
    ("in 1h 30m", timedelta(minutes=90)),
    ("in two weeks, three days and four hours", timedelta(days=17, hours=4)),
    ("in twenty-one minutes", timedelta(minutes=21)),
    ("in one hundred minutes", timedelta(minutes=100)),
    ("in one second", timedelta(seconds=1)),
    ("in an hour", timedelta(hours=1)),
])
def test_complete_compound_relative_durations(expression, expected):
    result, rule = parsed(expression)
    assert result == SATURDAY + expected
    assert rule is None


@pytest.mark.parametrize("expression,expected", [
    ("November 9th at 5pm", datetime(2026, 11, 9, 17, tzinfo=PACIFIC)),
    ("9th of November at 5pm", datetime(2026, 11, 9, 17, tzinfo=PACIFIC)),
    ("on the ninth of November at 5pm", datetime(2026, 11, 9, 17, tzinfo=PACIFIC)),
    ("November twenty-first at 5pm", datetime(2026, 11, 21, 17, tzinfo=PACIFIC)),
    ("November second, 2027 at 5pm", datetime(2027, 11, 2, 17, tzinfo=PACIFIC)),
    ("January 5th at 9am", datetime(2027, 1, 5, 9, tzinfo=PACIFIC)),
    ("next month on the 1st at 6pm", datetime(2026, 12, 1, 18, tzinfo=PACIFIC)),
    ("this month on the 30th at 6pm", datetime(2026, 11, 30, 18, tzinfo=PACIFIC)),
    ("2026-11-09 at 17:00", datetime(2026, 11, 9, 17, tzinfo=PACIFIC)),
    ("2026-11-09T17:00:00-08:00", datetime(2026, 11, 9, 17, tzinfo=PACIFIC)),
    ("2026-11-10T01:00:00Z", datetime(2026, 11, 9, 17, tzinfo=PACIFIC)),
    ("2026-11-09T17:00:00", datetime(2026, 11, 9, 17, tzinfo=PACIFIC)),
    ("February 29th at 9am", datetime(2028, 2, 29, 9, tzinfo=PACIFIC)),
    ("on the 15th at 5pm", datetime(2026, 11, 15, 17, tzinfo=PACIFIC)),
    ("the 31st at 5pm", datetime(2026, 12, 31, 17, tzinfo=PACIFIC)),
    ("7th at 5pm", datetime(2026, 11, 7, 17, tzinfo=PACIFIC)),
    ("on the first at 5pm", datetime(2026, 12, 1, 17, tzinfo=PACIFIC)),
])
def test_explicit_calendar_dates_are_real_dates(expression, expected):
    result, rule = parsed(expression)
    assert result == expected
    assert rule is None


@pytest.mark.parametrize("expression,expected,rule", [
    ("every day at 2pm", datetime(2026, 11, 8, 14, tzinfo=PACIFIC), "DAILY"),
    ("daily at 14:05", datetime(2026, 11, 8, 14, 5, tzinfo=PACIFIC), "DAILY"),
    ("every Wednesday at 14:25", datetime(2026, 11, 11, 14, 25, tzinfo=PACIFIC), "WEEKLY:2"),
    ("every week on Wednesday at noon", datetime(2026, 11, 11, 12, tzinfo=PACIFIC), "WEEKLY:2"),
    ("weekly on Sat at 17:00", datetime(2026, 11, 14, 17, tzinfo=PACIFIC), "WEEKLY:5"),
    ("every month on the 7th at 18:00", datetime(2026, 11, 7, 18, tzinfo=PACIFIC), "MONTHLY:7"),
    ("every month on the 31st at noon", datetime(2026, 11, 30, 12, tzinfo=PACIFIC), "MONTHLY:31"),
    ("monthly on the 10th at 14:25", datetime(2026, 11, 10, 14, 25, tzinfo=PACIFIC), "MONTHLY:10"),
])
def test_recurrence_retains_requested_clock_and_storage_contract(expression, expected, rule):
    assert parsed(expression) == (expected, rule)


@pytest.mark.parametrize("expression,count,first_day", [
    ("next 5 days at 2pm", 5, 8),
    ("for the next five days at 2pm", 5, 8),
    ("5 days in a row at 2pm", 5, 8),
    ("every day for five days at 2pm", 5, 7),
    ("every day the next 2 weeks at 5pm", 14, 7),
    ("every day for the next two weeks at 17:00", 14, 7),
    ("every day for five days at 7am", 5, 8),
])
def test_bounded_spans_resolve_all_dates_before_any_storage(expression, count, first_day):
    result, rule = parsed(expression)
    assert isinstance(result, list)
    assert len(result) == count
    assert result[0].day == first_day
    assert result[-1].date() - result[0].date() == timedelta(days=count - 1)
    assert rule is None


@pytest.mark.parametrize("expression", [
    "Monday at 5pm except holidays", "Monday or Tuesday at 5pm", "Monday at 5pm next year",
    "tomorrow at noon about my appointment at 2pm", "tomorrow at noon about an appointment",
    "today tomorrow at 5pm", "in 1 hour tomorrow", "in 1 hour and 2 hours", "in zero minutes",
    "in 100000000000000000000 days", "in -1 hour", "next 0 days", "next 367 days at 5pm",
    "every day for 1000 weeks at 5pm", "every two weeks on Monday at 5pm",
    "every Monday and Tuesday at 5pm", "every weekday at 5pm", "every year at 5pm",
    "2026-02-30 at 5pm", "February 30th at 5pm", "November 31st at 5pm",
    "2026-11-01 at 5pm", "next month on the 32nd at 5pm", "every month on the 0th",
    "tomorrow at 25:00", "tomorrow at 13pm", "tomorrow at 12:99pm", "Monday at 5",
    "tomorrow at 5pm IST", "tomorrow at 5pm BST", "tomorrow at 5pm UTC+25:00",
    "11/09/2026 at 5pm", "11-09-2026 at 5pm", "tonight at 8am", "tomorrow at noon (2pm)",
    "November 9th at 5pm (2026-11-09T17:00:00+02:00)",
])
def test_invalid_or_unconsumed_qualifiers_fail_closed(expression):
    with pytest.raises(ScheduleError):
        parsed(expression)


def test_iso_annotation_is_compared_as_an_instant():
    assert parsed("November 9th at 5pm (2026-11-09T17:00:00-08:00)") == parsed(
        "November 9th at 5pm"
    )


@pytest.mark.parametrize("expression,expected", [
    ("Monday at 5pm America/New_York", datetime(2026, 11, 9, 22, tzinfo=timezone.utc)),
    ("Monday at 5pm in America/New_York", datetime(2026, 11, 9, 22, tzinfo=timezone.utc)),
    ("Monday at 5pm UTC", datetime(2026, 11, 9, 17, tzinfo=timezone.utc)),
    ("Monday at 5pm UTC+02:00", datetime(2026, 11, 9, 15, tzinfo=timezone.utc)),
    ("Monday at 5pm -05:00", datetime(2026, 11, 9, 22, tzinfo=timezone.utc)),
])
def test_named_zones_and_offsets_are_explicit(expression, expected):
    result, _ = parsed(expression)
    assert result == expected


@pytest.mark.parametrize("expression,reference", [
    ("tomorrow at 2:30am", datetime(2027, 3, 13, 10, tzinfo=PACIFIC)),
    ("tomorrow at 1:30am", datetime(2027, 11, 6, 10, tzinfo=PACIFIC)),
    ("every day for 3 days at 2:30am", datetime(2027, 3, 13, 10, tzinfo=PACIFIC)),
    ("every Sunday at 1:30am", datetime(2027, 11, 6, 10, tzinfo=PACIFIC)),
])
def test_dst_gaps_and_ambiguous_folds_require_disambiguation(expression, reference):
    with pytest.raises(ScheduleError, match="daylight-saving"):
        parsed(expression, reference)


def test_explicit_offset_disambiguates_a_dst_fold():
    reference = datetime(2027, 11, 6, 10, tzinfo=PACIFIC)
    early, _ = parsed("2027-11-07T01:30:00-07:00", reference)
    late, _ = parsed("2027-11-07T01:30:00-08:00", reference)
    assert late - early == timedelta(hours=1)


def test_elapsed_duration_crossing_dst_is_not_silently_shortened():
    reference = datetime(2027, 3, 14, 1, 30, tzinfo=PACIFIC)
    result, _ = parsed("in one hour", reference)
    assert result.hour == 3
    assert result.astimezone(timezone.utc) - reference.astimezone(timezone.utc) == timedelta(hours=1)


def test_relative_days_preserve_calendar_clock_while_hours_are_elapsed():
    reference = datetime(2027, 3, 13, 12, tzinfo=PACIFIC)
    day, _ = parsed("in one day", reference)
    hours, _ = parsed("in twenty four hours", reference)
    assert day == datetime(2027, 3, 14, 12, tzinfo=PACIFIC)
    assert hours == datetime(2027, 3, 14, 13, tzinfo=PACIFIC)
    compound, _ = parsed("in one day and two hours", reference)
    assert compound == datetime(2027, 3, 14, 14, tzinfo=PACIFIC)


@pytest.mark.parametrize("expression", [
    "every Monday at 5pm America/New_York", "every day at 5pm UTC",
    "every month on the 15th at 5pm UTC+05:00",
])
def test_foreign_timezone_recurrence_is_rejected_instead_of_losing_its_zone(expression):
    with pytest.raises(ScheduleError, match="configured application timezone"):
        parsed(expression)


def test_finite_daily_dates_can_preserve_an_explicit_foreign_timezone():
    result, rule = parsed("next 3 days at 5pm America/New_York")
    assert isinstance(result, list)
    assert len(result) == 3
    assert result[0] == datetime(2026, 11, 8, 22, tzinfo=timezone.utc)
    assert rule is None


def test_default_time_is_controlled_and_reference_must_be_aware():
    assert parse_time_expression("Monday", now=SATURDAY, default_hour=14)[0] == datetime(
        2026, 11, 9, 14, tzinfo=PACIFIC
    )
    with pytest.raises(ScheduleError, match="timezone"):
        parsed("Monday", SATURDAY.replace(tzinfo=None))
    for when in ("", " " * 20, "Monday " * 200):
        with pytest.raises(ScheduleError):
            parsed(when)


@pytest.mark.parametrize("when,schedule", [
    ("Monday at 5pm", {"kind": "weekday", "weekday": 0, "time": "17:00"}),
    ("in thirty minutes", {"kind": "relative", "delay_seconds": 1800}),
    ("2026-11-09 at 5pm", {"kind": "date", "date": "2026-11-09", "time": "17:00"}),
    ("every Monday at 5pm", {"kind": "weekly", "weekday": 0, "time": "17:00"}),
    ("every month on the 31st at noon", {"kind": "monthly", "day": 31, "time": "12:00"}),
    ("every day at 2pm", {"kind": "daily", "time": "14:00"}),
    ("next 5 days at 2pm", {"kind": "daily", "time": "14:00", "count": 5, "start_offset": 1}),
])
def test_structured_and_natural_schedules_must_agree(when, schedule):
    assert resolve_schedule(when, now=SATURDAY, schedule=schedule) == parsed(when)


@pytest.mark.parametrize("when,schedule", [
    ("Monday at 5pm", {"kind": "weekday", "weekday": 5, "time": "17:00"}),
    ("Monday at 5pm", {"kind": "weekday", "weekday": 0, "time": "16:00"}),
    ("in thirty minutes", {"kind": "relative", "delay_seconds": 3600}),
    ("every Monday at 5pm", {"kind": "weekday", "weekday": 0, "time": "17:00"}),
    ("next 5 days at 2pm", {"kind": "daily", "time": "14:00", "count": 4, "start_offset": 1}),
])
def test_model_interpretation_cannot_override_known_calendar_constraints(when, schedule):
    with pytest.raises(ScheduleError, match="conflict"):
        resolve_schedule(when, now=SATURDAY, schedule=schedule)


def test_semantic_schedule_handles_conversational_phrasing_without_another_model_call():
    result, rule = resolve_schedule(
        "when Monday rolls around, at 5pm", now=SATURDAY,
        schedule={"kind": "weekday", "weekday": 0, "time": "17:00"},
    )
    assert result == datetime(2026, 11, 9, 17, tzinfo=PACIFIC)
    assert rule is None


def test_semantic_bounded_span_preserves_count_from_conversational_phrasing():
    result, rule = resolve_schedule(
        "for the next five days, around two in the afternoon", now=SATURDAY,
        schedule={"kind": "daily", "time": "14:00", "count": 5, "start_offset": 1},
    )
    assert isinstance(result, list)
    assert len(result) == 5
    assert result[0] == datetime(2026, 11, 8, 14, tzinfo=PACIFIC)
    assert rule is None


@pytest.mark.parametrize("when,schedule", [
    ("when Monday rolls around, at 5pm", {"kind": "weekday", "weekday": 1, "time": "17:00"}),
    ("when Monday rolls around, at 5pm", {"kind": "weekday", "weekday": 0, "time": "16:00"}),
    ("whenever tomorrow arrives at 5pm", {"kind": "date", "date": "2026-11-09", "time": "17:00"}),
    ("the alert should be November 9th at 5pm", {"kind": "date", "date": "2026-11-10", "time": "17:00"}),
    ("every two weeks, Monday at 5pm", {"kind": "weekly", "weekday": 0, "time": "17:00"}),
    ("every weekday at 5pm", {"kind": "weekly", "weekday": 0, "time": "17:00"}),
    ("when 11/09/2026 arrives at 5pm", {"kind": "date", "date": "2026-11-09", "time": "17:00"}),
    ("after one hour please", {"kind": "relative", "delay_seconds": 7200}),
    ("when next Monday comes at 5pm except holidays", {"kind": "weekday", "weekday": 0, "time": "17:00"}),
    ("when Monday next year comes at 5pm", {"kind": "weekday", "weekday": 0, "time": "17:00"}),
    ("every day for the next five days please at 2pm", {"kind": "daily", "time": "14:00"}),
    ("every day for the next five days please at 2pm", {"kind": "daily", "time": "14:00", "count": 4}),
    ("every other Monday at 5pm", {"kind": "weekly", "weekday": 0, "time": "17:00"}),
    ("in about 30 minutes", {"kind": "relative", "delay_seconds": 30}),
    ("in 3 hours please", {"kind": "weekday", "weekday": 0, "time": "17:00"}),
    ("tomorrow at 5pm in America/New_York please", {"kind": "date", "date": "2026-11-08", "time": "17:00"}),
    ("this month on the 30th please at 5pm", {"kind": "date", "date": "2026-12-30", "time": "17:00"}),
    ("each Monday, around 5pm", {"kind": "daily", "time": "17:00"}),
    ("tomorrow at 5pm UTC thanks", {"kind": "date", "date": "2026-11-08", "time": "17:00"}),
    ("the 30th of February whenever convenient", {"kind": "date", "date": "2026-11-30", "time": "17:00"}),
])
def test_semantic_fallback_still_checks_recognizable_constraints(when, schedule):
    with pytest.raises(ScheduleError):
        resolve_schedule(when, now=SATURDAY, schedule=schedule)


@pytest.mark.parametrize("schedule", [
    {"kind": "date", "date": "2026-02-30", "time": "17:00"},
    {"kind": "date", "date": "2026-11-01", "time": "17:00"},
    {"kind": "date", "date": "2026-11-09", "time": "25:00"},
    {"kind": "relative", "delay_seconds": -1},
    {"kind": "relative", "delay_seconds": True},
    {"kind": "relative", "delay_seconds": 30, "time": "17:00"},
    {"kind": "weekday", "weekday": 7},
    {"kind": "daily", "count": MAX_OCCURRENCES + 1},
    {"kind": "daily", "start_offset": 1},
    {"kind": "monthly", "day": 32},
    {"kind": "weekly", "weekday": 0, "timezone": "PST"},
    {"kind": "weekly", "weekday": 0, "timezone": "EST"},
    {"kind": "unknown"},
    {"kind": "weekday", "weekday": 0, "ignored": True},
])
def test_semantic_schema_is_strict_before_any_mutation(schedule):
    with pytest.raises(ScheduleError):
        resolve_schedule("some unusual phrasing", now=SATURDAY, schedule=schedule)


def test_semantic_timezone_is_applied_to_original_calendar_constraints():
    result, _ = resolve_schedule(
        "Monday at 5pm America/New_York", now=SATURDAY,
        schedule={"kind": "weekday", "weekday": 0, "time": "17:00", "timezone": "America/New_York"},
    )
    assert result == datetime(2026, 11, 9, 22, tzinfo=timezone.utc)


def test_semantic_timezone_cannot_change_an_unqualified_local_clock():
    with pytest.raises(ScheduleError, match="conflict"):
        resolve_schedule(
            "Monday at 5pm", now=SATURDAY,
            schedule={"kind": "weekday", "weekday": 0, "time": "17:00",
                      "timezone": "America/New_York"},
        )


@pytest.mark.parametrize("expression,seconds", [
    ("in half an hour", 1800), ("in half a minute", 30),
    ("in an hour and a half", 5400), ("in one and a half hours", 5400),
    ("in 1.5 hours", 5400), ("in .5 hours", 1800),
    ("in 1.25 hours", 4500), ("in 2.5 minutes", 150),
    ("in a quarter of an hour", 900),
    ("in an hour and a quarter", 4500), ("in one and a quarter hours", 4500),
    ("in 1.5 hours and thirty minutes", 7200),
    ("half an hour from now", 1800), ("30 minutes from now", 1800),
])
def test_fractional_durations_are_complete_quantities(expression, seconds):
    expected = SATURDAY + timedelta(seconds=seconds)
    assert parsed(expression) == (expected, None)
    assert resolve_schedule(
        expression, now=SATURDAY,
        schedule={"kind": "relative", "delay_seconds": seconds},
    ) == (expected, None)


@pytest.mark.parametrize("expression", [
    "in half an hour", "in an hour and a half", "in 1.5 hours",
    "in about half an hour", "in about 1.5 hours",
    "around half an hour from now",
])
def test_semantic_fraction_check_never_drops_half_a_duration(expression):
    with pytest.raises(ScheduleError, match="conflict"):
        resolve_schedule(
            expression, now=SATURDAY,
            schedule={"kind": "relative", "delay_seconds": 3600},
        )


@pytest.mark.parametrize("expression", ["in an hour and a quarter", "in one and a quarter hours"])
@pytest.mark.parametrize("wrong_seconds", [900, 3600])
def test_compound_quarter_is_never_reduced_to_one_component(expression, wrong_seconds):
    with pytest.raises(ScheduleError, match="conflict"):
        resolve_schedule(
            expression, now=SATURDAY,
            schedule={"kind": "relative", "delay_seconds": wrong_seconds},
        )


def test_unrecognized_fractional_duration_cannot_use_a_recognized_subset():
    with pytest.raises(ScheduleError, match="fractional duration"):
        resolve_schedule(
            "in one hour and three quarters", now=SATURDAY,
            schedule={"kind": "relative", "delay_seconds": 3600},
        )


@pytest.mark.parametrize("expression", [
    "in -1.5 hours", "in 1.5.5 hours", "in 0.0001 seconds", "in zero point five hours",
    "in 1.5 hours tomorrow", "in half an hour except Sundays", "in one hour and two hours",
])
def test_invalid_fractional_duration_qualifiers_are_not_discarded(expression):
    with pytest.raises(ScheduleError):
        parsed(expression)


@pytest.mark.parametrize("expression,expected_day", [
    ("a week from Monday at 5pm", 16),
    ("one week from this Monday at 5pm", 16),
    ("two weeks from Monday at 5pm", 23),
    ("5pm a week from Monday", 16),
])
def test_week_from_weekday_preserves_the_offset(expression, expected_day):
    expected = datetime(2026, 11, expected_day, 17, tzinfo=PACIFIC)
    assert parsed(expression) == (expected, None)
    assert resolve_schedule(
        expression, now=SATURDAY,
        schedule={"kind": "date", "date": f"2026-11-{expected_day}", "time": "17:00"},
    ) == (expected, None)
    with pytest.raises(ScheduleError, match="conflict"):
        resolve_schedule(
            expression, now=SATURDAY,
            schedule={"kind": "weekday", "weekday": 0, "time": "17:00"},
        )


@pytest.mark.parametrize("abbreviation,offset", [
    ("PST", -8), ("PDT", -7), ("MST", -7), ("MDT", -6),
    ("CST", -6), ("CDT", -5), ("EST", -5), ("EDT", -4),
])
def test_explicit_us_abbreviations_mean_their_literal_utc_offset(abbreviation, offset):
    result, rule = parsed(f"Monday at 5pm {abbreviation}")
    assert result.utcoffset() == timedelta(hours=offset)
    assert result == datetime(2026, 11, 9, tzinfo=timezone.utc) + timedelta(hours=17 - offset)
    assert rule is None


def test_pst_is_not_silently_treated_as_summer_pdt():
    reference = datetime(2027, 6, 1, 9, tzinfo=PACIFIC)
    fixed, _ = parsed("July 1st at 5pm PST", reference)
    regional, _ = parsed("July 1st at 5pm Pacific", reference)
    assert fixed.astimezone(PACIFIC) == datetime(2027, 7, 1, 18, tzinfo=PACIFIC)
    assert regional == datetime(2027, 7, 1, 17, tzinfo=PACIFIC)
    with pytest.raises(ScheduleError, match="conflict"):
        resolve_schedule(
            "July 1st at 5pm PST", now=reference,
            schedule={"kind": "date", "date": "2027-07-01", "time": "17:00",
                      "timezone": "America/Los_Angeles"},
        )


def test_abbreviation_and_regional_semantics_agree_when_actual_offsets_agree():
    expected = datetime(2026, 11, 9, 17, tzinfo=PACIFIC)
    assert resolve_schedule(
        "Monday at 5pm PST", now=SATURDAY,
        schedule={"kind": "weekday", "weekday": 0, "time": "17:00",
                  "timezone": "America/Los_Angeles"},
    ) == (expected, None)


def test_literal_abbreviations_can_disambiguate_the_dst_fold():
    reference = datetime(2027, 11, 6, 10, tzinfo=PACIFIC)
    early, _ = parsed("tomorrow at 1:30am PDT", reference)
    late, _ = parsed("tomorrow at 1:30am PST", reference)
    assert late.astimezone(timezone.utc) - early.astimezone(timezone.utc) == timedelta(hours=1)


@pytest.mark.parametrize("expression", [
    "every Monday at 5pm PST", "every day at 5pm EST",
])
def test_fixed_offset_recurrence_is_not_saved_as_an_app_zone_recurrence(expression):
    with pytest.raises(ScheduleError, match="configured application timezone"):
        parsed(expression)


@pytest.mark.parametrize("expression,count,first,last", [
    ("for a week at 9am", 7, (7, 9), (13, 9)),
    ("for two weeks at 5pm", 14, (7, 17), (20, 17)),
    ("every day this week at 5pm", 2, (7, 17), (8, 17)),
    ("daily this week at 5pm", 2, (7, 17), (8, 17)),
    ("every day next week at 5pm", 7, (9, 17), (15, 17)),
])
def test_bounded_weeks_are_finite_calendar_dates(expression, count, first, last):
    result, rule = parsed(expression)
    assert isinstance(result, list)
    assert len(result) == count
    assert result[0] == datetime(2026, 11, first[0], first[1], tzinfo=PACIFIC)
    assert result[-1] == datetime(2026, 11, last[0], last[1], tzinfo=PACIFIC)
    assert rule is None


def test_remaining_this_week_excludes_a_clock_that_already_passed():
    result, rule = parsed("every day this week at 5pm", SATURDAY.replace(hour=18))
    assert result == [datetime(2026, 11, 8, 17, tzinfo=PACIFIC)]
    assert rule is None
    with pytest.raises(ScheduleError, match="remaining this week"):
        parsed("every day this week at 5pm", SATURDAY.replace(day=8, hour=18))


def test_semantic_week_span_cannot_lose_its_end_date_or_first_date():
    expected = parsed("every day this week at 5pm")
    assert resolve_schedule(
        "every day this week at 5pm", now=SATURDAY,
        schedule={"kind": "daily", "time": "17:00", "count": 2, "start_offset": 0},
    ) == expected
    for schedule in (
        {"kind": "daily", "time": "17:00"},
        {"kind": "daily", "time": "17:00", "count": 7},
        {"kind": "daily", "time": "17:00", "count": 2, "start_offset": 1},
    ):
        with pytest.raises(ScheduleError, match="conflict"):
            resolve_schedule("every day this week at 5pm", now=SATURDAY, schedule=schedule)


@pytest.mark.parametrize("expression", [
    "Monday @ 5pm", "Monday, 5pm", "Monday at 5pm please", "please Monday at 5pm",
    "kindly Monday at 5pm", "Monday at five p.m.",
])
def test_clock_separators_and_politeness_keep_the_entire_date(expression):
    assert parsed(expression) == (datetime(2026, 11, 9, 17, tzinfo=PACIFIC), None)


@pytest.mark.parametrize("expression,hour,minute", [
    ("Monday at half past five pm", 17, 30),
    ("Monday at quarter past five pm", 17, 15),
    ("Monday at quarter to six pm", 17, 45),
    ("Monday at a quarter past five pm", 17, 15),
])
def test_unambiguous_clock_idioms_have_one_checked_clock(expression, hour, minute):
    assert parsed(expression) == (datetime(2026, 11, 9, hour, minute, tzinfo=PACIFIC), None)


@pytest.mark.parametrize("expression", ["11/9 at 5pm", "11-09-2026 at 5pm"])
def test_plain_ambiguous_numeric_dates_request_month_day_clarification(expression):
    with pytest.raises(ScheduleError, match="Ambiguous numeric dates"):
        parsed(expression)


@pytest.mark.parametrize("when,schedule", [
    ("before Monday at 5pm", {"kind": "weekday", "weekday": 0, "time": "17:00"}),
    ("after Monday at 5pm", {"kind": "weekday", "weekday": 0, "time": "17:00"}),
    ("Monday after 5pm", {"kind": "weekday", "weekday": 0, "time": "17:00"}),
    ("in less than an hour", {"kind": "relative", "delay_seconds": 3600}),
    ("in more than an hour", {"kind": "relative", "delay_seconds": 3600}),
    ("in at least an hour", {"kind": "relative", "delay_seconds": 3600}),
    ("within 30 minutes", {"kind": "relative", "delay_seconds": 1800}),
    ("by Monday at 5pm", {"kind": "weekday", "weekday": 0, "time": "17:00"}),
    ("between Monday and Tuesday at 5pm", {"kind": "weekday", "weekday": 0, "time": "17:00"}),
])
def test_comparative_boundaries_cannot_become_an_exact_reminder(when, schedule):
    # The plain route must reject conclusively too: the original-request guard
    # uses it to detect a language model dropping a qualifier from tool args.
    from lib.reminder_schedule import UnsupportedScheduleError

    with pytest.raises(ScheduleError) as error:
        parsed(when)
    assert not isinstance(error.value, UnsupportedScheduleError)
    with pytest.raises(ScheduleError):
        resolve_schedule(when, now=SATURDAY, schedule=schedule)


def test_after_a_complete_duration_is_an_exact_relative_delay():
    assert parsed("after thirty minutes") == (SATURDAY + timedelta(minutes=30), None)
    assert resolve_schedule(
        "after an hour and a half", now=SATURDAY,
        schedule={"kind": "relative", "delay_seconds": 5400},
    ) == (SATURDAY + timedelta(minutes=90), None)
    with pytest.raises(ScheduleError):
        parsed("after thirty minutes and Monday")


def test_day_after_tomorrow_is_preserved_in_semantic_fallback():
    result, rule = resolve_schedule(
        "when the day after tomorrow arrives at 5pm", now=SATURDAY,
        schedule={"kind": "date", "date": "2026-11-09", "time": "17:00"},
    )
    assert result == datetime(2026, 11, 9, 17, tzinfo=PACIFIC)
    assert rule is None


@pytest.mark.parametrize("when", [
    "at five on Monday", "Monday at 5", "5 o'clock", "5 o’clock", "five oclock",
    "half past five", "quarter past five", "quarter to six", "tomorrow at eight",
    "at five thirty on Monday", "five oh five on Monday",
    "next five days at seven", "tonight at one",
])
@pytest.mark.parametrize("model_time", [None, "10:00", "05:00", "17:00"])
def test_a_model_clock_cannot_supply_a_missing_human_am_pm_choice(when, model_time):
    schedule = {"kind": "date", "date": "2026-11-09"}
    if model_time:
        schedule["time"] = model_time
    with pytest.raises(ScheduleError, match="AM or PM"):
        parsed(when)
    with pytest.raises(ScheduleError, match="AM or PM"):
        resolve_schedule(when, now=SATURDAY, schedule=schedule)


@pytest.mark.parametrize("when,hour,minute", [
    ("Monday morning at five", 5, 0),
    ("at five on Monday morning", 5, 0),
    ("Monday evening at six", 18, 0),
    ("Monday at five in the afternoon", 17, 0),
    ("five in the afternoon on Monday", 17, 0),
    ("Monday at five o'clock in the afternoon", 17, 0),
    ("Monday morning at half past five", 5, 30),
    ("Monday at quarter to six in the evening", 17, 45),
    ("Monday at a quarter past five in the afternoon", 17, 15),
    ("Monday at 5:30 in the evening", 17, 30),
    ("Monday at five thirty in the evening", 17, 30),
    ("Monday at five oh five in the afternoon", 17, 5),
    ("Monday at seventeen", 17, 0),
    ("Monday at zero", 0, 0),
    ("Monday at 05:30", 5, 30),
    ("Monday at 05", 5, 0),
    ("Monday at noon", 12, 0),
    ("Monday at midnight", 0, 0),
])
def test_human_dayparts_or_24_hour_clocks_determine_the_hour_and_minutes(when, hour, minute):
    expected = datetime(2026, 11, 9, hour, minute, tzinfo=PACIFIC)
    assert parsed(when) == (expected, None)
    assert resolve_schedule(
        when, now=SATURDAY,
        schedule={"kind": "weekday", "weekday": 0, "time": f"{hour:02d}:{minute:02d}"},
    ) == (expected, None)
    with pytest.raises(ScheduleError, match="conflict"):
        resolve_schedule(
            when, now=SATURDAY,
            schedule={"kind": "weekday", "weekday": 0, "time": f"{hour:02d}:{(minute + 1) % 60:02d}"},
        )


def test_tonight_disambiguates_a_bare_evening_clock():
    assert parsed("tonight at nine") == (datetime(2026, 11, 7, 21, tzinfo=PACIFIC), None)
    assert parsed("tonight at nine thirty pm") == (datetime(2026, 11, 7, 21, 30, tzinfo=PACIFIC), None)


@pytest.mark.parametrize("when", [
    "Monday evening at 5am", "Monday morning at 5pm", "Monday at 05:30 in the evening",
    "Monday at 17:30 in the morning", "Monday morning and evening at five",
])
def test_a_clock_cannot_conflict_with_the_human_daypart(when):
    with pytest.raises(ScheduleError, match="conflict"):
        parsed(when)
    with pytest.raises(ScheduleError, match="conflict"):
        resolve_schedule(
            when, now=SATURDAY,
            schedule={"kind": "weekday", "weekday": 0, "time": "17:00"},
        )


@pytest.mark.parametrize("when,day", [
    ("first of next month", "2026-12-01"),
    ("second of next month", "2026-12-02"),
    ("on the first", "2026-12-01"),
    ("this month on the fifteenth", "2026-11-15"),
    ("9 November", "2026-11-09"),
    ("November 9, 2026", "2026-11-09"),
])
def test_date_numbers_and_ordinal_words_are_not_bare_clocks(when, day):
    assert resolve_schedule(
        when, now=SATURDAY,
        schedule={"kind": "date", "date": day, "time": "10:00"},
    ) == parsed(when)


def test_duration_and_bounded_count_numbers_are_not_bare_clocks():
    assert resolve_schedule(
        "in five minutes", now=SATURDAY,
        schedule={"kind": "relative", "delay_seconds": 300},
    ) == parsed("in five minutes")
    assert resolve_schedule(
        "next five days", now=SATURDAY,
        schedule={"kind": "daily", "count": 5, "start_offset": 1},
    ) == parsed("next five days")


def test_conversational_fallback_checks_the_daypart_without_a_precise_clock():
    result, _ = resolve_schedule(
        "when Monday rolls around in the morning", now=SATURDAY,
        schedule={"kind": "weekday", "weekday": 0, "time": "09:00"},
    )
    assert result == datetime(2026, 11, 9, 9, tzinfo=PACIFIC)
    with pytest.raises(ScheduleError, match="conflict"):
        resolve_schedule(
            "when Monday rolls around in the morning", now=SATURDAY,
            schedule={"kind": "weekday", "weekday": 0, "time": "17:00"},
        )


def test_stated_clock_seconds_are_preserved_with_a_daypart():
    assert parsed("Monday at 05:30:45 in the morning") == (
        datetime(2026, 11, 9, 5, 30, 45, tzinfo=PACIFIC), None,
    )


def test_an_idiom_cannot_silently_consume_part_of_another_clock():
    with pytest.raises(ScheduleError):
        parsed("Monday at half past 5:30 in the morning")


@pytest.mark.parametrize("zone_name", [
    "UTC", "Europe/Berlin", "Asia/Kolkata", "Pacific/Chatham",
    "Australia/Lord_Howe", "Australia/Adelaide",
])
def test_unqualified_calendar_and_spoken_clocks_use_the_callers_configured_timezone(zone_name):
    zone = ZoneInfo(zone_name)
    reference = datetime(2026, 11, 7, 8, 30, tzinfo=zone)
    expected = datetime(2026, 11, 9, 5, 30, tzinfo=zone)
    assert parse_time_expression("Monday at half past five in the morning", now=reference) == (
        expected, None,
    )
    assert resolve_schedule(
        "Monday at half past five in the morning", now=reference,
        schedule={"kind": "weekday", "weekday": 0, "time": "05:30"},
    ) == (expected, None)
    assert parse_time_expression("Monday", now=reference)[0] == datetime(2026, 11, 9, 10, tzinfo=zone)
    with pytest.raises(ScheduleError, match="AM or PM"):
        resolve_schedule(
            "at five on Monday", now=reference,
            schedule={"kind": "weekday", "weekday": 0, "time": "17:00"},
        )


@pytest.mark.parametrize("zone_name", [
    "UTC", "Europe/Berlin", "Asia/Kolkata", "Pacific/Chatham", "Australia/Lord_Howe",
])
def test_explicit_semantic_iana_zones_are_respected_globally(zone_name):
    reference = datetime(2026, 11, 7, 8, 30, tzinfo=timezone.utc)
    expected = datetime(2026, 11, 9, 17, tzinfo=ZoneInfo(zone_name))
    assert resolve_schedule(
        f"Monday at five in the afternoon {zone_name}", now=reference,
        schedule={"kind": "weekday", "weekday": 0, "time": "17:00", "timezone": zone_name},
    ) == (expected, None)


@pytest.mark.parametrize("zone_name,year,month,day,elapsed_hour,elapsed_minute", [
    ("Europe/Berlin", 2027, 3, 27, 13, 0),
    ("Australia/Lord_Howe", 2027, 4, 3, 11, 30),
    ("Australia/Adelaide", 2027, 4, 3, 11, 0),
    ("Pacific/Chatham", 2027, 4, 3, 11, 0),
])
def test_calendar_days_and_elapsed_hours_respect_non_us_and_half_hour_dst(
    zone_name, year, month, day, elapsed_hour, elapsed_minute,
):
    zone = ZoneInfo(zone_name)
    reference = datetime(year, month, day, 12, tzinfo=zone)
    calendar_day, _ = parse_time_expression("in one day", now=reference)
    elapsed, _ = parse_time_expression("in twenty four hours", now=reference)
    assert calendar_day == datetime(year, month, day + 1, 12, tzinfo=zone)
    assert elapsed == datetime(year, month, day + 1, elapsed_hour, elapsed_minute, tzinfo=zone)
    assert elapsed.astimezone(timezone.utc) - reference.astimezone(timezone.utc) == timedelta(hours=24)


@pytest.mark.parametrize('when', ['Monday at 5pm', 'tomorrow at noon', 'in one hour', ''])
def test_explicit_timezone_lookup_never_invents_a_local_default(when):
    assert explicit_schedule_timezone(when) is None


@pytest.mark.parametrize('when,expected', [
    ('Monday at 5pm Europe/Berlin', ZoneInfo('Europe/Berlin')),
    ('Monday at 5pm in Asia/Kolkata please', ZoneInfo('Asia/Kolkata')),
    ('Monday at 5pm Pacific', ZoneInfo('America/Los_Angeles')),
    ('Monday at 5pm UTC', timezone.utc),
    ('2026-11-09T17:00:00Z', timezone.utc),
])
def test_explicit_timezone_lookup_preserves_the_stated_zone(when, expected):
    assert explicit_schedule_timezone(when) == expected


def test_explicit_fixed_offset_lookup_does_not_invent_a_regional_zone():
    zone = explicit_schedule_timezone('Monday at 5pm PST')
    assert zone is not None
    assert not isinstance(zone, ZoneInfo)
    assert zone.utcoffset(None) == timedelta(hours=-8)


def test_explicit_timezone_lookup_rejects_conflicting_zones():
    with pytest.raises(ScheduleError, match='conflicting timezones'):
        explicit_schedule_timezone('Monday at 5pm Europe/Berlin Asia/Kolkata')


@pytest.mark.parametrize('configured_zone', ['UTC', 'GMT', 'Etc/UTC'])
@pytest.mark.parametrize('explicit_zone', ['UTC', 'GMT', 'Etc/UTC', 'UTC+00:00'])
@pytest.mark.parametrize('when,day,rule', [
    ('every Monday at 5pm', 9, 'WEEKLY:0'),
    ('every day at 5pm', 8, 'DAILY'),
    ('every month on the 10th at 5pm', 10, 'MONTHLY:10'),
])
def test_equivalent_fixed_utc_zones_preserve_recurring_schedules(
    configured_zone, explicit_zone, when, day, rule,
):
    zone = ZoneInfo(configured_zone)
    reference = datetime(2026, 11, 7, 8, 30, tzinfo=zone)
    target, actual_rule = parse_time_expression(f'{when} {explicit_zone}', now=reference)
    assert target == datetime(2026, 11, day, 17, tzinfo=zone)
    assert actual_rule == rule


@pytest.mark.parametrize('configured_zone,explicit_zone', [
    ('America/Los_Angeles', 'UTC'), ('America/Los_Angeles', 'PST'),
    ('UTC', 'PST'), ('UTC', 'UTC+02:00'),
])
def test_fixed_zone_equivalence_does_not_admit_foreign_or_dst_dependent_recurrence(
    configured_zone, explicit_zone,
):
    reference = datetime(2026, 11, 7, 8, 30, tzinfo=ZoneInfo(configured_zone))
    with pytest.raises(ScheduleError, match='configured application timezone'):
        parse_time_expression(f'every Monday at 5pm {explicit_zone}', now=reference)
