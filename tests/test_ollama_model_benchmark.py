#!/usr/bin/env python3
"""Unit tests for the non-destructive Ollama model benchmark."""

import hashlib
import json
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import ollama_benchmark_fixtures as benchmark_fixtures  # noqa: E402
from ollama_benchmark_fixtures import (  # noqa: E402
    PRODUCTION_SHORTLIST,
    build_routing_system_prompt,
    is_loopback_url,
    load_production_shortlist,
    load_router_prompt,
    load_tool_rag_replay_fixture,
)
from ollama_model_benchmark import (  # noqa: E402
    FUNCTIONAL_CASES,
    TOOL_BY_NAME,
    BenchmarkError,
    BenchmarkRunner,
    CpuOffloadDetected,
    FunctionalCase,
    OllamaBenchmarkClient,
    ProviderTransportError,
    RawChatResult,
    calculate_grade,
    canonical_model_name,
    evaluate_functional_case,
    evaluate_structured_output,
    extract_native_context,
    find_model_entry,
    inspect_gpu_residency,
    is_provider_transport_error,
    is_retryable_provider_error,
    make_context_prompt,
    mentions_celsius_temperature,
    performance_score,
    resolve_context_candidates,
    same_ollama_host,
)


class _ResidencyClient:
    base_url = "http://benchmark.invalid"
    model = "gemma4"
    timeout = 1.0
    keep_alive = "5m"
    max_retries = 0
    retry_backoff_seconds = 0.0

    def __init__(self, running_models):
        self.running_models = running_models
        self.retry_events = []
        self.sleep = lambda _delay: None

    def get_running_models(self):
        return self.running_models

    def retry_delay(self, _attempt):
        return 0.0

    def record_retry(self, **event):
        self.retry_events.append(event)


def test_canonical_model_name_adds_latest_only_when_tag_is_absent():
    assert canonical_model_name("Gemma4") == "gemma4:latest"
    assert canonical_model_name("orcarouter/model:q3_K_S") == "orcarouter/model:q3_k_s"
    assert canonical_model_name("hf.co/owner/repo") == "hf.co/owner/repo:latest"


def test_find_model_entry_accepts_name_or_model_field():
    entries = [
        {"name": "gemma4:latest", "size": 10},
        {"model": "ornith-1.5:9b", "size": 20},
    ]

    assert find_model_entry(entries, "gemma4")["size"] == 10
    assert find_model_entry(entries, "ORNITH-1.5:9B")["size"] == 20
    assert find_model_entry(entries, "missing") is None


def test_extract_native_context_uses_largest_declared_context():
    show = {
        "model_info": {
            "gemma3.context_length": 131072,
            "vision.context_length": "32768",
            "unrelated": 999999,
        }
    }

    assert extract_native_context(show) == 131072
    assert extract_native_context({"model_info": {}}) is None


def test_auto_contexts_are_capped_by_model_and_operator_limit():
    assert resolve_context_candidates("auto", native_context=131072, max_context=65536) == [
        8192,
        16384,
        32768,
        65536,
    ]
    assert resolve_context_candidates(
        "32768,8192,32768", native_context=16384, max_context=65536
    ) == [8192]


def test_context_resolution_has_small_model_fallback():
    assert resolve_context_candidates("auto", native_context=4096, max_context=65536) == [4096]
    with pytest.raises(ValueError, match="greater than zero"):
        resolve_context_candidates("auto", native_context=None, max_context=0)


def test_gpu_residency_passes_fully_resident_dense_model():
    result = inspect_gpu_residency(
        [{"name": "gemma4:latest", "size": 10_000, "size_vram": 9_800}],
        "gemma4",
        artifact_size=10_000,
    )

    assert result["ok"] is True
    assert result["full_gpu"] is True
    assert result["vram_residency_ratio"] == 0.98


def test_gpu_residency_avoids_moe_mmap_double_count_false_positive():
    result = inspect_gpu_residency(
        [{"name": "gemma4:latest", "size": 20_000, "size_vram": 9_800}],
        "gemma4",
        artifact_size=10_000,
    )

    assert result["full_gpu"] is True
    assert result["residency_method"] == "mmap_accounting_exception"
    assert result["confidence"] == "medium"


