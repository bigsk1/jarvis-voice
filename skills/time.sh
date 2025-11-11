#!/bin/bash
# Jarvis Skill: Current Time and Date
# Returns the current time and/or date

set -euo pipefail

# Read input to check what user is asking for
INPUT=$(cat 2>/dev/null || echo "{}")

# Get current time and date components
TIME_ONLY=$(date "+%I:%M %p")
DATE_ONLY=$(date "+%A, %B %d, %Y")
FULL=$(date "+%I:%M %p on %A, %B %d")
HOUR=$(date "+%H")

# Check if user is asking specifically for date or time
if echo "$INPUT" | grep -qi "date\|day\|today"; then
  # Date-focused response
  RESPONSE="Today is $DATE_ONLY"
elif echo "$INPUT" | grep -qi "time"; then
  # Time-focused response
  if [ "$HOUR" -lt 12 ]; then
    RESPONSE="Good morning! It's $TIME_ONLY"
  elif [ "$HOUR" -lt 18 ]; then
    RESPONSE="It's currently $TIME_ONLY"
  else
    RESPONSE="It's $TIME_ONLY"
  fi
else
  # Generic response with both
  if [ "$HOUR" -lt 12 ]; then
    RESPONSE="Good morning! It's $FULL"
  elif [ "$HOUR" -lt 18 ]; then
    RESPONSE="It's currently $FULL"
  else
    RESPONSE="It's $FULL"
  fi
fi

# Return JSON response
jq -n \
  --arg speech "$RESPONSE" \
  --arg time "$(date "+%H:%M")" \
  --arg date "$(date "+%Y-%m-%d")" \
  '{ok:true, speech:$speech, data:{time:$time, date:$date}}'

