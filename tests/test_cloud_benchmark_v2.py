"""Independent path and grading checks, including false failures from V1."""

import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

import cloud_model_benchmark as bm  # noqa: E402
from cloud_benchmark_context import BenchmarkContext  # noqa: E402
from cloud_benchmark_v2 import ScenarioV2, answer_metrics_v2, score_v2  # noqa: E402
from config_loader import config_scope  # noqa: E402


@pytest.fixture
def suite():
    return bm.load_suite()


def case(suite, name):
    return next(c for c in suite["cases"] if c["case_id"] == name)


class Oracle:
    def __init__(self, task):
        self.task = task
        self.done = set()
        self.turn = 0
        self.snapshots = []

    def chat_with_tools(self, messages, tools, system_prompt=None, **_kwargs):
        self.snapshots.append((copy.deepcopy(messages), copy.deepcopy(tools), system_prompt))
        if self.task is None:
            return "A short walk could be pleasant.", None, {}, None
        for step in self.task["steps"]:
            if (
                step.get("required", True)
                and step.get("turn", 0) == self.turn
                and step["step_id"] not in self.done
            ):
                self.done.add(step["step_id"])
                return (
                    None,
                    {"name": step["tool"], "arguments": copy.deepcopy(step["example_arguments"])},
                    {},
                    None,
                )
        text = json.dumps(self.task["turns"][self.turn]["expected"])
        self.turn += 1
        return text, None, {}, None


def run(suite, tasks=None, **kwargs):
    tasks = tasks or suite["cases"]
    providers = []

    def factory(*_args):
        provider = Oracle(tasks[len(providers)] if len(providers) < len(tasks) else None)
        providers.append(provider)
        return provider

    runner = bm.CloudBenchmarkRunner(
        suite,
        provider_name="ollama",
        model="synthetic-only",
        rounds=1,
        provider_factory=factory,
        **kwargs,
    )
    return runner.run(tasks), providers


def finish(world, task):
    answers = []
    for index, turn in enumerate(task["turns"]):
        metric = answer_metrics_v2(json.dumps(turn["expected"]), turn)
        metric["steps_at_answer"] = sorted(world.done)
        answers.append(metric)
    return score_v2(world, answers, exhausted=False)


def test_legacy_fixture_is_byte_for_byte_preserved():
    assert (
        hashlib.sha256(bm.LEGACY_FIXTURE_PATH.read_bytes()).hexdigest()
        == "506f428a6108f59fc3597657db211e1d404d116089884a8d2e672ee094631933"
    )


def test_v2_fixture_is_preserved_and_rejects_changed_production_context():
    path = bm.FIXTURE_PATH.with_name("cloud-model-v2.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "dffc33e1b203ac5892745a28a658c41ff5c47cd2cefa39c4e5fddee26f69857d"
    )
    with pytest.raises(ValueError, match="production context drift"):
        bm.load_suite(path)


def test_v3_fixture_is_preserved_after_live_calibration():
    path = bm.FIXTURE_PATH.with_name("cloud-model-v3.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "b16c363f09cc093aeae53ccf36e0a222c43bc44a8d65f26b63d81e1440ab6974"
    )


def test_v4_fixture_is_byte_for_byte_preserved():
    path = bm.FIXTURE_PATH.with_name("cloud-model-v4.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "502a082ef680cd9fe2788cf5687d583fae0b0ec673ed242ff2ba6059a35bb022"
    )


def test_v5_fixture_is_byte_for_byte_preserved():
    path = bm.FIXTURE_PATH.with_name("cloud-model-v5.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "9bb0722682a3a3c9ee84c6dae835caccb2259de1afa721acf91df5021925f571"
    )


def test_v6_fixture_is_byte_for_byte_preserved():
    path = bm.FIXTURE_PATH.with_name("cloud-model-v6.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "0c55af070f18aec67a07f543aa598689bdb735e2b79beac8f3f976263f0d48b2"
    )


def test_v7_fixture_is_byte_for_byte_preserved():
    path = bm.FIXTURE_PATH.with_name("cloud-model-v7.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "0200b1e2c82c2c7505c4446e7dfae7936c09e0d20cf9a7098130707a1a07bb8e"
    )


def test_v8_fixture_is_byte_for_byte_preserved():
    path = bm.FIXTURE_PATH.with_name("cloud-model-v8.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "d16910b61307e82ba2b1718947c1716fec8b81b7a24d19df7b994c7000de7611"
    )


def test_v5_refreshes_only_pdf_tool_contracts_and_fixture_identity():
    previous = json.loads(bm.FIXTURE_PATH.with_name("cloud-model-v4.json").read_text())
    current = json.loads(bm.FIXTURE_PATH.with_name("cloud-model-v5.json").read_text())
    assert current["fixture_id"] == "jarvis-cloud-model-v5"
    assert current["provenance"]["supersedes"] == previous["fixture_id"]
    changed = {name for name, digest in previous["tool_schema_sha256"].items()
               if current["tool_schema_sha256"][name] != digest}
    assert changed == {"convert_file", "pdf_create"}
    current["tool_schema_sha256"] = previous["tool_schema_sha256"]
    current["fixture_id"] = previous["fixture_id"]
    current["provenance"] = previous["provenance"]
    old_match = case(previous, "missing_capability_is_not_substitute")["steps"][0]["result"]["data"]["matches"][0]
    match = case(current, "missing_capability_is_not_substitute")["steps"][0]["result"]["data"]["matches"][0]
    assert match["name"] == "pdf_create"
    assert match["description"] != old_match["description"]
    match["description"] = old_match["description"]
    assert current == previous


