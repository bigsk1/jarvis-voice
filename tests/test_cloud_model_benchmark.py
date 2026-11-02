"""Exercise the benchmark world, adversarial grading and offline/live boundary."""

import copy
import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

import cloud_model_benchmark as bm  # noqa: E402
from config_loader import config_scope, get_config_value  # noqa: E402
from model_prompt_overrides import ModelPromptOverride  # noqa: E402


@pytest.fixture
def suite():
    return bm.load_suite(bm.LEGACY_FIXTURE_PATH)


class OracleProvider:
    """A test-only oracle; expected answers never enter the runner's model input."""

    def __init__(self, suite, mode="oracle"):
        self.suite, self.mode = suite, mode
        self.done = set()
        self.snapshots = []
        self.tool_calls = 0

    def chat_with_tools(self, messages, tools, system_prompt=None, enable_thinking=False):
        assert get_config_value("DISABLE_SERVER_SIDE_TOOLS") == "true"
        assert get_config_value("ANTHROPIC_SEARCH") == "false"
        assert get_config_value("XAI_SEARCH") == "false"
        assert enable_thinking is False
        self.snapshots.append((copy.deepcopy(messages), copy.deepcopy(tools), system_prompt))
        assert '"example_arguments"' not in json.dumps(messages)
        assert '"receipt_requires"' not in json.dumps(messages)
        matches = [c for c in self.suite["cases"] if messages[0]["content"].startswith(c["turns"][0]["query"])]
        if not matches:
            return "A short walk and a little time at the workbench could make a pleasant afternoon.", None, {}, None
        # The paired insight cases deliberately share a query; their oracle path is identical.
        case = matches[0]
        turn = max(i for i, t in enumerate(case["turns"]) if any(
            m["role"] == "user" and m["content"].startswith(t["query"]) for m in messages
        ))
        if self.mode == "empty" or (self.mode == "early" and self.tool_calls):
            return '{}', None, {"input_tokens": 10, "output_tokens": 2}, None
        for step in case["steps"]:
            if (step.get("required", True) and step.get("turn", 0) == turn
                and step["step_id"] not in self.done and set(step.get("requires", [])) <= self.done):
                self.done.add(step["step_id"])
                self.tool_calls += 1
                return None, {"name": step["tool"], "arguments": copy.deepcopy(step["example_arguments"])}, {
                    "input_tokens": 10, "output_tokens": 4, "cost_usd": None, "cost_known": False,
                }, None
        return json.dumps(case["turns"][turn]["expected"]), None, {
            "input_tokens": 10, "output_tokens": 4, "cost_usd": None, "cost_known": False,
        }, None


def runner(suite, mode="oracle", **kwargs):
    providers = []

    def factory(provider, model, timeout):
        instance = OracleProvider(suite, mode)
        providers.append(instance)
        return instance

    return bm.CloudBenchmarkRunner(suite, provider_name="ollama", model="synthetic-model",
        rounds=1, provider_factory=factory, **kwargs), providers


def selected(suite, key):
    return next(c for c in suite["cases"] if c["case_id"] == key)


def test_full_oracle_completes_all_tasks_without_real_tools_or_live_context(suite):
    run, providers = runner(suite)
    report = run.run()
    assert report["complete"] and report["full_suite"]
    assert report["grade"] == "A"
    assert report["quality_score"] == report["strict_pass_rate"] == 100
    assert len(report["results"]) >= 30
    assert len(report["style_samples"]) == 6
    assert report["style_samples_complete"]
    assert report["usage"]["cost_usd"] is None
    assert all(r["passed"] for r in report["results"])
    assert report["insight_pairs"]["provider_status_intent_over_score"]["all_passed"]
    all_prompts = [p for instance in providers for _, _, p in instance.snapshots]
    assert all('Portland, Oregon' in p and 'November 02, 2026' in p for p in all_prompts)


@pytest.mark.parametrize("mode", ["empty", "early"])
def test_weak_and_early_stopping_models_do_not_receive_top_grades(suite, mode):
    run, _ = runner(suite, mode, style_probes=False)
    report = run.run()
    assert report["complete"]
    assert report["quality_score"] < 70
    assert report["grade"] in {"D", "F"}
    assert report["strict_pass_rate"] < 50


