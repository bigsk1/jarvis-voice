#!/usr/bin/env python3
"""
Create Reminder Tool
Creates time-based reminders that trigger TTS notifications.

Input: {
    "title": "Reminder title",
    "description": "Optional details",
    "when": "Natural time expression (e.g., 'in 4 hours', 'tomorrow at 3pm', 'in 30 minutes')"
}

Output: {
    "ok": bool,
    "speech": str,
    "data": {
        "reminder_id": int,
        "trigger_time": str,
        "trigger_time_local": str
    }
}
"""

import json
import os
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import (
    config_override_scope,
    config_scope,
    get_active_config_mode,
    get_config_value,
    get_scoped_config,
    load_config,
)
from memory_db import MemoryDB
from reminder_feedback import reminder_schedule_rejection
from reminder_schedule import explicit_schedule_timezone, resolve_schedule
from time_utils import (
    ensure_local,
    format_utc_db,
    format_utc_z,
    get_app_timezone,
    now_local,
    now_utc,
)


def sync_to_google_calendar(reminder_id: int, title: str, description: str, 
                            trigger_time_utc: datetime, recurrence_rule: str = None) -> dict | None:
    """Sync reminder to Google Calendar via n8n webhook.
    
    Args:
        reminder_id: Jarvis reminder ID
        title: Reminder title
        description: Reminder description
        trigger_time_utc: Trigger time in UTC
        recurrence_rule: Optional recurrence rule (WEEKLY:2, MONTHLY:10)
        
    Returns:
        dict with gcal_event_id if successful, None otherwise
    """
    webhook_url = get_config_value('N8N_JARVIS_WEBHOOK_URL')
    
    if not webhook_url:
        # n8n sync not configured, skip silently
        return None
    
    try:
        # Format time as ISO 8601 with Z suffix to indicate UTC
        # This ensures n8n/Google Calendar interprets the time correctly
        trigger_time_iso = format_utc_z(trigger_time_utc)
        
        payload = {
            "action": "create",
            "reminder": {
                "id": reminder_id,
                "title": title,
                "description": description or "",
                "trigger_time": trigger_time_iso,
                "recurrence_rule": recurrence_rule
            }
        }
        
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10
        )
        
        if response.ok:
            result = response.json()
            return result
        else:
            # Log error but don't fail the reminder creation
            print(f"Warning: Google Calendar sync failed: {response.status_code}", file=sys.stderr)
            return None
            
    except Exception as e:
        # Log error but don't fail the reminder creation
        print(f"Warning: Google Calendar sync error: {e}", file=sys.stderr)
        return None

def parse_time_expression(
    when: str,
    default_hour: int = 10,
    *,
    schedule: dict | None = None,
    reference_time: datetime | None = None,
):
    """Resolve the complete schedule against one captured local clock."""
    return resolve_schedule(
        when, now=reference_time if reference_time is not None else now_local(),
        default_hour=default_hour, schedule=schedule,
    )


def format_local_time(dt: datetime) -> str:
    """Format datetime in human-readable local time."""
    dt = ensure_local(dt, get_app_timezone())
    if dt.year != now_local().year:
        return dt.strftime("%A, %B %d, %Y at %I:%M %p %Z")
    return dt.strftime("%A, %B %d at %I:%M %p %Z")


def _parse_db_timestamp(value: str | None) -> datetime | None:
    """Parse timestamp values stored in SQLite."""
    if not value:
        return None
    normalized = value.strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def find_existing_reminder(cursor, title: str, trigger_time_utc: datetime, recurrence_rule: str = None):
    """Return an active matching reminder to suppress accidental duplicates."""
    normalized_title = title.strip().lower()
    trigger_time_db = format_utc_db(trigger_time_utc)
    cursor.execute("""
        SELECT id, title, description, trigger_time, status, recurrence_rule, created_at, metadata
        FROM reminders
        WHERE lower(trim(title)) = ?
          AND trigger_time = ?
          AND COALESCE(recurrence_rule, '') = COALESCE(?, '')
          AND status IN ('scheduled', 'triggered')
        ORDER BY id DESC
        LIMIT 1
    """, (
        normalized_title,
        trigger_time_db,
        recurrence_rule
    ))
    row = cursor.fetchone()
    if not row:
        return None

    created_at = _parse_db_timestamp(row[6])
    duplicate_recent = False
    if created_at is not None:
        duplicate_recent = (now_utc() - created_at.astimezone(timezone.utc)) <= timedelta(minutes=10)

    return {
        "reminder_id": row[0],
        "title": row[1],
        "description": row[2] or "",
        "trigger_time": row[3],
        "status": row[4],
        "recurrence_rule": row[5],
        "created_at": row[6],
        "metadata": row[7],
        "duplicate_recent": duplicate_recent,
    }


