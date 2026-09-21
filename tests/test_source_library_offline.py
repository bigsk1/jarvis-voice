"""Strict offline readiness must catch hidden Ollama fallback hosts."""

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from config_loader import config_scope
from source_library_offline import _no_external_sockets, preflight


def test_local_host_chain_and_assets_preflight():
    with config_scope("local", {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_EMBEDDING_FALLBACK_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "test-local:latest",
    }):
        report = preflight()
    assert report["ready"] is True
    assert all(report["checks"].values())


def test_remote_embedding_fallback_and_host_both_fail():
    with config_scope("local", {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_EMBEDDING_FALLBACK_URL": "http://192.0.2.15:11434",
        "OLLAMA_MODEL": "test-local:latest",
    }):
        report = preflight()
    assert not report["ready"]
    assert not report["checks"]["embedding_hosts_loopback"]
    with config_scope("local", {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://192.0.2.15:11434",
        "OLLAMA_EMBEDDING_FALLBACK_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "test-local:latest",
    }):
        report = preflight()
    assert not report["checks"]["llm_hosts_loopback"]


def test_process_network_guard_rejects_non_loopback_without_dialing():
    with _no_external_sockets():
        with pytest.raises(OSError, match="non-loopback"):
            socket.socket.connect(object(), ("198.51.100.1", 80))
