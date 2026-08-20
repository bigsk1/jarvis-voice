#!/usr/bin/env python3
"""Tests for the app-independent Ollama Model Capability Evaluation."""

import hashlib
import itertools
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import ollama_capability_evaluation as capability  # noqa: E402
from ollama_capability_evaluation import (  # noqa: E402
    CAPABILITY_CATEGORIES,
    evaluate_capability_answer,
    load_capability_fixture,
    score_capability_categories,
)
from ollama_model_benchmark import (  # noqa: E402
    BenchmarkRunner,
    OllamaBenchmarkClient,
    RawChatResult,
    calculate_combined_grade,
    render_markdown_report,
)


def _case(case_id: str) -> dict:
    fixture = load_capability_fixture()
    return next(case for case in fixture["cases"] if case["case_id"] == case_id)


def test_capability_fixture_is_progressive_content_addressed_and_app_independent():
    fixture = load_capability_fixture()

    assert fixture["fixture_id"] == "jarvis-ollama-model-capability-v2"
    assert fixture["schema_version"] == 2
    assert fixture["supersedes"]["fixture_id"] == "jarvis-ollama-model-capability-v1"
    assert len(fixture["fixture_sha256"]) == 64
    assert len(fixture["cases"]) == 32
    assert fixture["request_contract"] == {
        "system_prompt": False,
        "tools": False,
        "response_format": False,
        "temperature": 0,
        "seed": 73,
        "thinking": "explicit_cli_profile",
        "canonical_profile": "off",
    }
    assert fixture["output_budget_policy"] == {
        "retry_on_done_reason_length": True,
        "minimum_initial_tokens": 1024,
        "multiplier": 2,
        "max_tokens": 2048,
        "unresolved_truncation": "unscored",
    }
    assert fixture["qualitative_probe"]["scored"] is False
    assert all(case["grader"]["type"] != "word_count_concepts" for case in fixture["cases"])
    for category in CAPABILITY_CATEGORIES:
        difficulties = [
            case["difficulty"] for case in fixture["cases"] if case["category"] == category
        ]
        assert difficulties.count("easy") == 2
        assert difficulties.count("medium") == 3
        assert difficulties.count("hard") == 3


def test_synthetic_challenge_oracles_are_unique_and_numerically_correct():
    card_orders = [
        "".join(order)
        for order in itertools.permutations("5678")
        if order.index("6") < order.index("8")
        and abs(order.index("5") - order.index("6")) != 1
        and order.index("7") == order.index("5") + 1
        and order.index("8") < order.index("5")
    ]
    chest_answers = []
    for coin in "WXYZ":
        statement_1 = coin in "WX"
        statements = (statement_1, coin != "X", coin == "Y", statement_1)
        if sum(statements) == 3:
            chest_answers.append(coin)
    onto_functions = sum(
        len(set(outputs)) == 3 for outputs in itertools.product(range(3), repeat=4)
    )
    exclusive_multiples = sum((number % 4 == 0) ^ (number % 6 == 0) for number in range(1, 81))
    circular_not_adjacent = math.factorial(5) - 2 * math.factorial(4)
    base_rate = (0.80 * 0.02) / (0.80 * 0.02 + 0.05 * 0.98)
    harmonic_speed = 2 / (1 / 50 + 1 / 20)
    n_values = [n for n in range(1, 200) if n % 8 == 3 and n % 9 == 5]

    assert card_orders == ["6857"]
    assert chest_answers == ["W"]
    assert onto_functions == 36
    assert exclusive_multiples == 21
    assert circular_not_adjacent == 72
    assert n_values[0] == 59
    assert abs(base_rate * 100 - 24.615) < 0.01
    assert abs(harmonic_speed - 28.5714) < 0.001

    a_small, a_large = 16 / 20, 100 / 180
    b_small, b_large = 140 / 180, 4 / 10
    assert a_small > b_small and a_large > b_large
    assert (16 + 100) / (20 + 180) < (140 + 4) / (180 + 10)


def test_capability_v1_stays_immutable_for_historical_reports():
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "benchmarks"
        / "ollama-model-capability-v1.json"
    )

    assert hashlib.sha256(fixture_path.read_bytes()).hexdigest() == (
        "60359611c467c80bc35314dcae517c6eccd2f26fb857349e6edfc3368e242ba2"
    )