def test_v6_refreshes_only_image_tool_contract_and_fixture_identity():
    previous = json.loads(bm.FIXTURE_PATH.with_name("cloud-model-v5.json").read_text())
    current = json.loads(bm.FIXTURE_PATH.with_name("cloud-model-v6.json").read_text())
    assert current["fixture_id"] == "jarvis-cloud-model-v6"
    assert current["provenance"]["supersedes"] == previous["fixture_id"]
    changed = {name for name, digest in previous["tool_schema_sha256"].items()
               if current["tool_schema_sha256"][name] != digest}
    assert changed == {"generate_image"}
    assert current["tool_schema_sha256"]["generate_image"] == (
        "d5b738d1d9c63107a1170dccb65d29466aaf920543c103282dddbc756063e918"
    )
    current["tool_schema_sha256"] = previous["tool_schema_sha256"]
    current["fixture_id"] = previous["fixture_id"]
    current["provenance"] = previous["provenance"]
    assert current == previous


def test_v7_refreshes_only_vision_tool_contract_and_fixture_identity():
    previous = json.loads(bm.FIXTURE_PATH.with_name("cloud-model-v6.json").read_text())
    current = json.loads(bm.FIXTURE_PATH.with_name("cloud-model-v7.json").read_text())
    assert current["fixture_id"] == "jarvis-cloud-model-v7"
    assert current["provenance"]["supersedes"] == previous["fixture_id"]
    changed = {name for name, digest in previous["tool_schema_sha256"].items()
               if current["tool_schema_sha256"][name] != digest}
    assert changed == {"analyze_image"}
    assert current["tool_schema_sha256"]["analyze_image"] == (
        "f02a4c086f6a24401c71a8966a8c3994887c807dee0a6e32daa815ce48e3d27f"
    )
    current["tool_schema_sha256"] = previous["tool_schema_sha256"]
    current["fixture_id"] = previous["fixture_id"]
    current["provenance"] = previous["provenance"]
    assert current == previous


def test_v8_refreshes_only_image_tool_contract_and_fixture_identity():
    previous = json.loads(bm.FIXTURE_PATH.with_name("cloud-model-v7.json").read_text())
    current = json.loads(bm.FIXTURE_PATH.with_name("cloud-model-v8.json").read_text())
    assert current["fixture_id"] == "jarvis-cloud-model-v8"
    assert current["provenance"]["supersedes"] == previous["fixture_id"]
    changed = {name for name, digest in previous["tool_schema_sha256"].items()
               if current["tool_schema_sha256"][name] != digest}
    assert changed == {"generate_image"}
    assert current["tool_schema_sha256"]["generate_image"] == (
        "3d790f3112806cf12b979fdd0dc8609d570509dfd1c518d5a27022eb22371308"
    )
    current["tool_schema_sha256"] = previous["tool_schema_sha256"]
    current["fixture_id"] = previous["fixture_id"]
    current["provenance"] = previous["provenance"]
    assert current == previous


def test_v9_refreshes_only_reminder_tool_contract_and_fixture_identity(suite):
    previous = json.loads(bm.FIXTURE_PATH.with_name("cloud-model-v8.json").read_text())
    current = json.loads(bm.FIXTURE_PATH.read_text())
    assert current["fixture_id"] == "jarvis-cloud-model-v9"
    assert current["provenance"]["supersedes"] == previous["fixture_id"]
    changed = {name for name, digest in previous["tool_schema_sha256"].items()
               if current["tool_schema_sha256"][name] != digest}
    assert changed == {"create_reminder"}
    assert current["tool_schema_sha256"]["create_reminder"] == bm.tool_schema_sha256(
        suite["tools"]["create_reminder"]
    )
    current["tool_schema_sha256"] = previous["tool_schema_sha256"]
    current["fixture_id"] = previous["fixture_id"]
    current["provenance"] = previous["provenance"]
    assert current == previous


@pytest.mark.parametrize("location", ["Seattle, Washington", "Seattle, WA"])
def test_declared_weather_location_equivalents_match_the_same_place(suite, location):
    task = case(suite, "negative_lesson_does_not_disable_needed_tool")
    world = ScenarioV2(task, suite["tools"])
    result = world.dispatch({"name": "weather", "arguments": {"location": location}})
    assert result["ok"] and result["data"]["temperature"] == 6
    assert "weather" in world.done and not world.fixture_gap
    assert world.calls[-1]["arguments"]["location"] == location


