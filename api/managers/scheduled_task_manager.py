"""Scheduled task management business logic"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'orchestrator'))
from config_loader import load_config, get_config_value, get_active_config_mode
from memory_db import get_memory_db
from schedule_parser import calculate_next_run, parse_schedule_expression
from time_utils import format_utc_db, now_utc
from workflow_loader import WorkflowLoader


class ScheduledTaskManager:
    """Manages scheduled tasks and run history."""

    def __init__(self, mode: str | None = None):
        if not mode:
            mode = os.environ.get('JARVIS_API_MODE')

        if mode:
            load_config(mode)
            self.mode = mode
        else:
            load_config()
            self.mode = get_active_config_mode()

        self.db = get_memory_db(self.mode)
        self._ensure_tables()

    def _ensure_tables(self):
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                enabled BOOLEAN DEFAULT 1,
                task_type TEXT NOT NULL,
                task_target TEXT,
                task_payload TEXT,
                schedule_type TEXT NOT NULL,
                schedule_expr TEXT NOT NULL,
                timezone TEXT DEFAULT 'America/Los_Angeles',
                mode TEXT DEFAULT 'cloud',
                allow_overlap BOOLEAN DEFAULT 0,
                max_retries INTEGER DEFAULT 1,
                timeout_seconds INTEGER DEFAULT 300,
                last_run_at TEXT,
                next_run_at TEXT,
                last_status TEXT,
                last_error TEXT,
                last_duration_ms REAL,
                last_result_summary TEXT,
                lock_owner TEXT,
                lock_acquired_at TEXT,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_task_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                mode TEXT,
                provider TEXT,
                model TEXT,
                workflow_id TEXT,
                tools_used TEXT,
                speech TEXT,
                raw_llm_response TEXT,
                result_data TEXT,
                error TEXT,
                duration_ms REAL,
                completion_guard_applied BOOLEAN DEFAULT 0,
                feedback_collected BOOLEAN DEFAULT 0,
                metadata TEXT,
                FOREIGN KEY(task_id) REFERENCES scheduled_tasks(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run ON scheduled_tasks(enabled, next_run_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_mode ON scheduled_tasks(mode)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_task_runs_task ON scheduled_task_runs(task_id, started_at DESC)")
        conn.commit()
        conn.close()

    @staticmethod
    def _resolve_workflow_id(workflow_id: str) -> str:
        """Resolve a workflow by exact ID or explicit trigger alias like /crypto."""
        if not workflow_id:
            raise ValueError("workflow_id is required for workflow scheduled tasks")

        loader = WorkflowLoader(explicit_only=True)
        workflow = loader.get_workflow(workflow_id)
        if workflow:
            return workflow["id"]

        normalized = workflow_id if workflow_id.startswith("/") else f"/{workflow_id}"
        for candidate in loader.workflows.values():
            explicit = candidate.get("triggers", {}).get("explicit", [])
            if workflow_id in explicit or normalized in explicit:
                return candidate["id"]

        raise ValueError(f"Workflow '{workflow_id}' not found")

    def create_task(self, *, name: str, task_type: str, query: str | None = None,
                    workflow_id: str | None = None, when: str, timezone_name: str | None = None,
                    mode: str = 'cloud', enabled: bool = True, allow_overlap: bool = False,
                    max_retries: int = 1, timeout_seconds: int = 300,
                    metadata: dict[str, Any] | None = None) -> int:
        timezone_name = timezone_name or get_config_value("JARVIS_TIMEZONE", "America/Los_Angeles")
        schedule = parse_schedule_expression(when, tz_name=timezone_name)

        if task_type == 'query' and not query:
            raise ValueError("query is required for query scheduled tasks")
        if task_type == 'workflow' and not workflow_id:
            raise ValueError("workflow_id is required for workflow scheduled tasks")
        if task_type == 'workflow':
            workflow_id = self._resolve_workflow_id(workflow_id)

        payload = {"query": query} if task_type == 'query' else {"workflow_id": workflow_id}
        payload["when_original"] = when
        payload["schedule_summary"] = schedule["summary"]

        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO scheduled_tasks (
                name, enabled, task_type, task_target, task_payload,
                schedule_type, schedule_expr, timezone, mode,
                allow_overlap, max_retries, timeout_seconds,
                next_run_at, metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            1 if enabled else 0,
            task_type,
            workflow_id if task_type == 'workflow' else None,
            json.dumps(payload),
            schedule["schedule_type"],
            json.dumps(schedule["schedule_expr"]),
            timezone_name,
            mode,
            1 if allow_overlap else 0,
            max_retries,
            timeout_seconds,
            schedule["next_run_at"],
            json.dumps(metadata or {}),
            now,
            now,
        ))
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        row = cursor.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def list_tasks(self, status: str = 'all', limit: int = 100) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = "SELECT * FROM scheduled_tasks WHERE 1=1"
        params: list[Any] = []
        if status == 'enabled':
            query += " AND enabled = 1"
        elif status == 'disabled':
            query += " AND enabled = 0"
        query += " ORDER BY next_run_at ASC, id DESC LIMIT ?"
        params.append(limit)
        rows = cursor.execute(query, params).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def update_task(self, task_id: int, **updates) -> bool:
        existing = self.get_task(task_id)
        if not existing:
            return False

        fields: dict[str, Any] = {}
        if updates.get('name') is not None:
            fields['name'] = updates['name']
        if updates.get('enabled') is not None:
            fields['enabled'] = 1 if updates['enabled'] else 0
        if updates.get('allow_overlap') is not None:
            fields['allow_overlap'] = 1 if updates['allow_overlap'] else 0
        if updates.get('max_retries') is not None:
            fields['max_retries'] = updates['max_retries']
        if updates.get('timeout_seconds') is not None:
            fields['timeout_seconds'] = updates['timeout_seconds']
        if updates.get('mode') is not None:
            fields['mode'] = updates['mode']

        timezone_name = updates.get('timezone') or existing['timezone']
        if updates.get('timezone') is not None:
            fields['timezone'] = timezone_name

        task_payload = json.loads(existing['task_payload'] or "{}")
        if existing['task_type'] == 'query' and updates.get('query') is not None:
            task_payload['query'] = updates['query']
        if existing['task_type'] == 'workflow' and updates.get('workflow_id') is not None:
            resolved_workflow_id = self._resolve_workflow_id(updates['workflow_id'])
            fields['task_target'] = resolved_workflow_id
            task_payload['workflow_id'] = resolved_workflow_id

        if updates.get('metadata') is not None:
            fields['metadata'] = json.dumps(updates['metadata'])

        if updates.get('when') is not None:
            schedule = parse_schedule_expression(updates['when'], tz_name=timezone_name)
            fields['schedule_type'] = schedule['schedule_type']
            fields['schedule_expr'] = json.dumps(schedule['schedule_expr'])
            fields['next_run_at'] = schedule['next_run_at']
            task_payload['when_original'] = updates['when']
            task_payload['schedule_summary'] = schedule['summary']

        if task_payload != json.loads(existing['task_payload'] or "{}"):
            fields['task_payload'] = json.dumps(task_payload)

        if not fields:
            return True

        fields['updated_at'] = datetime.now().isoformat()
        clauses = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [task_id]

        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute(f"UPDATE scheduled_tasks SET {clauses} WHERE id = ?", values)
        conn.commit()
        updated = cursor.rowcount > 0
        conn.close()
        return updated

    def cancel_task(self, task_id: int) -> bool:
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scheduled_tasks
            SET enabled = 0, last_status = 'cancelled', updated_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), task_id))
        conn.commit()
        updated = cursor.rowcount > 0
        conn.close()
        return updated

    def delete_task(self, task_id: int) -> bool:
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scheduled_task_runs WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        return deleted

    def run_now(self, task_id: int) -> bool:
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scheduled_tasks
            SET enabled = 1,
                next_run_at = ?,
                updated_at = ?
            WHERE id = ?
        """, (format_utc_db(now_utc()), datetime.now().isoformat(), task_id))
        conn.commit()
        updated = cursor.rowcount > 0
        conn.close()
        return updated

    def get_due_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        now = format_utc_db(now_utc())
        rows = cursor.execute("""
            SELECT * FROM scheduled_tasks
            WHERE enabled = 1
              AND mode = ?
              AND next_run_at IS NOT NULL
              AND next_run_at <= ?
              AND (lock_owner IS NULL OR lock_owner = '')
            ORDER BY next_run_at ASC
            LIMIT ?
        """, (self.mode, now, limit)).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def acquire_lock(self, task_id: int, owner: str) -> bool:
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            UPDATE scheduled_tasks
            SET lock_owner = ?, lock_acquired_at = ?, last_status = 'running', updated_at = ?
            WHERE id = ? AND (lock_owner IS NULL OR lock_owner = '')
        """, (owner, now, now, task_id))
        conn.commit()
        ok = cursor.rowcount > 0
        conn.close()
        return ok

    def release_lock_and_update(self, task_id: int, *, status: str, error: str | None = None,
                                duration_ms: float | None = None, summary: str | None = None,
                                next_run_at: str | None = None):
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scheduled_tasks
            SET lock_owner = NULL,
                lock_acquired_at = NULL,
                last_run_at = ?,
                next_run_at = ?,
                last_status = ?,
                last_error = ?,
                last_duration_ms = ?,
                last_result_summary = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            datetime.now().isoformat(),
            next_run_at,
            status,
            error,
            duration_ms,
            summary,
            datetime.now().isoformat(),
            task_id
        ))
        conn.commit()
        conn.close()

    def create_run(self, task_id: int, *, status: str = 'running', metadata: dict[str, Any] | None = None) -> int:
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO scheduled_task_runs (task_id, started_at, status, metadata)
            VALUES (?, ?, ?, ?)
        """, (task_id, datetime.now().isoformat(), status, json.dumps(metadata or {})))
        run_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return run_id

    def finish_run(self, run_id: int, *, status: str, mode: str | None = None, provider: str | None = None,
                   model: str | None = None, workflow_id: str | None = None, tools_used: list[str] | None = None,
                   speech: str | None = None, raw_llm_response: str | None = None,
                   result_data: dict[str, Any] | None = None, error: str | None = None,
                   duration_ms: float | None = None, completion_guard_applied: bool = False,
                   feedback_collected: bool = False, metadata: dict[str, Any] | None = None):
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scheduled_task_runs
            SET finished_at = ?, status = ?, mode = ?, provider = ?, model = ?, workflow_id = ?,
                tools_used = ?, speech = ?, raw_llm_response = ?, result_data = ?, error = ?,
                duration_ms = ?, completion_guard_applied = ?, feedback_collected = ?, metadata = ?
            WHERE id = ?
        """, (
            datetime.now().isoformat(),
            status,
            mode,
            provider,
            model,
            workflow_id,
            json.dumps(tools_used or []),
            speech,
            raw_llm_response,
            json.dumps(result_data or {}),
            error,
            duration_ms,
            1 if completion_guard_applied else 0,
            1 if feedback_collected else 0,
            json.dumps(metadata or {}),
            run_id
        ))
        conn.commit()
        conn.close()

    def list_runs(self, task_id: int, limit: int = 20) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        rows = cursor.execute("""
            SELECT * FROM scheduled_task_runs
            WHERE task_id = ?
            ORDER BY started_at DESC
            LIMIT ?
        """, (task_id, limit)).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def calculate_followup_next_run(self, task: dict[str, Any], reference_utc: str | None = None) -> str | None:
        if task.get('schedule_type') == 'once':
            return None
        expr = json.loads(task['schedule_expr'])
        return calculate_next_run(task['schedule_type'], expr, from_utc=reference_utc or task['next_run_at'], tz_name=task['timezone'])
