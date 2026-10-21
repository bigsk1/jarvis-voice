#!/usr/bin/env python3
"""
OpenCode Client for Jarvis
Python wrapper for OpenCode HTTP API.
"""

import json
import os
import queue
import re
import shlex
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import requests
from model_catalog import get_provider_fallback_model
from opencode_logger import OpenCodeLogger
from paths import get_jarvis_workspace, get_project_root


def resolve_opencode_defaults(mode: str | None = None) -> dict[str, str]:
    """Resolve OpenCode provider/model from config with model_catalog fallbacks.

    OpenCode remains independently configurable: explicit OPENCODE_PROVIDER /
    OPENCODE_MODEL always win. When OpenCode's provider resolves to Ollama with
    no OpenCode-specific model, the mode-aware Ollama resolver is used so cloud
    mode picks OLLAMA_CLOUD_MODEL rather than the local OLLAMA_MODEL.
    """
    try:
        from config_loader import get_active_config_mode, get_config_value
        mode = get_active_config_mode(mode)
    except ImportError:
        get_config_value = lambda key, default="": default  # noqa: E731
        if mode is None:
            mode = os.environ.get("JARVIS_MODE", "cloud")

    def _ollama_default_model() -> str:
        try:
            from ollama_utils import resolve_ollama_model
            return resolve_ollama_model(mode)
        except Exception:
            return get_provider_fallback_model("ollama")

    configured_provider = get_config_value("OPENCODE_PROVIDER", "").strip()
    configured_model = get_config_value("OPENCODE_MODEL", "").strip()

    if configured_provider and configured_model:
        provider, model_id = configured_provider, configured_model
    elif configured_provider:
        provider = configured_provider
        model_id = _ollama_default_model() if provider == "ollama" else get_provider_fallback_model(provider)
    elif configured_model:
        provider = "ollama" if mode == "local" else "anthropic"
        model_id = configured_model
    elif mode == "local":
        provider = "ollama"
        model_id = _ollama_default_model()
    else:
        provider = "anthropic"
        model_id = get_provider_fallback_model(provider)

    return {"providerID": provider, "modelID": model_id}


