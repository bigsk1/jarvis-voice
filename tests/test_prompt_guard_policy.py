"""Threshold rules are exact, mode-bound, and never selected by returned text."""

import asyncio
import json
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from config_loader import config_scope  # noqa: E402

from lib import prompt_guard as pg  # noqa: E402
from lib import prompt_guard_incidents as incidents  # noqa: E402
from lib import prompt_guard_observer as observer  # noqa: E402
from lib import prompt_guard_policy as policy  # noqa: E402
from lib.rss_feeds import RSSFeedError  # noqa: E402
from orchestrator.pipeline_executor import PipelineExecutor  # noqa: E402

SOURCE = {"source_type": "tool_result", "source_name": "crawl_url"}
AI_RULE = {
    "id": "ai_status_crawl", **SOURCE, "workflow_id": "rss_digest", "profile": "ai_status",
    "threshold": 0.9,
}
EXAMPLE_POLICY = str(Path(__file__).resolve().parents[1] / "config/prompt_guard_policy.json.example")


def document(rules=None):
    return {
        "v": 2, "tools": ["rss_feed", "crawl_url"], "summarizers": {"enabled": True},
        "policies": {"web_content": 0.8, "document_text": 0.8},
        "rules": [AI_RULE] if rules is None else rules,
    }


def write_policy(tmp_path, rules=None):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document(rules)))
    return str(path)


def resolve(path=None, **source):
    return policy.resolve_prompt_guard_policy(0.8, policy_file=path, **{**SOURCE, **source})


def test_no_file_unmatched_source_and_unknown_workflow_keep_default(tmp_path):
    path = write_policy(tmp_path)
    with config_scope("cloud"):
        assert resolve() == policy.PromptGuardPolicyDecision(0.8)
        assert resolve(path) == policy.PromptGuardPolicyDecision(0.8)
        with policy.workflow_prompt_guard_scope(
            mode="cloud", workflow_id="rss_digest", profile="ai_status",
        ):
            assert resolve(path).threshold == 0.9
            assert resolve(path).policy_id == "ai_status_crawl"
            assert resolve(path, source_name="rss_feed").threshold == 0.8
            assert resolve(path, source_type="attachment").threshold == 0.8
        with policy.workflow_prompt_guard_scope(mode="cloud", workflow_id="ai_status"):
            assert resolve(path).threshold == 0.8


def test_source_only_and_workflow_rules_are_refined_by_exact_profile(tmp_path):
    path = write_policy(tmp_path, [
        {"id": "crawl", **SOURCE, "threshold": 0.81},
        {"id": "rss_crawl", **SOURCE, "workflow_id": "rss_digest", "threshold": 0.85},
        AI_RULE,
    ])
    with config_scope("cloud"):
        assert resolve(path).policy_id == "crawl"
        with policy.workflow_prompt_guard_scope(
            mode="cloud", workflow_id="rss_digest", profile="daily_tech",
        ):
            assert resolve(path).policy_id == "rss_crawl"
        with policy.workflow_prompt_guard_scope(
            mode="cloud", workflow_id="rss_digest", profile="ai_status",
        ):
            assert resolve(path).policy_id == "ai_status_crawl"


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("workflow_id,profile", [
    ("rss_digest", "ai_status"), ("rss_digest", "daily_tech"),
    ("research", None), ("ai_status", None), (None, None),
])
def test_operator_policy_relaxes_only_ai_status_feed_and_article_results(
    tmp_path, mode, workflow_id, profile,
):
    selected = write_policy(tmp_path, [
        {**AI_RULE, "id": "ai_status_rss", "source_name": "rss_feed"}, AI_RULE,
    ])
    with config_scope(mode), policy.workflow_prompt_guard_scope(
        mode=mode, workflow_id=workflow_id, profile=profile,
    ):
        for source_name, rule_id in (("rss_feed", "ai_status_rss"), ("crawl_url", "ai_status_crawl")):
            decision = resolve(selected, source_name=source_name)
            if workflow_id == "rss_digest" and profile == "ai_status":
                assert decision == policy.PromptGuardPolicyDecision(0.9, rule_id)
            else:
                assert decision == policy.PromptGuardPolicyDecision(0.8)
        assert resolve(selected, source_name="web_search").threshold == 0.8
        assert resolve(selected, source_type="attachment", source_name="web_text").threshold == 0.8


