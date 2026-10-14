#!/bin/bash
# Install all system-level dependencies for Jarvis Voice Assistant
# Ubuntu/Debian systems only
# Usage: ./install-system-deps.sh [--list]

set -e

DEPS_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPS_PACKAGE_FILE="$DEPS_SCRIPT_DIR/system-packages.txt"
if [ ! -f "$DEPS_PACKAGE_FILE" ]; then
    echo "❌ Missing package list: $DEPS_PACKAGE_FILE" >&2
    exit 1
fi

# One package per line, followed by an optional comment. Keep the installer
# and the documented requirements on the same source of truth.
mapfile -t JARVIS_SYSTEM_PACKAGES < <(awk 'NF && $1 !~ /^#/ {print $1}' "$DEPS_PACKAGE_FILE")
if [ "${#JARVIS_SYSTEM_PACKAGES[@]}" -eq 0 ]; then
    echo "❌ System package list is empty" >&2
    exit 1
fi

case "${1:-}" in
    --list)
        printf '%s\n' "${JARVIS_SYSTEM_PACKAGES[@]}"
        exit 0
        ;;
    "") ;;
    *)
        echo "Usage: $0 [--list]" >&2
        exit 2
        ;;
esac

echo "======================================"
echo "  Installing System Dependencies"
echo "======================================"
echo ""

# Check if running on Debian/Ubuntu
if [ ! -f /etc/debian_version ]; then
    echo "❌ This script is for Debian/Ubuntu systems only"
    exit 1
fi

# Check for root/sudo
if [ "$EUID" -ne 0 ]; then 
    echo "⚠️  This script requires sudo privileges"
    echo "   Running with sudo..."
    sudo "$DEPS_SCRIPT_DIR/install-system-deps.sh" "$@"
    exit $?
fi

echo "📦 Updating package lists..."
apt update

echo ""
echo "📦 Installing dependencies from system-packages.txt..."
apt install -y "${JARVIS_SYSTEM_PACKAGES[@]}"

echo ""
echo "======================================"
echo "  ✅ All system dependencies installed!"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Run ./setup.sh to configure Jarvis"
echo "2. Install Python packages: pip install -r requirements.txt"
echo ""
