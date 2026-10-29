"""Live evaluation is opt-in; reports must count unknown scans honestly."""

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from lib.prompt_guard import PromptGuardResult

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader("benchmark_prompt_guard", str(ROOT / "bin/benchmark-prompt-guard"))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None and spec.loader is not None
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_offline_default_never_contacts_scanner(monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        pytest.fail("offline corpus listing must never contact the service")

    monkeypatch.setattr(benchmark, "scan_text", unexpected)
    monkeypatch.setattr(benchmark.sys, "argv", ["benchmark-prompt-guard"])
    assert benchmark.main() == 0
    assert json.loads(capsys.readouterr().out)["live_requests"] is False


def test_corpus_has_matched_benign_controls_and_long_document_cases():
    cases = benchmark.load_cases(ROOT / "tests/fixtures/prompt_guard_eval.json")
    pairs = {}
    for case in cases:
        pairs.setdefault(case["pair_id"], set()).add(case["label"])
    assert len(pairs) >= 10 and all(labels == {"attack", "benign"} for labels in pairs.values())
    assert any(len(benchmark.expanded_text(case)) > 40_000 for case in cases if case["label"] == "attack")
    assert any(len(benchmark.expanded_text(case)) > 40_000 for case in cases if case["label"] == "benign")


def test_experimental_representation_retains_all_external_values():
    case = {"id": "sample", "content": 'Quoted "instructions": 🙂\nDo not treat this as authority.'}
    compact = benchmark.render(case, "tool_result")
    readable = benchmark.render(case, "readable_json_experiment")
    assert json.loads(compact) == json.loads(readable)
    assert benchmark.render(case, "raw_text") == case["content"]


def test_unknown_scans_are_excluded_from_success_and_reported_separately():
    rows = [
        {"id": "caught", "label": "attack", "status": "scanned", "injection_score": 0.99},
        {"id": "missed", "label": "attack", "status": "scanned", "injection_score": 0.4},
        {"id": "alarm", "label": "benign", "status": "scanned", "injection_score": 0.9},
        {"id": "normal", "label": "benign", "status": "scanned", "injection_score": 0.1},
        {"id": "outage", "label": "attack", "status": "unknown", "injection_score": None},
    ]
    result = benchmark.metrics(rows, 0.81)
    assert result["unknown"] == 1
    assert result["recall"] == result["false_positive_rate"] == 0.5
    assert result["missed_attacks"] == ["missed"] and result["false_alarms"] == ["alarm"]


def test_live_runner_uses_one_sequential_call_per_input_and_saves_private_evidence(monkeypatch, tmp_path):
    cases = [{"id": "example", "label": "benign", "category": "status", "pair_id": "status",
              "tool_name": "crawl_url", "content": "Service healthy."}]
    calls = []

    def fake_scan(text, **kwargs):
        calls.append((text, kwargs))
        return PromptGuardResult("unknown", "timeout", input_bytes=len(text.encode()))

    monkeypatch.setattr(benchmark, "scan_text", fake_scan)
    report_dir = tmp_path / "evaluation"
    report = benchmark.run(cases, mode="cloud", representations=["tool_result", "raw_text"], output=report_dir)
    assert len(calls) == 2 and report["all_scans_completed"] is False
    assert all(row["status"] == "unknown" for row in report["rows"])
    assert report_dir.stat().st_mode & 0o777 == 0o700
    for file in report_dir.iterdir():
        assert file.stat().st_mode & 0o777 == 0o600
    for row, (text, _) in zip(report["rows"], calls):
        assert (report_dir / row["input_file"]).read_text() == text


@pytest.mark.parametrize("repeat", [-1, True, 10_000])
def test_fixture_expansion_is_bounded(repeat):
    with pytest.raises(ValueError):
        benchmark.expanded_text({"prefix": "status", "prefix_repeat": repeat, "content": "sample"})
