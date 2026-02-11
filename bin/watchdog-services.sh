#!/bin/bash
# Watchdog for Jarvis self-healing daemon
# Run via cron every 5 minutes. Only watches self_healing_daemon since
# it already supervises reminder_scheduler and follow_up_daemon.
#
# Logic:
#   PID file exists + process dead  = crash → restart + announce
#   PID file missing                = intentional stop → do nothing
#   PID file exists + process alive = healthy → do nothing
#
# This means `jarvis-services --stop` (which removes PID files) won't
# be fought by the watchdog. Only unexpected crashes trigger a restart.
#
# Cron entry (add with: crontab -e):
#   */5 * * * * /home/boss/jarvis-voice/bin/watchdog-services.sh >> /home/boss/jarvis-voice/logs/watchdog.log 2>&1

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="$PROJECT_ROOT/logs/self_healing_daemon.pid"
SCRIPT="$PROJECT_ROOT/services/self_healing_daemon.py"
LOGFILE="$PROJECT_ROOT/logs/self_healing_daemon.log"
API_URL="http://localhost:8880/api/voice/announce"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# No PID file = intentional stop, do nothing
if [ ! -f "$PIDFILE" ]; then
    exit 0
fi

# PID file exists, check if process is alive
pid=$(cat "$PIDFILE" 2>/dev/null)
if [ -z "$pid" ]; then
    exit 0
fi

if kill -0 "$pid" 2>/dev/null; then
    # Process alive, all good
    exit 0
fi

# Process dead with stale PID file = crash, restart it
echo "[$TIMESTAMP] self_healing_daemon crashed (stale PID $pid) - restarting..."

# Load the same env that jarvis-services used (cloud or local)
MODE=$(cat "$PROJECT_ROOT/logs/services_mode" 2>/dev/null || echo "cloud")
if [ "$MODE" == "local" ]; then
    ENV_FILE="$PROJECT_ROOT/config/local.env"
else
    ENV_FILE="$PROJECT_ROOT/config/cloud.env"
fi

if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE" 2>/dev/null
    set +a
fi

# Activate venv if available
if [ -f "$HOME/jarvis-venv/bin/activate" ]; then
    source "$HOME/jarvis-venv/bin/activate"
fi

nohup python3 -u "$SCRIPT" >> "$LOGFILE" 2>&1 &
new_pid=$!
echo "$new_pid" > "$PIDFILE"

echo "[$TIMESTAMP] self_healing_daemon restarted (PID $new_pid) [mode=$MODE]"

# Announce via TTS if API is up
curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d '{"message": "Warning: self healing daemon crashed and has been restarted by watchdog."}' \
    --connect-timeout 5 --max-time 10 > /dev/null 2>&1
