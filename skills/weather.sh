#!/bin/bash
# Jarvis Skill: Weather (Mock)
# TODO: Replace with actual weather API call

set -euo pipefail

# Read input
INPUT=$(cat)
LOCATION=$(echo "$INPUT" | jq -r '.location // "your location"')

# Mock weather data (replace with real API)
# Example: curl wttr.in/$LOCATION?format=j1
TEMP="72"
CONDITION="partly cloudy"

# Return JSON response
jq -n \
  --arg speech "It's $TEMP degrees and $CONDITION in $LOCATION" \
  --arg location "$LOCATION" \
  --argjson temp "$TEMP" \
  --arg condition "$CONDITION" \
  '{ok:true, speech:$speech, data:{location:$location, temp:$temp, condition:$condition}}'