@pytest.mark.parametrize("action", ["create", "from_text"])
@pytest.mark.parametrize("correct", [True, False])
def test_pdf_equivalent_actions_grade_actual_document_contents(suite, action, correct):
    task = case(suite, "missing_capability_is_not_substitute")
    world = ScenarioV2(task, suite["tools"])
    world.dispatch({"name": "tool_search", "arguments": {"query": "create PDF document", "include_schema": True}})
    step = next(s for s in task["steps"] if s["step_id"] == "pdf")
    args = {**step["example_arguments"], "action": action}
    if not correct:
        args["text"] = "An unrelated document."
    result = world.dispatch({"name": "pdf_create", "arguments": args})
    assert result["ok"] and not world.fixture_gap
    assert result["data"]["mime_type"] == "application/pdf"
    score = finish(world, task)
    assert score["passed"] is correct
    if not correct:
        assert "artifact_facts" in score["issues"]


def test_pdf_does_not_accept_invented_input_files(suite):
    task = case(suite, "missing_capability_is_not_substitute")
    world = ScenarioV2(task, suite["tools"])
    world.dispatch({"name": "tool_search", "arguments": {"tool_names": ["pdf_create"], "include_schema": True}})
    args = {"action": "create", "text": "The launch window is Friday.", "files": ["stash://space_guessed/f_guessed"]}
    assert world.dispatch({"name": "pdf_create", "arguments": args})["error"] == "unproven_selector"


@pytest.mark.parametrize("timezone_name", ["America/Los_Angeles", "PST", "Pacific Standard Time"])
def test_timezone_answer_can_use_the_label_actually_shown_in_the_prompt(suite, timezone_name):
    task = case(suite, "configured_location_is_already_injected")
    turn = task["turns"][0]
    prompt = BenchmarkContext(suite, "openai", "synthetic", "baseline").system_prompt(task["initial_tools"])
    assert "PST" in prompt
    answer = {**turn["expected"], "timezone": timezone_name}
    assert answer_metrics_v2(json.dumps(answer), turn)["factually_correct"]
    answer["timezone"] = "EST"
    assert not answer_metrics_v2(json.dumps(answer), turn)["factually_correct"]


def test_human_provider_name_alias_applies_to_answer_and_saved_json_only(suite):
    task = case(suite, "research_snippet_is_not_authority")
    world = ScenarioV2(task, suite["tools"])
    for step in task["steps"]:
        if not step.get("required", True):
            continue
        args = copy.deepcopy(step["example_arguments"])
        if step["step_id"] == "save":
            content = json.loads(args["content"])
            content["winner"] = "spruce"
            args["content"] = json.dumps(content)
        assert world.dispatch({"name": step["tool"], "arguments": args})["ok"]
    turn = task["turns"][0]
    answer = {**turn["expected"], "winner": "spruce"}
    metric = answer_metrics_v2(json.dumps(answer), turn)
    metric["steps_at_answer"] = sorted(world.done)
    assert score_v2(world, [metric], exhausted=False)["passed"]
    answer["canvas_url"] = answer["canvas_url"].upper()
    assert not answer_metrics_v2(json.dumps(answer), turn)["factually_correct"]


def test_current_suite_retains_v4_literal_text_requirements(suite):
    assert suite["fixture_id"] == "jarvis-cloud-model-v9"
    email = case(suite, "authorized_literal_recipient_needs_no_memory")
    assert "subject and body verbatim" in email["turns"][0]["query"]
    image = case(suite, "discover_then_analyze_artifact")
    assert "only the code itself" in image["turns"][0]["query"]


def test_fixture_rejects_unreviewable_argument_aliases(suite, tmp_path):
    payload = json.loads(bm.FIXTURE_PATH.read_text())
    task = case(payload, "missing_capability_is_not_substitute")
    step = next(s for s in task["steps"] if s["step_id"] == "pdf")
    step["argument_aliases"] = {"action": ["invented_action"]}
    path = tmp_path / "invalid-alias.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="alias violates the tool schema"):
        bm.load_suite(path)


def test_profile_boundary_matches_live_wrapper_without_reading_private_profile(suite, monkeypatch):
    import user_profile

    def forbidden(*_args, **_kwargs):
        pytest.fail("benchmark accessed personal profile settings or storage")

    monkeypatch.setattr(user_profile, "get_cached_profile_card", forbidden)
    monkeypatch.setattr(user_profile, "_profile_card_enabled", forbidden)
    context = BenchmarkContext(suite, "ollama", "synthetic", "baseline")
    card = suite["runtime"]["profile_card"]
    with_card = context.system_prompt(["weather"])
    empty_suite = {**suite, "runtime": {**suite["runtime"], "profile_card": ""}}
    without_card = BenchmarkContext(empty_suite, "ollama", "synthetic", "baseline").system_prompt(["weather"])
    assert with_card == user_profile.append_profile_card_for_router_direct_answer(
        without_card, card_text=card,
    )
    assert "current user instruction and active response preferences" in with_card
    assert "win on conflict" in with_card


def test_benchmark_uses_runtime_module_objects(suite, monkeypatch):
    import context_assembler
    import router_v2

    context = BenchmarkContext(suite, "ollama", "synthetic", "baseline")
    assert type(context.assembler) is context_assembler.ContextAssembler
    original = router_v2.LLMRouter.build_system_prompt
    calls = []

    def capture(self, **kwargs):
        calls.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(router_v2.LLMRouter, "build_system_prompt", capture)
    context.system_prompt(["weather"])
    assert len(calls) == 1


