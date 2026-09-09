"""Embedding-only failover, model compatibility, and request-local notices."""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import embeddings
from config_loader import config_scope
from ollama_utils import get_ollama_base_urls


class Response:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def clean_runtime_cache():
    embeddings.clear_embedding_runtime_cache()
    yield
    embeddings.clear_embedding_runtime_cache()


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_embedding_fallback_does_not_extend_chat_hosts(mode):
    with config_scope(mode, overrides={
        "OLLAMA_BASE_URL": "http://primary:11434,http://windows:11434",
        "OLLAMA_EMBEDDING_FALLBACK_URL": "http://mini:11434/",
    }):
        chat_hosts = get_ollama_base_urls()
        assert embeddings.get_embedding_base_urls() == [*chat_hosts, "http://mini:11434"]
        assert get_ollama_base_urls() == chat_hosts
        assert "http://mini:11434" not in chat_hosts


@pytest.mark.parametrize("fallback", ["", "http://primary:11434/"])
def test_blank_or_duplicate_fallback_preserves_hosts(fallback):
    with config_scope("cloud", overrides={
        "OLLAMA_BASE_URL": "http://primary:11434",
        "OLLAMA_EMBEDDING_FALLBACK_URL": fallback,
    }):
        assert embeddings.get_embedding_base_urls() == ["http://primary:11434"]


def test_failed_primary_uses_verified_fallback_and_notifies_once():
    calls = []
    notices = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/tags":
            if kwargs["base_url"] == "http://primary:11434":
                raise ConnectionError("primary is down")
            return Response({"models": [{
                "name": embeddings.EMBEDDING_MODEL_DEFAULT,
                "digest": embeddings.EMBEDDING_MODEL_DIGEST_DEFAULT,
            }]}), "http://mini:11434"
        assert kwargs["base_urls"] == ["http://mini:11434"]
        assert "num_gpu" not in kwargs["json"]["options"]
        assert kwargs["include_localhost_fallback"] is False
        return Response({"embeddings": [[0.1] * 768]}), "http://mini:11434"

    with config_scope("cloud", overrides={
        "OLLAMA_BASE_URL": "http://primary:11434",
        "OLLAMA_EMBEDDING_FALLBACK_URL": "http://mini:11434",
    }), patch("embeddings.request_ollama", side_effect=request):
        with embeddings.embedding_status_scope(notices.append):
            for _ in range(2):
                assert len(embeddings.get_embedding("find music")) == 768
        status = embeddings.get_embedding_runtime_status()

    assert notices == ["fallback"]
    assert status["compatible_hosts"] == ["http://mini:11434"]
    assert status["unavailable_hosts"] == ["http://primary:11434"]
    assert len([call for call in calls if call[1] == "/api/tags"]) == 2


@pytest.mark.parametrize("used_host, expected", [
    ("http://primary:11434", []),
    ("http://windows:11434", ["fallback"]),
    ("http://mini:11434", ["fallback"]),
])
def test_notice_uses_actual_request_host_after_cached_verification(used_host, expected):
    hosts = ("http://primary:11434", "http://windows:11434", "http://mini:11434")
    runtime = embeddings.EmbeddingRuntime(
        model=embeddings.EMBEDDING_MODEL_DEFAULT,
        digest=embeddings.EMBEDDING_MODEL_DIGEST_DEFAULT,
        base_urls=hosts,
        configured_base_urls=hosts,
    )
    notices = []
    with patch("embeddings._resolve_embedding_runtime", return_value=runtime), patch(
        "embeddings.request_ollama",
        return_value=(Response({"embeddings": [[0.1] * 768]}), used_host),
    ), embeddings.embedding_status_scope(notices.append):
        embeddings.get_embedding("a query")
    assert notices == expected


def test_mismatched_fallback_never_produces_vectors():
    notices = []
    with config_scope("cloud", overrides={
        "OLLAMA_BASE_URL": "http://primary:11434",
        "OLLAMA_EMBEDDING_FALLBACK_URL": "http://mini:11434",
    }), patch("embeddings.request_ollama") as request, embeddings.embedding_status_scope(notices.append):
        request.side_effect = [
            ConnectionError("primary is down"),
            (Response({"models": [{
                "name": embeddings.EMBEDDING_MODEL_DEFAULT, "digest": "b" * 64,
            }]}), "http://mini:11434"),
        ]
        with pytest.raises(embeddings.EmbeddingRuntimeError, match="different Jarvis Embedding artifact"):
            embeddings.get_embedding("a query")
        assert all(call.args[1] == "/api/tags" for call in request.call_args_list)
    assert notices == ["unavailable"]


def test_notification_scopes_are_isolated_and_reset_after_failure():
    def run(_):
        notices = []
        with embeddings.embedding_status_scope(notices.append):
            for _ in range(2):
                with pytest.raises(embeddings.EmbeddingRuntimeError):
                    embeddings.get_embedding("a query")
        with pytest.raises(embeddings.EmbeddingRuntimeError):
            embeddings.get_embedding("outside the scope")
        return notices

    with patch("embeddings._resolve_embedding_runtime", side_effect=embeddings.EmbeddingRuntimeError("down")):
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(run, range(2))) == [["unavailable"], ["unavailable"]]


def test_notification_delivery_failure_does_not_break_embeddings():
    runtime = embeddings.EmbeddingRuntime(
        model=embeddings.EMBEDDING_MODEL_DEFAULT, digest="a" * 64,
        base_urls=("http://mini",), configured_base_urls=("http://primary", "http://mini"),
    )

    def broken_callback(status):
        raise RuntimeError("socket disconnected")

    with patch("embeddings._resolve_embedding_runtime", return_value=runtime), patch(
        "embeddings.request_ollama",
        return_value=(Response({"embeddings": [[0.1] * 768]}), "http://mini"),
    ), embeddings.embedding_status_scope(broken_callback):
        assert len(embeddings.get_embedding("a query")) == 768
