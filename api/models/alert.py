"""Alert Pydantic models"""

from pydantic import BaseModel, Field
from typing import Any
from enum import Enum

class AlertSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class AlertStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    AUTO_RESOLVED = "auto_resolved"
    CANCELED = "canceled"

class AlertCreate(BaseModel):
    """Model for creating a new alert"""
    title: str = Field(..., description="Alert title")
    description: str | None = Field(None, description="Detailed description")
    severity: AlertSeverity = Field(AlertSeverity.HIGH, description="Alert severity level")
    source: str = Field(..., description="Source system (e.g., uptime_kuma, coolify)")
    auto_resolve_url: str | None = Field(None, description="URL to check for auto-resolution")
    auto_resolve_check_interval: int = Field(300, description="Seconds between auto-resolve checks")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata (JSON)")
    related_intel_file: str | None = Field(None, description="Related intel file path")

class AlertUpdate(BaseModel):
    """Model for updating an alert"""
    title: str | None = None
    description: str | None = None
    severity: AlertSeverity | None = None
    status: AlertStatus | None = None
    metadata: dict[str, Any] | None = None

class Alert(BaseModel):
    """Full alert model"""
    id: int
    title: str
    description: str | None
    severity: AlertSeverity
    source: str
    status: AlertStatus
    created_at: str
    updated_at: str | None
    acknowledged_at: str | None
    resolved_at: str | None
    spoken: bool
    spoken_at: str | None
    follow_up_count: int
    last_follow_up: str | None
    auto_resolve_url: str | None
    auto_resolve_check_interval: int
    last_check_at: str | None
    metadata: str | None  # JSON string from DB
    related_intel_file: str | None

class AlertResponse(BaseModel):
    """API response for alert operations"""
    ok: bool
    alert_id: int | None = None
    alert: Alert | None = None
    alerts: list[Alert] | None = None
    message: str | None = None
    duplicate_suppressed: bool | None = None