def test_gpu_residency_detects_partial_offload_and_missing_runner():
    partial = inspect_gpu_residency(
        [{"name": "gemma4:latest", "size": 10_000, "size_vram": 7_000}],
        "gemma4",
        artifact_size=10_000,
    )
    missing = inspect_gpu_residency([], "gemma4", artifact_size=10_000)

    assert partial["ok"] is True
    assert partial["full_gpu"] is False
    assert missing["ok"] is False
    assert missing["full_gpu"] is False


def test_runner_aborts_on_partial_offload_but_not_missing_ps_as_cpu():
    partial_runner = BenchmarkRunner(
        _ResidencyClient([{"name": "gemma4:latest", "size": 10_000, "size_vram": 7_000}]),
        contexts=[8192],
    )
    partial_runner.artifact_size = 10_000
    missing_runner = BenchmarkRunner(_ResidencyClient([]), contexts=[8192])
    missing_runner.artifact_size = 10_000

    with pytest.raises(CpuOffloadDetected):
        partial_runner._residency_check("unit", requested_context=8192)
    with pytest.raises(BenchmarkError, match="could not verify"):
        missing_runner._residency_check("unit", requested_context=8192)


def test_runner_stops_if_another_model_appears_mid_benchmark():
    runner = BenchmarkRunner(
        _ResidencyClient(
            [
                {"name": "gemma4:latest", "size": 10_000, "size_vram": 10_000},
                {"name": "embeddinggemma:latest", "size": 1_000, "size_vram": 1_000},
            ]
        ),
        contexts=[8192],
    )
    runner.artifact_size = 10_000

    with pytest.raises(BenchmarkError, match="another model became loaded"):
        runner._residency_check("unit", requested_context=8192)


def test_functional_tool_grading_accepts_unit_aliases_but_rejects_extra_keys():
    case = next(item for item in FUNCTIONAL_CASES if item.case_id == "tool_conversion")
    valid = {
        "name": "calculator",
        "arguments": {"expression": "10 kilometers to miles"},
    }
    invalid = {
        "name": "calculator",
        "arguments": {
            "expression": "10 kilometers to miles",
            "invented_flag": True,
        },
    }

    assert evaluate_functional_case(case, text=None, tool_call=valid)[0] is True
    assert evaluate_functional_case(case, text=None, tool_call=invalid)[0] is False


def test_functional_grading_rejects_tool_call_for_direct_qa():
    case = FunctionalCase(
        "direct",
        "tool_routing",
        "What is 2 + 2?",
        exact_text="4",
    )

    assert evaluate_functional_case(case, text="4", tool_call=None)[0] is True
    assert (
        evaluate_functional_case(
            case,
            text=None,
            tool_call={"name": "brave_llm_context", "arguments": {"query": "2+2"}},
        )[0]
        is False
    )


def test_structured_output_requires_bare_exact_typed_json():
    schema = {
        "type": "object",
        "properties": {"ready": {"type": "boolean"}},
        "required": ["ready"],
        "additionalProperties": False,
    }

    assert evaluate_structured_output('{"ready":true}', schema, {"ready": True})[0] is True
    assert evaluate_structured_output('Result: {"ready":true}', schema, {"ready": True})[0] is False
    assert evaluate_structured_output('{"ready":"true"}', schema, {"ready": True})[0] is False


def test_context_prompt_is_deterministic_large_and_has_ordered_needles():
    prompt, first, second = make_context_prompt(8192)
    repeated = make_context_prompt(8192)

    assert repeated == (prompt, first, second)
    assert len(prompt) >= 8192 * 2
    assert prompt.index(first) < prompt.index(second)
    assert "no user data" in prompt
    assert prompt.count(" data") >= int(8192 * 0.45)


def test_grade_renormalizes_when_a_category_was_not_exercised():
    result = calculate_grade(
        {
            "tool_routing": 100,
            "structured_output": 100,
            "instruction_qa": None,
            "long_context": None,
            "performance": None,
        }
    )

    assert result["score"] == 100
    assert result["letter"] == "A"


def test_production_shortlist_loads_tracked_skill_schemas():
    tools = load_production_shortlist()
    assert tuple(tools) == PRODUCTION_SHORTLIST
    assert set(TOOL_BY_NAME) == set(PRODUCTION_SHORTLIST)
    assert "url" in tools["crawl_url"]["input_schema"]["properties"]
    assert "query" in tools["brave_llm_context"]["input_schema"]["properties"]
    weather = next(item for item in FUNCTIONAL_CASES if item.case_id == "tool_weather")
    assert weather.expected_tool == "weather"


