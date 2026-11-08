"""Normalize Workspace MCP receipts and preserve bounded follow-up handles.

Upstream v2.3.0 returns human-readable receipts, paged content and inline images.
Keep its actual response and explicitly labeled IDs; never invent an API receipt.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from itertools import islice
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from email_contacts import load_contacts, resolve_email_recipients

PREFIX = "mcp_google_workspace_"
_REQUEST_KEYS = frozenset({
    "user_google_email", "service_name", "action", "query", "title", "subject",
    "file_id", "file_name", "folder_id", "document_id", "spreadsheet_id", "presentation_id",
    "form_id", "message_id", "thread_id", "draft_id", "calendar_id", "event_id",
    "task_id", "task_list_id", "tasklist_id", "resource_name", "range_name",
    "page_token", "full", "attachment_id", "attachment_index", "sheet_name", "to", "start_time", "end_time", "script_id",
    "deployment_id", "version_number", "response_id", "permission_id", "role",
    "email_address", "body_format", "time_min", "time_max", "stash", "stash_space_id", "stash_ref",
    "tab_id", "replace_existing", "copy_comments", "request_sync_token", "sync_token",
    "page_object_id", "size", "heading", "heading_level", "include_colors", "color_id", "reply_all",
    "include_headers", "include_links", "this_and_following", "comment_id", "recurrence",
    "offset", "full_content", "page_offset", "page_size", "expected_sha256",
})
_REQUEST_ID_LISTS = frozenset({"message_ids", "thread_ids", "add_label_ids", "remove_label_ids", "recurrence"})
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


def _workspace_request(arguments: dict) -> tuple[dict, dict, dict]:
    """Keep explicit follow-up handles, with separate original counts and omissions."""
    request = {key: value for key, value in arguments.items()
               if key in _REQUEST_KEYS and isinstance(value, (str, int, bool))
               and len(str(value)) <= 1000}
    counts, truncated = {}, {}
    remaining = 3000
    for key in sorted(_REQUEST_ID_LISTS):
        values = arguments.get(key)
        if not isinstance(values, list):
            continue
        counts[key] = len(values)
        shown = []
        for value in islice(values, 20):
            if not isinstance(value, str) or not 0 < len(value) <= 512:
                continue
            cost = len(json.dumps(value, ensure_ascii=True)) + 2
            if len(shown) == 20 or cost > remaining:
                break
            shown.append(value)
            remaining -= cost
        request[key] = shown
        truncated[key] = len(shown) != len(values)
    return request, counts, truncated


def _gmail_label_outcomes(text: str, arguments: dict) -> tuple[dict, bool]:
    """Parse only the pinned batch-label receipt, never ordinary email content.

    Counts are verified outcomes reported by upstream, not inferred successes or
    a reason to replay writes. Detail excerpts retain upstream's own ID limits.
    """
    reports = {}
    complete = True
    headers = list(re.finditer(r"(?m)^Label changes for (\d{1,9}) (message|thread) ID\(s\):[^\n]*\nApplied: (\d{1,9})/(\d{1,9})$", text))
    for index, match in enumerate(headers):
        total, kind, applied, denominator = int(match[1]), match[2], int(match[3]), int(match[4])
        section = text[match.end():headers[index + 1].start() if index + 1 < len(headers) else len(text)]
        categories = {}
        for detail in re.finditer(r"(?m)^(No such message|No such thread|Unchanged|Could not verify|Failed) \((\d{1,9})\): ([^\n]*)$", section):
            label = detail[1]
            if label in categories:
                complete = False
            categories[label] = {"count": int(detail[2]), "details": detail[3][:1000],
                                 "details_truncated": len(detail[3]) > 1000 or "… (+" in detail[3]}
        valid = (kind not in reports and total > 0 and denominator == total and 0 <= applied <= total
                 and applied + sum(value["count"] for value in categories.values()) == total)
        reports[kind] = {"total": total, "applied": applied, "outcomes": categories, "valid": valid}
        complete = complete and valid and applied == total and not categories
    # Unverified and malformed receipts cannot establish a completed write.
    complete = (complete and bool(reports) and "NOT VERIFIED:" not in text
                and len(headers) == len(re.findall(r"(?m)^Label changes for ", text))
                and len(headers) == len(re.findall(r"(?m)^Applied:", text)))
    for kind in ("message", "thread"):
        requested = arguments.get(kind + "_ids")
        if isinstance(requested, list) and requested:
            complete = complete and reports.get(kind, {}).get("total") == len(requested)
    return reports, complete


def _split_series_id(tool_name: str, text: str, arguments: dict) -> str | None:
    """Read only the pinned Calendar split receipt, never a reader's body text."""
    if (tool_name != "manage_event" or arguments.get("action") != "update"
            or arguments.get("this_and_following") is not True):
        return None
    match = re.match(
        r"\ASuccessfully modified '[^\r\n]*' from instance ([A-Za-z0-9_-]{1,512}) "
        r"onward for [^\s]+\. Earlier instances keep the original series; this and "
        r"following instances are now series ID ([A-Za-z0-9_-]{1,512})\. Link: ", text,
    )
    if match and match[1] == arguments.get("event_id"):
        return match[2]
    return None


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


