"""Real native-client catalog reads with finite fixtures; no external calls."""

from __future__ import annotations

import io
import json
import threading
import time
from contextvars import ContextVar
from dataclasses import replace

import pytest
from config_loader import config_scope, get_active_config_mode, get_config_value
from stash_helper import get_space, parse_stash_ref
from urllib3.response import HTTPResponse

from lib import apify_catalog as catalog
from lib.apify import API_BASE, ApifyClient, ApifyError, ApifySettings
from lib.external_results import project_external_result


def actor(index: int, *, publisher="apify", title="Maps scraper", **extra):
    return {"id": f"Actor{index:03}", "username": publisher, "name": f"scraper-{index}",
            "title": title, "description": "Find maps and places",
            "stats": {"actorReviewCount": 0, "totalUsers30Days": 0}, **extra}


class Response:
    def __init__(self, payload, *, status=200):
        self.status_code = status
        self.headers = {"Content-Type": "application/json"}
        self.raw = HTTPResponse(body=io.BytesIO(json.dumps(payload).encode()), preload_content=False)
        self.closed = False

    def close(self):
        self.closed = True
        self.raw.close()


class NativeAPI:
    def __init__(self, *, official=None, trusted=()):
        self.official = official if official is not None else [actor(index) for index in range(5)]
        self.actors = {reference.replace("/", "~"): details for reference, details in trusted}
        self.calls, self.responses = [], []
        self.store_override = None
        self.before_read = None
        self.lock = threading.Lock()

    def request(self, method, url, **kwargs):
        assert method == "GET"
        assert url.startswith(API_BASE + "/")
        assert kwargs["headers"] == {"Authorization": "Bearer catalog-test-token"}
        assert kwargs["proxy_policy"] == "off"
        assert kwargs["stream"] is True and kwargs["allow_redirects"] is False
        path = url[len(API_BASE):]
        with self.lock:
            self.calls.append((method, path, kwargs))
        if self.before_read is not None:
            self.before_read(path)
        status = 200
        if path == "/store":
            if isinstance(self.store_override, Response):
                response = self.store_override
                with self.lock:
                    self.responses.append(response)
                return response
            params = kwargs["params"]
            assert params["username"] == "apify"
            assert "includeUnrunnableActors" not in params
            assert params["responseFormat"] == "full"
            rows = [details for details in self.official
                    if details["username"] == params["username"]
                    and catalog._relevant(details, params["search"])]
            total = len(rows)
            rows = rows[params["offset"]:params["offset"] + params["limit"]]
            payload = {"data": {"total": total, "offset": params["offset"],
                                 "limit": params["limit"], "count": len(rows), "items": rows}}
            if self.store_override is not None:
                payload = self.store_override(params)
        elif path.startswith("/acts/"):
            details = self.actors.get(path[len("/acts/"):])
            payload, status = ({"data": details}, 200) if details is not None else ({}, 404)
        else:
            pytest.fail("Catalog must not fetch builds, run Actors or read a dataset")
        response = Response(payload, status=status)
        with self.lock:
            self.responses.append(response)
        return response

    def client(self, references=()):
        settings = ApifySettings("catalog-test-token", 1800, 2048, 1.0, 30, 20, frozenset(references))
        return ApifyClient(settings, request=self.request)


@pytest.fixture(autouse=True)
def isolated_mode_and_stash(tmp_path):
    with config_scope("local", {"STASH_DIR": str(tmp_path / "stash"),
                                "CATALOG_CONTEXT_MARKER": "selected-local"}):
        yield


def retained(data):
    space_id, file_id = parse_stash_ref(data["raw_ref"])
    space = get_space(space_id)
    saved = next(item for item in space.meta["files"] if item["file_id"] == file_id)
    return json.loads((space.space_path / saved["stored_name"]).read_text())


def settle_reads(api):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with api.lock:
            if len(api.responses) == len(api.calls) and all(response.closed for response in api.responses):
                return
        time.sleep(0.005)
    pytest.fail("Fixture reads did not close after release")