def test_supplied_clock_normalizes_router_local_time_and_rejects_naive_values(suite):
    from router_v2 import LLMRouter

    router = object.__new__(LLMRouter)
    router.timezone = ZoneInfo("America/Los_Angeles")
    router._system_prompt_base = suite["base_prompt"]
    router._provider_override = "ollama"
    router._excluded_tools = []
    router.registry = SimpleNamespace(tools={})
    router.provider = SimpleNamespace(enable_search=False)
    router.prompt_override = None
    with config_scope("cloud", overrides={"LLM_PROVIDER": "ollama", "JARVIS_RESPONSE_STYLE": "detailed"}):
        kwargs = {"profile_card_appender": lambda text: text}
        clock = datetime(2026, 11, 2, 18, 30, tzinfo=timezone.utc)
        utc_prompt = router.build_system_prompt(now=clock, **kwargs)
        local_prompt = router.build_system_prompt(now=clock.astimezone(router.timezone), **kwargs)
        assert utc_prompt == local_prompt
        assert "at 10:30 AM PST" in utc_prompt and "at 18:30 UTC" in utc_prompt
        with pytest.raises(ValueError, match="timezone-aware"):
            router.build_system_prompt(now=clock.replace(tzinfo=None), **kwargs)


def test_supplied_context_clocks_normalize_consistently_and_reject_naive_values(suite):
    context = BenchmarkContext(suite, "ollama", "synthetic", "baseline")
    clock = context.clock
    prior = [{"role": "assistant", "content": "Earlier answer", "timestamp": "2026-11-02T18:29:00+00:00"}]
    executions = [{"tool": "weather", "arguments": {}, "result": {"ok": True, "data": {}},
                   "meta": {"executed_at_iso": prior[0]["timestamp"], "ttl_seconds": 300}}]
    for formatter, args in (
        (context.assembler.format_conversation_context, ("Follow up", prior)),
        (context.assembler.build_turn_context, ("Follow up", executions)),
    ):
        text = formatter(*args, now=clock)
        assert text == formatter(*args, now=clock.astimezone(context.zone))
        assert "60 seconds" in text or "age=60s" in text
        with pytest.raises(ValueError, match="timezone-aware"):
            formatter(*args, now=clock.replace(tzinfo=None))


@pytest.mark.parametrize("constant", ["_CHAT_ONLY_SYSTEM_POLICY", "_BACKGROUND_RECEIPT_SYSTEM_POLICY"])
def test_policy_text_drift_fails_offline_validation(monkeypatch, constant):
    import router_v2

    monkeypatch.setattr(router_v2, constant, getattr(router_v2, constant) + " Changed.")
    with pytest.raises(ValueError, match="production context drift"):
        bm.load_suite()


def test_shared_policies_keep_inherited_prompts_and_effective_search_boundaries(suite):
    from cloud_benchmark_context import fixture_registry
    from router_v2 import (
        _BACKGROUND_RECEIPT_SYSTEM_POLICY,
        _CHAT_ONLY_SYSTEM_POLICY,
        _apply_request_system_policies,
        _apply_search_availability_policy,
    )

    assert _apply_request_system_policies(None, chat_only=False, background_selected=True) is None
    assert _apply_request_system_policies(None, chat_only=True, background_selected=True) == _CHAT_ONLY_SYSTEM_POLICY
    registry = fixture_registry(suite, ["tool_search", "brave_llm_context"])
    assert _apply_search_availability_policy(None, registry, set(), ["tool_search"]) == (None, [])
    assert _apply_search_availability_policy("base", registry, set(), ["weather"]) == ("base", [])
    assert _apply_search_availability_policy("base", registry, {"brave_llm_context"}, ["tool_search"]) == ("base", [])
    context = BenchmarkContext(suite, "ollama", "synthetic", "baseline")
    prompt = context.system_prompt(["tool_search"], background=True, eligible_tools=registry.tools)
    assert prompt.startswith(_BACKGROUND_RECEIPT_SYSTEM_POLICY)
    assert prompt.endswith("follow its description.")
    assert "Local web search tools" in prompt
    prompt = context.system_prompt([], casual=True, background=True)
    assert _BACKGROUND_RECEIPT_SYSTEM_POLICY not in prompt
    assert prompt.endswith(_CHAT_ONLY_SYSTEM_POLICY)


def test_v2_oracle_covers_every_case_and_production_context(suite):
    report, providers = run(suite)
    failed = [
        (r["case_id"], r["status"], r.get("issues"), r.get("missing_steps"))
        for r in report["results"]
        if not r["passed"]
    ]
    assert not failed, failed
    assert report["grade"] == "A" and report["task_pass_rate"] == report["strict_pass_rate"] == 100
    assert len(report["results"]) == 44
    assert report["configuration"]["runtime"]["source_sha256"]["orchestrator/context_assembler.py"]
    prompts = [p for instance in providers for _, _, p in instance.snapshots]
    assert all("Monday, November 02, 2026" in p for p in prompts)


