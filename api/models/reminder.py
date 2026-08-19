"""Reminder Pydantic models"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ReminderStatus(str, Enum):
    SCHEDULED = "scheduled"
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    CANCELED = "canceled"
    EXPIRED = "expired"

class ReminderCreate(BaseModel):
    """Model for creating a new reminder"""
    title: str = Field(..., description="Reminder title")
    description: str | None = Field(None, description="Detailed description")
    trigger_time: str = Field(..., description="ISO 8601 timestamp when to trigger")
    related_intel_file: str | None = Field(None, description="Related intel file path")
    callback_url: str | None = Field(None, description="Webhook to call when triggered")
    recurrence_rule: str | None = Field(
        None,
        description="DAILY, WEEKLY:0-6, or MONTHLY:1-31",
    )
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata (JSON)")

    @field_validator("recurrence_rule")
    @classmethod
    def validate_recurrence_rule(cls, value: str | None) -> str | None:
        """Reject rules the reminder scheduler cannot execute."""
        if value is None or value == "DAILY":
            return value

        if ":" in value:
            recurrence_type, raw_number = value.split(":", 1)
            try:
                number = int(raw_number)
            except ValueError:
                number = None

            if recurrence_type == "WEEKLY" and number is not None and 0 <= number <= 6:
                return value
            if recurrence_type == "MONTHLY" and number is not None and 1 <= number <= 31:
                return value

        raise ValueError(
            "recurrence_rule must be DAILY, WEEKLY:0-6, or MONTHLY:1-31"
        )

class Reminder(BaseModel):
    """Full reminder model"""
    id: int
    title: str
    description: str | None
    trigger_time: str
    status: ReminderStatus
    created_at: str
    triggered_at: str | None
    acknowledged_at: str | None
    spoken: bool
    spoken_at: str | None
    related_intel_file: str | None
    callback_url: str | None
    recurrence_rule: str | None
    metadata: str | None  # JSON string from DB

class ReminderResponse(BaseModel):
    """API response for reminder operations"""
    ok: bool
    reminder_id: int | None = None
    reminder: Reminder | None = None
    reminders: list[Reminder] | None = None
    message: str | None = None