def test_router_v4_prompt_includes_gemma_overlay():
    version, prompt = load_router_prompt("v4")
    assembled = build_routing_system_prompt("gemma4", version=version)
    assert version == "v4"
    assert "You are Jarvis." in prompt
    assert assembled["override_enabled"] is True
    assert "exact tool name" in assembled["prompt"].lower()
    assert len(assembled["base_prompt_sha256"]) == 64
    assert len(assembled["overlay_sha256"]) == 64
    assert len(assembled["prompt_sha256"]) == 64


def test_tool_rag_replay_fixture_is_redacted_and_content_addressed():
    fixture = load_tool_rag_replay_fixture()

    assert fixture["schema_version"] == 2
    assert fixture["fixture_id"] == "jarvis-ollama-tool-rag-replay-v2"
    assert fixture["supersedes"] == {
        "fixture_id": "jarvis-ollama-tool-rag-replay-v1",
        "fixture_sha256": "46263e12ed1656bf35e3f9739824b0ecac32d75528e0bc284b754cde0246cb73",
    }
    assert fixture["safety"]["synthetic_queries_only"] is True
    assert fixture["safety"]["live_user_text_copied"] is False
    assert [packet["family"] for packet in fixture["packets"]] == [
        "shopping_serpapi",
        "memory_reminder",
    ]
    assert sum(len(packet["cases"]) for packet in fixture["packets"]) == 8
    assert all(len(packet["schema_snapshot_sha256"]) == 64 for packet in fixture["packets"])


def test_tool_rag_replay_v1_stays_immutable_for_historical_reports():
    fixture_path = (
        benchmark_fixtures.get_project_root()
        / "config"
        / "benchmarks"
        / "ollama-tool-rag-replay-v1.json"
    )

    assert hashlib.sha256(fixture_path.read_bytes()).hexdigest() == (
        "46263e12ed1656bf35e3f9739824b0ecac32d75528e0bc284b754cde0246cb73"
    )


def test_tool_rag_replay_fixture_rejects_ambiguous_expectation_keys(tmp_path, monkeypatch):
    payload = json.loads(benchmark_fixtures.replay_fixture_path().read_text(encoding="utf-8"))
    payload["packets"][0]["cases"][0]["expected"]["response_contains"] = ["ambiguous"]
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(benchmark_fixtures, "replay_fixture_path", lambda: fixture_path)

    with pytest.raises(ValueError, match="unknown expectation keys"):
        benchmark_fixtures.load_tool_rag_replay_fixture()


def test_replay_case_grading_uses_packet_schema_not_sanity_shortlist():
    packet = load_tool_rag_replay_fixture()["packets"][0]
    payload = packet["cases"][0]
    expected = payload["expected"]
    case = FunctionalCase(
        payload["case_id"],
        "tool_routing",
        payload["query"],
        expected_tool=expected["tool_name"],
        expected_args=expected["arguments"],
        optional_args=expected["optional_arguments"],
        arg_concepts={
            key: tuple(tuple(group) for group in groups)
            for key, groups in expected["argument_concepts"].items()
        },
    )
    schemas = {tool["name"]: tool for tool in packet["tools"]}
    valid = {
        "name": "serpapi_home_depot",
        "arguments": {"query": "cordless drills", "upperbound": 150, "num_results": 5},
    }

    assert (
        evaluate_functional_case(
            case,
            text=None,
            tool_call=valid,
            tool_schemas=schemas,
        )[0]
        is True
    )
    valid_without_default = {
        "name": "serpapi_home_depot",
        "arguments": {"query": "cordless impact driver", "upperbound": 150},
    }
    wrong_optional_value = {
        "name": "serpapi_home_depot",
        "arguments": {"query": "cordless drills", "upperbound": 150, "num_results": 6},
    }
    wrong_schema_type = {
        "name": "serpapi_home_depot",
        "arguments": {"query": "cordless drills", "upperbound": "150"},
    }
    assert evaluate_functional_case(
        case, text=None, tool_call=valid_without_default, tool_schemas=schemas
    )[0]
    assert not evaluate_functional_case(
        case, text=None, tool_call=wrong_optional_value, tool_schemas=schemas
    )[0]
    assert not evaluate_functional_case(
        case, text=None, tool_call=wrong_schema_type, tool_schemas=schemas
    )[0]


