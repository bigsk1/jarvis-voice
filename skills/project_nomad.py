#!/usr/bin/env python3
"""Bounded, opt-in access to a Project NOMAD knowledge server."""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import get_config_value, load_config  # noqa: E402

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
LIST_LIMIT = 20
VIEWABLE_TEXT_EXTENSIONS = frozenset({"md", "txt", "csv", "json", "yaml", "yml", "toml", "xml", "html"})


class NomadError(Exception):
    """An error safe to show to the user without leaking server responses."""


def _string(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())
    return value[:limit]


def _exact(value: Any, limit: int) -> str:
    return value if isinstance(value, str) and len(value) <= limit else ""


def _viewable_text(row: dict[str, Any]) -> bool:
    name = row.get("fileName")
    return (row.get("isUserUpload") is True and isinstance(name, str)
            and name.rsplit(".", 1)[-1].lower() in VIEWABLE_TEXT_EXTENSIONS)


def _base_url() -> str:
    configured = str(get_config_value("PROJECT_NOMAD_BASE_URL", "") or "").strip()
    try:
        parts = urlsplit(configured)
        # The configured server is an operator choice, never a model argument.
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment):
            raise ValueError
        path = parts.path.rstrip("/")
        if path.endswith("/api"):
            path = path[:-4]
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    except ValueError as exc:
        raise NomadError(
            "Set PROJECT_NOMAD_BASE_URL to an HTTP(S) Nomad server URL without credentials or query parameters."
        ) from exc


def _request_json(
    method: str, path: str, *, params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None, read_timeout: int = 20,
) -> Any:
    if method not in {"GET", "POST"} or not path.startswith("/api/"):
        raise ValueError("Unsupported Nomad route.")
    session = requests.Session()
    session.trust_env = False  # A LAN service must not inherit ambient proxy settings.
    try:
        try:
            response = session.request(
                method, _base_url() + path, params=params, json=body,
                headers={"Accept": "application/json", "User-Agent": "Jarvis-Project-NOMAD/1.0"},
                timeout=(5, read_timeout), stream=True, allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise NomadError(f"Project NOMAD request failed ({type(exc).__name__}).") from exc
        try:
            if not 200 <= response.status_code < 300:
                raise NomadError(f"Project NOMAD returned HTTP {response.status_code} for {path}.")
            size_header = response.headers.get("Content-Length", "")
            if size_header.isdigit() and int(size_header) > MAX_RESPONSE_BYTES:
                raise NomadError("Project NOMAD response is too large for this tool.")
            chunks: list[bytes] = []
            size = 0
            try:
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise NomadError("Project NOMAD response is too large for this tool.")
                    chunks.append(chunk)
            except requests.RequestException as exc:
                raise NomadError(f"Project NOMAD response failed ({type(exc).__name__}).") from exc
            try:
                payload = json.loads(b"".join(chunks))
            except (UnicodeDecodeError, ValueError) as exc:
                raise NomadError("Project NOMAD did not return valid JSON.") from exc
            if isinstance(payload, dict) and payload.get("success") is False:
                raise NomadError("Project NOMAD rejected the request.")
            return payload
        finally:
            response.close()
    finally:
        session.close()


def _limit_offset(arguments: dict[str, Any]) -> tuple[int, int]:
    limit = arguments.get("limit", 10)
    offset = arguments.get("offset", 0)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= LIST_LIMIT:
        raise ValueError("'limit' must be an integer from 1 to 20.")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100000:
        raise ValueError("'offset' must be an integer from 0 to 100000.")
    return limit, offset


def _required_string(arguments: dict[str, Any], name: str, limit: int, *, exact: bool = False) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"'{name}' must be 1 to {limit} characters.")
    return value if exact else value.strip()


def _optional_string(arguments: dict[str, Any], name: str, limit: int) -> str:
    value = arguments.get(name)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"'{name}' must be at most {limit} characters.")
    return value.strip()


def _rows(payload: Any, key: str) -> list[Any]:
    rows = payload.get(key) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise NomadError(f"Project NOMAD returned an unexpected {key} response.")
    return rows


