#!/usr/bin/env python3
"""
Tool Name: list_alerts
List alerts from the proactive API system
Input: { "status": "pending|acknowledged|all", "limit": 10 }
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json
import sqlite3
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB

def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        status = args.get('status', 'pending')
        limit = args.get('limit', 10)
        
        # Get database (auto-detects mode)
        db = MemoryDB()
        
        # Query alerts
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if status == 'all':
            query = "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?"
            params = [limit]
        else:
            query = "SELECT * FROM alerts WHERE status = ? ORDER BY created_at DESC LIMIT ?"
            params = [status, limit]
        
        alerts = cursor.execute(query, params).fetchall()
        conn.close()
        
        # Format response
        alert_list = []
        for alert in alerts:
            alert_list.append({
                'id': alert['id'],
                'title': alert['title'],
                'severity': alert['severity'],
                'status': alert['status'],
                'source': alert['source'],
                'created_at': alert['created_at'],
                'description': alert['description']
            })
        
        if len(alert_list) == 0:
            speech = f"No {status} alerts found."
        else:
            # Build speech response
            if status == 'pending':
                speech = f"You have {len(alert_list)} pending alert"
                if len(alert_list) != 1:
                    speech += "s"
                speech += ": "
            else:
                speech = f"Found {len(alert_list)} {status} alert"
                if len(alert_list) != 1:
                    speech += "s"
                speech += ": "
            
            # List first 3 for speech
            for i, alert in enumerate(alert_list[:3]):
                speech += f"{alert['title']} from {alert['source']}"
                if alert['severity'] in ['high', 'critical']:
                    speech += f" ({alert['severity']} priority)"
                if i < min(2, len(alert_list) - 1):
                    speech += ", "
            
            if len(alert_list) > 3:
                speech += f", and {len(alert_list) - 3} more."
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": {
                "alerts": alert_list,
                "count": len(alert_list),
                "status_filter": status
            }
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to list alerts: {e}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()

