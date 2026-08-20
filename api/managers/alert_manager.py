"""Alert management business logic"""

import sqlite3
import json
import logging
import math
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import sys

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
from config_loader import load_config, get_config_value, get_active_config_mode
from memory_db import get_memory_db
from price_alert_config import load_price_alert_config
from tts_normalizer import normalize_tts_text


logger = logging.getLogger(__name__)
PRICE_ALERT_DEFAULT_COOLDOWN_HOURS = 24.0
PRICE_ALERT_CONDITION_KEY = "price_condition_key"


def _tts_script_timeout_seconds(default: int = 60) -> int:
    """Bound native TTS script execution without blocking alert handling forever."""
    try:
        return max(1, int(get_config_value("TTS_SCRIPT_TIMEOUT_SECONDS", str(default))))
    except (TypeError, ValueError):
        return default


class AlertManager:
    """Manages alerts: creation, status updates, notifications, self-healing"""
    
    def __init__(self, mode: str = None):
        """Initialize alert manager
        
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
            # Resolve from JARVIS_MODE (launcher-provided), never the provider.
            load_config()
            self.mode = get_active_config_mode()
        
        self.db = get_memory_db(self.mode)
        self.project_root = Path(__file__).parent.parent.parent

    def _sanitize_weather_watch_speech(self, text: str) -> str:
        """Backward-compatible wrapper for the shared weather TTS profile."""
        return normalize_tts_text(text, profile="weather_watch")

    def _speech_profile_for_source(self, source: str | None) -> str | None:
        """Map alert sources to the best-fit shared TTS profile."""
        if source == "weather_watch":
            return "weather_watch"
        if source == "unifi-protect":
            return "camera_alert"
        if source == "price_monitor":
            return "price_quote"
        return None

    def _find_existing_alert_by_metadata_key(
        self,
        cursor: sqlite3.Cursor,
        source: str,
        metadata: dict[str, Any],
        key: str
    ) -> int | None:
        """Find a pending alert by a specific metadata key/value pair."""
        value = metadata.get(key)
        if value in (None, ""):
            return None

        cursor.execute("""
            SELECT id FROM alerts
            WHERE source = ? AND status = 'pending'
            AND metadata LIKE ?
        """, (source, f'%"{key}": "{value}"%'))
        existing = cursor.fetchone()
        return existing[0] if existing else None

    @staticmethod
    def _normalize_price_alert_type(value: Any) -> str:
        alert_type = str(value or "").strip().lower()
        if alert_type in {"percent_change", "percent_change_24h"}:
            return "percent_change"
        return alert_type

    @staticmethod
    def _format_price_threshold(value: Any) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric_value = float(value)
            if math.isfinite(numeric_value):
                return format(numeric_value, ".15g")
        return str(value or "").strip()

    @staticmethod
    def _price_alert_direction(metadata: dict[str, Any]) -> str:
        for key in ("change_24h", "change_percent"):
            value = metadata.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if value > 0:
                    return "up"
                if value < 0:
                    return "down"
        return "unknown"

    def _price_alert_condition_key(
        self,
        metadata: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> str | None:
        """Identify a price condition, including its configured threshold."""
        symbol = str(metadata.get("symbol") or "").strip().upper()
        alert_type = self._normalize_price_alert_type(metadata.get("type"))
        if not symbol or alert_type not in {"above", "below", "percent_change"}:
            return None

        threshold = metadata.get("threshold")
        if threshold is None and config:
            watchlist = config.get("watchlist") or {}
            for asset_type in ("crypto", "stocks"):
                for asset in watchlist.get(asset_type) or []:
                    if not isinstance(asset, dict):
                        continue
                    if str(asset.get("symbol") or "").strip().upper() != symbol:
                        continue
                    for condition in asset.get("conditions") or []:
                        if not isinstance(condition, dict):
                            continue
                        condition_type = self._normalize_price_alert_type(condition.get("type"))
                        if condition_type == alert_type:
                            threshold = condition.get("value")
                            break
                    if threshold is not None:
                        break
                if threshold is not None:
                    break

        direction = self._price_alert_direction(metadata) if alert_type == "percent_change" else None
        parts = [symbol, alert_type]
        if direction:
            parts.append(direction)
        parts.append(self._format_price_threshold(threshold))
        return ":".join(parts)

    def _price_alert_policy(self, metadata: dict[str, Any]) -> tuple[float, str | None]:
        """Load the acknowledgement cooldown and stable condition identity."""
        config: dict[str, Any] = {}
        try:
            config = load_price_alert_config()
        except Exception as exc:
            logger.warning("Unable to load price-alert cooldown configuration: %s", exc)

        raw_cooldown = (config.get("settings") or {}).get(
            "cooldown_hours",
            PRICE_ALERT_DEFAULT_COOLDOWN_HOURS,
        )
        try:
            cooldown_hours = float(raw_cooldown)
            if not math.isfinite(cooldown_hours) or cooldown_hours < 0:
                raise ValueError
        except (TypeError, ValueError):
            cooldown_hours = PRICE_ALERT_DEFAULT_COOLDOWN_HOURS

        return cooldown_hours, self._price_alert_condition_key(metadata, config)

    def _find_recent_acknowledged_price_alert(
        self,
        cursor: sqlite3.Cursor,
        metadata: dict[str, Any],
        condition_key: str,
        cooldown_hours: float,
    ) -> int | None:
        """Find the same acknowledged price condition within its cooldown."""
        if cooldown_hours <= 0:
            return None

        cutoff = (datetime.now() - timedelta(hours=cooldown_hours)).isoformat()
        cursor.execute("""
            SELECT id, metadata FROM alerts
            WHERE source = 'price_monitor'
              AND status = 'acknowledged'
              AND acknowledged_at IS NOT NULL
              AND acknowledged_at >= ?
            ORDER BY acknowledged_at DESC
        """, (cutoff,))

        symbol = str(metadata.get("symbol") or "").strip().upper()
        alert_type = self._normalize_price_alert_type(metadata.get("type"))
        direction = self._price_alert_direction(metadata)
        for alert_id, raw_metadata in cursor.fetchall():
            try:
                existing_metadata = json.loads(raw_metadata or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(existing_metadata, dict):
                continue
            if str(existing_metadata.get("symbol") or "").strip().upper() != symbol:
                continue
            if self._normalize_price_alert_type(existing_metadata.get("type")) != alert_type:
                continue
            if (
                alert_type == "percent_change"
                and self._price_alert_direction(existing_metadata) != direction
            ):
                continue

            existing_key = existing_metadata.get(PRICE_ALERT_CONDITION_KEY)
            if existing_key:
                if existing_key == condition_key:
                    return alert_id
                continue

            # Older percentage alerts did not record their configured threshold.
            # Treat those as the same condition so deploying cooldown support does
            # not immediately replay an alert that was just acknowledged.
            if existing_metadata.get("threshold") is None:
                return alert_id
            if self._price_alert_condition_key(existing_metadata) == condition_key:
                return alert_id

        return None

    def _stamp_price_condition_keys(
        self,
        cursor: sqlite3.Cursor,
        where_clause: str,
        params: list[Any] | tuple[Any, ...],
    ) -> None:
        """Persist condition identities on legacy price alerts as they are acknowledged."""
        cursor.execute(
            f"SELECT id, metadata FROM alerts "
            f"WHERE source = 'price_monitor' AND {where_clause}",
            params,
        )
        rows = cursor.fetchall()
        if not rows:
            return

        try:
            config = load_price_alert_config()
        except Exception as exc:
            logger.warning("Unable to load price-alert configuration while acknowledging: %s", exc)
            config = {}

        for alert_id, raw_metadata in rows:
            try:
                metadata = json.loads(raw_metadata or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(metadata, dict) or metadata.get(PRICE_ALERT_CONDITION_KEY):
                continue
            condition_key = self._price_alert_condition_key(metadata, config)
            if not condition_key:
                continue
            metadata[PRICE_ALERT_CONDITION_KEY] = condition_key
            cursor.execute(
                "UPDATE alerts SET metadata = ? WHERE id = ?",
                (json.dumps(metadata), alert_id),
            )
        
    def create_alert(self, 
                     title: str,
                     source: str,
                     description: str | None = None,
                     severity: str = "high",
                     auto_resolve_url: str | None = None,
                     auto_resolve_check_interval: int = 300,
                     metadata: dict[str, Any] | None = None,
                     related_intel_file: str | None = None,
                     speak_immediately: bool = True) -> int:
        """Create a new alert
        
        Args:
            title: Alert title (required)
            source: Source system (required)
            description: Detailed description
            severity: low, medium, high, critical
            auto_resolve_url: URL to check for auto-resolution
            auto_resolve_check_interval: Seconds between checks
            metadata: Additional data (stored as JSON)
            related_intel_file: Related intel file path
            speak_immediately: Whether to speak the alert via TTS
            
        Returns:
            Alert ID, or the negative existing alert ID when suppressed
        """
        metadata = dict(metadata) if metadata else None
        price_cooldown_hours = 0.0
        price_condition_key = None
        if source == 'price_monitor' and metadata:
            price_cooldown_hours, price_condition_key = self._price_alert_policy(metadata)
            if price_condition_key:
                metadata[PRICE_ALERT_CONDITION_KEY] = price_condition_key

        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        # Deduplication: Check for existing pending alert from same source
        # This prevents n8n price monitors from creating duplicate alerts every 10 minutes
        if metadata:
            # Generic dedupe path for workflows and tools that provide a stable key.
            dedupe_id = self._find_existing_alert_by_metadata_key(cursor, source, metadata, "dedupe_key")
            if dedupe_id:
                conn.close()
                return -dedupe_id

        if source == 'price_monitor' and metadata:
            # For price alerts with symbol
            if 'symbol' in metadata:
                symbol = metadata['symbol']
                alert_type = metadata.get('type', '')
                
                cursor.execute("""
                    SELECT id FROM alerts 
                    WHERE source = ? AND status = 'pending' 
                    AND metadata LIKE ? AND metadata LIKE ?
                """, (source, f'%"symbol": "{symbol}"%', f'%"type": "{alert_type}"%'))
                
                existing = cursor.fetchone()
                if existing:
                    conn.close()
                    return -existing[0]

                if price_condition_key:
                    existing_id = self._find_recent_acknowledged_price_alert(
                        cursor,
                        metadata,
                        price_condition_key,
                        price_cooldown_hours,
                    )
                    if existing_id:
                        conn.close()
                        return -existing_id
            
            # For error alerts (no symbol but has 'error' key)
            elif 'error' in metadata:
                error_type = metadata['error']
                
                cursor.execute("""
                    SELECT id FROM alerts 
                    WHERE source = ? AND status = 'pending' 
                    AND metadata LIKE ?
                """, (source, f'%"error": "{error_type}"%'))
                
                existing = cursor.fetchone()
                if existing:
                    conn.close()
                    return -existing[0]
        
        # Convert metadata to JSON string
        metadata_json = json.dumps(metadata) if metadata else None
        
        cursor.execute("""
            INSERT INTO alerts (
                title, description, severity, source,
                auto_resolve_url, auto_resolve_check_interval,
                metadata, related_intel_file,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            title, description, severity, source,
            auto_resolve_url, auto_resolve_check_interval,
            metadata_json, related_intel_file,
            datetime.now().isoformat()
        ))
        
        alert_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Speak immediately if high severity or requested
        if speak_immediately and severity in ['high', 'critical']:
            self._speak_alert(alert_id, title, severity, description=description, source=source)
        
        return alert_id
    
    def get_alert(self, alert_id: int) -> dict[str, Any] | None:
        """Get single alert by ID"""
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        result = cursor.execute(
            "SELECT * FROM alerts WHERE id = ?", (alert_id,)
        ).fetchone()
        
        conn.close()
        
        if result:
            return dict(result)
        return None
    
    def list_alerts(self, 
                    status: str | None = None,
                    severity: str | None = None,
                    source: str | None = None,
                    limit: int = 100,
                    offset: int = 0,
                    search: str | None = None) -> list[dict[str, Any]]:
        """List alerts with optional filters"""
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM alerts WHERE 1=1"
        params = []
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        
        if source:
            query += " AND source = ?"
            params.append(source)

        if search:
            pattern = f"%{search}%"
            query += """ AND (
                title LIKE ? OR description LIKE ? OR source LIKE ? OR
                status LIKE ? OR severity LIKE ? OR related_intel_file LIKE ? OR
                metadata LIKE ?
            )"""
            params.extend([pattern] * 7)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        results = cursor.execute(query, params).fetchall()
        conn.close()
        
        return [dict(row) for row in results]
    
    def acknowledge_alert(self, alert_id: int) -> bool:
        """Mark alert as acknowledged"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()

        self._stamp_price_condition_keys(cursor, "id = ?", [alert_id])
        now = datetime.now().isoformat()
        
        cursor.execute("""
            UPDATE alerts 
            SET status = 'acknowledged',
                acknowledged_at = ?,
                updated_at = ?
            WHERE id = ?
        """, (now, now, alert_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
    def acknowledge_all(self, 
                       status: str | None = None,
                       severity: str | None = None) -> int:
        """Acknowledge multiple alerts
        
        Args:
            status: Filter by status (default: pending)
            severity: Filter by severity
            
        Returns:
            Number of alerts acknowledged
        """
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        conditions = ["status = ?"]
        filter_params: list[Any] = [status or "pending"]
        
        if severity:
            conditions.append("severity = ?")
            filter_params.append(severity)

        where_clause = " AND ".join(conditions)
        self._stamp_price_condition_keys(cursor, where_clause, filter_params)

        now = datetime.now().isoformat()
        query = (
            "UPDATE alerts SET status = 'acknowledged', acknowledged_at = ?, updated_at = ? "
            f"WHERE {where_clause}"
        )
        params = [now, now, *filter_params]
        
        cursor.execute(query, params)
        count = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        return count
    
    def cancel_alert(self, alert_id: int) -> bool:
        """Cancel an alert"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE alerts 
            SET status = 'canceled',
                updated_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), alert_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
    def auto_resolve_alert(self, alert_id: int) -> bool:
        """Mark alert as auto-resolved"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE alerts 
            SET status = 'auto_resolved',
                resolved_at = ?,
                updated_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), datetime.now().isoformat(), alert_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        # Speak notification
        if success:
            alert = self.get_alert(alert_id)
            if alert:
                title = alert.get('title', '')
                source = alert.get('source', 'Unknown source')
                
                # Extract specific item from title (e.g., "Container Stopped: kokoro-cpu" -> "kokoro-cpu")
                if ':' in title and ('Stopped' in title or 'Down' in title):
                    # Extract the specific thing that was down
                    item = title.split(':')[-1].strip()
                    self._speak(f"Boss, good news! {item} is back up and running.", priority="low")
                else:
                    # Generic message with source
                    self._speak(f"Boss, good news! {source} is back up and running. Alert resolved.", priority="low")
        
        return success
    
    def check_auto_resolve(self, alert_id: int) -> bool:
        """Check if alert can be auto-resolved
        
        Makes HTTP request to auto_resolve_url if configured.
        
        Returns:
            True if resolved, False otherwise
        """
        alert = self.get_alert(alert_id)
        if not alert or not alert['auto_resolve_url']:
            return False
        
        try:
            import requests
            response = requests.get(
                alert['auto_resolve_url'],
                timeout=10,
                allow_redirects=True
            )
            
            # Update last check time
            conn = sqlite3.connect(self.db.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE alerts SET last_check_at = ? WHERE id = ?",
                (datetime.now().isoformat(), alert_id)
            )
            conn.commit()
            conn.close()
            
            # Consider 2xx and 3xx as "resolved"
            if 200 <= response.status_code < 400:
                self.auto_resolve_alert(alert_id)
                return True
            
            return False
            
        except Exception:
            # Connection failed - not resolved
            return False
    
    def _speak_alert(self, alert_id: int, title: str, severity: str,
                     description: str | None = None, source: str | None = None):
        """Speak alert via TTS and mark as spoken"""
        # Determine urgency phrase
        if severity == "critical":
            prefix = "Critical alert!"
        elif severity == "high":
            prefix = "Urgent alert!"
        else:
            prefix = "Alert:"
        
        message = f"Boss, {prefix} {title}"
        if source == "weather_watch" and description:
            detail = self._sanitize_weather_watch_speech(description.strip())
            if len(detail) > 220:
                detail = detail[:217].rstrip() + "..."
            message = f"{message}. {detail}"

        speech_profile = self._speech_profile_for_source(source)
        spoken = self._speak(message, priority=severity, profile=speech_profile, blocking=True)
        if not spoken:
            print(f"Warning: TTS failed for alert {alert_id}; leaving spoken=0", file=sys.stderr)
            return False
        
        # Mark as spoken
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE alerts 
            SET spoken = 1, spoken_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), alert_id))
        conn.commit()
        conn.close()
        return True
    
    def _speak(
        self,
        message: str,
        priority: str = "medium",
        profile: str | None = None,
        blocking: bool = False,
    ) -> bool:
        """Trigger TTS using say-status.sh and return whether delivery was started or completed."""
        try:
            spoken_message = normalize_tts_text(message, profile=profile)
            if not spoken_message:
                return False

            # Use say-status.sh which has caching for repeated phrases
            # This is ideal for alerts like "Person: Front Door" spoken many times
            if self.mode == 'local':
                say_script = self.project_root / 'bin' / 'say-status-local.sh'
            else:
                say_script = self.project_root / 'bin' / 'say-status.sh'
            
            # Fallback to regular say.sh if say-status doesn't exist
            if not say_script.exists():
                if self.mode == 'local':
                    say_script = self.project_root / 'bin' / 'say-local.sh'
                else:
                    say_script = self.project_root / 'bin' / 'say.sh'
            
            if not say_script.exists():
                return False

            blocking_arg = "true" if blocking else "false"
            if blocking:
                result = subprocess.run(
                    [str(say_script), spoken_message, blocking_arg],
                    capture_output=True,
                    text=True,
                    timeout=_tts_script_timeout_seconds()
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "").strip()
                    if detail:
                        print(f"Warning: TTS failed: {detail}", file=sys.stderr)
                    return False
                return True

            subprocess.Popen(
                [str(say_script), spoken_message, blocking_arg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except Exception as e:
            # TTS failure shouldn't crash the system
            print(f"Warning: TTS failed: {e}", file=sys.stderr)
            return False
    
    def get_pending_count(self) -> int:
        """Get count of pending alerts"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        result = cursor.execute(
            "SELECT COUNT(*) FROM alerts WHERE status = 'pending'"
        ).fetchone()
        
        conn.close()
        return result[0] if result else 0
