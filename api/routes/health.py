"""Health and status endpoints"""

from fastapi import APIRouter
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.managers.alert_manager import AlertManager

router = APIRouter(prefix="/api", tags=["health"])

# Track startup time
startup_time = time.time()

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "jarvis-api",
        "version": "1.0.0"
    }

@router.get("/status")
async def get_status():
    """Get system status"""
    import os
    alert_manager = AlertManager()
    
    pending_alerts = alert_manager.get_pending_count()
    uptime = int(time.time() - startup_time)
    
    # Get database path for verification
    db_path = str(alert_manager.db.db_path)
    
    return {
        "status": "running",
        "uptime_seconds": uptime,
        "pending_alerts": pending_alerts,
        "mode": alert_manager.mode,
        "database": db_path,
        "env_mode": os.environ.get('JARVIS_API_MODE', 'not set'),
        "llm_provider": os.environ.get('LLM_PROVIDER', 'not set')
    }

