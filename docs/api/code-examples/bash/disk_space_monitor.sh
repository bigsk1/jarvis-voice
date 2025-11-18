#!/bin/bash
# Disk Space Monitor - Bash Example
# Monitor disk space and alert Jarvis if threshold exceeded
# Add to cron: */15 * * * * /path/to/disk_space_monitor.sh

JARVIS_API="http://localhost:8880/api/alerts"
THRESHOLD=90  # Alert if usage > 90%
HOSTNAME=$(hostname)

# Get disk usage
USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')

if [ "$USAGE" -gt "$THRESHOLD" ]; then
    echo "❌ Disk usage is ${USAGE}% - Sending alert to Jarvis"
    
    curl -X POST "$JARVIS_API" \
        -H "Content-Type: application/json" \
        -d "{
            \"title\": \"Disk Space Low on $HOSTNAME\",
            \"description\": \"Disk usage is ${USAGE}% (threshold: ${THRESHOLD}%)\",
            \"severity\": \"high\",
            \"source\": \"disk-monitor\",
            \"metadata\": {
                \"hostname\": \"$HOSTNAME\",
                \"usage_percent\": $USAGE,
                \"threshold\": $THRESHOLD
            }
        }"
    
    echo ""
    echo "✅ Alert sent"
else
    echo "✓ Disk usage is ${USAGE}% (OK)"
fi

