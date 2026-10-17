"""Deterministic Apify boundary checks; no operator config or provider calls."""

from __future__ import annotations

import gzip
import io
import json
from dataclasses import replace

import pytest
import requests
from urllib3.response import HTTPResponse

from lib import apify
from lib.config_loader import config_scope

RUN = "RunExample123"
ACTOR = "ActorExample123"
BUILD = "BuildExample123"
DATASET = "DatasetExample123"
STORE = "StoreExample123"


class Response:
    def __init__(self, data=None, *, status=200, raw=None, content_type="application/json"):
        self.body = raw if raw is not None else json.dumps(data).encode()
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        self.closed = True


@pytest.fixture
def settings():
    return apify.ApifySettings("test-only-token", 1800, 2048, 1.0, 30, 20, frozenset())


@pytest.fixture
def fake(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("STASH_DIR", str(tmp_path / "stash"))
    actor = {"id": ACTOR, "username": "example", "name": "scraper",
        "actorPermissionLevel": "LIMITED_PERMISSIONS", "defaultRunOptions": {"memoryMbytes": 1024}}
    schema = {"type": "object", "properties": {"query": {"type": "string"}},
              "required": ["query"], "additionalProperties": False}
    build = {"id": BUILD, "actId": ACTOR, "buildNumber": "1.2.3", "status": "SUCCEEDED",
             "actorDefinition": {"input": schema, "minMemoryMbytes": 128}}
    run = {"id": RUN, "actId": ACTOR, "buildId": BUILD, "status": "SUCCEEDED",
        "defaultDatasetId": DATASET, "defaultKeyValueStoreId": STORE,
        "storageIds": {"datasets": {"default": DATASET, "secondary": "SecondaryDataset"}}}
    responses = {
        ("GET", "/acts/example~scraper"): {"data": actor},
        ("GET", f"/acts/{ACTOR}/builds/default"): {"data": build},
        ("POST", f"/acts/{ACTOR}/runs"): {"data": run},
        ("GET", f"/actor-runs/{RUN}"): {"data": run},
        ("GET", f"/datasets/{DATASET}"): {"data": {"id": DATASET, "itemCount": 4}},
        ("GET", f"/datasets/{DATASET}/items"): [{"title": "first", "nested": {"id": "opaqueA"}},
                                              {"title": "second", "nested": [1, True, None]}],
        ("GET", f"/key-value-stores/{STORE}/records/OUTPUT"): {"text": "actual output"},
        ("POST", f"/actor-runs/{RUN}/abort"): {"data": {**run, "status": "ABORTING"}},
    }
    calls = []

    def request(method, url, **kwargs):
        assert url.startswith(apify.API_BASE + "/")
        assert kwargs["headers"]["Authorization"] == "Bearer test-only-token"
        assert kwargs["allow_redirects"] is False
        assert kwargs["proxy_policy"] == "off"
        path = url[len(apify.API_BASE):]
        calls.append((method, path, kwargs))
        value = responses[method, path]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, Response) else Response(value)

    client = apify.ApifyClient(replace(settings, allowed_actors=frozenset({"example/scraper"})), request=request)
    return client, responses, calls, actor, build, run


def test_disabled_and_missing_mode_token_do_not_inherit_other_mode(monkeypatch):
    with config_scope("local", overrides={"APIFY_MCP_ENABLED": "false", "APIFY_TOKEN": ""}):
        with pytest.raises(apify.ApifyError, match="disabled"):
            apify.ApifySettings.load()
    with config_scope("cloud", overrides={"APIFY_MCP_ENABLED": "true", "APIFY_TOKEN": ""}):
        with pytest.raises(apify.ApifyError, match="missing"):
            apify.ApifySettings.load()


@pytest.mark.parametrize("key,value", [("APIFY_MAX_CHARGE_USD", "nan"),
    ("APIFY_POLL_SECONDS", "301"), ("APIFY_RUN_TIMEOUT_SECONDS", "0"),
    ("APIFY_RESULT_PAGE_SIZE", "101"), ("APIFY_ALLOWED_ACTORS", "https://bad.example")])
def test_operator_limits_fail_closed(key, value):
    with config_scope("cloud", overrides={"APIFY_MCP_ENABLED": "true", "APIFY_TOKEN": "unit-token", key: value}):
        with pytest.raises(apify.ApifyError):
            apify.ApifySettings.load()