def test_separate_searches_interleaved_with_reads_complete_research(suite):
    task = case(suite, "research_snippet_is_not_authority")
    world = ScenarioV2(task, suite["tools"])
    steps = {s["step_id"]: s for s in task["steps"]}
    first = world.dispatch({"name": "brave_llm_context", "arguments": {"query": "Cedar API plans"}})
    assert len(first["data"]["grounding"]["generic"]) == 1
    world.dispatch(
        {"name": "crawl_url", "arguments": {"url": "https://cedar.example.invalid/limits"}}
    )
    world.dispatch({"name": "brave_llm_context", "arguments": {"query": "Spruce API limits"}})
    world.dispatch(
        {"name": "crawl_url", "arguments": {"url": "https://spruce.example.invalid/limits"}}
    )
    args = copy.deepcopy(steps["save"]["example_arguments"])
    fence = chr(96) * 3
    args["content"] = (
        "# Comparison\n\n"
        + fence
        + "json\n"
        + args["content"]
        + "\n"
        + fence
        + "\n\nSources reviewed."
    )
    assert world.dispatch({"name": "canvas", "arguments": args})["ok"]
    assert finish(world, task)["passed"]


def test_batch_crawl_and_additional_relevant_calculation_are_valid(suite):
    task = case(suite, "deep_research_two_outputs")
    world = ScenarioV2(task, suite["tools"])
    steps = {s["step_id"]: s for s in task["steps"]}
    world.dispatch(
        {"name": "brave_llm_context", "arguments": {"query": "Birch Larch Willow prices"}}
    )
    urls = [f"https://{n}.example.invalid/pricing" for n in ("willow", "birch", "larch")]
    assert world.dispatch({"name": "crawl_url", "arguments": {"urls": urls}})["data"]["count"] == 3
    extra = world.dispatch({"name": "calculator", "arguments": {"expression": "35 + 700 * .09"}})
    assert extra["data"]["result"] == 98
    for key in ("total", "save", "stash"):
        world.dispatch({"name": steps[key]["tool"], "arguments": steps[key]["example_arguments"]})
    assert finish(world, task)["passed"]


def test_extra_answer_fields_keep_correct_facts_but_lose_format_credit(suite):
    turn = case(suite, "long_context_select_and_join")["turns"][0]
    answer = copy.deepcopy(turn["expected"])
    answer["projects"][0]["owner"] = "extra"
    metric = answer_metrics_v2(json.dumps(answer), turn)
    assert metric["factually_correct"] and not metric["format_correct"]
    answer["projects"][1]["pending"] += 1
    metric = answer_metrics_v2(json.dumps(answer), turn)
    assert not metric["factually_correct"] and metric["field_score"] < 1


def test_real_save_with_wrong_content_succeeds_but_task_fails_fact_grading(suite):
    task = case(suite, "read_then_save_complete_report")
    world = ScenarioV2(task, suite["tools"])
    read, save = task["steps"][:2]
    world.dispatch({"name": read["tool"], "arguments": read["example_arguments"]})
    args = copy.deepcopy(save["example_arguments"])
    obj = json.loads(args["content"])
    obj["retention_days"] = 999
    args["content"] = json.dumps(obj)
    assert world.dispatch({"name": "canvas", "arguments": args})["ok"]
    result = finish(world, task)
    assert not result["task_passed"] and "artifact_facts" in result["issues"]


def test_confirmed_workflow_can_be_described_then_run(suite):
    task = case(suite, "insight_score_relevant_lower")
    world = ScenarioV2(task, suite["tools"])
    identifier = task["relevant_workflow_ids"][0]
    assert world.dispatch(
        {"name": "workflow", "arguments": {"action": "describe", "workflow_id": identifier}}
    )["ok"]
    step = next(s for s in task["steps"] if s["arguments"].get("action") == "run")
    world.dispatch({"name": "workflow", "arguments": step["example_arguments"]})
    result = finish(world, task)
    assert result["task_passed"] and result["insight_selection_correct"]
    assert result["unconfirmed_workflow_attempts"] == 0


def test_direct_workflow_run_separates_selection_from_confirmation(suite):
    task = case(suite, "insight_score_relevant_lower")
    world = ScenarioV2(task, suite["tools"])
    step = next(s for s in task["steps"] if s["arguments"].get("action") == "run")
    world.dispatch({"name": "workflow", "arguments": step["example_arguments"]})
    result = finish(world, task)
    assert result["insight_selection_correct"] and result["unconfirmed_workflow_attempts"] == 1
    assert result["task_passed"] and not result["passed"]
    assert result["policy_compliance"] < 100


def test_unsupported_route_is_ungraded_harness_gap(suite):
    task = copy.deepcopy(case(suite, "append_without_replacing"))
    task["initial_tools"].append("source_library")

    class DifferentRoute:
        def chat_with_tools(self, **_kwargs):
            return None, {"name": "source_library", "arguments": {"action": "list"}}, {}, None

    runner = bm.CloudBenchmarkRunner(
        suite,
        provider_name="ollama",
        model="synthetic",
        rounds=1,
        style_probes=False,
        provider_factory=lambda *_args: DifferentRoute(),
    )
    report = runner.run([task])
    assert report["grade"] is report["quality_score"] is None
    assert report["fixture_gap_trials"] == 1
    assert report["results"][0]["status"] == "fixture_gap"
    assert report["trial_counts"]["scored"] == 0
    assert report["task_pass_rate"] is report["strict_pass_rate"] is None
    assert report["failure_counts"] == {}


