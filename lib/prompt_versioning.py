#!/usr/bin/env python3
"""
Prompt Versioning Library

Handles database operations for prompt version tracking, including:
- Creating/updating versions
- Performance tracking
- Rollback operations
- Audit logging
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from typing import Any
from dataclasses import dataclass

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))


@dataclass
class PromptVersion:
    """Represents a prompt version."""
    id: int
    component: str
    component_type: str
    version: int
    content: str
    parent_version_id: int | None
    created_at: str
    created_by: str
    times_used: int
    total_rating_sum: float
    is_active: bool
    is_archived: bool
    trigger_feedback_ids: str | None
    change_summary: str | None
    
    @property
    def avg_rating(self) -> float | None:
        if self.times_used > 0:
            return self.total_rating_sum / self.times_used
        return None


# Evolution thresholds - Configurable via environment variables
def _get_evolution_config():
    """Load evolution config from environment or use defaults."""
    return {
        # Minimum low ratings before considering evolution
        # Testing: 2, Production: 5
        "min_low_ratings": int(os.environ.get("EVOLUTION_MIN_LOW_RATINGS", "2")),
        
        # What counts as "low" rating (1-5 scale)
        # Ratings below this trigger evolution consideration
        # 4 = ratings 1,2,3 are "low" (default)
        "low_rating_threshold": int(os.environ.get("EVOLUTION_LOW_THRESHOLD", "4")),
        
        # Time window to accumulate feedback (days)
        # Testing: 3, Production: 7
        "window_days": int(os.environ.get("EVOLUTION_WINDOW_DAYS", "3")),
        
        # Minimum improvement required to promote (percentage)
        "min_improvement_pct": int(os.environ.get("EVOLUTION_MIN_IMPROVEMENT_PCT", "10")),
        
        # A/B test sample size
        # Testing: 10, Production: 20
        "ab_test_interactions": int(os.environ.get("EVOLUTION_AB_TEST_SIZE", "10")),
        
        # Degradation detection thresholds
        # Alert when performance drops by this %
        "degradation_alert_pct": int(os.environ.get("EVOLUTION_DEGRADATION_ALERT_PCT", "15")),
        # Auto-rollback when performance drops by this %
        "degradation_rollback_pct": int(os.environ.get("EVOLUTION_DEGRADATION_ROLLBACK_PCT", "25")),
        
        # Rate limits
        "max_evolutions_per_day": int(os.environ.get("EVOLUTION_MAX_PER_DAY", "5")),
        
        # Auto-evolution settings
        # If true, automatically run evolution after feedback threshold is hit
        "auto_evolve_enabled": os.environ.get("EVOLUTION_AUTO_ENABLED", "false").lower() == "true",
        # How many feedback entries before auto-check
        "auto_check_after_feedback": int(os.environ.get("EVOLUTION_AUTO_CHECK_AFTER", "10")),
    }

# Lazy load config
EVOLUTION_CONFIG = _get_evolution_config()


class PromptVersionDB:
    """Database operations for prompt versioning."""
    
    def __init__(self, mode: str = None):
        """Initialize with database connection."""
        if mode is None:
            mode = 'local' if os.environ.get('LLM_PROVIDER') == 'ollama' else 'cloud'
        
        self.mode = mode
        base_path = os.path.join(os.path.dirname(__file__), '..', 'data')
        
        if mode == 'local':
            self.db_path = os.path.join(base_path, 'jarvis_memory_local.db')
        else:
            self.db_path = os.path.join(base_path, 'jarvis_memory.db')
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # ==================== Version Operations ====================
    
    def get_active_version(self, component: str) -> PromptVersion | None:
        """Get the currently active version for a component."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM prompt_versions 
            WHERE component = ? AND is_active = TRUE
            ORDER BY version DESC LIMIT 1
        """, (component,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return PromptVersion(**dict(row))
        return None
    
    def get_version(self, version_id: int) -> PromptVersion | None:
        """Get a specific version by ID."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM prompt_versions WHERE id = ?", (version_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return PromptVersion(**dict(row))
        return None
    
    def get_version_history(self, component: str, limit: int = 10) -> list[PromptVersion]:
        """Get version history for a component."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM prompt_versions 
            WHERE component = ?
            ORDER BY version DESC
            LIMIT ?
        """, (component, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [PromptVersion(**dict(row)) for row in rows]
    
    def create_version(
        self,
        component: str,
        component_type: str,
        content: str,
        created_by: str = 'auto_evolution',
        parent_version_id: int = None,
        trigger_feedback_ids: list[str] = None,
        change_summary: str = None,
        activate: bool = False
    ) -> PromptVersion:
        """Create a new prompt version."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Get next version number
        cursor.execute("""
            SELECT COALESCE(MAX(version), 0) + 1 
            FROM prompt_versions WHERE component = ?
        """, (component,))
        next_version = cursor.fetchone()[0]
        
        # If activating, deactivate current active
        if activate:
            cursor.execute("""
                UPDATE prompt_versions 
                SET is_active = FALSE 
                WHERE component = ? AND is_active = TRUE
            """, (component,))
        
        # Insert new version
        cursor.execute("""
            INSERT INTO prompt_versions 
            (component, component_type, version, content, parent_version_id, 
             created_by, trigger_feedback_ids, change_summary, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            component, component_type, next_version, content,
            parent_version_id, created_by,
            json.dumps(trigger_feedback_ids) if trigger_feedback_ids else None,
            change_summary, activate
        ))
        
        version_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return self.get_version(version_id)
    
    def activate_version(self, version_id: int) -> bool:
        """Activate a specific version (deactivates others for same component)."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Get the version's component
        cursor.execute("SELECT component FROM prompt_versions WHERE id = ?", (version_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False
        
        component = row['component']
        
        # Deactivate all versions for this component
        cursor.execute("""
            UPDATE prompt_versions 
            SET is_active = FALSE 
            WHERE component = ?
        """, (component,))
        
        # Activate the target version
        cursor.execute("""
            UPDATE prompt_versions 
            SET is_active = TRUE, is_archived = FALSE
            WHERE id = ?
        """, (version_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def archive_version(self, version_id: int, reason: str = None) -> bool:
        """Archive a version."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE prompt_versions 
            SET is_archived = TRUE, is_active = FALSE
            WHERE id = ?
        """, (version_id,))
        
        conn.commit()
        conn.close()
        return True
    
    # ==================== Performance Tracking ====================
    
    def record_usage(self, component: str, rating: float = None):
        """Record a usage of the active version, optionally with rating."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        if rating is not None:
            cursor.execute("""
                UPDATE prompt_versions 
                SET times_used = times_used + 1,
                    total_rating_sum = total_rating_sum + ?
                WHERE component = ? AND is_active = TRUE
            """, (rating, component))
        else:
            cursor.execute("""
                UPDATE prompt_versions 
                SET times_used = times_used + 1
                WHERE component = ? AND is_active = TRUE
            """, (component,))
        
        conn.commit()
        conn.close()
    
    def get_performance_stats(self, component: str, days: int = 30) -> dict[str, Any]:
        """Get performance statistics for a component."""
        conn = self._get_conn()
        conn.cursor()
        
        active = self.get_active_version(component)
        if not active:
            conn.close()
            return {"error": "No active version found"}
        
        # Get recent feedback for this component from feedback logs
        # This queries the feedback jsonl files indirectly through analysis
        stats = {
            "component": component,
            "active_version": active.version,
            "active_version_id": active.id,
            "times_used": active.times_used,
            "avg_rating": active.avg_rating,
            "created_at": active.created_at,
            "created_by": active.created_by,
        }
        
        conn.close()
        return stats
    
    # ==================== Rollback Operations ====================
    
    def create_backup(self, version_id: int, reason: str = 'pre_evolution') -> int:
        """Create a backup of a version before changes."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        version = self.get_version(version_id)
        if not version:
            conn.close()
            return None
        
        cursor.execute("""
            INSERT INTO prompt_backups (component, version_id, content, reason)
            VALUES (?, ?, ?, ?)
        """, (version.component, version_id, version.content, reason))
        
        backup_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return backup_id
    
    def rollback(self, component: str, to_version: int = None) -> tuple[bool, str]:
        """Rollback to a previous version."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        if to_version:
            # Rollback to specific version
            cursor.execute("""
                SELECT id FROM prompt_versions 
                WHERE component = ? AND version = ?
            """, (component, to_version))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return False, f"Version {to_version} not found"
            target_id = row['id']
        else:
            # Rollback to previous version
            current = self.get_active_version(component)
            if not current or not current.parent_version_id:
                conn.close()
                return False, "No previous version to rollback to"
            target_id = current.parent_version_id
        
        # Create backup before rollback
        current = self.get_active_version(component)
        if current:
            self.create_backup(current.id, 'pre_rollback')
        
        # Activate target version
        success = self.activate_version(target_id)
        
        # Log the rollback
        self.log_evolution(
            action='rollback',
            component=component,
            from_version_id=current.id if current else None,
            to_version_id=target_id,
            trigger_type='manual',
            status='success' if success else 'failed'
        )
        
        conn.close()
        return success, f"Rolled back to version {to_version or 'previous'}"
    
    # ==================== Audit Logging ====================
    
    def log_evolution(
        self,
        action: str,
        component: str,
        from_version_id: int = None,
        to_version_id: int = None,
        trigger_type: str = None,
        trigger_details: dict = None,
        status: str = 'success',
        notes: str = None
    ):
        """Log an evolution action for audit trail."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO prompt_evolution_log 
            (action, component, from_version_id, to_version_id, 
             trigger_type, trigger_details, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            action, component, from_version_id, to_version_id,
            trigger_type, json.dumps(trigger_details) if trigger_details else None,
            status, notes
        ))
        
        conn.commit()
        conn.close()
    
    def get_evolution_log(self, component: str = None, limit: int = 20) -> list[dict]:
        """Get evolution log entries."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        if component:
            cursor.execute("""
                SELECT * FROM prompt_evolution_log 
                WHERE component = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (component, limit))
        else:
            cursor.execute("""
                SELECT * FROM prompt_evolution_log 
                ORDER BY timestamp DESC LIMIT ?
            """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    # ==================== Evolution Candidates ====================
    
    def get_all_components(self) -> list[str]:
        """Get list of all tracked components."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT component FROM prompt_versions")
        rows = cursor.fetchall()
        conn.close()
        
        return [row['component'] for row in rows]
    
    def check_evolution_rate_limit(self) -> bool:
        """Check if we've hit the daily evolution limit."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("""
            SELECT COUNT(*) FROM prompt_evolution_log 
            WHERE action = 'evolution' 
            AND date(timestamp) = ?
        """, (today,))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count < EVOLUTION_CONFIG['max_evolutions_per_day']


# Convenience function
def get_prompt_db(mode: str = None) -> PromptVersionDB:
    """Get a PromptVersionDB instance."""
    return PromptVersionDB(mode)

