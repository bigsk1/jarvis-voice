"""Add machine authentication to upstream's legacy, single-account HTTP mode."""

import asyncio
import hmac
import logging
import math
import os
import runpy
import time
from contextvars import ContextVar
from pathlib import Path
from threading import Event

BACKGROUND_EXECUTION_META = "jarvis/background_execution"


class _AppsScriptBudget:
    """Evidence belongs to one authenticated MCP call, including its HTTP threads."""

    def __init__(self, job_id, deadline, *, deadline_unix=None, allow_middleware_reentry=True):
        self.job_id = job_id
        self.background = job_id is not None
        self.deadline = deadline
        self.deadline_unix = deadline_unix
        self.allow_middleware_reentry = allow_middleware_reentry
        self.middleware_reentry_claimed = False
        self.script_submitted = False
        self.completion = "rejected"
        self.script_ok = False
        self.cancelled = Event()

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if self.cancelled.is_set() or remaining <= 0:
            raise TimeoutError("Apps Script observation deadline exceeded")
        return remaining


_script_execution_budget: ContextVar[_AppsScriptBudget | None] = ContextVar(
    "jarvis_google_script_execution_budget", default=None,
)


def configure_background_execution(SecureFastMCP, *, auth_session_factory=None):
    """Bound Apps Script calls and expose actual background provider settlement.

    The pinned server returns ordinary text even for script or socket errors. A
    successful MCP envelope therefore cannot establish that remote work stopped.
    Observe the reviewed Google HTTP boundary, without guessing from that text.
    """
    import google_auth_httplib2
    import httplib2
    from fastmcp.server.dependencies import fastmcp_request_ctx
    from fastmcp.tools.base import ToolResult
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.auth.transport.requests import _Response as GoogleAuthResponse
    from google.oauth2 import _client as oauth_client
    from googleapiclient.errors import HttpError
    from googleapiclient.http import HttpRequest

    try:
        from jarvis_http_observation import SocketBudget
    except ModuleNotFoundError:
        from lib.http_observation import SocketBudget

    original_call = SecureFastMCP.call_tool
    original_execute = HttpRequest.execute
    original_auth_request = GoogleAuthRequest.__call__
    original_token_request = oauth_client._token_endpoint_request_no_throw
    default_auth_timeout = object()

    def auth_request(self, url, method="GET", body=None, headers=None, timeout=default_auth_timeout, **kwargs):
        budget = _script_execution_budget.get()
        default_timeout = timeout is default_auth_timeout
        timeout = 120 if default_timeout else timeout
        if budget is None:
            return original_auth_request(self, url, method=method, body=body, headers=headers,
                                         timeout=timeout, **kwargs)
        remaining = budget.remaining()
        if default_timeout and not budget.background:
            timeout = remaining
        connect, read = timeout if isinstance(timeout, tuple) else (timeout, timeout)
        timeout = tuple(remaining if part is None else min(part, remaining)
                        for part in (connect, read))
        with SocketBudget(budget.deadline, budget.cancelled, clock=lambda: time.monotonic()) as observer:
            kwargs["allow_redirects"] = False
            response = observer.request(method, url, source_session=self.session,
                                        session_factory=auth_session_factory, data=body,
                                        headers=headers, timeout=timeout, **kwargs)
            try:
                # Materialize the token body while the socket observation is
                # still owned. Google's response adapter otherwise reads lazily.
                response.content
                budget.remaining()
                return GoogleAuthResponse(response)
            finally:
                response.close()

    def token_request(request, token_uri, body, access_token=None, use_json=False,
                      can_retry=True, headers=None, **kwargs):
        budget = _script_execution_budget.get()
        if budget is not None:
            budget.remaining()
            can_retry = False
        return original_token_request(request, token_uri, body, access_token=access_token,
                                      use_json=use_json, can_retry=can_retry, headers=headers,
                                      **kwargs)

    GoogleAuthRequest.__call__ = auth_request
    oauth_client._token_endpoint_request_no_throw = token_request

    class OneShotHttp(httplib2.Http):
        """Retain httplib2 TLS/proxy setup without its implicit POST replay loop."""

        def _conn_request(self, conn, request_uri, method, body, headers):
            budget = _script_execution_budget.get()
            if budget is None:
                raise RuntimeError("A one-shot Google transport requires an execution budget")
            budget.remaining()
            if conn.sock is None:
                conn.connect()
            # Connection setup cannot spend the deadline then dispatch a write.
            remaining = budget.remaining()
            if conn.sock is not None:
                self._observer.track_socket(conn.sock)
                conn.sock.settimeout(remaining)
            conn.request(method, request_uri, body, headers)
            response = conn.getresponse()
            content = b""
            if method == "HEAD":
                conn.close()
            else:
                content = response.read()
            response = httplib2.Response(response)
            if method != "HEAD":
                content = httplib2._decompressContent(response, content, self.limit_kwargs)
            return response, content

    def execute(self, http=None, num_retries=0):
        budget = _script_execution_budget.get()
        if budget is None:
            return original_execute(self, http=http, num_retries=num_retries)
        remaining = budget.remaining()
        original_http = http or self.http
        # A fresh transport leaves the shared Google connection pool, existing
        # sockets, and simultaneous foreground calls at their original timeout.
        observer = SocketBudget(budget.deadline, budget.cancelled, clock=lambda: time.monotonic())
        transport = OneShotHttp(timeout=remaining)
        transport._observer = observer
        transport.follow_redirects = False
        try:
            isolated_http = google_auth_httplib2.AuthorizedHttp(
                original_http.credentials, http=transport, max_refresh_attempts=0,
            )
            is_script_run = self.methodId == "script.scripts.run"
            if is_script_run:
                if budget.script_submitted:
                    raise RuntimeError("An Apps Script execution cannot be automatically replayed")
                budget.script_submitted = True
                budget.completion = "unknown"
            try:
                response = original_execute(self, http=isolated_http, num_retries=0)
            except HttpError as exc:
                if is_script_run and exc.resp.status in {400, 401, 403, 404, 429}:
                    budget.completion = "rejected"
                raise
            if is_script_run and isinstance(response, dict) and (
                "response" in response or "error" in response
            ):
                budget.completion = "completed"
                budget.script_ok = "error" not in response
            return response
        finally:
            observer.close()
            transport.close()

    HttpRequest.execute = execute

    async def call_tool(self, name, arguments, *args, **kwargs):
        existing_budget = _script_execution_budget.get()
        request_context = fastmcp_request_ctx.get()
        metadata = request_context.meta if request_context is not None else None
        background = isinstance(metadata, dict) and BACKGROUND_EXECUTION_META in metadata
        requested = metadata[BACKGROUND_EXECUTION_META] if background else None
        job_id = requested.get("job_id") if isinstance(requested, dict) else None
        deadline_unix = requested.get("deadline_unix") if isinstance(requested, dict) else None

        def rejected(message):
            evidence = {BACKGROUND_EXECUTION_META: {
                "version": 1, "job_id": job_id if isinstance(job_id, str) else "",
                "completion": "rejected",
            }} if background and (existing_budget is None or existing_budget.background) else None
            return ToolResult(content=message, is_error=True, meta=evidence)

        if not background:
            if existing_budget is not None and existing_budget.background:
                return rejected("Nested background calls must retain their execution context")
            if name != "run_script_function":
                if existing_budget is not None:
                    return rejected("Nested Apps Script calls cannot change execution authority")
                return await original_call(self, name, arguments, *args, **kwargs)
            # Foreground scripts use the same finite transport scope, without a
            # durable job identity or any background acknowledgement metadata.
            deadline_unix = (existing_budget.deadline_unix if existing_budget is not None
                             else time.time() + 390)
        elif name != "run_script_function":
            return rejected("Background execution is not registered for this Google tool")
        elif (not isinstance(requested, dict) or requested.get("version") != 1
                or not isinstance(job_id, str) or not job_id.strip() or len(job_id) > 256
                or isinstance(deadline_unix, bool) or not isinstance(deadline_unix, (int, float))
                or not math.isfinite(deadline_unix) or deadline_unix <= time.time()):
            return rejected("Invalid or expired background Apps Script observation budget")
        if existing_budget is not None:
            # FastMCP 4.1.4 dispatches middleware by re-entering this same method
            # with run_middleware=False. Keep one budget and one provider receipt
            # across that framework boundary; a second budget loses its evidence.
            if (kwargs.get("run_middleware") is not False
                    or not existing_budget.allow_middleware_reentry
                    or existing_budget.middleware_reentry_claimed
                    or existing_budget.background is not background
                    or existing_budget.job_id != job_id
                    or existing_budget.deadline_unix != deadline_unix):
                return rejected("Nested background calls cannot change or reuse execution authority")
            existing_budget.remaining()
            existing_budget.middleware_reentry_claimed = True
            return await original_call(self, name, arguments, *args, **kwargs)
        # Google limits execution to six minutes. The bounded extra margin covers
        # deployment discovery and transport overhead, without extending that limit.
        budget = _AppsScriptBudget(
            job_id, time.monotonic() + min(390, deadline_unix - time.time()),
            deadline_unix=deadline_unix,
            allow_middleware_reentry=kwargs.get("run_middleware", True) is True,
        )
        token = _script_execution_budget.set(budget)
        try:
            try:
                async with asyncio.timeout(budget.remaining()):
                    result = await original_call(self, name, arguments, *args, **kwargs)
            except Exception as exc:
                detail = str(exc)[:16000] or type(exc).__name__
                result = ToolResult(content=f"Apps Script observation failed: {detail}", is_error=True)
            if background:
                result.meta = {**(result.meta or {}), BACKGROUND_EXECUTION_META: {
                    "version": 1, "job_id": job_id, "completion": budget.completion,
                }}
            if not budget.script_ok or budget.completion != "completed":
                result.is_error = True
            return result
        finally:
            budget.cancelled.set()
            _script_execution_budget.reset(token)

    SecureFastMCP.call_tool = call_tool


