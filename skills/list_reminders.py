#!/usr/bin/env python3
"""
List Reminders Tool
Query reminders by status and time range.

Input: {
    "status": "scheduled|triggered|acknowledged|all",  # optional, default "all"
    "limit": 10  # optional, default 10
}

Output: {
    "ok": bool,
    "speech": str,
    "data": {
        "reminders": [...]
    }
}
"""

import sys
import os
import json
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB

def format_time_relative(trigger_time_str: str) -> str:
    """Format trigger time as relative time (e.g., 'in 2 hours', '5 minutes ago')."""
    try:
        trigger_time = datetime.fromisoformat(trigger_time_str.replace('Z', '+00:00'))
        
        # Convert to naive UTC for comparison
        if trigger_time.tzinfo:
            trigger_time = trigger_time.replace(tzinfo=None)
        
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        delta = trigger_time - now
        
        if delta.total_seconds() < 0:
            # Past
            seconds = abs(delta.total_seconds())
            if seconds < 60:
                return "just now"
            elif seconds < 3600:
                mins = int(seconds / 60)
                return f"{mins} minute{'s' if mins != 1 else ''} ago"
            elif seconds < 86400:
                hours = int(seconds / 3600)
                return f"{hours} hour{'s' if hours != 1 else ''} ago"
            else:
                days = int(seconds / 86400)
                return f"{days} day{'s' if days != 1 else ''} ago"
        else:
            # Future
            seconds = delta.total_seconds()
            if seconds < 60:
                return "in less than a minute"
            elif seconds < 3600:
                mins = int(seconds / 60)
                return f"in {mins} minute{'s' if mins != 1 else ''}"
            elif seconds < 86400:
                hours = int(seconds / 3600)
                return f"in {hours} hour{'s' if hours != 1 else ''}"
            else:
                days = int(seconds / 86400)
                return f"in {days} day{'s' if days != 1 else ''}"
    except:
        return trigger_time_str


def format_trigger_time_local(trigger_time_str: str, tz: ZoneInfo) -> str:
    """Convert UTC trigger_time to a human-readable local time string."""
    try:
        trigger_time = datetime.fromisoformat(trigger_time_str.replace('Z', '+00:00'))
        if trigger_time.tzinfo is None:
            trigger_time = trigger_time.replace(tzinfo=timezone.utc)
        local_time = trigger_time.astimezone(tz)
        return local_time.strftime('%A, %B %d, %Y at %I:%M %p %Z')
    except:
        return trigger_time_str


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()
        
        # Extract parameters
        status_filter = args.get('status', 'all').lower()
        limit = args.get('limit', 10)
        
        # Valid statuses
        valid_statuses = ['scheduled', 'triggered', 'acknowledged', 'all']
        if status_filter not in valid_statuses:
            raise ValueError(f"status must be one of: {', '.join(valid_statuses)}")
        
        # Query database
        db = MemoryDB()
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Build query
        if status_filter == 'all':
            query = """
                SELECT * FROM reminders
                ORDER BY trigger_time ASC
                LIMIT ?
            """
            params = (limit,)
        else:
            query = """
                SELECT * FROM reminders
                WHERE status = ?
                ORDER BY trigger_time ASC
                LIMIT ?
            """
            params = (status_filter, limit)
        
        rows = cursor.execute(query, params).fetchall()
        conn.close()
        
        # Get local timezone for display
        local_tz = ZoneInfo(get_config_value("JARVIS_TIMEZONE", "America/Los_Angeles"))
        
        # Format reminders
        reminders = []
        for row in rows:
            reminder = dict(row)
            reminder['relative_time'] = format_time_relative(reminder['trigger_time'])
            reminder['trigger_time_local'] = format_trigger_time_local(reminder['trigger_time'], local_tz)
            reminders.append(reminder)
        
        # Generate speech
        if not reminders:
            speech = "You have no reminders"
            if status_filter != 'all':
                speech += f" with status '{status_filter}'"
            speech += "."
        else:
            count = len(reminders)
            
            # Group by status for summary
            scheduled = [r for r in reminders if r['status'] == 'scheduled']
            triggered = [r for r in reminders if r['status'] == 'triggered']
            
            if status_filter == 'all':
                # Highlight triggered (missed) reminders first
                if triggered:
                    if len(triggered) == 1:
                        t = triggered[0]
                        speech = f"Yes, you have 1 missed reminder: '{t['title']}' from {t['relative_time']}. "
                    else:
                        speech = f"Yes, you have {len(triggered)} missed reminders. "
                        speech += f"Most recent: '{triggered[0]['title']}' from {triggered[0]['relative_time']}. "
                    
                    # Add scheduled info if any
                    if scheduled:
                        speech += f"You also have {len(scheduled)} upcoming reminder{'s' if len(scheduled) != 1 else ''}."
                else:
                    # No triggered, just scheduled
                    if scheduled:
                        speech = f"No missed reminders. You have {len(scheduled)} upcoming reminder{'s' if len(scheduled) != 1 else ''}. "
                        next_reminder = scheduled[0]
                        speech += f"Next: '{next_reminder['title']}' {next_reminder['relative_time']}."
                    else:
                        speech = "You have no active reminders."
            else:
                # Specific status filter
                if status_filter == 'triggered':
                    # User specifically asked for triggered/missed reminders
                    if count == 1:
                        r = reminders[0]
                        speech = f"You have 1 missed reminder: '{r['title']}' from {r['relative_time']}."
                    else:
                        speech = f"You have {count} missed reminders. "
                        speech += f"Most recent: '{reminders[0]['title']}' from {reminders[0]['relative_time']}."
                else:
                    speech = f"Found {count} {status_filter} reminder{'s' if count != 1 else ''}"
                    if count > 0:
                        first = reminders[0]
                        speech += f". First: '{first['title']}' {first['relative_time']}."
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": {
                "reminders": reminders,
                "count": len(reminders)
            }
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to list reminders: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

