"""Readable Prompt Guard selection, gates, profiles and trusted child scopes."""

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import paths  # noqa: E402
from config_loader import config_scope  # noqa: E402

from lib import paths as package_paths  # noqa: E402
from lib import prompt_guard_policy as policy  # noqa: E402

SOURCE = {"source_type": "tool_result", "source_name": "crawl_url"}


@pytest.fixture(autouse=True)
def isolated_tool_definitions(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(package_paths, "get_project_root", lambda: tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/mcp-servers.json").write_text(json.dumps({"mcpServers": {}}))
    (tmp_path / "skills").mkdir()


def config_document(**changes):
    return {
        "v": 2,
        "tools": ["crawl_url"],
        "summarizers": {"enabled": True},
        "policies": {"web_content": 0.84, "document_text": 0.82},
        "rules": [],
        **changes,
    }


def write_config(tmp_path, document=None, name="policy.json"):
    path = tmp_path / name
    path.write_text(json.dumps(config_document() if document is None else document))
    return str(path)


def resolve(path=None, **options):
    return policy.resolve_prompt_guard_policy(0.8, policy_file=path, **SOURCE, **options)


@pytest.fixture
def shipped_policy():
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / policy.DEFAULT_POLICY_FILE).read_text())


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_unconfigured_uses_shipped_readable_selection_without_relaxing_thresholds(mode, shipped_policy):
    with config_scope(mode, {"PROMPT_GUARD_POLICY_FILE": ""}):
        assert all(policy.is_tool_selected(name) for name in shipped_policy["tools"])
        assert policy.summarizers_enabled() is shipped_policy["summarizers"]["enabled"]
        assert policy.is_tool_selected("send_email") is False
        assert resolve() == policy.PromptGuardPolicyDecision(0.8)
        assert resolve(policy_name="web_content") == policy.PromptGuardPolicyDecision(
            0.8, "policy:web_content",
        )
        with policy.workflow_prompt_guard_scope(
            mode=mode, workflow_id="rss_digest", profile="ai_status",
        ):
            assert resolve() == policy.PromptGuardPolicyDecision(0.8)


def test_shipped_json_is_valid_and_preserves_declared_named_thresholds(shipped_policy):
    parsed = policy._parse_config(shipped_policy)
    assert parsed.tools == frozenset(shipped_policy["tools"])
    assert shipped_policy["rules"] == []
    with config_scope("cloud", {"PROMPT_GUARD_POLICY_FILE": ""}):
        for name, threshold in shipped_policy["policies"].items():
            assert resolve(policy_name=name) == policy.PromptGuardPolicyDecision(
                threshold, f"policy:{name}",
            )


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_exact_json_selection_and_independent_gate_hot_reload(tmp_path, mode):
    path = write_config(tmp_path)
    with config_scope(mode, {"PROMPT_GUARD_POLICY_FILE": path}):
        assert policy.is_tool_selected("crawl_url") is True
        assert policy.is_tool_selected("Crawl_url") is False
        assert policy.is_tool_selected("crawl_url_other") is False
        assert policy.is_tool_selected("mcp_crawl_url") is False
        assert policy.summarizers_enabled() is True
        write_config(tmp_path, config_document(tools=[], summarizers={"enabled": False}))
        assert policy.is_tool_selected("crawl_url") is False
        assert policy.summarizers_enabled() is False
        write_config(tmp_path)
        assert policy.is_tool_selected("crawl_url") is True
        assert policy.summarizers_enabled() is True


def test_tool_name_validator_preserves_exact_identifier_bounds(tmp_path):
    name = "mcp_" + "a-" * 48
    assert len(name) == 100
    path = write_config(tmp_path, config_document(tools=[name]))
    with config_scope("cloud", {"PROMPT_GUARD_POLICY_FILE": path}):
        assert policy.is_valid_tool_name(name)
        assert policy.is_tool_selected(name)
    for invalid in (None, True, "", "a" * 101, "mcp_apify_*", "mcp_apify_search-actors\n"):
        assert not policy.is_valid_tool_name(invalid)


