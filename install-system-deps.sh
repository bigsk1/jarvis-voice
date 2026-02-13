#!/bin/bash
# Install all system-level dependencies for Jarvis Voice Assistant
# Ubuntu/Debian systems only

set -e

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
    sudo "$0" "$@"
    exit $?
fi

echo "📦 Updating package lists..."
apt update

echo ""
echo "📦 Installing core dependencies..."

# Core audio packages
apt install -y \
    sox \
    ffmpeg \
    alsa-utils

# Utilities
apt install -y \
    jq \
    curl \
    git \
    tmux \
    python3 \
    python3-pip \
    python3-venv

# Network tools (for network_tools skill)
apt install -y \
    traceroute \
    inetutils-traceroute \
    dnsutils

# Optional but recommended
apt install -y \
    build-essential \
    libportaudio2 \
    libsndfile1 \
    sqlite3 \
    cups \
    libsqlite3-dev \
    ripgrep

echo ""
echo "======================================"
echo "  ✅ All system dependencies installed!"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Run ./setup.sh to configure Jarvis"
echo "2. Install Python packages: pip install -r requirements.txt"
echo ""