def create_single_reminder(title: str, description: str, trigger_time_local: datetime,
                           recurrence_rule: str = None, db_path: str = None,
                           schedule_context: dict | None = None):
    """Create a single reminder in the database and sync to Google Calendar.
    
    Returns: dict with reminder details
    """
    import sqlite3
    
    # Convert to UTC for storage using the configured local timezone.
    trigger_time_local = ensure_local(trigger_time_local, get_app_timezone())
    trigger_time_utc = trigger_time_local.astimezone(timezone.utc)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    existing = find_existing_reminder(
        cursor=cursor,
        title=title,
        trigger_time_utc=trigger_time_utc,
        recurrence_rule=recurrence_rule
    )
    if existing:
        conn.close()
        saved_utc = _parse_db_timestamp(existing['trigger_time'])
        assert saved_utc is not None
        saved_local = saved_utc.astimezone(get_app_timezone())
        return {
            "reminder_id": existing["reminder_id"],
            "trigger_time": existing["trigger_time"],
            "trigger_time_local": saved_local.isoformat(),
            "formatted_time": format_local_time(saved_local),
            "recurring": recurrence_rule is not None,
            "recurrence_rule": recurrence_rule,
            "gcal_synced": False,
            "duplicate_suppressed": True,
            "duplicate_recent": existing["duplicate_recent"],
        }
    
    cursor.execute("""
        INSERT INTO reminders (
            title, description, trigger_time, status,
            created_at, spoken, spoken_at, triggered_at,
            acknowledged_at, callback_url, recurrence_rule,
            related_intel_file, metadata
        ) VALUES (?, ?, ?, 'scheduled', ?, 0, NULL, NULL, NULL, NULL, ?, NULL, ?)
    """, (
        title,
        description,
        format_utc_db(trigger_time_utc),
        now_utc().isoformat(),
        recurrence_rule,
        json.dumps(schedule_context) if schedule_context else None,
    ))
    
    reminder_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # Sync to Google Calendar via n8n
    gcal_result = sync_to_google_calendar(
        reminder_id=reminder_id,
        title=title,
        description=description,
        trigger_time_utc=trigger_time_utc,
        recurrence_rule=recurrence_rule
    )
    
    # If sync succeeded, update reminder metadata
    gcal_synced = False
    gcal_event_id = None
    if gcal_result and gcal_result.get('ok'):
        gcal_event_id = gcal_result.get('gcal_event_id')
        if gcal_event_id:
            gcal_synced = True
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            metadata_fields = {
                **(schedule_context or {}),
                "gcal_event_id": gcal_event_id,
                "gcal_synced": True,
                "gcal_synced_at": now_utc().isoformat()
            }
            if gcal_result.get('gcal_calendar_id'):
                metadata_fields['gcal_calendar_id'] = gcal_result['gcal_calendar_id']
            metadata = json.dumps(metadata_fields)
            cursor.execute("UPDATE reminders SET metadata = ? WHERE id = ?", (metadata, reminder_id))
            conn.commit()
            conn.close()
    
    return {
        "reminder_id": reminder_id,
        "trigger_time": format_utc_db(trigger_time_utc),
        "trigger_time_local": trigger_time_local.isoformat(),
        "formatted_time": format_local_time(trigger_time_local),
        "recurring": recurrence_rule is not None,
        "recurrence_rule": recurrence_rule,
        "gcal_synced": gcal_synced,
        "duplicate_suppressed": False,
        # Note: gcal_event_id intentionally excluded from response to prevent
        # LLM from speaking the long ID. It's stored in the database for sync purposes.
    }


def _require_reminder_timezone(when: str, scopes: ExitStack) -> bool:
    """Require a configured zone or a usable explicit zone for this request only."""
    configured = get_config_value('JARVIS_TIMEZONE')
    if isinstance(configured, str) and configured.strip():
        try:
            ZoneInfo(configured)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("The configured reminder timezone is invalid; check JARVIS_TIMEZONE") from error
        return True
    explicit = explicit_schedule_timezone(when)
    timezone_name = getattr(explicit, 'key', None)
    if explicit == timezone.utc or str(explicit).upper() in {'UTC', 'GMT'}:
        timezone_name = 'UTC'
    if not timezone_name:
        raise ValueError(
            "No reminder timezone is configured; configure JARVIS_TIMEZONE "
            "or specify an IANA timezone"
        )
    overrides = {'JARVIS_TIMEZONE': timezone_name}
    if get_scoped_config() is None:
        scopes.enter_context(config_scope(get_active_config_mode(), overrides=overrides))
    else:
        scopes.enter_context(config_override_scope(overrides))
    return False