def test_direct_response_concepts_accept_synonyms_but_require_every_concept():
    case = FunctionalCase(
        "direct-concepts",
        "tool_routing",
        "Explain VRAM",
        response_concepts=(("memory", "storage"), ("gpu", "graphics card")),
    )

    assert evaluate_functional_case(
        case,
        text="Dedicated storage on the graphics card.",
        tool_call=None,
    )[0]
    assert not evaluate_functional_case(
        case,
        text="Dedicated storage for rendering.",
        tool_call=None,
    )[0]


def test_celsius_continuation_accepts_word_and_degree_notation():
    assert mentions_celsius_temperature("It is 17 degrees Celsius.", 17)
    assert mentions_celsius_temperature("It is 17°C.", 17)
    assert mentions_celsius_temperature("It is 17 C.", 17)
    assert not mentions_celsius_temperature("It is 17°F.", 17)


def test_json_classification_prompt_names_the_required_key():
    from ollama_model_benchmark import STRUCTURED_CASES

    case = next(item for item in STRUCTURED_CASES if item["case_id"] == "json_classification")
    assert "key named label" in case["prompt"]


def test_loopback_urls_are_detected():
    assert is_loopback_url("http://127.0.0.1:11434") is True
    assert is_loopback_url("http://localhost:11434") is True
    assert is_loopback_url("http://gpu-one:11434") is False
    assert is_loopback_url("http://192.168.1.50:11434") is False
    assert same_ollama_host("http://gpu:11434/", "http://gpu:11434") is True


def test_provider_transport_errors_are_not_case_failures():
    assert is_provider_transport_error(
        "Error: Request timed out after 300s. The model may be overloaded.",
        None,
        None,
    )
    assert not is_provider_transport_error("4", None, {"input_tokens": 3})
    assert not is_provider_transport_error(
        "Error: missing serial",
        {"name": "weather", "arguments": {"location": "Portland"}},
        None,
    )


def test_retryable_provider_errors_are_narrowly_classified():
    assert is_retryable_provider_error("Error: Request timed out after 300s")
    assert is_retryable_provider_error("Error: 503 Service Unavailable: server busy")
    assert is_retryable_provider_error("Error: 429 Too Many Requests")
    assert not is_retryable_provider_error("Error: 400 Bad Request: invalid tool schema")


def test_exact_host_client_retries_connection_error_without_failing_over():
    class _Response:
        status_code = 200
        headers = {}

        def json(self):
            return {"version": "0.32.15"}

        def raise_for_status(self):
            return None

    class _Session:
        def __init__(self):
            self.urls = []

        def request(self, _method, url, **_kwargs):
            self.urls.append(url)
            if len(self.urls) == 1:
                raise requests.ConnectionError("connection reset")
            return _Response()

    session = _Session()
    delays = []
    client = OllamaBenchmarkClient(
        "http://gpu-one:11434",
        "gemma4",
        max_retries=1,
        retry_backoff_seconds=0.25,
        session=session,
        sleep=delays.append,
    )

    assert client.get_version() == "0.32.15"
    assert session.urls == [
        "http://gpu-one:11434/api/version",
        "http://gpu-one:11434/api/version",
    ]
    assert delays == [0.25]
    assert client.retry_events[0]["next_attempt"] == 2


def test_exact_host_client_preserves_nested_ollama_http_error_detail():
    class _Response:
        status_code = 400
        headers = {}
        text = ""

        def json(self):
            return {
                "error": (
                    '{"error":{"code":400,"message":"request (8406 tokens) exceeds '
                    'the available context size (8192 tokens)"}}'
                )
            }

    class _Session:
        def request(self, *_args, **_kwargs):
            return _Response()

    client = OllamaBenchmarkClient(
        "http://gpu-one:11434",
        "ornith-1.5:9b",
        max_retries=0,
        session=_Session(),
    )

    with pytest.raises(requests.HTTPError, match=r"8406 tokens.*8192 tokens"):
        client.chat(
            [{"role": "user", "content": "synthetic"}],
            context_window=8192,
            max_tokens=1,
        )


