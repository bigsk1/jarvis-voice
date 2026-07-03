"""Regression coverage for the Werkzeug WebSocket teardown shim.

Jarvis Web serves Flask-SocketIO (threading mode, simple-websocket) through
Werkzeug. Without the shim in ``jarvis-web/server/werkzeug_ws_compat.py``,
every normal WebSocket disconnect makes Werkzeug log a false HTTP 500:

    AssertionError: write() before start_response

These tests run a real threaded Werkzeug server with a real WebSocket client
and assert the traceback is gone with the shim applied. A canary test keeps
the unpatched failure reproducible: when a python-engineio upgrade makes the
canary fail, upstream has fixed the teardown and the shim should be deleted.
"""

from __future__ import annotations

import logging
import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = PROJECT_ROOT / "jarvis-web"
sys.path.insert(0, str(WEB_ROOT))

from server.werkzeug_ws_compat import _SENTINEL, apply_werkzeug_ws_teardown_shim

TRACEBACK_MARKER = "write() before start_response"


class _WerkzeugLogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _driver_class():
    from engineio.async_drivers import _websocket_wsgi as eio_ws

    return eio_ws.SimpleWebSocketWSGI


def _remove_shim():
    """Restore the pristine Engine.IO driver; returns True if removed."""
    cls = _driver_class()
    if not getattr(cls, _SENTINEL, False):
        return False
    cls.__call__ = cls.__call__.__wrapped__
    setattr(cls, _SENTINEL, False)
    return True


class _LiveWerkzeugServer:
    """A minimal Flask-SocketIO app on a real threaded Werkzeug server."""

    def __init__(self) -> None:
        from flask import Flask
        from flask_socketio import SocketIO
        from werkzeug.serving import make_server

        app = Flask(__name__)

        @app.route("/health")
        def health():
            return {"ok": True}

        # Mirrors the Jarvis Web runtime: threading mode + simple-websocket,
        # with the Socket.IO WSGI middleware wrapping the Flask app.
        SocketIO(app, async_mode="threading", cors_allowed_origins="*",
                 logger=False, engineio_logger=False)

        self._server = make_server("127.0.0.1", 0, app, threaded=True)
        self.port = self._server.server_port

        import threading

        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)
        self._thread.start()

        self.log_capture = _WerkzeugLogCapture()
        logging.getLogger("werkzeug").addHandler(self.log_capture)

    def websocket_cycle(self) -> None:
        """Connect an Engine.IO WebSocket, read the open packet, disconnect."""
        import simple_websocket

        ws = simple_websocket.Client.connect(
            f"ws://127.0.0.1:{self.port}/socket.io/?EIO=4&transport=websocket")
        try:
            opened = ws.receive(timeout=5)
        finally:
            ws.close()
        assert opened is not None and str(opened).startswith("0"), (
            f"expected Engine.IO open packet, got {opened!r}")

    def http_ok(self) -> bool:
        import json
        import urllib.request

        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/health", timeout=5) as resp:
            return resp.status == 200 and json.load(resp)["ok"] is True

    def drain(self, seconds: float = 0.3) -> None:
        # Teardown logging happens on the per-request thread after the client
        # closes; give it a moment before inspecting captured records.
        time.sleep(seconds)

    def stop(self) -> None:
        logging.getLogger("werkzeug").removeHandler(self.log_capture)
        self._server.shutdown()
        self._thread.join(timeout=5)


class _RestoresShimStateMixin(unittest.TestCase):
    """Capture the shim state before each test and restore it afterward.

    ``server.app`` applies the shim at import time and stays cached in
    ``sys.modules``; tests that mutate the driver class must leave it exactly
    as they found it, or later tests in the same process would run the cached
    app with the shim unexpectedly disabled.
    """

    def setUp(self) -> None:
        super().setUp()
        self._shim_was_applied = getattr(_driver_class(), _SENTINEL, False)

    def tearDown(self) -> None:
        if self._shim_was_applied:
            apply_werkzeug_ws_teardown_shim()
        else:
            _remove_shim()
        super().tearDown()


class WerkzeugTeardownShimUnitTests(_RestoresShimStateMixin):
    def test_app_module_applies_the_shim(self) -> None:
        app_source = (WEB_ROOT / "server" / "app.py").read_text()
        self.assertIn(
            "from .werkzeug_ws_compat import apply_werkzeug_ws_teardown_shim",
            app_source)
        self.assertIn("apply_werkzeug_ws_teardown_shim()", app_source)

    def test_shim_is_idempotent(self) -> None:
        cls = _driver_class()
        apply_werkzeug_ws_teardown_shim()
        second = apply_werkzeug_ws_teardown_shim()
        self.assertFalse(second, "second apply must be a no-op")
        # Exactly one wrapper layer: the original must not itself be
        # a shim wrapper.
        self.assertTrue(hasattr(cls.__call__, "__wrapped__"))
        self.assertFalse(hasattr(cls.__call__.__wrapped__, "__wrapped__"))


class WerkzeugTeardownLiveTests(_RestoresShimStateMixin):
    """Real-server tests; shim state is restored by the mixin."""

    def test_canary_unpatched_werkzeug_still_reproduces_traceback(self) -> None:
        """If this fails, python-engineio fixed the teardown upstream.

        Delete jarvis-web/server/werkzeug_ws_compat.py, its call in
        server/app.py, and this test module when that happens.
        """
        _remove_shim()
        server = _LiveWerkzeugServer()
        try:
            server.websocket_cycle()
            server.drain()
            captured = "\n".join(server.log_capture.messages)
            self.assertIn(
                TRACEBACK_MARKER, captured,
                "Upstream no longer emits the Werkzeug teardown traceback; "
                "the Jarvis shim is obsolete and should be removed.")
        finally:
            server.stop()

    def test_patched_repeated_connect_disconnect_is_silent(self) -> None:
        apply_werkzeug_ws_teardown_shim()
        server = _LiveWerkzeugServer()
        try:
            for _ in range(25):
                server.websocket_cycle()
            server.drain()
            captured = "\n".join(server.log_capture.messages)
            self.assertNotIn(TRACEBACK_MARKER, captured)
            self.assertNotIn("AssertionError", captured)
            self.assertNotIn("Error on request", captured)
            self.assertTrue(server.http_ok(),
                            "server must stay healthy after teardowns")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