def _slice(rows: list[dict[str, Any]], arguments: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    limit, offset = _limit_offset(arguments)
    return rows[offset:offset + limit], limit, offset


def _files_payload() -> list[dict[str, Any]]:
    return [row for row in _rows(_request_json("GET", "/api/rag/files"), "files") if isinstance(row, dict)]


def _inventory_summary(files: list[dict[str, Any]]) -> dict[str, Any]:
    states = {name: 0 for name in (
        "indexed", "pending_decision", "failed", "browse_only", "stalled", "queued", "processing",
    )}
    states["other"] = 0
    with_chunks = 0
    reported_chunks = 0
    unassigned = 0
    for row in files:
        state = row.get("state")
        states[state if isinstance(state, str) and state in states else "other"] += 1
        chunks = row.get("chunksEmbedded")
        if type(chunks) is int and chunks > 0:
            with_chunks += 1
            reported_chunks += chunks
        if not row.get("collection"):
            unassigned += 1
    return {
        "total_files": len(files), "states": states, "files_with_chunks": with_chunks,
        "reported_embedded_chunks": reported_chunks, "unassigned_files": unassigned,
    }


def _files(arguments: dict[str, Any]) -> dict[str, Any]:
    _limit_offset(arguments)
    collection = _optional_string(arguments, "collection", 120)
    query = _optional_string(arguments, "query", 120)
    all_files = _files_payload()
    inventory = _inventory_summary(all_files)
    files = all_files
    if collection:
        files = [row for row in files if row.get("collection") == collection]
    if query:
        needle = query.casefold()
        files = [row for row in files if needle in str(row.get("fileName") or "").casefold()
                 or needle in str(row.get("source") or "").casefold()]
    total = len(files)
    page, limit, offset = _slice(files, arguments)
    data = {
        "action": "files", "total": total, "offset": offset, "limit": limit,
        "has_more": offset + len(page) < total, "collection": collection or None,
        "query": query or None, "inventory": inventory,
        "note": "File names and index states are metadata, not document text or proof of chat retrieval."
                " Ask without a collection filter to query unassigned knowledge.",
        "files": [{
            "source": _exact(row.get("source"), 500),
            "file_name": _string(row.get("fileName"), 240),
            "collection": _exact(row.get("collection"), 120),
            "state": _string(row.get("state"), 60),
            "viewable_text": _viewable_text(row),
            "chunks_embedded": row.get("chunksEmbedded") if isinstance(row.get("chunksEmbedded"), int) else None,
            "size_bytes": row.get("size") if isinstance(row.get("size"), int) else None,
            "uploaded_at": _string(row.get("uploadedAt"), 80),
        } for row in page],
    }
    speech = (f"Project NOMAD reports {inventory['total_files']} stored RAG files, "
              f"{inventory['files_with_chunks']} with embedded chunks, "
              f"{inventory['states']['pending_decision']} pending decisions, and "
              f"{inventory['states']['failed']} failed. "
              f"This filtered view has {total} file(s); showing {len(page)}. "
              "Do not infer the full inventory from this page.")
    return {"ok": True, "speech": speech, "data": data}


def _read_file(arguments: dict[str, Any]) -> dict[str, Any]:
    source = _required_string(arguments, "source", 500, exact=True)
    start = arguments.get("start_char", 0)
    if isinstance(start, bool) or not isinstance(start, int) or not 0 <= start <= 10_000_000:
        raise ValueError("'start_char' must be an integer from 0 to 10000000.")
    matching = next((row for row in _files_payload() if row.get("source") == source), None)
    if matching is None:
        raise NomadError("That source is not in Nomad's stored-file list. Use the files action to obtain its exact source value.")
    if not _viewable_text(matching):
        raise NomadError("Nomad's file-content API only views uploaded text files; open this PDF, EPUB, ZIM, or other source in Nomad's interface.")
    payload = _request_json("GET", "/api/rag/files/content", params={"source": source})
    content = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(content, str):
        raise NomadError("Project NOMAD returned an unsupported file-content response.")
    excerpt = content[start:start + 12000]
    data = {
        "action": "read_file", "source": source, "text": excerpt,
        "start_char": start, "next_start_char": start + len(excerpt) if start + len(excerpt) < len(content) else None,
        "total_chars": len(content),
        "evidence_note": "Uploaded Nomad text file. This is not an original-layout viewer or a passage citation.",
    }
    return {"ok": True, "speech": excerpt[:1200] or "No text at this offset.", "data": data}


def _collections(arguments: dict[str, Any]) -> dict[str, Any]:
    _limit_offset(arguments)
    rows = _rows(_request_json("GET", "/api/rag/collections"), "collections")
    total = len(rows)
    page, limit, offset = _slice(rows, arguments)
    names = [_exact(row if isinstance(row, str) else row.get("name") or row.get("collection"), 120)
             for row in page if isinstance(row, (str, dict))]
    return {"ok": True, "speech": f"Project NOMAD has {total} named knowledge collection(s)."
            " Unassigned files can still be indexed and searched.", "data": {
        "action": "collections", "total": total, "offset": offset, "limit": limit,
        "has_more": offset + len(page) < total, "collections": names,
        "note": "Named collections are optional groups. Zero named collections does not mean an empty knowledge base.",
    }}


def _zims(arguments: dict[str, Any]) -> dict[str, Any]:
    _limit_offset(arguments)
    rows = [row for row in _rows(_request_json("GET", "/api/zim/list"), "files") if isinstance(row, dict)]
    total = len(rows)
    page, limit, offset = _slice(rows, arguments)
    return {"ok": True, "speech": f"Project NOMAD has {total} installed ZIM file(s).", "data": {
        "action": "zims", "total": total, "offset": offset, "limit": limit,
        "has_more": offset + len(page) < total,
        "zim_inventory_only": True,
        "note": "Installed ZIM inventory does not show whether articles were embedded into Qdrant; chat may retrieve only embedded content.",
        "zims": [{
            "key": _exact(row.get("key"), 240), "title": _string(row.get("title") or row.get("name"), 240),
            "type": _string(row.get("type"), 80), "size_bytes": row.get("size_bytes") if isinstance(row.get("size_bytes"), int) else None,
            "summary": _string(row.get("summary"), 400),
        } for row in page],
    }}


def _models(arguments: dict[str, Any]) -> dict[str, Any]:
    _limit_offset(arguments)
    rows = [row for row in _rows(_request_json("GET", "/api/ollama/installed-models"), "models") if isinstance(row, dict)]
    total = len(rows)
    page, limit, offset = _slice(rows, arguments)
    return {"ok": True, "speech": f"Project NOMAD sees {total} installed model(s).", "data": {
        "action": "models", "total": total, "offset": offset, "limit": limit,
        "has_more": offset + len(page) < total,
        "models": [{
            "name": _string(row.get("name") or row.get("model"), 180),
            "thinking": row.get("thinking") is True,
            "cloud": str(row.get("name") or row.get("model") or "").endswith(":cloud"),
        } for row in page],
    }}


def _answer_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    for key in ("response", "content", "answer"):
        if isinstance(payload.get(key), str):
            return payload[key]
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def _ask(arguments: dict[str, Any]) -> dict[str, Any]:
    question = _required_string(arguments, "question", 2000)
    collection = _optional_string(arguments, "collection", 120)
    model = _optional_string(arguments, "model", 180) or str(get_config_value("PROJECT_NOMAD_MODEL", "") or "").strip()
    if not model or len(model) > 180:
        raise ValueError("Set PROJECT_NOMAD_MODEL or provide a model from the models action.")
    think = arguments.get("think", False)
    if not isinstance(think, bool):
        raise ValueError("'think' must be true or false.")
    if collection:
        rows = _rows(_request_json("GET", "/api/rag/collections"), "collections")
        names: set[str] = set()
        for row in rows:
            if isinstance(row, str):
                name = row
            elif isinstance(row, dict):
                name = row.get("name") or row.get("collection")
            else:
                continue
            if isinstance(name, str):
                names.add(name)
        if collection not in names:
            raise NomadError("That named Nomad collection does not exist. Leave collection unset to ask across unassigned knowledge.")
    payload = _request_json(
        "POST", "/api/ollama/chat", params={"collection": collection} if collection else None,
        body={"model": model, "messages": [{"role": "user", "content": question}], "stream": False, "think": think},
        read_timeout=145,
    )
    answer = _answer_text(payload)
    if not answer.strip():
        raise NomadError("Project NOMAD returned no usable chat answer.")
    answer = answer.strip()
    data = {
        "action": "ask", "question": question, "answer": answer[:16000],
        "answer_truncated": len(answer) > 16000, "model": model,
        "collection": collection or None,
        "grounding_status": "unverified",
        "evidence_note": "Nomad-generated answer; this chat response provides no verifiable source passages. Do not claim a particular file was retrieved from the answer alone.",
    }
    return {"ok": True, "speech": answer[:1200], "data": data}


def _status(_arguments: dict[str, Any]) -> dict[str, Any]:
    health = _request_json("GET", "/api/health")
    rag = _request_json("GET", "/api/rag/health")
    status = _string(health.get("status"), 80) if isinstance(health, dict) else ""
    online = rag.get("online") is True if isinstance(rag, dict) else False
    return {"ok": True, "speech": f"Project NOMAD status: {status or 'unknown'}; RAG service {'online' if online else 'offline'}."
            " This does not verify that a particular answer retrieved documents.", "data": {
        "action": "status", "status": status, "rag_online": online,
        "note": "RAG service reachability is not a test of document indexing or answer grounding.",
    }}


ACTIONS = {
    "ask": _ask, "files": _files, "read_file": _read_file,
    "collections": _collections, "zims": _zims, "models": _models, "status": _status,
}


def run(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("Tool input must be a JSON object.")
    action = arguments.get("action")
    if action not in ACTIONS:
        raise ValueError("Choose action: ask, files, read_file, collections, zims, models, or status.")
    return ACTIONS[action](arguments)


def main() -> int:
    load_config()
    try:
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        result = run(arguments)
    except (ValueError, NomadError) as exc:
        result = {"ok": False, "speech": str(exc), "error": str(exc)}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
