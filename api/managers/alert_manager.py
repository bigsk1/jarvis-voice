"""Alert management business logic"""

import sqlite3
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import sys

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB

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
            # Auto-detect from config
            load_config()
            provider = get_config_value('LLM_PROVIDER', 'anthropic')
            self.mode = 'local' if provider == 'ollama' else 'cloud'
        
        self.db = MemoryDB()  # Use existing memory system
        self.project_root = Path(__file__).parent.parent.parent
        
    def create_alert(self, 
                     title: str,
                     source: str,
                     description: Optional[str] = None,
                     severity: str = "medium",
                     auto_resolve_url: Optional[str] = None,
                     auto_resolve_check_interval: int = 300,
                     metadata: Optional[Dict[str, Any]] = None,
                     related_intel_file: Optional[str] = None,
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
            Alert ID
        """
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
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
            self._speak_alert(alert_id, title, severity)
        
        return alert_id
    
    def get_alert(self, alert_id: int) -> Optional[Dict[str, Any]]:
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
                    status: Optional[str] = None,
                    severity: Optional[str] = None,
                    source: Optional[str] = None,
                    limit: int = 100) -> List[Dict[str, Any]]:
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
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        results = cursor.execute(query, params).fetchall()
        conn.close()
        
        return [dict(row) for row in results]
    
    def acknowledge_alert(self, alert_id: int) -> bool:
        """Mark alert as acknowledged"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE alerts 
            SET status = 'acknowledged',
                acknowledged_at = ?,
                updated_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), datetime.now().isoformat(), alert_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
    def acknowledge_all(self, 
                       status: Optional[str] = None,
                       severity: Optional[str] = None) -> int:
        """Acknowledge multiple alerts
        
        Args:
            status: Filter by status (default: pending)
            severity: Filter by severity
            
        Returns:
            Number of alerts acknowledged
        """
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        query = "UPDATE alerts SET status = 'acknowledged', acknowledged_at = ?, updated_at = ? WHERE 1=1"
        params = [datetime.now().isoformat(), datetime.now().isoformat()]
        
        if status:
            query += " AND status = ?"
            params.append(status)
        else:
            query += " AND status = 'pending'"  # Default to pending
        
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        
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
            
        except Exception as e:
            # Connection failed - not resolved
            return False
    
    def _speak_alert(self, alert_id: int, title: str, severity: str):
        """Speak alert via TTS and mark as spoken"""
        # Determine urgency phrase
        if severity == "critical":
            prefix = "Critical alert!"
        elif severity == "high":
            prefix = "Urgent alert!"
        else:
            prefix = "Alert:"
        
        message = f"Boss, {prefix} {title}"
        
        self._speak(message, priority=severity)
        
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
    
    def _speak(self, message: str, priority: str = "medium"):
        """Trigger TTS using existing say.sh script"""
        try:
            # Use appropriate say script for mode
            if self.mode == 'local':
                say_script = self.project_root / 'bin' / 'say-local.sh'
            else:
                say_script = self.project_root / 'bin' / 'say.sh'
            
            if say_script.exists():
                subprocess.run(
                    [str(say_script), message],
                    check=False,
                    capture_output=True,
                    text=True
                )
        except Exception as e:
            # TTS failure shouldn't crash the system
            print(f"Warning: TTS failed: {e}", file=sys.stderr)
    
    def get_pending_count(self) -> int:
        """Get count of pending alerts"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        result = cursor.execute(
            "SELECT COUNT(*) FROM alerts WHERE status = 'pending'"
        ).fetchone()
        
        conn.close()
        return result[0] if result else 0