def test_official_owner_filter_is_upfront_with_original_query_and_default_limit():
    api = NativeAPI(official=[actor(1), actor(2, publisher="unapproved")])
    response = catalog.search_actors({"keywords": "Maps"}, client=api.client())

    assert response["ok"] is True
    data, result = response["data"], response["data"]["result"]
    assert data["source"] == {"provider": "apify", "tool": "search-actors", "mode": "local"}
    assert data["execution"]["status"] == "SUCCEEDED"
    assert result["complete"] is True and result["total_items"] == 1
    assert result["sample_items"][0]["actor"] == "apify/scraper-1"
    assert result["sample_items"][0]["eligibility"] == "official_apify"
    assert api.calls[0][2]["params"] == {"username": "apify", "search": "Maps",
        "responseFormat": "full", "sortBy": "relevance", "offset": 0, "limit": 5}
    assert "unapproved" not in json.dumps(response)
    assert "unapproved" not in json.dumps(retained(data))
    assert all(response.closed for response in api.responses)


def test_relevant_trusted_exceptions_are_additive_without_quality_thresholds():
    low_rated = actor(20, publisher="trusted", stats={"actorReviewRating": 1.2,
        "actorReviewCount": 1, "totalUsers30Days": 0})
    unrated = actor(21, publisher="trusted", stats={})
    irrelevant = actor(22, publisher="trusted", title="Weather", description="Forecasts only")
    trusted = [(f"trusted/scraper-{index}", details)
               for index, details in ((20, low_rated), (21, unrated), (22, irrelevant))]
    api = NativeAPI(official=[actor(1)], trusted=trusted)
    result = catalog.search_actors({"keywords": "maps"},
        client=api.client(reference for reference, _ in trusted))["data"]["result"]

    assert [item["actor_id"] for item in result["sample_items"]] == ["Actor020", "Actor021", "Actor001"]
    assert result["sample_items"][0]["quality"] == {"rating": 1.2, "reviews": 1, "monthly_users": 0}
    assert result["sample_items"][1]["quality"] == {}
    assert result["policy"]["quality_metrics"] == "advisory_only"
    assert result["policy"]["trusted_exceptions"] == sorted(reference for reference, _ in trusted)
    assert result["policy"]["exception_scan"] == {"configured": 3, "checked": 3,
                                                  "matched": 2, "complete": True}
    assert result["total_items"] == 3 and result["complete"] is True


def test_all_thirty_exceptions_are_scanned_and_each_worker_inherits_scope():
    trusted = [(f"trusted/scraper-{index}", actor(index, publisher="trusted",
        title="Maps" if index >= 125 else "Weather", description="Unique " * 60))
        for index in range(100, 130)]
    api, marker = NativeAPI(official=[], trusted=trusted), ContextVar("catalog_test_marker")
    observations = []
    marker.set("request-specific")

    def observe(path):
        observations.append((marker.get(), get_active_config_mode(),
                             get_config_value("CATALOG_CONTEXT_MARKER")))

    api.before_read = observe
    response = catalog.search_actors({"keywords": "maps"},
        client=api.client(reference for reference, _ in trusted))
    result = response["data"]["result"]

    assert len(api.calls) == 31
    assert observations == [("request-specific", "local", "selected-local")] * 31
    assert [item["actor_id"] for item in result["sample_items"]] == [f"Actor{index}" for index in range(125, 130)]
    assert result["policy"]["exception_scan"]["checked"] == 30
    projection = project_external_result(response["data"])
    assert projection["result"]["sample_count"] == 5
    assert projection["result"]["policy"]["trusted_exceptions"] == sorted(reference for reference, _ in trusted)
    assert len(json.dumps(projection, separators=(",", ":"))) <= 6000


def test_native_id_and_canonical_aliases_dedupe_exactly_and_official_alias_stays_in_store():
    community, official = actor(20, publisher="trusted"), actor(1)
    trusted = [("Actor020", community), ("trusted/scraper-20", community),
               ("apify/scraper-1", official)]
    api = NativeAPI(official=[official], trusted=trusted)
    result = catalog.search_actors({}, client=api.client(reference for reference, _ in trusted))["data"]["result"]

    assert [item["actor_id"] for item in result["sample_items"]] == ["Actor020", "Actor001"]
    assert result["total_items"] == 2
    assert result["policy"]["exception_scan"]["checked"] == 3


