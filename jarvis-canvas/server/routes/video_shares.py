"""Protected Canvas proxies for FastAPI-owned generated-video actions."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

import requests
from flask import Blueprint, jsonify, request
from internal_api import get_internal_api_base_url, get_internal_api_headers

from config import GENERATED_VIDEOS_DIR

video_shares_bp = Blueprint("video_shares", __name__)
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
_SHARE_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _is_safe_video_filename(filename: str, *, mp4_only: bool = False) -> bool:
    extension = Path(filename).suffix.lower() if filename else ""
    return bool(
        filename
        and filename == Path(filename).name
        and ".." not in filename
        and "/" not in filename
        and "\\" not in filename
        and extension in ({".mp4"} if mp4_only else VIDEO_EXTENSIONS)
    )


def _proxy_response(response):
    try:
        payload = response.json()
    except ValueError:
        payload = {"ok": False, "error": "Jarvis API returned an invalid response."}
    if isinstance(payload, dict) and "detail" in payload and "error" not in payload:
        detail = payload.get("detail")
        if isinstance(detail, dict):
            payload = {"ok": False, "error": detail.get("message") or "Request failed.", **detail}
        else:
            payload = {"ok": False, "error": str(detail)}
    return jsonify(payload), response.status_code


def _request_fastapi(method: str, path: str, *, timeout: int, **kwargs):
    url = f"{get_internal_api_base_url()}{path}"
    try:
        response = requests.request(
            method,
            url,
            headers=get_internal_api_headers(),
            timeout=timeout,
            **kwargs,
        )
    except requests.exceptions.RequestException:
        return jsonify({"ok": False, "error": "Jarvis API is unavailable."}), 502
    return _proxy_response(response)


@video_shares_bp.route("/api/xai-video-shares/status", methods=["GET"])
def xai_video_share_status():
    return _request_fastapi(
        "GET",
        "/api/generated-videos/xai-shares/status",
        timeout=10,
    )


@video_shares_bp.route("/api/xai-video-shares/preview", methods=["POST"])
def preview_xai_video_share():
    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename") or "")
    if not _is_safe_video_filename(filename, mp4_only=True):
        return jsonify({"ok": False, "error": "Only retained MP4 videos can be shared."}), 400
    return _request_fastapi(
        "POST",
        "/api/generated-videos/xai-shares/preview",
        json={"filename": filename},
        timeout=45,
    )


@video_shares_bp.route("/api/xai-video-shares/list", methods=["GET"])
def list_xai_video_shares():
    filename = str(request.args.get("filename") or "")
    if not _is_safe_video_filename(filename, mp4_only=True):
        return jsonify({"ok": False, "error": "Invalid video filename."}), 400
    return _request_fastapi(
        "GET",
        "/api/generated-videos/xai-shares",
        params={"filename": filename},
        timeout=15,
    )


@video_shares_bp.route("/api/xai-video-shares/publish", methods=["POST"])
def publish_xai_video_share():
    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename") or "")
    if not _is_safe_video_filename(filename, mp4_only=True):
        return jsonify({"ok": False, "error": "Only retained MP4 videos can be shared."}), 400
    payload = {
        "filename": filename,
        "ttl_days": data.get("ttl_days"),
        "expected_video_sha256": data.get("expected_video_sha256"),
        "confirmed": data.get("confirmed") is True,
    }
    return _request_fastapi(
        "POST",
        "/api/generated-videos/xai-shares/publish",
        json=payload,
        timeout=240,
    )


@video_shares_bp.route("/api/xai-video-shares/revoke", methods=["DELETE"])
def revoke_xai_video_share():
    data = request.get_json(silent=True) or {}
    share_id = str(data.get("share_id") or "")
    if not _SHARE_ID_RE.fullmatch(share_id):
        return jsonify({"ok": False, "error": "Invalid share identifier."}), 400
    return _request_fastapi(
        "DELETE",
        "/api/generated-videos/xai-shares/revoke",
        json={"share_id": share_id},
        timeout=60,
    )


@video_shares_bp.route("/api/video-actions/delete", methods=["DELETE"])
def delete_local_video():
    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename") or "")
    if not _is_safe_video_filename(filename):
        return jsonify({"ok": False, "error": "Invalid video filename."}), 400
    encoded_filename = quote(filename, safe="")
    response, status_code = _request_fastapi(
        "DELETE",
        f"/api/generated-videos/{encoded_filename}",
        params={"revoke_public_shares": data.get("revoke_public_shares") is True},
        timeout=120,
    )
    if status_code < 300:
        thumbnail = GENERATED_VIDEOS_DIR / ".thumbnails" / f"{Path(filename).stem}.jpg"
        try:
            thumbnail.unlink(missing_ok=True)
        except OSError:
            pass
    return response, status_code
