"""Benchmark reports preserve actual inputs without changing comparison fairness."""

import copy
import hashlib
import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

import cloud_model_benchmark as bm  # noqa: E402
from config_loader import config_scope, get_config_value  # noqa: E402


@pytest.fixture
def suite():
    return bm.load_suite()


def task(suite, case_id):
    return next(case for case in suite["cases"] if case["case_id"] == case_id)


class SnapshotOracle:
    def __init__(self, case, events, *, fail=False, mutate=False, early=False):
        self.case, self.events = case, events
        self.fail, self.mutate, self.early = fail, mutate, early
        self.snapshots = []
        self.done = set()
        self.turn = 0

    def chat_with_tools(self, messages, tools, system_prompt=None, **kwargs):
        assert self.events[-1]["event"] == "request"
        assert self.events[-1]["messages"] == messages
        assert self.events[-1]["tools"] == tools
        assert self.events[-1]["system_prompt"] == system_prompt
        assert kwargs == {"enable_thinking": False}
        assert '"example_arguments"' not in json.dumps(messages)
        assert '"receipt_requires"' not in json.dumps(messages)
        self.snapshots.append((copy.deepcopy(messages), copy.deepcopy(tools), system_prompt))
        if self.fail:
            raise RuntimeError("PRIVATE_TRANSPORT_EXCEPTION_SENTINEL")
        if self.mutate:
            messages.append({"role": "user", "content": "Adapter-private mutation"})
            tools.clear()
        if self.case is None:
            return "A short walk could be pleasant.", None, {}, None
        if self.early:
            return "{}", None, {}, None
        for step in self.case["steps"]:
            if (step.get("required", True) and step.get("turn", 0) == self.turn
                and step["step_id"] not in self.done
                and set(step.get("requires", [])) <= self.done):
                self.done.add(step["step_id"])
                return None, {"name": step["tool"],
                    "arguments": copy.deepcopy(step["example_arguments"])}, {}, None
        answer = json.dumps(self.case["turns"][self.turn]["expected"])
        self.turn += 1
        return answer, None, {}, None


def run(suite, cases, *, provider="ollama", model="synthetic", style_probes=False,
        prompt_profile="baseline", **options):
    events, providers = [], []

    def factory(*_args):
        assert events[0]["event"] == "runtime"
        assert events[0]["contract_snapshot_sha256"]
        selected = cases[len(providers)] if len(providers) < len(cases) else None
        instance = SnapshotOracle(selected, events, **options)
        providers.append(instance)
        return instance

    runner = bm.CloudBenchmarkRunner(suite, provider_name=provider, model=model, rounds=1,
        style_probes=style_probes, prompt_profile=prompt_profile, provider_factory=factory,
        checkpoint=lambda event: events.append(copy.deepcopy(event)))
    return runner.run(cases), events, providers


def assert_snapshot_hashes(snapshot):
    assert snapshot["system_prompt_sha256"] == hashlib.sha256(
        snapshot["system_prompt"].encode()).hexdigest()
    assert snapshot["messages_sha256"] == bm.content_hash(snapshot["messages"])
    assert snapshot["tools_sha256"] == bm.content_hash(snapshot["tools"])
    original = {key: value for key, value in snapshot.items() if key != "request_snapshot_sha256"}
    assert snapshot["request_snapshot_sha256"] == bm.content_hash(original)


@pytest.mark.parametrize("provider", ["ollama", "anthropic", "openai", "xai"])
def test_actual_request_inputs_and_newly_discovered_schemas_are_saved(suite, provider):
    selected = [task(suite, "missing_canvas_after_research")]
    report, events, providers = run(suite, selected, provider=provider)
    snapshots = report["request_snapshots"]
    assert report["quality_score"] == 100
    assert len(snapshots) == report["configuration"]["requests"]
    assert [(row["messages"], row["tools"], row["system_prompt"]) for row in snapshots] == providers[0].snapshots
    assert snapshots == [{key: value for key, value in event.items() if key != "event"}
        for event in events if event["event"] == "request"]
    assert all(row["kind"] == "case" for row in snapshots)
    assert [row["request"] for row in snapshots] == list(range(1, len(snapshots) + 1))
    def names(row):
        return {tool.get("name", tool.get("function", {}).get("name")) for tool in row["tools"]}
    assert "canvas" not in names(snapshots[0])
    assert "canvas" in names(snapshots[-1])
    for snapshot in snapshots:
        assert_snapshot_hashes(snapshot)
    contract = report["contract_snapshot"]
    assert contract["tools"] == suite["tools"]
    assert contract["base_prompt"] == suite["base_prompt"]
    assert contract["workload"]["cases"] == suite["cases"]
    assert contract["workload"]["runtime"] == suite["runtime"]
    assert contract["workload"]["style_probes"] == suite["style_probes"]
    assert contract["category_weights"] == bm.CATEGORY_WEIGHTS
    assert "base_prompt" not in contract["workload"]
    assert contract["tool_schema_sha256"] == {
        name: bm.tool_schema_sha256(tool) for name, tool in suite["tools"].items()}
    assert report["contract_snapshot_sha256"] == bm.content_hash(contract)
    assert report["comparison"]["contract_snapshot_sha256"] == report["contract_snapshot_sha256"]