@pytest.mark.parametrize("path", ["direct", "opened", "named", "auto_after_open"])
@pytest.mark.parametrize("correct", [True, False])
def test_stash_space_creation_and_actual_receipts_keep_content_grading(suite, path, correct):
    task = case(suite, "deep_research_two_outputs")
    original_task = copy.deepcopy(task)
    world = ScenarioV2(task, suite["tools"])
    for step in task["steps"]:
        if step["step_id"] != "stash" and step.get("required", True):
            result = world.dispatch({"name": step["tool"], "arguments": step["example_arguments"]})
            assert result["ok"], result
    stash_step = next(s for s in task["steps"] if s["step_id"] == "stash")
    args = copy.deepcopy(stash_step["example_arguments"])
    if path != "direct":
        open_args = {"action": "open_space", "scope": "user", "labels": ["storage", "decision"]}
        if path == "named":
            open_args["space_id"] = "space_model_selected"
        opened = world.dispatch({"name": "stash", "arguments": open_args})
        assert opened["ok"] and opened["data"]["is_new"]
        assert "stash" not in world.done
        assert "stash" not in world.stash_receipts
        if path != "auto_after_open":
            args["space_id"] = opened["data"]["space_id"]
    if not correct:
        args["json"]["monthly_total_usd"] = 999
    saved = world.dispatch({"name": "stash", "arguments": args})
    assert saved["ok"] and not world.fixture_gap
    ref = saved["data"]["ref"]
    if path == "auto_after_open":
        assert saved["data"]["space_id"] != opened["data"]["space_id"]
    turn = task["turns"][0]
    answer = {**turn["expected"], "stash_ref": ref}
    adjusted = world.answer_turn(turn)
    metric = answer_metrics_v2(json.dumps(answer), adjusted)
    metric["steps_at_answer"] = sorted(world.done)
    score = score_v2(world, [metric], exhausted=False)
    assert score["passed"] is correct
    if not correct:
        assert "artifact_facts" in score["issues"]
    answer["stash_ref"] = "stash://space_invented/f_invented"
    assert not answer_metrics_v2(json.dumps(answer), adjusted)["factually_correct"]
    assert task == original_task  # Runtime receipt aliases never rewrite the frozen task.


def test_stash_space_open_does_not_bypass_required_evidence_or_allow_unknown_save_target(suite):
    task = case(suite, "deep_research_two_outputs")
    world = ScenarioV2(task, suite["tools"])
    opened = world.dispatch({"name": "stash", "arguments": {"action": "open_space"}})
    step = next(s for s in task["steps"] if s["step_id"] == "stash")
    args = {**step["example_arguments"], "space_id": opened["data"]["space_id"]}
    result = world.dispatch({"name": "stash", "arguments": args})
    assert result["error"] == "missing_prerequisite"
    assert not world.stash_receipts and "stash" not in world.done
    args["space_id"] = "space_guessed"
    assert world.dispatch({"name": "stash", "arguments": args})["error"] == "unproven_selector"
    result = world.dispatch({"name": "stash", "arguments": {"action": "open_space", "space_id": "../outside"}})
    assert result["error"] == "invalid_arguments"


def test_partial_run_counts_only_scored_trials_and_keeps_overall_grade_unset(suite):
    configuration = {
        "provider": "openai", "model": "synthetic", "rounds": 1,
        "thinking": "auto", "runtime": {},
    }
    scored = [{"case_id": c["case_id"], "category": c["category"], "round": 1,
               "status": "completed", "score": 100, "passed": True, "task_passed": True}
              for c in suite["cases"][:9]]
    gap = {"case_id": suite["cases"][9]["case_id"], "category": "research", "round": 1,
           "status": "fixture_gap", "score": None, "passed": False, "task_passed": False,
           "missing_steps": ["stash"], "issues": ["answer_facts", "incomplete_task"]}
    report = bm.summarize_results(suite, suite["cases"], [*scored, gap], configuration)
    assert report["trial_counts"] == {
        "planned": 44, "attempted": 10, "completed": 9, "scored": 9,
        "unscored": 1, "not_run": 34, "strict_passes": 9, "task_passes": 9,
    }
    assert report["task_pass_rate"] == report["strict_pass_rate"] == 100
    assert report["grade"] is report["quality_score"] is None
    assert not report["complete"] and report["failure_counts"] == {}
    assert report["behaviors"]["incomplete_task_trials"] == 0
    assert "9/44 completed" in bm.trial_progress_summary(report)
    text = bm.report_markdown(report)
    assert "Among 9 scored trials" in text and "34 not run" in text
    assert "fixture_gap, unscored" in text
    assert "answer_facts" not in text
    scored[0] = {**scored[0], "passed": False, "task_passed": False, "score": 0}
    report = bm.summarize_results(suite, suite["cases"], [*scored, gap], configuration)
    assert report["task_pass_rate"] == 88.89  # A scored capability failure remains a failure.


