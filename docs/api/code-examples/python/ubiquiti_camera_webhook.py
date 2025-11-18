#!/usr/bin/env python3
"""
Ubiquiti UDM Pro Camera Webhook Handler
Receives webhooks from Ubiquiti cameras and sends alerts to Jarvis

Setup in Ubiquiti:
1. Go to Settings → Notifications
2. Add webhook: http://YOUR_SERVER:5000/webhook
3. Select events: Smart Detection, Motion, etc.

This script:
- Runs a Flask server to receive webhooks
- Filters by time (e.g., only alert between 10PM-6AM)
- Sends alerts to Jarvis for person detection
"""
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import json

app = Flask(__name__)

# Configuration
JARVIS_API = "http://localhost:8880/api/alerts"
ALERT_HOURS_START = 22  # 10 PM
ALERT_HOURS_END = 6     # 6 AM

def is_alert_hours():
    """Check if current time is within alert hours"""
    current_hour = datetime.now().hour
    if ALERT_HOURS_START > ALERT_HOURS_END:
        # Wraps around midnight (e.g., 22:00 to 06:00)
        return current_hour >= ALERT_HOURS_START or current_hour < ALERT_HOURS_END
    else:
        return ALERT_HOURS_START <= current_hour < ALERT_HOURS_END

@app.route('/webhook', methods=['POST'])
def ubiquiti_webhook():
    """Handle incoming Ubiquiti webhook"""
    try:
        data = request.json
        
        # Extract event info
        event_type = data.get('type', 'unknown')
        camera_name = data.get('camera', {}).get('name', 'Unknown Camera')
        detected_object = data.get('smartDetectTypes', [])
        timestamp = data.get('start', datetime.now().isoformat())
        
        # Only alert for person detection during alert hours
        if 'person' in detected_object and is_alert_hours():
            # Send alert to Jarvis
            alert = {
                "title": f"Person Detected: {camera_name}",
                "description": f"Smart detection identified a person at {camera_name}",
                "severity": "medium",
                "source": "ubiquiti-protect",
                "metadata": {
                    "camera": camera_name,
                    "event_type": event_type,
                    "detected": detected_object,
                    "timestamp": timestamp
                }
            }
            
            response = requests.post(JARVIS_API, json=alert, timeout=10)
            
            if response.ok:
                print(f"✅ Alert sent to Jarvis: Person detected at {camera_name}")
                return jsonify({"ok": True, "message": "Alert sent to Jarvis"})
            else:
                print(f"❌ Failed to send alert: {response.text}")
                return jsonify({"ok": False, "message": "Failed to send alert"}), 500
        
        # Outside alert hours or not person detection
        print(f"ℹ️  Event received but not alerting: {event_type} at {camera_name}")
        return jsonify({"ok": True, "message": "Event logged but not alerting"})
        
    except Exception as e:
        print(f"❌ Error processing webhook: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "service": "ubiquiti-webhook"})

if __name__ == '__main__':
    print("🎥 Ubiquiti Camera Webhook Handler")
    print(f"   Jarvis API: {JARVIS_API}")
    print(f"   Alert hours: {ALERT_HOURS_START}:00 - {ALERT_HOURS_END}:00")
    print(f"   Listening on: http://0.0.0.0:5000/webhook")
    print()
    app.run(host='0.0.0.0', port=5000)

