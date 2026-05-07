#!/usr/bin/env python3
"""Regression tests for Ollama host fallback helpers."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from ollama_utils import get_ollama_base_urls, parse_ollama_base_urls, request_ollama  # noqa: E402


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
    def test_get_ollama_base_urls_uses_env_order(self):
        self.assertEqual(
            get_ollama_base_urls(),
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


if __name__ == "__main__":
    unittest.main()
