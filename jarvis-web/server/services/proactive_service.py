"""
Proactive Notification Service
Polls jarvis-api for alerts and reminders, broadcasts to connected web clients.
"""

import requests
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# Polling interval in seconds
POLL_INTERVAL = 10

# jarvis-api URL (same host, different port)
API_BASE_URL = "http://localhost:8880"


@dataclass
class ProactiveService:
    """Service to poll jarvis-api and track notification state"""
    
    # Track which items we've already notified about
    notified_alerts: set[int] = field(default_factory=set)
    notified_reminders: set[int] = field(default_factory=set)
    
    # Last check timestamps
    last_alert_check: float = 0
    last_reminder_check: float = 0
    
    # Callback for broadcasting
    broadcast_callback: Optional[Callable] = None
    
    def set_broadcast_callback(self, callback: Callable):
        """Set the callback used to broadcast to WebSocket clients"""
        self.broadcast_callback = callback
    
    def check_alerts(self) -> list[dict]:
        """Check for new pending alerts"""
        try:
            response = requests.get(
                f"{API_BASE_URL}/api/alerts",
                params={"status": "pending"},
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                alerts = data.get('alerts', [])
                
                # Find new alerts we haven't notified about
                new_alerts = []
                for alert in alerts:
                    alert_id = alert.get('id')
                    if alert_id and alert_id not in self.notified_alerts:
                        new_alerts.append(alert)
                        self.notified_alerts.add(alert_id)
                
                return new_alerts
            
        except requests.RequestException:
            # API not running is expected sometimes
            pass
        except Exception as e:
            print(f"[Proactive] Error checking alerts: {e}")
        
        return []
    
    def check_reminders(self) -> list[dict]:
        """Check for triggered reminders"""
        try:
            response = requests.get(
                f"{API_BASE_URL}/api/reminders",
                params={"status": "triggered"},
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                reminders = data.get('reminders', [])
                
                # Find new reminders we haven't notified about
                new_reminders = []
                for reminder in reminders:
                    reminder_id = reminder.get('id')
                    if reminder_id and reminder_id not in self.notified_reminders:
                        new_reminders.append(reminder)
                        self.notified_reminders.add(reminder_id)
                
                return new_reminders
            
        except requests.RequestException:
            # API not running is expected sometimes
            pass
        except Exception as e:
            print(f"[Proactive] Error checking reminders: {e}")
        
        return []
    
    def acknowledge_alert(self, alert_id: int) -> bool:
        """Acknowledge an alert via jarvis-api"""
        try:
            response = requests.put(
                f"{API_BASE_URL}/api/alerts/{alert_id}/acknowledge",
                timeout=5
            )
            if response.status_code == 200:
                # Remove from notified set so we don't re-notify
                self.notified_alerts.discard(alert_id)
                return True
        except Exception as e:
            print(f"[Proactive] Error acknowledging alert {alert_id}: {e}")
        return False
    
    def acknowledge_reminder(self, reminder_id: int) -> bool:
        """Acknowledge a reminder via jarvis-api"""
        try:
            response = requests.post(
                f"{API_BASE_URL}/api/reminders/{reminder_id}/acknowledge",
                timeout=5
            )
            if response.status_code == 200:
                self.notified_reminders.discard(reminder_id)
                return True
        except Exception as e:
            print(f"[Proactive] Error acknowledging reminder {reminder_id}: {e}")
        return False
    
    def get_pending_counts(self) -> dict:
        """Get counts of pending alerts/reminders"""
        alerts_count = 0
        reminders_count = 0
        
        try:
            # Alerts
            response = requests.get(
                f"{API_BASE_URL}/api/alerts",
                params={"status": "pending"},
                timeout=3
            )
            if response.status_code == 200:
                alerts_count = len(response.json().get('alerts', []))
        except:
            pass
        
        try:
            # Reminders
            response = requests.get(
                f"{API_BASE_URL}/api/reminders",
                params={"status": "triggered"},
                timeout=3
            )
            if response.status_code == 200:
                reminders_count = len(response.json().get('reminders', []))
        except:
            pass
        
        return {
            'alerts': alerts_count,
            'reminders': reminders_count
        }
    
    def poll_and_notify(self) -> dict:
        """
        Main polling function - check for new alerts/reminders and broadcast.
        Returns dict with new items found.
        """
        result = {
            'new_alerts': [],
            'new_reminders': [],
            'counts': {'alerts': 0, 'reminders': 0}
        }
        
        # Check alerts
        new_alerts = self.check_alerts()
        if new_alerts:
            result['new_alerts'] = new_alerts
            print(f"[Proactive] Found {len(new_alerts)} new alert(s)")
        
        # Check reminders
        new_reminders = self.check_reminders()
        if new_reminders:
            result['new_reminders'] = new_reminders
            print(f"[Proactive] Found {len(new_reminders)} new reminder(s)")
        
        # Get current counts
        result['counts'] = self.get_pending_counts()
        
        # Broadcast if we have new items and callback is set
        if self.broadcast_callback and (new_alerts or new_reminders):
            for alert in new_alerts:
                self.broadcast_callback('proactive:alert', {
                    'type': 'alert',
                    'alert': alert,
                    'timestamp': time.time()
                })
            
            for reminder in new_reminders:
                self.broadcast_callback('proactive:reminder', {
                    'type': 'reminder',
                    'reminder': reminder,
                    'timestamp': time.time()
                })
        
        return result
    
    def clear_notification_cache(self):
        """Clear the notification cache (for mode switches)"""
        self.notified_alerts.clear()
        self.notified_reminders.clear()


# Singleton instance
_proactive_service = None

def get_proactive_service() -> ProactiveService:
    """Get or create the singleton proactive service"""
    global _proactive_service
    if _proactive_service is None:
        _proactive_service = ProactiveService()
    return _proactive_service

def reset_proactive_service():
    """Reset the singleton (for mode switches)"""
    global _proactive_service
    if _proactive_service:
        _proactive_service.clear_notification_cache()

