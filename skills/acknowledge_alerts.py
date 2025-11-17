#!/usr/bin/env python3
"""
Tool Name: acknowledge_alerts
Acknowledge/clear alerts from the proactive API system
Input: { "alert_id": 123, "clear_all": true }
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from memory_db import MemoryDB

def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        alert_id = args.get('alert_id')
        clear_all = args.get('clear_all', False)
        
        # Get database (auto-detects mode)
        db = MemoryDB()
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        if clear_all:
            # Acknowledge all pending alerts
            cursor.execute("""
                UPDATE alerts 
                SET status = 'acknowledged', acknowledged_at = ?, updated_at = ?
                WHERE status = 'pending'
            """, (now, now))
            count = cursor.rowcount
            conn.commit()
            conn.close()
            
            if count == 0:
                speech = "No pending alerts to clear."
            elif count == 1:
                speech = "Cleared 1 alert."
            else:
                speech = f"Cleared {count} alerts."
            
            print(json.dumps({
                "ok": True,
                "speech": speech,
                "data": {
                    "cleared_count": count
                }
            }))
        
        elif alert_id:
            # Acknowledge specific alert
            cursor.execute("""
                UPDATE alerts 
                SET status = 'acknowledged', acknowledged_at = ?, updated_at = ?
                WHERE id = ?
            """, (now, now, alert_id))
            
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            
            if success:
                speech = f"Alert {alert_id} acknowledged."
            else:
                speech = f"Alert {alert_id} not found."
            
            print(json.dumps({
                "ok": success,
                "speech": speech,
                "data": {
                    "alert_id": alert_id,
                    "acknowledged": success
                }
            }))
        
        else:
            raise ValueError("Must provide either alert_id or clear_all=true")
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to acknowledge alerts: {e}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()