def test_policy_relative_path_is_project_relative_and_reload_has_no_stale_cache(tmp_path, monkeypatch):
    path = write_policy(tmp_path, [{"id": "crawl", **SOURCE, "threshold": 0.81}])
    monkeypatch.setattr(policy, "get_project_root", lambda: tmp_path)
    assert resolve("policy.json").threshold == 0.81
    write_policy(tmp_path, [{"id": "crawl", **SOURCE, "threshold": 0.83}])
    assert resolve(path).threshold == 0.83


@pytest.mark.parametrize("invalid_document", [
    [], {}, {"v": True, "rules": []}, {"v": 1, "rules": []},
    {**document([]), "default": 0.99}, document({}),
    document([AI_RULE] * 129), document([AI_RULE, AI_RULE]),
    document([AI_RULE, {**AI_RULE, "id": "duplicate_selector"}]),
    *(document([{**AI_RULE, "threshold": value}])
      for value in (True, "0.9", None, -0.1, 1.1, 10 ** 400, float("nan"), float("inf"))),
    *(document([{**AI_RULE, "id": value}])
      for value in ("configured_default", "bad\nname", "has space", "", None, "*")),
    document([{**AI_RULE, "category": "trusted"}]),
    document([{key: value for key, value in AI_RULE.items() if key != "source_name"}]),
    document([{**AI_RULE, "source_name": "crawl_*"}]),
    document([{**AI_RULE, "profile": "ai status"}]),
    document([{**AI_RULE, "workflow_id": "research"}]),
    document([{key: value for key, value in AI_RULE.items() if key != "workflow_id"}]),
    document([{**AI_RULE, "policy": "web_content"}]),
    document([{key: value for key, value in AI_RULE.items() if key != "threshold"}]),
    document([{**{key: value for key, value in AI_RULE.items() if key != "threshold"},
               "policy": "missing_policy"}]),
])
def test_invalid_policy_is_rejected_whole_without_losing_default(tmp_path, invalid_document):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid_document))
    with policy.workflow_prompt_guard_scope(
        mode="cloud", workflow_id="rss_digest", profile="ai_status",
    ):
        decision = resolve(str(path))
    assert decision == policy.PromptGuardPolicyDecision(0.8, error_code="invalid_policy")


