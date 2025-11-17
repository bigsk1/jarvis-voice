"""Alert API endpoints"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.models.alert import AlertCreate, AlertUpdate, Alert, AlertResponse, AlertSeverity, AlertStatus
from api.managers.alert_manager import AlertManager

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Initialize manager
alert_manager = AlertManager()

@router.post("", response_model=AlertResponse)
@router.post("/", response_model=AlertResponse, include_in_schema=False)
async def create_alert(alert: AlertCreate):
    """
    Create a new alert (generic webhook endpoint)
    
    This endpoint accepts webhooks from ANY source:
    - Uptime Kuma
    - Coolify
    - Custom bash scripts
    - Cron jobs
    - HomeAssistant
    - n8n workflows
    - Any monitoring system
    
    Required fields:
    - title: Alert title
    - source: Source system name (e.g., "uptime_kuma", "coolify", "custom_script")
    
    Optional fields:
    - description: Detailed info
    - severity: low, medium, high, critical
    - auto_resolve_url: URL to check for auto-resolution
    - metadata: Any additional data (JSON object)
    
    Example webhook payloads:
    
    Uptime Kuma:
    ```json
    {
      "title": "Web Server Down",
      "description": "example.com not responding",
      "severity": "high",
      "source": "uptime_kuma",
      "auto_resolve_url": "https://example.com",
      "metadata": {"monitor_id": "123"}
    }
    ```
    
    Coolify:
    ```json
    {
      "title": "Deployment Failed",
      "description": "myapp build failed",
      "severity": "high",
      "source": "coolify"
    }
    ```
    
    Custom Script:
    ```json
    {
      "title": "Disk Space Low",
      "description": "/dev/sda1 at 95%",
      "severity": "medium",
      "source": "cron_disk_check",
      "metadata": {"disk": "/dev/sda1", "usage": 95}
    }
    ```
    """
    try:
        alert_id = alert_manager.create_alert(
            title=alert.title,
            description=alert.description,
            severity=alert.severity.value,
            source=alert.source,
            auto_resolve_url=alert.auto_resolve_url,
            auto_resolve_check_interval=alert.auto_resolve_check_interval,
            metadata=alert.metadata,
            related_intel_file=alert.related_intel_file,
            speak_immediately=True
        )
        
        created_alert = alert_manager.get_alert(alert_id)
        
        return AlertResponse(
            ok=True,
            alert_id=alert_id,
            alert=Alert(**created_alert) if created_alert else None,
            message=f"Alert created (ID: {alert_id})"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("", response_model=AlertResponse)
@router.get("/", response_model=AlertResponse, include_in_schema=False)
async def list_alerts(
    status: Optional[AlertStatus] = Query(None, description="Filter by status"),
    severity: Optional[AlertSeverity] = Query(None, description="Filter by severity"),
    source: Optional[str] = Query(None, description="Filter by source"),
    limit: int = Query(100, description="Maximum number of results")
):
    """List alerts with optional filters"""
    try:
        alerts = alert_manager.list_alerts(
            status=status.value if status else None,
            severity=severity.value if severity else None,
            source=source,
            limit=limit
        )
        
        return AlertResponse(
            ok=True,
            alerts=[Alert(**a) for a in alerts],
            message=f"Found {len(alerts)} alert(s)"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: int):
    """Get a specific alert by ID"""
    alert = alert_manager.get_alert(alert_id)
    
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    
    return AlertResponse(
        ok=True,
        alert=Alert(**alert)
    )

@router.put("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(alert_id: int):
    """Acknowledge an alert (mark as resolved by user)"""
    success = alert_manager.acknowledge_alert(alert_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    
    return AlertResponse(
        ok=True,
        message=f"Alert {alert_id} acknowledged"
    )

@router.post("/acknowledge-all", response_model=AlertResponse)
async def acknowledge_all_alerts(
    status: Optional[AlertStatus] = Query(None, description="Filter by status (default: pending)"),
    severity: Optional[AlertSeverity] = Query(None, description="Filter by severity")
):
    """Acknowledge multiple alerts at once
    
    Useful for commands like "Hey Jarvis, clear all pending alerts"
    """
    count = alert_manager.acknowledge_all(
        status=status.value if status else None,
        severity=severity.value if severity else None
    )
    
    return AlertResponse(
        ok=True,
        message=f"Acknowledged {count} alert(s)"
    )

@router.delete("/{alert_id}", response_model=AlertResponse)
async def cancel_alert(alert_id: int):
    """Cancel/delete an alert"""
    success = alert_manager.cancel_alert(alert_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    
    return AlertResponse(
        ok=True,
        message=f"Alert {alert_id} canceled"
    )

@router.post("/{alert_id}/check", response_model=AlertResponse)
async def check_auto_resolve(alert_id: int):
    """Manually trigger auto-resolve check for an alert"""
    resolved = alert_manager.check_auto_resolve(alert_id)
    
    if resolved:
        return AlertResponse(
            ok=True,
            message=f"Alert {alert_id} auto-resolved"
        )
    else:
        return AlertResponse(
            ok=True,
            message=f"Alert {alert_id} still active (not resolved)"
        )

