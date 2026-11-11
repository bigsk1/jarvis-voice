"""Screen summarizer evidence before helper calls and preserve terminal stops."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lib.prompt_guard_observer import PromptGuardInputBlocked

ROOT = Path(__file__).resolve().parents[1]


def _load_tool(monkeypatch, relative_path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_config", lambda: None)
    return module


@pytest.fixture
def text_tool(monkeypatch):
    return _load_tool(
        monkeypatch, "skills/auto-tools/text_summarizer.py", "guarded_text_summarizer_tool"
    )


@pytest.fixture
def stash_tool(monkeypatch):
    return _load_tool(monkeypatch, "skills/stash.py", "guarded_stash_tool")


@pytest.fixture
def blocked_result():
    return {
        "ok": False,
        "error_code": "prompt_injection_detected",
        "terminal_failure": True,
        "retry_safe": False,
        "completion": "rejected",
        "speech": "Prompt Guard withheld summarizer input.",
        "data": {"prompt_guard": {"content_withheld": True, "source_type": "model_input"}},
    }


def _provider(outputs, events):
    responses = iter(outputs)
    provider = Mock(model="summary-test")

    def chat(message, **_kwargs):
        events.append(("model", message))
        return next(responses)

    def chat_with_tools(*, messages, tools, system_prompt):
        assert tools == []
        assert system_prompt.startswith("TASK=")
        events.append(("model", messages[0]["content"]))
        return next(responses), None, {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }, None

    provider.chat.side_effect = chat
    provider.chat_with_tools.side_effect = chat_with_tools
    return provider


def _install_text_provider(monkeypatch, text_tool, provider):
    monkeypatch.setattr(
        text_tool, "create_llm_provider", lambda _args: ("openai", "summary-test", provider)
    )


@pytest.mark.parametrize("relative_path", [
    "skills/stash.py", "skills/auto-tools/text_summarizer.py"
])
def test_tools_import_shared_guard_without_an_inherited_pythonpath(tmp_path, relative_path):
    result = subprocess.run(
        [sys.executable, "-I", "-c", (
            "import runpy, sys; runpy.run_path(sys.argv[1], run_name='tool_import_check')"
        ), str(ROOT / relative_path)],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("capture_usage", [False, True])
def test_text_summary_scans_exact_input_before_both_provider_paths(
    monkeypatch, text_tool, capture_usage
):
    events = []
    provider = _provider(["A faithful summary."], events)
    _install_text_provider(monkeypatch, text_tool, provider)
    source = "Example source with names, prices, and dates."

    def review(name, text, **kwargs):
        assert name == "text_summarizer"
        assert kwargs["args"] == {"operation": "summarize"}
        events.append(("scan", text))
        return {"ok": True, "data": {"content": text}}

    monkeypatch.setattr(text_tool, "review_model_input", review)
    summary, metadata = text_tool.summarize_with_strategy(
        source,
        {"method": "llm", "_capture_usage": capture_usage, "prompt_guard_threshold": 1},
    )

    assert summary == "A faithful summary."
    assert events[0] == ("scan", source)
    assert events[1][0] == "model" and source in events[1][1]
    assert len(events) == 2
    assert metadata["llm_used"] is True
    if capture_usage:
        assert metadata["_usage"]["model_calls"] == 1
        assert metadata["_usage"]["total_tokens"] == 15
        assert metadata["_usage"]["provider"] == "openai"
    else:
        assert metadata["_usage"] is None


def test_text_summary_scans_selected_chunks_and_merge_without_claiming_omitted_coverage(
    monkeypatch, text_tool
):
    events = []
    provider = _provider(["First partial.", "Last partial.", "Merged summary."], events)
    _install_text_provider(monkeypatch, text_tool, provider)
    chunks = ["A" * 20, "B" * 20, "C" * 20]
    source_info = {"stash_ref": "stash://space_guard/f_input"}

    def review(name, text, **kwargs):
        assert name == "text_summarizer"
        assert kwargs["args"]["stash_ref"] == source_info["stash_ref"]
        events.append(("scan", text))
        return {"ok": True, "data": {"content": text}}

    monkeypatch.setattr(text_tool, "review_model_input", review)
    summary, metadata = text_tool.summarize_with_strategy(
        "\n\n".join(chunks),
        {"method": "llm", "llm_chunk_chars": 20, "llm_max_chunks": 2, "_capture_usage": True},
        source_info,
    )

    assert summary == "Merged summary."
    assert [event[0] for event in events] == ["scan", "model"] * 3
    assert [text for kind, text in events if kind == "scan"] == [
        chunks[0], chunks[2], "Chunk 1: First partial.\n\nChunk 2: Last partial."
    ]
    assert all(chunks[1] not in text for _kind, text in events)
    assert metadata["chunk_limited"] is True
    assert metadata["chunks_total"] == 3
    assert metadata["chunks_used"] == 2
    assert metadata["_usage"]["model_calls"] == 3
    assert metadata["_usage"]["total_tokens"] == 45


@pytest.mark.parametrize("blocked_scan", [1, 2, 3])
def test_text_summary_block_stops_chunk_or_merge_without_extractive_fallback(
    monkeypatch, text_tool, blocked_result, blocked_scan
):
    events = []
    provider = _provider(["First partial.", "Second partial."], events)
    _install_text_provider(monkeypatch, text_tool, provider)
    scans = []

    def review(_name, text, **_kwargs):
        scans.append(text)
        if len(scans) == blocked_scan:
            return blocked_result
        return {"ok": True, "data": {"content": text}}

    monkeypatch.setattr(text_tool, "review_model_input", review)
    fallback = Mock(side_effect=AssertionError("Rejected text must not enter extractive fallback"))
    monkeypatch.setattr(text_tool, "summarize_text", fallback)

    with pytest.raises(PromptGuardInputBlocked) as exc:
        text_tool.summarize_with_strategy(
            "A" * 20 + "\n\n" + "B" * 20,
            {"method": "llm", "llm_chunk_chars": 20},
        )

    assert exc.value.result is blocked_result
    assert len(events) == blocked_scan - 1
    fallback.assert_not_called()


def test_stash_sourced_text_summary_emits_original_terminal_receipt(
    monkeypatch, tmp_path, text_tool, blocked_result, capsys
):
    source = "Private source text that must be withheld. " * 120
    source_file = tmp_path / "source.txt"
    source_file.write_text(source)
    stash_ref = "stash://space_guard/f_source"
    monkeypatch.setattr(text_tool, "resolve_file_path", lambda **_kwargs: str(source_file))
    calls = []

    def review(name, text, **kwargs):
        calls.append((name, text, kwargs["args"]["stash_ref"]))
        return blocked_result

    monkeypatch.setattr(text_tool, "review_model_input", review)
    provider = Mock(model="summary-test")
    _install_text_provider(monkeypatch, text_tool, provider)
    monkeypatch.setattr(sys, "argv", ["text_summarizer.py", json.dumps({
        "stash_ref": stash_ref, "method": "llm"
    })])

    with pytest.raises(SystemExit) as exc:
        text_tool.main()

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert json.loads(output) == blocked_result
    assert source not in output
    assert calls == [("text_summarizer", source, stash_ref)]
    provider.chat.assert_not_called()
    provider.chat_with_tools.assert_not_called()


def test_blocked_merge_retains_usage_from_completed_partial_summaries(
    monkeypatch, text_tool, blocked_result
):
    events = []
    provider = _provider(["First partial.", "Second partial."], events)
    _install_text_provider(monkeypatch, text_tool, provider)
    scans = []

    def review(_name, text, **_kwargs):
        scans.append(text)
        if len(scans) == 3:
            return blocked_result
        return {"ok": True, "data": {"content": text}}

    monkeypatch.setattr(text_tool, "review_model_input", review)

    with pytest.raises(PromptGuardInputBlocked) as exc:
        text_tool.summarize_with_strategy(
            "A" * 20 + "\n\n" + "B" * 20,
            {"method": "llm", "llm_chunk_chars": 20, "_capture_usage": True},
        )

    assert {key: value for key, value in exc.value.result.items() if key != "usage"} == blocked_result
    assert exc.value.result["usage"]["model_calls"] == 2
    assert exc.value.result["usage"]["total_tokens"] == 30
    assert "usage" not in blocked_result
    assert len(events) == 2


@pytest.mark.parametrize("operation", ["keywords", "count", "sentiment", "summarize"])
def test_non_llm_text_operations_do_not_scan_or_create_a_provider(
    monkeypatch, text_tool, operation, capsys
):
    review = Mock(side_effect=AssertionError("No model input exists"))
    provider_factory = Mock(side_effect=AssertionError("This is an extractive operation"))
    monkeypatch.setattr(text_tool, "review_model_input", review)
    monkeypatch.setattr(text_tool, "create_llm_provider", provider_factory)
    monkeypatch.setattr(sys, "argv", ["text_summarizer.py", json.dumps({
        "text": "Useful examples are good. More useful examples follow.",
        "operation": operation,
        "method": "extractive",
    })])

    text_tool.main()

    assert json.loads(capsys.readouterr().out)["ok"] is True
    review.assert_not_called()
    provider_factory.assert_not_called()


@pytest.mark.parametrize("capture_usage", [False, True])
def test_stash_summary_scans_only_consumed_slice_before_provider_call(
    monkeypatch, stash_tool, capture_usage
):
    import llm_provider

    events = []
    provider = _provider(["Dense summary."], events)
    monkeypatch.setattr(
        llm_provider, "create_configured_provider",
        lambda **_kwargs: ("openai", "summary-test", provider),
    )
    source = "A" * 8000 + "OMITTED FROM THE MODEL INPUT"

    def review(name, text, **kwargs):
        assert name == "stash_summary"
        assert kwargs["args"] == {"action": "remember", "file_name": "source.txt"}
        events.append(("scan", text))
        return {"ok": True, "data": {"content": text}}

    monkeypatch.setattr(stash_tool, "review_model_input", review)
    summary, usage = stash_tool._summarize_content_with_llm_and_usage(
        source, "source.txt", collect_usage=capture_usage,
    )

    assert summary == "Dense summary."
    assert events[0] == ("scan", source[:8000])
    assert events[1][0] == "model" and source[:8000] in events[1][1]
    assert "OMITTED FROM THE MODEL INPUT" not in events[1][1]
    assert len(events) == 2
    if capture_usage:
        assert usage["model_calls"] == 1
        assert usage["total_tokens"] == 15
    else:
        assert usage is None


def _remember_source(monkeypatch, tmp_path, stash_tool, *, pdf=False):
    import memory_db

    source = "Private artifact text that must not enter Memory. " * 120
    (tmp_path / "source.txt").write_text(source)
    metadata = {
        "file_id": "f_source", "name": "source.txt", "stored_name": "source.txt",
        "mime_type": "application/pdf" if pdf else "text/plain", "size_bytes": len(source),
    }
    space = SimpleNamespace(space_path=tmp_path)
    monkeypatch.setattr(stash_tool, "get_space", lambda _space_id: space)
    monkeypatch.setattr(
        stash_tool, "StashFile", lambda *_args, **_kwargs: SimpleNamespace(exists=True, meta=metadata)
    )
    monkeypatch.setattr(stash_tool, "extract_pdf_text", lambda _path: source)
    memory_factory = Mock()
    monkeypatch.setattr(memory_db, "get_memory_db", memory_factory)
    return source, memory_factory


@pytest.mark.parametrize("pdf", [False, True])
def test_stash_remember_block_never_falls_back_or_writes_memory(
    monkeypatch, tmp_path, stash_tool, blocked_result, pdf
):
    import llm_provider

    _source, memory_factory = _remember_source(monkeypatch, tmp_path, stash_tool, pdf=pdf)
    monkeypatch.setattr(stash_tool, "review_model_input", lambda *_args, **_kwargs: blocked_result)
    provider_factory = Mock(side_effect=AssertionError("Blocked before provider construction"))
    monkeypatch.setattr(llm_provider, "create_configured_provider", provider_factory)

    with pytest.raises(PromptGuardInputBlocked) as exc:
        stash_tool.action_remember({
            "space_id": "space_guard", "file_id": "f_source", "summarize": True,
        })

    assert exc.value.result is blocked_result
    memory_factory.assert_not_called()
    provider_factory.assert_not_called()


def test_stash_main_keeps_terminal_receipt_without_raw_fallback(
    monkeypatch, tmp_path, stash_tool, blocked_result, capsys
):
    source, memory_factory = _remember_source(monkeypatch, tmp_path, stash_tool)
    monkeypatch.setattr(stash_tool, "review_model_input", lambda *_args, **_kwargs: blocked_result)
    monkeypatch.setattr(sys, "argv", ["stash.py", json.dumps({
        "action": "remember", "space_id": "space_guard", "file_id": "f_source", "summarize": True,
    })])

    with pytest.raises(SystemExit) as exc:
        stash_tool.main()

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert json.loads(output) == blocked_result
    assert source not in output
    memory_factory.assert_not_called()


def test_stash_ordinary_summary_failure_retains_existing_truncation_fallback(
    monkeypatch, tmp_path, stash_tool
):
    import llm_provider

    source, memory_factory = _remember_source(monkeypatch, tmp_path, stash_tool)
    monkeypatch.setattr(
        stash_tool, "review_model_input",
        lambda _name, text, **_kwargs: {"ok": True, "data": {"content": text}},
    )
    provider = Mock()
    provider.chat.side_effect = RuntimeError("Provider unavailable")
    monkeypatch.setattr(
        llm_provider, "create_configured_provider",
        lambda **_kwargs: ("openai", "summary-test", provider),
    )

    result = stash_tool.action_remember({
        "space_id": "space_guard", "file_id": "f_source", "summarize": True,
    })

    assert result["ok"] is True
    assert result["data"]["metadata"]["content_truncated"] is True
    assert memory_factory.return_value.remember.call_args.kwargs["value"] == (
        source[:2000] + "... [truncated]"
    )
