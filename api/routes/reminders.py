"""Reminder API endpoints"""

from fastapi import APIRouter, HTTPException, Query
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
    status: ReminderStatus | None = Query(None, description="Filter by status"),
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

@router.post("/{reminder_id}/acknowledge", response_model=ReminderResponse)
async def acknowledge_reminder(reminder_id: int):
    """Acknowledge a triggered reminder"""
    success = reminder_manager.acknowledge_reminder(reminder_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Reminder {reminder_id} not found")
    
    return ReminderResponse(
        ok=True,
        message=f"Reminder {reminder_id} acknowledged"
    )

@router.post("/acknowledge-all", response_model=ReminderResponse)
async def acknowledge_all_reminders(
    status: ReminderStatus | None = Query(None, description="Filter by status (default: triggered)")
):
    """Acknowledge all reminders matching filter
    
    Useful for commands like "Hey Jarvis, clear all triggered reminders"
    """
    count = reminder_manager.acknowledge_all(
        status=status.value if status else None
    )
    
    return ReminderResponse(
        ok=True,
        message=f"Acknowledged {count} reminder(s)"
    )

@router.put("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(reminder_id: int, reminder: ReminderCreate):
    """Update an existing reminder (for n8n sync)"""
    try:
        success = reminder_manager.update_reminder(
            reminder_id=reminder_id,
            title=reminder.title,
            description=reminder.description,
            trigger_time=reminder.trigger_time,
            related_intel_file=reminder.related_intel_file,
            callback_url=reminder.callback_url,
            recurrence_rule=reminder.recurrence_rule,
            metadata=reminder.metadata
        )
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Reminder {reminder_id} not found")
        
        updated_reminder = reminder_manager.get_reminder(reminder_id)
        
        return ReminderResponse(
            ok=True,
            reminder=Reminder(**updated_reminder) if updated_reminder else None,
            message=f"Reminder {reminder_id} updated"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/by-gcal/{gcal_event_id}", response_model=ReminderResponse)
async def get_reminder_by_gcal_id(gcal_event_id: str):
    """Find a reminder by Google Calendar event ID
    
    Used by n8n to find Jarvis reminders when GCal events are updated/cancelled.
    """
    reminder = reminder_manager.find_by_gcal_event_id(gcal_event_id)
    
    if not reminder:
        raise HTTPException(status_code=404, detail=f"No reminder found with gcal_event_id: {gcal_event_id}")
    
    return ReminderResponse(
        ok=True,
        reminder=Reminder(**reminder)
    )

@router.delete("/by-gcal/{gcal_event_id}", response_model=ReminderResponse)
async def cancel_reminder_by_gcal_id(gcal_event_id: str):
    """Cancel a reminder by Google Calendar event ID
    
    Used by n8n when a Google Calendar event is deleted.
    """
    reminder = reminder_manager.find_by_gcal_event_id(gcal_event_id)
    
    if not reminder:
        raise HTTPException(status_code=404, detail=f"No reminder found with gcal_event_id: {gcal_event_id}")
    
    reminder_manager.cancel_reminder(reminder['id'])
    
    return ReminderResponse(
        ok=True,
        message=f"Reminder {reminder['id']} canceled (gcal_event_id: {gcal_event_id})"
    )

@router.put("/by-gcal/{gcal_event_id}", response_model=ReminderResponse)
async def update_reminder_by_gcal_id(gcal_event_id: str, reminder: ReminderCreate):
    """Update a reminder by Google Calendar event ID
    
    Used by n8n when a Google Calendar event is modified.
    """
    existing = reminder_manager.find_by_gcal_event_id(gcal_event_id)
    
    if not existing:
        raise HTTPException(status_code=404, detail=f"No reminder found with gcal_event_id: {gcal_event_id}")
    
    try:
        reminder_manager.update_reminder(
            reminder_id=existing['id'],
            title=reminder.title,
            description=reminder.description,
            trigger_time=reminder.trigger_time,
            related_intel_file=reminder.related_intel_file,
            callback_url=reminder.callback_url,
            recurrence_rule=reminder.recurrence_rule,
            metadata=reminder.metadata
        )
        
        updated_reminder = reminder_manager.get_reminder(existing['id'])
        
        return ReminderResponse(
            ok=True,
            reminder=Reminder(**updated_reminder) if updated_reminder else None,
            message=f"Reminder {existing['id']} updated (gcal_event_id: {gcal_event_id})"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
