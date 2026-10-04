#!/usr/bin/env python3
"""CLI wrapper around the shared TTS normalizer."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from tts_normalizer import normalize_tts_text
from tts_style_tags import speech_tag_options


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize text for TTS playback.")
    parser.add_argument("text", nargs="?", help="Text to normalize. If omitted, read stdin.")
    parser.add_argument("--profile", help="Optional normalizer profile, e.g. weather_watch.")
    args = parser.parse_args()

    raw_text = args.text if args.text is not None else sys.stdin.read()
    sys.stdout.write(normalize_tts_text(
        raw_text, profile=args.profile,
        **speech_tag_options(
            os.environ.get("TTS_PROVIDER_OVERRIDE") or os.environ.get("TTS_PROVIDER", ""),
            os.environ.get("ELEVENLABS_TTS_MODEL", ""),
        ),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