def test_config_scope_uses_each_modes_path_and_gate(tmp_path):
    cloud = write_config(tmp_path, name="cloud.json")
    local = write_config(tmp_path, config_document(
        tools=["rss_feed"], summarizers={"enabled": False},
        policies={"web_content": 0.89},
    ), name="local.json")
    with config_scope("cloud", {"PROMPT_GUARD_POLICY_FILE": cloud}):
        assert policy.is_tool_selected("crawl_url") and policy.summarizers_enabled()
        assert resolve(policy_name="web_content").threshold == 0.84
        with config_scope("local", {"PROMPT_GUARD_POLICY_FILE": local}):
            assert not policy.is_tool_selected("crawl_url")
            assert policy.is_tool_selected("rss_feed")
            assert not policy.summarizers_enabled()
            assert resolve(policy_name="web_content").threshold == 0.89
        assert policy.is_tool_selected("crawl_url") and policy.summarizers_enabled()
        assert resolve(policy_name="web_content").threshold == 0.84


def test_relative_selected_config_is_project_relative_and_old_csv_has_no_effect(tmp_path, monkeypatch):
    write_config(tmp_path)
    monkeypatch.setattr(policy, "get_project_root", lambda: tmp_path)
    with config_scope("cloud", {
        "PROMPT_GUARD_POLICY_FILE": "policy.json", "PROMPT_GUARD_TOOLS": "send_email",
    }):
        assert policy.is_tool_selected("crawl_url") is True
        assert policy.is_tool_selected("send_email") is False


def test_exact_rules_override_named_policy_then_global_fallback(tmp_path):
    path = write_config(tmp_path, config_document(rules=[
        {"id": "crawl_override", **SOURCE, "threshold": 0.85},
        {"id": "rss_workflow", **SOURCE, "workflow_id": "rss_digest", "threshold": 0.87},
        {"id": "rss_profile", **SOURCE, "workflow_id": "rss_digest", "profile": "ai_status",
         "policy": "document_text"},
    ]))
    with config_scope("cloud"):
        assert resolve(path, policy_name="web_content") == policy.PromptGuardPolicyDecision(
            0.85, "crawl_override",
        )
        with policy.workflow_prompt_guard_scope(mode="cloud", workflow_id="rss_digest"):
            assert resolve(path, policy_name="web_content").threshold == 0.87
        with policy.workflow_prompt_guard_scope(
            mode="cloud", workflow_id="rss_digest", profile="ai_status",
        ):
            assert resolve(path, policy_name="web_content") == policy.PromptGuardPolicyDecision(
                0.82, "rss_profile",
            )
    path = write_config(tmp_path)
    assert resolve(path, policy_name="web_content").threshold == 0.84
    assert resolve(path) == policy.PromptGuardPolicyDecision(0.8)
    assert resolve(path, policy_name="does_not_exist") == policy.PromptGuardPolicyDecision(
        0.8, error_code="unknown_policy",
    )


@pytest.mark.parametrize("document", [
    config_document(tools="crawl_url"),
    config_document(tools=["crawl_url", "crawl_url"]),
    config_document(tools=["crawl_*"]),
    config_document(tools=["mcp_apify_search-*"]),
    config_document(tools=["send email"]),
    *(config_document(tools=[name]) for name in (
        "mcp_apify_search-actors\n", "mcp.apify", "mcp/apify", "mcp:apify", "検索", "x" * 101,
    )),
    config_document(tools=[True]),
    config_document(tools=[f"tool_{index}" for index in range(policy.MAX_SELECTED_TOOLS + 1)]),
    config_document(summarizers=False),
    config_document(summarizers={}),
    config_document(summarizers={"enabled": "false"}),
    config_document(summarizers={"enabled": True, "threshold": 0.9}),
    config_document(policies=[]),
    config_document(policies={"bad name": 0.9}),
    config_document(policies={"configured_default": 0.9}),
    config_document(policies={"x" * 94: 0.9}),
    config_document(policies={f"p{index}": 0.8 for index in range(policy.MAX_NAMED_POLICIES + 1)}),
    *(config_document(policies={"web_content": value})
      for value in (True, "0.9", -0.1, 1.1, float("nan"), float("inf"), 10 ** 400)),
    {key: value for key, value in config_document().items() if key != "summarizers"},
    {**config_document(), "unexpected": True},
])
def test_invalid_config_never_expands_selected_content_and_keeps_global_threshold(
    tmp_path, caplog, document,
):
    path = write_config(tmp_path, document)
    with config_scope("cloud", {"PROMPT_GUARD_POLICY_FILE": path}), caplog.at_level(
        logging.WARNING, logger="prompt_guard",
    ):
        assert policy.is_tool_selected("send_email") is False
        assert policy.is_tool_selected("crawl_url") is False
        assert policy.summarizers_enabled() is True
        assert resolve(policy_name="web_content") == policy.PromptGuardPolicyDecision(
            0.8, error_code="invalid_policy",
        )
    assert "reason=invalid_policy" in caplog.text
    assert path not in caplog.text
    assert "unexpected" not in caplog.text


