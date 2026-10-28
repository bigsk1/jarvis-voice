"""RSS tool envelopes and workflow text handoffs use the narrow feed service."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from skills import rss_feed

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def service(monkeypatch):
    value = SimpleNamespace(execute=Mock(return_value={"items": [], "candidate_count": 0}))
    monkeypatch.setattr(rss_feed, "RSSFeedService", lambda: value)
    monkeypatch.setattr(rss_feed, "load_config", lambda: {})
    return value


@pytest.mark.parametrize(
    "params",
    [
        {"action": "list_profiles"},
        {"url": "https://example.org/feed.xml", "limit": 4},
        {"action": "read", "profile": "daily_tech"},
        {"action": "resolve_selection", "profile": "daily_tech", "batch_id": "batch-1", "text": '{"ids":[]}'},
        {"action": "acknowledge", "profile": "daily_tech", "batch_id": "batch-1", "page_id": "page_test"},
    ],
)
def test_actions_use_exact_service_arguments_and_standard_result(service, params):
    result = rss_feed.execute(params)
    assert result["ok"] is True
    assert isinstance(result["speech"], str)
    expected = {"action": "read", **params}
    service.execute.assert_called_once_with(**expected)
    if params.get("action") == "acknowledge":
        assert result["data"]["publication_status"] == "Published the digest to Canvas."
    else:
        assert "publication_status" not in result["data"]


def test_identical_workflow_llm_aliases_become_one_selection_text(service):
    text = '{"ids":["story-1"]}'
    params = {"action": "resolve_selection", "profile": "daily_tech", "batch_id": "batch-1", "text": text}
    result = rss_feed.execute({**params, "content": text, "body": text})
    assert result["ok"]
    service.execute.assert_called_once_with(**params)


@pytest.mark.parametrize(
    "params",
    [
        [],
        {"action": "delete"},
        {"action": ["read"]},
        {"action": "read", "config_path": "/private/config"},
        {"action": "read", "body": "text"},
        {"action": "resolve_selection", "text": '{"ids":[]}', "body": "different"},
        {"action": "resolve_selection", "content": '{"ids":[]}'},
    ],
)
def test_unsupported_arguments_fail_before_service_execution(service, params):
    result = rss_feed.execute(params)
    assert not result["ok"]
    service.execute.assert_not_called()


def test_safe_service_errors_are_returned_without_claiming_publication(service):
    service.execute.side_effect = rss_feed.RSSFeedError("The feed batch has expired.")
    result = rss_feed.execute({"action": "acknowledge", "profile": "daily_tech", "batch_id": "expired", "page_id": "page_test"})
    assert not result["ok"]
    assert result["error"] == "The feed batch has expired."
    assert "publication_status" not in result.get("data", {})


def test_unexpected_service_errors_never_expose_details(service):
    service.execute.side_effect = RuntimeError("https://user:private-token@host/secret")
    result = rss_feed.execute({"profile": "daily_tech"})
    assert not result["ok"]
    assert result["error"] == "rss_feed_failed"
    assert "private-token" not in json.dumps(result)


def test_profile_read_does_not_acknowledge_or_claim_publication(service):
    service.execute.return_value = {"profile": "daily_tech", "candidate_count": 3, "items": [{"id": "one"}]}
    result = rss_feed.execute({"profile": "daily_tech"})
    assert result["speech"] == "Found 3 fresh RSS candidates."
    service.execute.assert_called_once_with(action="read", profile="daily_tech")


@pytest.mark.parametrize("value", ["not JSON", "[]", '{"action":"read","profile":"daily_tech"}'])
def test_cli_always_emits_one_json_result_with_truthful_exit(service, monkeypatch, capsys, value):
    monkeypatch.setattr(rss_feed.sys, "argv", ["rss_feed.py", value])
    with pytest.raises(SystemExit) as stopped:
        rss_feed.main()
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert stopped.value.code == (0 if result["ok"] else 1)
    assert result["ok"] is (value.startswith("{"))


def test_manifest_has_restricted_foreground_environment_and_explicit_proxy_policy():
    manifest = json.loads((ROOT / "skills/rss_feed.tool.json").read_text())
    assert manifest["name"] == "rss_feed"
    assert manifest["proxy_policy"] == "prefer"
    assert manifest["child_environment"] == {"mode": "restricted", "allow": []}
    assert not manifest.get("background")
    assert set(manifest["parameters"]["properties"]) == {"action", *rss_feed.PARAMETERS}
    assert manifest["parameters"]["additionalProperties"] is False
