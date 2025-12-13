# UniFi Protect Webhook Receiver

Receives events from UniFi Protect (cameras, sensors) and forwards them to Jarvis alerts API.

## Features

- **Multiple alert types** with configurable behavior
- **Auto-acknowledge** option for transient alerts (camera detections)
- **Follow-up reminders** for persistent issues (battery low, water leak)
- **Per-device cooldowns** to prevent alert storms
- **Time windows** for alert hours
- **TTS caching** - Repeated alerts play instantly from cache

## Alert Rules

Built-in rules for different UniFi event types:

| Event Type | Severity | Auto-Ack | Cooldown | Behavior |
|------------|----------|----------|----------|----------|
| `person` | high | ✅ Yes | 60s | Fire & forget - look at screen |
| `package` | medium | ✅ Yes | 300s | Fire & forget |
| `audio_alarm_glass_break` | critical | ❌ No | 60s | Follow-ups - serious! |
| `audio_alarm_smoke_co` | critical | ❌ No | 60s | Follow-ups - serious! |
| `sensor_water_leak` | critical | ❌ No | 300s | Follow-ups until resolved |
| `sensor_battery_low` | medium | ❌ No | 3600s | Follow-ups until replaced |
| `sensor_alarm` | critical | ❌ No | 300s | Follow-ups until checked |
| `application_issue` | high | ❌ No | 900s | Follow-ups until resolved |
| `camera_offline` | high | ❌ No | 900s | Follow-ups until back online |
| `sensor_offline` | medium | ❌ No | 1800s | Follow-ups until back online |

### Auto-Acknowledge Explained

- **Auto-ack = True**: Alert speaks once, immediately acknowledged. No follow-up reminders. Good for camera detections where you look at the screen and you're done.

- **Auto-ack = False**: Alert stays "pending" and follow-up daemon reminds you at 15/30/60 minutes (varies by severity) until acknowledged. Good for issues requiring action.

## TTS Caching

Alert phrases are automatically cached after first playback:

| Alert | First Time | Subsequent Times |
|-------|-----------|------------------|
| "Boss, Urgent alert! Person: Front Door" | API call (~2s) | Instant (~10ms) ✅ |
| "First reminder: Sense Low Battery" | API call (~2s) | Instant (~10ms) ✅ |

**Cache location:** `~/.cache/jarvis/status-tts/`

**View cache stats:**
```bash
./bin/status-cache stats
```

## Quick Setup

### 1. Configure

```bash
cd /home/boss/jarvis-voice/services/unifi-protect-webhook
cp config.env.example config.env
nano config.env  # Edit as needed
```

### 2. Test manually

```bash
source ~/jarvis-venv/bin/activate
source config.env && export JARVIS_ALERTS_URL WEBHOOK_PORT ALERT_START_HOUR ALERT_END_HOUR COOLDOWN_SECONDS
python3 webhook_receiver.py
```

### 3. Configure UniFi Protect

In UDM Pro → Protect → Settings → Alarms:

1. Create alarms with descriptive names (e.g., "Person: Front Door", "Sense Water Leak")
2. **Objects**: Select detection types
3. **Scope**: Include cameras/sensors
4. **Action**: Webhook → POST
5. **Delivery URL**: `http://<JARVIS_HOST>:5050/webhook`

**Recommended alarm naming:** Include location in name for clear alerts:
- "Person: Front Door" → Jarvis says: "Boss, Urgent alert! Person: Front Door"
- "Person: Garage Camera"
- "Package: Front Door"
- "Sense Water Leak"
- "Sense Low Battery"

### 4. Install as systemd service

```bash
sudo cp unifi-protect-webhook.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now unifi-protect-webhook
```

**Service management:**
```bash
sudo systemctl status unifi-protect-webhook   # Check status
sudo journalctl -u unifi-protect-webhook -f   # View logs
sudo systemctl restart unifi-protect-webhook  # Restart
sudo systemctl stop unifi-protect-webhook     # Stop
```

## Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `JARVIS_ALERTS_URL` | `http://localhost:8880/api/alerts` | Jarvis alerts endpoint |
| `WEBHOOK_PORT` | `5050` | Port to listen on |
| `ALERT_START_HOUR` | `0` | Start of alert window (24h) |
| `ALERT_END_HOUR` | `24` | End of alert window (24h) |
| `COOLDOWN_SECONDS` | `60` | Default cooldown between alerts |

### Time Window Examples

- **Always alert**: `ALERT_START_HOUR=0`, `ALERT_END_HOUR=24`
- **Night only (10PM-6AM)**: `ALERT_START_HOUR=22`, `ALERT_END_HOUR=6`
- **Work hours (9AM-5PM)**: `ALERT_START_HOUR=9`, `ALERT_END_HOUR=17`

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` or `/health` | GET | Health check with enabled rules summary |
| `/rules` | GET | Show all rules (enabled and disabled) |
| `/webhook` | POST | Receive UniFi Protect events |

## Customizing Rules

Edit `ALERT_RULES` in `webhook_receiver.py`:

```python
ALERT_RULES = {
    "person": {
        "enabled": True,
        "severity": "high",      # low, medium, high, critical
        "auto_ack": True,        # True = no follow-ups, False = reminders
        "cooldown": 60,          # Seconds between alerts per device
        "title_template": "{location}",  # Use alarm name directly
        "description": "Person detected on camera",
    },
    "my_custom_event": {
        "enabled": True,
        "severity": "medium",
        "auto_ack": False,
        "cooldown": 300,
        "title_template": "Custom: {location}",
    },
}
```

### Title Template Variables

- `{event}` - Event type (e.g., "Person", "Sensor Battery Low")
- `{location}` - Alarm name from UniFi or device MAC suffix
- `{device}` - Last 4 chars of device MAC

## Testing

```bash
# Health check
curl http://localhost:5050/health | jq .

# Show all rules
curl http://localhost:5050/rules | jq .

# Simulate person detection (uses real MAC, will trigger alert)
curl -X POST http://localhost:5050/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "alarm": {
      "name": "Person: Test Camera",
      "triggers": [{"key": "person", "device": "AABBCCDD1234", "eventId": "test123"}]
    }
  }'

# Note: Test alarms from UniFi UI use "FAKE_MAC" and are intentionally skipped
```

## Firewall

Port 5050 must be accessible from your UDM Pro:

```bash
# Allow from UDM Pro subnet
sudo ufw allow from 192.168.1.0/24 to any port 5050 proto tcp comment "UniFi Protect webhooks"

# Or allow from any (if UDM is on different subnet)
sudo ufw allow 5050/tcp comment "UniFi Protect webhooks"
```

## Troubleshooting

### Webhook not receiving events

1. **Check service is running:**
   ```bash
   curl http://localhost:5050/health
   ```

2. **Test network from UDM Pro:**
   ```bash
   ssh root@192.168.1.1
   curl -v http://<JARVIS_IP>:5050/health
   ```

3. **Check firewall:**
   ```bash
   sudo ufw status | grep 5050
   ```

### Test alarms being skipped

This is intentional! UniFi's "Test Alarm" button sends `FAKE_MAC` as the device ID. We skip these to prevent false alerts. Trigger a **real** detection by walking in front of a camera.

### Alert not speaking

1. Check Jarvis API is running on port 8880
2. Check logs: `sudo journalctl -u unifi-protect-webhook -f`
3. Verify `JARVIS_ALERTS_URL` in config.env

## Architecture

```
┌─────────────────┐         ┌──────────────────────┐         ┌─────────────────┐
│  UniFi Protect  │─webhook─▶│  webhook_receiver.py │─────────▶│  Jarvis Alerts  │
│  (UDM Pro)      │         │  (port 5050)         │         │  API (:8880)    │
└─────────────────┘         └──────────────────────┘         └─────────────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │  Auto-acknowledge │ (for camera alerts)
                            │  or keep pending  │ (for sensor issues)
                            └──────────────────┘
```
