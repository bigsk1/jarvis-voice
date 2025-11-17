"""Reminder Pydantic models"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from enum import Enum

class ReminderStatus(str, Enum):
    SCHEDULED = "scheduled"
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    CANCELED = "canceled"
    EXPIRED = "expired"

class ReminderCreate(BaseModel):
    """Model for creating a new reminder"""
    title: str = Field(..., description="Reminder title")
    description: Optional[str] = Field(None, description="Detailed description")
    trigger_time: str = Field(..., description="ISO 8601 timestamp when to trigger")
    related_intel_file: Optional[str] = Field(None, description="Related intel file path")
    callback_url: Optional[str] = Field(None, description="Webhook to call when triggered")
    recurrence_rule: Optional[str] = Field(None, description="Cron-like recurrence (future)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata (JSON)")

class Reminder(BaseModel):
    """Full reminder model"""
    id: int
    title: str
    description: Optional[str]
    trigger_time: str
    status: ReminderStatus
    created_at: str
    triggered_at: Optional[str]
    acknowledged_at: Optional[str]
    spoken: bool
    spoken_at: Optional[str]
    related_intel_file: Optional[str]
    callback_url: Optional[str]
    recurrence_rule: Optional[str]
    metadata: Optional[str]  # JSON string from DB

class ReminderResponse(BaseModel):
    """API response for reminder operations"""
    ok: bool
    reminder_id: Optional[int] = None
    reminder: Optional[Reminder] = None
    reminders: Optional[list[Reminder]] = None
    message: Optional[str] = None