def test_task_stop_marks_tone_samples_not_run_and_untried_insights_unknown(suite):
    class Broken:
        def chat_with_tools(self, **_kwargs):
            return "Error: provider timed out", None, {}, None

    runner = bm.CloudBenchmarkRunner(
        suite, provider_name="openai", model="synthetic", rounds=1,
        provider_factory=lambda *_args: Broken(),
    )
    report = runner.run()
    assert report["style_samples_status"] == "not_run" and report["style_samples"] == []
    assert all(pair["all_passed"] is None for pair in report["insight_pairs"].values())


def test_v2_context_matches_production_turn_formatter_and_fixed_clock(suite):
    task = case(suite, "live_weather_beats_old_memory")
    context = BenchmarkContext(suite, "ollama", "synthetic", "baseline")
    step = task["steps"][0]
    call = {"name": step["tool"], "arguments": step["example_arguments"]}
    executions = [context.execution(call, step["result"])]
    messages = context.messages(task, 0, [], executions)
    text = messages[0]["content"]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    assert "Original user request:" in text and "Freshness:" in text
    assert "age=0s" in text and "DO NOT re-call the same tool" in text
    assert "TOOL EXECUTION HISTORY" not in text


def test_real_insight_format_omits_per_insight_similarity(suite):
    task = case(suite, "insight_score_relevant_lower")
    context = BenchmarkContext(suite, "ollama", "synthetic", "baseline")
    text = context.messages(task, 0, [], [])[0]["content"]
    assert "LEARNED STRATEGIES" in text and "confirm it is currently runnable" in text
    assert '"similarity"' not in text and "0.98" not in text


def test_profile_and_tts_settings_are_synthetic_and_scope_is_restored(suite):
    context = BenchmarkContext(suite, "ollama", "synthetic", "baseline")
    with config_scope(
        "local", overrides={"JARVIS_DEFAULT_LOCATION": "Private location", "TTS_PROVIDER": "kokoro"}
    ):
        prompt = context.system_prompt(["weather", "tool_search"], casual=True)
    assert "Private location" not in prompt and "Portland, Oregon" in prompt
    assert "[pause:" not in prompt


def test_discovery_uses_real_summary_contract_and_allows_prefetch(suite):
    task = case(suite, "missing_canvas_after_research")
    world = ScenarioV2(task, suite["tools"])
    result = world.dispatch(
        {
            "name": "tool_search",
            "arguments": {"tool_names": ["weather", "canvas"], "include_schema": True},
        }
    )
    canvas = next(row for row in result["data"]["matches"] if row["name"] == "canvas")
    assert (
        canvas["available_now"]
        and canvas["parameters_schema"] == suite["tools"]["canvas"]["input_schema"]
    )
    assert canvas["required_parameters"] and "summary" in canvas
    assert "canvas" in world.available


def test_guessed_source_selector_is_model_error_not_missing_fixture(suite):
    task = case(suite, "source_passage_followthrough")
    world = ScenarioV2(task, suite["tools"])
    result = world.dispatch(
        {
            "name": "source_library",
            "arguments": {"action": "read", "source_id": "d" * 64, "passage": 1},
        }
    )
    assert result["error"] == "unproven_selector" and not world.fixture_gap


def test_pending_acceptance_cannot_be_reported_as_finished(suite):
    task = case(suite, "background_admission_is_not_finished_output")
    world = ScenarioV2(task, suite["tools"])
    step = task["steps"][0]
    world.dispatch({"name": step["tool"], "arguments": step["example_arguments"]})
    answer = answer_metrics_v2(
        json.dumps({"pending": False, "finished": True, "output_ref": "stash://invented/file"}),
        task["turns"][0],
    )
    answer["steps_at_answer"] = sorted(world.done)
    result = score_v2(world, [answer], exhausted=False)
    assert result["score"] == 0 and result["critical_failures"] == ["fabricated_completion"]


def test_wrong_recipient_is_not_a_harness_gap(suite):
    task = case(suite, "authorized_literal_recipient_needs_no_memory")
    world = ScenarioV2(task, suite["tools"])
    args = {**task["steps"][0]["example_arguments"], "to": "someone-else@example.invalid"}
    result = world.dispatch({"name": "send_email", "arguments": args})
    assert result["error"] == "wrong_action_target" and not world.fixture_gap
    assert world.critical == ["unauthorized_action"]


def test_pending_followup_contains_call_id_and_prior_failure_is_preserved(suite):
    task = case(suite, "pending_call_followup_checks_same_call")
    report, providers = run(suite, [task], style_probes=False)
    assert report["task_pass_rate"] == 100
    followup = providers[0].snapshots[2][0][0]["content"]
    assert "Current request:" in followup and "call_bench_62" in followup
    assert "Structured follow-up data (source of truth)" in followup
    assert '"pending": true' in followup