class OpenCodeClient:
    """Client for communicating with OpenCode server."""

    SSE_READ_TIMEOUT_SECONDS = 45
    HEALTHY_POLL_INTERVAL_SECONDS = 10
    DEGRADED_POLL_INTERVAL_SECONDS = 3
    HEARTBEAT_INTERVAL_SECONDS = 30
    NO_REPLY_TIMEOUT_SECONDS = 30
    DEFAULT_TASK_TIMEOUT_SECONDS = 900
    MAX_PROGRESS_TOOL_CONTEXT = 128

    def __init__(self, base_url: str | None = None):
        """
        Initialize OpenCode client.
        
        Args:
            base_url: OpenCode server URL (defaults to config or localhost:4096)
        """
        if base_url is None:
            # Try to get from config
            try:
                from config_loader import get_config_value
                base_url = get_config_value("OPENCODE_BASE_URL", "http://localhost:4096")
            except Exception:
                base_url = "http://localhost:4096"
        
        self.base_url = base_url.rstrip("/")
        self.timeout = 360  # Generic OpenCode API calls; final tasks use task_timeout.
        self.logger = OpenCodeLogger()
        self.active_session_id: str | None = None
        self.active_input_id: str | None = None
        self._pending_input_ids: dict[str, list[str]] = {}
        self._cancelled_sessions: set[str] = set()
        
        # Load model config from environment
        try:
            from config_loader import get_config_value

            defaults = resolve_opencode_defaults()
            self.default_provider_id = defaults["providerID"]
            self.default_model_id = defaults["modelID"]
            try:
                self.task_timeout = max(
                    60,
                    int(
                        get_config_value(
                            "OPENCODE_TASK_TIMEOUT_SECONDS",
                            str(self.DEFAULT_TASK_TIMEOUT_SECONDS),
                        )
                    ),
                )
            except (TypeError, ValueError):
                self.task_timeout = self.DEFAULT_TASK_TIMEOUT_SECONDS
            server_password = get_config_value("OPENCODE_SERVER_PASSWORD", "").strip()
            server_username = get_config_value("OPENCODE_SERVER_USERNAME", "opencode").strip() or "opencode"
        except Exception:
            self.default_provider_id = "anthropic"
            self.default_model_id = get_provider_fallback_model("anthropic")
            self.task_timeout = self.DEFAULT_TASK_TIMEOUT_SECONDS
            server_password = ""
            server_username = "opencode"

        if server_username != "opencode":
            raise ValueError("OpenCode 2 requires OPENCODE_SERVER_USERNAME=opencode; update Jarvis and the service environment together")
        self.auth = (server_username, server_password) if server_password else None
        
        self._verify_connection()

    def _request_kwargs(self, timeout: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"timeout": timeout}
        if self.auth:
            kwargs["auth"] = self.auth
        return kwargs

    def _get(
        self,
        path: str,
        timeout: int | float | tuple[int | float, int | float] | None = None,
        **request_options: Any,
    ):
        kwargs = self._request_kwargs(timeout or self.timeout)
        kwargs.update(request_options)
        return requests.get(f"{self.base_url}{path}", **kwargs)

    def _post(
        self,
        path: str,
        json_payload: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ):
        kwargs = self._request_kwargs(timeout or self.timeout)
        if json_payload is not None:
            kwargs["json"] = json_payload
        return requests.post(f"{self.base_url}{path}", **kwargs)

    def _verify_connection(self, max_retries: int = 3) -> bool:
        """Verify OpenCode server is accessible."""
        for attempt in range(max_retries):
            try:
                response = self._get("/api/info", timeout=5)
                if response.status_code == 200 and str(response.json().get("version", "")).lstrip(
                    "v"
                ).startswith("2."):
                    return True
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    print(f"⚠️  OpenCode server not reachable at {self.base_url}", file=sys.stderr)
                    return False
            except Exception as e:
                print(f"⚠️  Error connecting to OpenCode: {e}", file=sys.stderr)
                return False
        return False

    def health_check(self) -> dict[str, Any]:
        """Check OpenCode server health."""
        try:
            response = self._get("/api/info", timeout=5)
            if response.status_code != 200:
                return {"healthy": False, "status": "error"}

            info = response.json()
            version = str(info.get("version", "")).lstrip("v")
            if not version.startswith("2."):
                return {
                    "healthy": False,
                    "status": "incompatible",
                    "error": "Jarvis requires OpenCode 2; upgrade and restart the OpenCode service.",
                }

            return {
                "healthy": True,
                "status": "running",
                "version": version,
            }
        except Exception as e:
            return {"healthy": False, "status": "error", "error": str(e)}

    def create_session(
        self, title: str = "Jarvis Session", agent_mode: str = "build"
    ) -> dict[str, Any]:
        """Create a new OpenCode session."""
        payload: dict[str, Any] = {
            "title": title,
            "location": {"directory": str(get_jarvis_workspace().resolve())},
        }
        if agent_mode:
            payload["agent"] = agent_mode

        response = self._post("/api/session", json_payload=payload)
        response.raise_for_status()
        return self._response_data(response, dict)

    def get_session(self, session_id: str) -> dict[str, Any]:
        """Get session information."""
        response = self._get(f"/api/session/{quote(session_id, safe='')}")
        response.raise_for_status()
        return self._response_data(response, dict)

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions, following V2 cursors in newest-first order."""
        sessions: list[dict[str, Any]] = []
        params: dict[str, Any] = {"order": "desc", "limit": 50}
        seen_cursors: set[str] = set()
        while True:
            response = self._get("/api/session", params=params)
            response.raise_for_status()
            sessions.extend(self._response_data(response, list))
            pagination = response.json().get("cursor")
            if not isinstance(pagination, dict):
                raise RuntimeError("Unexpected OpenCode 2 session pagination format")
            cursor = pagination.get("next")
            if cursor is None:
                return sessions
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise RuntimeError("Invalid or repeated OpenCode 2 session pagination cursor")
            seen_cursors.add(cursor)
            # The cursor carries its order; V2 rejects order plus cursor.
            params = {"cursor": cursor, "limit": 50}

    @staticmethod
    def _response_data(response: Any, expected_type: type) -> Any:
        """Unwrap V2 envelopes and reject HTML, receipts, or malformed responses."""
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, expected_type):
            raise RuntimeError("Unexpected OpenCode 2 response format")
        return data

    def get_messages(self, session_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return native V2 messages, newest first."""
        response = self._get(
            f"/api/session/{quote(session_id, safe='')}/message",
            params={"order": "desc", "limit": limit},
            timeout=5,
        )
        response.raise_for_status()
        return self._response_data(response, list)

    def send_message(
        self,
        session_id: str,
        message: str,
        provider_id: str | None = None,
        model_id: str | None = None,
        no_reply: bool = False,
    ) -> dict[str, Any]:
        """Send a message to an OpenCode session."""
        # Use configured defaults if not specified
        if provider_id is None:
            provider_id = self.default_provider_id
        if model_id is None:
            model_id = self.default_model_id

        self._check_cancelled(session_id)
        session_path = f"/api/session/{quote(session_id, safe='')}"
        if no_reply:
            input_id = "msg_" + uuid.uuid4().hex
            self._pending_input_ids.setdefault(session_id, []).append(input_id)
            try:
                response = self._post(
                    f"{session_path}/synthetic",
                    json_payload={
                        "id": input_id,
                        "text": message,
                        "resume": False,
                        "delivery": "queue",
                    },
                    timeout=self.NO_REPLY_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
            finally:
                self._check_cancelled(session_id, admitted_id=input_id)
            receipt = self._response_data(response, dict)
            if receipt.get("id") != input_id:
                raise RuntimeError("OpenCode synthetic receipt did not match the submitted input")
            return receipt

        started = time.monotonic()
        response = self._post(
            f"{session_path}/model",
            json_payload={"model": {"providerID": provider_id, "id": model_id}},
            timeout=self.NO_REPLY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        self._check_cancelled(session_id)
        input_id = "msg_" + uuid.uuid4().hex
        self.active_input_id = input_id
        self._pending_input_ids.setdefault(session_id, []).append(input_id)
        try:
            response = self._post(
                f"{session_path}/prompt",
                json_payload={"id": input_id, "text": message, "delivery": "queue"},
                timeout=self.NO_REPLY_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        finally:
            self._check_cancelled(session_id, admitted_id=input_id)
        receipt = self._response_data(response, dict)
        if receipt.get("id") != input_id or receipt.get("type") != "user":
            raise RuntimeError("OpenCode did not return a durable prompt receipt")
        remaining = self.task_timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("OpenCode task deadline reached")
        response = self._post(
            f"/api/experimental/session/{quote(session_id, safe='')}/wait", timeout=remaining
        )
        response.raise_for_status()
        self._check_cancelled(session_id)
        result = self._collect_final_response(session_id, input_id)
        self._pending_input_ids.pop(session_id, None)
        return result

    def _check_cancelled(self, session_id: str, admitted_id: str | None = None) -> None:
        """Prevent a slow request from admitting work after its owner cancelled."""
        if session_id not in getattr(self, "_cancelled_sessions", set()):
            return
        if admitted_id:
            # Cancellation may have raced the HTTP admission. Reconcile the
            # known ID once the server acknowledges it; never resubmit it.
            pending = self._pending_input_ids.setdefault(session_id, [])
            if admitted_id not in pending:
                pending.append(admitted_id)
            self.abort_session(session_id)
        raise RuntimeError("OpenCode task was cancelled")

    def _collect_final_response(self, session_id: str, input_id: str) -> dict[str, Any]:
        """Collect only completed output after this prompt, never an older answer."""
        path = f"/api/session/{quote(session_id, safe='')}/message"
        params: dict[str, Any] = {"order": "desc", "limit": 100}
        newest_assistant = None
        outcome = None
        seen_cursors: set[str] = set()
        while True:
            response = self._get(path, params=params, timeout=5)
            response.raise_for_status()
            messages = self._response_data(response, list)
            for item in messages:
                if item.get("id") == input_id:
                    if outcome != "succeeded":
                        raise RuntimeError(
                            f"OpenCode execution {outcome or 'has no confirmed completion'}"
                        )
                    if not newest_assistant or not self._has_usable_final_response(
                        newest_assistant
                    ):
                        raise RuntimeError("OpenCode finished without a usable assistant answer")
                    # Keep the established Jarvis result shape; provider replay data
                    # and hidden reasoning are not required by the caller.
                    return {
                        "info": {
                            k: newest_assistant[k]
                            for k in ("id", "type", "time", "model", "finish")
                            if k in newest_assistant
                        },
                        "parts": [
                            {"type": "text", "text": part["text"]}
                            for part in newest_assistant.get("content", [])
                            if part.get("type") == "text" and isinstance(part.get("text"), str)
                        ],
                    }
                if item.get("type") == "idle" and outcome is None:
                    outcome = item.get("outcome")
                    if outcome != "succeeded":
                        raise RuntimeError(
                            self._error_message(
                                item.get("error") or f"OpenCode execution {outcome}"
                            )
                        )
                if item.get("type") == "user":
                    raise RuntimeError(
                        "OpenCode session received concurrent input; inspect the session before continuing"
                    )
                if item.get("type") == "assistant" and newest_assistant is None:
                    if item.get("error"):
                        raise RuntimeError(self._error_message(item["error"]))
                    if item.get("time", {}).get("completed"):
                        newest_assistant = item
            cursor = response.json().get("cursor", {}).get("next")
            if not cursor or cursor in seen_cursors:
                raise RuntimeError(
                    "OpenCode prompt delivery could not be confirmed; no previous answer was reused"
                )
            seen_cursors.add(cursor)
            params = {"cursor": cursor, "limit": 100}

    @staticmethod
    def _iter_sse_payloads(
        lines: Iterable[str | bytes],
        stop_event: threading.Event | None = None,
    ) -> Iterable[dict[str, Any]]:
        """Yield decoded JSON payloads from a Server-Sent Events line stream."""
        data_lines: list[str] = []

        for raw_line in lines:
            # V2 sends comment-only keepalives. Observe cancellation even when
            # there is no JSON event to yield to the outer consumer.
            if stop_event is not None and stop_event.is_set():
                return
            line = (
                raw_line.decode("utf-8", errors="replace")
                if isinstance(raw_line, bytes)
                else str(raw_line)
            )
            if line == "":
                if data_lines:
                    try:
                        payload = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict):
                        yield payload
                    data_lines = []
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if data_lines:
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                yield payload

    def _stream_events(
        self,
        event_queue: queue.Queue,
        stop_event: threading.Event,
        ready_event: threading.Event,
    ) -> None:
        """Continuously read OpenCode's SSE feed until the supervised call ends."""
        while not stop_event.is_set():
            response = None
            try:
                response = self._get(
                    "/api/event",
                    timeout=(5, self.SSE_READ_TIMEOUT_SECONDS),
                    headers={"Accept": "text/event-stream"},
                    stream=True,
                )
                response.raise_for_status()
                ready_event.set()
                event_queue.put({"_monitor_connected": True})
                for payload in self._iter_sse_payloads(
                    response.iter_lines(chunk_size=1, decode_unicode=True),
                    stop_event=stop_event,
                ):
                    if stop_event.is_set():
                        break
                    event_queue.put(payload)
            except Exception as exc:
                ready_event.set()
                if not stop_event.is_set():
                    event_queue.put({"_monitor_error": str(exc)[:300]})
                if stop_event.wait(1):
                    break
            finally:
                if response is not None:
                    response.close()

    @staticmethod
    def _clean_progress_text(value: Any, max_chars: int = 160) -> str:
        """Bound and flatten provider text before it reaches status/TTS surfaces."""
        if not isinstance(value, str):
            return ""
        text = re.sub(r"\s+", " ", value).strip()
        text = "".join(char for char in text if char.isprintable())
        secret_value = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s;&"']+)'''
        text = re.sub(
            r"(?i)\b(authorization\s*[:=]\s*)(?:[a-z][a-z0-9_-]*\s+)?" + secret_value,
            r"\1[redacted]",
            text,
        )
        text = re.sub(
            r"(?i)\b((?:[a-z0-9]+[_-])*(?:api[_-]?key|token|password|"
            r"secret(?:[_-]?access[_-]?key)?|access[_-]?key(?:[_-]?id)?))"
            r'''["']?\s*[:=]\s*''' + secret_value,
            r"\1=[redacted]",
            text,
        )
        text = re.sub(
            r"(?i)((?:--(?:[a-z0-9]+[-_])*(?:api[_-]?key|token|password|secret)|--user))(?:\s+|=)" + secret_value,
            r"\1 [redacted]",
            text,
        )
        text = re.sub(r"(?<!\S)(-u)\s*" + secret_value, r"\1 [redacted]", text)
        text = re.sub(r"\b(?:sk|xai)-[A-Za-z0-9_-]{8,}", "[redacted]", text)
        def safe_url(match: re.Match[str]) -> str:
            try:
                url = urlsplit(match.group(0))
                host = url.netloc.rsplit("@", 1)[-1]
                return urlunsplit((url.scheme, host, url.path, "", ""))
            except ValueError:
                return "[url]"

        text = re.sub(r'''https?://[^\s'"<>]+''', safe_url, text)
        if len(text) > max_chars:
            text = text[: max_chars - 3].rstrip() + "..."
        return text

    @classmethod
    def _command_progress_text(cls, value: Any) -> str:
        """Display only a bounded command line, excluding embedded script bodies."""
        if not isinstance(value, str) or not value.strip():
            return ""
        first_line = value.strip().splitlines()[0]
        try:
            shlex.split(first_line)
        except ValueError:
            program = cls._clean_progress_text(first_line.split(None, 1)[0], 80)
            return f"{program} [arguments omitted]"
        # Request payloads and arbitrary headers can contain credentials without
        # recognizable names. Their values do not belong in a progress preview.
        shell_argument = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\\.|[^\s;&"'\\])+'''
        first_line = re.sub(
            r"(?i)(?<!\S)(--(?:header|cookie|data(?:-raw|-binary|-urlencode|-ascii)?|form(?:-string)?|json|user|proxy-user)|-[HbdFuU])(?:\s+|=)?" + shell_argument,
            r"\1 [redacted]",
            first_line,
        )
        if "<<" in first_line:
            first_line = first_line.split("<<", 1)[0].rstrip() + " [inline script]"
        if re.search(r"(?i)\b(?:python[0-9.]*|node|ruby|perl|bash|sh|zsh|powershell|pwsh|cmd(?:\.exe)?)\b", first_line):
            first_line = re.sub(
                r'''(?i)(\s(?:-[a-z]*[ce][a-z]*|--eval|--command|-command|/c))(?=\s|=|['"$]|$).*''',
                r"\1 [inline code]",
                first_line,
            )
        return cls._clean_progress_text(first_line, 140)

    @staticmethod
    def _event_session_id(event: dict[str, Any]) -> str | None:
        properties = event.get("data", event.get("properties"))
        if not isinstance(properties, dict):
            properties = {}
        part = properties.get("part")
        if not isinstance(part, dict):
            part = {}
        return (
            properties.get("sessionID")
            or properties.get("sessionId")
            or part.get("sessionID")
            or part.get("sessionId")
            or event.get("sessionID")
            or event.get("sessionId")
            or (properties.get("form") or {}).get("sessionID")
        )

    @classmethod
    def _error_message(cls, error: Any) -> str:
        if isinstance(error, str):
            return cls._clean_progress_text(error)
        if not isinstance(error, dict):
            return "Unknown OpenCode error"
        data = error.get("data")
        if isinstance(data, dict) and data.get("message"):
            return cls._clean_progress_text(data["message"])
        return cls._clean_progress_text(
            error.get("message") or error.get("name") or "Unknown OpenCode error"
        )

    @classmethod
    def _tool_progress_title(
        cls,
        tool_name: str,
        state: dict[str, Any],
    ) -> str:
        title = cls._clean_progress_text(state.get("title"))
        inputs = state.get("input") if isinstance(state.get("input"), dict) else {}

        if not title:
            command = cls._command_progress_text(inputs.get("command"))
            if command:
                title = f"Running command: {command}"

        if not title:
            raw_path = next(
                (
                    inputs.get(key)
                    for key in ("filePath", "filepath", "path", "file")
                    if isinstance(inputs.get(key), str)
                ),
                "",
            )
            path = cls._clean_progress_text(raw_path, max_chars=120)
            if path:
                workspace = str(get_jarvis_workspace().resolve())
                if path.startswith(workspace + os.sep):
                    path = "workspace/" + path[len(workspace) + 1 :]
                if tool_name.lower() in {"read", "glob", "grep", "list"}:
                    title = f"Inspecting {path}"
                else:
                    title = f"Updating {path}"

        workspace = str(get_jarvis_workspace().resolve())
        workspace_without_root = workspace.lstrip(os.sep)
        title = title.replace(workspace + os.sep, "workspace/")
        title = title.replace(workspace_without_root + os.sep, "workspace/")

        if not title:
            friendly_tools = {
                "bash": "Running a command",
                "shell": "Running a command",
                "write": "Writing a file",
                "edit": "Editing a file",
                "patch": "Applying a code change",
                "read": "Reading project files",
                "glob": "Finding project files",
                "grep": "Searching project files",
                "task": "Running a delegated coding step",
            }
            title = friendly_tools.get(tool_name.lower(), f"Running {tool_name}")

        return title

    @classmethod
    def _tool_progress_message(cls, tool_name: str, state: dict[str, Any]) -> str:
        title = cls._tool_progress_title(tool_name, state)
        status = state.get("status", "running")
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        if status == "completed":
            detail = re.sub(r"^Running command: ", "Command: ", title)
            if metadata.get("status") == "running":
                return f"OpenCode: Command running in background — {detail}"
            exit_code = metadata.get("exit")
            if isinstance(exit_code, (int, float)) and exit_code != 0:
                return f"OpenCode command exited with status {exit_code:g} — task continues: {detail}"
            return f"OpenCode step complete — continuing: {detail}"
        if status == "error":
            error = cls._clean_progress_text(state.get("error"), max_chars=180)
            suffix = f": {error}" if error else ""
            return f"OpenCode hit an issue in {tool_name}{suffix}"
        return f"OpenCode: {title}"

    @classmethod
    def _normalize_progress_event(
        cls,
        event: dict[str, Any],
        session_id: str,
        tool_context: dict[tuple[str, str, str], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Convert raw OpenCode events into safe, useful Jarvis progress phases."""
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("type"):
            event = payload

        event_type = event.get("type")
        properties = event.get("data", event.get("properties"))
        if not isinstance(properties, dict):
            properties = {}

        event_session_id = cls._event_session_id(event)
        if event_session_id and event_session_id != session_id:
            return None
        if not event_session_id and event_type not in {"server.connected"}:
            return None

        base: dict[str, Any] = {
            "session_id": session_id,
            "event_type": event_type,
        }

        if event_type in {
            "session.tool.input.started",
            "session.tool.called",
            "session.tool.progress",
            "session.tool.success",
            "session.tool.failed",
        }:
            call_id = properties.get("id")
            assistant_id = properties.get("assistantMessageID")
            key = (session_id, str(assistant_id or ""), str(call_id or ""))
            cached = tool_context.get(key, {}) if tool_context is not None and call_id else {}
            name = cls._clean_progress_text(properties.get("name"), 60) or cached.get("name") or "coding step"
            status = {
                "session.tool.input.started": "pending",
                "session.tool.called": "running",
                "session.tool.progress": "running",
                "session.tool.success": "completed",
                "session.tool.failed": "error",
            }[event_type]
            state = {
                "status": status,
                "input": properties.get("input", {}),
                "error": cls._error_message(properties["error"]) if properties.get("error") else "",
            }
            if not properties.get("input") and cached.get("title"):
                state["title"] = cached["title"]
            metadata = properties.get("metadata")
            safe_metadata = {}
            if isinstance(metadata, dict):
                if metadata.get("status") in {"running", "completed"}:
                    safe_metadata["status"] = metadata["status"]
                if isinstance(metadata.get("exit"), (int, float)):
                    safe_metadata["exit"] = metadata["exit"]
            state["metadata"] = safe_metadata
            if tool_context is not None and call_id:
                tool_context[key] = {"name": name, "title": cls._tool_progress_title(name, state)}
                while len(tool_context) > cls.MAX_PROGRESS_TOOL_CONTEXT:
                    tool_context.pop(next(iter(tool_context)))
            return {
                **base,
                "phase": "tool",
                "status": cls._tool_progress_message(name, state),
                "opencode_tool": name,
                "tool_status": "running" if status == "completed" and safe_metadata.get("status") == "running" else status,
                "call_id": call_id,
                "assistant_message_id": assistant_id,
            }

        if event_type == "session.retry.scheduled":
            return {
                **base,
                "phase": "retry",
                "status": f"OpenCode is retrying provider work (attempt {properties.get('attempt', 1)}): {cls._error_message(properties.get('error'))}",
            }

        if event_type == "session.execution.started":
            return {
                **base,
                "phase": "running",
                "status": "OpenCode is actively working on the task",
            }

        if event_type in {"session.execution.failed", "session.execution.interrupted"}:
            detail = cls._error_message(
                properties.get("error") or properties.get("reason") or "execution failed"
            )
            return {
                **base,
                "phase": "error",
                "status": f"OpenCode stopped with an issue: {detail}",
                "terminal": True,
            }

        if event_type == "form.created":
            form = properties.get("form") or {}
            detail = cls._clean_progress_text(form.get("title"), 180)
            suffix = f": {detail}" if detail else ""
            return {
                **base,
                "phase": "blocked",
                "status": f"OpenCode needs an answer before it can continue{suffix}",
                "terminal": True,
            }

        if event_type == "message.part.updated":
            part = properties.get("part")
            if not isinstance(part, dict):
                return None
            part_type = part.get("type")
            if part_type == "tool":
                state = part.get("state")
                if not isinstance(state, dict):
                    return None
                tool_status = state.get("status")
                if tool_status not in {"pending", "streaming", "running", "completed", "error"}:
                    return None
                opencode_tool = cls._clean_progress_text(part.get("tool"), 60) or "tool"
                call_id = part.get("id")
                assistant_id = properties.get("assistantMessageID")
                if tool_context is not None and call_id:
                    key = (session_id, str(assistant_id or ""), str(call_id))
                    tool_context[key] = {"name": opencode_tool, "title": cls._tool_progress_title(opencode_tool, state)}
                    while len(tool_context) > cls.MAX_PROGRESS_TOOL_CONTEXT:
                        tool_context.pop(next(iter(tool_context)))
                return {
                    **base,
                    "phase": "tool",
                    "status": cls._tool_progress_message(opencode_tool, state),
                    "opencode_tool": opencode_tool,
                    "tool_status": "running" if tool_status == "completed" and isinstance(state.get("metadata"), dict) and state["metadata"].get("status") == "running" else tool_status,
                    "call_id": call_id,
                    "assistant_message_id": assistant_id,
                }
            if part_type == "retry":
                attempt = int(part.get("attempt") or 0) + 1
                error = cls._error_message(part.get("error"))
                return {
                    **base,
                    "phase": "retry",
                    "status": f"OpenCode is retrying provider work (attempt {attempt}): {error}",
                }
            return None

        if event_type == "session.next.tool.called":
            opencode_tool = cls._clean_progress_text(properties.get("tool"), 60) or "tool"
            state = {
                "status": "running",
                "input": properties.get("input")
                if isinstance(properties.get("input"), dict)
                else {},
            }
            return {
                **base,
                "phase": "tool",
                "status": cls._tool_progress_message(opencode_tool, state),
                "opencode_tool": opencode_tool,
                "tool_status": "running",
            }

        if event_type == "session.next.tool.failed":
            error = cls._error_message(properties.get("error"))
            return {
                **base,
                "phase": "tool",
                "status": f"OpenCode hit an issue in a coding step: {error}",
                "tool_status": "error",
            }

        if event_type == "session.next.tool.progress":
            return {
                **base,
                "phase": "tool",
                "status": "OpenCode is making progress on a coding step",
                "tool_status": "running",
            }

        if event_type == "session.next.tool.success":
            return {
                **base,
                "phase": "tool",
                "status": "OpenCode step complete — continuing",
                "tool_status": "completed",
            }

        if event_type == "todo.updated":
            todos = properties.get("todos")
            if not isinstance(todos, list) or not todos:
                return None
            active = next(
                (
                    todo
                    for todo in todos
                    if isinstance(todo, dict) and todo.get("status") == "in_progress"
                ),
                None,
            )
            completed = sum(
                1 for todo in todos if isinstance(todo, dict) and todo.get("status") == "completed"
            )
            total = sum(1 for todo in todos if isinstance(todo, dict))
            progress = int((completed / total) * 100) if total else None
            if active:
                detail = cls._clean_progress_text(active.get("content"), 180)
                status = f"OpenCode is working on: {detail}"
            else:
                status = f"OpenCode completed {completed} of {total} planned steps"
            return {
                **base,
                "phase": "todo",
                "status": status,
                "progress": progress,
                "completed_steps": completed,
                "total_steps": total,
            }

        if event_type == "session.status":
            status_info = properties.get("status")
            if not isinstance(status_info, dict):
                return None
            status_type = status_info.get("type")
            if status_type == "retry":
                attempt = int(status_info.get("attempt") or 0) + 1
                detail = cls._clean_progress_text(status_info.get("message"), 180)
                suffix = f": {detail}" if detail else ""
                return {
                    **base,
                    "phase": "retry",
                    "status": f"OpenCode is retrying (attempt {attempt}){suffix}",
                }
            if status_type == "busy":
                return {
                    **base,
                    "phase": "running",
                    "status": "OpenCode is actively working on the task",
                }
            return None

        if event_type in {
            "permission.asked",
            "permission.v2.asked",
        }:
            permission = cls._clean_progress_text(
                properties.get("permission") or properties.get("action") or properties.get("type"),
                100,
            )
            suffix = f" for {permission}" if permission else ""
            return {
                **base,
                "phase": "blocked",
                "status": f"OpenCode is blocked waiting for permission{suffix}",
                "terminal": True,
            }

        if event_type in {
            "question.asked",
            "question.v2.asked",
        }:
            questions = properties.get("questions")
            question = ""
            if isinstance(questions, list) and questions and isinstance(questions[0], dict):
                question = cls._clean_progress_text(questions[0].get("question"), 180)
            suffix = f": {question}" if question else ""
            return {
                **base,
                "phase": "blocked",
                "status": f"OpenCode needs an answer before it can continue{suffix}",
                "terminal": True,
            }

        if event_type == "session.error":
            error = cls._error_message(properties.get("error"))
            return {
                **base,
                "phase": "error",
                "status": f"OpenCode stopped with an issue: {error}",
                "terminal": True,
            }

        if event_type == "session.idle":
            return {
                **base,
                "phase": "finishing",
                "status": "OpenCode is preparing the task result",
            }

        return None

    @classmethod
    def _heartbeat_status(
        cls,
        last_substantive_progress: dict[str, Any] | None,
        elapsed_seconds: float,
    ) -> str:
        """Build a bounded heartbeat from the last real phase, never another heartbeat."""
        elapsed = max(0, int(elapsed_seconds))
        minutes, seconds = divmod(elapsed, 60)
        elapsed_text = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"

        if last_substantive_progress and last_substantive_progress.get("tool_status") in {"completed", "error"}:
            return f"OpenCode is working on the next step ({elapsed_text} elapsed)"

        detail = ""
        if (
            last_substantive_progress
            and last_substantive_progress.get("event_type") != "jarvis.heartbeat"
            and last_substantive_progress.get("status")
        ):
            detail = cls._clean_progress_text(
                last_substantive_progress["status"],
                max_chars=120,
            )
            detail = re.sub(r"^OpenCode(?:\s+is|:)?\s*", "", detail).strip()
        suffix = f" — {detail}" if detail else ""
        return f"OpenCode is still active ({elapsed_text} elapsed){suffix}"

    @staticmethod
    def _has_usable_final_response(result: Any) -> bool:
        """Return whether the final POST contains authoritative assistant text."""
        if not isinstance(result, dict) or result.get("error"):
            return False
        info = result.get("info")
        if isinstance(info, dict) and info.get("error"):
            return False

        def contains_public_text(payload: Any) -> bool:
            if isinstance(payload, str):
                return bool(payload.strip())
            if isinstance(payload, list):
                return any(contains_public_text(item) for item in payload)
            if not isinstance(payload, dict):
                return False
            if payload.get("type") in {"reasoning", "step-start", "step-finish"}:
                return False
            if isinstance(payload.get("text"), str) and payload["text"].strip():
                return True
            return any(
                contains_public_text(payload.get(key))
                for key in ("parts", "content")
                if key in payload
            )

        return contains_public_text(result.get("parts")) or contains_public_text(
            result.get("content")
        )

    def _poll_session_progress(
        self,
        session_id: str,
        tool_context: dict[tuple[str, str, str], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Recover tool progress and persisted blockers after missed SSE events."""
        try:
            path = f"/api/session/{quote(session_id, safe='')}"
            for suffix, message in (
                ("permission", "OpenCode is blocked waiting for permission"),
                ("form", "OpenCode needs an answer before it can continue"),
            ):
                response = self._get(f"{path}/{suffix}", timeout=3)
                response.raise_for_status()
                if self._response_data(response, list):
                    return {
                        "session_id": session_id,
                        "event_type": f"jarvis.poll.{suffix}",
                        "phase": "blocked",
                        "status": message,
                        "terminal": True,
                        "source": "poll",
                    }
            for message in self.get_messages(session_id):
                if message.get("type") == "idle":
                    break
                for part in reversed(message.get("content", [])):
                    if part.get("type") != "tool":
                        continue
                    progress = self._normalize_progress_event(
                        {
                            "type": "message.part.updated",
                            "properties": {
                                "sessionID": session_id,
                                "assistantMessageID": message.get("id"),
                                "part": {**part, "tool": part.get("name")},
                            },
                        },
                        session_id,
                        tool_context=tool_context,
                    )
                    if progress:
                        progress["source"] = "poll"
                        return progress
        except (requests.RequestException, ValueError, RuntimeError):
            return None
        return None

    def _send_message_with_progress(
        self,
        *,
        session_id: str,
        message: str,
        provider_id: str,
        model_id: str,
        progress_callback: Callable[[dict[str, Any]], None],
    ) -> tuple[dict[str, Any], str]:
        """Run the final prompt while supervising it through SSE and polling."""
        event_queue: queue.Queue = queue.Queue()
        stop_event = threading.Event()
        ready_event = threading.Event()
        stream_thread = threading.Thread(
            target=self._stream_events,
            args=(event_queue, stop_event, ready_event),
            daemon=True,
            name=f"opencode-events-{session_id[-8:]}",
        )
        stream_thread.start()
        ready_event.wait(timeout=2)

        last_signature: tuple[Any, ...] | None = None
        last_substantive_progress: dict[str, Any] | None = None
        last_progress_at = time.monotonic()
        request_started_at = last_progress_at
        last_poll_at = 0.0
        last_heartbeat_at = 0.0
        stream_healthy = False
        sse_connected = False
        poll_used = False
        terminal_issue: str | None = None
        abort_requested = False
        busy_emitted = False
        tool_context: dict[tuple[str, str, str], dict[str, Any]] = {}
        seen_tool_progress: dict[tuple[str, str], tuple[Any, ...]] = {}

        def publish(progress: dict[str, Any]) -> None:
            nonlocal last_signature, last_substantive_progress, last_progress_at, busy_emitted
            if (
                progress.get("event_type") == "session.status"
                and progress.get("phase") == "running"
            ):
                if busy_emitted:
                    return
                busy_emitted = True
            signature = (
                progress.get("phase"),
                progress.get("status"),
                progress.get("tool_status"),
                progress.get("progress"),
                progress.get("call_id"),
                progress.get("assistant_message_id"),
            )
            if progress.get("phase") == "tool" and progress.get("call_id"):
                key = (str(progress.get("assistant_message_id") or ""), str(progress["call_id"]))
                previous = seen_tool_progress.get(key)
                if previous == signature:
                    return
                if previous and previous[2] in {"completed", "error"} and progress.get("tool_status") not in {"completed", "error"}:
                    return
                seen_tool_progress[key] = signature
                while len(seen_tool_progress) > self.MAX_PROGRESS_TOOL_CONTEXT:
                    seen_tool_progress.pop(next(iter(seen_tool_progress)))
            if signature == last_signature:
                return
            last_signature = signature
            if progress.get("event_type") != "jarvis.heartbeat":
                last_substantive_progress = progress
            last_progress_at = time.monotonic()
            progress_callback(progress)

        request_done = threading.Event()
        request_result: dict[str, Any] = {}

        def send_final_message() -> None:
            try:
                request_result["value"] = self.send_message(
                    session_id,
                    message,
                    provider_id,
                    model_id,
                )
            except Exception as exc:
                request_result["error"] = exc
            finally:
                request_done.set()

        request_thread = threading.Thread(
            target=send_final_message,
            daemon=True,
            name=f"opencode-request-{session_id[-8:]}",
        )
        request_thread.start()

        try:
            while not request_done.is_set():
                try:
                    raw_event = event_queue.get(timeout=0.5)
                except queue.Empty:
                    raw_event = None

                # The final POST is authoritative. If it completed while this
                # queue read was waiting, classify the event in the post-response
                # drain instead of aborting a response that is already available.
                if request_done.is_set():
                    if raw_event is not None:
                        event_queue.put(raw_event)
                    break

                if isinstance(raw_event, dict) and raw_event.get("_monitor_error"):
                    stream_healthy = False
                elif isinstance(raw_event, dict) and raw_event.get("_monitor_connected"):
                    stream_healthy = True
                    sse_connected = True
                elif isinstance(raw_event, dict):
                    stream_healthy = True
                    sse_connected = True
                    progress = self._normalize_progress_event(raw_event, session_id, tool_context=tool_context)
                    if progress:
                        publish(progress)
                        if progress.get("terminal") and not terminal_issue:
                            terminal_issue = progress.get("status") or "OpenCode stopped"

                now = time.monotonic()
                poll_interval = (
                    self.DEGRADED_POLL_INTERVAL_SECONDS
                    if not stream_healthy
                    else self.HEALTHY_POLL_INTERVAL_SECONDS
                )
                poll_needed = not stream_healthy or now - last_progress_at >= poll_interval
                if poll_needed and now - last_poll_at >= poll_interval:
                    last_poll_at = now
                    polled = self._poll_session_progress(session_id, tool_context=tool_context)
                    if polled:
                        poll_used = True
                        publish(polled)
                        if polled.get("terminal") and not terminal_issue:
                            terminal_issue = polled.get("status") or "OpenCode stopped"

                if (
                    now - last_progress_at >= self.HEARTBEAT_INTERVAL_SECONDS
                    and now - last_heartbeat_at >= self.HEARTBEAT_INTERVAL_SECONDS
                ):
                    last_heartbeat_at = now
                    publish(
                        {
                            "session_id": session_id,
                            "event_type": "jarvis.heartbeat",
                            "phase": "heartbeat",
                            "status": self._heartbeat_status(
                                last_substantive_progress,
                                now - request_started_at,
                            ),
                        }
                    )

                if terminal_issue and not abort_requested:
                    abort_requested = True
                    self.abort_session(session_id)
                    raise RuntimeError(terminal_issue)
                if now - request_started_at >= self.task_timeout:
                    raise TimeoutError("OpenCode task deadline reached")

            if "error" in request_result:
                raise request_result["error"]
            result = request_result["value"]
            has_usable_final = self._has_usable_final_response(result)

            # Drain events already received before the blocking response completed.
            while True:
                try:
                    raw_event = event_queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(raw_event, dict) and not raw_event.get("_monitor_error"):
                    progress = self._normalize_progress_event(raw_event, session_id, tool_context=tool_context)
                    if progress:
                        if progress.get("terminal") and has_usable_final:
                            continue
                        publish(progress)
                        if progress.get("terminal") and not terminal_issue:
                            terminal_issue = progress.get("status") or "OpenCode stopped"

            if terminal_issue:
                raise RuntimeError(terminal_issue)
            if sse_connected and poll_used:
                progress_transport = "sse+poll"
            elif sse_connected:
                progress_transport = "sse"
            elif poll_used:
                progress_transport = "poll"
            else:
                progress_transport = "none"
            return result, progress_transport
        finally:
            stop_event.set()
            stream_thread.join(timeout=1)

    def execute_task(
        self,
        task: str,
        session_id: str | None = None,
        model: dict[str, str] | None = None,
        context: dict[str, Any] | None = None,
        agent_mode: str = "build",  # "build" or "plan"
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Execute a task via OpenCode."""
        start_time = time.time()
        task_type = context.get("task_type", "general") if context else "general"
        progress_events: list[dict[str, Any]] = []
        progress_sequence = 0

        def report_progress(progress: dict[str, Any]) -> None:
            nonlocal progress_sequence
            if not progress_callback:
                return
            progress_sequence += 1
            event = dict(progress)
            event.setdefault("session_id", session_id)
            event["sequence"] = progress_sequence
            event["elapsed_ms"] = int((time.time() - start_time) * 1000)
            if len(progress_events) >= 25:
                progress_events.pop(0)
            progress_events.append(event)
            try:
                self.logger.log_progress(str(session_id or "unknown"), event)
            except Exception:
                pass
            try:
                progress_callback(event)
            except Exception:
                pass
        
        try:
            # Create or use existing session
            if session_id is None:
                session = self.create_session(
                    title=f"Jarvis: {task[:50]}",
                    agent_mode=agent_mode,
                )
                session_id = session.get("id") or session.get("sessionId")
                if not session_id:
                    raise Exception("Failed to get session ID")
            self.active_session_id = session_id

            report_progress(
                {
                    "phase": "session",
                    "status": "OpenCode session is ready",
                    "event_type": "jarvis.session.ready",
                }
            )
            
            # Log session start
            self.logger.log_session_start(
                session_id=session_id,
                task=task,
                task_type=task_type,
                model=model,
                context=context
            )

            _ws = get_jarvis_workspace().resolve()
            _repo = get_project_root().resolve()
            _ws_str = str(_ws)
            _repo_str = str(_repo)
            _proj_str = str(_ws / "projects")
            _temp_str = str(_ws / "temp")
            _dep_str = str(_ws / "deployments")

            # Inject system prompt explaining Jarvis integration (paths from lib.paths — portable across users)
            system_prompt = f"""# You are OpenCode - A specialized coding agent called by Jarvis

## Your Identity
- **Name**: OpenCode (always use "OpenCode" when referring to yourself, never "Claude" or "Claude Code")
- **Role**: Autonomous coding agent specialized in software development
- **Context**: You're being called by Jarvis, a voice-controlled AI assistant

## Your Role
You are executing tasks on behalf of Jarvis. The user spoke to Jarvis via voice, and Jarvis determined this task requires your specialized coding capabilities.

**IMPORTANT**: You are responding to Jarvis (a powerful LLM), NOT directly to the user. Jarvis will translate your response into natural language for voice output.

## Execution Environment
- OpenCode runs on its service host, which may differ from the Jarvis host or the user's browser machine.
- Inspect the operating system, distribution, and available tools on that host; do not assume another machine's environment applies.
- Treat execution as headless unless the task explicitly provides a graphical display.
- For GUI projects, create the code and run headless compilation, import checks, or self-tests. Explain that a graphical run belongs on a machine with a display.

## Response Style
- **Skip lengthy introductions** unless specifically asked "what can you do?"
- **Get straight to work** on the task at hand
- **Focus on deliverables** (code, files, analysis) rather than explaining who you are

## Response Format Guidelines
- **Be detailed and technical**: Jarvis needs full context to understand what happened
- **Include all relevant information**: URLs, file paths, error details, technical specifics
- **Use technical jargon freely**: Jarvis understands technical terms and will translate appropriately
- **Provide complete context**: What was done, how it was done, what files were created/modified, any errors encountered
- **Include actionable details**: File paths, URLs, command outputs, error messages - Jarvis will decide what to tell the user
- **Be thorough**: Better to give too much detail than too little - Jarvis can condense

## Workspace & Boundaries - CRITICAL

**ABSOLUTE RULES - DO NOT VIOLATE:**

1. **NEVER create, modify, or delete files in `{_repo_str}`**
   - This is Jarvis's codebase - READ ONLY
   - If asked to modify Jarvis code, refuse and explain it's protected

2. **ALL file writes MUST be in `{_ws_str}`**
   - Your workspace root: `{_ws_str}`
   - Projects: `{_proj_str}/`
   - Temp files: `{_temp_str}/`
   - Deployments: `{_dep_str}/`
   - Do not use `/tmp`; use `{_temp_str}/` for scratch files, temporary scripts, test artifacts, and command output.

3. **Source files outside the workspace may be read when needed for the task.**
   - Keep those sources read-only, including the Jarvis checkout.
   - If asked to modify files outside the workspace, refuse and suggest a workspace copy.
   - The native systemd service limits host writes for shell commands and Code Mode too.
   - OpenCode's required data/state directories and private temporary storage are shared writable exceptions, not project output locations. Do not modify them directly.

**Working directory will be specified in context**

## Error Handling
- Provide full technical error details: stack traces, error codes, specific failure points
- Include diagnostic information: What was attempted, what failed, why it failed
- Suggest technical solutions: Jarvis will translate these into user-friendly language

## Context
You will receive additional context about the task, workspace, and user preferences in the next message.

Remember: Your response goes to Jarvis, who will intelligently format it for voice output to the user. Be thorough and technical!
"""
            # Log system prompt
            self.logger.log_message_sent(
                session_id=session_id,
                message=system_prompt,
                message_type="system",
                no_reply=True
            )
            self.send_message(
                session_id=session_id, message=system_prompt, no_reply=True
            )

            # Inject context if provided, always include workspace path
            if context is None:
                context = {}
            
            # Always specify workspace
            if "workspace" not in context:
                context["workspace"] = _ws_str
            
            context_text = f"""# Jarvis Context

## Workspace
Your workspace root: `{_ws_str}`

Keep all created or modified files within this directory. Source files elsewhere,
including `{_repo_str}`, are read-only and may be inspected when relevant to the task.

## Task Context
{json.dumps(context, indent=2)}"""
            
            # Log context injection
            self.logger.log_message_sent(
                session_id=session_id,
                message=context_text,
                message_type="context",
                no_reply=True
            )
            self.send_message(
                session_id=session_id, message=context_text, no_reply=True
            )

            # Default model from config
            if model is None:
                model = {
                    "providerID": self.default_provider_id,
                    "modelID": self.default_model_id,
                }

            # Log task message
            self.logger.log_message_sent(
                session_id=session_id,
                message=task,
                message_type="task",
                no_reply=False
            )
            
            # Execute task
            msg_start_time = time.time()
            report_progress(
                {
                    "phase": "starting",
                    "status": "OpenCode received the task and is starting work",
                    "event_type": "jarvis.task.started",
                }
            )
            progress_transport = None
            # Supervise even when a caller does not display progress, so an
            # unattended permission/form request never becomes a hidden stall.
            result, progress_transport = self._send_message_with_progress(
                session_id=session_id,
                message=task,
                provider_id=model["providerID"],
                model_id=model["modelID"],
                progress_callback=report_progress,
            )
            msg_duration = (time.time() - msg_start_time) * 1000
            
            # Log response
            self.logger.log_message_received(
                session_id=session_id,
                response=result,
                duration_ms=msg_duration
            )
            
            # Log session completion
            total_duration = (time.time() - start_time) * 1000
            self.logger.log_session_complete(
                session_id=session_id,
                success=True,
                result_summary=f"Task completed in {total_duration:.0f}ms"
            )

            report_progress(
                {
                    "phase": "complete",
                    "status": "OpenCode completed the task and returned its result",
                    "event_type": "jarvis.task.completed",
                    "progress": 100,
                }
            )

            return {
                "ok": True,
                "session_id": session_id,
                "result": result,
                "progress_events": progress_events,
                "progress_transport": progress_transport,
            }
        except Exception as e:
            if (
                session_id
                and session_id not in self._cancelled_sessions
                and (
                    isinstance(e, (requests.RequestException, TimeoutError))
                    or self._pending_input_ids.get(session_id)
                )
            ):
                # An HTTP failure can occur after the server accepted work.
                # Reconcile owned input IDs instead of leaving paid work alive.
                self.abort_session(session_id)
            report_progress(
                {
                    "phase": "error",
                    "status": f"OpenCode stopped with an issue: {self._clean_progress_text(str(e), 180)}",
                    "event_type": "jarvis.task.error",
                }
            )
            # Log error
            self.logger.log_error(
                session_id=session_id,
                error_type=type(e).__name__,
                error_message=str(e),
                context={"task": task, "task_type": task_type}
            )
            self.logger.log_session_complete(
                session_id=session_id if session_id else "unknown",
                success=False,
                error=str(e)
            )
            return {
                "ok": False,
                "session_id": session_id,
                "error": str(e),
                "progress_events": progress_events,
            }

    def get_providers(self) -> dict[str, Any]:
        """Get available LLM providers and models."""
        response = self._get("/api/provider")
        response.raise_for_status()
        return {"providers": self._response_data(response, list)}

    def abort_session(self, session_id: str) -> bool:
        """Abort a running session."""
        if not hasattr(self, "_cancelled_sessions"):
            self._cancelled_sessions = set()
        self._cancelled_sessions.add(session_id)
        try:
            path = f"/api/session/{quote(session_id, safe='')}"
            # Interrupt with resume=false so pending work is not automatically
            # restarted. Remove our own queued input if it was never delivered.
            response = self._post(f"{path}/interrupt?resume=false", timeout=5)
            response.raise_for_status()
            for input_id in self._pending_input_ids.pop(session_id, []):
                response = requests.delete(
                    f"{self.base_url}{path}/inbox/{quote(input_id, safe='')}",
                    **self._request_kwargs(5),
                )
                if response.status_code != 404:
                    response.raise_for_status()
            return True
        except Exception as e:
            print(f"Failed to abort session: {e}", file=sys.stderr)
            return False


def get_client() -> OpenCodeClient:
    """Get singleton OpenCode client instance."""
    return OpenCodeClient()


if __name__ == "__main__":
    # Test the client
    print("Testing OpenCode Client...")
    client = OpenCodeClient()
    health = client.health_check()
    print(f"Health: {json.dumps(health, indent=2)}")

    if health["healthy"]:
        sessions = client.list_sessions()
        print(f"Active sessions: {len(sessions)}")
        providers = client.get_providers()
        print(f"Providers: {json.dumps(providers, indent=2)}")