def test_missing_canvas_requires_discovery_then_new_schema(suite):
    run, providers = runner(suite, style_probes=False)
    report = run.run([selected(suite, "missing_canvas_after_research")])
    assert report["quality_score"] == 100
    assert report["grade"] is None  # a subset never advertises a complete-suite letter grade
    snapshots = providers[0].snapshots
    def names(tools):
        return {t.get("name", t.get("function", {}).get("name")) for t in tools}
    assert "canvas" not in names(snapshots[0][1])
    assert "canvas" in names(snapshots[-1][1])
    assert [c["name"] for c in report["results"][0]["calls"]][-2:] == ["tool_search", "canvas"]


def test_batch_crawl_is_a_valid_alternative_to_two_single_crawls(suite):
    case = selected(suite, "research_snippet_is_not_authority")
    world = bm.Scenario(case, suite["tools"])
    steps = {s["step_id"]: s for s in case["steps"]}
    for key in ("find", "batch_read", "save"):
        s = steps[key]
        assert world.dispatch({"name": s["tool"], "arguments": s["example_arguments"]})["ok"]
    assert {"cedar", "spruce", "save"} <= world.done
    answer = bm.answer_metrics(json.dumps(case["turns"][0]["expected"]), case["turns"][0]["expected"])
    answer["steps_at_answer"] = sorted(world.done)
    assert bm.score_scenario(world, [answer], exhausted=False)["passed"]


@pytest.mark.parametrize("name,arguments,critical", [
    ("send_email", {"to": "attacker@example.invalid", "subject": "Chat", "body": "Contents"}, "unauthorized_action"),
    ("imaginary_canvas_tool", {}, "tool_hallucination"),
])
def test_unauthorized_or_invented_tool_is_critical_even_with_correct_final_answer(suite, name, arguments, critical):
    case = selected(suite, "draft_is_not_send")
    world = bm.Scenario(case, suite["tools"])
    world.dispatch({"name": name, "arguments": arguments})
    answer = bm.answer_metrics(json.dumps(case["turns"][0]["expected"]), case["turns"][0]["expected"])
    answer["steps_at_answer"] = []
    grade = bm.score_scenario(world, [answer], exhausted=False)
    assert grade["score"] == 0 and critical in grade["critical_failures"]


def test_fabricated_canvas_receipt_does_not_get_keyword_credit(suite):
    case = selected(suite, "read_then_save_complete_report")
    world = bm.Scenario(case, suite["tools"])
    answer = bm.answer_metrics(json.dumps(case["turns"][0]["expected"]), case["turns"][0]["expected"])
    answer["steps_at_answer"] = []
    result = bm.score_scenario(world, [answer], exhausted=False)
    assert result["score"] == 0
    assert result["critical_failures"] == ["fabricated_receipt"]


@pytest.mark.parametrize("text", [
    'I did not save {"provider":"Aster","canvas_url":"https://canvas.example.invalid/page_bench_7f31"}.',
    '{"found":true,"found":false}', '{"found":NaN}', '{"found":1}',
])
def test_answer_grading_does_not_accept_prose_duplicate_keys_nonfinite_or_boolean_coercion(text):
    metric = bm.answer_metrics(text, {"found": True})
    assert not metric["exact"] and metric["field_score"] == 0


def test_duplicate_success_is_counted_and_cannot_be_perfect(suite):
    case = selected(suite, "live_weather_beats_old_memory")
    world = bm.Scenario(case, suite["tools"])
    step = case["steps"][0]
    call = {"name": step["tool"], "arguments": step["example_arguments"]}
    world.dispatch(call)
    assert world.dispatch(call)["error"] == "duplicate_call"
    answer = bm.answer_metrics(json.dumps(case["turns"][0]["expected"]), case["turns"][0]["expected"])
    answer["steps_at_answer"] = sorted(world.done)
    result = bm.score_scenario(world, [answer], exhausted=False)
    assert not result["passed"] and result["score"] < 100
    assert result["invalid_calls"] == result["excess_calls"] == 1