def test_relevant_exceptions_prefix_has_stable_pages_and_short_last_page():
    trusted = [(f"trusted/scraper-{index}", actor(index, publisher="trusted")) for index in (20, 21, 22)]
    api = NativeAPI(trusted=trusted)
    client = api.client(reference for reference, _ in trusted)
    ids = []
    for offset in (0, 3, 6, 9):
        result = catalog.search_actors({"keywords": "maps", "limit": 3, "offset": offset},
                                       client=client)["data"]["result"]
        assert result["pagination"]["available"] is True
        assert result["total_items"] == 8
        assert result["pagination"]["next_offset"] == (offset + 3 if offset < 6 else None)
        assert result["pagination"]["has_more"] is (offset < 6)
        ids.extend(item["actor_id"] for item in result["sample_items"])
    assert ids == ["Actor020", "Actor021", "Actor022", *[f"Actor{index:03}" for index in range(5)]]


@pytest.mark.parametrize("offset,expected", [(0, ["Actor000"]), (1, [])])
def test_single_official_result_is_complete_first_page_and_valid_empty_later_page(offset, expected):
    api = NativeAPI(official=[actor(0)])
    data = catalog.search_actors({"offset": offset}, client=api.client())["data"]
    assert data["execution"]["status"] == "SUCCEEDED"
    assert data["result"]["complete"] is (offset == 0)
    assert data["result"]["pagination"]["available"] is True
    assert [item["actor_id"] for item in data["result"]["sample_items"]] == expected


def test_empty_keyword_match_does_not_retry_or_widen_query():
    api = NativeAPI(trusted=[("trusted/scraper-20", actor(20, publisher="trusted"))])
    data = catalog.search_actors({"keywords": "no-such-capability"},
        client=api.client(["trusted/scraper-20"]))["data"]
    assert data["result"]["sample_items"] == []
    assert data["result"]["total_items"] == 0
    assert len(api.calls) == 2
    assert next(call[2]["params"]["search"] for call in api.calls if call[1] == "/store") == "no-such-capability"


@pytest.mark.parametrize("offset", [0, 2])
def test_unavailable_trusted_reference_makes_combined_offsets_explicitly_unavailable(offset):
    api = NativeAPI(trusted=[("trusted/scraper-20", actor(20, publisher="trusted"))])
    response = catalog.search_actors({"keywords": "maps", "offset": offset},
        client=api.client(["trusted/scraper-20", "trusted/missing"]))
    data, result = response["data"], response["data"]["result"]
    assert data["execution"]["status"] == "PARTIAL"
    assert data["limits"]["catalog_partial"] is True
    assert result["total_items"] is None and result["complete"] is False
    assert result["pagination"]["available"] is False
    assert result["pagination"]["next_offset"] is None and result["pagination"]["has_more"] is None
    assert result["policy"]["exception_scan"] == {"configured": 2, "checked": 2,
        "matched": 1, "complete": False, "unavailable_references": ["trusted/missing"]}
    assert bool(result["sample_items"]) is (offset == 0)
    assert "looked up directly" in response["speech"]


def test_mismatched_trusted_identity_is_not_shown_or_archived():
    api = NativeAPI(trusted=[("trusted/scraper-20", actor(99, publisher="outsider"))])
    response = catalog.search_actors({}, client=api.client(["trusted/scraper-20"]))
    assert "outsider" not in json.dumps(response)
    assert "Actor099" not in json.dumps(retained(response["data"]))
    assert response["data"]["result"]["policy"]["exception_scan"]["complete"] is False


def test_unexpected_community_store_card_is_filtered_before_retention():
    api = NativeAPI()
    api.store_override = lambda params: {"data": {"total": 2, "offset": params["offset"],
        "items": [actor(1), actor(99, publisher="outsider")]}}
    response = catalog.search_actors({}, client=api.client())
    assert response["data"]["execution"]["status"] == "PARTIAL"
    assert response["data"]["result"]["total_items"] is None
    assert "outsider" not in json.dumps(response)
    assert "Actor099" not in json.dumps(retained(response["data"]))