def test_five_minute_poll_is_supported_and_token_is_not_in_repr():
    with config_scope("cloud", overrides={"APIFY_MCP_ENABLED": "true", "APIFY_TOKEN": "unit-token",
                                          "APIFY_POLL_SECONDS": "300"}):
        settings = apify.ApifySettings.load()
        assert settings.poll_seconds == 300
        assert "unit-token" not in repr(settings)


def test_start_pins_validated_build_and_never_enables_restart(fake):
    client, _, calls, *_ = fake
    prepared = client.prepare("example/scraper", {"query": "user request"})
    handle = client.start(prepared)
    assert handle == {"run_id": RUN, "actor_id": ACTOR, "build_id": BUILD,
                      "default_dataset_id": DATASET, "default_key_value_store_id": STORE}
    posts = [call for call in calls if call[0] == "POST"]
    assert len(posts) == 1
    assert posts[0][2]["params"] == {"build": "1.2.3", "timeout": 1800, "memory": 1024,
        "maxTotalChargeUsd": 1.0, "waitForFinish": 0, "restartOnError": "false",
        "forcePermissionLevel": "LIMITED_PERMISSIONS"}
    assert posts[0][2]["json"] == {"query": "user request"}


@pytest.mark.parametrize("requested", ["example/scraper", ACTOR])
@pytest.mark.parametrize("owner", ["apify", "trusted"])
def test_mismatched_actor_lookup_cannot_start_another_eligible_actor(fake, requested, owner):
    client, responses, calls, actor, build, run = fake
    returned_id = "OtherEligibleActor123"
    returned = {**actor, "id": returned_id, "username": owner, "name": "different"}
    path = "/acts/" + requested.replace("/", "~")
    responses["GET", path] = {"data": returned}
    responses["GET", f"/acts/{returned_id}/builds/default"] = {
        "data": {**build, "actId": returned_id}}
    responses["POST", f"/acts/{returned_id}/runs"] = {
        "data": {**run, "actId": returned_id}}
    client.settings = replace(client.settings, allowed_actors=frozenset({f"{owner}/different"}))

    with pytest.raises(apify.ApifyError, match="mismatched Actor identity"):
        apify.run_actor({"actor": requested, "input": {"query": "requested work"}}, client=client)

    assert [(method, url) for method, url, _ in calls] == [("GET", path)]


def test_native_actor_id_resolves_and_submits_that_same_actor(fake):
    client, responses, calls, actor, *_ = fake
    responses["GET", f"/acts/{ACTOR}"] = {"data": actor}
    result = apify.run_actor({"actor": ACTOR, "input": {"query": "requested work"}}, client=client)
    assert result["data"]["execution"]["actor_id"] == ACTOR
    assert [path for method, path, _ in calls if method == "POST"] == [f"/acts/{ACTOR}/runs"]


@pytest.mark.parametrize("cap", ["1536", "2048.5"])
def test_invalid_configured_memory_cap_blocks_only_new_starts(fake, cap):
    client, _, calls, *_ = fake
    with config_scope("cloud", overrides={"APIFY_MCP_ENABLED": "true",
            "APIFY_TOKEN": "test-only-token", "APIFY_ALLOWED_ACTORS": "example/scraper",
            "APIFY_MAX_MEMORY_MB": cap}):
        client.settings = apify.ApifySettings.load()
        with pytest.raises(apify.ApifyError, match="APIFY_MAX_MEMORY_MB"):
            apify.run_actor({"actor": "example/scraper", "input": {"query": "x"}}, client=client)
        assert calls == []
        assert apify.read_result({"run_id": RUN}, client=client)["ok"] is True
    assert [method for method, _, _ in calls] == ["GET"]


@pytest.mark.parametrize("cap", [128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768])
def test_supported_memory_caps_preserve_clamping_and_run_limits(fake, cap):
    client, _, calls, actor, *_ = fake
    actor["defaultRunOptions"]["memoryMbytes"] = 4096
    client.settings = replace(client.settings, memory_mb=cap)
    apify.run_actor({"actor": "example/scraper", "input": {"query": "x"}}, client=client)
    post = next(call for call in calls if call[0] == "POST")
    assert post[2]["params"]["memory"] == min(cap, 4096)
    assert post[2]["params"]["maxTotalChargeUsd"] == client.settings.max_charge_usd
    assert post[2]["params"]["forcePermissionLevel"] == "LIMITED_PERMISSIONS"


