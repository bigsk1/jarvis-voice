"""Account status transport/schema/cache coverage; no real providers or sockets."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import ollama_cloud_status as status
import pytest
import requests


class Response:
    def __init__(self, payload=None, code=200, headers=None):
        self.status_code = code
        self.payload = payload
        self.headers = headers or {}

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    status._CACHE.clear()
    monkeypatch.setattr(requests, "get", Mock(return_value=Response(code=404)))
    monkeypatch.setattr(requests, "post", Mock(return_value=Response(code=404)))
    yield
    status._CACHE.clear()


def read(*, key="test-secret", mode="cloud", base="http://daemon.invalid:11434", provider="ollama"):
    return status.get_cloud_status(
        mode=mode, api_key=key, base_url=base, effective_provider=provider
    )


def usage(**totals):
    return {"range": "7d", "scope": "self", "totals": totals}


def test_monthly_balance_and_usage_only_expose_allowlisted_fields(monkeypatch):
    balance = {
        "included": {
            "balance_usd": 72.5,
            "allowance_usd": 100,
            "period": {"from": "2026-10-01T00:00:00Z", "until": "2026-11-01T00:00:00Z"},
            "email": "private@example.com",
        },
        "purchased": {"balance_usd": 25},
        "token": "secret",
    }
    activity = usage(
        request_count=15,
        usage_usd=0.01718,
        input_tokens=106000,
        cached_input_tokens=46000,
        output_tokens=13600,
    )
    activity["buckets"] = [{"identity": "private"}]
    requests.get.side_effect = [Response(balance), Response(activity)]
    result = read()
    assert result["balance"]["data"]["included"]["balance_usd"] == 72.5
    assert result["usage"]["data"]["totals"] == activity["totals"]
    assert result["quota_available"] is None
    assert result["signed_in"] is True
    text = json.dumps(result)
    assert "secret" not in text and "private" not in text and "buckets" not in text
    for call in requests.get.call_args_list:
        assert call.args[0].startswith("https://ollama.com/api/")
        assert call.kwargs["headers"] == {"Authorization": "Bearer test-secret"}
        assert call.kwargs["allow_redirects"] is False
        assert call.kwargs["timeout"] == (2, 4)
    requests.post.assert_not_called()


def test_legacy_remaining_percent_and_count_only_history():
    requests.get.side_effect = [
        Response(
            {
                "included": {
                    "session": {"remaining_percent": 75, "resets_at": "2026-11-01T07:00:00Z"},
                    "weekly": {"remaining_percent": 0},
                },
                "purchased": {"balance_usd": 0},
            }
        ),
        Response(usage(request_count=100)),
    ]
    result = read()
    assert result["balance"]["data"]["included"]["session"]["remaining_percent"] == 75
    assert result["balance"]["data"]["included"]["weekly"]["remaining_percent"] == 0
    assert result["usage"]["data"]["totals"] == {"request_count": 100}
    assert result["quota_available"] is None


@pytest.mark.parametrize("mode,key", [("cloud", ""), ("local", "must-ignore-local-key")])
def test_daemon_path_never_receives_cloud_key(mode, key):
    requests.post.return_value = Response({"id": "private", "plan": "pro"})
    requests.get.side_effect = [
        Response({"purchased": {"balance_usd": 0}}),
        Response(usage(request_count=0)),
    ]
    result = read(mode=mode, key=key)
    assert result["connection_mode"] == "signed_in_host"
    assert result["plan"] == "pro"
    for call in requests.post.call_args_list + requests.get.call_args_list:
        assert call.args[0].startswith("http://daemon.invalid:11434/api/")
        assert call.kwargs["headers"] == {}
    assert "private" not in json.dumps(result)


def test_old_daemon_keeps_signin_without_inventing_quota():
    requests.post.return_value = Response({"email": "private@example.com", "plan": "free"})
    result = read(key="")
    assert result["signed_in"] is True
    assert result["balance"] == {"status": "unsupported", "data": None}
    assert result["usage"]["status"] == "unsupported"


def test_partial_failure_preserves_good_balance():
    requests.get.side_effect = [
        Response({"purchased": {"balance_usd": 3}}),
        requests.Timeout("secret-url"),
    ]
    result = read()
    assert result["balance"]["data"]["purchased"]["balance_usd"] == 3
    assert result["usage"]["status"] == "unavailable"
    assert result["signed_in"] is True and result["reachable"] is True
    assert "secret-url" not in json.dumps(result)


def test_usage_can_succeed_independently():
    requests.get.side_effect = [Response(code=503), Response(usage(request_count=4))]
    result = read()
    assert result["balance"]["status"] == "unavailable"
    assert result["usage"]["data"]["totals"]["request_count"] == 4


@pytest.mark.parametrize("code", [401, 403])
def test_auth_rejection_with_non_json_body_is_explicit(code):
    requests.get.return_value = Response(ValueError("private-body"), code=code)
    result = read()
    assert result["signed_in"] is False and result["reachable"] is True
    assert result["balance"]["status"] == "unauthorized"


def test_outage_and_redirect_are_not_reported_as_signed_in():
    requests.get.side_effect = requests.ConnectionError("secret")
    assert read()["reachable"] is False
    status._CACHE.clear()
    requests.get.side_effect = None
    requests.get.return_value = Response(code=302, headers={"Location": "https://other.invalid"})
    result = read()
    assert result["signed_in"] == "unknown"
    assert result["balance"]["status"] == "unavailable"


@pytest.mark.parametrize("bad", [True, -1, float("inf"), float("nan"), "20", 10**400])
def test_invalid_numbers_are_not_turned_into_zero(bad):
    requests.get.side_effect = [
        Response({"included": {"balance_usd": bad}}),
        Response(usage(request_count=bad)),
    ]
    result = read()
    assert result["balance"]["status"] == "invalid"
    assert result["usage"]["status"] == "invalid"


def test_invalid_percent_dates_scope_and_json():
    assert status._balance({"included": {"session": {"remaining_percent": 101}}}) is None
    assert status._balance(
        {"included": {"session": {"remaining_percent": 1, "resets_at": "javascript:evil"}}}
    ) == {"included": {"session": {"remaining_percent": 1}}}
    assert status._usage({"range": "7d", "scope": "team", "totals": {"request_count": 1}}) is None
    requests.get.return_value = Response(ValueError("bad json"))
    assert read()["balance"]["status"] == "invalid"


def test_cache_identity_scope_and_ttl(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(status.time, "monotonic", lambda: now[0])
    requests.get.side_effect = lambda *a, **k: (
        Response({"purchased": {"balance_usd": 5}})
        if a[0].endswith("balance")
        else Response(usage(request_count=1))
    )
    first = read()
    first["balance"]["data"]["purchased"]["balance_usd"] = 999
    assert read(provider="xai")["balance"]["data"]["purchased"]["balance_usd"] == 5
    assert read(provider="xai")["effective_provider"] == "xai"
    assert requests.get.call_count == 2
    now[0] += 59
    read()
    assert requests.get.call_count == 2
    now[0] += 2
    read()
    assert requests.get.call_count == 4
    read(key="different-account")
    assert requests.get.call_count == 6
    read(mode="local")
    assert requests.get.call_count == 8
    assert all("test-secret" not in cache_key for cache_key in status._CACHE)


@pytest.mark.parametrize("retry", ["60", "180"])
def test_rate_limit_waits_and_does_not_probe_second_endpoint(monkeypatch, retry):
    now = [100.0]
    monkeypatch.setattr(status.time, "monotonic", lambda: now[0])
    requests.get.return_value = Response(code=429, headers={"Retry-After": retry})
    result = read()
    assert result["usage"]["status"] == "rate_limited"
    assert requests.get.call_count == 1
    now[0] += int(retry) - 1
    read()
    assert requests.get.call_count == 1
    now[0] += 2
    read()
    assert requests.get.call_count == 2


def test_concurrent_loads_are_coalesced():
    requests.get.return_value = Response({"purchased": {"balance_usd": 0}})
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _: read(), range(10)))
    assert all(r["signed_in"] is True for r in results)
    assert requests.get.call_count == 2


@pytest.mark.parametrize(
    "base",
    ["file:///tmp/key", "http://user:secret@host", "http://[bad", "http://host?token=secret"],
)
def test_invalid_daemon_configuration_never_requests(base):
    result = read(key="", base=base)
    assert result == {"ok": False, "error": "Invalid Ollama host configuration"}
    requests.get.assert_not_called()
    requests.post.assert_not_called()


def test_signin_link_is_only_official_origin():
    requests.post.return_value = Response(
        {"signin_url": "https://ollama.com/signin?code=abc"}, code=401
    )
    assert read(key="")["signin_url"] == "https://ollama.com/signin?code=abc"
    status._CACHE.clear()
    requests.post.return_value = Response(
        {"signin_url": "https://ollama.com.evil.invalid/"}, code=401
    )
    assert read(key="")["signin_url"] is None


def test_slow_account_does_not_block_cached_or_other_accounts():
    started = threading.Event()
    release = threading.Event()

    def get(url, **kwargs):
        if kwargs["headers"].get("Authorization") == "Bearer slow":
            started.set()
            assert release.wait(timeout=3)
        return (
            Response({"purchased": {"balance_usd": 0}})
            if url.endswith("balance")
            else Response(usage(request_count=1))
        )

    requests.get.side_effect = get
    read(key="cached")
    with ThreadPoolExecutor(max_workers=3) as pool:
        slow = pool.submit(read, key="slow")
        try:
            assert started.wait(timeout=1)
            assert pool.submit(read, key="cached").result(timeout=1)["signed_in"] is True
            assert pool.submit(read, key="other").result(timeout=1)["signed_in"] is True
        finally:
            release.set()
        assert slow.result(timeout=1)["signed_in"] is True
