"""Reminder management business logic"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import sys

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
from config_loader import load_config
from memory_db import MemoryDB

class ReminderManager:
    """Manages reminders: creation, triggering, notifications"""
    
    def __init__(self, mode: str = None):
        """Initialize reminder manager
        
        Args:
            mode: 'cloud' or 'local' (auto-detected if not provided)
        """
        import os
        
        # Check for explicit mode from environment (set by jarvis-api script)
        if not mode:
            mode = os.environ.get('JARVIS_API_MODE')
        
        if mode:
            load_config(mode)
        else:
            load_config()  # Auto-detect
        
        self.db = MemoryDB()
    
    def create_reminder(self,
                       title: str,
                       trigger_time: str,
                       description: Optional[str] = None,
                       related_intel_file: Optional[str] = None,
                       callback_url: Optional[str] = None,
                       recurrence_rule: Optional[str] = None,
                       metadata: Optional[Dict[str, Any]] = None) -> int:
        """Create a new reminder
        
        Args:
            title: Reminder title
            trigger_time: ISO 8601 timestamp
            description: Detailed description
            related_intel_file: Related intel file
            callback_url: Webhook to call when triggered
            recurrence_rule: Cron-like syntax (future)
            metadata: Additional data (JSON)
            
        Returns:
            Reminder ID
        """
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        metadata_json = json.dumps(metadata) if metadata else None
        
        cursor.execute("""
            INSERT INTO reminders (
                title, description, trigger_time,
                related_intel_file, callback_url, recurrence_rule,
                metadata, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)
        """, (
            title, description, trigger_time,
            related_intel_file, callback_url, recurrence_rule,
            metadata_json, datetime.now().isoformat()
        ))
        
        reminder_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return reminder_id
    
    def get_reminder(self, reminder_id: int) -> Optional[Dict[str, Any]]:
        """Get single reminder by ID"""
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        result = cursor.execute(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        
        conn.close()
        
        if result:
            return dict(result)
        return None
    
    def list_reminders(self,
                      status: Optional[str] = None,
                      limit: int = 100) -> List[Dict[str, Any]]:
        """List reminders with optional filters"""
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM reminders WHERE 1=1"
        params = []
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY trigger_time ASC LIMIT ?"
        params.append(limit)
        
        results = cursor.execute(query, params).fetchall()
        conn.close()
        
        return [dict(row) for row in results]
    
    def cancel_reminder(self, reminder_id: int) -> bool:
        """Cancel a reminder"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE reminders 
            SET status = 'canceled'
            WHERE id = ? AND status = 'scheduled'
        """, (reminder_id,))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success

