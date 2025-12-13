#!/usr/bin/env python3
"""
UniFi Protect Webhook Receiver
Receives events from UniFi Protect and forwards to Jarvis alerts API.

Supports multiple alert types with different behaviors:
- Camera alerts (person, vehicle, animal) → Fire & forget (auto-acknowledge)
- Sensor alerts (battery_low, water_leak) → Follow-ups until fixed

Configuration via environment:
  JARVIS_ALERTS_URL    - Jarvis alerts endpoint (default: http://localhost:8880/api/alerts)
  WEBHOOK_PORT         - Port to listen on (default: 5050)
  ALERT_START_HOUR     - Start of alert window, 24h format (default: 0 = always)
  ALERT_END_HOUR       - End of alert window, 24h format (default: 24 = always)
  COOLDOWN_SECONDS     - Default cooldown between alerts per device (default: 60)

Run:
  python3 webhook_receiver.py
  
Or via systemd:
  sudo systemctl start unifi-protect-webhook
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError
from typing import Dict, Any, Optional

# Configuration from environment
JARVIS_ALERTS_URL = os.environ.get('JARVIS_ALERTS_URL', 'http://localhost:8880/api/alerts')
WEBHOOK_PORT = int(os.environ.get('WEBHOOK_PORT', '5050'))
ALERT_START_HOUR = int(os.environ.get('ALERT_START_HOUR', '0'))
ALERT_END_HOUR = int(os.environ.get('ALERT_END_HOUR', '24'))
DEFAULT_COOLDOWN = int(os.environ.get('COOLDOWN_SECONDS', '60'))

# =============================================================================
# ALERT RULES CONFIGURATION
# =============================================================================
# Define how each UniFi event type should be handled
#
# Keys: UniFi trigger "key" values (person, vehicle, sensor_battery_low, etc.)
#
# Options per rule:
#   enabled:        Whether to process this event type (default: True)
#   severity:       low, medium, high, critical (default: medium)
#   auto_ack:       Auto-acknowledge after alert? (default: False)
#                   True = Fire & forget (no follow-ups) - good for camera alerts
#                   False = Follow-up reminders until acknowledged - good for issues
#   cooldown:       Seconds before another alert from same device (default: 60)
#   title_template: Custom title format (default: "{event} Detected: {location}")
#                   Variables: {event}, {location}, {device}
#   description:    Custom description (optional)
#
# =============================================================================

ALERT_RULES: Dict[str, Dict[str, Any]] = {
    # ==========================================================================
    # CAMERA SMART DETECTION (fire & forget - auto-acknowledge)
    # Alarm names include location: "Person: Front Door", "Package: Garage Camera"
    # ==========================================================================
    "person": {
        "enabled": True,
        "severity": "high",
        "auto_ack": True,  # No follow-ups - look at screen, done
        "cooldown": 60,
        "title_template": "{location}",  # Alarm name already has context
        "description": "Person detected on camera",
    },
    "package": {
        "enabled": True,
        "severity": "medium",
        "auto_ack": True,
        "cooldown": 300,
        "title_template": "{location}",
        "description": "Package detected on camera",
    },
    "vehicle": {
        "enabled": False,  # Enable if needed
        "severity": "medium",
        "auto_ack": True,
        "cooldown": 120,
        "title_template": "{location}",
    },
    "animal": {
        "enabled": False,  # Usually too noisy
        "severity": "low",
        "auto_ack": True,
        "cooldown": 300,
        "title_template": "{location}",
    },
    
    # ==========================================================================
    # AUDIO DETECTION (fire & forget for notifications, but serious!)
    # ==========================================================================
    "audio_alarm_glass_break": {
        "enabled": True,
        "severity": "critical",
        "auto_ack": False,  # Keep reminding - this is serious!
        "cooldown": 60,
        "title_template": "🚨 {location}",
        "description": "Glass breakage audio detected!",
    },
    "audio_alarm_smoke_co": {
        "enabled": True,
        "severity": "critical",
        "auto_ack": False,
        "cooldown": 60,
        "title_template": "🚨 SMOKE/CO ALARM: {location}",
        "description": "Smoke or CO alarm audio detected!",
    },
    
    # ==========================================================================
    # SENSOR ALERTS (need follow-ups until fixed)
    # ==========================================================================
    "sensor_battery_low": {
        "enabled": True,
        "severity": "medium",
        "auto_ack": False,  # Follow-up reminders until battery replaced
        "cooldown": 3600,   # 1 hour between alerts for same sensor
        "title_template": "{location}",  # "Sense Low Battery"
        "description": "Sensor battery needs replacement",
    },
    "sensor_water_leak": {
        "enabled": True,
        "severity": "critical",
        "auto_ack": False,  # CRITICAL - keep reminding!
        "cooldown": 300,
        "title_template": "🚨 {location}",  # "Sense Water Leak"
        "description": "Water leak detected! Check immediately.",
    },
    "sensor_alarm": {
        "enabled": True,
        "severity": "critical",
        "auto_ack": False,
        "cooldown": 300,
        "title_template": "🚨 {location}",
        "description": "Sensor triggered alarm state",
    },
    "sensor_opened": {
        "enabled": False,  # Usually too noisy
        "severity": "low",
        "auto_ack": True,
        "cooldown": 60,
        "title_template": "{location}",
    },
    "sensor_closed": {
        "enabled": False,
        "severity": "low", 
        "auto_ack": True,
        "cooldown": 60,
        "title_template": "{location}",
    },
    
    # ==========================================================================
    # SYSTEM/APPLICATION ALERTS
    # ==========================================================================
    "application_issue": {
        "enabled": True,
        "severity": "high",
        "auto_ack": False,  # Follow-up until resolved
        "cooldown": 900,    # 15 min
        "title_template": "{location}",  # "Application Issue"
        "description": "UniFi application issue detected",
    },
    "camera_offline": {
        "enabled": True,
        "severity": "high",
        "auto_ack": False,
        "cooldown": 900,
        "title_template": "Camera Offline: {location}",
        "description": "Camera not responding",
    },
    "sensor_offline": {
        "enabled": True,
        "severity": "medium",
        "auto_ack": False,
        "cooldown": 1800,   # 30 min
        "title_template": "Sensor Offline: {location}",
        "description": "Sensor not responding",
    },
    
    # ==========================================================================
    # MOTION (disabled by default - too noisy)
    # ==========================================================================
    "motion": {
        "enabled": False,
        "severity": "low",
        "auto_ack": True,
        "cooldown": 30,
        "title_template": "{location}",
    },
}

# Per-device cooldown tracker: {device_mac}_{event_type} -> last_alert_time
_last_alert_time: Dict[str, float] = {}

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('unifi-webhook')


def get_enabled_rules() -> Dict[str, Dict[str, Any]]:
    """Get only enabled alert rules."""
    return {k: v for k, v in ALERT_RULES.items() if v.get('enabled', True)}


def is_within_alert_hours() -> bool:
    """Check if current time is within alert window."""
    if ALERT_START_HOUR == 0 and ALERT_END_HOUR == 24:
        return True
    
    hour = datetime.now().hour
    if ALERT_START_HOUR <= ALERT_END_HOUR:
        return ALERT_START_HOUR <= hour < ALERT_END_HOUR
    else:
        return hour >= ALERT_START_HOUR or hour < ALERT_END_HOUR


def is_cooldown_active(device_id: str, event_type: str) -> bool:
    """Check if device+event combination is in cooldown period."""
    key = f"{device_id}_{event_type}"
    rule = ALERT_RULES.get(event_type, {})
    cooldown = rule.get('cooldown', DEFAULT_COOLDOWN)
    
    last_time = _last_alert_time.get(key, 0)
    return (time.time() - last_time) < cooldown


def update_cooldown(device_id: str, event_type: str):
    """Update cooldown tracker for device+event."""
    key = f"{device_id}_{event_type}"
    _last_alert_time[key] = time.time()


def send_to_jarvis(alert_data: dict, auto_ack: bool = False) -> bool:
    """Send alert to Jarvis API, optionally auto-acknowledge."""
    try:
        req = Request(
            JARVIS_ALERTS_URL,
            data=json.dumps(alert_data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return False
            
            response_data = json.loads(resp.read().decode('utf-8'))
            alert_id = response_data.get('alert_id')
            
            if alert_id and auto_ack:
                _acknowledge_alert(alert_id)
            
            return True
    except URLError as e:
        log.error(f"Failed to send alert to Jarvis: {e}")
        return False


def _acknowledge_alert(alert_id: int):
    """Acknowledge alert to prevent follow-up reminders."""
    try:
        ack_url = f"{JARVIS_ALERTS_URL}/{alert_id}/acknowledge"
        req = Request(ack_url, method='PUT')
        with urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                log.info(f"  Auto-acknowledged alert {alert_id} (no follow-ups)")
    except URLError as e:
        log.warning(f"  Could not auto-acknowledge alert {alert_id}: {e}")


def process_unifi_event(data: dict) -> dict:
    """
    Process UniFi Protect webhook payload.
    
    UniFi Protect alarm webhook format:
    {
      "alarm": {
        "name": "Jarvis Alert Person",
        "sources": [{"device": "MAC_ADDR", "type": "include"}, ...],
        "conditions": [{"condition": {"type": "is", "source": "person"}}],
        "triggers": [{"key": "person", "device": "MAC_ADDR", "eventId": "...", ...}],
        "eventLocalLink": "https://192.168.1.1/protect/events/event/..."
      },
      "timestamp": 1765610239108
    }
    """
    alarm = data.get('alarm', {})
    
    if not alarm:
        return {'skip': True, 'reason': 'No alarm data in payload'}
    
    alarm_name = alarm.get('name', 'Unknown Alarm')
    triggers = alarm.get('triggers', [])
    event_link = alarm.get('eventLocalLink', '')
    timestamp = data.get('timestamp', int(time.time() * 1000))
    
    if not triggers:
        return {'skip': True, 'reason': 'No triggers in alarm'}
    
    # Get first trigger info
    trigger = triggers[0]
    event_type = trigger.get('key', 'unknown')
    device_mac = trigger.get('device', 'unknown')
    event_id = trigger.get('eventId', '')
    
    # Skip test events
    if device_mac == 'FAKE_MAC':
        return {'skip': True, 'reason': f'Test alarm ({event_type}) - ignoring'}
    
    # Check if we have a rule for this event type
    enabled_rules = get_enabled_rules()
    if event_type not in enabled_rules:
        return {'skip': True, 'reason': f'No enabled rule for event type: {event_type}'}
    
    rule = enabled_rules[event_type]
    
    # Check time window
    if not is_within_alert_hours():
        return {'skip': True, 'reason': 'Outside alert hours'}
    
    # Check cooldown
    if is_cooldown_active(device_mac, event_type):
        cooldown = rule.get('cooldown', DEFAULT_COOLDOWN)
        return {'skip': True, 'reason': f'Device {device_mac[-4:]} in cooldown ({cooldown}s) for {event_type}'}
    
    # Build alert using rule configuration
    location = alarm_name if alarm_name not in ['Unknown Alarm', 'New Alarm'] else f'Device {device_mac[-4:]}'
    
    title_template = rule.get('title_template', '{event} Detected: {location}')
    title = title_template.format(
        event=event_type.replace('_', ' ').title(),
        location=location,
        device=device_mac[-4:]
    )
    
    description = rule.get('description', f'UniFi Protect alert: {event_type}')
    
    alert = {
        'title': title,
        'description': description,
        'severity': rule.get('severity', 'medium'),
        'source': 'unifi-protect',
        'metadata': {
            'alarm_name': alarm_name,
            'device_mac': device_mac,
            'event_type': event_type,
            'event_id': event_id,
            'event_link': event_link,
            'auto_ack': rule.get('auto_ack', False),
            'timestamp_ms': timestamp
        }
    }
    
    # Update cooldown
    update_cooldown(device_mac, event_type)
    
    return {
        'skip': False,
        'alert': alert,
        'auto_ack': rule.get('auto_ack', False)
    }


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for UniFi webhooks."""
    
    def log_message(self, format, *args):
        log.info(f"{self.address_string()} - {format % args}")
    
    def _send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def do_GET(self):
        """Health check and status endpoint."""
        if self.path in ('/', '/health'):
            enabled = get_enabled_rules()
            self._send_json(200, {
                'ok': True,
                'service': 'unifi-protect-webhook',
                'jarvis_url': JARVIS_ALERTS_URL,
                'alert_hours': f'{ALERT_START_HOUR}:00-{ALERT_END_HOUR}:00',
                'enabled_rules': list(enabled.keys()),
                'rules_summary': {
                    k: {'severity': v.get('severity'), 'auto_ack': v.get('auto_ack', False)}
                    for k, v in enabled.items()
                }
            })
        elif self.path == '/rules':
            # Show all rules (enabled and disabled)
            self._send_json(200, {
                'ok': True,
                'rules': ALERT_RULES
            })
        else:
            self._send_json(404, {'ok': False, 'error': 'Not found'})
    
    def do_POST(self):
        """Handle incoming webhook."""
        if self.path != '/webhook':
            self._send_json(404, {'ok': False, 'error': 'Use POST /webhook'})
            return
        
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))
            
            # Extract event type for logging
            alarm = data.get('alarm', {})
            triggers = alarm.get('triggers', [])
            event_type = triggers[0].get('key', 'unknown') if triggers else 'unknown'
            alarm_name = alarm.get('name', '?')
            
            log.info(f"Received: {event_type} from '{alarm_name}'")
            log.debug(f"Full payload: {json.dumps(data, indent=2)}")
            
            result = process_unifi_event(data)
            
            if result.get('skip'):
                log.info(f"  Skipped: {result['reason']}")
                self._send_json(200, {'ok': True, 'action': 'skipped', 'reason': result['reason']})
                return
            
            alert = result['alert']
            auto_ack = result.get('auto_ack', False)
            
            if send_to_jarvis(alert, auto_ack=auto_ack):
                ack_status = " (auto-ack)" if auto_ack else " (follow-ups enabled)"
                log.info(f"  ✅ Alert sent: {alert['title']}{ack_status}")
                self._send_json(200, {
                    'ok': True,
                    'action': 'alerted',
                    'title': alert['title'],
                    'auto_ack': auto_ack
                })
            else:
                log.error(f"  ❌ Failed to send alert: {alert['title']}")
                self._send_json(500, {'ok': False, 'error': 'Failed to send to Jarvis'})
        
        except json.JSONDecodeError as e:
            log.error(f"Invalid JSON: {e}")
            self._send_json(400, {'ok': False, 'error': f'Invalid JSON: {e}'})
        except Exception as e:
            log.error(f"Error processing webhook: {e}")
            self._send_json(500, {'ok': False, 'error': str(e)})


def main():
    """Start the webhook server."""
    enabled = get_enabled_rules()
    
    log.info("=" * 60)
    log.info("UniFi Protect Webhook Receiver")
    log.info("=" * 60)
    log.info(f"  Jarvis API:     {JARVIS_ALERTS_URL}")
    log.info(f"  Listening:      http://0.0.0.0:{WEBHOOK_PORT}/webhook")
    log.info(f"  Alert hours:    {ALERT_START_HOUR}:00 - {ALERT_END_HOUR}:00 (0-24 = always)")
    log.info(f"  Default cooldown: {DEFAULT_COOLDOWN}s")
    log.info("")
    log.info("Enabled alert rules:")
    for name, rule in enabled.items():
        ack = "auto-ack" if rule.get('auto_ack') else "follow-ups"
        sev = rule.get('severity', 'medium')
        cd = rule.get('cooldown', DEFAULT_COOLDOWN)
        log.info(f"  • {name}: {sev}, {ack}, cooldown={cd}s")
    log.info("=" * 60)
    
    server = HTTPServer(('0.0.0.0', WEBHOOK_PORT), WebhookHandler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()
