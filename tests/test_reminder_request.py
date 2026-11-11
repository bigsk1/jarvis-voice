"""Only clear original notification clauses constrain reminder tool arguments."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from lib.reminder_request import (
    reminder_request_coverage_warning,
    reminder_request_rejection,
    reminder_request_timezone,
)

REFERENCE = datetime(2026, 11, 7, 5, 17, 34, 123456, tzinfo=ZoneInfo("America/Los_Angeles"))
WINDOWS_SHARED_REPORT_QUERY = (
    "Set a reminder Every Friday at 11 a.m. And a reminder on Every Tuesday At 11 a.m. "
    "To check the updated Home watch report"
)
REPORT_TITLE = "Check the updated Home watch report"


def check(query, when, *, title="Update firewall", schedule=None):
    arguments = {"title": title, "when": when}
    if schedule is not None:
        arguments["schedule"] = schedule
    return reminder_request_rejection(query, arguments, reference_time=REFERENCE)


@pytest.mark.parametrize("query", [
    "Set a reminder Monday at 5pm to update firewall",
    "Remind me Monday at 5pm to update firewall",
    "Please remind me Monday at 5pm about the firewall",
    "While you're at it, remind me Monday at 5pm that the firewall needs updating.",
    "Create a reminder for Monday at 5pm to update firewall",
    "Set me a reminder Monday at 5pm to update firewall",
    "Add a reminder Monday at 5pm to update firewall",
    "Remind me Monday at 5pm",
])
def test_source_weekday_cannot_be_dropped(query):
    assert "does not match" in check(query, "5pm")
    assert check(query, "Monday at 5pm") is None


@pytest.mark.parametrize("source,actual", [
    ("tomorrow at 5pm", "5pm"),
    ("Monday at 5pm", "Monday at 6pm"),
    ("in one hour", "in 30 minutes"),
    ("every Monday at 5pm", "Monday at 5pm"),
    ("every day for the next 3 days at 5pm", "every day at 5pm"),
    ("Monday at 5pm America/New_York", "Monday at 5pm America/Los_Angeles"),
])
def test_date_time_duration_repetition_count_and_timezone_are_compared(source, actual):
    assert check(f"Remind me {source} to update firewall", actual)


def test_equivalent_utc_instant_and_semantic_input_are_accepted():
    query = "Remind me Monday at 5pm to update firewall"
    assert check(query, "2026-11-10T01:00:00Z") is None
    assert check(query, "Monday at 5pm", schedule={
        "kind": "weekday", "weekday": 0, "time": "17:00",
    }) is None


@pytest.mark.parametrize("expression", ["Monday at 5pm", "tomorrow at 5pm", "in one hour"])
def test_clear_body_first_trailing_date_preserves_its_constraints(expression):
    query = f"Set a reminder to update firewall {expression}"
    assert check(query, expression) is None
    assert "original request" in check(query, "5pm")


@pytest.mark.parametrize("query,title", [
    ("Remind me to call about the Monday appointment at 5pm", "Call about the Monday appointment"),
    ("Remind me to book a flight Monday at 5pm", "Book a flight"),
    ("Remind me to update firewall at 5pm", "Update firewall"),
    ("Remind me to update firewall Monday at 5pm", "Update firewall Monday"),
])
def test_body_first_ambiguity_or_lost_constraints_are_rejected(query, title):
    assert check(query, "Tuesday at 6pm", title=title)


def test_body_first_clock_and_article_variations_are_independently_checked():
    query = "Remind me to update the firewall at 5pm"
    assert check(query, "5pm", title="Update firewall") is None
    assert check(query, "Tuesday at 5pm", title="Update the firewall")
    assert check(query, "Tuesday at 6pm", title="Anything the model calls it")


@pytest.mark.parametrize("query", [
    "Remind me Friday at 5pm about my Monday appointment at 9am",
    "Remind me Friday at 5pm to call about the Monday appointment",
    "Remind me Friday at 5pm that my Monday flight leaves at 9am",
])
def test_appointment_dates_in_the_content_are_not_notification_dates(query):
    assert check(query, "Friday at 5pm") is None
    assert check(query, "Monday at 9am")


def test_distinct_reminder_clauses_are_matched_by_exact_subject():
    query = "Remind me Monday at 5pm to call plumber and remind me Tuesday at 6pm to buy milk."
    assert check(query, "Monday at 5pm", title="Call plumber") is None
    assert check(query, "Tuesday at 6pm", title="Buy milk") is None
    assert check(query, "5pm", title="Call plumber")
    assert check(query, "Monday at 5pm", title="Buy milk")
    assert "ambiguous" in check(query, "Tuesday at 6pm", title="Ambiguous summary")


@pytest.mark.parametrize("meridiem,clock", [
    ("11 a.m.", "11:00"), ("11 p.m.", "23:00"),
    ("12 a.m.", "00:00"), ("12 p.m.", "12:00"),
    ("11a.m", "11:00"), ("11a.m.", "11:00"), ("11 a.m", "11:00"),
    ("11 am.", "11:00"), ("11 AM", "11:00"), ("11am", "11:00"),
    ("11 a. m.", "11:00"), ("11A.M.", "11:00"),
    ("11p.m", "23:00"), ("11p.m.", "23:00"), ("11 p.m", "23:00"),
    ("11 pm.", "23:00"), ("11 PM", "23:00"), ("11pm", "23:00"),
    ("11 p. m.", "23:00"), ("11P.M.", "23:00"),
    ("12a.m", "00:00"), ("12A.M.", "00:00"),
    ("12p.m", "12:00"), ("12P.M.", "12:00"),
])
def test_windows_dictation_preserves_both_weekly_schedules_and_shared_subject(meridiem, clock):
    query = WINDOWS_SHARED_REPORT_QUERY.replace("11 a.m.", meridiem)
    for day, weekday in (("Friday", 4), ("Tuesday", 1)):
        when = f"every {day} at {clock}"
        assert check(query, when, title=REPORT_TITLE) is None
        assert check(query, when, title=REPORT_TITLE, schedule={
            "kind": "weekly", "weekday": weekday, "time": clock,
        }) is None


@pytest.mark.parametrize("source_clock", ["11", "13A.M.", "13P.M."])
def test_human_clock_must_be_unambiguous_and_valid_before_accepting_model_time(source_clock):
    query = WINDOWS_SHARED_REPORT_QUERY.replace("11 a.m.", source_clock)
    for day, weekday in (("Friday", 4), ("Tuesday", 1)):
        rejection = check(query, f"every {day} at 11:00", title=REPORT_TITLE, schedule={
            "kind": "weekly", "weekday": weekday, "time": "11:00",
        })
        assert rejection is not None
        assert "clarification" in rejection


@pytest.mark.parametrize("when,title", [
    ("Friday at 11:00", REPORT_TITLE),
    ("Tuesday at 11:00", REPORT_TITLE),
    ("every Friday at 23:00", REPORT_TITLE),
    ("every Tuesday at 10:00", REPORT_TITLE),
    ("every Wednesday at 11:00", REPORT_TITLE),
    ("every Friday at 11:00", "Check a different report"),
])
def test_windows_shared_subject_does_not_authorize_changed_schedules_or_content(when, title):
    assert check(WINDOWS_SHARED_REPORT_QUERY, when, title=title)


def test_identical_subjects_are_disambiguated_by_the_complete_notification_schedule():
    query = (
        "Set a reminder every Friday at 11 a.m. to check report "
        "and a reminder on every Friday at 2 p.m. to check report"
    )
    assert check(query, "every Friday at 11:00", title="Check report") is None
    assert check(query, "every Friday at 14:00", title="Check report") is None
    assert check(query, "every Friday at 12:00", title="Check report")
    assert check(query, "Friday at 14:00", title="Check report")


def test_multiple_explicit_subjects_do_not_fill_an_unassociated_reminder():
    query = (
        "Set a reminder every Friday at 11 a.m. "
        "and a reminder on every Tuesday at 12 p.m. to buy milk "
        "and another reminder every Wednesday at 1 p.m. to call plumber"
    )
    assert check(query, "every Tuesday at 12:00", title="Buy milk") is None
    assert check(query, "every Wednesday at 13:00", title="Call plumber") is None
    for title in ("Buy milk", "Call plumber", "Unknown reminder"):
        assert check(query, "every Friday at 11:00", title=title)
    assert check(query, "every Tuesday at 12:00", title="Call plumber")
    assert check(query, "every Wednesday at 13:00", title="Buy milk")


@pytest.mark.parametrize("query", [
    "Set two reminders: Monday at 5pm and Tuesday at 6pm",
    "Remind me when convenient to update firewall",
    "Remember that I updated the firewall on Monday at 5pm",
])
def test_ambiguous_or_unsupported_source_returns_no_validation_verdict(query):
    assert check(query, "Tuesday at 6pm") is None


def test_recognizable_unsupported_source_cannot_lose_visible_constraints():
    query = "Remind me Monday at 5pm please to update firewall"
    assert check(query, "Monday at 5pm") is None
    assert check(query, "Tuesday at 5pm")
    assert check("Set a reminder Monday or Tuesday at 5pm to update firewall", "Tuesday at 5pm")


@pytest.mark.parametrize("query", [
    "Remind me Monday at 5pm to call plumber and Tuesday at 6pm to buy milk",
    "Remind me Monday at 5pm to call the plumber and then Tuesday at 6pm buy milk",
])
def test_conjoined_notifications_keep_independent_dates_subjects_and_clocks(query):
    assert check(query, "Monday at 5pm", title="Call the plumber") is None
    assert check(query, "Tuesday at 6pm", title="Buy milk") is None
    assert check(query, "Monday at 5pm", title="Buy milk")
    assert check(query, "Tuesday at 6pm", title="Call plumber")
    assert "ambiguous" in check(query, "5pm", title="Unknown reminder")


def test_shared_tomorrow_qualifier_applies_to_each_conjoined_clock():
    query = "Remind me tomorrow at noon to call plumber and at 3pm to buy milk and at 6pm to pay rent"
    for title, when in (("Call plumber", "tomorrow at noon"), ("Buy milk", "tomorrow at 3pm"),
                        ("Pay rent", "tomorrow at 6pm")):
        assert check(query, when, title=title) is None
    assert check(query, "3pm", title="Buy milk")
    assert check(query, "6pm", title="Pay rent")


def test_shared_clock_inherits_explicit_timezone_and_weekly_repetition():
    query = "Remind me every Monday at noon America/New_York to call plumber and at 3pm to buy milk"
    assert check(query, "every Monday at 3pm America/New_York", title="Buy milk") is None
    assert check(query, "every Monday at 3pm America/Los_Angeles", title="Buy milk")


def test_conjunction_in_appointment_content_does_not_create_another_notification():
    query = "Remind me Friday at 5pm about my Monday appointment and Tuesday appointment"
    assert check(query, "Friday at 5pm") is None
    assert check(query, "Tuesday at 5pm")


def test_unfamiliar_conjoined_action_requires_clarification_before_any_partial_save():
    query = "Remind me Monday at 5pm to call plumber and Tuesday at 6pm sanitize equipment"
    assert "clarification" in check(query, "Monday at 5pm", title="Call plumber")
    assert "clarification" in check(query, "Tuesday at 6pm", title="Sanitize equipment")
    explicit = query.replace("6pm sanitize", "6pm to sanitize")
    assert check(explicit, "Monday at 5pm", title="Call plumber") is None
    assert check(explicit, "Tuesday at 6pm", title="Sanitize equipment") is None


def test_appointment_content_conjunction_with_a_clock_is_not_an_extra_mutation():
    query = "Remind me Friday at 5pm about my Monday appointment and Tuesday at 6pm appointment"
    assert check(query, "Friday at 5pm") is None
    assert reminder_request_coverage_warning(
        query, [_saved("Appointment reminder", "Friday at 5pm")], reference_time=REFERENCE,
    ) is None


def test_model_supplied_source_fields_do_not_replace_the_human_request():
    arguments = {"title": "Update firewall", "when": "5pm",
                 "original_query": "Remind me at 5pm", "requested_when": "5pm"}
    assert reminder_request_rejection(
        "Remind me Monday at 5pm to update firewall", arguments, reference_time=REFERENCE,
    )


def test_recognized_invalid_source_is_not_silently_replaced():
    assert "clarification" in check("Remind me today at 3am to update firewall", "tomorrow at 3am")


def test_argument_errors_remain_the_tools_responsibility():
    assert check("Remind me Monday at 5pm to update firewall", "at a convenient time") is None


def test_reference_clock_must_be_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        reminder_request_rejection("Remind me at 5pm", {"when": "5pm"}, reference_time=datetime(2026, 11, 7))


def _saved(title, when, *, trigger=None, reference=REFERENCE, ok=True):
    data = {"reminder_id": 1, "schedule_reference_time": reference.isoformat(),
            "schedule_timezone": str(reference.tzinfo)}
    if trigger is not None:
        data["trigger_time"] = trigger
        data["recurrence_rule"] = None
    return {"tool": "create_reminder", "arguments": {"title": title, "when": when},
            "result": {"ok": ok, "data": data}}


def test_coverage_identifies_only_missing_second_notification():
    query = "Remind me Monday at 5pm to call plumber and Tuesday at 6pm to buy milk"
    first = _saved("Call the plumber", "Monday at 5pm", trigger="2026-11-10T01:00:00")
    warning = reminder_request_coverage_warning(query, [first], reference_time=REFERENCE)
    assert "buy milk" in warning and "Tuesday at 6pm" in warning
    assert "call plumber" not in warning
    second = _saved("Buy milk", "Tuesday at 6pm", trigger="2026-11-11T02:00:00Z")
    assert reminder_request_coverage_warning(query, [first, second], reference_time=REFERENCE) is None


def test_windows_shared_subject_coverage_requires_both_successful_weekly_receipts():
    first = _saved(REPORT_TITLE, "every Friday at 11:00")
    warning = reminder_request_coverage_warning(
        WINDOWS_SHARED_REPORT_QUERY, [first], reference_time=REFERENCE,
    )
    assert warning is not None
    assert "tuesday" in warning.lower()
    assert "friday" not in warning.lower()
    second = _saved(REPORT_TITLE, "every Tuesday at 11:00")
    assert reminder_request_coverage_warning(
        WINDOWS_SHARED_REPORT_QUERY, [first, second], reference_time=REFERENCE,
    ) is None
    second["result"]["ok"] = False
    assert "tuesday" in reminder_request_coverage_warning(
        WINDOWS_SHARED_REPORT_QUERY, [first, second], reference_time=REFERENCE,
    ).lower()


@pytest.mark.parametrize("query", [
    "Remind me to print the invoice and a reminder email tomorrow at 5pm",
    "Remind me to bring medication and a reminder card tomorrow at 5pm",
])
def test_reminder_nouns_in_content_do_not_erase_the_notification_schedule(query):
    assert check(query, "tomorrow at 5pm") is None
    assert check(query, "every Friday at 11:00")


def test_attached_dotted_clock_clause_keeps_the_shared_date_and_repetition():
    query = ("Remind me every Friday at 11a.m. to call plumber "
             "and at 11p.m. to buy milk")
    assert check(query, "every Friday at 11am", title="Call plumber") is None
    assert check(query, "every Friday at 11pm", title="Buy milk") is None
    assert check(query, "11pm", title="Buy milk")


def test_unfamiliar_action_with_attached_dotted_clock_still_requires_clarification():
    query = ("Remind me Monday at 11a.m. to call plumber "
             "and Tuesday at 11p.m. sanitize equipment")
    assert "clarification" in check(query, "Monday at 11am", title="Call plumber")


def test_coverage_survives_internal_recovery_guard_without_suppressing_missing_work():
    query = "Remind me Monday at 5pm to call plumber and Tuesday at 6pm to buy milk"
    contexts = [_saved("Call plumber", "Monday at 5pm"),
                {"tool": "reminder_completion_guard", "result": {"ok": False}},
                {"tool": "duplicate_guard", "result": {"ok": False}}]
    assert "buy milk" in reminder_request_coverage_warning(query, contexts, reference_time=REFERENCE)


def test_single_source_coverage_does_not_require_an_exact_model_title():
    query = "Remind me tomorrow at noon about my 2pm appointment"
    context = _saved("Call the plumber", "tomorrow at noon")
    assert reminder_request_coverage_warning(query, [context], reference_time=REFERENCE) is None


def test_coverage_uses_recorded_reference_even_with_actual_machine_timestamp():
    target = (REFERENCE + timedelta(hours=1)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    context = _saved("Update firewall", "in one hour", trigger=target.isoformat())
    assert reminder_request_coverage_warning(
        "Remind me in one hour to update firewall", [context],
        reference_time=REFERENCE + timedelta(days=3),
    ) is None


def test_each_relative_notification_uses_its_own_recorded_parse_clock():
    query = "Remind me in one hour to call plumber and in two hours to buy milk"
    later = REFERENCE + timedelta(seconds=12)
    contexts = [
        _saved("Call plumber", "in one hour", trigger=(REFERENCE + timedelta(hours=1)).isoformat()),
        _saved("Buy milk", "in two hours", reference=later,
               trigger=(later + timedelta(hours=2)).isoformat()),
    ]
    assert reminder_request_coverage_warning(query, contexts, reference_time=later) is None


@pytest.mark.parametrize("tool", ["cancel_reminder", "update_reminder", "acknowledge_reminders", "workflow"])
def test_coverage_never_recovers_after_mutations_that_may_invalidate_saved_receipts(tool):
    query = "Remind me Monday at 5pm to call plumber and Tuesday at 6pm to buy milk"
    contexts = [_saved("Call plumber", "Monday at 5pm"), {"tool": tool, "result": {"ok": True}}]
    assert reminder_request_coverage_warning(query, contexts, reference_time=REFERENCE) is None


def test_coverage_requires_an_attempt_and_does_not_invent_an_unsupported_date():
    assert reminder_request_coverage_warning(
        "Remind me Monday at 5pm to update firewall", [], reference_time=REFERENCE,
    ) is None
    assert reminder_request_coverage_warning(
        "Remind me Monday or Tuesday at 5pm to update firewall",
        [_saved("Update firewall", "Monday at 5pm")], reference_time=REFERENCE,
    ) is None


def test_failed_attempt_does_not_count_as_saved_coverage():
    query = "Remind me Monday at 5pm to call plumber and Tuesday at 6pm to buy milk"
    contexts = [_saved("Call plumber", "Monday at 5pm"), _saved("Buy milk", "Tuesday at 6pm", ok=False)]
    assert "buy milk" in reminder_request_coverage_warning(query, contexts, reference_time=REFERENCE)


@pytest.mark.parametrize("zone_name", ["UTC", "Europe/Berlin", "Asia/Kolkata", "Pacific/Chatham"])
def test_source_preflight_and_coverage_follow_the_provided_timezone(zone_name):
    zone = ZoneInfo(zone_name)
    reference = datetime(2026, 11, 7, 5, 17, 34, tzinfo=zone)
    correct = {"title": "Update firewall", "when": "Monday at 5pm"}
    wrong = {"title": "Update firewall", "when": "5pm"}
    for query in ("Remind me Monday at 5pm to update firewall",
                  "Remind me to update the firewall Monday at 5pm"):
        assert reminder_request_rejection(query, correct, reference_time=reference) is None
        assert reminder_request_rejection(query, wrong, reference_time=reference)
        target = datetime(2026, 11, 9, 17, tzinfo=zone).astimezone(ZoneInfo("UTC"))
        context = _saved("Update firewall", "Monday at 5pm", reference=reference,
                         trigger=target.isoformat())
        assert reminder_request_coverage_warning(
            query, [context], reference_time=reference.astimezone(ZoneInfo("UTC")) + timedelta(days=3),
        ) is None


@pytest.mark.parametrize("zone_text,expected_name", [
    ("Europe/Berlin", "Europe/Berlin"), ("Asia/Kolkata", "Asia/Kolkata"),
    ("Pacific/Chatham", "Pacific/Chatham"), ("UTC", "UTC"),
    ("Pacific", "America/Los_Angeles"), ("Eastern", "America/New_York"),
])
def test_explicit_human_notification_timezone_is_available_without_configuration(zone_text, expected_name):
    for query in (f"Remind me Monday at 5pm {zone_text} to update firewall",
                  f"Remind me to update the firewall Monday at 5pm {zone_text}"):
        zone = reminder_request_timezone(query, reference_time=REFERENCE)
        assert str(zone) == expected_name


@pytest.mark.parametrize("query", [
    "Remind me Monday at 5pm to update firewall",
    "Remind me Monday at 5pm to check the Europe/Berlin firewall",
    "Remind me Monday at 5pm about my UTC appointment",
    "Remind me to update the Europe/Berlin firewall Monday at 5pm",
    "Review the Europe/Berlin host configuration",
])
def test_timezone_must_be_in_the_notification_not_its_content_or_runtime_clock(query):
    assert reminder_request_timezone(query, reference_time=REFERENCE) is None


def test_only_one_explicit_notification_timezone_can_authorize_an_unconfigured_request():
    same = ("Remind me Monday at 5pm Europe/Berlin to call plumber and "
            "Tuesday at 6pm Europe/Berlin to buy milk")
    assert str(reminder_request_timezone(same, reference_time=REFERENCE)) == "Europe/Berlin"
    conflicting = same.replace("Tuesday at 6pm Europe/Berlin", "Tuesday at 6pm Asia/Kolkata")
    assert reminder_request_timezone(conflicting, reference_time=REFERENCE) is None


def test_explicit_iso_offset_is_returned_without_becoming_a_guessed_region():
    query = "Remind me 2026-11-09T17:00:00+05:30 to update firewall"
    zone = reminder_request_timezone(query, reference_time=REFERENCE)
    assert zone is not None and zone.utcoffset(None) == timedelta(hours=5, minutes=30)
    assert not isinstance(zone, ZoneInfo)


@pytest.mark.parametrize("reply,expected", [
    ("Europe/Berlin", "Europe/Berlin"), (" Use Asia/Kolkata. ", "Asia/Kolkata"),
    ("Timezone is Pacific/Chatham", "Pacific/Chatham"),
    ("My time zone is Europe/Berlin", "Europe/Berlin"),
    ("UTC", "UTC"), ("Use Pacific", "America/Los_Angeles"),
])
def test_whole_human_timezone_clarification_reply_is_an_explicit_assertion(reply, expected):
    assert str(reminder_request_timezone(reply, reference_time=REFERENCE)) == expected


@pytest.mark.parametrize("reply", [
    "In the article Europe/Berlin", "The server logs say UTC", "Use Europe/Berlin for the report",
    "My host is Europe/Berlin", "timezone is Unknown/Missing", "Europe/Berlin or Asia/Kolkata",
])
def test_timezone_mentions_in_arbitrary_content_are_not_clarification_replies(reply):
    assert reminder_request_timezone(reply, reference_time=REFERENCE) is None