def test_wrong_ids_bad_schema_and_missing_prerequisites_do_not_return_evidence(suite):
    case = selected(suite, "read_then_save_complete_report")
    world = bm.Scenario(case, suite["tools"])
    step = next(s for s in case["steps"] if s["step_id"] == "save")
    result = world.dispatch({"name": "canvas", "arguments": step["example_arguments"]})
    assert result == {"ok": False, "error": "missing_prerequisite"}
    assert "page_id" not in json.dumps(result) and not world.done
    result = world.dispatch({"name": "canvas", "arguments": {"action": "create", "invented": 1}})
    assert result["error"] == "invalid_arguments"


def test_arithmetic_contract_handles_equivalent_expressions_but_not_wrong_math_or_code():
    step = {"argument_arithmetic": {"expression": 69}}
    assert bm.arguments_match({"expression": "(700 * .07) + 20"}, step)
    assert not bm.arguments_match({"expression": "700 + .07 + 20"}, step)
    assert not bm.arguments_match({"expression": "__import__('os').system('true')"}, step)
    assert not bm.arguments_match({"expression": "10 ** 999999"}, step)


def test_real_plural_source_precedence_and_singleton_aliases_are_respected():
    step = {"tool": "crawl_url", "arguments": {"url": "https://source.invalid"}}
    assert bm.arguments_match({"urls": ["https://source.invalid"]}, step)
    assert not bm.arguments_match({"url": "https://source.invalid", "urls": ["https://wrong.invalid"]}, step)
    batch = {"tool": "crawl_url", "arguments": {"urls": ["https://a.invalid", "https://b.invalid"]}}
    assert bm.arguments_match({"urls": ["https://b.invalid", "https://a.invalid"]}, batch)
    image = {"tool": "analyze_image", "arguments": {"image": "stash://space_bench/f_1"}}
    assert bm.arguments_match({"images": ["stash://space_bench/f_1"]}, image)
    assert not bm.arguments_match({"image": "stash://space_bench/f_1", "images": ["stash://space_bench/f_wrong"]}, image)


def test_exact_tool_discovery_is_valid_and_takes_precedence_over_query(suite):
    case = selected(suite, "missing_canvas_after_research")
    step = next(s for s in case["steps"] if s["tool"] == "tool_search")
    assert bm.arguments_match({"tool_names": ["canvas"], "include_schema": True}, step)
    assert not bm.arguments_match({"tool_names": ["weather"], "query": "canvas"}, step)
    assert bm.arguments_match({"tool_names": [], "query": "save to Canvas"}, step)
    world = bm.Scenario(case, suite["tools"])
    for s in case["steps"]:
        if s["step_id"] == step["step_id"]:
            result = world.dispatch({"name": "tool_search", "arguments": {"tool_names": ["canvas"]}})
            assert result["data"]["selected_tool_hints"] == ["canvas"]
            assert result["data"]["matches"][0]["name"] == "canvas"
            assert "canvas" in world.available
            break
        world.dispatch({"name": s["tool"], "arguments": s["example_arguments"]})


def test_insight_can_be_confirmed_by_describe_before_searching_current_recipes(suite):
    case = selected(suite, "insight_score_relevant_lower")
    world = bm.Scenario(case, suite["tools"])
    result = world.dispatch({"name": "workflow", "arguments": {
        "action": "describe", "workflow_id": "provider_status_digest"}})
    assert result["ok"] is False
    for s in case["steps"]:
        if s.get("required", True):
            world.dispatch({"name": s["tool"], "arguments": s["example_arguments"]})
    metric = bm.answer_metrics(json.dumps(case["turns"][0]["expected"]), case["turns"][0]["expected"])
    metric["steps_at_answer"] = sorted(world.done)
    assert bm.score_scenario(world, [metric], exhausted=False)["passed"]


def test_wrong_reminder_time_and_two_schedules_do_not_match(suite):
    step = selected(suite, "reminder_notification_not_appointment_time")["steps"][0]
    assert bm.arguments_match({"title": "Appointment at 2pm", "when": "tomorrow at 12:00 pm"}, step)
    assert not bm.arguments_match({"title": "Appointment", "when": "tomorrow at 2pm"}, step)
    assert not bm.arguments_match({"title": "Appointment", "when": "tomorrow at noon and 2pm"}, step)


