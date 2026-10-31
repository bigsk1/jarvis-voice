"""Artifact handoffs reuse one webhook send and expose retrieval handles only."""

import json
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from lib.webhook_handoff import prepare_artifact_handoff
from skills import send_webhook

POLICY = {"artifact_handoff": "jarvis_v1"}
REF = "stash://space_synthetic/f_123"


def payload(**context):
    return {"v": 1, "id": "handoff-synthetic-1", "source": "jarvis", "type": "question",
            "task": "Check the selected research", "reply": "chat", "context": context}


def test_ordinary_sends_stay_unchanged_even_when_body_contains_reference_fields():
    body = payload(stash_refs=[REF])
    for config in ({}, {"artifact_handoff": False}):
        outgoing, receipt = prepare_artifact_handoff(config, body, mode="cloud")
        assert outgoing is body
        assert receipt == {}
    plain = payload(summary="Existing handoff")
    outgoing, receipt = prepare_artifact_handoff(POLICY, plain, mode="cloud")
    assert outgoing is plain
    assert receipt == {"handoff_id": plain["id"]}


def test_selected_artifacts_get_relative_mode_pinned_paths_without_mutating_input():
    body = payload(stash_refs=[REF, REF], canvas_page_ids=["page_synthetic", "page_synthetic"],
                   mode="local", summary="Selected summary only")
    before = deepcopy(body)
    outgoing, receipt = prepare_artifact_handoff(POLICY, body, mode="cloud")
    assert body == before
    manifest = outgoing["context"]["artifact_manifest"]
    assert manifest["v"] == 1 and manifest["mode"] == "local"
    assert manifest["availability"] == "not_checked"
    assert len(manifest["artifacts"]) == receipt["handoff_artifacts_count"] == 2
    stash, canvas = manifest["artifacts"]
    for name, route in (("resolve_url", "resolve"), ("read_url", "read"), ("download_url", "download")):
        parsed = urlsplit(stash[name])
        assert parsed.path == "/api/stash/" + route
        assert not parsed.scheme and not parsed.netloc
        assert parse_qs(parsed.query) == {"ref": [REF], "mode": ["local"]}
    assert canvas == {"kind": "canvas", "page_id": "page_synthetic",
                      "read_url": "/api/canvas/page_synthetic?include_content=true"}
    assert outgoing["reply"] == "chat" and "priority" not in outgoing


@pytest.mark.parametrize("field", ["ref", "stash_ref", "both"])
def test_helper_and_media_reference_aliases_strip_internal_result_fields(field):
    ref = "stash://space_synthetic/日本語 report #1?.md"
    selected = {"path": "/private/server-only-path", "token": "SECRET_SENTINEL"}
    for key in ("ref", "stash_ref") if field == "both" else (field,):
        selected[key] = ref
    body = payload(stash_refs=[selected])
    outgoing, receipt = prepare_artifact_handoff(POLICY, body, mode="cloud")
    assert outgoing["context"]["stash_refs"] == [ref]
    assert receipt["handoff_artifacts"][0]["ref"] == ref
    query = urlsplit(outgoing["context"]["artifact_manifest"]["artifacts"][0]["resolve_url"]).query
    assert parse_qs(query)["ref"] == [ref]
    assert "SECRET_SENTINEL" not in json.dumps(outgoing)
    assert "server-only-path" not in json.dumps(outgoing)
    assert body["context"]["stash_refs"][0] == selected


@pytest.mark.parametrize("context", [
    {"stash_refs": "not-an-array"}, {"canvas_page_ids": None},
    {"stash_refs": ["/home/boss/local-file"]}, {"stash_refs": ["https://example.test/file"]},
    {"stash_refs": ["stash://../file"]}, {"stash_refs": ["stash://space_x/../secret"]},
    {"stash_refs": ["stash://space_x/.."]}, {"stash_refs": ["stash://space_x/file\\secret"]},
    {"stash_refs": ["stash://space_x/file\x00"]}, {"stash_refs": ["stash://space_x/"]},
    {"stash_refs": [{"ref": REF, "stash_ref": "stash://space_x/other"}]},
    {"stash_refs": [{}]}, {"canvas_page_ids": ["../page"]}, {"canvas_page_ids": ["https://example.test/page"]},
    {"stash_refs": [REF], "mode": []}, {"stash_refs": [REF], "mode": "invalid"},
    {"stash_refs": [REF], "artifact_manifest": {}}, {"stash_refs": [REF] * 13},
])
def test_invalid_explicit_selection_is_rejected(context):
    with pytest.raises(ValueError):
        prepare_artifact_handoff(POLICY, payload(**context), mode="cloud")