@pytest.mark.parametrize("field", ["default", "minimum"])
def test_unsupported_derived_memory_never_submits(fake, field):
    client, _, calls, actor, build, _ = fake
    if field == "default":
        actor["defaultRunOptions"]["memoryMbytes"] = 1536
    else:
        build["actorDefinition"]["minMemoryMbytes"] = 1536
    with pytest.raises(apify.ApifyError, match="Actor memory allocation"):
        apify.run_actor({"actor": "example/scraper", "input": {"query": "x"}}, client=client)
    assert [method for method, _, _ in calls] == ["GET", "GET"]


@pytest.mark.parametrize("actor", ["../evil", "https://example.org", "user/actor:tool", "user/actor?token=x"])
def test_actor_is_identifier_not_endpoint(fake, actor):
    client, _, calls, *_ = fake
    with pytest.raises(apify.ApifyError):
        client.prepare(actor, {"query": "x"})
    assert calls == []


@pytest.mark.parametrize("inputs", [{}, {"query": 3}, {"query": "x", "unknown": True},
                                    {"query": float("nan")}])
def test_invalid_inputs_never_submit(fake, inputs):
    client, _, calls, *_ = fake
    with pytest.raises(apify.ApifyError):
        client.prepare("example/scraper", inputs)
    assert not any(call[0] == "POST" for call in calls)


def test_schema_remote_refs_are_not_retrieved(fake):
    client, _, calls, _, build, _ = fake
    build["actorDefinition"]["input"] = {"type": "object", "$ref": "https://untrusted.example/schema"}
    with pytest.raises(apify.ApifyError):
        client.prepare("example/scraper", {"query": "x"})
    assert len(calls) == 2


@pytest.mark.parametrize("field,value", [("actorPermissionLevel", "FULL_PERMISSIONS"),
                                        ("actorStandby", {"isEnabled": True})])
def test_other_actor_lifecycles_do_not_launch(fake, field, value):
    client, _, calls, actor, *_ = fake
    actor[field] = value
    with pytest.raises(apify.ApifyError):
        client.prepare("example/scraper", {"query": "x"})
    assert not any(call[0] == "POST" for call in calls)


def test_operator_actor_allowlist_is_enforced(fake, settings):
    client, _, calls, *_ = fake
    client.settings = replace(settings, allowed_actors=frozenset({"other/actor"}))
    with pytest.raises(apify.ApifyError, match="APIFY_ALLOWED_ACTORS"):
        client.prepare("example/scraper", {"query": "x"})
    assert len(calls) == 1


@pytest.mark.parametrize("exceptions", [frozenset(), frozenset({"trusted/obscure"})])
def test_native_apify_owner_is_eligible_even_with_unrelated_exceptions(fake, settings, exceptions):
    client, responses, calls, actor, *_ = fake
    actor["username"] = "apify"
    responses["GET", "/acts/apify~scraper"] = {"data": actor}
    actor["stats"] = {"actorReviewRating": 0, "actorReviewCount": 0, "totalUsers30Days": 0}
    client.settings = replace(settings, allowed_actors=exceptions)
    apify.run_actor({"actor": "apify/scraper", "input": {"query": "requested work"}}, client=client)
    assert len([call for call in calls if call[0] == "POST"]) == 1


@pytest.mark.parametrize("entry", [ACTOR, "example/scraper"])
def test_exact_trusted_community_exception_can_run_without_reviews(fake, settings, entry):
    client, _, calls, actor, *_ = fake
    actor["stats"] = {"actorReviewCount": 0, "totalUsers30Days": 0}
    client.settings = replace(settings, allowed_actors=frozenset({entry}))
    result = apify.run_actor({"actor": "example/scraper", "input": {"query": "requested work"}}, client=client)
    assert result["data"]["execution"]["run_id"] == RUN
    post = next(call for call in calls if call[0] == "POST")
    assert post[2]["params"]["maxTotalChargeUsd"] == settings.max_charge_usd
    assert post[2]["params"]["forcePermissionLevel"] == "LIMITED_PERMISSIONS"


@pytest.mark.parametrize("exceptions", [frozenset(), frozenset({"example/scraper-other"})])
def test_ratings_or_claimed_official_badges_do_not_authorize_community(fake, settings, exceptions):
    client, _, calls, actor, *_ = fake
    actor.update({"isOfficialApify": True, "fullName": "apify/scraper",
                  "stats": {"actorReviewRating": 5, "actorReviewCount": 5000, "totalUsers30Days": 100000}})
    client.settings = replace(settings, allowed_actors=exceptions)
    with pytest.raises(apify.ApifyError, match="APIFY_ALLOWED_ACTORS"):
        apify.run_actor({"actor": "example/scraper", "input": {"query": "requested work"}}, client=client)
    assert not any(call[0] == "POST" for call in calls)


