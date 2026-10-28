"""Isolated Docker embedding preparation: no daemon, model downloads or DBs."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

SCRIPT = Path(__file__).resolve().parents[1] / "docker/bootstrap-ollama.py"
SPEC = importlib.util.spec_from_file_location("docker_ollama_bootstrap", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
bootstrap = importlib.util.module_from_spec(SPEC)
original_search_path = sys.path.copy()
try:
    SPEC.loader.exec_module(bootstrap)
finally:
    sys.path[:] = original_search_path


@pytest.fixture(autouse=True)
def isolated_bootstrap_environment(monkeypatch):
    for name in ("OLLAMA_BASE_URL", "JARVIS_OLLAMA_BOOTSTRAP_READY_TIMEOUT_SECONDS",
                 "JARVIS_OLLAMA_BOOTSTRAP_PULL_TIMEOUT_SECONDS", "JARVIS_OLLAMA_BOOTSTRAP_EMBED_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)


class Response:
    def __init__(self, payload=None, *, status=200, body=None):
        self.status_code = status
        self.body = json.dumps(payload).encode() if body is None else body
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def tags(digest=None):
    return {"models": [{"name": bootstrap.EMBEDDING_MODEL_DEFAULT,
                        "model": bootstrap.EMBEDDING_MODEL_DEFAULT,
                        "digest": digest or bootstrap.EMBEDDING_MODEL_DIGEST_DEFAULT}]}


def embedding(vector=None):
    return {"model": bootstrap.EMBEDDING_MODEL_DEFAULT,
            "embeddings": [[0.1] * bootstrap.EMBEDDING_DIMENSIONS if vector is None else vector]}


def install_session(monkeypatch, *responses):
    session = Session(responses)
    monkeypatch.setattr(bootstrap, "create_session", lambda: session)
    return session


def test_existing_pinned_model_is_verified_without_pulling(monkeypatch):
    responses = [Response(tags("sha256:" + bootstrap.EMBEDDING_MODEL_DIGEST_DEFAULT)), Response(embedding())]
    session = install_session(monkeypatch, *responses)
    bootstrap.bootstrap("http://private-ollama:11434")
    assert [(method, url.rsplit("/", 1)[1]) for method, url, _ in session.calls] == [
        ("GET", "tags"), ("POST", "embed")]
    payload = session.calls[1][2]["json"]
    assert payload == {
        "model": bootstrap.EMBEDDING_MODEL_DEFAULT,
        "input": bootstrap.format_embedding_input("Jarvis Docker embedding readiness", role="query"),
        "dimensions": bootstrap.EMBEDDING_DIMENSIONS,
        "truncate": False,
        "options": {"num_ctx": bootstrap.EMBEDDING_CONTEXT_WINDOW},
    }
    assert session.closed and all(response.closed for response in responses)
    assert all(call[2]["allow_redirects"] is False for call in session.calls)


def test_missing_model_pulls_once_then_rechecks_digest_before_embedding(monkeypatch):
    session = install_session(monkeypatch, Response({"models": []}), Response({"status": "success"}),
                              Response(tags()), Response(embedding()))
    bootstrap.bootstrap("http://private-ollama:11434", pull_timeout=400, embed_timeout=80)
    assert [url.rsplit("/", 1)[1] for _, url, _ in session.calls] == ["tags", "pull", "tags", "embed"]
    pull = session.calls[1][2]
    assert pull["json"] == {"model": bootstrap.EMBEDDING_MODEL_DEFAULT, "stream": False}
    assert pull["timeout"] == (3.0, 397)
    assert session.calls[3][2]["timeout"] == (3.0, 77)


@pytest.mark.parametrize("response", [tags("f" * 64), {"models": [{"name": bootstrap.EMBEDDING_MODEL_DEFAULT}]},
                                     {}, {"models": None}, {"models": [None]}, {"models": [{}]},
                                     {"models": [{"name": 3}]}, {"models": tags()["models"] * 2},
                                     {"models": [{"name": "different", "model": bootstrap.EMBEDDING_MODEL_DEFAULT}]}])
def test_bad_existing_catalog_fails_without_pull_or_embedding(monkeypatch, response):
    received = Response(response)
    session = install_session(monkeypatch, received)
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.bootstrap("http://private-ollama:11434")
    assert len(session.calls) == 1 and session.closed and received.closed


@pytest.mark.parametrize("pulled", [{}, {"status": "downloading"}, {"status": "success", "error": "private detail"}])
def test_pull_requires_success_and_never_retries(monkeypatch, pulled):
    session = install_session(monkeypatch, Response({"models": []}), Response(pulled))
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.bootstrap("http://private-ollama:11434")
    assert len(session.calls) == 2 and session.closed


@pytest.mark.parametrize("after", [{"models": []}, tags("f" * 64)])
def test_pull_does_not_bypass_postdownload_identity_check(monkeypatch, after):
    session = install_session(monkeypatch, Response({"models": []}), Response({"status": "success"}), Response(after))
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.bootstrap("http://private-ollama:11434")
    assert len(session.calls) == 3


@pytest.mark.parametrize("vector", [[], [0.1] * 767, [0.0] * 768,
                                   [float("nan")] * 768, [float("inf")] * 768,
                                   [True] * 768, ["0.1"] * 768, [10 ** 1000] * 768])
def test_invalid_embedding_never_completes_readiness(monkeypatch, vector):
    session = install_session(monkeypatch, Response(tags()), Response(embedding(vector)))
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.bootstrap("http://private-ollama:11434")
    assert len(session.calls) == 2 and session.closed


@pytest.mark.parametrize("payload", [{}, {"model": "different", "embeddings": [[0.1] * 768]},
                                    {"model": bootstrap.EMBEDDING_MODEL_DEFAULT, "embeddings": [[0.1] * 768] * 2}])
def test_invalid_embedding_envelope_rejected(monkeypatch, payload):
    install_session(monkeypatch, Response(tags()), Response(payload))
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.bootstrap("http://private-ollama:11434")


@pytest.mark.parametrize("response", [Response(body=b"not json"), Response(body=b"\xff"), Response([]),
                                     Response(tags(), status=302), Response(body=b"x" * (2 * 1024 * 1024 + 1))])
def test_bad_http_responses_fail_closed_and_close(monkeypatch, response):
    session = install_session(monkeypatch, response)
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.bootstrap("http://private-ollama:11434")
    assert response.closed and session.closed


def test_daemon_wait_is_bounded_and_recovers_without_replaying_posts(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(bootstrap, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds)))
    session = install_session(monkeypatch, requests.ConnectionError("unready"), Response({}, status=503),
                              Response(tags()), Response(embedding()))
    bootstrap.bootstrap("http://private-ollama:11434", ready_timeout=3)
    assert now[0] == 2
    assert [method for method, _, _ in session.calls] == ["GET", "GET", "GET", "POST"]
    assert session.calls[2][2]["timeout"] == (0.5, 0.5)


def test_daemon_wait_stops_at_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(bootstrap, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds)))
    session = install_session(monkeypatch, *[requests.Timeout("private detail")] * 3)
    with pytest.raises(bootstrap.BootstrapError, match="startup timeout"):
        bootstrap.bootstrap("http://private-ollama:11434", ready_timeout=2.5)
    assert now[0] == 2.5 and len(session.calls) == 3


@pytest.mark.parametrize("phase", ["pull", "embed"])
def test_cli_network_failure_is_safe_nonzero_and_not_retried(monkeypatch, capsys, phase):
    responses = [Response({"models": []}) if phase == "pull" else Response(tags()),
                 requests.Timeout("http://user:private-secret@host/?key=private-key")]
    session = install_session(monkeypatch, *responses)
    assert bootstrap.main() == 1
    output = capsys.readouterr()
    assert "timed out" in output.err and "private-secret" not in output.err and "private-key" not in output.err
    assert len(session.calls) == 2 and session.closed


@pytest.mark.parametrize("value", ["nan", "inf", "0", "-1", "no", "7201"])
def test_cli_bad_timeout_is_rejected_before_network(monkeypatch, capsys, value):
    monkeypatch.setenv("JARVIS_OLLAMA_BOOTSTRAP_READY_TIMEOUT_SECONDS", value)
    construct = Mock()
    monkeypatch.setattr(bootstrap, "create_session", construct)
    assert bootstrap.main() == 1
    construct.assert_not_called()
    assert "between 1 and 7200" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["", "ftp://host", "http://user:secret@host", "http://@host", "http://a,http://b", "http://host:bad", "http://host/api", "http://host?key=secret"])
def test_cli_invalid_single_daemon_url_is_rejected_without_echoing_secrets(monkeypatch, capsys, value):
    monkeypatch.setenv("OLLAMA_BASE_URL", value)
    construct = Mock()
    monkeypatch.setattr(bootstrap, "create_session", construct)
    assert bootstrap.main() == 1
    construct.assert_not_called()
    assert "secret" not in capsys.readouterr().err


def test_session_has_no_ambient_proxy_netrc_or_post_retries(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://unused-proxy.test:8080")
    with bootstrap.create_session() as session:
        assert session.trust_env is False
        assert session.auth is None and not session.proxies
        assert session.get_adapter("http://private-ollama:11434").max_retries.total == 0


def test_cli_success_and_default_settings(monkeypatch, capsys):
    for name in ("OLLAMA_BASE_URL", "JARVIS_OLLAMA_BOOTSTRAP_READY_TIMEOUT_SECONDS",
                 "JARVIS_OLLAMA_BOOTSTRAP_PULL_TIMEOUT_SECONDS", "JARVIS_OLLAMA_BOOTSTRAP_EMBED_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    run = Mock()
    monkeypatch.setattr(bootstrap, "bootstrap", run)
    assert bootstrap.main() == 0
    run.assert_called_once_with("http://jarvis-ollama:11434", ready_timeout=120,
                                pull_timeout=900, embed_timeout=180)
    assert not capsys.readouterr().err
