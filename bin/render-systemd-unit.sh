#!/bin/bash
# Render a systemd unit template with the current user's account details.

set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 TEMPLATE_FILE OUTPUT_FILE" >&2
    exit 1
fi

TEMPLATE_FILE="$1"
OUTPUT_FILE="$2"
JARVIS_USER_NAME="${JARVIS_SERVICE_USER:-$(id -un)}"
JARVIS_GROUP_NAME="${JARVIS_SERVICE_GROUP:-$(id -gn)}"

if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "❌ Template not found: $TEMPLATE_FILE" >&2
    exit 1
fi

sed \
    -e "s|__JARVIS_USER__|$JARVIS_USER_NAME|g" \
    -e "s|__JARVIS_GROUP__|$JARVIS_GROUP_NAME|g" \
    "$TEMPLATE_FILE" > "$OUTPUT_FILE"

echo "✅ Rendered $OUTPUT_FILE for user=$JARVIS_USER_NAME group=$JARVIS_GROUP_NAME"
