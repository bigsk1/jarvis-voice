"""
Jarvis Version - Single source of truth

Reads the VERSION file at project root and exports JARVIS_VERSION.
All services should import from here instead of hardcoding version strings.

Usage:
    from version import JARVIS_VERSION
"""

from pathlib import Path

_VERSION_FILE = Path(__file__).parent.parent / "VERSION"

try:
    JARVIS_VERSION = _VERSION_FILE.read_text().strip()
except FileNotFoundError:
    JARVIS_VERSION = "0.0.0"
