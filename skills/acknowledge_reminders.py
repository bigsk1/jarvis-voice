#!/usr/bin/env python3
"""
Acknowledge Reminders Tool
Mark reminders as acknowledged/completed.

Input: {
    "reminder_ids": [1, 2, 3],  # List of reminder IDs to acknowledge
    "all_triggered": false  # Optional: acknowledge ALL triggered reminders
}

Output: {
    "ok": bool,
    "speech": str,
    "data": {
        "acknowledged_count": int,
        "acknowledged_ids": [...]
    }
}
"""

import sys
import os
import json
import sqlite3
from datetime import datetime, timezone

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config
from memory_db import MemoryDB

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
        reminder_ids = args.get('reminder_ids', [])
        all_triggered = args.get('all_triggered', False)
        
        if not reminder_ids and not all_triggered:
            raise ValueError("Either 'reminder_ids' or 'all_triggered' must be specified")
        
        # Connect to database
        db = MemoryDB()
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        
        now = datetime.now(timezone.utc).isoformat()
        acknowledged_ids = []
        
        if all_triggered:
            # Acknowledge all pending reminders (triggered or scheduled)
            cursor.execute("""
                UPDATE reminders
                SET status = 'acknowledged',
                    acknowledged_at = ?
                WHERE status IN ('triggered', 'scheduled')
            """, (now,))
            
            # Get IDs that were updated
            cursor.execute("""
                SELECT id FROM reminders
                WHERE status = 'acknowledged'
                AND acknowledged_at = ?
            """, (now,))
            
            acknowledged_ids = [row[0] for row in cursor.fetchall()]
        else:
            # Acknowledge specific reminders
            for reminder_id in reminder_ids:
                cursor.execute("""
                    UPDATE reminders
                    SET status = 'acknowledged',
                        acknowledged_at = ?
                    WHERE id = ?
                    AND status IN ('scheduled', 'triggered')
                """, (now, reminder_id))
                
                if cursor.rowcount > 0:
                    acknowledged_ids.append(reminder_id)
        
        conn.commit()
        conn.close()
        
        # Generate speech
        count = len(acknowledged_ids)
        
        if count == 0:
            speech = "No reminders were acknowledged. They may have already been completed or don't exist."
        elif count == 1:
            speech = f"Acknowledged 1 reminder (ID: {acknowledged_ids[0]})."
        else:
            speech = f"Acknowledged {count} reminders."
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": {
                "acknowledged_count": count,
                "acknowledged_ids": acknowledged_ids
            }
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to acknowledge reminders: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