def gmail_attachment_metadata(text: str, message_id: str) -> list[dict]:
    """Read the pinned server's attachment footer, separately from truncated body.

    These remain untrusted descriptors. The inbox checks downloaded bytes against
    its authenticated raw MIME before making them available to a request.
    """
    if "\n--- ATTACHMENTS ---" not in text:
        return []
    footer = text.rsplit("\n--- ATTACHMENTS ---", 1)[1]
    pattern = re.compile(
        r"(?m)^(\d+)\. (.+) \(([^,\s]+), [\d.]+ KB\)(?: \[in attached message\])?\r?\n"
        r"[ \t]+Attachment ID: ([A-Za-z0-9_+=/-]{1,4096})\r?\n"
        r"[ \t]+Use get_gmail_attachment_content\(message_id='([a-f0-9]+)', "
        r"attachment_id='([A-Za-z0-9_+=/-]{1,4096})', attachment_index=(\d+)\) to download"
    )
    return [{"name": match[2], "mime_type": match[3], "attachment_id": match[4],
             "attachment_index": int(match[7])}
            for match in islice(pattern.finditer(footer), 500)
            if match[5] == message_id and match[4] == match[6] and int(match[1]) == int(match[7]) + 1]


_DRIVE_CONTENT_HEADER = re.compile(
    r'\AFile: "[^\r\n]*" \(ID: ([A-Za-z0-9_-]{1,512}), Type: ([A-Za-z0-9.+/-]+), Version: (\d{1,30})\)\n'
    r"Link: [^\r\n]*\n\n--- CONTENT ---\n"
)
_DRIVE_PAGE_FOOTER = re.compile(
    r"\n\n\[Truncated: showing characters ([0-9,]{1,30}) to ([0-9,]{1,30}) of ([0-9,]{1,30}); "
    r"([0-9,]{1,30}) more follow \(default page size ([0-9,]{1,30}), set by WORKSPACE_MCP_MAX_CONTENT_CHARS\)\. "
    r"Call again with offset=([0-9]{1,19}) to read on, or pass full_content=True for the whole file\.\]\Z"
)
_GMAIL_PAGE_KEYS = frozenset({
    "message_id", "body_format", "body", "page_offset", "next_offset", "total_chars",
    "complete", "body_sha256", "scope",
})