@pytest.mark.parametrize("raw", [
    '{"v":1,"v":1,"rules":[]}',
    '{"v":1,"rules":[{"id":"a","id":"b"}]}',
    "broken JSON", "\ud800", " " * (policy.MAX_POLICY_BYTES + 1),
])
def test_invalid_bytes_duplicate_json_fields_and_size_limit_are_safe(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_bytes(raw.encode("utf-8", errors="surrogatepass"))
    assert resolve(str(path)).error_code == "invalid_policy"
    assert resolve(str(tmp_path / "missing.json")).threshold == 0.8


def test_nested_context_resets_on_exceptions_and_cross_mode_scan_cannot_inherit(tmp_path):
    path = write_policy(tmp_path)
    with config_scope("cloud"), policy.workflow_prompt_guard_scope(
        mode="cloud", workflow_id="rss_digest", profile="ai_status",
    ):
        assert resolve(path).threshold == 0.9
        with config_scope("local"):
            assert resolve(path).threshold == 0.8
        with pytest.raises(RuntimeError), policy.workflow_prompt_guard_scope(
            mode="cloud", workflow_id="research",
        ):
            assert resolve(path).threshold == 0.8
            raise RuntimeError("synthetic failure")
        assert resolve(path).threshold == 0.9
        with policy.workflow_prompt_guard_scope(mode="cloud", workflow_id="invalid name"):
            assert resolve(path).threshold == 0.8
    assert resolve(path).threshold == 0.8


def test_thread_and_async_scopes_do_not_leak_between_workflows(tmp_path):
    path = write_policy(tmp_path)
    barrier = threading.Barrier(2)

    def thread_scan(mode, profile):
        with config_scope(mode), policy.workflow_prompt_guard_scope(
            mode=mode, workflow_id="rss_digest", profile=profile,
        ):
            barrier.wait(timeout=10)
            return resolve(path).threshold

    with ThreadPoolExecutor(max_workers=2) as executor:
        cloud = executor.submit(thread_scan, "cloud", "ai_status")
        local = executor.submit(thread_scan, "local", "daily_tech")
        assert (cloud.result(timeout=10), local.result(timeout=10)) == (0.9, 0.8)

    async def scan(profile):
        with config_scope("cloud"), policy.workflow_prompt_guard_scope(
            mode="cloud", workflow_id="rss_digest", profile=profile,
        ):
            await asyncio.sleep(0)
            return resolve(path).threshold

    async def run():
        return await asyncio.gather(scan("ai_status"), scan("daily_tech"))

    assert asyncio.run(run()) == [0.9, 0.8]
    assert resolve(path).threshold == 0.8


@pytest.fixture
def transport(monkeypatch):
    calls = []
    scores = []
    response_thresholds = []
    with pg._state_lock:
        pg._states.clear()
    monkeypatch.setattr(pg, "_capacity", threading.BoundedSemaphore(1))

    class Response:
        status_code = 200
        headers = {"Content-Type": "application/json"}

        def __init__(self, payload):
            threshold = payload["threshold"]
            echoed = response_thresholds.pop(0) if response_thresholds else threshold
            score = scores.pop(0) if scores else 0.85
            self.body = {
                "status": "ok", "injection_score": score,
                "threshold": echoed, "flagged": score >= echoed,
                "coverage": {"complete": True, "truncated": False,
                             "windows_scanned": 1, "windows_total": 1},
            }

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_content(self, _size):
            yield json.dumps(self.body).encode()

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            calls.append((url, deepcopy(kwargs["json"])))
            return Response(kwargs["json"])

    monkeypatch.setattr(pg.requests, "Session", Session)
    return calls, scores, response_thresholds


def scan_config(path=""):
    return {
        "PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_URL": "http://scanner.test:8188",
        "PROMPT_GUARD_API_KEY": "synthetic-key", "PROMPT_GUARD_THRESHOLD": "0.8",
        "PROMPT_GUARD_POLICY_FILE": path,
    }


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("score,flagged", [(0.899254, False), (0.9, True), (0.91, True)])
def test_selected_threshold_is_sent_checked_and_recorded(transport, tmp_path, caplog, mode, score, flagged):
    calls, scores, _ = transport
    scores.append(score)
    path = write_policy(tmp_path)
    caplog.set_level(logging.DEBUG, logger="prompt_guard")
    with config_scope(mode, scan_config(path)), policy.workflow_prompt_guard_scope(
        mode=mode, workflow_id="rss_digest", profile="ai_status",
    ):
        observation = pg.scan_text("untrusted text", **SOURCE)
    assert observation.status == "scanned" and observation.flagged is flagged
    assert observation.threshold == 0.9 and observation.policy_id == "ai_status_crawl"
    assert calls[0][1] == {
        "text": "untrusted text", "threshold": 0.9,
        "source": {"type": "tool_result", "name": "crawl_url"},
    }
    assert "policy_id=ai_status_crawl" in caplog.text and "threshold=0.900000" in caplog.text


def test_invalid_policy_does_not_skip_scanning_and_logs_no_path_or_payload(transport, tmp_path, caplog):
    calls, _, _ = transport
    path = tmp_path / "private-policy-name.json"
    path.write_text('{"v":1,"rules":["private raw document"]}')
    with config_scope("cloud", scan_config(str(path))):
        observation = pg.scan_text("evidence", **SOURCE)
    assert observation.status == "scanned" and observation.flagged is True
    assert observation.threshold == 0.8 and observation.policy_id == "configured_default"
    assert calls[0][1]["threshold"] == 0.8
    assert "reason=invalid_policy" in caplog.text and "policy_id=configured_default" in caplog.text
    assert str(path) not in caplog.text and "private raw document" not in caplog.text


def test_wrong_threshold_echo_stays_unknown_instead_of_accepting_service_verdict(transport, tmp_path):
    _, _, echoes = transport
    echoes.append(0.8)
    with config_scope("cloud", scan_config(write_policy(tmp_path))), policy.workflow_prompt_guard_scope(
        mode="cloud", workflow_id="rss_digest", profile="ai_status",
    ):
        observation = pg.scan_text("evidence", **SOURCE)
    assert observation.status == "unknown" and observation.reason_code == "invalid_response"
    assert observation.threshold == 0.9 and observation.flagged is None
    assert observation.policy_id == "ai_status_crawl"


def test_scanner_uses_each_modes_selected_file_and_preserves_scoped_default(transport, tmp_path):
    calls, _, _ = transport
    cloud_dir = tmp_path / "cloud"
    local_dir = tmp_path / "local"
    cloud_dir.mkdir()
    local_dir.mkdir()
    cloud = write_policy(cloud_dir, [{"id": "cloud_crawl", **SOURCE, "threshold": 0.92}])
    local = write_policy(local_dir, [{"id": "local_crawl", **SOURCE, "threshold": 0.79}])
    with config_scope("cloud", scan_config(cloud)):
        first = pg.scan_text("evidence", **SOURCE)
        with config_scope("local", {**scan_config(local), "PROMPT_GUARD_THRESHOLD": "0.83"}):
            second = pg.scan_text("evidence", **SOURCE)
            other = pg.scan_text("evidence", source_type="attachment", source_name="web_text")
        third = pg.scan_text("evidence", **SOURCE)
    assert [(item.threshold, item.policy_id) for item in (first, second, other, third)] == [
        (0.92, "cloud_crawl"), (0.79, "local_crawl"),
        (0.83, "configured_default"), (0.92, "cloud_crawl"),
    ]
    assert [payload["threshold"] for _url, payload in calls] == [0.92, 0.79, 0.83, 0.92]


def rss_workflow(*, loop=False):
    return {
        "id": "rss_digest", "name": "RSS digest", "triggers": {"explicit": ["/rss_digest"]},
        "variables": {
            "profile": {"from": "query", "extract": "first_words", "max_words": 1,
                        "default": "daily_tech"},
            "urls": {"from": "static", "value": ["https://example.test/a", "https://example.test/b"]},
        },
        "steps": [
            {"step": 1, "tool": "crawl_url", "params": {"url": "https://example.test/a"},
             **({"for_each": "${urls}", "process_all": True} if loop else {})},
        ],
        "success_speech": "Complete.",
    }


def pipeline_with(execute):
    instance = object.__new__(PipelineExecutor)
    instance.mode = "cloud"
    instance.provider = None
    instance.executor = SimpleNamespace(execute=execute, registry=None)
    instance.logger = SimpleNamespace(log_workflow_execution=lambda **_kwargs: None)
    instance.llm_logger = SimpleNamespace(log_server_side_tools=lambda **_kwargs: None)
    return instance


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("profile,threshold,selection_runs", [
    ("ai_status", 0.9, True), ("daily_tech", 0.8, False),
])
def test_real_rss_recipe_screens_feed_result_before_selection_model(
    transport, monkeypatch, tmp_path, mode, profile, threshold, selection_runs,
):
    calls, _, _ = transport
    monkeypatch.setattr("lib.rss_feeds.config.load_profiles", lambda: {"ai_status": {}, "daily_tech": {}})
    monkeypatch.setattr(observer, "save_incident", lambda **_kwargs: SimpleNamespace(
        incident_id=None, evidence_saved=False,
    ))
    monkeypatch.setattr(observer, "notify_prompt_guard_block", lambda *_args, **_kwargs: None)
    recipe = json.loads((Path(__file__).resolve().parents[1] / "data/workflows/rss_digest.json").read_text())
    recipe["steps"] = recipe["steps"][:2]
    tool_actions = []
    prompts = []

    def execute(tool_name, params):
        tool_actions.append(params["action"])
        if params["action"] == "read":
            data = {
                "profile": profile, "batch_id": "synthetic-batch", "title": "Synthetic status",
                "interests": [], "exclude": [], "max_stories": 8,
                "items": [{"id": "fixture-status", "summary": "Synthetic provider outage."}],
                "has_items": True, "coverage_note": "", "checked_at": "2026-11-01T00:00:00Z",
            }
        else:
            data = {"profile": profile, "selected_items": [], "urls": [], "has_selection": False}
        return observer.review_tool_result(
            tool_name, {"ok": True, "data": data}, args=params,
        )

    instance = pipeline_with(execute)
    instance.mode = mode
    instance.provider = object()

    def select(message, **_kwargs):
        # The model runs after the initial feed result was scanned, and before
        # resolve_selection itself returns another screened tool result.
        assert len(calls) == 1 and tool_actions == ["read"]
        prompts.append(message)
        return '{"ids": []}'

    monkeypatch.setattr(instance, "_chat_with_usage", select)
    with config_scope(mode, {
        **scan_config(write_policy(tmp_path, [
            {**AI_RULE, "id": "ai_status_rss", "source_name": "rss_feed"}, AI_RULE,
        ])),
    }):
        result = instance.execute(recipe, f"/rss_digest {profile}")
    assert result["ok"] is selection_runs
    assert [payload["threshold"] for _url, payload in calls] == [threshold] * (2 if selection_runs else 1)
    assert all(payload["source"] == {"type": "tool_result", "name": "rss_feed"}
               for _url, payload in calls)
    if selection_runs:
        assert tool_actions == ["read", "resolve_selection"]
        assert len(prompts) == 1 and "Synthetic provider outage." in prompts[0]
        assert not any(payload["text"] == prompts[0] for _url, payload in calls)
    else:
        assert tool_actions == ["read"] and prompts == []
        assert observer.is_prompt_guard_rejection(result)
        assert result["data"]["prompt_guard"]["policy_id"] == "configured_default"


@pytest.mark.parametrize("profile,threshold", [("ai_status", 0.9), ("daily_tech", 0.8)])
@pytest.mark.parametrize("loop", [False, True])
def test_pipeline_single_and_loop_steps_use_original_validated_profile(tmp_path, monkeypatch, profile, threshold, loop):
    path = write_policy(tmp_path)
    monkeypatch.setattr("lib.rss_feeds.config.load_profiles", lambda: {"ai_status": {}, "daily_tech": {}})
    seen = []

    def execute(_tool, params):
        # Forged model/result fields must not select a policy for another profile.
        params.update(workflow_id="rss_digest", profile="ai_status", threshold=0.99)
        seen.append(resolve(path).threshold)
        return {"ok": True, "data": {"profile": "ai_status", "workflow_id": "rss_digest"}}

    instance = pipeline_with(execute)
    with config_scope("cloud"):
        result = instance.execute(rss_workflow(loop=loop), f"/rss_digest {profile}")
        assert result["ok"] is True
        assert resolve(path).threshold == 0.8
    assert seen == [threshold] * (2 if loop else 1)


def test_model_variable_changes_cannot_grant_or_remove_profile_exception(tmp_path, monkeypatch):
    path = write_policy(tmp_path)
    monkeypatch.setattr("lib.rss_feeds.config.load_profiles", lambda: {"ai_status": {}, "daily_tech": {}})
    instance = pipeline_with(lambda *_args: {"ok": True, "data": {}})
    original = instance._extract_workflow_variables

    def rewrite(query, workflow, topic):
        variables = original(query, workflow, topic)
        variables["profile"] = "ai_status"
        variables["workflow_id"] = "rss_digest"
        return variables

    monkeypatch.setattr(instance, "_extract_workflow_variables", rewrite)
    seen = []
    instance.executor.execute = lambda *_args: seen.append(resolve(path).threshold) or {"ok": True, "data": {}}
    with config_scope("cloud"):
        instance.execute(rss_workflow(), "/rss_digest daily_tech")
    assert seen == [0.8]


@pytest.mark.parametrize("changed", [
    {"from": "static", "value": "ai_status"},
    {"from": "query", "extract": "short_title", "max_words": 1},
    {"from": "query", "extract": "first_words", "max_words": True},
    {"from": "query", "extract": "first_words", "max_words": 1, "transform": "lowercase"},
])
def test_custom_profile_extraction_does_not_gain_rss_exception(monkeypatch, changed):
    monkeypatch.setattr("lib.rss_feeds.config.load_profiles", lambda: {"ai_status": {}})
    instance = pipeline_with(lambda *_args: None)
    workflow = rss_workflow()
    workflow["variables"]["profile"] = changed
    assert instance._prompt_guard_rss_profile(workflow, "/rss_digest ai_status") is None


def test_unconfigured_or_invalid_rss_profile_falls_back_and_nested_pipeline_restores(tmp_path, monkeypatch):
    path = write_policy(tmp_path)
    monkeypatch.setattr("lib.rss_feeds.config.load_profiles", lambda: {"daily_tech": {}})
    instance = pipeline_with(lambda *_args: None)
    assert instance._prompt_guard_rss_profile(rss_workflow(), "/rss_digest ai_status") is None
    assert instance._prompt_guard_rss_profile(rss_workflow(), "/rss_digest bad/profile") is None

    def unavailable():
        raise RSSFeedError("private config details")

    monkeypatch.setattr("lib.rss_feeds.config.load_profiles", unavailable)
    assert instance._prompt_guard_rss_profile(rss_workflow(), "/rss_digest ai_status") is None

    monkeypatch.setattr("lib.rss_feeds.config.load_profiles", lambda: {"ai_status": {}, "daily_tech": {}})
    observations = []
    child = pipeline_with(lambda *_args: None)

    def fail(*_args):
        observations.append(resolve(path).threshold)
        raise RuntimeError("synthetic pipeline exception")

    monkeypatch.setattr(child, "_execute", fail)

    def parent(*_args):
        observations.append(resolve(path).threshold)
        with pytest.raises(RuntimeError):
            child.execute(rss_workflow(), "/rss_digest daily_tech")
        observations.append(resolve(path).threshold)
        return {"ok": True}

    monkeypatch.setattr(instance, "_execute", parent)
    with config_scope("cloud"):
        instance.execute(rss_workflow(), "/rss_digest ai_status")
        observations.append(resolve(path).threshold)
    assert observations == [0.9, 0.8, 0.9, 0.8]


def test_incident_records_validated_policy_id_and_attachment_source(tmp_path, monkeypatch):
    monkeypatch.setattr(incidents, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(incidents, "get_config_value", lambda _key, default=None: default)
    observation = pg.PromptGuardResult(
        "scanned", flagged=True, injection_score=0.99, threshold=0.9,
        coverage_complete=True, windows_scanned=1, policy_id="ai_status_crawl",
    )
    receipt = incidents.save_incident(
        tool_name="web_text", mode="cloud", observation=observation, text="evidence",
        args={}, result={"ok": True}, source_type="attachment",
    )
    assert receipt.evidence_saved
    path, = (tmp_path / "logs/prompt-guard/incidents/cloud").glob(f"*-{receipt.incident_id}.json")
    record = json.loads(path.read_text())
    assert record["source_type"] == "attachment"
    assert record["scan"]["policy_id"] == "ai_status_crawl"
    assert record["evidence"]["representation"] == "scanned_untrusted_text"
