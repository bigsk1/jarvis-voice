#!/usr/bin/env python3
"""Regression tests for Ollama host fallback helpers."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from ollama_utils import (  # noqa: E402
    OLLAMA_CLOUD_DIRECT_URL,
    get_ollama_base_urls,
    get_ollama_request_urls,
    ollama_uses_direct_cloud_api,
    parse_ollama_base_urls,
    request_ollama,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class OllamaUtilsTests(unittest.TestCase):
    def test_parse_ollama_base_urls_appends_localhost_once(self):
        urls = parse_ollama_base_urls(
            "http://203.0.113.226:11434, http://203.0.113.68:11434"
        )

        self.assertEqual(
            urls,
            [
                "http://203.0.113.226:11434",
                "http://203.0.113.68:11434",
                "http://localhost:11434",
            ],
        )

    def test_parse_single_remote_url_backwards_compatible(self):
        """Single OLLAMA_BASE_URL string (no commas) still gets localhost fallback."""
        urls = parse_ollama_base_urls("http://203.0.113.226:11434")
        self.assertEqual(
            urls,
            ["http://203.0.113.226:11434", "http://localhost:11434"],
        )

    @patch.dict(
        "os.environ",
        {"OLLAMA_BASE_URL": "http://mini-ai:11434,http://desktop:11434"},
        clear=False,
    )
    def test_get_ollama_base_urls_local_mode_appends_localhost(self):
        from config_loader import config_scope

        # Use temp configs so config_scope("local") can load a mode file.
        import tempfile, os
        from pathlib import Path
        import config_loader

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config"
            cfg.mkdir()
            (cfg / "cloud.env").write_text("")
            (cfg / "local.env").write_text("")
            orig_root = config_loader.get_project_root
            config_loader.get_project_root = lambda: Path(tmp)
            try:
                with config_scope("local"):
                    self.assertEqual(
                        get_ollama_base_urls(),
                        [
                            "http://mini-ai:11434",
                            "http://desktop:11434",
                            "http://localhost:11434",
                        ],
                    )
                with config_scope("cloud"):
                    # Cloud mode must NOT silently append localhost.
                    self.assertEqual(
                        get_ollama_base_urls(),
                        ["http://mini-ai:11434", "http://desktop:11434"],
                    )
            finally:
                config_loader.get_project_root = orig_root

    @patch.dict(
        "os.environ",
        {"OLLAMA_BASE_URL": "http://mini-ai:11434,http://desktop:11434"},
        clear=False,
    )
    def test_get_ollama_base_urls_can_force_localhost(self):
        self.assertEqual(
            get_ollama_base_urls(include_localhost_fallback=True),
            [
                "http://mini-ai:11434",
                "http://desktop:11434",
                "http://localhost:11434",
            ],
        )

    @patch("requests.request")
    def test_request_ollama_falls_back_after_connection_error(self, mock_request):
        mock_request.side_effect = [
            requests.exceptions.ConnectionError("primary down"),
            _FakeResponse(200, {"models": [{"name": "qwen3"}]}),
        ]

        response, used_base_url = request_ollama(
            "get",
            "/api/tags",
            base_url="http://primary:11434,http://secondary:11434",
            timeout=5,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(used_base_url, "http://secondary:11434")
        self.assertEqual(
            mock_request.call_args_list[0].args[1],
            "http://primary:11434/api/tags",
        )
        self.assertEqual(
            mock_request.call_args_list[1].args[1],
            "http://secondary:11434/api/tags",
        )

    @patch.dict(
        "os.environ",
        {"OLLAMA_BASE_URL": "http://configured:11434"},
        clear=False,
    )
    @patch("requests.request")
    def test_request_without_explicit_url_uses_ollama_base_url(self, mock_request):
        mock_request.return_value = _FakeResponse(200, {"models": []})

        response, used_base_url = request_ollama("get", "/api/tags", timeout=5)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(used_base_url, "http://configured:11434")
        self.assertEqual(
            mock_request.call_args.args[1],
            "http://configured:11434/api/tags",
        )

    @patch("requests.request")
    def test_request_ollama_retries_next_host_on_503(self, mock_request):
        mock_request.side_effect = [
            _FakeResponse(503),
            _FakeResponse(200, {"response": "ok"}),
        ]

        response, used_base_url = request_ollama(
            "post",
            "/api/generate",
            base_url="http://primary:11434,http://secondary:11434",
            json={"model": "qwen3"},
            timeout=30,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(used_base_url, "http://secondary:11434")

    @patch("requests.request")
    def test_request_ollama_reports_host_that_returned_last_retryable_response(self, mock_request):
        mock_request.side_effect = [
            _FakeResponse(503),
            requests.exceptions.ConnectionError("secondary down"),
            requests.exceptions.ConnectionError("localhost down"),
        ]

        response, used_base_url = request_ollama(
            "get",
            "/api/tags",
            base_url="http://primary:11434,http://secondary:11434",
            timeout=5,
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(used_base_url, "http://primary:11434")

    @patch.dict("os.environ", {"OLLAMA_API_KEY": "test-cloud-key"}, clear=False)
    def test_cloud_access_with_api_key_uses_ollama_com_only(self):
        from config_loader import config_scope
        import config_loader
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config"
            cfg.mkdir()
            (cfg / "cloud.env").write_text('OLLAMA_API_KEY="test-cloud-key"\n')
            (cfg / "local.env").write_text("")
            orig_root = config_loader.get_project_root
            config_loader.get_project_root = lambda: Path(tmp)
            try:
                with config_scope("cloud"):
                    self.assertTrue(ollama_uses_direct_cloud_api())
                    self.assertEqual(
                        get_ollama_request_urls(cloud_access=True),
                        [OLLAMA_CLOUD_DIRECT_URL],
                    )
                with config_scope("local"):
                    self.assertFalse(ollama_uses_direct_cloud_api())
                    self.assertNotEqual(
                        get_ollama_request_urls(cloud_access=True)[0],
                        OLLAMA_CLOUD_DIRECT_URL,
                    )
            finally:
                config_loader.get_project_root = orig_root

    @patch("requests.request")
    @patch.dict("os.environ", {"OLLAMA_API_KEY": "test-cloud-key"}, clear=False)
    def test_request_ollama_cloud_access_sends_bearer_to_ollama_com(self, mock_request):
        from config_loader import config_scope
        import config_loader
        import tempfile
        from pathlib import Path

        mock_request.return_value = _FakeResponse(200, {"models": []})
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config"
            cfg.mkdir()
            (cfg / "cloud.env").write_text(
                'OLLAMA_API_KEY="test-cloud-key"\nOLLAMA_BASE_URL="http://localhost:11434"\n'
            )
            (cfg / "local.env").write_text("")
            orig_root = config_loader.get_project_root
            config_loader.get_project_root = lambda: Path(tmp)
            try:
                with config_scope("cloud"):
                    request_ollama("get", "/api/tags", cloud_access=True, timeout=5)
            finally:
                config_loader.get_project_root = orig_root

        self.assertEqual(
            mock_request.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-cloud-key",
        )
        self.assertEqual(
            mock_request.call_args.args[1],
            f"{OLLAMA_CLOUD_DIRECT_URL}/api/tags",
        )

    @patch("requests.request")
    @patch.dict("os.environ", {"OLLAMA_API_KEY": "test-cloud-key"}, clear=False)
    def test_request_ollama_never_sends_cloud_key_to_daemon(self, mock_request):
        mock_request.return_value = _FakeResponse(200, {"models": []})

        request_ollama(
            "get",
            "/api/tags",
            base_url="http://daemon:11434",
            timeout=5,
        )

        self.assertIsNone(mock_request.call_args.kwargs["headers"])


if __name__ == "__main__":
    unittest.main()