def test_capability_fixture_rejects_app_features(tmp_path, monkeypatch):
    payload = json.loads(capability.capability_fixture_path().read_text(encoding="utf-8"))
    payload["request_contract"]["system_prompt"] = True
    fixture_path = tmp_path / "capability.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(capability, "capability_fixture_path", lambda: fixture_path)

    with pytest.raises(ValueError, match="disable app request features"):
        capability.load_capability_fixture()


def test_alias_grader_accepts_plain_language_around_final_answer():
    score, reason, parsed = evaluate_capability_answer(
        _case("knowledge_easy_tungsten"),
        "The symbol comes from wolfram.\nFinal answer: Tungsten.",
    )

    assert score == 1
    assert "matched accepted" in reason
    assert parsed == "Tungsten."


@pytest.mark.parametrize(
    ("case_id", "answer"),
    [
        ("knowledge_medium_terminal_acceptor", r"Final answer: $\text{O}_2$"),
        ("knowledge_medium_incompleteness", "Final answer: Gödel's incompleteness theorems"),
        ("logic_medium_truth_tellers", "Final answer: Aria truthful; Bex lying"),
        ("logic_hard_schedule", "Final answer: NJLKM"),
        ("logic_hard_four_chests", "Final answer: W"),
        ("logic_hard_four_chests", "Final answer: chest W"),
    ],
)
def test_alias_grader_accepts_live_equivalent_answer_forms(case_id, answer):
    assert evaluate_capability_answer(_case(case_id), answer)[0] == 1


@pytest.mark.parametrize(
    ("case_id", "answer"),
    [
        ("math_medium_binomial", "Final answer: 3/8"),
        ("reflection_easy_die_streak", "Final answer: 1/6"),
        ("reflection_easy_die_streak", "Final answer: 16.7%"),
        ("reflection_hard_switch_chests", "Final answer: 3/4"),
        ("reflection_medium_lamp_bulb", "Final answer: $0.20"),
        ("reflection_hard_base_rate", "Final answer: 25%"),
        ("reflection_hard_base_rate", "Final answer: 0.246"),
        ("reflection_hard_base_rate", "Final answer: 16/65"),
    ],
)
def test_numeric_grader_accepts_equivalent_free_response_forms(case_id, answer):
    assert evaluate_capability_answer(_case(case_id), answer)[0] == 1


def test_concept_grader_awards_partial_credit_and_rejects_contradiction():
    case = _case("knowledge_hard_lunar_day")

    assert evaluate_capability_answer(case, "The Moon moves eastward in its orbit.")[0] == 0.5
    assert (
        evaluate_capability_answer(
            case,
            "The Moon advances in its orbit, so Earth must rotate farther to catch up.",
        )[0]
        == 1
    )
    assert (
        evaluate_capability_answer(
            case,
            "Earth rotates slower while the Moon moves eastward, so Earth rotates farther.",
        )[0]
        == 0
    )
    assert (
        evaluate_capability_answer(
            case,
            "The Moon advances in its orbit, not because Earth rotates slower, "
            "so Earth must rotate farther to catch up.",
        )[0]
        == 1
    )


def test_concept_grader_accepts_correct_live_carbon_dating_explanation():
    answer = (
        "Carbon-14 decays with a measurable rate, and after tens of millions of years, "
        "almost all of it has decayed to undetectable levels."
    )

    assert evaluate_capability_answer(_case("knowledge_hard_carbon_dating"), answer)[0] == 1


def test_concept_grader_accepts_correct_live_lunar_and_mercator_paraphrases():
    lunar = (
        "The Moon orbits Earth in the same direction that Earth rotates, so Earth must "
        "rotate a little extra to bring it back to the meridian."
    )
    mercator = (
        "The Mercator projection stretches areas away from the equator toward the poles, "
        "exaggerating high-latitude Greenland relative to Africa."
    )

    assert evaluate_capability_answer(_case("knowledge_hard_lunar_day"), lunar)[0] == 1
    assert evaluate_capability_answer(_case("knowledge_hard_mercator"), mercator)[0] == 1


def test_concept_grader_accepts_articles_plurals_and_detectability_paraphrases():
    lunar = (
        "The Moon orbits the Earth in the same direction that the Earth rotates, so the "
        "Earth must rotate slightly more than 360 degrees to catch up."
    )
    carbon = (
        "Carbon-14 decays so quickly that after millions of years there is none left to "
        "measure reliably."
    )
    mercator = (
        "The Mercator projection stretches landmasses away from the equator, so regions "
        "near the poles look much larger."
    )

    assert evaluate_capability_answer(_case("knowledge_hard_lunar_day"), lunar)[0] == 1
    assert evaluate_capability_answer(_case("knowledge_hard_carbon_dating"), carbon)[0] == 1
    assert evaluate_capability_answer(_case("knowledge_hard_mercator"), mercator)[0] == 1


