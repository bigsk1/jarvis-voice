#!/usr/bin/env python3
"""Regression coverage for sanitized Ollama Cloud account status."""

import sys
import os
import importlib
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "jarvis-web"))
sys.path.insert(0, str(ROOT / "lib"))

# Several lightweight ChatHandler tests install collection-time Flask stubs.
# This test creates the real app, so replace those stubs with installed modules.
for module_name in ("flask", "flask_socketio"):
    module = sys.modules.get(module_name)
    if module is not None and not getattr(module, "__file__", None):
        del sys.modules[module_name]
    importlib.import_module(module_name)

from server_package_utils import load_server_package  # noqa: E402

load_server_package("jarvis_web_test_server", ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.app import app  # noqa: E402
from jarvis_web_test_server.routes import api  # noqa: E402
from jarvis_web_test_server.sockets.chat import _scoped_by_mode  # noqa: E402
from config_loader import export_config_environment, get_config_value  # noqa: E402


class _Response:
    def __init__(self, status_code=200, payload=None, json_error=False):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise ValueError("invalid json")
        return self.payload


def _status_payload(response):
    api._OLLAMA_CLOUD_STATUS_CACHE.clear()
    with app.test_request_context("/api/ollama/cloud-status?mode=cloud"):
        with patch("ollama_utils.get_ollama_api_key", return_value=""), patch(
            "requests.post", return_value=response
        ):
            return api.get_ollama_cloud_status().get_json()


def test_malformed_success_is_unknown_not_signed_in():
    payload = _status_payload(_Response(json_error=True))
    assert payload["reachable"] is True
    assert payload["signed_in"] == "unknown"
    assert payload["plan"] is None


def test_empty_success_is_unknown_not_signed_in():
    payload = _status_payload(_Response(payload={}))
    assert payload["signed_in"] == "unknown"


def test_valid_account_is_sanitized():
    payload = _status_payload(_Response(payload={
        "id": "private-account-id",
        "email": "private@example.com",
        "plan": "free",
    }))
    assert payload["signed_in"] is True
    assert payload["plan"] == "free"
    assert "id" not in payload
    assert "email" not in payload


def test_api_key_mode_skips_daemon_me_check():
    import config_loader
    import tempfile

    api._OLLAMA_CLOUD_STATUS_CACHE.clear()
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config"
        cfg.mkdir()
        (cfg / "cloud.env").write_text('OLLAMA_API_KEY="test-key"\n')
        (cfg / "local.env").write_text("")
        orig_root = config_loader.get_project_root
        config_loader.get_project_root = lambda: Path(tmp)
        try:
            with app.test_request_context("/api/ollama/cloud-status?mode=cloud"):
                with patch("requests.post") as mock_post:
                    payload = api.get_ollama_cloud_status().get_json()
                    mock_post.assert_not_called()
        finally:
            config_loader.get_project_root = orig_root

    assert payload["connection_mode"] == "api_key"
    assert payload["signed_in"] is True
    assert payload["reachable"] is True


def test_web_chat_overrides_are_scoped_and_exported_to_children():
    @_scoped_by_mode
    def probe(mode, image_data=None):
        child = export_config_environment(mode)
        return {
            "image": get_config_value("IMAGE_TOOL_PROVIDER"),
            "tts": get_config_value("TTS_PROVIDER"),
            "child_image": child.get("JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER"),
            "child_tts": child.get("JARVIS_OVERRIDE_TTS_PROVIDER"),
        }

    web_config = {
        "cloud": {
            "image_provider": "gemini",
            "tts_provider": "elevenlabs",
        }
    }
    image_data = {"action": "image", "settings": {"provider": "openai"}}
    before = dict(os.environ)
    with patch("jarvis_web_test_server.config.load_web_config", return_value=web_config):
        result = probe("cloud", image_data=image_data)

    assert result == {
        "image": "openai",
        "tts": "elevenlabs",
        "child_image": "openai",
        "child_tts": "elevenlabs",
    }
    assert dict(os.environ) == before