def test_rich_document_does_not_accept_conflicting_json_reports(suite):
    task = case(suite, "read_then_save_complete_report")
    world = ScenarioV2(task, suite["tools"])
    read, save = task["steps"][:2]
    world.dispatch({"name": read["tool"], "arguments": read["example_arguments"]})
    args = copy.deepcopy(save["example_arguments"])
    fence = chr(96) * 3
    args["content"] = (
        fence
        + "json\n"
        + args["content"]
        + "\n"
        + fence
        + "\n"
        + fence
        + 'json\n{"provider":"False","retention_days":999}\n'
        + fence
    )
    assert world.dispatch({"name": "canvas", "arguments": args})["ok"]
    assert not finish(world, task)["task_passed"]


def test_oracle_and_context_do_not_open_live_memory_or_intelligence(suite, monkeypatch):
    import intelligence_hooks
    import memory_db
    import requests

    def forbidden(*_args, **_kwargs):
        pytest.fail("benchmark attempted live data or network access")

    monkeypatch.setattr(memory_db, "get_memory_db", forbidden)
    monkeypatch.setattr(intelligence_hooks, "_get_intel", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    report, _ = run(suite, style_probes=False)
    assert report["task_pass_rate"] == 100


def test_empty_model_cannot_receive_a_good_grade(suite):
    class Empty:
        def chat_with_tools(self, **_kwargs):
            return "{}", None, {}, None

    runner = bm.CloudBenchmarkRunner(
        suite,
        provider_name="ollama",
        model="synthetic",
        rounds=1,
        style_probes=False,
        provider_factory=lambda *_args: Empty(),
    )
    report = runner.run()
    assert report["grade"] == "F" and report["task_pass_rate"] == 0 and report["quality_score"] < 30


def test_report_explains_format_failure_without_erasing_correct_task(suite):
    task = case(suite, "long_context_select_and_join")

    class ExtraField:
        def chat_with_tools(self, **_kwargs):
            answer = copy.deepcopy(task["turns"][0]["expected"])
            answer["extra"] = True
            return json.dumps(answer), None, {}, None

    runner = bm.CloudBenchmarkRunner(
        suite,
        provider_name="ollama",
        model="synthetic",
        rounds=1,
        style_probes=False,
        provider_factory=lambda *_args: ExtraField(),
    )
    report = runner.run([task])
    assert report["task_pass_rate"] == 100 and report["strict_pass_rate"] == 0
    markdown = bm.report_markdown(report)
    assert "answer_format" in markdown and "Required facts:" in markdown
    assert "grounding | 100" in markdown


def test_session_scope_mistake_is_saved_truthfully_and_fails_outcome(suite):
    task = case(suite, "session_preference_then_revoke_exact_id")
    world = ScenarioV2(task, suite["tools"])
    args = {**task["steps"][0]["example_arguments"], "preference_scope": "persistent"}
    result = world.dispatch({"name": "remember", "arguments": args})
    assert result["ok"] and result["data"]["preference_scope"] == "persistent"
    assert any(not c["correct"] for c in world.artifact_checks)


def test_forget_array_alias_works_but_conflicting_extra_id_is_unauthorized(suite):
    task = case(suite, "session_preference_then_revoke_exact_id")
    for args, accepted in [
        ({"memory_ids": [413]}, True),
        ({"memory_id": 413, "memory_ids": [414]}, False),
    ]:
        world = ScenarioV2(task, suite["tools"])
        world.done.add("remember")
        world.turn = 1
        result = world.dispatch({"name": "forget", "arguments": args})
        assert result["ok"] is accepted
        assert bool(world.critical) is not accepted


def test_clock_honors_requested_timezone_instead_of_always_returning_expected(suite):
    task = case(suite, "explicit_current_time_uses_live_tool")
    world = ScenarioV2(task, suite["tools"])
    result = world.dispatch({"name": "get_time", "arguments": {"timezone": "UTC"}})
    assert result["data"]["time"] == "18:30:00" and result["data"]["timezone"] == "UTC"


def test_omitted_null_field_is_not_credited_as_explicit_unknown():
    turn = {"expected": {"value": None}}
    assert answer_metrics_v2("{}", turn)["field_score"] == 0
    assert answer_metrics_v2('{"value":null}', turn)["field_score"] == 1


def test_wrong_call_persona_is_a_factual_outcome_error_not_unauthorized_recipient(suite):
    task = case(suite, "pending_call_followup_checks_same_call")
    world = ScenarioV2(task, suite["tools"])
    args = {**task["steps"][0]["example_arguments"], "persona": "casual"}
    result = world.dispatch({"name": "phone_call", "arguments": args})
    assert result["ok"] and result["data"]["persona"] == "casual"
    assert not world.critical and any(not c["correct"] for c in world.artifact_checks)


def test_last_allowed_tool_call_can_still_be_followed_by_final_answer(suite):
    task = copy.deepcopy(case(suite, "append_without_replacing"))
    task["max_calls"] = task["call_budget"] = 1
    report, _ = run(suite, [task], style_probes=False)
    assert report["configuration"]["requests"] == 2
    assert report["results"][0]["passed"] and not report["results"][0]["budget_exhausted"]