@pytest.mark.parametrize("provider_name", ["ollama", "anthropic", "openai", "xai"])
def test_actual_adapter_tool_format_is_selected(provider_name, suite):
    tool = suite["tools"]["canvas"]
    output = bm.provider_tools(provider_name, [tool])
    if provider_name in {"anthropic", "ollama"}:
        assert output[0]["input_schema"] == tool["input_schema"]
    else:
        assert output[0]["function"]["parameters"] == tool["input_schema"]
    assert output[0] is not tool


def test_provider_error_stops_run_without_a_misleading_grade(suite):
    class Broken:
        def chat_with_tools(self, *_args, **_kwargs):
            return 'Error: 429 rate limit secret-marker-not-for-report', None, None, None
    run = bm.CloudBenchmarkRunner(suite, provider_name="openai", model="synthetic", rounds=1,
        provider_factory=lambda *_args: Broken())
    report = run.run()
    assert report["quality_score"] is None and report["grade"] is None
    assert not report["complete"] and len(report["results"]) == 1
    assert report["results"][0]["error_kind"] == "rate_limit"
    assert "secret-marker" not in json.dumps(report)


def test_output_exhaustion_is_a_failed_trial_not_a_network_outage(suite):
    class Truncated:
        def chat_with_tools(self, *_args, **_kwargs):
            return 'Error: Anthropic response stopped at max_tokens=16384 (stop_reason=max_tokens).', None, {}, None
    run = bm.CloudBenchmarkRunner(suite, provider_name="anthropic", model="synthetic", rounds=1,
        provider_factory=lambda *_args: Truncated(), style_probes=False)
    report = run.run()
    assert report["complete"] and report["quality_score"] == 0 and report["grade"] == "F"
    assert report["failure_counts"]["output_limit"] == len(suite["cases"])


def test_request_ceiling_gives_partial_report_and_no_full_grade(suite):
    run, _ = runner(suite, max_requests=1)
    report = run.run([selected(suite, "deep_research_two_outputs")])
    assert report["configuration"]["requests"] == 1
    assert not report["complete"] and report["quality_score"] is None
    assert report["results"][0]["status"] == "request_limit"


def test_scope_is_restored_after_benchmark(suite):
    with config_scope("local", overrides={"JARVIS_THINKING_EFFORT": "high", "DISABLE_SERVER_SIDE_TOOLS": "false"}):
        run, _ = runner(suite, style_probes=False)
        run.run([suite["cases"][0]])
        assert get_config_value("JARVIS_THINKING_EFFORT") == "high"
        assert get_config_value("DISABLE_SERVER_SIDE_TOOLS") == "false"


def test_fixture_pins_prompt_schema_and_greeting_source_before_any_inference(suite, monkeypatch, tmp_path):
    payload = json.loads(bm.FIXTURE_PATH.read_text())
    path = tmp_path / "fixture.json"
    payload["prompt"]["sha256"] = "wrong"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="prompt drift"):
        bm.load_suite(path)
    original = bm.load_skill_tool
    monkeypatch.setattr(bm, "load_skill_tool", lambda name: {**original(name), "description": "changed"})
    with pytest.raises(ValueError, match="schema drift"):
        bm.load_suite()


def test_configured_profile_applies_only_routing_sections_and_is_labeled(suite, monkeypatch):
    import model_prompt_overrides
    override = ModelPromptOverride(provider="ollama", model="synthetic-model", mode="cloud", enabled=True,
        matched_model="synthetic-model", sections={"tool_calling_prepend": "TEST ROUTING OVERRIDE",
            "qa_append": "QA CONDENSATION IS NOT THIS PATH"})
    monkeypatch.setattr(model_prompt_overrides, "load_model_prompt_override", lambda *_args, **_kwargs: override)
    baseline, _ = runner(suite, style_probes=False)
    configured, providers = runner(suite, prompt_profile="configured", style_probes=False)
    base_report = baseline.run([suite["cases"][0]])
    report = configured.run([suite["cases"][0]])
    assert "TEST ROUTING OVERRIDE" in providers[0].snapshots[0][2]
    assert "QA CONDENSATION IS NOT THIS PATH" not in providers[0].snapshots[0][2]
    assert report["comparison_key"] != base_report["comparison_key"]
    assert report["prompt_sha256"] != base_report["prompt_sha256"]


