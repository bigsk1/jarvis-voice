"""Normalize Workspace MCP receipts and preserve bounded follow-up handles.

Upstream v2.0.1 mostly returns human-readable text, not Google API objects.
Keep its actual response and explicitly labeled IDs; never invent an API receipt.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from itertools import islice
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

PREFIX = "mcp_google_workspace_"
_REQUEST_KEYS = frozenset({
    "user_google_email", "service_name", "action", "query", "title", "subject",
    "file_id", "file_name", "folder_id", "document_id", "spreadsheet_id", "presentation_id",
    "form_id", "message_id", "thread_id", "draft_id", "calendar_id", "event_id",
    "task_id", "task_list_id", "tasklist_id", "resource_name", "range_name",
    "page_token", "sheet_name", "to", "start_time", "end_time", "script_id",
    "deployment_id", "version_number", "response_id", "permission_id", "role",
    "email_address", "body_format", "time_min", "time_max", "stash", "stash_space_id", "stash_ref",
})
_LINK = re.compile(r"https?://[^\s<>\"'\[\]]+")
_HANDLE = re.compile(
    r"(?im)\b((?:File|Document|Spreadsheet|Presentation|Form|Message|Thread|Draft|"
    r"Calendar|Event|Task|Task List|Sheet|Permission)?\s*ID|resource\s*Name|next\s*Page\s*Token)"
    r"\s*[:=]\s*[`\"']?([A-Za-z0-9_@./:+=-]{1,512})(?![A-Za-z0-9_@./:+=-])"
)


def normalize_labeled_ids(text: str) -> str:
    """Strip sentence periods only from explicitly labeled IDs, not cursors."""
    return _HANDLE.sub(lambda match: match[0].rstrip(".") if match[1].lower().endswith("id") else match[0], text)


def _bounded(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        return {str(k)[:100]: _bounded(v, depth + 1) for k, v in islice(value.items(), 30)}
    if isinstance(value, list):
        return [_bounded(v, depth + 1) for v in value[:20]]
    if isinstance(value, str):
        return normalize_labeled_ids(value)[:2000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:200]


_PROVIDER_HOSTS = frozenset({
    "docs.google.com", "drive.google.com", "calendar.google.com", "mail.google.com",
    "script.google.com", "forms.google.com", "contacts.google.com", "tasks.google.com",
    "console.cloud.google.com", "console.developers.google.com",
})
# Only these pinned tools return creation receipts without document/message bodies.
# Unknown and future readers default to untrusted, even for Google-hosted URLs.
_RECEIPT_LINK_TOOLS = frozenset({
    "create_doc", "create_spreadsheet", "create_presentation", "create_form", "create_drive_file",
    "create_drive_folder",
})


def workspace_links(text: str, *, content_links_untrusted: bool = True, auth_required: bool = False) -> list[dict[str, str]]:
    links = []
    seen = set()
    for match in _LINK.finditer(text):
        url = match[0].rstrip(".,;)")
        try:
            parsed = urlsplit(url)
            if parsed.username or parsed.password or parsed.scheme not in {"http", "https"}:
                continue
        except ValueError:
            continue
        if parsed.hostname == "accounts.google.com":
            if not auth_required:
                continue
        elif content_links_untrusted or parsed.hostname not in _PROVIDER_HOSTS:
            continue
        if parsed.scheme != "https":
            continue
        # A complete-tier Google consent URL contains many encoded scopes and
        # routinely exceeds 2K. Preserve it intact; ordinary result links stay small.
        url_limit = 16384 if parsed.scheme == "https" and parsed.hostname == "accounts.google.com" else 2048
        if len(url) > url_limit or url in seen:
            continue
        seen.add(url)
        links.append({"url": url, "title": parsed.hostname or "Google result"})
        if len(links) == 20:
            break
    return links


def normalize_workspace_result(tool_name: str, result: dict, arguments: dict | None = None) -> dict:
    content = result.get("content") or []
    text = "\n".join(
        item["text"] for item in content
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    )
    structured = result.get("structuredContent")
    if not text and structured is not None:
        text = json.dumps(structured, ensure_ascii=False, default=str)
    text = normalize_labeled_ids(text)
    if isinstance(structured, str):
        structured = normalize_labeled_ids(structured)
    head = text.lstrip()
    auth_required = (tool_name == "start_google_auth" and "accounts.google.com/" in text) or head.startswith(
        ("Authentication required", "**Authentication Required", "**Authentication Error:",
         "**ACTION REQUIRED: Google Authentication", "**ACTION REQUIRED: Google sign-in")
    )
    failed = not text or bool(result.get("isError")) or auth_required or head.startswith(("Error:", "**Error:**"))
    data: dict[str, Any] = {
        "source": "google_workspace", "tool": tool_name,
        "request": {key: value for key, value in (arguments or {}).items()
                    if key in _REQUEST_KEYS and isinstance(value, (str, int, bool))
                    and len(str(value)) <= 1000},
        "response_text": text[:16000], "response_truncated": len(text) > 16000,
        "links": workspace_links(text, content_links_untrusted=tool_name not in _RECEIPT_LINK_TOOLS, auth_required=auth_required),
        "content_links_untrusted": tool_name not in _RECEIPT_LINK_TOOLS,
        "references": [{"label": m[1].strip(), "id": m[2].rstrip(".") if m[1].lower().endswith("id") else m[2]}
                       for m in islice(_HANDLE.finditer(text), 30)],
        "external_content_trust": "untrusted",
    }
    if structured is not None:
        compact = _bounded(structured)
        if len(json.dumps(compact, default=str)) <= 12000:
            data["structured_result"] = compact
    data["ok"] = not failed
    if auth_required:
        data["authentication_required"] = True
    if failed:
        disabled_api = re.search(
            r"https://console\.cloud\.google\.com/flows/enableapi\?apiid=([a-z0-9.-]+\.googleapis\.com)", text,
        )
        project = re.search(r"not enabled for your project \(([0-9]+)\)", text)
        if not (disabled_api and project):
            disabled_api = re.search(
                r"https://console\.(?:developers|cloud)\.google\.com/apis/api/([a-z0-9.-]+\.googleapis\.com)/overview", text,
            )
            project = re.search(r"not been used in project ([0-9]+) before or it is disabled", text)
        if disabled_api and project:
            data["configuration_required"] = {
                "reason": "api_disabled", "api_id": disabled_api[1],
                "project_number": project[1],
            }
    normalized = {"ok": not failed, "speech": text[:500] or "Google Workspace returned an empty response", "data": data}
    if failed:
        normalized["error"] = text[:16000] or "Google Workspace request failed"
    return normalized


def _stash_browser_download(artifact: dict) -> str | None:
    """Build a same-origin browser link from a complete saved Stash handle."""
    space_id, file_id, mode = (artifact.get(key) for key in ("space_id", "file_id", "mode"))
    if (isinstance(space_id, str) and re.fullmatch(r"space_[A-Za-z0-9_-]{1,100}", space_id)
            and isinstance(file_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,150}", file_id)
            and isinstance(mode, str) and mode in {"cloud", "local"}):
        return f"/api/stash/{space_id}/{file_id}?mode={mode}"
    return None


def _workspace_display_text(text: str, download_url: str | None) -> str:
    """Replace private cache URLs only when a usable Stash copy exists."""
    if not download_url:
        return text
    def replace_link(match):
        try:
            if re.fullmatch(r"/attachments/" + _UUID, urlsplit(match[0].rstrip(".,;)")).path):
                return download_url
        except ValueError:
            pass
        return match[0]
    text = _LINK.sub(replace_link, text)
    return re.sub(r"(?im)^The file will expire after [^\n]+$",
                  "The Google attachment cache is temporary; use the Stash copy for follow-ups.", text)


def project_workspace_data(result: dict, *, max_chars: int = 4500) -> dict:
    """Pure replay projection with a hard serialized bound and honest trimming."""
    max_chars = max(2, int(max_chars))
    payload = result.get("data", result)
    if not isinstance(payload, dict):
        return {}
    projected = {key: _bounded(payload[key]) for key in (
        "source", "tool", "ok", "authentication_required", "configuration_required", "request", "references",
        "links", "artifacts", "stash_error", "google_ok", "response_truncated", "external_content_trust",
        "content_links_untrusted",
    ) if key in payload}
    projected = deepcopy(projected)
    trimmed = any(projected[key] != payload[key] for key in projected)
    artifacts = projected.get("artifacts") or []
    download_url = None
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        browser_url = _stash_browser_download(artifact)
        if browser_url:
            artifact["download_url"] = browser_url
            download_url = download_url or browser_url
    original_text = str(payload.get("response_text") or result.get("error") or result.get("speech") or "")
    text = _workspace_display_text(original_text, download_url)
    projected["response_excerpt"] = text[:2200]
    trimmed = trimmed or len(text) > 2200
    structured = payload.get("structured_result")
    echo = structured.get("result") if isinstance(structured, dict) and set(structured) == {"result"} else structured if isinstance(structured, str) else None
    # FastMCP echoes the same text in structuredContent. Removing that copy
    # omits no evidence and must not imply that a complete receipt was truncated.
    if structured is not None and not (isinstance(echo, str) and echo and original_text.startswith(echo)):
        compact = _bounded(structured)
        trimmed = trimmed or compact != structured
        def display(value):
            if isinstance(value, str):
                return _workspace_display_text(value, download_url)
            if isinstance(value, dict):
                return {key: display(child) for key, child in value.items()}
            if isinstance(value, list):
                return [display(child) for child in value]
            return value
        projected["structured_result"] = display(compact)
    projected["context_truncated"] = False
    def size():
        return len(json.dumps(projected, ensure_ascii=True, default=str))
    if size() > max_chars and "structured_result" in projected:
        projected.pop("structured_result")
        trimmed = True
    if size() > max_chars and projected.get("response_excerpt"):
        projected["response_excerpt"] = ""
        trimmed = True
    for key in ("links", "references", "artifacts"):
        while size() > max_chars and projected.get(key):
            projected[key].pop()
            trimmed = True
    while size() > max_chars and projected.get("request"):
        projected["request"].popitem()
        trimmed = True
    # Small parent budgets and unusually large diagnostic fields must not
    # escape the bound after collections have been reduced.
    for key in ("stash_error", "configuration_required", "response_excerpt", "links", "references", "artifacts",
                "request", "external_content_trust", "tool", "source", "content_links_untrusted",
                "response_truncated", "authentication_required", "google_ok", "ok"):
        if size() <= max_chars:
            break
        if key in projected:
            projected.pop(key)
            trimmed = True
    projected["context_truncated"] = trimmed
    return projected if size() <= max_chars else {}


# These tools produce authenticated, temporary /attachments/{UUID} downloads.
_DOWNLOAD_TOOLS = frozenset({
    "get_drive_file_download_url", "get_gmail_attachment_content", "get_gmail_message_content",
})
_MAX_BRIDGE_BYTES = 50 * 1024 * 1024
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def extend_workspace_schema(tool_name: str, parameters: dict, description: str) -> str:
    """Add Jarvis-only options; the upstream schema stays unchanged."""
    props = parameters.setdefault("properties", {})
    hints = []
    if tool_name == "get_gmail_message_content" and "message_id" in props:
        props["message_id"]["description"] = (
            "Gmail Message ID from search_gmail_messages. A Draft ID (r123456789) is not a Message ID; "
            "resolve drafts with a Gmail search using in:drafts and the known subject first."
        )
    if tool_name in {"send_gmail_message", "draft_gmail_message"} and "attachments" in props:
        props["attachments"]["description"] = (
            'Optional attachments using "url" (public HTTP(S) or a Google service attachment URL), '
            'or "content" (standard base64) plus "filename". Optional "mime_type" and "content_id" '
            '(for inline HTML images). Container "path" inputs are not accepted.'
        )
    if tool_name in _DOWNLOAD_TOOLS:
        props["stash"] = {"type": "boolean", "default": False, "description":
            "Copy the downloaded/exported file into Jarvis Stash for follow-up tools. Default false."}
        props["stash_space_id"] = {"type": "string", "description":
            "Optional existing Stash space to reuse when stash=true."}
        hints.append("Set stash=true only when a persistent file or downstream file manipulation is needed; "
                     "returns a stash:// reference and Web download link (50 MiB maximum).")
    if "file_path" in props or tool_name == "create_drive_file" and "fileUrl" in props:
        props["stash_ref"] = {"type": "string", "description":
            "Optional stash://space_id/file_id to upload/import instead of a container file_path. "
            "Jarvis stages only that file in the Google attachment cache."}
        for key in ("fileUrl", "file_url"):
            if key in props:
                props[key]["description"] = "Public HTTP(S) source URL. Use stash_ref for a Jarvis-local file; file:// container paths are not accepted."
        props.pop("file_path", None)
        parameters["required"] = [key for key in parameters.get("required", []) if key != "file_path"]
        hints.append("For a file already in Jarvis Stash, use stash_ref. Public URLs and inline content remain supported; do not guess container paths.")
    return (" ".join(hints) + "\n\n" + description) if hints else description


def _service_url(client, path: str) -> str:
    origin = urlsplit(client.url)
    if origin.scheme not in {"http", "https"} or origin.username or origin.password:
        raise ValueError("Invalid Google service URL")
    return urlunsplit((origin.scheme, origin.netloc, path, "", ""))


def prepare_workspace_transfer(client, tool_name: str, arguments: dict):
    """Resolve an explicit Stash upload without mounting host directories."""
    from pathlib import Path

    from mcp_client import _check_remote_call_budget
    from stash_helper import safe_resolve_file

    upstream = dict(arguments)
    if tool_name == "get_gmail_message_content" and re.fullmatch(r"r-?\d+", str(upstream.get("message_id", ""))):
        raise ValueError("message_id is a Draft ID. Search Gmail with in:drafts and the known subject, then read the returned Message ID with get_gmail_message_content")
    if "file_path" in upstream:
        raise ValueError("Use stash_ref for a Jarvis file; container paths are supplied only by staging")
    for key in ("fileUrl", "file_url"):
        value = upstream.get(key)
        if value is not None:
            if not isinstance(value, str) or urlsplit(value).scheme not in {"http", "https"} or not urlsplit(value).hostname:
                raise ValueError("File source must be an HTTP(S) URL; use stash_ref for a Jarvis file")
    if any(isinstance(item, dict) and "path" in item for item in upstream.get("attachments") or []):
        raise ValueError("Attachment paths are not accepted; use an attachment URL or base64 content")
    stash = upstream.pop("stash", False)
    if stash is None:
        stash = False  # Strict provider schemas may use null for omitted options.
    space_id = upstream.pop("stash_space_id", None)
    stash_ref = upstream.pop("stash_ref", None)
    if not isinstance(stash, bool):
        raise ValueError("stash must be a boolean")
    if stash and tool_name not in _DOWNLOAD_TOOLS:
        raise ValueError("This Google tool does not produce a Stash download")
    if space_id is not None and (not isinstance(space_id, str) or not re.fullmatch(r"space_[A-Za-z0-9_-]{1,100}", space_id)):
        raise ValueError("Invalid stash_space_id")
    if space_id and not stash:
        raise ValueError("stash_space_id requires stash=true")
    if stash and tool_name == "get_gmail_message_content":
        upstream["full"] = True
    if not stash_ref:
        return upstream, stash, space_id, None
    tool = next((t for t in (client._tools_cache or []) if t.get("name") == tool_name), {})
    properties = (tool.get("inputSchema", {}).get("properties", {}) if tool
                  else getattr(client, "_tool_properties", {}).get(tool_name, set()))
    upload_parameter = "file_path" if "file_path" in properties else "fileUrl" if tool_name == "create_drive_file" and "fileUrl" in properties else None
    if upload_parameter is None:
        raise ValueError("This Google tool does not accept a Stash file upload")
    if any(upstream.get(key) for key in ("file_path", "file_url", "fileUrl", "content", "base64_content")):
        raise ValueError("Use stash_ref or another file source, not both")
    if not isinstance(stash_ref, str) or not re.fullmatch(r"stash://space_[A-Za-z0-9_-]{1,100}/[A-Za-z0-9_-]{1,150}", stash_ref):
        raise ValueError("Invalid stash_ref")
    resolved = safe_resolve_file(stash_ref=stash_ref)
    if not resolved["found"]:
        raise ValueError(resolved.get("error") or "Stash file unavailable")
    path = Path(resolved["path"])
    if path.stat().st_size > _MAX_BRIDGE_BYTES:
        raise ValueError("Stash upload exceeds 50 MiB")
    _check_remote_call_budget()
    with path.open("rb") as stream:
        response = client._http_request("POST", _service_url(client, "/jarvis/stage"),
            headers={**client.headers, "X-Jarvis-Filename": quote(path.name, safe=""),
                     "Content-Type": "application/octet-stream"}, data=stream,
            allow_redirects=False, timeout=30)
    try:
        if response.status_code != 201:
            raise ValueError("Google attachment staging failed")
        receipt = response.json()
        staged_id = receipt.get("id", "")
        if not re.fullmatch(_UUID, staged_id):
            raise ValueError("Invalid Google staging receipt")
        # The service owns this exact managed path; the model never chooses it.
        stage_path = receipt.get("path", "")
        if not isinstance(stage_path, str) or not stage_path.startswith("/app/store_creds/attachments/") or ".." in stage_path:
            raise ValueError("Invalid Google staging path")
        upstream[upload_parameter] = "file://" + stage_path if upload_parameter == "fileUrl" else stage_path
        return upstream, stash, space_id, staged_id
    finally:
        response.close()


def cleanup_workspace_transfer(client, staged_id):
    if not staged_id:
        return
    # Cleanup uses at most two seconds within the remaining call budget. No Google API
    # action is retried here; crashed clients leave only the expiring cache copy.
    import time

    from mcp_client import _remote_call_budget, _RemoteCallBudget
    parent = _remote_call_budget.get()
    cleanup_budget = _RemoteCallBudget(min(time.monotonic() + 2, parent.deadline) if parent else time.monotonic() + 2)
    if parent:
        cleanup_budget.cancelled = parent.cancelled
    token = _remote_call_budget.set(cleanup_budget)
    try:
        response = client._http_request("DELETE", _service_url(client, f"/jarvis/stage/{staged_id}"),
            headers=client.headers, allow_redirects=False, timeout=2)
        response.close()
    except Exception:
        pass  # The upstream attachment sweeper also removes expired staging.
    finally:
        _remote_call_budget.reset(token)


def stash_workspace_download(client, result: dict, space_id=None) -> dict:
    """Copy one explicit download through the canonical Stash helper."""
    import hashlib
    from email.message import Message
    from pathlib import Path

    from mcp_client import _check_remote_call_budget
    from stash_helper import StashFile, open_space, sanitize_filename

    if not result.get("ok"):
        return result
    data = result["data"]
    try:
        # Only the labeled download in known file-producing tools is eligible.
        # Ignore its advertised hostname: Docker and native have different
        # origins. Bearer credentials go exclusively to the configured service.
        match = re.search(r"Download URL:\s*(https?://[^\s<>]+)", data.get("response_text", ""))
        if not match:
            raise ValueError("Google did not return a downloadable attachment")
        parsed = urlsplit(match[1].rstrip(".,;)"))
        if parsed.query or parsed.fragment or not re.fullmatch(r"/attachments/" + _UUID, parsed.path):
            raise ValueError("Invalid Google attachment download path")
        response = client._http_request("GET", _service_url(client, parsed.path),
            headers=client.headers, allow_redirects=False, timeout=30, stream=True)
        try:
            if response.status_code != 200:
                raise ValueError("Google attachment is unavailable or expired")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > _MAX_BRIDGE_BYTES:
                raise ValueError("Google attachment exceeds 50 MiB")
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                _check_remote_call_budget()
                if len(body) + len(chunk) > _MAX_BRIDGE_BYTES:
                    raise ValueError("Google attachment exceeds 50 MiB")
                body.extend(chunk)
            _check_remote_call_budget()
            disposition = Message()
            disposition["content-disposition"] = response.headers.get("Content-Disposition", "")
            name = sanitize_filename(disposition.get_filename() or "google_attachment")
            mime = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
        finally:
            response.close()
        import time
        budget = _check_remote_call_budget()
        lock_timeout = min(5, max(0, budget.deadline - time.monotonic())) if budget else 5
        space, _ = open_space(space_id=space_id, labels=["google_workspace"], scope="project", lock_timeout=lock_timeout)
        with space.transaction(timeout=lock_timeout):
            _check_remote_call_budget()
            digest = hashlib.sha256(body).hexdigest()
            saved = None
            for item in space.meta.get("files", []):
                if item.get("hash_sha256") == digest and item.get("mime_type") == mime:
                    entry = StashFile(space, file_id=item["file_id"])
                    if entry.path and Path(entry.path).is_file():
                        saved = {**item, "ref": f"stash://{space.space_id}/{item['file_id']}"}
                        break
            if saved is None:
                saved = StashFile(space).save_binary(bytes(body), name=name, mime_type=mime,
                    on_conflict="version", tags=["google_workspace"], tool_origin=PREFIX + data["tool"])
        artifact = {key: saved[key] for key in ("ref", "file_id", "name", "mime_type", "size_bytes")}
        artifact["space_id"] = space.space_id
        from config_loader import get_active_config_mode
        artifact["mode"] = get_active_config_mode()
        artifact["download_url"] = f"/api/stash/{space.space_id}/{saved['file_id']}?mode={artifact['mode']}"
        data["artifacts"] = [artifact]
        # The authenticated temporary link is not a usable browser download.
        data["links"] = [link for link in data.get("links", []) if urlsplit(link["url"]).path != parsed.path]
        data["response_text"] += f"\nStashed file: {artifact['ref']}"
        result["speech"] = "Google file downloaded and saved to Jarvis Stash."
    except Exception as exc:
        data["google_ok"] = True
        data["stash_error"] = str(exc)
        data["ok"] = result["ok"] = False
        result["error"] = f"Google download succeeded, but Stash transfer failed: {exc}"
        result["speech"] = result["error"]
    return result
