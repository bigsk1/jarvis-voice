"""Add machine authentication to upstream's legacy, single-account HTTP mode."""

import hmac
import logging
import os
import runpy
from pathlib import Path


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
    runpy.run_path(str(Path(__file__).with_name("main.py")), run_name="__main__")


if __name__ == "__main__":
    main()