@pytest.mark.parametrize("legacy", [False, True])
def test_tone_and_legacy_requests_are_captured_before_adapter_mutation(suite, legacy):
    if legacy:
        payload = json.loads(bm.LEGACY_FIXTURE_PATH.read_text())
        suite = bm.prepare_suite(payload,
            {name: suite["tools"][name] for name in payload["tool_schema_sha256"]},
            "Synthetic legacy test prompt", prompt_version="test")
    report, events, providers = run(suite, [task(suite, "draft_is_not_send")],
        style_probes=True, mutate=True)
    snapshots = report["request_snapshots"]
    assert len(snapshots) == 7
    assert [row["kind"] for row in snapshots] == ["case"] + ["style"] * 6
    assert [row["greeting_hint"] for row in snapshots[1:]] == [True, False] * 3
    actual = [snapshot for instance in providers for snapshot in instance.snapshots]
    assert [(row["messages"], row["tools"], row["system_prompt"]) for row in snapshots] == actual
    assert "Adapter-private mutation" not in json.dumps(snapshots)
    for snapshot in snapshots:
        assert_snapshot_hashes(snapshot)
    assert events[0]["contract_snapshot"] == report["contract_snapshot"]


def test_request_checkpoint_survives_transport_failure_without_exception_details(suite):
    report, events, _ = run(suite, [task(suite, "draft_is_not_send")], fail=True)
    assert [event["event"] for event in events] == ["runtime", "request", "response", "case_complete"]
    assert report["results"][0]["status"] == "provider_error"
    assert len(report["request_snapshots"]) == 1
    assert "PRIVATE_TRANSPORT_EXCEPTION_SENTINEL" not in json.dumps([report, events])
    assert_snapshot_hashes(report["request_snapshots"][0])


def test_failed_request_checkpoint_prevents_the_provider_call(suite):
    calls = []

    class Provider:
        def chat_with_tools(self, **kwargs):
            calls.append(kwargs)
            pytest.fail("provider called before request snapshot was flushed")

    def checkpoint(event):
        if event["event"] == "request":
            raise OSError("synthetic checkpoint failure")

    runner = bm.CloudBenchmarkRunner(suite, provider_name="ollama", model="synthetic",
        rounds=1, style_probes=False, provider_factory=lambda *_args: Provider(),
        checkpoint=checkpoint)
    with pytest.raises(OSError, match="checkpoint failure"):
        runner.run([task(suite, "draft_is_not_send")])
    assert calls == []
    assert len(runner.request_snapshots) == 1


@pytest.mark.parametrize("change", ["description", "schema", "prompt", "context", "workload"])
def test_contract_changes_automatically_separate_comparison_identity(suite, change):
    original, _, _ = run(suite, [task(suite, "draft_is_not_send")])
    changed = copy.deepcopy(suite)
    if change == "description":
        changed["tools"]["weather"]["description"] += " Current description update."
    elif change == "schema":
        changed["tools"]["weather"]["input_schema"]["properties"]["new_optional"] = {"type": "string"}
    elif change == "prompt":
        changed["base_prompt"] += "\nCurrent prompt update."
    elif change == "context":
        changed["actual_production_contract_sha256"] = {
            **changed.get("actual_production_contract_sha256", changed.get("production_contract_sha256", {})),
            "system_prompt": "new-context-fingerprint",
        }
    else:
        changed["runtime"]["location"] = "Synthetic changed location"
    updated, _, _ = run(changed, [task(changed, "draft_is_not_send")])
    assert original["fixture_sha256"] == updated["fixture_sha256"]
    assert original["comparison_key"] != updated["comparison_key"]
    assert original["contract_snapshot_sha256"] != updated["contract_snapshot_sha256"]


