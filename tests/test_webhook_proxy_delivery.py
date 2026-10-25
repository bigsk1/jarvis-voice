"""Real loopback HTTP delivery must never replay a POST after a proxy response.

These tests require local sockets and intentionally fail under a socket-blocking
sandbox; run them with the same permissions as the full regression suite.
"""

import importlib
import json
import sys
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest


@contextmanager
def _http_endpoint(status):
    posts = []

    class Handler(BaseHTTPRequestHandler):
        timeout = 2

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            posts.append({"path": self.path, "body": body})
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, _format, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}", posts=posts)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "Disposable HTTP server did not stop"


@pytest.mark.parametrize("proxy_status,delivery_status,request_sent", [
    (407, "proxy_rejected", False),
    (502, "unknown", None),
])
def test_primary_proxy_response_never_replays_webhook(
    monkeypatch, tmp_path, capsys, proxy_status, delivery_status, request_sent,
):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "lib"))
    monkeypatch.syspath_prepend(str(root / "skills"))
    webhook = importlib.import_module("send_webhook")
    transport = importlib.import_module("webhook_transport")
    http = importlib.import_module("http_client")
    projection = importlib.import_module("webhook_context")

    with ExitStack() as stack:
        primary = stack.enter_context(_http_endpoint(proxy_status))
        secondary = stack.enter_context(_http_endpoint(204))
        receiver = stack.enter_context(_http_endpoint(204))
        destination = receiver.url + "/webhook"
        registry_path = tmp_path / "webhook_registry.json"
        registry_path.write_text(json.dumps({"webhooks": {"local_test": {
            "url": destination, "proxy_policy": "require", "rate_limit_seconds": 5,
        }}}))
        config = {"LOCAL_PROXY": primary.url, "LOCAL_PROXY2": secondary.url}

        def controlled_config(key, default=None):
            return config.get(key, default)

        monkeypatch.setattr(webhook, "load_config", lambda: None)
        monkeypatch.setattr(webhook, "load_webhook_registry", lambda: json.loads(registry_path.read_text())["webhooks"])
        monkeypatch.setattr(webhook, "RATE_LIMIT_FILE", str(tmp_path / "webhook_rate_limit.json"))
        monkeypatch.setattr(webhook, "get_config_value", controlled_config)
        monkeypatch.setattr(transport, "get_config_value", controlled_config)
        monkeypatch.setattr(http, "get_config_value", controlled_config)
        monkeypatch.setenv("NO_PROXY", "*")
        monkeypatch.setenv("no_proxy", "*")
        # A conventional proxy must neither replace the selected route nor
        # receive a fallback attempt after the primary responds.
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            monkeypatch.setenv(key, secondary.url)
        body = {"event": "single-delivery-regression", "value": 42}
        monkeypatch.setattr(sys, "argv", ["send_webhook.py", json.dumps({"webhook": "local_test", "data": body})])

        assert webhook.main() == 1
        result = json.loads(capsys.readouterr().out)
        assert len(primary.posts) == 1
        assert primary.posts[0]["path"] == destination
        assert json.loads(primary.posts[0]["body"]) == body
        assert secondary.posts == [] and receiver.posts == []
        data = result["data"]
        assert data["response_received"] is True and data["status_code"] == proxy_status
        assert data["request_sent"] is request_sent
        assert data["delivery_status"] == delivery_status and data["retry_safe"] is False
        expected_route = {"policy": "require", "used": True, "basis": "webhook_route", "slot": "LOCAL_PROXY"}
        assert data["proxy"] == expected_route
        projected = projection.project_webhook_data(result)
        assert projected["proxy"] == expected_route
        assert projected["request_sent"] is request_sent
        assert projected["delivery_status"] == delivery_status
        assert primary.url not in json.dumps(projected) and secondary.url not in json.dumps(projected)
