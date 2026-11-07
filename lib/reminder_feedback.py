"""Actionable, deterministic feedback for reminder plans rejected before saving."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def reminder_schedule_rejection(
    reason: str, *, when: Any, reference_time: datetime,
) -> dict[str, Any]:
    """Explain a pre-write rejection without relying on model-generated claims."""
    lower = reason.lower()
    if "does not match the original request" in lower:
        explanation = "The proposed reminder time does not match your original request."
        question = "What exact notification date and time should I use?"
    elif "am or pm" in lower:
        explanation = "The requested hour needs AM or PM."
        question = "Do you mean AM or PM for the notification time?"
    elif "original request contains multiple" in lower:
        explanation = "I couldn't safely pair each reminder message with its requested time."
        question = "Which notification time goes with each reminder?"
    elif "appointment or event time" in lower:
        explanation = "I need to distinguish the notification time from the appointment or event time."
        question = "When should I notify you?"
    elif "no reminder timezone is configured" in lower and "recurr" in lower:
        explanation = "A timezone must be configured for recurring reminders."
        question = "Which timezone should recurring reminders use?"
    elif "no reminder timezone is configured" in lower:
        explanation = "No local timezone is configured for reminders."
        question = "What city or timezone should I use?"
    elif "past" in lower:
        explanation = "The requested notification time is in the past."
        question = "What future date and time should I use?"
    elif "does not exist because of a daylight" in lower:
        explanation = "That local time is skipped when the clocks change."
        question = "What other time should I use?"
    elif "occurs twice" in lower or "ambiguous local time" in lower:
        explanation = "That local time occurs twice when the clocks change."
        question = "Which UTC offset should I use, or would you prefer another time?"
    elif "numeric date" in lower:
        explanation = "The numeric date could mean more than one calendar date."
        question = "What month and day do you mean?"
    elif any(value in lower for value in ("comparative", "range", "qualifier requires clarification")):
        explanation = "The schedule contains a range or condition that needs an exact notification time."
        question = "What exact date and time should I notify you?"
    elif ("timezone" in lower or "utc offset" in lower) and "not understood" not in lower:
        explanation = "I couldn't validate the requested timezone against the reminder time."
        question = "What city or UTC offset should I use?"
    elif "recurrence" in lower or "repetition" in lower or "frequency" in lower:
        explanation = "I couldn't safely represent the requested repeat schedule."
        question = "What exact dates and times should the notifications use?"
    elif "multiple clock" in lower or "conflicting notification clock" in lower:
        explanation = "The notification schedule contains conflicting times."
        question = "When should I notify you, separately from any appointment time?"
    elif "semantic schedule conflicts" in lower or "annotation conflicts" in lower:
        explanation = "The interpreted date or time conflicts with the schedule you requested."
        question = "What exact notification date and time should I use?"
    elif any(value in lower for value in (
        "invalid calendar date", "does not exist in the requested month", "invalid day of",
    )):
        explanation = "That calendar date does not exist."
        question = "What calendar date should I use?"
    else:
        explanation = "I couldn't understand the complete notification schedule safely."
        question = "What notification date and time, or delay such as 30 minutes, should I use?"
    return {
        "ok": False,
        "error": f"{reason.rstrip('. ')}. No reminder was created.",
        "error_code": "invalid_reminder_schedule",
        "speech": f"I couldn't create the reminder. {explanation} {question} No reminder was created.",
        "data": {
            "needs_clarification": True,
            "clarification_question": question,
            "schedule_rejection_reason": reason,
            "requested_when": when,
            "schedule_reference_time": reference_time.isoformat(),
        },
    }
