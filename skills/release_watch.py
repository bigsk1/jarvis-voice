#!/usr/bin/env python3
"""Detect new stable PyPI or GitHub releases with explicit acknowledgement."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from packaging.version import InvalidVersion, Version

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from http_client import get_proxy_chain, proxy_response_indicates_tunnel_failure


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_ROOT = PROJECT_ROOT / "data" / "release-watch"
WATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PYPI_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
GITHUB_REPO_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<repo>[A-Za-z0-9_.-]{1,100})$"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _state_root() -> Path:
    configured = os.getenv("RELEASE_WATCH_STATE_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_STATE_ROOT


def _state_path(watch_id: str) -> Path:
    if not WATCH_ID_RE.fullmatch(watch_id):
        raise ValueError("watch_id must contain only letters, numbers, dots, dashes, or underscores")
    return _state_root() / f"{watch_id}.json"


def _read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read release-watch state {path}: {exc}") from exc
    if not isinstance(data, dict) or not data.get("version"):
        raise ValueError(f"Invalid release-watch state in {path}")
    return data


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}-",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        temporary_path.unlink(missing_ok=True)


def _request_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "jarvis-release-watch/1.0",
    }
    last_error: Exception | None = None
    attempted_direct = False

    for proxies in get_proxy_chain():
        if proxies is None:
            attempted_direct = True
        try:
            response = requests.get(url, headers=headers, timeout=timeout, proxies=proxies)
            if proxy_response_indicates_tunnel_failure(response):
                response.close()
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"Expected a JSON object from {url}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc

    if not attempted_direct:
        try:
            response = requests.get(url, headers=headers, timeout=timeout, proxies=None)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"Expected a JSON object from {url}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc

    raise RuntimeError(f"Release source request failed for {url}: {last_error}")


def _normalized_version(value: str) -> str | None:
    candidate = value.strip()
    if candidate.lower().startswith("v"):
        candidate = candidate[1:]
    try:
        return str(Version(candidate))
    except InvalidVersion:
        return None


def _is_newer(current: str, previous: str) -> tuple[bool, bool]:
    """Return (changed, regression_detected)."""
    if current == previous:
        return False, False
    current_normalized = _normalized_version(current)
    previous_normalized = _normalized_version(previous)
    if current_normalized is None or previous_normalized is None:
        return True, False
    current_version = Version(current_normalized)
    previous_version = Version(previous_normalized)
    return current_version > previous_version, current_version < previous_version


def _latest_pypi_release(project: str) -> dict[str, Any]:
    if not PYPI_PROJECT_RE.fullmatch(project):
        raise ValueError("PyPI project must contain only letters, numbers, dots, dashes, or underscores")
    payload = _request_json(f"https://pypi.org/pypi/{project}/json")
    releases = payload.get("releases") or {}
    candidates: list[tuple[Version, str, list[dict[str, Any]]]] = []
    for version_text, files in releases.items():
        try:
            parsed = Version(version_text)
        except InvalidVersion:
            continue
        usable_files = [item for item in (files or []) if not item.get("yanked", False)]
        if parsed.is_prerelease or parsed.is_devrelease or not usable_files:
            continue
        candidates.append((parsed, version_text, usable_files))
    if not candidates:
        raise ValueError(f"PyPI returned no stable releases for {project}")

    parsed, version_text, files = max(candidates, key=lambda item: item[0])
    timestamps = [
        item.get("upload_time_iso_8601") or item.get("upload_time")
        for item in files
        if item.get("upload_time_iso_8601") or item.get("upload_time")
    ]
    info = payload.get("info") or {}
    return {
        "version": version_text,
        "normalized_version": str(parsed),
        "release_url": f"https://pypi.org/project/{project}/{version_text}/",
        "published_at": max(timestamps) if timestamps else None,
        "summary": info.get("summary") or "",
    }


def _latest_github_release(project: str) -> dict[str, Any]:
    match = GITHUB_REPO_RE.fullmatch(project)
    if not match:
        raise ValueError("GitHub project must use the owner/repository format")
    payload = _request_json(
        f"https://api.github.com/repos/{match.group('owner')}/{match.group('repo')}/releases/latest"
    )
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise ValueError(f"GitHub returned no latest release tag for {project}")
    return {
        "version": tag,
        "normalized_version": _normalized_version(tag),
        "release_url": payload.get("html_url") or f"https://github.com/{project}/releases/latest",
        "published_at": payload.get("published_at"),
        "summary": payload.get("name") or tag,
    }


def _fetch_latest(source: str, project: str) -> dict[str, Any]:
    if source == "pypi":
        return _latest_pypi_release(project)
    if source == "github":
        return _latest_github_release(project)
    raise ValueError("source must be pypi or github")


def _state_payload(
    *, watch_id: str, source: str, project: str, release: dict[str, Any]
) -> dict[str, Any]:
    return {
        "watch_id": watch_id,
        "source": source,
        "project": project,
        "version": release["version"],
        "normalized_version": release.get("normalized_version"),
        "release_url": release.get("release_url"),
        "published_at": release.get("published_at"),
        "acknowledged_at": _now_iso(),
    }


def check_release(*, watch_id: str, source: str, project: str) -> dict[str, Any]:
    state_path = _state_path(watch_id)
    current = _fetch_latest(source, project)
    previous = _read_state(state_path)
    checked_at = _now_iso()

    if previous is None:
        _write_state(
            state_path,
            _state_payload(watch_id=watch_id, source=source, project=project, release=current),
        )
        changed = False
        initialized = True
        regression_detected = False
        previous_version = None
    else:
        if previous.get("source") != source or previous.get("project") != project:
            raise ValueError(
                f"watch_id {watch_id!r} already tracks "
                f"{previous.get('source')}:{previous.get('project')}"
            )
        changed, regression_detected = _is_newer(current["version"], str(previous["version"]))
        initialized = False
        previous_version = str(previous["version"])

    release_url = str(current.get("release_url") or "")
    title = f"New {project} release: {current['version']}"
    description = (
        f"{project} moved from {previous_version or 'an uninitialized baseline'} "
        f"to {current['version']}. Release: {release_url}"
    )
    return {
        "watch_id": watch_id,
        "source": source,
        "project": project,
        "initialized": initialized,
        "changed": changed,
        "regression_detected": regression_detected,
        "previous_version": previous_version,
        "current_version": current["version"],
        "normalized_version": current.get("normalized_version"),
        "release_url": release_url,
        "published_at": current.get("published_at"),
        "summary": current.get("summary") or "",
        "checked_at": checked_at,
        "state_path": str(state_path),
        "alert_title": title,
        "alert_description": description,
        "alert_severity": "medium",
        "alert_dedupe_key": f"release-watch:{watch_id}:{current['version']}",
    }


def acknowledge_release(
    *, watch_id: str, source: str, project: str, version: str,
    release_url: str | None = None, published_at: str | None = None,
) -> dict[str, Any]:
    version = version.strip()
    if not version:
        raise ValueError("version is required for acknowledge")
    state_path = _state_path(watch_id)
    existing = _read_state(state_path)
    if existing and (
        existing.get("source") != source or existing.get("project") != project
    ):
        raise ValueError(
            f"watch_id {watch_id!r} already tracks "
            f"{existing.get('source')}:{existing.get('project')}"
        )
    release = {
        "version": version,
        "normalized_version": _normalized_version(version),
        "release_url": release_url,
        "published_at": published_at,
    }
    _write_state(
        state_path,
        _state_payload(watch_id=watch_id, source=source, project=project, release=release),
    )
    return {
        "watch_id": watch_id,
        "source": source,
        "project": project,
        "acknowledged": True,
        "version": version,
        "state_path": str(state_path),
    }


def main() -> None:
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
        action = str(args.get("action") or "check").strip().lower()
        watch_id = str(args.get("watch_id") or "").strip()
        source = str(args.get("source") or "").strip().lower()
        project = str(args.get("project") or "").strip()
        if not watch_id or not source or not project:
            raise ValueError("watch_id, source, and project are required")

        if action == "check":
            data = check_release(watch_id=watch_id, source=source, project=project)
            if data["initialized"]:
                speech = f"Release watch initialized at {project} {data['current_version']}."
            elif data["changed"]:
                speech = data["alert_title"] + "."
            elif data["regression_detected"]:
                speech = f"Release watch kept the newer acknowledged version for {project}."
            else:
                speech = f"No new {project} release. Latest is {data['current_version']}."
        elif action == "acknowledge":
            data = acknowledge_release(
                watch_id=watch_id,
                source=source,
                project=project,
                version=str(args.get("version") or ""),
                release_url=args.get("release_url"),
                published_at=args.get("published_at"),
            )
            speech = f"Acknowledged {project} release {data['version']}."
        else:
            raise ValueError("action must be check or acknowledge")

        print(json.dumps({"ok": True, "speech": speech, "data": data}))
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error": str(exc),
            "speech": f"Release watch failed: {exc}",
        }))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
