"""Validation tests for reminder API models."""

import pytest
from pydantic import ValidationError

from api.models.reminder import ReminderCreate


@pytest.mark.parametrize(
    "recurrence_rule",
    [None, "DAILY", "WEEKLY:0", "WEEKLY:6", "MONTHLY:1", "MONTHLY:31"],
)
def test_reminder_create_accepts_supported_recurrence_rules(recurrence_rule):
    reminder = ReminderCreate(
        title="Check backup",
        trigger_time="2026-08-20T12:00:00+00:00",
        recurrence_rule=recurrence_rule,
    )

    assert reminder.recurrence_rule == recurrence_rule


@pytest.mark.parametrize(
    "recurrence_rule",
    [
        "",
        "daily",
        "YEARLY",
        "WEEKLY:-1",
        "WEEKLY:7",
        "WEEKLY:nope",
        "MONTHLY:0",
        "MONTHLY:32",
        "MONTHLY:nope",
    ],
)
def test_reminder_create_rejects_malformed_recurrence_rules(recurrence_rule):
    with pytest.raises(ValidationError, match="recurrence_rule"):
        ReminderCreate(
            title="Check backup",
            trigger_time="2026-08-20T12:00:00+00:00",
            recurrence_rule=recurrence_rule,
        )