def _run_main(scopes: ExitStack):
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()
        
        # Extract parameters
        title = args.get('title')
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        
        description = args.get('description', '')
        when = args.get('when')
        
        # Resolve and validate the entire plan before opening the DB or syncing Calendar.
        reference_time = now_utc()
        try:
            timezone_is_configured = _require_reminder_timezone(when, scopes)
            reference_time = now_local()
            schedule_context: dict = {
                'schedule_reference_time': reference_time.isoformat(),
                'schedule_timezone': str(get_app_timezone()),
                'requested_when': when,
            }
            if 'schedule' in args:
                schedule_context['requested_schedule'] = args['schedule']
            trigger_result, recurrence_rule = parse_time_expression(
                when, schedule=args.get('schedule'), reference_time=reference_time,
            )
            if recurrence_rule and not timezone_is_configured:
                raise ValueError(
                    "No reminder timezone is configured; recurring reminders require persistent JARVIS_TIMEZONE "
                    "so later occurrences preserve the requested timezone"
                )
        except ValueError as error:
            print(json.dumps(reminder_schedule_rejection(
                str(error), when=when, reference_time=reference_time,
            )))
            sys.exit(1)
        
        # Get database path
        db = MemoryDB()
        db_path = db.db_path
        
        # Check if we have multiple datetimes (multi-day pattern)
        if isinstance(trigger_result, list):
            # Create multiple individual reminders
            reminders_created = []
            gcal_synced_count = 0
            
            for trigger_time_local in trigger_result:
                result = create_single_reminder(
                    title=title,
                    description=description,
                    trigger_time_local=trigger_time_local,
                    recurrence_rule=None,  # Individual reminders, not recurring
                    db_path=db_path,
                    schedule_context=schedule_context,
                )
                result.update(schedule_context)
                reminders_created.append(result)
                if result.get('gcal_synced'):
                    gcal_synced_count += 1
            
            # Format response for multiple reminders
            num_reminders = len(reminders_created)
            reused_count = sum(bool(reminder.get('duplicate_suppressed')) for reminder in reminders_created)
            created_count = num_reminders - reused_count
            first_date = reminders_created[0]['formatted_time']
            last_date = reminders_created[-1]['formatted_time']
            
            if reused_count == num_reminders:
                speech = f"Active reminders already exist for '{title}': {first_date} through {last_date}"
            elif reused_count:
                created_label = 'reminder' if created_count == 1 else 'reminders'
                speech = f"Created {created_count} {created_label} and reused {reused_count} existing reminders for '{title}': {first_date} through {last_date}"
            else:
                speech = f"Created {num_reminders} reminders for '{title}': {first_date} through {last_date}"
            if gcal_synced_count > 0:
                speech += f". All {gcal_synced_count} added to Google Calendar."
            
            print(json.dumps({
                "ok": True,
                "speech": speech,
                "data": {
                    # Legacy field counts all requested occurrences, including reuse.
                    "reminders_created": num_reminders,
                    "newly_created_count": created_count,
                    "reminders_reused": reused_count,
                    "reminders_total": num_reminders,
                    "reminders": reminders_created,
                    "first_reminder": reminders_created[0],
                    "last_reminder": reminders_created[-1],
                    "gcal_synced_count": gcal_synced_count,
                    **schedule_context,
                }
            }))
        else:
            # Single reminder (original behavior)
            trigger_time_local = trigger_result
            
            result = create_single_reminder(
                title=title,
                description=description,
                trigger_time_local=trigger_time_local,
                recurrence_rule=recurrence_rule,
                db_path=db_path,
                schedule_context=schedule_context,
            )
            result.update(schedule_context)
            
            # Format response
            if result.get('duplicate_suppressed'):
                speech = f"Active reminder already exists for {result['formatted_time']}: {title}"
            elif recurrence_rule:
                speech = f"Recurring reminder set: {title}. First trigger {result['formatted_time']}"
            else:
                speech = f"Reminder set for {result['formatted_time']}: {title}"
            
            if result.get('gcal_synced'):
                speech += ". Also added to Google Calendar."
            
            print(json.dumps({
                "ok": True,
                "speech": speech,
                "data": result
            }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to create reminder: {e}"
        }))
        sys.exit(1)


def main():
    with ExitStack() as scopes:
        _run_main(scopes)


if __name__ == "__main__":
    main()