def test_string_schema_fallback_supported(fake):
    client, _, _, _, build, _ = fake
    build["inputSchema"] = json.dumps(build["actorDefinition"].pop("input"))
    assert client.prepare("example/scraper", {"query": "x"})["build_number"] == "1.2.3"


@pytest.mark.parametrize("response,uncertain", [
    (Response(status=400), False), (Response(status=408), True), (Response(status=503), True),
    (Response(raw=b"not-json"), True), (requests.Timeout("sensitive request contents"), True)])
def test_failed_submit_is_never_retried_and_errors_do_not_echo_body(fake, response, uncertain):
    client, responses, calls, *_ = fake
    prepared = client.prepare("example/scraper", {"query": "private input"})
    responses["POST", f"/acts/{ACTOR}/runs"] = response
    with pytest.raises(apify.ApifyError) as exc:
        client.start(prepared)
    assert exc.value.uncertain is uncertain
    assert "sensitive" not in str(exc.value) and "private input" not in str(exc.value)
    assert len([call for call in calls if call[0] == "POST"]) == 1
    if isinstance(response, Response):
        assert response.closed


def test_native_handle_survives_bad_optional_receipt_and_keeps_expected_build(fake):
    client, responses, _, *_ = fake
    prepared = client.prepare("example/scraper", {"query": "x"})
    responses["POST", f"/acts/{ACTOR}/runs"] = {"data": {"id": RUN,
        "actId": "UnexpectedActor", "buildId": "UnexpectedBuild", "defaultDatasetId": "../bad"}}
    handle = client.start(prepared)
    assert handle == {"run_id": RUN, "actor_id": ACTOR, "build_id": BUILD}


def test_missing_native_id_is_uncertain(fake):
    client, responses, _, *_ = fake
    prepared = client.prepare("example/scraper", {"query": "x"})
    responses["POST", f"/acts/{ACTOR}/runs"] = {"data": {"status": "RUNNING"}}
    with pytest.raises(apify.ApifyError) as exc:
        client.start(prepared)
    assert exc.value.uncertain


def test_foreground_returns_native_handle_without_polling_or_background_receipt(fake):
    client, _, calls, *_ = fake
    result = apify.run_actor({"actor": "example/scraper", "input": {"query": "x"}}, client=client)
    assert result["ok"]
    assert result["data"]["execution"]["run_id"] == RUN
    assert result["data"]["execution"]["status"] == "SUBMITTED"
    assert "not confirmed complete" in result["speech"]
    assert "job_id" not in result and "result_kind" not in result
    assert len(calls) == 3


def test_dataset_page_preserves_nested_json_and_pagination(fake):
    client, _, calls, *_, run = fake
    result = apify.read_result({"run_id": RUN, "action": "dataset", "offset": 0, "limit": 2}, client=client)
    data = result["data"]
    assert data["execution"]["datasets"]["secondary"] == "SecondaryDataset"
    assert data["result"]["sample_items"][1]["nested"] == [1, True, None]
    assert data["result"]["total_items"] == 4
    assert data["result"]["returned_count"] == 2
    assert data["result"]["complete"] is False
    assert data["result"]["pagination"]["next_offset"] == 2
    assert data["result"]["pagination"]["has_more"] is True
    assert data["raw_ref"].startswith("stash://")
    assert all(call[0] == "GET" for call in calls)
    assert "page, not the complete" in result["speech"]


@pytest.mark.parametrize("options", [{"limit": 0}, {"limit": 101}, {"limit": True},
    {"offset": -1}, {"offset": True}, {"dataset_id": "UnrelatedDataset"}])
def test_dataset_reads_are_bounded_and_run_owned(fake, options):
    client, _, calls, *_ = fake
    with pytest.raises(apify.ApifyError):
        apify.read_result({"run_id": RUN, "action": "dataset", **options}, client=client)
    assert not any(call[1].endswith("/items") for call in calls)


def test_complete_and_unknown_dataset_totals_are_truthful(fake):
    client, responses, _, *_ = fake
    responses["GET", f"/datasets/{DATASET}"]["data"]["itemCount"] = 2
    assert apify.read_result({"run_id": RUN, "action": "dataset"}, client=client)["data"]["result"]["complete"]
    responses["GET", f"/datasets/{DATASET}"]["data"].pop("itemCount")
    result = apify.read_result({"run_id": RUN, "action": "dataset"}, client=client)
    assert result["data"]["result"]["total_items"] is None
    assert result["data"]["result"]["complete"] is False


