"""Alert Pydantic models"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
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
    description: Optional[str] = Field(None, description="Detailed description")
    severity: AlertSeverity = Field(AlertSeverity.MEDIUM, description="Alert severity level")
    source: str = Field(..., description="Source system (e.g., uptime_kuma, coolify)")
    auto_resolve_url: Optional[str] = Field(None, description="URL to check for auto-resolution")
    auto_resolve_check_interval: int = Field(300, description="Seconds between auto-resolve checks")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata (JSON)")
    related_intel_file: Optional[str] = Field(None, description="Related intel file path")

class AlertUpdate(BaseModel):
    """Model for updating an alert"""
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[AlertSeverity] = None
    status: Optional[AlertStatus] = None
    metadata: Optional[Dict[str, Any]] = None

class Alert(BaseModel):
    """Full alert model"""
    id: int
    title: str
    description: Optional[str]
    severity: AlertSeverity
    source: str
    status: AlertStatus
    created_at: str
    updated_at: Optional[str]
    acknowledged_at: Optional[str]
    resolved_at: Optional[str]
    spoken: bool
    spoken_at: Optional[str]
    follow_up_count: int
    last_follow_up: Optional[str]
    auto_resolve_url: Optional[str]
    auto_resolve_check_interval: int
    last_check_at: Optional[str]
    metadata: Optional[str]  # JSON string from DB
    related_intel_file: Optional[str]

class AlertResponse(BaseModel):
    """API response for alert operations"""
    ok: bool
    alert_id: Optional[int] = None
    alert: Optional[Alert] = None
    alerts: Optional[list[Alert]] = None
    message: Optional[str] = None

