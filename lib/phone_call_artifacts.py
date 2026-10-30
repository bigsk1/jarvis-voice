"""Retain phone-call transcripts and authenticated recordings in canonical Stash."""

from __future__ import annotations

import hashlib
import io
import re
import time
import wave
from urllib.parse import quote, urlsplit

import requests
from config_loader import get_active_config_mode, get_config_value
from filelock import FileLock, Timeout
from stash_helper import StashFile, StashSpace, get_space, open_space, safe_download

MAX_RECORDING_BYTES = 50 * 1024 * 1024
RECORDING_TIMEOUT = (5, 15)
RECORDING_STREAM_SECONDS = 45
_SPACE_ID = re.compile(r"space_phone_call_[a-f0-9]{24}\Z")


def _space_id(call_id: str) -> str:
    identity = f"{get_active_config_mode()}:{call_id}"
    return "space_phone_call_" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def _transcript_content(call_id: str, result: dict) -> str:
    transcript = result.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        return ""
    sections = [f"# Phone call\n\nCall ID: {call_id}"]
    for key, label in (("recipient", "Recipient"), ("task", "Task")):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            sections.append(f"{label}: {value.strip()}")
    summary = result.get("summary")
    if isinstance(summary, str) and summary.strip():
        sections.append(f"## Summary\n\n{summary.strip()}")
    sections.append(f"## Transcript\n\n{transcript.strip()}")
    return "\n\n".join(sections) + "\n"


def _save_transcript(space: StashSpace, content: str) -> str:
    """Refresh text without rotating an existing link on a late summary update."""
    data = content.encode("utf-8")
    with space.transaction():
        file = StashFile(space, name="transcript.md")
        previous = dict(file.meta or {})
        if previous.get("hash_sha256") == hashlib.sha256(data).hexdigest():
            if file.path and file.path.is_file():
                return f"stash://{space.space_id}/{previous['file_id']}"
        saved = file.save_binary(
            data,
            "transcript.md",
            mime_type="text/markdown",
            on_conflict="overwrite",
            tags=["phone_call_transcript"],
            tool_origin="phone_call",
        )
        previous_id = previous.get("file_id")
        if previous_id:
            for record in space.meta.get("files", []):
                if record.get("file_id") == saved["file_id"]:
                    record["file_id"] = previous_id
                    break
            space._save_meta()
            return f"stash://{space.space_id}/{previous_id}"
        return saved["ref"]


def _audio_type(data: bytes, claimed_type: str) -> tuple[str, str]:
    mime = claimed_type.split(";", 1)[0].strip().lower()
    if not (
        mime.startswith("audio/") or mime in {"application/octet-stream", "binary/octet-stream"}
    ):
        raise ValueError("Recording response is not audio")
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        with wave.open(io.BytesIO(data), "rb") as audio:
            if audio.getnframes() <= 0 or not audio.readframes(1):
                raise ValueError("Recording is empty")
        return "audio/wav", "wav"
    if data.startswith(b"OggS") and any(
        marker in data[:4096] for marker in (b"OpusHead", b"\x01vorbis")
    ):
        return "audio/ogg", "ogg"
    start = 0
    if data.startswith(b"ID3") and len(data) >= 10:
        if any(value & 0x80 for value in data[6:10]):
            raise ValueError("Invalid MP3 header")
        start = 10 + sum(value << shift for value, shift in zip(data[6:10], (21, 14, 7, 0)))
    for index in range(start, min(len(data) - 3, start + 4096)):
        header = data[index : index + 4]
        if (
            header[0] == 0xFF
            and header[1] & 0xE0 == 0xE0
            and header[1] & 0x18 != 0x08
            and header[1] & 0x06 != 0
            and 0 < header[2] >> 4 < 15
            and header[2] & 0x0C != 0x0C
        ):
            return "audio/mpeg", "mp3"
    raise ValueError("Recording has no supported audio signature")


def _cached_audio(space: StashSpace) -> dict | None:
    with space.transaction():
        for record in space.meta.get("files", []):
            if "phone_call_recording" not in record.get("tags", []):
                continue
            file = StashFile(space, file_id=record.get("file_id"))
            path = file.path
            if path and path.is_file() and 0 < path.stat().st_size <= MAX_RECORDING_BYTES:
                return {
                    "stash_ref": f"stash://{space.space_id}/{record['file_id']}",
                    "filename": record["name"],
                    "mime_type": record["mime_type"],
                }
    return None


def _read_audio_response(response) -> tuple[bytes, str]:
    length = response.headers.get("Content-Length")
    if length and int(length) > MAX_RECORDING_BYTES:
        raise ValueError("Recording exceeds the size limit")
    started = time.monotonic()
    content = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        if time.monotonic() - started > RECORDING_STREAM_SECONDS:
            raise ValueError("Recording exceeded the download deadline")
        if len(content) + len(chunk) > MAX_RECORDING_BYTES:
            raise ValueError("Recording exceeds the size limit")
        content.extend(chunk)
    return bytes(content), response.headers.get("Content-Type", "")