class ServiceTokenMiddleware:
    """Keep streaming intact; only the OAuth callback and health probe are public."""

    def __init__(self, app, token):
        if len(token) < 32:
            raise ValueError("A private MCP service token of at least 32 characters is required")
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        public = scope.get("method") == "GET" and scope.get("path") in {
            "/health", "/oauth2callback",
        }
        values = [value for key, value in scope.get("headers", []) if key.lower() == b"authorization"]
        authorized = len(values) == 1 and hmac.compare_digest(values[0], self.expected)
        if not public and not authorized:
            await send({"type": "http.response.start", "status": 401, "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
                (b"cache-control", b"no-store"),
            ]})
            await send({"type": "http.response.body", "body": b'{"error":"MCP service authentication required"}'})
            return
        await self.app(scope, receive, send)



class AttachmentBridgeMiddleware:
    """Private bounded staging, inside token auth; never exposes host Stash."""

    def __init__(self, app):
        self.app = app
        self.staged = set()

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/jarvis/stage"):
            await self.app(scope, receive, send)
            return
        import asyncio
        import re
        import tempfile
        from urllib.parse import unquote

        from core.attachment_storage import STORAGE_DIR, get_attachment_storage
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        request = Request(scope, receive)
        storage = get_attachment_storage()
        if request.method == "DELETE":
            staged_id = path.removeprefix("/jarvis/stage/")
            if staged_id not in self.staged:
                response = JSONResponse({"error": "Staging file not found"}, status_code=404)
            else:
                storage._cleanup_file(staged_id)
                self.staged.discard(staged_id)
                response = JSONResponse({"removed": True})
        elif request.method == "POST" and path == "/jarvis/stage":
            maximum = 50 * 1024 * 1024
            temporary = None
            try:
                filename = Path(unquote(request.headers.get("x-jarvis-filename", "attachment"))).name
                filename = re.sub(r"[\x00-\x1f]", "_", filename)[:180] or "attachment"
                length = request.headers.get("content-length")
                if length and int(length) > maximum:
                    raise ValueError("File exceeds 50 MiB")
                STORAGE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
                with tempfile.NamedTemporaryFile(dir=STORAGE_DIR, prefix="stage_", delete=False) as stream:
                    temporary = Path(stream.name)
                    size = 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > maximum:
                            raise ValueError("File exceeds 50 MiB")
                        await asyncio.to_thread(stream.write, chunk)
                saved = await asyncio.to_thread(storage.save_attachment_from_path,
                    str(temporary), filename, request.headers.get("content-type", "application/octet-stream"))
                self.staged.add(saved.file_id)
                response = JSONResponse({"id": saved.file_id, "path": saved.path}, status_code=201)
            except ValueError:
                response = JSONResponse({"error": "Invalid or oversized staging upload"}, status_code=413)
            except Exception:
                response = JSONResponse({"error": "Attachment staging failed"}, status_code=500)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
        else:
            response = JSONResponse({"error": "Unknown staging action"}, status_code=405)
        await response(scope, receive, send)

