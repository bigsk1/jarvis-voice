#!/usr/bin/env python3
"""Backward-compatible local-mode entry point for Jarvis STT."""

import os
import sys
from pathlib import Path


stt_script = Path(__file__).resolve().with_name("stt.py")
os.execv(
    sys.executable,
    [sys.executable, str(stt_script), "--mode", "local", *sys.argv[1:]],
)
