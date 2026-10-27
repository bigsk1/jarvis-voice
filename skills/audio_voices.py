#!/usr/bin/env python3
"""Look up available speech voices without generating or playing audio."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from config_loader import load_config  # noqa: E402


def run(arguments: dict) -> dict:
    """Return a bounded provider voice catalog for an explicitly enabled tool."""
    from audio_voices import AudioVoiceCatalogError, list_audio_voices

    try:
        load_config()
        data = list_audio_voices(arguments)
    except ValueError as exc:
        return {"ok": False, "speech": str(exc), "error": str(exc)}
    except AudioVoiceCatalogError as exc:
        message = f"Speech voice lookup returned HTTP {exc.status}; check provider voice-listing access. No audio was generated."
        return {"ok": False, "speech": message, "error": message}
    except Exception:
        message = "Speech voice lookup failed; no audio was generated"
        return {"ok": False, "speech": message, "error": message}
    count = data.get("count", len(data.get("items", [])))
    provider = data.get("provider", "speech")
    speech = f"Found {count} {provider} voices. No audio was generated."
    if data.get("partial"):
        speech += " The catalog is partial; see the lookup warning."
    return {"ok": True, "speech": speech, "data": data}


def main() -> int:
    try:
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except ValueError:
        result = {"ok": False, "speech": "Invalid JSON input", "error": "Invalid JSON input"}
    else:
        result = run(arguments)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
