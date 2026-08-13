"""Fixed-file bridge from Jarvis Web to the FastAPI Intel CRUD routes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import requests

from internal_api import get_internal_api_base_url, get_internal_api_headers
from user_profile import extract_profile_card


USER_PROFILE_FILENAME = "user-profile.md"
USER_PROFILE_MAX_BYTES = 256 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[3]
STARTER_PROFILE_PATH = PROJECT_ROOT / "jarvis-intel" / "user-profile.md.example"


class UserProfileServiceError(RuntimeError):
    """A safe user-facing error from the profile bridge."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def _content_revision(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _starter_profile() -> str:
    try:
        return STARTER_PROFILE_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "# User Profile\n\n"
            "## Profile Card\n\n"
            "- **Who**: (your name or callsign and what you use Jarvis for)\n"
            "- **Treat me as**: (your preferred level of technical detail)\n"
            "- **How I work**: (your stable working preferences)\n"
            "- **Honesty**: Report failures and stale data plainly.\n\n"
            "## Profile Reference\n\n"
            "Optional longer notes that semantic recall can retrieve when relevant.\n"
        )


def _safe_response_detail(response: requests.Response, fallback: str) -> str:
    if response.status_code >= 500:
        return fallback
    try:
        payload = response.json()
    except ValueError:
        return fallback
    if not isinstance(payload, dict):
        return fallback
    detail = payload.get("detail") or payload.get("error") or payload.get("message")
    return str(detail)[:400] if detail else fallback


def _intel_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
) -> requests.Response:
    try:
        return requests.request(
            method,
            f"{get_internal_api_base_url()}{path}",
            headers=get_internal_api_headers(),
            json=payload,
            timeout=(3, 20),
        )
    except requests.RequestException as exc:
        raise UserProfileServiceError(
            "Jarvis API is unavailable, so the user profile could not be accessed.",
            503,
        ) from exc


def get_user_profile(mode: str | None = None) -> dict[str, Any]:
    """Read the canonical profile through FastAPI's existing Intel route."""
    mode_query = f"?mode={mode}" if mode in {"cloud", "local"} else ""
    response = _intel_request(
        "GET",
        f"/api/intel/{USER_PROFILE_FILENAME}{mode_query}",
    )
    if response.status_code == 404:
        return {
            "exists": False,
            "filename": USER_PROFILE_FILENAME,
            "content": "",
            "revision": None,
            "starter_template": _starter_profile(),
            "modified_at": None,
            "ingested": False,
            "fact_count": 0,
        }
    if response.status_code >= 400:
        raise UserProfileServiceError(
            _safe_response_detail(response, "The user profile could not be loaded."),
            response.status_code,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise UserProfileServiceError("Jarvis API returned an invalid profile response.", 502) from exc
    content = str(payload.get("content") or "")
    metadata = payload.get("file") if isinstance(payload.get("file"), dict) else {}
    try:
        fact_count = int(metadata.get("fact_count") or 0)
    except (TypeError, ValueError):
        fact_count = 0
    return {
        "exists": True,
        "filename": USER_PROFILE_FILENAME,
        "content": content,
        "revision": _content_revision(content),
        "starter_template": None,
        "modified_at": metadata.get("modified_at"),
        "ingested": bool(metadata.get("ingested")),
        "fact_count": fact_count,
    }


def save_user_profile(
    content: str,
    *,
    mode: str,
    expected_exists: bool,
    expected_revision: str | None,
) -> dict[str, Any]:
    """Create or replace user-profile.md and start existing Intel ingestion."""
    if not isinstance(content, str):
        raise UserProfileServiceError("Profile content must be text.", 400)
    if len(content.encode("utf-8")) > USER_PROFILE_MAX_BYTES:
        raise UserProfileServiceError("User profile is too large (maximum 256 KB).", 400)
    if not extract_profile_card(content):
        raise UserProfileServiceError(
            "Add a non-empty '## Profile Card' section before saving.",
            400,
        )

    if mode not in {"cloud", "local"}:
        raise UserProfileServiceError("Mode must be 'cloud' or 'local'.", 400)

    current = get_user_profile(mode)
    if bool(expected_exists) != current["exists"]:
        raise UserProfileServiceError(
            "The user profile changed after it was opened. Reload it before saving.",
            409,
        )
    if current["exists"] and expected_revision != current["revision"]:
        raise UserProfileServiceError(
            "The user profile changed after it was opened. Reload it before saving.",
            409,
        )

    request_payload = {"content": content, "auto_ingest": True}
    if current["exists"]:
        response = _intel_request(
            "PUT",
            f"/api/intel/{USER_PROFILE_FILENAME}?mode={mode}",
            payload=request_payload,
        )
    else:
        response = _intel_request(
            "POST",
            f"/api/intel?mode={mode}",
            payload={"filename": USER_PROFILE_FILENAME, **request_payload},
        )
    if response.status_code >= 400:
        raise UserProfileServiceError(
            _safe_response_detail(response, "The user profile could not be saved."),
            response.status_code,
        )

    try:
        mutation_result = response.json()
    except ValueError:
        mutation_result = {}
    if not isinstance(mutation_result, dict):
        mutation_result = {}

    saved = get_user_profile(mode)
    saved["ingestion_started"] = bool(mutation_result.get("ingestion_started", True))
    saved["ingest_modes"] = [
        item for item in (mutation_result.get("ingest_modes") or [])
        if item in {"cloud", "local"}
    ]
    ingest_warning = mutation_result.get("ingest_warning")
    saved["ingest_warning"] = str(ingest_warning)[:400] if ingest_warning else None
    return saved
