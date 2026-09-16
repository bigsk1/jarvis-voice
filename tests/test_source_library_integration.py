"""Real tool subprocess, Stash retention and saved follow-up contracts."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

from config_loader import config_scope  # noqa: E402
from source_library import SourceLibrary  # noqa: E402
from source_library_context import project_library_result  # noqa: E402


def test_actual_executor_uses_argv_and_request_scoped_storage(tmp_path, monkeypatch):
    from executor import ToolExecutor
    from tool_schema import ToolRegistry

    # Executor resolves python3 through the active application's PATH.
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    with config_scope("local", {"SOURCE_LIBRARY_DIR": str(tmp_path)}):
        lib = SourceLibrary()
        sid = lib.save(b"End-to-end local evidence: silver fern.", "note.txt")["source_id"]
        registry = ToolRegistry(str(ROOT / "skills"))
        assert registry.get_tool("source_library") is not None
        executor = ToolExecutor("local", registry=registry)
        result = executor.execute(
            "source_library", {"action": "search", "query": "silver fern", "semantic": False}
        )
        assert result["ok"], result
        assert result["data"]["passages"][0]["source_id"] == sid
        assert result["data"]["mode"] == "local"
        source = tmp_path / "new-source.txt"
        source.write_text("Retained through the real save subprocess.")
        saved = executor.execute("source_library", {"action": "save", "source": str(source)})
        assert saved["ok"], saved
        assert saved["data"]["source"]["index_status"] == "keyword_only"
        assert saved["data"]["remaining"] == 1
        assert lib.download(saved["data"]["source"]["source_id"])[0] == source.read_bytes()
        executor.set_cancel_check(lambda: True)
        cancelled = executor.execute("source_library", {"action": "remove", "source_id": sid})
        assert cancelled.get("cancelled") is True, cancelled
        assert lib.download(sid)[0].endswith(b"silver fern.")
        registry.cleanup()


def test_saving_stash_then_expiring_it_keeps_library_original(tmp_path, monkeypatch):
    import source_library
    from stash_helper import StashFile, open_space

    spec = importlib.util.spec_from_file_location(
        "library_skill", ROOT / "skills/source_library.py"
    )
    skill = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(skill)

    def unexpected_embedding(*args, **kwargs):
        pytest.fail("Save must acknowledge the original without waiting for embeddings")

    monkeypatch.setattr(source_library, "get_embeddings_batch", unexpected_embedding)
    with config_scope(
        "local",
        {"SOURCE_LIBRARY_DIR": str(tmp_path / "library"), "STASH_DIR": str(tmp_path / "stash")},
    ):
        space, _ = open_space(labels=["source-test"])
        saved = StashFile(space).save_text("A complete retained note.", "note.txt")
        result = skill.execute({"action": "save", "source": saved["ref"]})
        assert result["ok"] and "index_error" not in result["data"]
        assert result["data"]["remaining"] == result["data"]["source"]["passage_count"]
        assert result["data"]["source"]["index_status"] == "keyword_only"
        assert "Saved" in result["speech"] and "index" in result["speech"]
        sid = result["data"]["source"]["source_id"]
        for path in space.space_path.iterdir():
            path.unlink()
        space.space_path.rmdir()
        assert SourceLibrary().download(sid)[0] == b"A complete retained note."


def test_followup_replay_and_provider_preview_preserve_evidence(tmp_path, monkeypatch):
    from context_assembler import ContextAssembler

    load_server_package("source_followup_test", ROOT / "jarvis-web/server")
    from source_followup_test.services.followup_extractor import extract_followup_data

    monkeypatch.setenv("JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR", str(tmp_path))
    lib = SourceLibrary("local")
    text = ("Background detail. " * 300 + "\nFINAL FINDING: amber stone.").encode()
    sid = lib.save(text, "report.txt")["source_id"]
    search = lib.search("amber stone", semantic=False)
    followup = extract_followup_data({"source_library": search})
    compact = followup["source_library"]
    assert compact["passages"][0]["source_id"] == sid
    assert "amber stone" in compact["passages"][0]["text"]
    path = tmp_path / "saved.json"
    path.write_text(
        json.dumps(
            [
                {
                    "role": "assistant",
                    "content": "Found the passage.",
                    "tools_used": ["source_library"],
                    "tool_results": followup,
                }
            ]
        )
    )
    assembler = ContextAssembler.__new__(ContextAssembler)
    assembler.timezone = ZoneInfo("UTC")
    assembler._safe_iso_to_local_datetime = lambda _value: None
    context = assembler.format_conversation_context(
        "Read the next passage.", json.loads(path.read_text())
    )
    assert "Selected tool hints: source_library" in context
    assert sid in context
    preview, _, shown, _ = assembler.build_llm_result_context_preview(
        "source_library", {"ok": True, "data": search}
    )
    assert "amber stone" in preview and sid in preview
    assert shown <= assembler.tool_context_max_chars("source_library")


def test_large_unicode_context_is_bounded_without_corrupting_passage_text(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR", str(tmp_path))
    lib = SourceLibrary("local")
    sid = lib.save(("界" * 16000).encode(), "note.txt")["source_id"]
    data = lib.read(sid, limit=8)
    projected = project_library_result(data)
    assert len(json.dumps(projected)) <= 15000
    originals = {p["number"]: p for p in data["passages"]}
    for passage in projected["passages"]:
        assert passage["source_id"] == sid
        if "text" in passage:
            assert passage["text"] == originals[passage["number"]]["text"]
        else:
            assert passage["text_omitted"]


def test_canvas_citations_resolve_to_web_with_custom_navigation():
    code = (ROOT / "jarvis-canvas/client/static/js/canvas.js").read_text()
    fn = code[
        code.index("function resolveLibraryLinks(") : code.index(
            "/**", code.index("function resolveLibraryLinks(")
        )
    ]
    script = (
        """
const assert = require('node:assert/strict');
const window = {location: {origin: 'http://jarvis.test:8890', href: 'http://jarvis.test:8890/page/a'}};
"""
        + fn
        + """
const input = '<a href="/library?mode=local&amp;source=' + 'a'.repeat(64) + '&amp;passage=4">Evidence</a>';
assert.ok(resolveLibraryLinks(input).includes('http://jarvis.test:5001/library?'));
window.JarvisUINavigation = {url: () => 'https://chat.example.test'};
assert.ok(resolveLibraryLinks(input).includes('https://chat.example.test/library?'));
assert.equal(resolveLibraryLinks('<a href="https://other.test/library">Other</a>'), '<a href="https://other.test/library">Other</a>');
assert.equal(resolveLibraryLinks('<a href="/library?source=bad">Bad</a>'), '<a href="/library?source=bad">Bad</a>');
"""
    )
    subprocess.run(["node", "-e", script], check=True, timeout=10)


def test_unicode_titles_and_empty_page_metadata_fit_followup_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR", str(tmp_path))
    lib = SourceLibrary("local")
    sid = lib.save(("界" * 16000).encode(), "文" * 195 + ".txt", title="界" * 200)["source_id"]
    data = lib.read(sid, limit=8)
    data["source"]["empty_pages"] = list(range(1, 1000))
    compact = project_library_result(data, text_budget=2000, max_chars=2500)
    assert len(json.dumps(compact)) <= 2500
    assert compact["source"]["source_id"] == sid
    assert compact["passages"][0]["source_id"] == sid
    assert compact["passages"][0]["number"] == 1
