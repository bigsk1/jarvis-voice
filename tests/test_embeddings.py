#!/usr/bin/env python3
"""Regression tests for the unified Jarvis Embedding contract."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingConfigurationError,
    EmbeddingRuntime,
    EmbeddingRuntimeError,
    PersistentEmbeddingError,
    _compact_text_for_embedding,
    _get_ollama_embedding,
    _get_ollama_embedding_options,
    _resolve_embedding_runtime,
    clear_embedding_runtime_cache,
    cosine_similarity,
    format_embedding_input,
    get_embedding_model,
    get_embedding_runtime_status,
    get_embeddings_batch,
    get_persistable_embedding,
)
from embedding_inputs import (
    build_outcome_embedding_text,
    build_stored_outcome_embedding_text,
)


class _FakeResponse:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


RUNTIME = EmbeddingRuntime(
    model="bigsk1/jarvis-embedding:bf16-v1",
    digest="a" * 64,
    base_urls=("http://ollama-test:11434",),
)


class EmbeddingsTests(unittest.TestCase):
    @patch(
        "embeddings.get_config_value",
        return_value="bigsk1/jarvis-embedding:bf16-v1",
    )
    def test_only_versioned_jarvis_embedding_artifact_is_accepted(self, _config):
        self.assertEqual(
            get_embedding_model(),
            "bigsk1/jarvis-embedding:bf16-v1",
        )

    @patch("embeddings.get_config_value", return_value="embeddinggemma")
    def test_upstream_embeddinggemma_tag_is_not_a_supported_runtime_alias(self, _config):
        with self.assertRaisesRegex(
            EmbeddingConfigurationError,
            "bigsk1/jarvis-embedding:bf16-v1",
        ):
            get_embedding_model()

    def test_official_asymmetric_prompts(self):
        self.assertEqual(
            format_embedding_input("find weather", role="query"),
            "task: search result | query: find weather",
        )
        self.assertEqual(
            format_embedding_input("Forecast tool", role="document", title="weather"),
            "title: weather | text: Forecast tool",
        )
        self.assertEqual(
            format_embedding_input("same meaning", role="similarity"),
            "task: sentence similarity | query: same meaning",
        )

    def test_compact_text_for_embedding_keeps_head_and_tail(self):
        text = "start " + ("middle " * 400) + "end"
        compacted = _compact_text_for_embedding(text, 120)
        self.assertLessEqual(len(compacted), 120)
        self.assertIn("start", compacted)
        self.assertIn("end", compacted)
        self.assertIn(" ... ", compacted)

    @patch("embeddings._resolve_embedding_runtime", return_value=RUNTIME)
    @patch("requests.request")
    def test_ollama_embedding_retries_compacted_prompt(self, mock_request, _runtime):
        vector = [0.1] * EMBEDDING_DIMENSIONS
        mock_request.side_effect = [
            _FakeResponse(500, '{"error":"the input length exceeds the context length"}'),
            _FakeResponse(200, payload={"embeddings": [vector]}),
        ]
        embedding = _get_ollama_embedding("x" * 7000, role="query")
        self.assertEqual(embedding, vector)
        first_prompt = mock_request.call_args_list[0].kwargs["json"]["input"]
        second_prompt = mock_request.call_args_list[1].kwargs["json"]["input"]
        self.assertTrue(first_prompt.startswith("task: search result | query: "))
        self.assertLess(len(second_prompt), len(first_prompt))
        self.assertNotIn("num_gpu", mock_request.call_args_list[0].kwargs["json"]["options"])

    @patch("embeddings._resolve_embedding_runtime", return_value=RUNTIME)
    @patch("requests.request")
    def test_ollama_failure_raises_instead_of_hash_fallback(self, mock_request, _runtime):
        mock_request.return_value = _FakeResponse(500, "connection refused")
        with self.assertRaises(EmbeddingRuntimeError):
            _get_ollama_embedding("semantic query")

    @patch.dict("os.environ", {"OLLAMA_EMBEDDING_CONTEXT_WINDOW": "48000"}, clear=False)
    def test_context_window_is_clamped_to_model_limit(self):
        self.assertEqual(_get_ollama_embedding_options(), {"num_ctx": 2048})

    @patch("embeddings._request_embeddings")
    def test_batch_uses_one_request_with_document_prompts(self, request):
        request.return_value = [[0.0] * EMBEDDING_DIMENSIONS] * 2
        result = get_embeddings_batch(
            ["first", "second"],
            role="document",
            titles=["one", "two"],
        )
        self.assertEqual(len(result), 2)
        request.assert_called_once_with(
            ["title: one | text: first", "title: two | text: second"]
        )

    @patch("embeddings.time.sleep")
    @patch("embeddings.get_embedding", side_effect=RuntimeError("provider unavailable"))
    def test_persistable_embedding_retries_then_raises(self, mock_get, mock_sleep):
        with self.assertRaises(PersistentEmbeddingError):
            get_persistable_embedding(
                "store this",
                max_attempts=3,
                retry_delay_seconds=0.25,
            )
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_cosine_similarity_rejects_dimension_mismatch(self):
        with self.assertRaisesRegex(ValueError, "dimension mismatch"):
            cosine_similarity([1.0, 0.0], [1.0])

    def test_stored_outcome_builder_matches_live_builder(self):
        live = build_outcome_embedding_text(
            "send the report",
            ["pdf_create", "send_email"],
            {"success": True},
            {"thanked": True, "retried": False},
        )
        stored = build_stored_outcome_embedding_text(
            query="send the report",
            tools_used_json='["pdf_create", "send_email"]',
            raw_data_json=(
                '{"outcome":{"success":true},'
                '"user_signals":{"thanked":true,"retried":false}}'
            ),
            outcome_success=1,
            error_occurred=0,
        )
        self.assertEqual(stored, live)

    @patch("embeddings.get_embedding_model_digest")
    @patch("embeddings._resolve_embedding_runtime")
    def test_runtime_status_reports_invalid_config_without_crashing(
        self,
        resolve_runtime,
        model_digest,
    ):
        error = EmbeddingConfigurationError("invalid digest")
        resolve_runtime.side_effect = error
        model_digest.side_effect = error

        status = get_embedding_runtime_status(force_refresh=True)

        self.assertFalse(status["ok"])
        self.assertEqual(status["error"], "invalid digest")

    @patch("embeddings.get_ollama_base_urls", return_value=["http://one", "http://two"])
    @patch("embeddings.get_embedding_model_digest", return_value="a" * 64)
    @patch("embeddings.request_ollama")
    def test_runtime_rejects_one_mismatched_reachable_host(
        self,
        request_ollama,
        _digest,
        _base_urls,
    ):
        request_ollama.side_effect = [
            (_FakeResponse(200, payload={"models": [{"name": "bigsk1/jarvis-embedding:bf16-v1", "digest": "a" * 64}]}), "http://one"),
            (_FakeResponse(200, payload={"models": [{"name": "bigsk1/jarvis-embedding:bf16-v1", "digest": "b" * 64}]}), "http://two"),
        ]
        clear_embedding_runtime_cache()

        with self.assertRaisesRegex(EmbeddingRuntimeError, "different Jarvis Embedding artifact"):
            _resolve_embedding_runtime(force_refresh=True)


if __name__ == "__main__":
    unittest.main()