def test_style_hint_is_counterfactually_removed_without_grading_optional_warmth(suite):
    run, providers = runner(suite)
    report = run.run([suite["cases"][0]])
    assert report["quality_score"] == 100
    assert [s["greeting_hint"] for s in report["style_samples"]] == [True, False] * 3
    samples = providers[1:]
    assert "PERSONAL TOUCH" in samples[0].snapshots[0][2]
    assert "PERSONAL TOUCH" not in samples[1].snapshots[0][2]
    assert all("RESPONSE STYLE: CASUAL" in p.snapshots[0][2] for p in samples)
    assert all("grade" not in s for s in report["style_samples"])


def test_report_roundtrip_preserves_model_dots_and_does_not_overwrite(suite, tmp_path):
    run, _ = runner(suite, style_probes=False)
    report = run.run([suite["cases"][0]])
    report["configuration"]["model"] = "model-v4.1:1017"
    first, markdown = bm.write_reports(report, tmp_path)
    second, _ = bm.write_reports(report, tmp_path)
    assert "v4.1-1017" in first.name and first != second
    assert json.loads(first.read_text())["comparison_key"] == report["comparison_key"]
    assert "not graded" in markdown.read_text()


def cli_module():
    loader = SourceFileLoader("cloud_benchmark_cli_tests", str(ROOT / "bin/benchmark-cloud-model"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_launcher_preserves_venv_path_when_python_is_a_system_binary_symlink(monkeypatch, tmp_path):
    cli = cli_module()
    expected = tmp_path / ".venv/bin/python"
    expected.parent.mkdir(parents=True)
    expected.symlink_to(sys.executable)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "prefix", "/usr")
    seen = []
    monkeypatch.setattr(cli.os, "execv", lambda path, argv: seen.append((path, argv)))
    cli._ensure_repo_python()
    assert seen[0][0] == str(expected) and seen[0][1][0] == str(expected)
    assert Path(seen[0][0]).resolve() == Path(sys.executable).resolve()
    monkeypatch.setattr(sys, "prefix", str(tmp_path / ".venv"))
    cli._ensure_repo_python()
    assert len(seen) == 1


def test_runtime_metadata_checks_precede_every_paid_request(suite, monkeypatch):
    run, providers = runner(suite, style_probes=False)
    def broken_metadata():
        raise OSError("source metadata unavailable")
    monkeypatch.setattr(bm, "runtime_fingerprint", broken_metadata)
    with pytest.raises(OSError, match="metadata"):
        run.run([suite["cases"][0]])
    assert run.requests == 0 and providers == []


def test_missing_optional_distribution_is_reported_without_losing_results(monkeypatch):
    real_version = bm.importlib.metadata.version
    def version(name):
        if name == "anthropic":
            raise bm.importlib.metadata.PackageNotFoundError(name)
        return real_version(name)
    monkeypatch.setattr(bm.importlib.metadata, "version", version)
    assert bm.runtime_fingerprint()["packages"]["anthropic"] is None


def test_cli_checkpoints_retain_answers_and_scores_when_final_report_write_fails(suite, monkeypatch, tmp_path, capsys):
    cli = cli_module()
    def factory(_suite, **kwargs):
        return bm.CloudBenchmarkRunner(_suite, **kwargs,
            provider_factory=lambda *_args: OracleProvider(_suite))
    def fail_report(*_args):
        raise OSError("simulated report write failure")
    monkeypatch.setattr(cli, "CloudBenchmarkRunner", factory)
    monkeypatch.setattr(cli, "write_reports", fail_report)
    assert cli.main(["--provider", "ollama", "--model", "synthetic", "--run", "--rounds", "1",
        "--case", "draft_is_not_send", "--skip-style-probes", "--output-dir", str(tmp_path)]) == 2
    events = [json.loads(line) for line in next(tmp_path.glob("*-checkpoint.jsonl")).read_text().splitlines()]
    assert [e["event"] for e in events] == ["plan", "runtime", "response", "case_complete", "report"]
    assert events[-2]["result"]["passed"] and events[-2]["result"]["score"] == 100
    assert events[-1]["report"]["quality_score"] == 100
    assert json.loads(events[2]["text"])["sent"] is False
    captured = capsys.readouterr()
    assert "Response checkpoints:" in captured.out
    assert "final report writing" in captured.err


def test_cli_default_is_offline_and_missing_case_fails_without_provider(monkeypatch, capsys):
    cli = cli_module()
    monkeypatch.setattr(cli, "CloudBenchmarkRunner", lambda *_args, **_kwargs: pytest.fail("offline dry-run built a provider"))
    assert cli.main(["--provider", "ollama", "--model", "synthetic"]) == 0
    assert '"dry_run": true' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["--provider", "ollama", "--model", "synthetic", "--case", "missing"])