def test_word_count_concept_grader_still_works_on_synthetic_payloads():
    case = {
        "grader": {
            "type": "word_count_concepts",
            "word_count": 4,
            "word_count_weight": 0.4,
            "required_groups": [["axial tilt"]],
        }
    }

    exact_score, exact_reason, _ = evaluate_capability_answer(case, "axial tilt does matter")
    short_score, short_reason, _ = evaluate_capability_answer(case, "axial tilt matters")

    assert exact_score == 1
    assert "word count 4/4" in exact_reason
    assert short_score == pytest.approx(0.6)
    assert "word count 3/4" in short_reason


def test_short_letter_aliases_require_the_whole_final_answer():
    assert evaluate_capability_answer(_case("logic_hard_four_chests"), "Final answer: Y")[0] == 0
    assert (
        evaluate_capability_answer(
            _case("reflection_hard_simpson_glaze"),
            "Final answer: B is better than A overall",
        )[0]
        == 0
    )
    assert (
        evaluate_capability_answer(_case("reflection_hard_simpson_glaze"), "Final answer: A")[0]
        == 1
    )


def test_memorized_classic_crt_answers_do_not_pass_varied_covers():
    assert (
        evaluate_capability_answer(_case("reflection_hard_switch_chests"), "Final answer: 2/3")[0]
        == 0
    )
    assert (
        evaluate_capability_answer(_case("reflection_hard_base_rate"), "Final answer: 9%")[0] == 0
    )
    assert (
        evaluate_capability_answer(_case("reflection_medium_lamp_bulb"), "Final answer: $0.25")[0]
        == 0
    )


def test_alias_grading_remains_strict_when_concept_matching_is_flexible():
    assert evaluate_capability_answer(_case("logic_hard_four_chests"), "Final answer: Y")[0] == 0


def test_capability_category_scores_weight_harder_cases_more():
    fixture = load_capability_fixture()
    results = [
        {
            "category": "math",
            "difficulty": "easy",
            "score_fraction": 1,
        },
        {
            "category": "math",
            "difficulty": "hard",
            "score_fraction": 0,
        },
    ]

    scores = score_capability_categories(results, fixture)

    assert scores["math"] == 25
    assert scores["logic"] is None


class _Response:
    status_code = 200
    headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "message": {"content": "Final answer: 8"},
            "prompt_eval_count": 10,
            "prompt_eval_duration": 1_000_000,
            "eval_count": 4,
            "eval_duration": 1_000_000,
        }


class _Session:
    def __init__(self):
        self.payloads = []

    def request(self, _method, _url, **kwargs):
        self.payloads.append(kwargs["json"])
        return _Response()


def test_raw_capability_request_can_explicitly_disable_or_omit_thinking():
    session = _Session()
    client = OllamaBenchmarkClient(
        "http://benchmark.invalid",
        "model",
        session=session,
        max_retries=0,
    )
    messages = [{"role": "user", "content": "Solve this."}]

    client.chat(messages, context_window=8192, max_tokens=128, think=False)
    client.chat(messages, context_window=8192, max_tokens=128, think=None)
    client.chat(messages, context_window=8192, max_tokens=128, think="high")

    assert session.payloads[0]["think"] is False
    assert "think" not in session.payloads[1]
    assert session.payloads[2]["think"] == "high"
    assert all(payload["messages"] == messages for payload in session.payloads)
    assert all("tools" not in payload and "format" not in payload for payload in session.payloads)


def test_combined_grade_requires_complete_canonical_thinking_off_profile():
    jarvis = {"score": 80, "letter": "B"}
    capability_grade = {"score": 90, "letter": "A"}

    combined = calculate_combined_grade(
        jarvis,
        capability_grade,
        capability_thinking="off",
    )
    noncanonical = calculate_combined_grade(
        jarvis,
        capability_grade,
        capability_thinking="high",
    )

    assert combined["score"] == 84
    assert combined["letter"] == "B"
    assert noncanonical["score"] is None
    assert "thinking=off" in noncanonical["reason"]