def _page_integer(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 2**63 - 1


def _workspace_content_page(tool_name: str, text: str, arguments: dict) -> tuple[dict, str] | None:
    """Read only pinned, request-matched envelopes; body text is never authority.

    The plain Drive footer is a continuation hint, not authenticated content.
    Check its arithmetic against the actual returned body rather than accepting
    arbitrary offsets embedded in a document. Local delivery determines the
    next cursor in both formats, independently of the upstream continuation.
    """
    if tool_name == "get_gmail_message_content":
        offset, size = arguments.get("page_offset"), arguments.get("page_size", 20000)
        if (not _page_integer(offset) or not _page_integer(size) or not 1 <= size <= 20000
                or arguments.get("full", False) is not False or arguments.get("format", "full") != "full"
                or arguments.get("body_format", "text") not in {"text", "html"}):
            return None
        try:
            page = json.loads(text)
        except (ValueError, RecursionError):
            return None
        if not isinstance(page, dict) or not _GMAIL_PAGE_KEYS <= page.keys() or page.keys() - _GMAIL_PAGE_KEYS - {"headers"}:
            return None
        if arguments.get("include_headers", True):
            if (not isinstance(page.get("headers"), dict)
                    or not all(isinstance(key, str) and isinstance(value, str) for key, value in page["headers"].items())):
                return None
        elif "headers" in page:
            return None
        body, total, following = page["body"], page["total_chars"], page["next_offset"]
        digest = page["body_sha256"]
        if (not isinstance(body, str) or len(body) > size or not _page_integer(page["page_offset"])
                or page["page_offset"] != offset or not _page_integer(total)
                or page["message_id"] != arguments.get("message_id")
                or page["body_format"] != arguments.get("body_format", "text")
                or type(page["complete"]) is not bool
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or page["scope"] != "Decoded outer message body, excluding attachments and attached messages."
                or (arguments.get("expected_sha256") is not None and arguments["expected_sha256"] != digest)):
            return None
        end = offset + len(body)
        if (end > total or page["complete"] != (end == total)
                or (following is not None and not _page_integer(following))
                or following != (end if end < total else None)
                or (not body and end < total)):
            return None
        return {"kind": "gmail", "offset": offset, "page_end": end, "total_chars": total,
                "upstream_next_offset": following, "page_complete": page["complete"],
                "body_sha256": digest}, body
    if tool_name != "get_drive_file_content":
        return None
    offset = arguments.get("offset", 0)
    header = _DRIVE_CONTENT_HEADER.match(text)
    if (not _page_integer(offset) or not header or header[1] != arguments.get("file_id")
            or header[2] in {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/tiff"}):
        return None
    body = text[header.end():]
    if re.fullmatch(r"\[offset=[0-9,]+ is past the end of the content \([0-9,]+ characters\)\.\]", body):
        return None
    footer = _DRIVE_PAGE_FOOTER.search(body)
    end, total, following = offset + len(body), offset + len(body), None
    if footer:
        if arguments.get("full_content", False) is not False:
            return None
        numbers = [int(value.replace(",", "") or "-1") for value in footer.groups()[:5]]
        if any(not _page_integer(number) or value != f"{number:,}"
               for value, number in zip(footer.groups()[:5], numbers, strict=True)):
            return None
        start, end, total, remaining, size = numbers
        page_body = body[:footer.start()]
        if (start != offset or end != offset + len(page_body) or not end < total
                or remaining != total - end or size < len(page_body) or size < 1
                or len(page_body) < size / 2 or int(footer[6]) != end):
            return None
        body, following = page_body, end
    elif "[Truncated:" in body:
        return None
    return {"kind": "drive", "offset": offset, "page_end": end, "total_chars": total,
            "upstream_next_offset": following, "page_complete": following is None,
            "file_version": header[3]}, body


def _page_delivery(page: dict, text: str) -> dict:
    """Keep upstream completion distinct from text actually delivered locally."""
    delivered_end = page["offset"] + len(text)
    return {**page, "delivered_end": delivered_end,
            "content_delivered": delivered_end == page["page_end"],
            "next_offset": delivered_end if delivered_end < page["total_chars"] else None}


def normalize_workspace_result(tool_name: str, result: dict, arguments: dict | None = None) -> dict:
    from google_workspace_images import image_delivery, without_image_bytes

    content = result.get("content") or []
    image_count = sum(isinstance(item, dict) and item.get("type") == "image" for item in content)
    text = "\n".join(
        item["text"] for item in content
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    )
    structured = without_image_bytes(result.get("structuredContent"))
    if not text and structured is not None:
        text = json.dumps(structured, ensure_ascii=False, default=str)
    # Character cursors refer to exact provider body text. Parse before labeled
    # ID cleanup, which intentionally rewrites human-readable legacy receipts.
    content_page = _workspace_content_page(tool_name, text, arguments or {}) if not result.get("isError") else None
    if content_page and without_image_bytes(content_page[1]) != content_page[1]:
        # Never restore image bytes through page_body. A transformed body no
        # longer has exact provider character positions, so omit its cursors.
        content_page = None
    text = without_image_bytes(text)
    text = normalize_labeled_ids(text)
    if isinstance(structured, str):
        structured = normalize_labeled_ids(structured)
    head = text.lstrip()
    auth_required = (tool_name == "start_google_auth" and "accounts.google.com/" in text) or head.startswith(
        ("Authentication required", "**Authentication Required", "**Authentication Error:",
         "**ACTION REQUIRED: Google Authentication", "**ACTION REQUIRED: Google sign-in")
    )
    failed = not text or bool(result.get("isError")) or auth_required or head.startswith(("Error:", "**Error:**"))
    batch_outcomes = None
    if tool_name == "batch_modify_gmail_message_labels":
        batch_outcomes, batch_complete = _gmail_label_outcomes(text, arguments or {})
        failed = failed or not batch_complete
    request, request_counts, request_truncated = _workspace_request(arguments or {})
    data: dict[str, Any] = {
        "source": "google_workspace", "tool": tool_name,
        "request": request,
        "response_text": text[:16000], "response_truncated": len(text) > 16000,
        "links": workspace_links(text, content_links_untrusted=tool_name not in _RECEIPT_LINK_TOOLS, auth_required=auth_required),
        "content_links_untrusted": tool_name not in _RECEIPT_LINK_TOOLS,
        "references": [{"label": m[1].strip(), "id": m[2].rstrip(".") if m[1].lower().endswith("id") else m[2]}
                       for m in islice(_HANDLE.finditer(text), 30)],
        "external_content_trust": "untrusted",
    }
    if request_counts:
        data["request_list_counts"] = request_counts
        data["request_lists_truncated"] = request_truncated
    if content_page and not failed:
        page, body = content_page
        data["page_body"] = body[:16000]
        data["pagination"] = _page_delivery(page, data["page_body"])
    if image_count:
        data["image_delivery"] = image_delivery(image_count, 0, ["Inline images have not been saved locally"])
    # This cursor follows the full contact listing, often beyond both text and
    # reference limits. Only an explicitly requested sync's final footer is
    # control metadata; contact bodies can contain matching lines themselves.
    sync_token = (arguments or {}).get("sync_token")
    sync_requested = ((arguments or {}).get("request_sync_token") is True
                      or isinstance(sync_token, str) and bool(sync_token.strip()))
    next_sync = (re.search(r"(?im)^Next sync token:[ \t]*([^\s]+)[ \t\r\n]*\Z", text)
                 if tool_name == "list_contacts" and not failed and sync_requested else None)
    if next_sync:
        if len(next_sync[1]) <= 1000:
            data["next_sync_token"] = next_sync[1]
        else:
            data["next_sync_token_unavailable"] = "Google sync token exceeds the 1000-character replay limit"
    if batch_outcomes is not None:
        data["batch_outcomes"] = batch_outcomes
    new_series_id = _split_series_id(tool_name, text, arguments or {}) if not failed else None
    if new_series_id:
        data["new_series_id"] = new_series_id
    if tool_name == "get_gmail_message_content" and (arguments or {}).get("body_format", "text") == "text":
        data["gmail_attachments"] = gmail_attachment_metadata(text, (arguments or {}).get("message_id", ""))
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
        if batch_outcomes is not None and not result.get("isError") and not auth_required:
            summary = "Google label changes were not fully confirmed; inspect the receipt before any further action."
            normalized["speech"] = summary
            normalized["error"] = summary + "\n" + text[:16000]
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
        "content_links_untrusted", "batch_outcomes", "google_export_ok", "download_ok", "download_error",
        "request_list_counts", "request_lists_truncated", "image_delivery", "next_sync_token", "next_sync_token_unavailable",
        "new_series_id", "pagination",
    ) if key in payload}
    projected = deepcopy(projected)
    trimmed = any(projected[key] != payload[key] for key in projected)
    # Revalidate old persisted requests too; generic list clipping loses original
    # counts and cannot distinguish a complete list from its first 20 entries.
    if isinstance(payload.get("request"), dict):
        request, counts, omitted = _workspace_request(payload["request"])
        trimmed = trimmed or request != payload["request"]
        projected["request"] = request
        if counts:
            previous_counts = payload.get("request_list_counts", {})
            previous_omitted = payload.get("request_lists_truncated", {})
            for key in counts:
                old_count = previous_counts.get(key) if isinstance(previous_counts, dict) else None
                if isinstance(old_count, int) and not isinstance(old_count, bool) and old_count > counts[key]:
                    counts[key] = old_count
                    omitted[key] = True
                if isinstance(previous_omitted, dict):
                    omitted[key] = omitted[key] or bool(previous_omitted.get(key))
            projected["request_list_counts"] = counts
            projected["request_lists_truncated"] = omitted
            trimmed = trimmed or any(omitted.values())
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
    page_body = payload.get("page_body")
    page = projected.get("pagination")
    if (not isinstance(page, dict) or not isinstance(page_body, str)
            or not all(_page_integer(page.get(key)) for key in ("offset", "page_end", "total_chars"))
            or not page["offset"] <= page["page_end"] <= page["total_chars"]
            or len(page_body) > page["page_end"] - page["offset"]):
        projected.pop("pagination", None)
        page = None
    if payload.get("tool") == "batch_modify_gmail_message_labels" and "batch_outcomes" not in payload:
        saved_request = payload.get("request")
        outcomes, complete = _gmail_label_outcomes(original_text, saved_request if isinstance(saved_request, dict) else {})
        projected["batch_outcomes"] = _bounded(outcomes)
        # Old saved receipts predate outcome normalization. Downgrade an
        # unconfirmed receipt, but never upgrade a persisted tool failure.
        projected["ok"] = bool(payload.get("ok", result.get("ok", True))) and complete
    text = page_body if page is not None else _workspace_display_text(original_text, download_url)
    projected["response_excerpt"] = text[:2200]
    trimmed = trimmed or len(text) > 2200
    if page is not None:
        projected["pagination"] = _page_delivery(page, projected["response_excerpt"])
        trimmed = trimmed or not projected["pagination"]["content_delivered"]
    structured = payload.get("structured_result")
    echo = structured.get("result") if isinstance(structured, dict) and set(structured) == {"result"} else structured if isinstance(structured, str) else None
    # FastMCP echoes the same text in structuredContent. Removing that copy
    # omits no evidence and must not imply that a complete receipt was truncated.
    if page is None and structured is not None and not (isinstance(echo, str) and echo and original_text.startswith(echo)):
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
        if page is not None:
            excerpt = projected["response_excerpt"]
            low, high = 0, len(excerpt)
            while low < high:
                middle = (low + high + 1) // 2
                projected["response_excerpt"] = excerpt[:middle]
                projected["pagination"] = _page_delivery(page, projected["response_excerpt"])
                if size() <= max_chars:
                    low = middle
                else:
                    high = middle - 1
            projected["response_excerpt"] = excerpt[:low]
            projected["pagination"] = _page_delivery(page, projected["response_excerpt"])
        else:
            projected["response_excerpt"] = ""
        trimmed = True
    for key in ("links", "references", "artifacts"):
        while size() > max_chars and projected.get(key):
            projected[key].pop()
            trimmed = True
    while size() > max_chars and projected.get("request"):
        removed, _ = projected["request"].popitem()
        if removed in _REQUEST_ID_LISTS and "request_lists_truncated" in projected:
            projected["request_lists_truncated"][removed] = True
        trimmed = True
    # Small parent budgets and unusually large diagnostic fields must not
    # escape the bound after collections have been reduced.
    for key in ("stash_error", "download_error", "configuration_required", "response_excerpt", "links", "references", "artifacts",
                "request", "external_content_trust", "tool", "source", "content_links_untrusted",
                "response_truncated", "authentication_required", "google_ok", "google_export_ok", "download_ok",
                "request_list_counts", "request_lists_truncated", "batch_outcomes", "image_delivery",
                "next_sync_token", "next_sync_token_unavailable", "new_series_id", "pagination", "ok"):
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
    if tool_name in {"get_drive_file_content", "render_page_to_image"}:
        hints.append("Inline PNG/JPEG/GIF/WebP images are saved to Jarvis Stash (up to 4 images, "
                     "8 MiB each, 16 MiB total). The result contains metadata and stash:// references, "
                     "not visual analysis. Use analyze_image with those references to inspect images; "
                     "check image_delivery for unavailable or partial saves.")
    if tool_name in {"send_gmail_message", "draft_gmail_message"}:
        for key in ("to", "cc", "bcc"):
            if key in props:
                props[key]["description"] = (
                    props[key].get("description", "")
                    + " Also accepts a contact key or display name from Jarvis config/contacts.json "
                    "(case-insensitive), or comma-separated names and email addresses."
                ).strip()
        hints.append("Gmail recipients in to, cc and bcc accept the same local contact names as "
                     "send_email, such as Boss. Pass the requested contact name directly; "
                     "Jarvis resolves it from config/contacts.json before calling Google. Unknown "
                     "names fail without sending.")
        hints.append("For a read-only lookup of those local aliases, use email_contacts. "
                     "Google list_contacts/search_contacts inspect a separate Google address book; "
                     "no Google or memory match does not mean the local alias is missing. "
                     "Explicit recipient addresses are supported without a saved contact.")
        hints.append("Use this tool for 'use Gmail to email Boss'." if tool_name == "send_gmail_message"
                     else "Use this tool for 'draft a Gmail email to Boss'; it creates an unsent draft.")
    if tool_name in {"list_contacts", "search_contacts", "get_contact"}:
        hints.append("Reads Google Contacts, not Jarvis config/contacts.json or conversational memory. "
                     "Use email_contacts to inspect Jarvis local aliases shared by send_email and "
                     "Gmail send/draft. An empty Google result does not establish that a local "
                     "email alias is missing.")
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


def resolve_workspace_recipients(tool_name: str, arguments: dict) -> dict:
    """Resolve only Gmail recipient fields; account and Send As identity are separate."""
    resolved = dict(arguments)
    if tool_name in {"send_gmail_message", "draft_gmail_message"}:
        contacts = load_contacts()
        for key in ("to", "cc", "bcc"):
            value = resolved.get(key)
            if value is not None and value != "":
                resolved[key] = resolve_email_recipients(value, contacts)
    return resolved


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


def download_workspace_file(client, result: dict, *, max_bytes=None) -> dict:
    """Bounded download from the configured authenticated origin; no Stash write."""
    from email.message import Message

    from mcp_client import _check_remote_call_budget
    from stash_helper import sanitize_filename

    if not result.get("ok"):
        raise ValueError("Google file export failed")
    data = result.get("data") or {}
    max_bytes = _MAX_BRIDGE_BYTES if max_bytes is None else max_bytes
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
        declared_size = None
        if declared is not None:
            if not re.fullmatch(r"[0-9]{1,20}", str(declared)):
                raise ValueError("Invalid Google download Content-Length")
            declared_size = int(declared)
            if declared_size > max_bytes:
                raise ValueError(f"Google download exceeds {max_bytes} bytes")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            _check_remote_call_budget()
            if len(body) + len(chunk) > max_bytes:
                raise ValueError(f"Google download exceeds {max_bytes} bytes")
            body.extend(chunk)
        _check_remote_call_budget()
        # requests decodes compressed transfer bodies, so the advertised wire
        # length is comparable only for identity content encoding.
        if (declared_size is not None and response.headers.get("Content-Encoding", "identity").lower() == "identity"
                and len(body) != declared_size):
            raise ValueError("Google download was incomplete: Content-Length does not match received bytes")
        disposition = Message()
        disposition["content-disposition"] = response.headers.get("Content-Disposition", "")
        name = sanitize_filename(disposition.get_filename() or "google_attachment")
        mime = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
    finally:
        response.close()
    return {"body": bytes(body), "name": name, "mime_type": mime}


def stash_workspace_download(client, result: dict, space_id=None) -> dict:
    """Copy one explicit download through the canonical Stash helper."""
    import hashlib
    from pathlib import Path

    from mcp_client import _check_remote_call_budget
    from stash_helper import (
        SecurityError,
        StashFile,
        open_space,
        validate_gif_artifact,
        validate_gif_declarations,
    )

    if not result.get("ok"):
        return result
    data = result["data"]
    data["google_export_ok"] = True
    data["download_ok"] = False
    data["google_ok"] = False
    try:
        downloaded = download_workspace_file(client, result)
        data["download_ok"] = data["google_ok"] = True
        body, name, mime = downloaded["body"], downloaded["name"], downloaded["mime_type"]
        declared_mime = mime
        # Authenticated origin and transfer completeness do not establish that
        # an animation is safe to decode. Validate before either save or reuse.
        gif_metadata = validate_gif_artifact(body, name=name, mime_type=mime)
        if gif_metadata is not None:
            mime = gif_metadata["mime_type"]
        _check_remote_call_budget()
        import time
        budget = _check_remote_call_budget()
        lock_timeout = min(5, max(0, budget.deadline - time.monotonic())) if budget else 5
        space, _ = open_space(space_id=space_id, labels=["google_workspace"], scope="project", lock_timeout=lock_timeout)
        with space.transaction(timeout=lock_timeout):
            _check_remote_call_budget()
            digest = hashlib.sha256(body).hexdigest()
            saved = None
            for item in space.meta.get("files", []):
                if item.get("hash_sha256") == digest and (
                    item.get("mime_type") == mime or gif_metadata is not None
                ):
                    if gif_metadata is not None:
                        try:
                            validate_gif_declarations(item.get("name", ""), item.get("mime_type"))
                            validate_gif_declarations(item.get("stored_name", ""), item.get("mime_type"))
                        except SecurityError:
                            # An incompatible old row is not a cache candidate.
                            # Continue to a compatible row or a new checked save.
                            continue
                    entry = StashFile(space, file_id=item["file_id"])
                    if entry.path and Path(entry.path).is_file():
                        if gif_metadata is not None:
                            # Legacy metadata may predate validation or no longer
                            # describe the file on disk. Never trust its hash alone.
                            entry.validate_gif(
                                name=name, mime_type=declared_mime, expected_sha256=digest,
                            )
                            _check_remote_call_budget()
                        saved = {**entry.meta, "ref": f"stash://{space.space_id}/{item['file_id']}"}
                        break
            if saved is None:
                saved = StashFile(space).save_binary(bytes(body), name=name, mime_type=declared_mime,
                    on_conflict="version", tags=["google_workspace"], tool_origin=PREFIX + data["tool"])
            _check_remote_call_budget()
        artifact = {key: saved[key] for key in ("ref", "file_id", "name", "mime_type", "size_bytes")}
        for key in ("gif_validation", "animated", "frame_count", "duration_ms", "width", "height"):
            if key in saved:
                artifact[key] = saved[key]
        artifact["space_id"] = space.space_id
        from config_loader import get_active_config_mode
        artifact["mode"] = get_active_config_mode()
        artifact["download_url"] = f"/api/stash/{space.space_id}/{saved['file_id']}?mode={artifact['mode']}"
        data["artifacts"] = [artifact]
        # The authenticated temporary link is not a usable browser download.
        data["links"] = [link for link in data.get("links", [])
                         if not re.fullmatch(r"/attachments/" + _UUID, urlsplit(link["url"]).path)]
        data["response_text"] += f"\nStashed file: {artifact['ref']}"
        result["speech"] = "Google file downloaded and saved to Jarvis Stash."
    except Exception as exc:
        data.pop("artifacts", None)
        data["ok"] = result["ok"] = False
        if data["download_ok"]:
            data["stash_error"] = str(exc)
            result["error"] = f"Google download succeeded, but Stash save failed: {exc}"
        else:
            data["download_error"] = str(exc)
            result["error"] = f"Google export returned a receipt, but the file download failed: {exc}"
        result["speech"] = result["error"]
    return result
