#!/usr/bin/env python3
"""Transcribe an existing audio file and preserve the full text in Stash."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from audio_transcription import PartialAudioTranscriptionError, transcribe_audio_file
from config_loader import load_config
from paths import resolve_local_file_tool_path, validate_tool_output_filename
from stash_helper import StashFile, get_space, open_space, safe_resolve_file, sanitize_filename
from stt_client import STTProviderError

TOOL_NAME = "transcribe_audio"
INLINE_TRANSCRIPT_CHARS = 6000


def _resolve_source(source: object) -> tuple[Path, str | None]:
    value = str(source or "").strip()
    if not value:
        raise ValueError("source is required")
    if value.startswith("stash://"):
        resolved = safe_resolve_file(stash_ref=value)
        if not resolved.get("found"):
            raise ValueError(resolved.get("error") or "Stash audio file was not found")
        return Path(str(resolved["path"])).resolve(), value

    path = resolve_local_file_tool_path(value, include_pictures=False)
    if not path.is_file():
        raise ValueError(f"Audio file does not exist: {value}")
    return path, None


def _prepare_output(args: dict[str, Any], source: Path) -> dict[str, Any]:
    save_to_stash = args.get("save_to_stash", True)
    if not isinstance(save_to_stash, bool):
        raise ValueError("save_to_stash must be true or false")

    requested_name = str(args.get("output_name") or "").strip()
    if requested_name:
        output_name = validate_tool_output_filename(requested_name)
    else:
        output_name = sanitize_filename(f"{source.stem}_transcript.txt")
    if not output_name.lower().endswith((".txt", ".md")):
        output_name = f"{output_name}.txt"

    output_space_id = str(args.get("output_space_id") or "").strip()
    space = get_space(output_space_id) if output_space_id else None
    return {
        "save_to_stash": save_to_stash,
        "output_name": output_name,
        "space": space,
    }


def _save_transcript(plan: dict[str, Any], transcript: str) -> tuple[str, str]:
    space = plan["space"]
    if space is None:
        space, _ = open_space(
            labels=["audio_transcripts", "audio_transcript", "transcript"]
        )
    saved = StashFile(space).save_text(
        transcript,
        plan["output_name"],
        on_conflict="version",
        tags=["audio_transcript", "transcript", "text"],
        tool_origin=TOOL_NAME,
    )
    return str(saved["ref"]), space.space_id


def _transcript_payload(
    transcript: str,
    *,
    transcript_stash_ref: str | None,
) -> dict[str, Any]:
    """Return exactly one inline text field without losing unsaved content."""

    if len(transcript) <= INLINE_TRANSCRIPT_CHARS or not transcript_stash_ref:
        return {
            "transcript": transcript,
            "transcript_truncated": False,
        }
    return {
        "transcript_excerpt": transcript[:INLINE_TRANSCRIPT_CHARS],
        "transcript_truncated": True,
    }


def _persist_transcript(
    plan: dict[str, Any],
    transcript: str,
) -> tuple[str | None, str | None, bool, str | None]:
    force_stash = not plan["save_to_stash"] and len(transcript) > INLINE_TRANSCRIPT_CHARS
    if not plan["save_to_stash"] and not force_stash:
        return None, None, False, None
    try:
        stash_ref, space_id = _save_transcript(plan, transcript)
        return stash_ref, space_id, force_stash, None
    except Exception:
        # The provider work has already completed. Return the complete text in
        # the tool result rather than converting a Stash failure into data loss.
        return None, None, force_stash, "The transcript could not be saved to Stash."


def _result_data(
    result,
    *,
    source_stash_ref: str | None,
    transcript: str,
    transcript_stash_ref: str | None,
    output_space_id: str | None,
    stash_forced: bool,
    transcript_save_error: str | None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source_filename": result.info.filename,
        "source_stash_ref": source_stash_ref,
        "size_bytes": result.info.size_bytes,
        "duration_seconds": round(result.info.duration_seconds, 3),
        "provider_requested": result.provider_requested,
        "provider": result.provider,
        "model": result.model,
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "chunk_count": result.chunk_count,
        "transcript_chars": len(transcript),
        "transcript_stash_ref": transcript_stash_ref,
        "stash_ref": transcript_stash_ref,
        "space_id": output_space_id,
        "stash_forced": stash_forced,
        "transcript_save_error": transcript_save_error,
    }
    data.update(
        _transcript_payload(
            transcript,
            transcript_stash_ref=transcript_stash_ref,
        )
    )
    return data


def execute(args: dict[str, Any]) -> dict[str, Any]:
    source, source_stash_ref = _resolve_source(args.get("source"))
    plan = _prepare_output(args, source)
    try:
        result = transcribe_audio_file(source)
    except PartialAudioTranscriptionError as exc:
        transcript = exc.partial_transcript
        stash_ref, space_id, stash_forced, save_error = _persist_transcript(
            plan, transcript
        )
        data = {
            "source_filename": source.name,
            "source_stash_ref": source_stash_ref,
            "partial": True,
            "completed_chunks": exc.completed_chunks,
            "chunk_count": exc.total_chunks,
            "transcript_chars": len(transcript),
            "transcript_stash_ref": stash_ref,
            "stash_ref": stash_ref,
            "space_id": space_id,
            "stash_forced": stash_forced,
            "transcript_save_error": save_error,
            "error_code": "audio_transcription_partial",
            "retryable": False,
        }
        data.update(
            _transcript_payload(transcript, transcript_stash_ref=stash_ref)
        )
        message = (
            f"Audio transcription stopped after {exc.completed_chunks} of "
            f"{exc.total_chunks} chunks: {exc}"
        )
        if stash_ref:
            message += " The partial transcript was saved to Stash."
        return {"ok": False, "speech": message, "error": message, "data": data}

    transcript = result.transcript
    transcript_stash_ref, output_space_id, stash_forced, save_error = (
        _persist_transcript(plan, transcript)
    )
    data = _result_data(
        result,
        source_stash_ref=source_stash_ref,
        transcript=transcript,
        transcript_stash_ref=transcript_stash_ref,
        output_space_id=output_space_id,
        stash_forced=stash_forced,
        transcript_save_error=save_error,
    )

    if transcript:
        speech = (
            f"Transcribed {round(result.info.duration_seconds / 60, 1)} minutes "
            f"of audio using {result.provider}."
        )
    else:
        speech = "The audio was processed, but no speech was detected."
    if transcript_stash_ref:
        speech += " The full transcript was saved to Stash."
    elif save_error:
        speech += " The full transcript is returned inline because Stash saving failed."
    return {"ok": True, "speech": speech, "data": data}


def main() -> int:
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        if not isinstance(args, dict):
            raise ValueError("Tool input must be a JSON object")
        load_config()
        result = execute(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    except STTProviderError as exc:
        message = f"Audio transcription provider failed: {exc}"
        print(json.dumps({
            "ok": False,
            "speech": message,
            "error": message,
            "data": {
                "error_code": "audio_transcription_provider_failed",
                "retryable": exc.retryable,
            },
        }, ensure_ascii=False))
        return 1
    except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        message = f"Audio transcription failed: {exc}"
        print(json.dumps({
            "ok": False,
            "speech": message,
            "error": message,
            "data": {"error_code": "audio_transcription_invalid"},
        }, ensure_ascii=False))
        return 1
    except Exception:
        message = "Audio transcription failed because of an unexpected local error."
        print(json.dumps({
            "ok": False,
            "speech": message,
            "error": message,
            "data": {"error_code": "audio_transcription_failed"},
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