def test_official_read_failure_is_an_error_with_closed_response_and_no_archive(tmp_path):
    api = NativeAPI()
    api.store_override = Response({"error": "never echo upstream contents"}, status=503)
    with pytest.raises(ApifyError, match="HTTP 503"):
        catalog.search_actors({}, client=api.client())
    assert api.responses[0].closed is True
    assert not list((tmp_path / "stash").rglob("external-response*"))


@pytest.mark.parametrize("offset", [0, 3])
def test_soft_scan_deadline_bounds_concurrency_marks_partial_and_keeps_all_trusted_refs(monkeypatch, offset):
    trusted = [(f"trusted/scraper-{index}", actor(index, publisher="trusted")) for index in range(20, 50)]
    api, release = NativeAPI(trusted=trusted), threading.Event()
    active = 0

    def block_exceptions(path):
        nonlocal active
        if path != "/store":
            with api.lock:
                active += 1
            assert release.wait(3)

    api.before_read = block_exceptions
    monkeypatch.setattr(catalog, "_WORK_SECONDS", 0.1)
    started = time.monotonic()
    try:
        response = catalog.search_actors({"offset": offset},
            client=api.client(reference for reference, _ in trusted), deadline=started + 2)
        assert time.monotonic() - started < 1
        result = response["data"]["result"]
        assert 1 <= active <= 4
        assert len(api.calls) == 1 + active
        assert result["policy"]["exception_scan"]["checked"] == 0
        assert result["policy"]["exception_scan"]["pending_references"] == sorted(reference for reference, _ in trusted)
        assert result["policy"]["trusted_exceptions"] == sorted(reference for reference, _ in trusted)
        assert result["pagination"]["available"] is False
        assert bool(result["sample_items"]) is (offset == 0)
    finally:
        calls_at_return = len(api.calls)
        release.set()
        settle_reads(api)
        assert len(api.calls) == calls_at_return


@pytest.mark.parametrize("cancelled", [False, True])
def test_hard_deadline_or_cancellation_never_archives_late_result(tmp_path, cancelled):
    api, release, entered, stop = NativeAPI(), threading.Event(), threading.Event(), threading.Event()

    def block(path):
        entered.set()
        assert release.wait(3)

    api.before_read = block
    if cancelled:
        timer = threading.Timer(0.05, stop.set)
        timer.start()
    try:
        with pytest.raises(ApifyError, match="cancelled|deadline"):
            catalog.search_actors({}, client=api.client(), deadline=time.monotonic() + 0.15,
                                  cancel_event=stop)
        assert entered.is_set()
        assert not list((tmp_path / "stash").rglob("external-response*"))
    finally:
        release.set()
        settle_reads(api)
        if cancelled:
            timer.join()


@pytest.mark.parametrize("arguments", [{"unknown": True}, {"keywords": []}, {"limit": 0},
    {"limit": 11}, {"limit": True}, {"offset": -1}, {"offset": True}, {"offset": 1 << 53}])
def test_invalid_public_inputs_fail_before_any_read(arguments):
    api = NativeAPI()
    with pytest.raises(ApifyError):
        catalog.search_actors(arguments, client=api.client())
    assert api.calls == []


def test_large_integer_quality_is_exact_in_preview_and_original_numeric_in_archive():
    api = NativeAPI(official=[actor(1, stats={"actorReviewCount": (1 << 60) + 1})])
    data = catalog.search_actors({}, client=api.client())["data"]
    assert data["result"]["sample_items"][0]["quality"]["reviews"] == str((1 << 60) + 1)
    assert data["limits"]["integer_strings"] is True
    assert retained(data)["sample_items"][0]["quality"]["reviews"] == (1 << 60) + 1


def test_explicit_client_settings_remain_frozen_after_discovery():
    api = NativeAPI()
    client = api.client()
    before = replace(client.settings)
    catalog.search_actors({}, client=client)
    assert client.settings == before