def test_model_identity_and_output_dependent_continuations_do_not_split_groups(suite):
    selected = [task(suite, "missing_canvas_after_research")]
    oracle, _, _ = run(suite, selected)
    early, _, _ = run(suite, selected, provider="openai", model="different-model", early=True)
    assert len(oracle["request_snapshots"]) > len(early["request_snapshots"])
    assert oracle["quality_score"] != early["quality_score"]
    assert oracle["comparison_key"] == early["comparison_key"]


def test_model_specific_configured_wording_is_disclosed_without_splitting_comparisons(suite, monkeypatch):
    import cloud_benchmark_context
    from model_prompt_overrides import ModelPromptOverride

    def override(provider, model, mode):
        return ModelPromptOverride(provider=provider, model=model, mode=mode,
            matched_model=model, enabled=True,
            sections={"routing_prepend": f"Synthetic instructions for {model}"})

    monkeypatch.setattr(cloud_benchmark_context, "load_model_prompt_override", override)
    selected = [task(suite, "draft_is_not_send")]
    first, _, _ = run(suite, selected, model="first", prompt_profile="configured")
    second, _, _ = run(suite, selected, model="second", prompt_profile="configured")
    assert first["request_snapshots"][0]["system_prompt"] != second["request_snapshots"][0]["system_prompt"]
    assert first["request_snapshots"][0]["prompt_metadata"]["override_matched_model"] == "first"
    assert second["request_snapshots"][0]["prompt_metadata"]["override_matched_model"] == "second"
    assert first["comparison_key"] == second["comparison_key"]


def test_snapshots_exclude_private_settings_and_personal_profile(suite, monkeypatch):
    import user_profile

    def forbidden(*_args, **_kwargs):
        pytest.fail("benchmark accessed private profile settings or storage")

    monkeypatch.setattr(user_profile, "get_cached_profile_card", forbidden)
    monkeypatch.setattr(user_profile, "_profile_card_enabled", forbidden)
    private_settings = {
        "OPENAI_API_KEY": "PRIVATE_API_KEY_SENTINEL",
        "JARVIS_DEFAULT_LOCATION": "PRIVATE_LOCATION_SENTINEL",
        "JARVIS_DEFAULT_POSTAL_CODE": "PRIVATE_POSTAL_SENTINEL",
        "JARVIS_TIMEZONE": "Indian/Kerguelen",
    }
    with config_scope("local", overrides=private_settings):
        report, events, _ = run(suite, [task(suite, "draft_is_not_send")], style_probes=True)
        assert get_config_value("JARVIS_DEFAULT_LOCATION") == private_settings["JARVIS_DEFAULT_LOCATION"]
    persisted = json.dumps([report, events])
    for secret in private_settings.values():
        assert secret not in persisted
    assert suite["runtime"]["profile_card"] in report["request_snapshots"][0]["system_prompt"]
    assert suite["runtime"]["location"] in persisted


def test_report_snapshot_roundtrip_and_historical_comparison_stay_offline(suite, tmp_path, monkeypatch, capsys):
    report, _, _ = run(suite, [task(suite, "draft_is_not_send")])
    current_path, markdown_path = bm.write_reports(report, tmp_path)
    assert json.loads(current_path.read_text())["request_snapshots"] == report["request_snapshots"]
    assert "Adapter input snapshots saved in JSON: 1." in markdown_path.read_text()
    paths = [current_path]
    for version in (1, 2):
        archived = copy.deepcopy(report)
        archived["schema_version"] = version
        archived["comparison_key"] = f"historical-comparison-{version}"
        for field in ("contract_snapshot", "contract_snapshot_sha256", "request_snapshots"):
            archived.pop(field, None)
        archived["configuration"].pop("contract_snapshot_sha256", None)
        archived["comparison"].pop("contract_snapshot_sha256", None)
        path = tmp_path / f"historical-{version}.json"
        path.write_text(json.dumps(archived))
        paths.append(path)
    loader = SourceFileLoader("cloud_snapshot_cli_tests", str(ROOT / "bin/benchmark-cloud-model"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    cli = importlib.util.module_from_spec(spec)
    loader.exec_module(cli)
    monkeypatch.setattr(cli, "load_suite", lambda *_args, **_kwargs: pytest.fail("comparison loaded a suite"))
    monkeypatch.setattr(cli, "CloudBenchmarkRunner", lambda *_args, **_kwargs: pytest.fail("comparison ran a provider"))
    assert cli.main(["--compare", *map(str, paths)]) == 0
    output = capsys.readouterr().out
    assert "separate comparison groups" in output
    assert "Comparison historical-compa" in output