def test_provider_transient_failure_retries_then_grades_success():
    class _Provider:
        base_url = "http://benchmark.invalid"

        def __init__(self):
            self.calls = 0

        def chat_with_tools(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "Error: 503 Service Unavailable: server busy", None, None, None
            return (
                None,
                {"name": "weather", "arguments": {"location": "Portland, Oregon"}},
                {"input_tokens": 10, "output_tokens": 5},
                None,
            )

    client = _ResidencyClient([{"name": "gemma4:latest", "size": 10_000, "size_vram": 10_000}])
    client.max_retries = 1
    runner = BenchmarkRunner(client, contexts=[8192])
    runner.artifact_size = 10_000
    runner._provider = _Provider()
    runner._routing_prompt = "You are Jarvis."

    result = runner._run_functional_case(FUNCTIONAL_CASES[0], 1)

    assert result["passed"] is True
    assert runner._provider.calls == 2
    assert len(client.retry_events) == 1


def test_runner_aborts_on_provider_timeout_instead_of_failing_the_case():
    class _Provider:
        base_url = "http://benchmark.invalid"

        def chat_with_tools(self, *args, **kwargs):
            return (
                "Error: Request timed out after 300s. The model may be overloaded.",
                None,
                None,
                None,
            )

    runner = BenchmarkRunner(
        _ResidencyClient([{"name": "gemma4:latest", "size": 10_000, "size_vram": 10_000}]),
        contexts=[8192],
    )
    runner.artifact_size = 10_000
    runner._provider = _Provider()
    runner._routing_prompt = "You are Jarvis."

    with pytest.raises(ProviderTransportError, match="timed out"):
        runner._run_functional_case(FUNCTIONAL_CASES[0], 1)


def test_dry_run_preflight_reports_other_models_without_refusing_busy_host():
    class _Client(_ResidencyClient):
        def get_version(self):
            return "0.32.15"

        def get_tags(self):
            return [{"name": "gemma4:latest", "size": 10_000}]

        def get_show(self):
            return {"capabilities": ["completion"]}

    client = _Client([{"name": "embeddinggemma:latest", "size": 1_000, "size_vram": 1_000}])
    runner = BenchmarkRunner(client, contexts=[8192, 16384], dry_run=True)

    report = runner.run()

    assert report["status"] == "dry_run"
    assert report["configuration"]["contexts"] == [8192, 16384]
    assert report["safety"]["other_models_loaded"] == ["embeddinggemma:latest"]


def test_error_report_never_promotes_partial_results_to_top_level_grade():
    runner = BenchmarkRunner(_ResidencyClient([]), contexts=[8192])
    report = {
        "status": "error",
        "functional_results": [
            {
                "category": "tool_routing",
                "passed": True,
                "wall_ms": 100.0,
            }
        ],
        "context_probes": [],
        "performance": {},
        "transport": {"retry_events": []},
        "warnings": [],
    }

    runner._finalize_report(report)

    assert report["grade"] == {
        "letter": "N/A (incomplete)",
        "score": None,
        "weights": {},
    }
    assert report["partial_grade"]["score"] is not None
    assert report["jarvis_local_fit"] == "inconclusive"


def test_keyboard_interrupt_writes_an_inconclusive_interrupted_report():
    class _Client(_ResidencyClient):
        def get_version(self):
            raise KeyboardInterrupt

    runner = BenchmarkRunner(_Client([]), contexts=[8192])

    report = runner.run()

    assert report["status"] == "interrupted"
    assert report["grade"]["letter"] == "N/A (incomplete)"
    assert report["jarvis_local_fit"] == "inconclusive"
    assert report["progress"]["completed_steps"] == 0


def test_keyboard_interrupt_before_residency_check_skips_unsafe_release():
    class _Client(_ResidencyClient):
        def __init__(self):
            super().__init__([])
            self.unloaded = False

        def get_version(self):
            return "0.32.15"

        def get_tags(self):
            return [{"name": "gemma4:latest", "size": 10_000}]

        def get_show(self):
            return {"capabilities": ["completion"]}

        def chat(self, *args, **kwargs):
            raise KeyboardInterrupt

        def unload(self):
            self.unloaded = True

    client = _Client()
    runner = BenchmarkRunner(
        client,
        contexts=[8192],
        release_owned_runner=True,
    )

    report = runner.run()

    assert report["status"] == "interrupted"
    assert client.unloaded is False
    assert report["safety"]["released_owned_runner"] is False
    assert any("no post-inference /api/ps" in warning for warning in report["warnings"])


def test_performance_score_distinguishes_measured_5060ti_and_4090_profiles():
    rtx_5060ti = performance_score(
        89.39,
        820.33,
        prefill_tps=4229.59,
        p95_latency_ms=1925.78,
    )
    rtx_4090 = performance_score(
        120.95,
        561.39,
        prefill_tps=11198.38,
        p95_latency_ms=1222.98,
    )

    assert rtx_5060ti == 77.0
    assert rtx_4090 == 96.0
    assert rtx_4090 > rtx_5060ti


def test_raw_chat_timing_matches_ollama_verbose_formulas():
    result = RawChatResult(
        content="ok",
        message={"content": "ok"},
        raw={
            "total_duration": 5_654_073_000,
            "load_duration": 3_991_530_000,
            "prompt_eval_count": 4099,
            "prompt_eval_duration": 916_619_000,
            "eval_count": 64,
            "eval_duration": 722_688_000,
            "done_reason": "length",
        },
        wall_ms=5659.111,
    )

    timing = result.timing()
    assert timing["prompt_tokens_per_second"] == 4471.87
    assert timing["eval_tokens_per_second"] == 88.56
    assert timing["prompt_eval_duration_ms"] == 916.619
    assert timing["done_reason"] == "length"


def test_release_unloads_only_when_this_run_loaded_the_target():
    class _Client(_ResidencyClient):
        def __init__(self):
            super().__init__(
                [
                    {
                        "name": "gemma4:latest",
                        "size": 10_000,
                        "size_vram": 10_000,
                        "expires_at": "2026-08-19T19:00:00Z",
                    }
                ]
            )
            self.unloaded = False

        def unload(self):
            self.unloaded = True

    owned = BenchmarkRunner(_Client(), contexts=[8192], release_owned_runner=True)
    owned._loaded_target = True
    owned._target_was_loaded = False
    owned.residency_checks.append({"expires_at": "2026-08-19T19:00:00Z"})
    report = {"safety": {}, "warnings": []}
    owned._release_owned_runner_if_needed(report)
    assert owned.client.unloaded is True
    assert report["safety"]["released_owned_runner"] is True
    assert report["safety"]["runner_cleanup"]["action"] == "released"

    preexisting = BenchmarkRunner(_Client(), contexts=[8192], release_owned_runner=True)
    preexisting._loaded_target = True
    preexisting._target_was_loaded = True
    preexisting_report = {"safety": {}, "warnings": []}
    preexisting._release_owned_runner_if_needed(preexisting_report)
    assert preexisting.client.unloaded is False
    assert preexisting_report["safety"]["released_owned_runner"] is False
    assert (
        preexisting_report["safety"]["runner_cleanup"]["action"] == "preserved_preexisting_runner"
    )


def test_release_skips_runner_with_later_shared_activity():
    class _Client(_ResidencyClient):
        def __init__(self):
            super().__init__(
                [
                    {
                        "name": "gemma4:latest",
                        "size": 10_000,
                        "size_vram": 10_000,
                        "expires_at": "2026-08-19T19:05:00Z",
                    }
                ]
            )
            self.unloaded = False

        def unload(self):
            self.unloaded = True

    client = _Client()
    runner = BenchmarkRunner(client, contexts=[8192], release_owned_runner=True)
    runner._loaded_target = True
    runner.residency_checks.append({"expires_at": "2026-08-19T19:00:00Z"})
    report = {"safety": {}, "warnings": []}

    runner._release_owned_runner_if_needed(report)

    assert client.unloaded is False
    assert report["safety"]["released_owned_runner"] is False
    assert any("another client may be using it" in warning for warning in report["warnings"])


def test_target_appearing_after_preflight_is_treated_as_preexisting_for_release():
    client = _ResidencyClient(
        [
            {
                "name": "gemma4:latest",
                "size": 10_000,
                "size_vram": 10_000,
                "expires_at": "2026-08-19T19:00:00Z",
            }
        ]
    )
    runner = BenchmarkRunner(client, contexts=[8192], release_owned_runner=True)
    report = {"safety": {}, "warnings": []}

    runner._recheck_target_before_inference(report)

    assert runner._target_was_loaded is True
    assert report["safety"]["target_appeared_before_inference"] is True
