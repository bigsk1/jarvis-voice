#!/bin/bash
# Jarvis Skill: Current Time
# Returns the current time

set -euo pipefail

# Read input (we don't need it for time, but it's part of the contract)
INPUT=$(cat)

# Get current time
NOW=$(date "+%I:%M %p on %A, %B %d")
HOUR=$(date "+%H")

# Determine greeting based on time
if [ "$HOUR" -lt 12 ]; then
  GREETING="Good morning! It's"
elif [ "$HOUR" -lt 18 ]; then
  GREETING="It's currently"
else
  GREETING="It's"
fi

# Return JSON response
jq -n \
  --arg speech "$GREETING $NOW" \
  --arg time "$(date "+%H:%M")" \
  '{ok:true, speech:$speech, data:{time:$time}}'

