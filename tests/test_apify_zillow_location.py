"""Geography preparation fails before billing and never forwards Jarvis secrets."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
import requests
from filelock import FileLock, Timeout

from lib import apify
from lib.apify_actors import zillow_location as location
from lib.apify_actors.zillow_search import compile_search
from lib.config_loader import config_scope

EXPECTED = {"south": 44.4, "north": 44.8, "west": -123.3, "east": -122.9}
NATIVE_ROW = {"address": {"city": "Albany", "state": "Oregon", "country_code": "us"},
              "boundingbox": ["44.4", "44.8", "-123.3", "-122.9"]}


class Response:
    def __init__(self, value, *, status=200, raw=None):
        self.status_code = status
        self.body = json.dumps(value).encode() if raw is None else raw
        self.closed = False

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]

    def close(self):
        self.closed = True


@dataclass
class Clock:
    now: float = 1800000000
    sleeps: list[float] = field(default_factory=list)

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def harness(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(location, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(location, "time", SimpleNamespace(
        time=clock.time, monotonic=clock.time, sleep=clock.sleep))
    state = {"response": Response([deepcopy(NATIVE_ROW)]), "calls": []}

    def request(method, endpoint, **kwargs):
        state["calls"].append((method, endpoint, kwargs))
        response = state["response"]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(location, "http_request", request)
    with config_scope("cloud", overrides={"APIFY_GEOCODER_URL": location.DEFAULT_URL,
                                          "APIFY_TOKEN": "must-not-reach-the-geocoder"}):
        yield SimpleNamespace(root=tmp_path, clock=clock, state=state)


def _cache(harness):
    files = list((harness.root / "data/cache/apify-geography").glob("*.json"))
    assert len(files) == 1
    return files[0]


def test_native_us_bounds_use_one_public_get_and_private_atomic_cache(harness):
    assert location.resolve_bounds("Albany, OR") == EXPECTED
    [(method, endpoint, kwargs)] = harness.state["calls"]
    assert method == "GET" and endpoint == location.DEFAULT_URL
    assert kwargs["params"] == {"q": "Albany, OR", "countrycodes": "us", "format": "jsonv2",
                                "limit": 2, "addressdetails": 1}
    assert set(kwargs["headers"]) == {"User-Agent"}
    assert "github.com/bigsk1/jarvis-voice" in kwargs["headers"]["User-Agent"]
    assert kwargs["allow_redirects"] is False and kwargs["proxy_policy"] == "off"
    assert kwargs["timeout"] == (5, 10) and kwargs["stream"] is True
    assert "must-not-reach-the-geocoder" not in repr(harness.state["calls"])
    cache = _cache(harness)
    assert json.loads(cache.read_text())["bounds"] == EXPECTED
    assert cache.stat().st_mode & 0o777 == 0o600
    assert cache.parent.stat().st_mode & 0o777 == 0o700
    assert not list(cache.parent.glob("*.tmp"))
    assert harness.state["response"].closed


def test_casefold_cache_hit_avoids_http_rate_delay_and_cross_mode_credentials(harness):
    assert location.resolve_bounds("Albany, OR") == EXPECTED
    with config_scope("local", overrides={"APIFY_GEOCODER_URL": location.DEFAULT_URL,
                                          "APIFY_TOKEN": "another-secret"}):
        assert location.resolve_bounds("ALBANY, OR") == EXPECTED
    assert len(harness.state["calls"]) == 1
    assert harness.clock.sleeps == []


def test_alternative_endpoint_has_independent_cache_but_shared_rate_limit(harness):
    location.resolve_bounds("Albany, OR")
    with config_scope("cloud", overrides={"APIFY_GEOCODER_URL": "https://geocoder.example/search"}):
        assert location.resolve_bounds("Albany, OR") == EXPECTED
    assert len(harness.state["calls"]) == 2
    assert harness.state["calls"][-1][1] == "https://geocoder.example/search"
    assert harness.clock.sleeps == [1.0]
    assert len(list((harness.root / "data/cache/apify-geography").glob("*.json"))) == 2


@pytest.mark.parametrize("saved_age", [180 * 86400, 181 * 86400, -10])
def test_expired_or_future_cache_is_not_reused(harness, saved_age):
    location.resolve_bounds("Albany, OR")
    cache = _cache(harness)
    saved = json.loads(cache.read_text())
    saved["saved_at"] = harness.clock.now - saved_age
    cache.write_text(json.dumps(saved))
    assert location.resolve_bounds("Albany, OR") == EXPECTED
    assert len(harness.state["calls"]) == 2


@pytest.mark.parametrize("bad_cache", [
    "not json", "null", "{}", '{"saved_at":null}',
    '{"saved_at":1800000000,"bounds":{"west":true,"east":1,"south":0,"north":1}}',
])
def test_corrupt_cache_is_refetched(harness, bad_cache):
    location.resolve_bounds("Albany, OR")
    _cache(harness).write_text(bad_cache)
    assert location.resolve_bounds("Albany, OR") == EXPECTED
    assert len(harness.state["calls"]) == 2


def test_outsize_cached_integer_does_not_escape_cache_validation(harness):
    location.resolve_bounds("Albany, OR")
    cache = _cache(harness)
    saved = json.loads(cache.read_text())
    saved["bounds"]["east"] = 10 ** 500
    cache.write_text(json.dumps(saved))
    assert location.resolve_bounds("Albany, OR") == EXPECTED
    assert len(harness.state["calls"]) == 2


def test_global_file_lock_is_held_during_lookup_and_rate_shared_between_queries(harness, monkeypatch):
    original = location.http_request

    def locked_request(*args, **kwargs):
        lock_path = harness.root / "data/cache/apify-geography/lookup.lock"
        with pytest.raises(Timeout):
            with FileLock(str(lock_path), timeout=0):
                pytest.fail("A second independent lock acquired during lookup")
        return original(*args, **kwargs)

    monkeypatch.setattr(location, "http_request", locked_request)
    location.resolve_bounds("Albany, OR")
    location.resolve_bounds("Lebanon, OR")
    assert harness.clock.sleeps == [1.0]
    rate = harness.root / "data/cache/apify-geography/last-request"
    assert float(rate.read_text()) == harness.clock.now


def test_busy_lookup_fails_without_http_or_paid_submission(harness, monkeypatch):
    class BusyLock:
        def __init__(self, path, timeout):
            assert timeout == 15

        def __enter__(self):
            raise Timeout("test-held-lock")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(location, "FileLock", BusyLock)
    with pytest.raises(ValueError, match="busy; no Apify run was submitted"):
        location.resolve_bounds("Albany, OR")
    assert harness.state["calls"] == []


@pytest.mark.parametrize("endpoint", [
    "", "http://geocoder.example/search", "https://user:secret@geocoder.example/search",
    "https://@geocoder.example/search", "https://geocoder.example/search?key=secret",
    "https://geocoder.example/search#fragment", "https://geocoder.example:bad/search",
    "https://geocoder.example:65536/search", "https://geocoder.example:0/search",
    "https://[broken/search", "https://geo coder.example/search",
    "https://geo\ncoder.example/search", "https://geocoder.example\\@other.example/search",
])
def test_invalid_endpoint_fails_before_request(harness, endpoint):
    with config_scope("cloud", overrides={"APIFY_GEOCODER_URL": endpoint}):
        with pytest.raises(ValueError, match="credential-free HTTPS"):
            location.resolve_bounds("Albany, OR")
    assert harness.state["calls"] == []


@pytest.mark.parametrize("rows", [
    [], [NATIVE_ROW, NATIVE_ROW], {}, [None],
    [{**NATIVE_ROW, "address": {"country_code": "ca"}}],
    [{**NATIVE_ROW, "address": None}],
    [{**NATIVE_ROW, "boundingbox": None}],
    [{**NATIVE_ROW, "boundingbox": ["44", "45", "-123"]}],
    [{**NATIVE_ROW, "boundingbox": [False, True, -123, -122]}],
    [{**NATIVE_ROW, "boundingbox": ["44", "43", "-123", "-122"]}],
    [{**NATIVE_ROW, "boundingbox": ["44", "45", "-122", "-123"]}],
    [{**NATIVE_ROW, "boundingbox": ["44", "91", "-123", "-122"]}],
    [{**NATIVE_ROW, "boundingbox": ["44", "45", "-181", "-122"]}],
    [{**NATIVE_ROW, "boundingbox": ["nan", "45", "-123", "-122"]}],
    [{**NATIVE_ROW, "boundingbox": ["44", "inf", "-123", "-122"]}],
    [{**NATIVE_ROW, "boundingbox": ["44", "45", {}, "-122"]}],
])
def test_missing_ambiguous_non_us_or_invalid_bounds_fail_without_cache(harness, rows):
    harness.state["response"] = Response(rows)
    with pytest.raises(ValueError, match="Location lookup"):
        location.resolve_bounds("Albany, OR")
    assert not list((harness.root / "data/cache/apify-geography").glob("*.json"))
    assert harness.state["response"].closed
    assert all(call[0] == "GET" for call in harness.state["calls"])


@pytest.mark.parametrize("status", [301, 302, 403, 429, 500, 503])
def test_http_failures_are_not_retried_or_cached(harness, status):
    harness.state["response"] = Response({}, status=status)
    with pytest.raises(ValueError, match="unavailable; no Apify run was submitted"):
        location.resolve_bounds("Albany, OR")
    assert len(harness.state["calls"]) == 1
    assert harness.state["response"].closed
    assert not list((harness.root / "data/cache/apify-geography").glob("*.json"))


def test_transient_failure_can_be_retried_by_a_later_preparation_with_rate_limit(harness):
    harness.state["response"] = requests.Timeout("provider timed out")
    with pytest.raises(ValueError, match="failed; no Apify run was submitted"):
        location.resolve_bounds("Albany, OR")
    harness.state["response"] = Response([NATIVE_ROW])
    assert location.resolve_bounds("Albany, OR") == EXPECTED
    assert len(harness.state["calls"]) == 2 and harness.clock.sleeps == [1.0]


@pytest.mark.parametrize("raw,pattern", [(b"x" * 65537, "response limit"),
                                         (b"not json", "failed; no Apify")])
def test_unbounded_or_invalid_response_is_closed_without_cache(harness, raw, pattern):
    harness.state["response"] = Response(None, raw=raw)
    with pytest.raises(ValueError, match=pattern):
        location.resolve_bounds("Albany, OR")
    assert harness.state["response"].closed
    assert not list((harness.root / "data/cache/apify-geography").glob("*.json"))


def test_slow_stream_stops_at_response_deadline(harness, monkeypatch):
    response = harness.state["response"]

    def slow_chunks(chunk_size):
        harness.clock.now += 16
        yield response.body

    monkeypatch.setattr(response, "iter_content", slow_chunks)
    with pytest.raises(ValueError, match="response limit"):
        location.resolve_bounds("Albany, OR")
    assert response.closed
    assert not list((harness.root / "data/cache/apify-geography").glob("*.json"))


def test_geography_errors_stop_actor_preparation_before_any_submission(harness):
    harness.state["response"] = Response([NATIVE_ROW, NATIVE_ROW])
    with pytest.raises(ValueError, match="ambiguous"):
        compile_search("maxcopell/zillow-scraper", {
            "locations": ["Albany"], "listing_status": "for_sale"})
    assert [method for method, _, _ in harness.state["calls"]] == ["GET"]


def test_gateway_cannot_submit_a_paid_actor_after_ambiguous_geography(harness, monkeypatch):
    harness.state["response"] = Response([NATIVE_ROW, NATIVE_ROW])
    client = apify.ApifyClient(apify.ApifySettings(
        "test-token", 1800, 2048, 1, 30, 20, frozenset({"maxcopell/zillow-scraper"})))

    def unexpected(*_args, **_kwargs):
        pytest.fail("Actor prepare/start reached after invalid geography")

    monkeypatch.setattr(client, "prepare", unexpected)
    monkeypatch.setattr(client, "start", unexpected)
    with pytest.raises(ValueError, match="ambiguous"):
        apify.run_actor({"actor": "maxcopell/zillow-scraper", "search": {
            "locations": ["Albany"], "listing_status": "for_sale"}}, client=client)


def test_run_attribution_is_private_mode_run_and_actor_bound(harness):
    assert location.remember_run_geography("Run123", "Actor123") is True
    assert location.run_geography("Run123", "Actor123") == {"provider": "openstreetmap"}
    assert location.run_geography("Other123", "Actor123") is None
    assert location.run_geography("Run123", "OtherActor") is None
    with config_scope("local"):
        assert location.run_geography("Run123", "Actor123") is None
    path = harness.root / "data/cache/apify-geography/runs/cloud/Run123.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert set(json.loads(path.read_text())) == {"run_id", "actor_id", "geography_attribution"}
    assert harness.state["calls"] == []


@pytest.mark.parametrize("run_id", ["../escape", "/tmp/escape", "", "has-dash", None])
def test_run_attribution_rejects_non_native_id_without_writing(harness, run_id):
    assert location.remember_run_geography(run_id, "Actor123") is False
    assert location.run_geography(run_id, "Actor123") is None
    assert not list(harness.root.rglob("*.json"))


@pytest.mark.parametrize("content", ["not JSON", "[]", "{}", "x" * 4097,
    '{"run_id":"Other","actor_id":"Actor123","geography_attribution":{"provider":"openstreetmap"}}',
    '{"run_id":"Run123","actor_id":"Actor123","geography_attribution":{"provider":"guessed"}}'])
def test_unusable_attribution_record_never_invents_a_credit(harness, content):
    assert location.remember_run_geography("Run123", "Actor123")
    path = harness.root / "data/cache/apify-geography/runs/cloud/Run123.json"
    path.write_text(content)
    assert location.run_geography("Run123", "Actor123") is None