def _download_recording(call_id: str) -> tuple[bytes, str] | dict:
    key = get_config_value("VAPI_API_KEY")
    if not key:
        return {
            "audio_status": "failed",
            "audio_error": "Vapi recording credentials are unavailable.",
        }
    endpoint = f"https://api.vapi.ai/call/{quote(call_id, safe='')}/mono-recording"
    response = requests.get(
        endpoint,
        headers={"Authorization": f"Bearer {key}"},
        allow_redirects=False,
        timeout=RECORDING_TIMEOUT,
        stream=True,
    )
    try:
        status = response.status_code
        if status in {401, 403}:
            return {
                "audio_status": "failed",
                "audio_error": "Vapi recording access was not authorized.",
            }
        if status in {404, 409, 425, 429} or status >= 500:
            return {
                "audio_status": "pending",
                "audio_error": "Recording is not ready or is temporarily unavailable.",
            }
        if status in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location", "")
        elif status == 200:
            return _read_audio_response(response)
        else:
            return {"audio_status": "failed", "audio_error": "Vapi recording request was rejected."}
    finally:
        response.close()
    parsed = urlsplit(location)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid recording download destination")
    # This independent public downloader validates every redirect and receives no
    # Vapi headers. Never use save_from_url: signed URLs must not enter metadata.
    content, mime, _ = safe_download(location, max_size=MAX_RECORDING_BYTES)
    return content, mime


def save_call_artifacts(call_id: str, result: dict) -> dict:
    """Best-effort artifact collection; failure never changes the call's outcome."""
    saved = {
        "transcript_saved": False,
        "transcript_status": "unavailable",
        "audio_saved": False,
        "audio_status": "unavailable",
    }
    if not isinstance(call_id, str) or not call_id.strip() or not isinstance(result, dict):
        return saved
    try:
        space, _ = open_space(
            space_id=_space_id(call_id),
            labels=["phone_calls", "transcript"],
            scope="user",
        )
        saved["stash_space_id"] = space.space_id
    except Exception:
        return {
            **saved,
            "transcript_status": "failed",
            "transcript_error": "Call artifacts could not be stored in Stash.",
            "audio_status": "failed",
            "audio_error": "Call artifacts could not be stored in Stash.",
        }
    try:
        # Once the active-call marker is cleared, a status request may only know
        # the phone number. Retain the original task/name in the written record.
        with space.transaction():
            previous_context = space.meta.get("phone_call_context")
            context = dict(previous_context) if isinstance(previous_context, dict) else {}
            for key in ("recipient", "task"):
                value = result.get(key)
                if not context.get(key) and isinstance(value, str) and value.strip():
                    context[key] = value.strip()
            space.meta["phone_call_context"] = context
            space._save_meta()
        content = _transcript_content(call_id, {**result, **context})
        if content:
            saved["transcript_stash_ref"] = _save_transcript(space, content)
            saved.update(transcript_saved=True, transcript_status="saved")
    except Exception:
        saved.update(
            transcript_status="failed",
            transcript_error="The call transcript could not be stored in Stash.",
        )
    try:
        # This per-call lock never holds the root-wide Stash transaction during
        # network I/O, and a concurrent collector returns promptly for a retry.
        with FileLock(str(space.space_path / ".phone_artifacts.lock"), timeout=0):
            audio = _cached_audio(space)
            if audio:
                saved.update(
                    audio,
                    audio_stash_ref=audio["stash_ref"],
                    audio_saved=True,
                    audio_status="saved",
                )
                return saved
            if not result.get("recording_url"):
                return saved
            downloaded = _download_recording(call_id)
            if isinstance(downloaded, dict):
                saved.update(downloaded)
                return saved
            data, claimed_type = downloaded
            if not data or len(data) > MAX_RECORDING_BYTES:
                raise ValueError("Recording is empty or exceeds the size limit")
            mime, extension = _audio_type(data, claimed_type)
            artifact = StashFile(space).save_binary(
                data,
                f"recording.{extension}",
                mime_type=mime,
                tags=["phone_call_recording"],
                tool_origin="phone_call",
                on_conflict="overwrite",
            )
            saved.update(
                stash_ref=artifact["ref"],
                audio_stash_ref=artifact["ref"],
                filename=artifact["name"],
                mime_type=mime,
                audio_saved=True,
                audio_status="saved",
            )
    except Timeout:
        saved.update(
            audio_status="pending", audio_error="Recording collection is already in progress."
        )
    except Exception:
        saved.update(
            audio_status="failed",
            audio_error="The call recording could not be downloaded or stored.",
        )
    return saved


def get_call_canvas(space_id: str) -> dict:
    """Read the Canvas identity associated with this call's artifact space."""
    if not isinstance(space_id, str) or not _SPACE_ID.fullmatch(space_id):
        return {}
    try:
        space = get_space(space_id)
        with space.transaction():
            canvas = space.meta.get("phone_call_canvas")
            if isinstance(canvas, dict):
                return {
                    key: canvas[key]
                    for key in ("page_id", "title", "audio_stash_ref", "result_sha256")
                    if isinstance(canvas.get(key), str)
                }
    except Exception:
        pass
    return {}


def remember_call_canvas(
    space_id: str,
    page_id: str,
    title: str,
    audio_stash_ref: str | None = None,
    result_sha256: str | None = None,
) -> None:
    """Retain Canvas identity without replacing any other Stash metadata."""
    if not isinstance(space_id, str) or not _SPACE_ID.fullmatch(space_id):
        return
    if not isinstance(page_id, str) or not page_id:
        return
    try:
        space = get_space(space_id)
        with space.transaction():
            previous = space.meta.get("phone_call_canvas")
            canvas = dict(previous) if isinstance(previous, dict) else {}
            canvas.update(page_id=page_id, title=title)
            if isinstance(audio_stash_ref, str) and audio_stash_ref.startswith("stash://"):
                canvas["audio_stash_ref"] = audio_stash_ref
            if isinstance(result_sha256, str) and re.fullmatch(r"[a-f0-9]{64}", result_sha256):
                canvas["result_sha256"] = result_sha256
            space.meta["phone_call_canvas"] = canvas
            space._save_meta()
    except Exception:
        pass
