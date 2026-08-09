"""Protected Canvas proxies for FastAPI-owned generated-audio actions."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

import requests
from audio_catalog import AUDIO_EXTENSIONS
from flask import Blueprint, jsonify, request
from internal_api import get_internal_api_base_url, get_internal_api_headers

audio_actions_bp = Blueprint("audio_actions", __name__)
_SHARE_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _is_safe_audio_filename(filename: str) -> bool:
    return bool(
        filename
        and filename == Path(filename).name
        and ".." not in filename
        and "/" not in filename
        and "\\" not in filename
        and Path(filename).suffix.lower() in AUDIO_EXTENSIONS
    )


def _proxy_response(response):
    try:
        payload = response.json()
    except ValueError:
        payload = {"ok": False, "error": "Jarvis API returned an invalid response."}
    if isinstance(payload, dict) and "detail" in payload and "error" not in payload:
        detail = payload.get("detail")
        if isinstance(detail, dict):
            payload = {
                "ok": False,
                "error": detail.get("message") or "Request failed.",
                **detail,
            }
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


@audio_actions_bp.route("/api/xai-audio-shares/status", methods=["GET"])
def xai_audio_share_status():
    return _request_fastapi(
        "GET",
        "/api/generated-music/xai-shares/status",
        timeout=10,
    )


@audio_actions_bp.route("/api/xai-audio-shares/preview", methods=["POST"])
def preview_xai_audio_share():
    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename") or "")
    if not _is_safe_audio_filename(filename):
        return jsonify({"ok": False, "error": "Invalid audio filename."}), 400
    return _request_fastapi(
        "POST",
        "/api/generated-music/xai-shares/preview",
        json={"filename": filename},
        timeout=45,
    )


@audio_actions_bp.route("/api/xai-audio-shares/list", methods=["GET"])
def list_xai_audio_shares():
    filename = str(request.args.get("filename") or "")
    if not _is_safe_audio_filename(filename):
        return jsonify({"ok": False, "error": "Invalid audio filename."}), 400
    return _request_fastapi(
        "GET",
        "/api/generated-music/xai-shares",
        params={"filename": filename},
        timeout=15,
    )


@audio_actions_bp.route("/api/xai-audio-shares/publish", methods=["POST"])
def publish_xai_audio_share():
    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename") or "")
    if not _is_safe_audio_filename(filename):
        return jsonify({"ok": False, "error": "Invalid audio filename."}), 400
    return _request_fastapi(
        "POST",
        "/api/generated-music/xai-shares/publish",
        json={
            "filename": filename,
            "ttl_days": data.get("ttl_days"),
            "expected_audio_sha256": data.get("expected_audio_sha256"),
            "confirmed": data.get("confirmed") is True,
        },
        timeout=1200,
    )


@audio_actions_bp.route("/api/xai-audio-shares/revoke", methods=["DELETE"])
def revoke_xai_audio_share():
    data = request.get_json(silent=True) or {}
    share_id = str(data.get("share_id") or "")
    if not _SHARE_ID_RE.fullmatch(share_id):
        return jsonify({"ok": False, "error": "Invalid share identifier."}), 400
    return _request_fastapi(
        "DELETE",
        "/api/generated-music/xai-shares/revoke",
        json={"share_id": share_id},
        timeout=60,
    )


@audio_actions_bp.route("/api/audio-actions/delete", methods=["DELETE"])
def delete_local_audio():
    """Ask FastAPI to delete retained audio and catalog metadata."""
    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename") or "")
    if not _is_safe_audio_filename(filename):
        return jsonify({"ok": False, "error": "Invalid audio filename."}), 400

    encoded_filename = quote(filename, safe="")
    return _request_fastapi(
        "DELETE",
        f"/api/generated-music/{encoded_filename}",
        params={"revoke_public_shares": data.get("revoke_public_shares") is True},
        timeout=120,
    )