def test_missing_explicit_file_never_expands_selection(tmp_path, shipped_policy):
    path = str(tmp_path / "not-created.json")
    with config_scope("cloud", {"PROMPT_GUARD_POLICY_FILE": path}):
        assert all(not policy.is_tool_selected(name) for name in shipped_policy["tools"])
        assert policy.summarizers_enabled() is True
        assert resolve().error_code == "invalid_policy"


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_valid_named_policy_id_is_bounded_for_receipts(tmp_path, mode):
    name = "p" * 93
    path = write_config(tmp_path, config_document(policies={name: 0.85}))
    with config_scope(mode):
        decision = resolve(path, policy_name=name)
    assert decision.threshold == 0.85
    assert decision.policy_id == f"policy:{name}" and len(decision.policy_id) == 100


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_export_and_restore_trusted_child_scope_match_mode_and_reset(tmp_path, mode):
    path = write_config(tmp_path, config_document(rules=[{
        "id": "rss_exception", **SOURCE, "workflow_id": "rss_digest", "profile": "ai_status",
        "threshold": 0.9,
    }]))
    with config_scope(mode):
        assert policy.export_prompt_guard_context() is None
        with policy.workflow_prompt_guard_scope(
            mode=mode, workflow_id="rss_digest", profile="ai_status",
        ):
            snapshot = policy.export_prompt_guard_context()
        assert snapshot is not None
        assert policy.export_prompt_guard_context() is None
        with policy.inherited_prompt_guard_scope(snapshot):
            assert resolve(path).threshold == 0.9
            assert policy.export_prompt_guard_context() == snapshot
        assert resolve(path).threshold == 0.8
        other = "local" if mode == "cloud" else "cloud"
        with config_scope(other), policy.inherited_prompt_guard_scope(snapshot):
            assert resolve(path).threshold == 0.8
            assert policy.export_prompt_guard_context() is None


def test_current_workflow_context_wins_over_ambient_child_snapshot(tmp_path):
    path = write_config(tmp_path, config_document(rules=[{
        "id": "rss_exception", **SOURCE, "workflow_id": "rss_digest", "profile": "ai_status",
        "threshold": 0.9,
    }]))
    snapshot = json.dumps({"v": 1, "mode": "cloud", "workflow_id": "rss_digest", "profile": "ai_status"})
    with config_scope("cloud"):
        with policy.workflow_prompt_guard_scope(mode="cloud", workflow_id="research"):
            with policy.inherited_prompt_guard_scope(snapshot):
                assert resolve(path).threshold == 0.8
        with policy.workflow_prompt_guard_scope(mode="cloud", workflow_id=None):
            with policy.inherited_prompt_guard_scope(snapshot):
                assert resolve(path).threshold == 0.8
        with policy.workflow_prompt_guard_scope(
            mode="cloud", workflow_id="rss_digest", profile="ai_status",
        ), policy.inherited_prompt_guard_scope(None):
            assert resolve(path).threshold == 0.9
        with policy.workflow_prompt_guard_scope(
            mode="local", workflow_id="rss_digest", profile="ai_status",
        ), policy.inherited_prompt_guard_scope(snapshot):
            assert resolve(path).threshold == 0.8


@pytest.mark.parametrize("snapshot", [
    None, "", "broken", " " * 1025, "[]", "{}",
    '{"v":1,"v":1,"mode":"cloud","workflow_id":"rss_digest","profile":"ai_status"}',
    json.dumps({"v": True, "mode": "cloud", "workflow_id": "rss_digest", "profile": "ai_status"}),
    json.dumps({"v": 1, "mode": "cloud", "workflow_id": "research", "profile": "ai_status"}),
    json.dumps({"v": 1, "mode": "cloud", "workflow_id": "bad workflow", "profile": None}),
    json.dumps({"v": 1, "mode": "cloud", "workflow_id": "rss_digest", "profile": "bad profile"}),
])
def test_invalid_child_snapshot_cannot_select_exception(snapshot):
    with config_scope("cloud"), policy.inherited_prompt_guard_scope(snapshot):
        assert policy.export_prompt_guard_context() is None
