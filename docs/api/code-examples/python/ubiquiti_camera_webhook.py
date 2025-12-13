#!/usr/bin/env python3
"""
DEPRECATED: This is an example file only.

For the production-ready UniFi Protect webhook receiver, see:
  /home/boss/jarvis-voice/services/unifi-protect-webhook/

That version includes:
- Environment-based configuration (no hardcoded values)
- Per-camera cooldown to prevent alert storms
- Configurable time windows
- Systemd service file
- Health check endpoint

Quick start:
  cd services/unifi-protect-webhook
  cp config.env.example config.env
  # edit config.env
  python3 webhook_receiver.py
"""

print("This example has been moved to services/unifi-protect-webhook/")
print("See that directory for the production version.")