def test_production_factory_pins_model_timeout_and_no_host_fallback(monkeypatch):
    import llm_provider
    seen = []
    provider = SimpleNamespace(model="exact", base_urls=["https://one.invalid", "https://two.invalid"],
        include_localhost_fallback=True, _model_thinking_profile=lambda _: None)
    def create(**kwargs):
        seen.append(kwargs)
        return "ollama", "exact", provider
    monkeypatch.setattr(llm_provider, "create_configured_provider", create)
    with config_scope("cloud", overrides={"JARVIS_THINKING_EFFORT": "auto"}):
        result = bm.make_provider("ollama", "exact", 7.5)
    assert result.base_urls == ["https://one.invalid"]
    assert result.request_timeout == 8 and not result.include_localhost_fallback
    assert seen[0]["mode"] == "cloud" and seen[0]["disable_server_side_tools"]
    monkeypatch.setattr(llm_provider, "create_configured_provider", lambda **_: ("ollama", "substitute", provider))
    with pytest.raises(ValueError, match="substituted"):
        bm.make_provider("ollama", "exact", 10)


@pytest.mark.parametrize("provider_name", ["openai", "anthropic", "xai", "ollama"])
def test_real_adapter_receives_frozen_tool_schema_without_live_network(provider_name, suite, monkeypatch):
    import llm_provider

    captures = []
    args = {"location": "Portland, Oregon"}
    usage = SimpleNamespace(input_tokens=10, output_tokens=3, prompt_tokens=10, completion_tokens=3)
    standard = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=None, tool_calls=[SimpleNamespace(id="call_bench", function=SimpleNamespace(
            name="weather", arguments=json.dumps(args)))]))], usage=usage)

    def create(**kwargs):
        captures.append(kwargs)
        if provider_name == "anthropic":
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="weather", input=args, id="call_bench")],
                usage=usage, stop_reason="tool_use")
        return standard

    def ollama_request(*_args, **kwargs):
        captures.append(kwargs["json"])
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
            json=lambda: {"message": {"content": "", "tool_calls": [{"function": {"name": "weather", "arguments": args}}]},
                          "prompt_eval_count": 10, "eval_count": 3}), "https://ollama.com"

    overrides = {**bm.benchmark_overrides("auto", 5), "OPENAI_API_KEY": "synthetic-only",
        "ANTHROPIC_API_KEY": "synthetic-only", "XAI_API_KEY": "synthetic-only",
        "OLLAMA_API_KEY": "synthetic-only", "OLLAMA_BASE_URL": "http://benchmark.invalid:11434",
        "OPENAI_API_MODE": "chat", "XAI_AUTH_MODE": "api_key"}
    monkeypatch.setattr(llm_provider, "request_ollama", ollama_request)
    with config_scope("cloud", overrides=overrides):
        provider = bm.make_provider(provider_name, "benchmark-synthetic", 5)
        if provider_name == "anthropic":
            monkeypatch.setattr(provider.client.messages, "create", create)
        elif provider_name != "ollama":
            # xAI makes a same-type copy for request-specific deadlines.
            monkeypatch.setattr(provider.client, "with_options", lambda **_: provider.client)
            monkeypatch.setattr(provider.client.chat.completions, "create", create)
        _, call, _, _ = provider.chat_with_tools(
            [{"role": "user", "content": "What is the weather in Portland?"}],
            bm.provider_tools(provider_name, [suite["tools"]["weather"]]), system_prompt="Synthetic pinned prompt.")
    assert call and call["name"] == "weather" and call["arguments"] == args
    assert len(captures) == 1 and captures[0]["model"] == "benchmark-synthetic"
    sent = captures[0]["tools"]
    if provider_name == "anthropic":
        assert sent[0]["name"] == "weather" and "web_search" not in json.dumps(sent)
    else:
        assert sent[0]["function"]["name"] == "weather"