def test_unknown_registry_policy_is_rejected():
    with pytest.raises(ValueError, match="Unsupported"):
        prepare_artifact_handoff({"artifact_handoff": "unknown"}, payload(), mode="cloud")


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    config = {**POLICY, "url": "https://receiver.example.test/handoff", "required_fields": ["id", "context"],
              "headers": {"Authorization": "Bearer DESTINATION_SECRET"},
              "payload_schema": {"type": "object", "properties": {"context": {"type": "object"}}}}
    monkeypatch.setattr(send_webhook, "load_config", lambda: None)
    monkeypatch.setattr(send_webhook, "load_webhook_registry", lambda: {"agent": config})
    monkeypatch.setattr(send_webhook, "get_active_config_mode", lambda: "cloud")
    cooldown = tmp_path / "cooldown.json"
    monkeypatch.setattr(send_webhook, "RATE_LIMIT_FILE", str(cooldown))
    post = Mock(return_value=SimpleNamespace(status_code=202, text='{"accepted":true}'))
    monkeypatch.setattr(send_webhook, "post_webhook", post)
    return config, post, cooldown


def invoke(monkeypatch, capsys, body):
    monkeypatch.setattr(sys, "argv", ["send_webhook.py", json.dumps({"webhook": "agent", "data": body})])
    code = send_webhook.main()
    return code, json.loads(capsys.readouterr().out)


def test_send_once_returns_correlation_and_handles_without_claiming_remote_completion(runtime, monkeypatch, capsys):
    _, post, cooldown = runtime
    code, result = invoke(monkeypatch, capsys, payload(stash_refs=[REF]))
    assert code == 0 and result["ok"] is True
    post.assert_called_once()
    outgoing = post.call_args.kwargs["data"]
    assert outgoing["context"]["artifact_manifest"]["availability"] == "not_checked"
    assert "DESTINATION_SECRET" not in json.dumps(outgoing)
    assert result["data"]["handoff_id"] == outgoing["id"]
    assert result["data"]["handoff_artifacts"] == [{"kind": "stash", "ref": REF, "mode": "cloud"}]
    assert result["data"]["delivery_status"] == "accepted"
    assert "completed" not in result["data"]
    assert cooldown.exists()


def test_bad_selection_rejected_before_network_and_cooldown(runtime, monkeypatch, capsys):
    _, post, cooldown = runtime
    code, result = invoke(monkeypatch, capsys, payload(stash_refs=["/private/file"]))
    assert code == 1 and result["data"]["request_sent"] is False
    post.assert_not_called()
    assert not cooldown.exists()


def test_final_enriched_body_is_validated_before_network(runtime, monkeypatch, capsys):
    config, post, cooldown = runtime
    config["payload_schema"]["properties"]["context"] = {"type": "object", "additionalProperties": False}
    code, result = invoke(monkeypatch, capsys, payload(stash_refs=[REF]))
    assert code == 1 and result["data"]["request_sent"] is False
    assert result["data"]["validation_path"] == "context"
    post.assert_not_called()
    assert not cooldown.exists()


def test_uncertain_delivery_keeps_handoff_id_and_never_retries(runtime, monkeypatch, capsys):
    _, post, cooldown = runtime
    post.side_effect = requests.Timeout()
    code, result = invoke(monkeypatch, capsys, payload(stash_refs=[REF]))
    assert code == 1 and result["data"]["delivery_status"] == "unknown"
    assert result["data"]["retry_safe"] is False
    assert result["data"]["handoff_id"] == "handoff-synthetic-1"
    assert result["data"]["handoff_artifacts_count"] == 1
    assert cooldown.exists()
    post.assert_called_once()
