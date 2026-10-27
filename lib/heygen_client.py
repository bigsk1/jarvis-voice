"""Small opt-in HeyGen v3 client. Submit once; observe or collect by native ID."""

from __future__ import annotations

import math
import re
import time
import uuid
from pathlib import Path

import requests
from config_loader import get_active_config_mode, get_config_value
from heygen_media import media_input, save_result
from http_client import http_request
from remote_completion import RemoteCompletionError, completion_for_error, submission_error
from stash_helper import StashFile, open_space
from tool_availability import is_env_configured
from tool_progress import emit_tool_progress

API_URL = "https://api.heygen.com"
VIDEO_MODEL = "heygen-video-1"
CLIP_RATES = {"480p": 0.01, "768p": 0.018, "1080p": 0.04, "2k": 0.05}
CLIP_ASPECTS = {"16:9", "9:16", "4:3", "1:1", "3:4", "21:9"}
_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


def is_heygen_configured() -> bool:
    """A configured key is the only opt-in; never probe the account at discovery."""
    return is_env_configured("HEYGEN_API_KEY")


class HeyGenError(RuntimeError):
    """Safe public error plus bounded recovery identifiers, never credentials."""

    def __init__(self, message: str, recovery: dict | None = None):
        super().__init__(message)
        self.recovery = dict(recovery or {})


def heygen_error_result(error: Exception) -> dict:
    """Return truthful completion evidence without exposing HTTP headers/bodies."""
    safe = isinstance(error, (HeyGenError, RemoteCompletionError, ValueError))
    message = str(error) if safe else "HeyGen operation failed; check the existing job before retrying"
    recovery = dict(getattr(error, "recovery", {}) or {})
    completion = completion_for_error(error)
    if isinstance(error, ValueError) and not recovery:
        completion = "rejected"
    return {
        "ok": False,
        "speech": message,
        "error": message,
        "completion": completion,
        "data": recovery,
    }


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("A valid HeyGen video, avatar, or voice ID is required")
    return value


def _with_recovery(error: Exception, recovery: dict) -> Exception:
    setattr(error, "recovery", dict(recovery))
    return error


def _observer_wait(timeout_seconds: float | None = None) -> float:
    """Validate the observer setting before starting paid work."""
    try:
        wait = float(timeout_seconds if timeout_seconds is not None else get_config_value("HEYGEN_WAIT_SECONDS", "300"))
    except (TypeError, ValueError):
        raise ValueError("HEYGEN_WAIT_SECONDS must be a finite number from 0 to 900") from None
    if not math.isfinite(wait):
        raise ValueError("HEYGEN_WAIT_SECONDS must be a finite number from 0 to 900")
    return max(0, min(wait, 900))


