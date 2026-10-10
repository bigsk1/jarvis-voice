"""Reminder management business logic"""

import sqlite3
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
from config_loader import load_config
from memory_db import get_memory_db


class CalendarIdentityConflict(ValueError):
    """An event needs an explicit calendar identity before it can be changed."""


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
            self.mode = mode
        else:
            load_config()  # Auto-detect
            self.mode = None
        
        self.db = get_memory_db(self.mode)
    
    def create_reminder(self,
                       title: str,
                       trigger_time: str,
                       description: str | None = None,
                       related_intel_file: str | None = None,
                       callback_url: str | None = None,
                       recurrence_rule: str | None = None,
                       metadata: dict[str, Any] | None = None) -> int:
        """Create a reminder, reusing records for duplicate deliveries.
        
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
        metadata_json = metadata if isinstance(metadata, str) else (json.dumps(metadata) if metadata else None)
        incoming_metadata = json.loads(metadata_json) if metadata_json else None
        event_id = incoming_metadata.get('gcal_event_id') if isinstance(incoming_metadata, dict) else None

        with closing(sqlite3.connect(self.db.db_path)) as conn, conn:
            # Serialize lookup + insert across workers; a check before the write
            # transaction would still allow concurrent duplicate imports.
            conn.execute('BEGIN IMMEDIATE')
            if event_id:
                rows, calendar_id = self._calendar_rows(conn, event_id, incoming_metadata.get('gcal_calendar_id'))
                if rows:
                    # Replayed creates must not revive a canceled import or
                    # overwrite a newer update. Explicit updates use PUT.
                    self._adopt_calendar_scope(conn, rows, calendar_id)
                    return self._canonical_calendar_row(rows)['id']
                if calendar_id:
                    incoming_metadata['gcal_calendar_id'] = calendar_id
                    metadata_json = json.dumps(incoming_metadata)
            else:
                candidates = conn.execute("""
                    SELECT id, metadata, trigger_time FROM reminders
                    WHERE title = ? AND status = 'scheduled'
                      AND description IS ? AND related_intel_file IS ?
                      AND callback_url IS ? AND recurrence_rule IS ?
                    ORDER BY id
                """, (title, description, related_intel_file,
                      callback_url, recurrence_rule)).fetchall()
                for reminder_id, stored_metadata, stored_time in candidates:
                    try:
                        parsed = json.loads(stored_metadata) if stored_metadata else None
                    except json.JSONDecodeError:
                        continue
                    if parsed == incoming_metadata and self._same_trigger_time(stored_time, trigger_time):
                        return reminder_id

            cursor = conn.execute("""
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
            assert reminder_id is not None
            return reminder_id
    
    def get_reminder(self, reminder_id: int) -> dict[str, Any] | None:
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
                      status: str | None = None,
                      limit: int = 100) -> list[dict[str, Any]]:
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

    def delete_reminder(self, reminder_id: int) -> bool:
        """Permanently delete a reminder."""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return success

    @staticmethod
    def _calendar_id(value):
        value = str(value or '').strip()
        return value if value and value.lower() != 'primary' else None

    @staticmethod
    def _same_trigger_time(left, right):
        try:
            def parsed(value):
                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
            return parsed(left) == parsed(right)
        except (ValueError, TypeError, AttributeError):
            return left == right

    def _adopt_calendar_scope(self, conn, rows, calendar_id):
        if calendar_id:
            for row in rows:
                metadata = json.loads(row['metadata'])
                if metadata.get('gcal_calendar_id') != calendar_id:
                    metadata['gcal_calendar_id'] = calendar_id
                    conn.execute('UPDATE reminders SET metadata=? WHERE id=?', (json.dumps(metadata), row['id']))

    @staticmethod
    def _canonical_calendar_row(rows):
        return next((row for row in rows if row['status'] == 'scheduled'), rows[0])

    def _calendar_rows(self, conn, event_id, calendar_id=None):
        """Resolve legacy empty/primary identities only when their scope is clear."""
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute("""
            SELECT * FROM reminders
            WHERE json_extract(CASE WHEN json_valid(metadata) THEN metadata ELSE '{}' END,
                               '$.gcal_event_id') = ?
            ORDER BY id
        """, (event_id,))]
        requested = self._calendar_id(calendar_id)
        known = {self._calendar_id(json.loads(row['metadata']).get('gcal_calendar_id')) for row in rows}
        legacy = None in known
        known.discard(None)
        if len(known) > 1 and (not requested or legacy):
            raise CalendarIdentityConflict('Event matches multiple calendars; reconcile legacy identities or supply calendar_id.')
        if legacy and requested and known and requested not in known:
            raise CalendarIdentityConflict('Legacy event identity conflicts with the requested calendar; reconcile its calendar_id.')
        resolved = requested or (next(iter(known)) if known else None)
        selected = [row for row in rows if (
            self._calendar_id(json.loads(row['metadata']).get('gcal_calendar_id')) == resolved
            or (not self._calendar_id(json.loads(row['metadata']).get('gcal_calendar_id'))
                and known.issubset({resolved}))
        )]
        return selected, resolved

    def cancel_reminders_by_gcal_event_id(self, gcal_event_id: str, calendar_id: str | None = None) -> int:
        """Cancel every scheduled copy, including unambiguous legacy identities."""
        with closing(sqlite3.connect(self.db.db_path)) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            rows, resolved = self._calendar_rows(conn, gcal_event_id, calendar_id)
            self._adopt_calendar_scope(conn, rows, resolved)
            count = 0
            for row in rows:
                count += conn.execute("UPDATE reminders SET status='canceled' WHERE id=? AND status='scheduled'",
                                      (row['id'],)).rowcount
            return count

    def update_reminders_by_gcal_event_id(self, gcal_event_id: str, calendar_id: str | None = None,
                                        **changes) -> int | None:
        """Update matching copies together; only one canonical copy may fire."""
        with closing(sqlite3.connect(self.db.db_path)) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            rows, resolved = self._calendar_rows(conn, gcal_event_id, calendar_id)
            if not rows:
                return None
            canonical_id = self._canonical_calendar_row(rows)['id']
            for row in rows:
                reset = row['id'] == canonical_id and not self._same_trigger_time(row['trigger_time'], changes['trigger_time'])
                status = ('scheduled' if reset else row['status']) if row['id'] == canonical_id else 'canceled'
                metadata = json.loads(row['metadata'])
                metadata.update(changes.get('metadata') or {})
                metadata['gcal_event_id'] = gcal_event_id
                if resolved:
                    metadata['gcal_calendar_id'] = resolved
                else:
                    metadata.pop('gcal_calendar_id', None)
                conn.execute("""
                    UPDATE reminders SET title=?, description=?, trigger_time=?, related_intel_file=?,
                      callback_url=?, recurrence_rule=?, metadata=?, status=?,
                      triggered_at=CASE WHEN ? THEN NULL ELSE triggered_at END,
                      acknowledged_at=CASE WHEN ? THEN NULL ELSE acknowledged_at END,
                      spoken=CASE WHEN ? THEN 0 ELSE spoken END,
                      spoken_at=CASE WHEN ? THEN NULL ELSE spoken_at END
                    WHERE id=?
                """, (changes['title'], changes.get('description', row['description']), changes['trigger_time'],
                      changes.get('related_intel_file', row['related_intel_file']), changes.get('callback_url', row['callback_url']),
                      changes.get('recurrence_rule', row['recurrence_rule']), json.dumps(metadata),
                      status, reset, reset, reset, reset, row['id']))
            return canonical_id
    
    def acknowledge_reminder(self, reminder_id: int) -> bool:
        """Mark a triggered reminder as acknowledged."""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE reminders 
            SET status = 'acknowledged',
                acknowledged_at = ?
            WHERE id = ? AND status = 'triggered'
        """, (datetime.now().isoformat(), reminder_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
    def acknowledge_all(self, status: str | None = None) -> int:
        """Acknowledge all reminders matching filter
        
        Args:
            status: Filter by status (default: triggered)
            
        Returns:
            Number of reminders acknowledged
        """
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        query = "UPDATE reminders SET status = 'acknowledged', acknowledged_at = ? WHERE 1=1"
        params = [datetime.now().isoformat()]
        
        if status:
            query += " AND status = ?"
            params.append(status)
        else:
            # Default: acknowledge triggered reminders
            query += " AND status = 'triggered'"
        
        cursor.execute(query, params)
        count = cursor.rowcount
        conn.commit()
        conn.close()
        
        return count
    
    def update_reminder(self,
                       reminder_id: int,
                       title: str,
                       trigger_time: str,
                       description: str | None = None,
                       related_intel_file: str | None = None,
                       callback_url: str | None = None,
                       recurrence_rule: str | None = None,
                       metadata: dict[str, Any] | None = None,
                       reactivate: bool = False) -> bool:
        """Update an existing reminder
        
        Args:
            reminder_id: ID of reminder to update
            title: Reminder title
            trigger_time: ISO 8601 timestamp
            description: Detailed description
            related_intel_file: Related intel file
            callback_url: Webhook to call when triggered
            recurrence_rule: Cron-like syntax
            metadata: Additional data (JSON)
            reactivate: Reset lifecycle state so the updated time can fire again
            
        Returns:
            True if updated, False if not found
        """
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        metadata_json = metadata if isinstance(metadata, str) else (json.dumps(metadata) if metadata else None)
        
        cursor.execute("""
            UPDATE reminders SET
                title = ?,
                description = ?,
                trigger_time = ?,
                related_intel_file = ?,
                callback_url = ?,
                recurrence_rule = ?,
                metadata = ?,
                status = CASE WHEN ? THEN 'scheduled' ELSE status END,
                triggered_at = CASE WHEN ? THEN NULL ELSE triggered_at END,
                acknowledged_at = CASE WHEN ? THEN NULL ELSE acknowledged_at END,
                spoken = CASE WHEN ? THEN 0 ELSE spoken END,
                spoken_at = CASE WHEN ? THEN NULL ELSE spoken_at END
            WHERE id = ?
        """, (
            title, description, trigger_time,
            related_intel_file, callback_url, recurrence_rule,
            metadata_json,
            reactivate, reactivate, reactivate, reactivate, reactivate,
            reminder_id
        ))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
    def find_by_gcal_event_id(self, gcal_event_id: str, calendar_id: str | None = None) -> dict[str, Any] | None:
        """Find reminder by Google Calendar event ID
        
        Searches metadata JSON for gcal_event_id field.
        
        Args:
            gcal_event_id: Google Calendar event ID
            
        Returns:
            Reminder dict or None
        """
        with closing(sqlite3.connect(self.db.db_path)) as conn:
            rows, _ = self._calendar_rows(conn, gcal_event_id, calendar_id)
            return self._canonical_calendar_row(rows) if rows else None
