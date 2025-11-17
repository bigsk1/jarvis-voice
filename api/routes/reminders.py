"""Reminder API endpoints"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.models.reminder import ReminderCreate, Reminder, ReminderResponse, ReminderStatus
from api.managers.reminder_manager import ReminderManager

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

reminder_manager = ReminderManager()

@router.post("", response_model=ReminderResponse)
@router.post("/", response_model=ReminderResponse, include_in_schema=False)
async def create_reminder(reminder: ReminderCreate):
    """Create a new reminder"""
    try:
        reminder_id = reminder_manager.create_reminder(
            title=reminder.title,
            description=reminder.description,
            trigger_time=reminder.trigger_time,
            related_intel_file=reminder.related_intel_file,
            callback_url=reminder.callback_url,
            recurrence_rule=reminder.recurrence_rule,
            metadata=reminder.metadata
        )
        
        created_reminder = reminder_manager.get_reminder(reminder_id)
        
        return ReminderResponse(
            ok=True,
            reminder_id=reminder_id,
            reminder=Reminder(**created_reminder) if created_reminder else None,
            message=f"Reminder created (ID: {reminder_id})"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("", response_model=ReminderResponse)
@router.get("/", response_model=ReminderResponse, include_in_schema=False)
async def list_reminders(
    status: Optional[ReminderStatus] = Query(None, description="Filter by status"),
    limit: int = Query(100, description="Maximum number of results")
):
    """List reminders"""
    try:
        reminders = reminder_manager.list_reminders(
            status=status.value if status else None,
            limit=limit
        )
        
        return ReminderResponse(
            ok=True,
            reminders=[Reminder(**r) for r in reminders],
            message=f"Found {len(reminders)} reminder(s)"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{reminder_id}", response_model=ReminderResponse)
async def get_reminder(reminder_id: int):
    """Get a specific reminder by ID"""
    reminder = reminder_manager.get_reminder(reminder_id)
    
    if not reminder:
        raise HTTPException(status_code=404, detail=f"Reminder {reminder_id} not found")
    
    return ReminderResponse(
        ok=True,
        reminder=Reminder(**reminder)
    )

@router.delete("/{reminder_id}", response_model=ReminderResponse)
async def cancel_reminder(reminder_id: int):
    """Cancel a reminder"""
    success = reminder_manager.cancel_reminder(reminder_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Reminder {reminder_id} not found")
    
    return ReminderResponse(
        ok=True,
        message=f"Reminder {reminder_id} canceled"
    )

