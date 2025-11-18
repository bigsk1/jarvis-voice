#!/usr/bin/env python3
"""
Self-Healing Daemon
Periodically checks alerts with auto_resolve_url.
Auto-resolves if URL returns 2xx/3xx status codes.

Check intervals:
- Per-alert custom interval (default: 300 seconds / 5 minutes)
- Global check loop: 60 seconds
"""

import sys
import os
import time
import sqlite3
import subprocess
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB
from service_logger import ServiceLogger


# Maximum tool calls per check (safety limit)
MAX_CHECKS_PER_LOOP = 10

# Request timeout
REQUEST_TIMEOUT = 10  # seconds


def get_alerts_to_check(db_path: str) -> List[Dict[str, Any]]:
    """Get pending alerts that have auto_resolve_url and are due for checking."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    alerts = cursor.execute("""
        SELECT * FROM alerts 
        WHERE status = 'pending'
        AND auto_resolve_url IS NOT NULL
        AND auto_resolve_url != ''
        ORDER BY severity DESC, created_at ASC
        LIMIT ?
    """, (MAX_CHECKS_PER_LOOP,)).fetchall()
    
    conn.close()
    return [dict(row) for row in alerts]


def should_check_now(alert: Dict[str, Any]) -> bool:
    """Determine if it's time to check this alert's URL."""
    check_interval = alert.get('auto_resolve_check_interval', 300)  # Default 5 min
    last_check_str = alert.get('last_check_at')
    
    if not last_check_str:
        # Never checked, check now
        return True
    
    try:
        last_check = datetime.fromisoformat(last_check_str)
    except (ValueError, TypeError):
        return True
    
    elapsed = datetime.now() - last_check
    return elapsed.total_seconds() >= check_interval


def check_url(url: str) -> bool:
    """
    Check if URL is responding successfully.
    Returns True if 2xx or 3xx status code.
    """
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            verify=True  # Verify SSL certificates
        )
        
        # Consider 2xx and 3xx as "resolved"
        return 200 <= response.status_code < 400
    
    except requests.exceptions.Timeout:
        return False
    except requests.exceptions.ConnectionError:
        return False
    except requests.exceptions.TooManyRedirects:
        return False
    except requests.exceptions.RequestException:
        return False
    except Exception:
        return False


def auto_resolve_alert(db_path: str, alert_id: int, alert_title: str, alert_source: str, mode: str, project_root: Path):
    """Mark alert as auto-resolved and notify user."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    cursor.execute("""
        UPDATE alerts
        SET status = 'auto_resolved',
            resolved_at = ?,
            updated_at = ?
        WHERE id = ?
    """, (now, now, alert_id))
    
    conn.commit()
    conn.close()
    
    # Speak notification - extract specific item from title if possible
    if ':' in alert_title and ('Stopped' in alert_title or 'Down' in alert_title):
        # Extract specific thing (e.g., "Container Stopped: kokoro-cpu" -> "kokoro-cpu")
        item = alert_title.split(':')[-1].strip()
        message = f"Boss, good news! {item} is back up and running."
    else:
        # Generic message with source
        message = f"Boss, good news! {alert_source} is back up and running. Alert resolved."
    
    # Use appropriate TTS script
    if mode == 'local':
        say_script = project_root / 'bin' / 'say-local.sh'
    else:
        say_script = project_root / 'bin' / 'say.sh'
    
    if say_script.exists():
        try:
            subprocess.run(
                [str(say_script), message],
                check=False,
                capture_output=True,
                text=True,
                timeout=10
            )
        except Exception as e:
            print(f"Warning: TTS failed for alert {alert_id}: {e}", file=sys.stderr)


def update_last_check(db_path: str, alert_id: int):
    """Update last_check_at timestamp."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    cursor.execute("""
        UPDATE alerts
        SET last_check_at = ?
        WHERE id = ?
    """, (now, alert_id))
    
    conn.commit()
    conn.close()


def main():
    """Self-healing daemon main loop."""
    print("🩹 Self-Healing Daemon Starting...")
    
    # Load config
    load_config()
    mode = 'local' if get_config_value('LLM_PROVIDER', 'anthropic') == 'ollama' else 'cloud'
    
    project_root = Path(__file__).parent.parent
    db = MemoryDB()
    db_path = db.db_path
    
    # Initialize logger
    logger = ServiceLogger('self_healing_daemon')
    logger.log_startup(mode, {
        "database": str(db_path),
        "check_interval": 60,
        "max_checks_per_loop": MAX_CHECKS_PER_LOOP,
        "request_timeout": REQUEST_TIMEOUT
    })
    
    print(f"   Mode: {mode}")
    print(f"   Database: {db_path}")
    print(f"   Check interval: 60 seconds")
    print(f"   Max checks per loop: {MAX_CHECKS_PER_LOOP}")
    print(f"   Request timeout: {REQUEST_TIMEOUT}s")
    print()
    
    check_count = 0
    resolved_count = 0
    
    try:
        while True:
            check_count += 1
            
            # Get alerts with auto_resolve_url
            alerts_to_check = get_alerts_to_check(db_path)
            
            logger.log_check(len(alerts_to_check), {"with_auto_resolve_url": len(alerts_to_check)})
            
            if len(alerts_to_check) > 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Check #{check_count}: {len(alerts_to_check)} alerts with auto_resolve_url")
                
                for alert in alerts_to_check:
                    if not should_check_now(alert):
                        continue
                    
                    alert_id = alert['id']
                    title = alert['title']
                    source = alert.get('source', 'Unknown')
                    url = alert['auto_resolve_url']
                    
                    print(f"  → Checking alert {alert_id}: {title}")
                    print(f"    URL: {url}")
                    
                    try:
                        # Check URL
                        is_resolved = check_url(url)
                        
                        # Update last check time
                        update_last_check(db_path, alert_id)
                        
                        # Log URL check
                        logger.log_action("url_check", {
                            "alert_id": alert_id,
                            "title": title,
                            "url": url
                        }, success=is_resolved)
                        
                        if is_resolved:
                            print(f"    ✅ RESOLVED - Auto-canceling alert")
                            auto_resolve_alert(db_path, alert_id, title, source, mode, project_root)
                            
                            # Log auto-resolve
                            logger.log_action("auto_resolve", {
                                "alert_id": alert_id,
                                "title": title,
                                "source": source,
                                "url": url
                            }, success=True)
                            
                            resolved_count += 1
                        else:
                            print(f"    ⏳ Still down")
                    
                    except Exception as e:
                        logger.log_error(f"Check failed for alert {alert_id}", {
                            "alert_id": alert_id,
                            "url": url,
                            "error": str(e)
                        })
                        print(f"    ⚠️  Error: {e}")
            
            # Wait before next check
            time.sleep(60)
    
    except KeyboardInterrupt:
        print(f"\n✋ Self-Healing Daemon stopped by user")
        print(f"   Total resolved: {resolved_count}")
        logger.log_shutdown({"total_resolved": resolved_count, "checks": check_count})
    except Exception as e:
        logger.log_error(f"Fatal error: {e}")
        print(f"\n❌ Self-Healing Daemon error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

