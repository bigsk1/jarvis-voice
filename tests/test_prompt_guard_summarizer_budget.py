"""Shipped guard budgets cover the actual default summarizer model inputs."""

import importlib.util
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import config_loader
import pytest
from config_loader import config_scope
from prompt_guard_test_config import write_guard_config
from test_prompt_guard import Response, payload

from lib import prompt_guard as scanner
from lib.prompt_guard_observer import PromptGuardInputBlocked

ROOT = Path(__file__).resolve().parents[1]


def _example_budget(mode):
    settings = (ROOT / f"config/{mode}.env.example").read_text().splitlines()
    return next(line.split("=", 1)[1] for line in settings
                if line.startswith("PROMPT_GUARD_MAX_INPUT_BYTES="))


@pytest.fixture
def summarizer_boundary(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    policy = write_guard_config(directory / "policy.json")
    for mode in ("cloud", "local"):
        (directory / f"{mode}.env").write_text(
            "PROMPT_GUARD_ENABLED=true\n"
            "PROMPT_GUARD_URL=http://scanner-budget.test\n"
            "PROMPT_GUARD_API_KEY=test-scanner-key\n"
            "PROMPT_GUARD_ALERTS_ENABLED=false\n"
            f"PROMPT_GUARD_POLICY_FILE={policy}\n"
            f"PROMPT_GUARD_INCIDENT_DIR={tmp_path / 'incidents'}\n"
        )
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(scanner, "_states", OrderedDict())
    monkeypatch.setattr(scanner, "_capacity", threading.BoundedSemaphore(1))
    state = SimpleNamespace(events=[], flagged=False)

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def post(self, _url, **kwargs):
            body = kwargs["json"]
            state.events.append(("scan", body["text"]))
            return Response(payload(
                threshold=body["threshold"],
                injection_score=0.99 if state.flagged else 0.1,
                flagged=state.flagged,
            ))

    monkeypatch.setattr(scanner.requests, "Session", Session)
    modules = {}
    for name, relative in (
        ("text", "skills/auto-tools/text_summarizer.py"),
        ("stash", "skills/stash.py"),
    ):
        module_name = f"budget_{name}_summarizer"
        spec = importlib.util.spec_from_file_location(module_name, ROOT / relative)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)
        modules[name] = module

    provider = Mock(model="budget-summary-test")

    def chat(message, **_kwargs):
        state.events.append(("model", message))
        return "The report describes library opening hours."

    provider.chat.side_effect = chat
    monkeypatch.setattr(modules["text"], "create_llm_provider",
                        lambda _args: ("ollama", provider.model, provider))
    import llm_provider

    monkeypatch.setattr(llm_provider, "create_configured_provider",
                        lambda **_kwargs: ("ollama", provider.model, provider))
    return SimpleNamespace(**modules, provider=provider, state=state)


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("budget", ["unset", "example"])
@pytest.mark.parametrize("character", ["a", "😀"])
@pytest.mark.parametrize("flagged", [False, True])
def test_default_source_chunk_is_scanned_before_model_with_both_shipped_budgets(
    summarizer_boundary, mode, budget, character, flagged,
):
    boundary = summarizer_boundary
    boundary.state.flagged = flagged
    source = character * 12000
    overrides = {} if budget == "unset" else {"PROMPT_GUARD_MAX_INPUT_BYTES": _example_budget(mode)}
    with config_scope(mode, overrides):
        if flagged:
            with pytest.raises(PromptGuardInputBlocked):
                boundary.text.summarize_with_strategy(source, {"method": "llm"})
            boundary.provider.chat.assert_not_called()
            assert boundary.state.events == [("scan", source)]
        else:
            summary, metadata = boundary.text.summarize_with_strategy(source, {"method": "llm"})
            assert summary and metadata["llm_used"] is True
            assert metadata["chunks_used"] == metadata["chunks_total"] == 1
            assert [kind for kind, _ in boundary.state.events] == ["scan", "model"]
            assert boundary.state.events[0][1] == source
            assert source in boundary.state.events[1][1]


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_default_stash_source_slice_scans_multibyte_text_before_helper(summarizer_boundary, mode):
    boundary = summarizer_boundary
    source = "😀" * 9000
    with config_scope(mode):
        summary = boundary.stash.summarize_content_with_llm(source, "library.txt")
    assert summary
    assert [kind for kind, _ in boundary.state.events] == ["scan", "model"]
    assert boundary.state.events[0][1] == source[:8000]
    assert source[:8000] in boundary.state.events[1][1]
    assert source not in boundary.state.events[1][1]


def test_explicit_smaller_budget_still_skips_whole_source(summarizer_boundary):
    boundary = summarizer_boundary
    source = "a" * 12000
    with config_scope("cloud", {"PROMPT_GUARD_MAX_INPUT_BYTES": "8192"}):
        summary, metadata = boundary.text.summarize_with_strategy(source, {"method": "llm"})
    assert summary and metadata["llm_used"] is True
    assert [kind for kind, _ in boundary.state.events] == ["model"]
    assert source in boundary.state.events[0][1]
