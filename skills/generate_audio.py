#!/usr/bin/env python3
"""Create a reusable speech recording without changing Jarvis's runtime voice."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from audio_generation import resolve_audio_settings, synthesize_audio  # noqa: E402
from config_loader import get_project_root, load_config  # noqa: E402
from remote_completion import RemoteCompletionError, completion_for_error  # noqa: E402
from stash_helper import StashFile, open_space  # noqa: E402

_FIELDS = {"text", "provider", "voice", "model", "title", "instructions"}


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _save_audio(settings: dict, audio: dict, root: Path) -> dict:
    """Keep a local copy even if enrolling the already-generated audio fails."""
    extension = audio["extension"]
    if extension not in {"mp3", "wav"} or not isinstance(audio["audio_bytes"], bytes):
        raise ValueError("The speech provider did not return a supported audio recording")
    title = settings.get("title") or "Generated speech"
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40] or "speech"
    stem = f"speech_{slug}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex}"
    path = root / f"{stem}.{extension}"
    _atomic_write(path, audio["audio_bytes"])
    data = {
        "provider": settings["provider"], "model": settings["model"],
        "voice": settings["voice"], "title": title,
        "file_path": str(path), "filename": path.name, "mime_type": audio["mime_type"],
        "audio_url": f"/api/generated-audio/{path.name}", "recovery_available": True,
        "duration_seconds": audio.get("duration_seconds"),
        "size_bytes": len(audio["audio_bytes"]), "text_chars": len(settings["text"]),
        "saved": {"saved": True, "path": str(path), "filename": path.name, "stash": False},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if audio.get("duration_warning"):
        data["duration_warning"] = audio["duration_warning"]
    if settings.get("instructions"):
        data["instructions"] = settings["instructions"]
    metadata_path = root / f"{stem}.json"
    try:
        # Persist a recovery receipt before optional Stash enrollment.
        _atomic_write(metadata_path, json.dumps(data, indent=2).encode("utf-8"))
        script_path = root / f"{stem}.txt"
        _atomic_write(script_path, settings["text"].encode("utf-8"))
        data["script_path"] = str(script_path)
        space, _ = open_space(scope="project", labels=["generated_audio", "audio", "speech"])
        files = StashFile(space)
        recording = files.save_binary(
            audio["audio_bytes"], name=path.name, mime_type=audio["mime_type"],
            tags=["generated_audio", "speech", settings["provider"]], tool_origin="generate_audio",
        )
        data.update({"stash_ref": recording["ref"], "space_id": space.space_id})
        data["saved"].update({"stash": True, "stash_ref": recording["ref"], "space_id": space.space_id})
        script = files.save_text(
            settings["text"], name=script_path.name,
            tags=["speech_script", "text"], tool_origin="generate_audio",
        )
        data["script_ref"] = script["ref"]
        with space.transaction():
            for entry in space.meta["files"]:
                if entry["file_id"] == recording["file_id"]:
                    entry.update({key: data[key] for key in (
                        "provider", "model", "voice", "duration_seconds", "script_ref",
                    )})
                    if "instructions" in data:
                        entry["instructions"] = data["instructions"]
            space._save_meta()
    except Exception:
        data["save_error"] = "Some audio metadata or Stash artifacts could not be saved. Reuse the existing recording; do not regenerate it."
    try:
        _atomic_write(metadata_path, json.dumps(data, indent=2).encode("utf-8"))
    except OSError:
        data["save_error"] = "The audio was saved locally but its metadata could not be saved. Reuse the existing recording; do not regenerate it."
    return data


def run(arguments: dict) -> dict:
    generated = False
    try:
        if not isinstance(arguments, dict) or set(arguments) - _FIELDS:
            raise ValueError("Use only the documented generate_audio arguments")
        load_config()
        settings = resolve_audio_settings(arguments)
        root = Path(get_project_root()) / "data" / "generated_audio"
        root.mkdir(parents=True, exist_ok=True)
        # Check the destination before making a potentially billed request.
        with tempfile.TemporaryFile(dir=root):
            pass
        audio = synthesize_audio(settings)
        generated = True
        data = _save_audio(settings, audio, root)
        if data.get("save_error"):
            message = "The audio was generated and saved locally, but saving all artifacts failed. Reuse the existing recording; do not regenerate it."
            return {"ok": False, "completion": "completed", "speech": message, "error": message, "data": data}
        return {
            "ok": True, "completion": "completed",
            "speech": f"Generated speech with {settings['provider']} and saved the audio and script to Stash.",
            "data": data,
        }
    except Exception as exc:
        completion = "completed" if generated else completion_for_error(exc)
        if isinstance(exc, ValueError) and not generated:
            completion = "rejected"
        if not generated and isinstance(exc, (ValueError, RemoteCompletionError)):
            message = str(exc)
        else:
            message = "Audio generation could not finish. Do not automatically repeat a request whose outcome is uncertain."
        return {"ok": False, "completion": completion, "error": message, "speech": message}


def main() -> int:
    try:
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
    except (ValueError, OSError):
        result = {"ok": False, "completion": "rejected", "error": "Invalid JSON input", "speech": "Invalid JSON input"}
    else:
        result = run(arguments)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