class HeyGenClient:
    """Use the selected mode's API wallet without OAuth or automatic POST retries."""

    def __init__(self):
        if not is_heygen_configured():
            raise ValueError("HeyGen is not configured. Set HEYGEN_API_KEY in the active mode env.")
        self._key = str(get_config_value("HEYGEN_API_KEY", "")).strip()
        self.mode = get_active_config_mode()

    def _request(self, method: str, path: str, *, submission: bool = False,
                 idempotency_key: str | None = None, **kwargs) -> dict:
        headers = {"X-Api-Key": self._key}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = http_request(
                method, API_URL + path, headers=headers, timeout=(10, 60),
                proxy_policy="off", allow_redirects=False, **kwargs,
            )
        except requests.RequestException:
            raise HeyGenError("HeyGen connection interrupted; do not submit again to check status") from None
        try:
            if response.status_code >= 300:
                message = f"HeyGen returned HTTP {response.status_code}"
                if submission:
                    raise submission_error(response.status_code, message)
                raise HeyGenError(message)
            try:
                payload = response.json()
            except (ValueError, TypeError):
                raise HeyGenError("HeyGen returned an unreadable response; do not resubmit") from None
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, (dict, list)):
                raise HeyGenError("HeyGen returned no usable data; do not resubmit")
            normalized = dict(data) if isinstance(data, dict) else {"items": data}
            for key in ("next_token", "has_more"):
                if key in payload:
                    normalized[key] = payload[key]
            return normalized
        finally:
            response.close()

    def account(self) -> dict:
        """Expose wallet/plan information without returning personal profile fields."""
        data = self._request("GET", "/v3/users/me")
        return {key: data.get(key) for key in ("billing_type", "wallet", "subscription", "usage_based")}

    def _catalog(self, path: str, limit: int, cursor: str | None) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("Catalog limit must be an integer from 1 to 50")
        params = {"limit": limit}
        if cursor:
            params["token"] = str(cursor)[:500]
        data = self._request("GET", path, params=params)
        items = data.get("items", data.get("avatars", data.get("voices", data.get("looks", []))))
        if not isinstance(items, list):
            raise HeyGenError("HeyGen returned an unreadable catalog")
        allowed = {"id", "avatar_id", "voice_id", "name", "avatar_name", "display_name", "gender",
                   "language", "locale", "preview_image_url", "preview_video_url", "preview_audio",
                   "preview_audio_url", "avatar_type", "is_public", "group_id", "default_voice_id",
                   "supported_api_engines", "available_engines", "default_engine", "status"}
        normalized = [{key: value for key, value in item.items() if key in allowed}
                      for item in items if isinstance(item, dict)]
        cursor = data.get("next_token") or data.get("next_cursor")
        return {"items": normalized, "next_cursor": cursor, "has_more": bool(cursor)}

    def list_avatars(self, limit: int = 20, cursor: str | None = None) -> dict:
        """Return looks: their IDs, rather than avatar group IDs, render videos."""
        return self._catalog("/v3/avatars/looks", limit, cursor)

    def list_voices(self, limit: int = 20, cursor: str | None = None) -> dict:
        return self._catalog("/v3/voices", limit, cursor)

    def _upload(self, path: Path, mime_type: str) -> str:
        with path.open("rb") as stream:
            data = self._request("POST", "/v3/assets", submission=True,
                                 files={"file": (path.name, stream, mime_type)})
        asset_id = data.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            raise HeyGenError("HeyGen upload returned no asset ID; no video was submitted")
        return asset_id

    def _input(self, source: str, kind: str) -> dict:
        try:
            return media_input(source, kind, self._upload)
        except ValueError:
            raise
        except Exception as exc:
            # Asset preparation precedes the paid /videos submission boundary.
            raise RemoteCompletionError("HeyGen input preparation failed; no video was submitted", "rejected") from exc

    def _submit(self, kind: str, payload: dict, context: dict) -> dict:
        request_id = "jarvis-heygen-" + uuid.uuid4().hex
        space, _ = open_space(labels=["heygen", "receipt", "generated_videos", self.mode], scope="project")
        request = {"provider": "heygen", "request_id": request_id, "kind": kind, "mode": self.mode}
        request_file = StashFile(space).save_json(request, name="heygen_request.json", tool_origin="heygen")
        recovery = {**request, "receipt_stash_ref": request_file["ref"]}
        emit_tool_progress({"phase": "Submitting to HeyGen", "recovery": {
            "request_id": request_id, "receipt_stash_ref": request_file["ref"],
        }})
        try:
            path = "/v3/models/videos" if kind == "model" else "/v3/videos"
            data = self._request("POST", path, submission=True, idempotency_key=request_id, json=payload)
            video_id = _identifier(data.get("video_id") or data.get("id") or "")
            recovery["provider_video_id"] = video_id
            recovery["task_id"] = video_id
            job_file = StashFile(space).save_json(recovery, name="heygen_job.json", tool_origin="heygen")
            recovery["receipt_stash_ref"] = job_file["ref"]
        except Exception as exc:
            if isinstance(exc, ValueError):
                exc = HeyGenError("HeyGen submission returned no usable video ID; check the receipt before retrying")
            raise _with_recovery(exc, recovery)
        emit_tool_progress({"phase": "HeyGen accepted the video", "recovery": {
            "task_id": video_id, "request_id": request_id,
            "receipt_stash_ref": recovery["receipt_stash_ref"],
        }})
        return {**context, **recovery, "status": "pending", "video_id": video_id}

    def generate_clip(self, prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
                      resolution: str = "480p", image_source: str | None = None,
                      model: str = VIDEO_MODEL) -> dict:
        _observer_wait()
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
            raise ValueError("HeyGen requires a prompt from 1 to 20000 characters")
        if isinstance(duration, bool) or not isinstance(duration, int) or not 5 <= duration <= 15:
            raise ValueError("HeyGen clips in Jarvis must be 5 to 15 whole seconds")
        if model != VIDEO_MODEL:
            raise ValueError("This integration supports only heygen-video-1")
        resolution = "768p" if resolution == "720p" else resolution
        if resolution not in CLIP_RATES or aspect_ratio not in CLIP_ASPECTS:
            raise ValueError("Unsupported HeyGen resolution or aspect ratio")
        payload = {"model": model, "mode": "image_to_video" if image_source else "text_to_video",
                   "prompt": prompt, "duration": duration, "resolution": resolution,
                   "prompt_enhancement": "quality"}
        if image_source:
            payload["image"] = self._input(image_source, "image")
        else:
            payload["aspect_ratio"] = aspect_ratio
        context = {"provider": "heygen", "model": model, "duration": duration,
                   "aspect_ratio": aspect_ratio, "resolution": resolution,
                   "from_image": bool(image_source), "has_audio": True,
                   "estimated_cost_usd": round(duration * CLIP_RATES[resolution], 4)}
        job = self._submit("model", payload, context)
        return self.wait_for_video(job["video_id"], "model", context=job)

    def submit_avatar(self, script: str | None = None, avatar_id: str | None = None,
                      image_source: str | None = None, voice_id: str | None = None,
                      audio_source: str | None = None, title: str = "",
                      aspect_ratio: str = "16:9", resolution: str = "720p") -> dict:
        if bool(avatar_id) == bool(image_source):
            raise ValueError("Choose exactly one avatar_id or image_source")
        if bool(script) == bool(audio_source):
            raise ValueError("Choose exactly one script or audio_source")
        if script and (not isinstance(script, str) or len(script) > 1000 or len(script.split()) > 75):
            raise ValueError("Presenter scripts are limited to 75 words and 1000 characters")
        if script and (not script.strip() or not voice_id):
            raise ValueError("A nonempty exact script and a discovered voice_id are required")
        if resolution not in {"720p", "1080p"} or aspect_ratio not in {"16:9", "9:16", "1:1", "auto"}:
            raise ValueError("Unsupported presenter resolution or aspect ratio")
        if len(title) > 200:
            raise ValueError("Video title is limited to 200 characters")
        payload = {"type": "avatar" if avatar_id else "image", "resolution": resolution,
                   "aspect_ratio": aspect_ratio}
        if avatar_id:
            payload["avatar_id"] = _identifier(avatar_id)
            # Only saved-avatar requests accept an engine selector. The strict
            # image request schema rejects it and uses Avatar IV implicitly.
            payload["engine"] = {"type": "avatar_iv"}
        if script:
            payload.update({"script": script, "voice_id": _identifier(voice_id)})
        if title:
            payload["title"] = title
        if image_source:
            payload["image"] = self._input(image_source, "image")
        if audio_source:
            audio = self._input(audio_source, "audio")
            payload["audio_asset_id" if audio["type"] == "asset_id" else "audio_url"] = (
                audio.get("asset_id") or audio.get("url")
            )
        context = {"provider": "heygen", "model": "avatar_iv", "aspect_ratio": aspect_ratio,
                   "resolution": resolution, "has_audio": True}
        if script:
            duration = max(1, len(script.split()) / 2.5)
            context["estimated_cost_usd"] = round(duration / 60 * (4.83 if avatar_id else 2.31), 4)
        return self._submit("avatar", payload, context)

    def generate_avatar(self, **kwargs) -> dict:
        _observer_wait()
        job = self.submit_avatar(**kwargs)
        return self.wait_for_video(job["video_id"], "avatar", context=job)

    def status(self, video_id: str, kind: str = "model") -> dict:
        video_id = _identifier(video_id)
        if kind not in {"model", "avatar"}:
            raise ValueError("HeyGen job kind must be model or avatar")
        path = "/v3/models/videos/" if kind == "model" else "/v3/videos/"
        data = self._request("GET", path + video_id)
        result = {key: data[key] for key in (
            "status", "video_url", "duration", "width", "height", "aspect_ratio", "model",
            "failure_code", "failure_message", "thumbnail_url",
        ) if key in data}
        result.update({"provider": "heygen", "provider_video_id": video_id,
                       "video_id": video_id, "kind": kind})
        result.setdefault("model", VIDEO_MODEL if kind == "model" else "avatar_iv")
        if result.get("status") not in {"pending", "queued", "waiting", "processing", "completed", "failed", "cancelled"}:
            raise HeyGenError("HeyGen returned an unknown job state", {
                "provider": "heygen", "provider_video_id": video_id, "kind": kind,
            })
        return result

    def wait_for_video(self, video_id: str, kind: str = "model", context: dict | None = None,
                       timeout_seconds: float | None = None) -> dict:
        context = dict(context or {})
        recovery = {key: context[key] for key in (
            "request_id", "receipt_stash_ref", "kind", "provider_video_id", "task_id", "mode",
        ) if key in context}
        recovery.update({"provider_video_id": video_id, "task_id": video_id, "kind": kind, "provider": "heygen"})
        try:
            wait = _observer_wait(timeout_seconds)
            deadline = time.monotonic() + wait
            while True:
                result = self.status(video_id, kind)
                if result["status"] == "completed":
                    if not result.get("video_url"):
                        raise HeyGenError("HeyGen completed but returned no download URL", recovery)
                    return {**context, **result}
                if result["status"] in {"failed", "cancelled"}:
                    raise _with_recovery(RemoteCompletionError(
                        f"HeyGen video {result['status']}; no replacement was submitted", "completed"), recovery)
                if time.monotonic() >= deadline:
                    raise HeyGenError("HeyGen is still processing. Check or collect this existing job; do not regenerate", recovery)
                time.sleep(min(10, max(0, deadline - time.monotonic())))
        except Exception as exc:
            raise _with_recovery(exc, recovery)

    def collect(self, video_id: str, kind: str = "model") -> dict:
        result = self.status(video_id, kind)
        if result["status"] != "completed":
            return {"ok": result["status"] not in {"failed", "cancelled"},
                    "speech": f"HeyGen video is {result['status']}; no new video was submitted", "data": result}
        return save_result(result)
