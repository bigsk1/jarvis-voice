#!/usr/bin/env python3
"""
Regression tests for embedding helpers.

Run:
    python3 tests/test_embeddings.py
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from embeddings import (
    _compact_text_for_embedding,
    _extract_ollama_embedding,
    _get_ollama_embedding,
    _get_ollama_embedding_options,
    consume_embedding_fallback_tracking,
    reset_embedding_fallback_tracking,
)


class _FakeResponse:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class EmbeddingsTests(unittest.TestCase):
    def test_compact_text_for_embedding_keeps_head_and_tail(self):
        text = "start " + ("middle " * 400) + "end"
        compacted = _compact_text_for_embedding(text, 120)

        self.assertLessEqual(len(compacted), 120)
        self.assertIn("start", compacted)
        self.assertIn("end", compacted)
        self.assertIn(" ... ", compacted)

    @patch("requests.request")
    def test_ollama_embedding_retries_with_compacted_text_on_context_error(self, mock_request):
        mock_request.side_effect = [
            _FakeResponse(500, '{"error":"the input length exceeds the context length"}'),
            _FakeResponse(200, payload={"embedding": [0.1, 0.2, 0.3]}),
        ]

        long_text = "x" * 7000
        embedding = _get_ollama_embedding(long_text)

        self.assertEqual(embedding, [0.1, 0.2, 0.3])
        self.assertEqual(mock_request.call_count, 2)

        first_prompt = mock_request.call_args_list[0].kwargs["json"]["input"]
        second_prompt = mock_request.call_args_list[1].kwargs["json"]["input"]
        self.assertEqual(len(first_prompt), 7000)
        self.assertLess(len(second_prompt), len(first_prompt))

    @patch("requests.request")
    def test_ollama_embedding_records_fallback_tracking(self, mock_request):
        mock_request.return_value = _FakeResponse(500, '{"error":"connection refused"}')

        reset_embedding_fallback_tracking()
        _get_ollama_embedding("semantic query")
        diagnostics = consume_embedding_fallback_tracking()

        self.assertTrue(diagnostics["fallback_embeddings"])
        self.assertEqual(diagnostics["fallback_count"], 1)
        self.assertEqual(diagnostics["fallback_providers"], ["ollama"])

    @patch.dict("os.environ", {"OLLAMA_CONTEXT_WINDOW": "48000"}, clear=False)
    def test_get_ollama_embedding_options_uses_context_window(self):
        self.assertEqual(_get_ollama_embedding_options(), {"num_ctx": 48000})

    def test_extract_ollama_embedding_supports_embed_endpoint_shape(self):
        result = {"embeddings": [[0.4, 0.5, 0.6]]}
        self.assertEqual(_extract_ollama_embedding(result), [0.4, 0.5, 0.6])


if __name__ == "__main__":
    unittest.main()