class _ReportClient:
    base_url = "http://benchmark.invalid"
    model = "model"
    timeout = 1.0
    keep_alive = "5m"
    max_retries = 0
    retry_backoff_seconds = 0.0
    retry_events = []

    def get_running_models(self):
        return []


class _CapabilityChatClient(_ReportClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.max_token_calls = []

    def chat(self, _messages, *, max_tokens, **_kwargs):
        self.max_token_calls.append(max_tokens)
        content, done_reason = self.responses.pop(0)
        return RawChatResult(
            content=content,
            message={"content": content},
            raw={
                "message": {"content": content},
                "done_reason": done_reason,
                "prompt_eval_count": 10,
                "prompt_eval_duration": 10_000_000,
                "eval_count": max_tokens,
                "eval_duration": 1_000_000_000,
            },
            wall_ms=100,
        )


def test_capability_case_retries_output_truncation_with_larger_budget(monkeypatch):
    client = _CapabilityChatClient(
        [
            ("I derived x = 8 but need to verify", "length"),
            ("The solution is x = 8.\nFinal answer: 8", "stop"),
        ]
    )
    runner = BenchmarkRunner(client, contexts=[8192], evaluation="capability")
    runner._capability_fixture = load_capability_fixture()
    monkeypatch.setattr(runner, "_residency_check", lambda *_args, **_kwargs: {"ok": True})

    result = runner._run_capability_case(_case("math_easy_linear"), 1)

    assert client.max_token_calls == [1024, 2048]
    assert result["score_fraction"] == 1
    assert result["output_budget"]["retry_count"] == 1
    assert result["wall_ms"] == 200


def test_unresolved_output_truncation_is_unscored_not_wrong(monkeypatch):
    client = _CapabilityChatClient(
        [
            ("partial", "length"),
            ("still partial", "length"),
        ]
    )
    runner = BenchmarkRunner(client, contexts=[8192], evaluation="capability")
    runner._capability_fixture = load_capability_fixture()
    monkeypatch.setattr(runner, "_residency_check", lambda *_args, **_kwargs: {"ok": True})

    result = runner._run_capability_case(_case("math_easy_linear"), 1)

    assert result["score_fraction"] is None
    assert result["passed"] is None
    assert result["scored"] is False
    assert "unscored" in result["reason"]


def test_capability_only_report_has_separate_grade_and_no_jarvis_fit():
    runner = BenchmarkRunner(
        _ReportClient(),
        contexts=[8192],
        evaluation="capability",
    )
    runner._capability_fixture = load_capability_fixture()
    report = {
        "status": "complete",
        "functional_results": [],
        "capability_results": [
            {
                "category": category,
                "difficulty": "easy",
                "score_fraction": 1,
                "thinking_control_honored": True,
            }
            for category in CAPABILITY_CATEGORIES
        ],
        "context_probes": [],
        "performance": {},
        "transport": {"retry_events": []},
        "warnings": [],
    }

    runner._finalize_report(report)

    assert report["grades"]["jarvis"]["score"] is None
    assert report["grades"]["model_capability"]["score"] == 100
    assert report["grades"]["combined"]["score"] is None
    assert report["grade_scope"] == "model_capability"
    assert report["grade"]["score"] == 100
    assert report["jarvis_local_fit"] == "not_evaluated"
    report["configuration"] = {"evaluation": "capability", "capability_thinking": "off"}
    markdown = render_markdown_report(report)
    assert "Warm latency median/p95" not in markdown
    assert "Recommended tested context" not in markdown


def test_explicit_thinking_profile_is_inconclusive_when_model_does_not_honor_it():
    runner = BenchmarkRunner(
        _ReportClient(),
        contexts=[8192],
        evaluation="capability",
        capability_thinking="high",
    )
    runner._capability_fixture = load_capability_fixture()
    report = {
        "status": "complete",
        "functional_results": [],
        "capability_results": [
            {
                "category": category,
                "difficulty": "easy",
                "score_fraction": 1,
                "thinking_control_honored": False,
            }
            for category in CAPABILITY_CATEGORIES
        ],
        "context_probes": [],
        "performance": {},
        "transport": {"retry_events": []},
        "warnings": [],
    }

    runner._finalize_report(report)

    assert report["grades"]["model_capability"]["score"] is None
    assert "think=high" in report["grades"]["model_capability"]["reason"]
    assert any("think=high" in warning for warning in report["warnings"])