def configure_server(FastMCP, Middleware, token):
    original = FastMCP.http_app
    original_run = FastMCP.run

    def http_app(self, *args, **kwargs):
        kwargs["middleware"] = [
            Middleware(ServiceTokenMiddleware, token=token),
            Middleware(AttachmentBridgeMiddleware),
            *(kwargs.get("middleware") or []),
        ]
        return original(self, *args, **kwargs)

    FastMCP.http_app = http_app

    def run(self, *args, **kwargs):
        transport = kwargs.get("transport", args[0] if args else None)
        if transport in {"http", "streamable-http", "sse"}:
            # Uvicorn's dictConfig re-enables loggers during startup. Its actual
            # server option must suppress query-bearing OAuth access records.
            kwargs["uvicorn_config"] = {**(kwargs.get("uvicorn_config") or {}), "access_log": False}
        return original_run(self, *args, **kwargs)

    FastMCP.run = run



def configure_account_independent_tools(SecureFastMCP, FastMCP):
    """Avoid the pinned server's blanket account injection for its pure helper."""
    original_call = SecureFastMCP.call_tool

    async def call_tool(self, name, arguments, *args, **kwargs):
        if name == "generate_trigger_code":
            # This function does not use Google credentials and does not accept
            # an owner parameter. Keep base validation and MCP middleware intact.
            cleaned = {key: value for key, value in (arguments or {}).items()
                       if key != "user_google_email"}
            return await FastMCP.call_tool(self, name, cleaned, *args, **kwargs)
        return await original_call(self, name, arguments, *args, **kwargs)

    SecureFastMCP.call_tool = call_tool

def main():
    from fastmcp import FastMCP
    from starlette.middleware import Middleware

    os.umask(0o077)
    token = os.environ.pop("JARVIS_GOOGLE_MCP_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("Missing private MCP service token; run bin/jarvis-google prepare")
    logging.getLogger("uvicorn.access").disabled = True
    configure_server(FastMCP, Middleware, token)
    from core.server import SecureFastMCP
    configure_account_independent_tools(SecureFastMCP, FastMCP)
    configure_background_execution(SecureFastMCP)
    runpy.run_path(str(Path(__file__).with_name("main.py")), run_name="__main__")


if __name__ == "__main__":
    main()