def test_native_status_mismatch_is_not_success(fake):
    client, responses, _, *_ = fake
    responses["GET", f"/actor-runs/{RUN}"] = {"data": {"id": "DifferentRun", "status": "SUCCEEDED"}}
    with pytest.raises(apify.ApifyError, match="mismatched"):
        client.get_run(RUN)


def test_running_status_is_not_finished_output(fake):
    client, _, calls, *_, run = fake
    run["status"] = "RUNNING"
    result = apify.read_result({"run_id": RUN}, client=client)
    assert result["ok"] and result["data"]["result"]["complete"] is False
    assert "not finished" in result["speech"] and "do not start" in result["speech"]
    assert len(calls) == 1


def test_record_json_and_binary_are_retained_without_another_run(fake):
    client, responses, calls, *_ = fake
    result = apify.read_result({"run_id": RUN, "action": "record"}, client=client)
    assert result["data"]["result"]["value"] == {"text": "actual output"}
    responses["GET", f"/key-value-stores/{STORE}/records/OUTPUT"] = Response(raw=b"\x89PNG\r\n", content_type="image/png")
    result = apify.read_result({"run_id": RUN, "action": "record"}, client=client)
    assert result["data"]["result"]["kind"] == "file"
    assert result["data"]["artifacts"][0]["ref"].startswith("stash://")
    assert all(call[0] == "GET" for call in calls)


def test_request_has_absolute_stream_budget(fake, monkeypatch):
    client, responses, _, *_ = fake
    response = Response({"data": {}})
    ticks = iter([0, 21])
    monkeypatch.setattr(apify.time, "monotonic", lambda: next(ticks))
    responses["GET", f"/actor-runs/{RUN}"] = response
    with pytest.raises(apify.ApifyError, match="observation budget"):
        client.get_run(RUN)
    assert response.closed


def test_real_http_gzip_response_is_decoded_within_stream_limits(fake):
    client, responses, _, *_, run = fake
    response = Response()
    response.raw = HTTPResponse(body=io.BytesIO(gzip.compress(json.dumps({"data": run}).encode())),
        headers={"Content-Encoding": "gzip"}, preload_content=False)
    responses["GET", f"/actor-runs/{RUN}"] = response
    assert client.get_run(RUN)["id"] == RUN
    assert response.closed


def test_oversized_output_is_not_loaded_or_called_again(fake, monkeypatch):
    client, responses, calls, *_ = fake
    monkeypatch.setattr(apify, "MAX_RESPONSE_BYTES", 16)
    responses["GET", f"/actor-runs/{RUN}"] = Response(raw=b"x" * 17)
    with pytest.raises(apify.ApifyError, match="8 MiB"):
        client.get_run(RUN)
    assert len(calls) == 1


@pytest.mark.parametrize("submission", [False, True])
def test_excessive_json_nesting_has_a_bounded_error_without_retry(fake, submission):
    client, responses, calls, *_ = fake
    method, path = ("POST", f"/acts/{ACTOR}/runs") if submission else ("GET", f"/actor-runs/{RUN}")
    response = Response(raw=b"[" * 10000 + b"0" + b"]" * 10000)
    responses[method, path] = response
    with pytest.raises(apify.ApifyError, match="invalid JSON") as error:
        client._request(method, path, submission=submission)
    assert error.value.uncertain is submission
    assert response.closed
    assert len(calls) == 1


def test_mcp_configuration_exposes_only_fixed_discovery_tools():
    from pathlib import Path
    from urllib.parse import parse_qs, urlsplit
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config/mcp-servers.json").read_text())["mcpServers"]["apify"]
    assert config["enabled_env"] == "APIFY_MCP_ENABLED"
    assert config["headers"] == {"Authorization": "Bearer ${APIFY_TOKEN}"}
    assert set(config["allowed_tools"]) == {"search-actors", "fetch-actor-details"}
    assert "call-actor" not in config["allowed_tools"]
    assert parse_qs(urlsplit(config["url"]).query)["tools"][0].split(",") == config["allowed_tools"]
    for name in ("apify_run_actor", "apify_read_result"):
        manifest = json.loads((root / "skills" / (name + ".tool.json")).read_text())
        assert manifest["availability"]["enabled_env"] == "APIFY_MCP_ENABLED"
        assert manifest["child_environment"]["mode"] == "restricted"
