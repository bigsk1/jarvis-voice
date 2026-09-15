"""DeepWiki transport enrichment, citation handling, and isolated artifacts."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import deepwiki
import stash_helper
from mcp_client import MCPClient, MCPRemoteClient, _normalize_call_tool_result


@pytest.fixture(autouse=True)
def isolated_stash(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(tmp_path / "stash"))
    # Fail closed even if a surrounding request-local config overrides env.
    monkeypatch.setattr(stash_helper, "get_stash_dir", lambda: tmp_path / "stash")
    return tmp_path / "stash"


def mcp_result(text, **kwargs):
    return {"content": [{"type": "text", "text": text}], **kwargs}


@pytest.mark.parametrize("transport", ["stdio", "http"])
@pytest.mark.parametrize("tool_name", ["read_wiki_structure", "read_wiki_contents", "ask_question"])
def test_both_transports_enrich_deepwiki_without_raw_duplicate(transport, tool_name, monkeypatch, isolated_stash):
    client = (
        MCPClient("deepwiki", "unused", []) if transport == "stdio"
        else MCPRemoteClient("deepwiki", "https://example.test/mcp", "streamable-http")
    )
    text = 'Uses <wiki_page repo_name="pallets/flask" id="2.2" page_name="Context System" />.'
    monkeypatch.setattr(client, "_send_request", lambda *_args, **_kwargs: mcp_result(text))
    result = client.call_tool(tool_name, {"repoName": "pallets/flask", "question": "Explain contexts"})
    assert result["ok"] is True
    data = result["data"]
    assert data["source"] == "deepwiki"
    assert data["repo_names"] == ["pallets/flask"]
    assert data["question"] == "Explain contexts"
    assert data["answer"] == "Uses [Context System](https://deepwiki.com/pallets/flask/2.2-context-system)."
    assert data["answer_chars"] == len(data["answer"])
    assert data["answer_truncated"] is False
    assert data["external_content_trust"] == "untrusted"
    assert data["sources"] == [{"title": "Context System", "url": "https://deepwiki.com/pallets/flask/2.2-context-system"}]
    assert "raw" not in data and "full_text" not in data and "stash_ref" not in data
    assert not isolated_stash.exists()


def test_relative_citations_use_page_mapping_from_later_in_answer():
    text = (
        "See [contexts](/wiki/pallets/flask#2.2), "
        "[unknown section](/wiki/pallets/flask#9.9), and "
        "[overview](/pallets/flask/1-overview).\n\n"
        '<wiki_page repo="pallets/flask" id="2.2" page_name="Context System" />'
    )
    answer, sources = deepwiki.normalize_deepwiki_markdown(text)
    assert "[contexts](https://deepwiki.com/pallets/flask/2.2-context-system)" in answer
    assert "[unknown section](https://deepwiki.com/pallets/flask)" in answer
    assert "[overview](https://deepwiki.com/pallets/flask/1-overview)" in answer
    assert "/wiki/" not in answer
    assert len(sources) == 3


def test_citation_like_code_is_not_rewritten_or_used_as_source():
    tag = '<wiki_page repo="pallets/flask" id="2.2" page_name="Context System" />'
    code = f"```xml\n{tag}\n[docs](/wiki/pallets/flask#2.2)\n```\n\n`{tag}`\n"
    text = code + "See [contexts](/wiki/pallets/flask#2.2)."
    answer, sources = deepwiki.normalize_deepwiki_markdown(text)
    assert answer.startswith(code)
    assert sources == [{"title": "contexts", "url": "https://deepwiki.com/pallets/flask"}]


def test_source_at_tail_survives_excerpt_and_full_markdown_is_saved(isolated_stash):
    full = "Architecture details. " * 430 + "\n\nSee [source](https://github.com/pallets/flask/blob/main/src/flask/app.py#L10)."
    result = deepwiki.normalize_deepwiki_result(
        "ask_question", mcp_result(full), {"repoName": ["pallets/flask"], "question": "Explain this repository"},
    )
    data = result["data"]
    assert result["ok"] is True
    assert len(data["answer"]) <= deepwiki.DEEPWIKI_ANSWER_CHARS
    assert data["answer_chars"] == len(full)
    assert data["answer_truncated"] is True
    assert data["sources"] == [{"title": "source", "url": "https://github.com/pallets/flask/blob/main/src/flask/app.py#L10"}]
    assert data["stash_ref"].startswith(f"stash://{data['space_id']}/f_")
    saved = isolated_stash / data["space_id"] / data["filename"]
    content = saved.read_text(encoding="utf-8")
    assert full in content
    assert "Repositories: pallets/flask" in content
    assert "Question: Explain this repository" in content
    metadata = json.loads((saved.parent / "meta.json").read_text())
    assert metadata["files"][0]["mime_type"] == "text/markdown"
    assert metadata["files"][0]["tool_origin"] == "mcp_deepwiki_ask_question"
    assert data["mime_type"] == "text/markdown"
    assert "raw" not in data and "full_text" not in data


def test_saved_markdown_has_normalized_citations(isolated_stash):
    full = "Repository details. " * 400 + '<wiki_page repo="pallets/flask" id="2.2" page_name="Context System" />'
    data = deepwiki.normalize_deepwiki_result("read_wiki_contents", mcp_result(full), {})["data"]
    saved = (isolated_stash / data["space_id"] / data["filename"]).read_text()
    assert "<wiki_page" not in saved
    assert "[Context System](https://deepwiki.com/pallets/flask/2.2-context-system)" in saved


def test_artifact_failure_keeps_answer_and_no_bogus_handle(monkeypatch, isolated_stash):
    def partial_failure(self, *args, **kwargs):
        (self.space.space_path / "partial.md").write_text("partial")
        raise OSError("secret /operator/private/path should not appear in tool output")

    monkeypatch.setattr(stash_helper.StashFile, "save_binary", partial_failure)
    result = deepwiki.normalize_deepwiki_result("ask_question", mcp_result("Useful details. " * 500), {})
    data = result["data"]
    assert result["ok"] is True
    assert data["answer"].startswith("Useful details.")
    assert data["answer_truncated"] is True
    assert "artifact_warning" in data
    assert "secret" not in json.dumps(result)
    assert "stash_ref" not in data and "space_id" not in data
    assert list(isolated_stash.iterdir()) == []


@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_unindexed_repo_failure_is_not_saved_or_changed(transport, monkeypatch, isolated_stash):
    client = (
        MCPClient("deepwiki", "unused", []) if transport == "stdio"
        else MCPRemoteClient("deepwiki", "https://example.test/mcp", "streamable-http")
    )
    text = "Repository not found. Visit https://deepwiki.com/bigsk1/jarvis-voice to index it."
    monkeypatch.setattr(client, "_send_request", lambda *_args, **_kwargs: mcp_result(text, isError=True))
    result = client.call_tool("ask_question", {"repoName": "bigsk1/jarvis-voice", "question": "Explain it"})
    assert result["ok"] is False
    assert result["error"] == text
    assert result["data"]["isError"] is True
    assert result["data"]["error"] == text
    assert result["data"]["repo_names"] == ["bigsk1/jarvis-voice"]
    assert result["data"]["question"] == "Explain it"
    assert "raw" not in result["data"] and "full_text" not in result["data"]
    assert "stash_ref" not in result["data"]
    assert not isolated_stash.exists()


def test_direct_normalizer_does_not_stash_large_error(isolated_stash):
    text = "Error details " * 600
    result = deepwiki.normalize_deepwiki_result("ask_question", mcp_result(text, isError=True), {})
    assert result["ok"] is False
    assert result["error"] == text
    assert not isolated_stash.exists()


@pytest.mark.parametrize("server,tool", [("other", "ask_question"), ("deepwiki", "future_tool")])
def test_unrelated_mcp_results_keep_existing_contract(server, tool, isolated_stash):
    raw = mcp_result("Original response")
    result = _normalize_call_tool_result(tool, raw, server_name=server, arguments={"repoName": "pallets/flask"})
    assert result == {"ok": True, "speech": "Original response", "data": {"raw": raw["content"], "full_text": "Original response"}}
    assert not isolated_stash.exists()


@pytest.mark.parametrize("url", [
    "https://user:secret@github.com/owner/repo", "https://github.com:8443/owner/repo",
    "http://github.com/owner/repo", "https://100.64.0.1/repo", "https://localhost/repo",
    "https://github.com.evil.test/owner/repo", "https://example.test/docs", "https://github.com\\@evil.test/docs",
])
def test_source_projection_rejects_unknown_or_credentialed_urls(url):
    assert deepwiki.safe_source_url(url) is None
    _, sources = deepwiki.normalize_deepwiki_markdown(f"[reference]({url})")
    assert sources == []


def test_repository_metadata_handles_current_array_schema():
    assert deepwiki.normalize_repo_names({"repoName": ["pallets/flask", "bigsk1/jarvis-voice", "pallets/flask", "../secret", "https://github.com/pallets/flask", 1]}) == ["pallets/flask", "bigsk1/jarvis-voice"]
    assert deepwiki.normalize_repo_names({"repoName": None}) == []


def test_excerpt_does_not_publish_cut_link(isolated_stash):
    text = "x " * 2920 + "[long source](https://github.com/pallets/flask/blob/main/" + "a" * 400 + ")"
    data = deepwiki.normalize_deepwiki_result("ask_question", mcp_result(text), {})["data"]
    assert "https://" not in data["answer"]
    assert data["sources"][0]["url"].endswith("a" * 400)


def test_full_wiki_relative_source_formats_get_explicit_revision_note():
    text = (
        "# Page: Overview\n\n"
        "- [CHANGES.rst](CHANGES.rst)\n"
        "- [src/flask/__init__.py](src/flask/__init__.py)\n\n"
        "See [Installation and Setup](#1.1).\n\n"
        "Sources: [docs/index.rst:10-11](), [src/flask/__init__.py:2]()."
    )
    result = deepwiki.normalize_deepwiki_result("read_wiki_contents", mcp_result(text), {"repoName": "pallets/flask"})
    data = result["data"]
    assert data["citation_revision_note"] == deepwiki.DEEPWIKI_CITATION_REVISION_NOTE
    assert data["answer"].startswith(deepwiki.DEEPWIKI_CITATION_REVISION_NOTE)
    assert "[CHANGES.rst (HEAD)](https://github.com/pallets/flask/blob/HEAD/CHANGES.rst)" in data["answer"]
    assert "[docs/index.rst:10-11 (HEAD)](https://github.com/pallets/flask/blob/HEAD/docs/index.rst#L10-L11)" in data["answer"]
    assert "[src/flask/__init__.py:2 (HEAD)](https://github.com/pallets/flask/blob/HEAD/src/flask/__init__.py#L2)" in data["answer"]
    assert "[Installation and Setup](https://deepwiki.com/pallets/flask/1.1-installation-and-setup)" in data["answer"]
    assert len(data["sources"]) == 5
    for source in data["sources"]:
        if "/blob/HEAD/" in source["url"]:
            assert "current default branch, HEAD" in source["title"]


@pytest.mark.parametrize("repo_names", [[], ["pallets/flask", "pallets/werkzeug"]])
def test_relative_sources_without_unambiguous_repo_do_not_point_at_jarvis(repo_names):
    text = "[README.md](README.md) and [docs/index.rst:10-11]() and [Overview](#1.1)"
    answer, sources = deepwiki.normalize_deepwiki_markdown(text, repo_names)
    assert answer == "README.md and docs/index.rst:10-11 and Overview"
    assert sources == []


@pytest.mark.parametrize("reference", [
    "../private.py", "foo/../private.py", "/../../private.py", "foo//bar.py",
    "%2e%2e/private.py", "foo/%2Fprivate.py", "foo\\private.py", "//localhost/private.py",
    "/wiki/../private", "file.py:20-10", "https://[invalid",
])
def test_malformed_relative_paths_are_plain_text_not_inferred_sources(reference):
    answer, sources = deepwiki.normalize_deepwiki_markdown(f"[reference]({reference})", ["pallets/flask"])
    assert sources == []
    assert answer == "reference"


def test_relative_file_and_empty_citations_inside_fenced_code_are_unchanged():
    code = "~~~markdown\n[CHANGES.rst](CHANGES.rst)\n[docs/index.rst:10-11]()\n[Setup](#1.1)\n~~~"
    answer, sources = deepwiki.normalize_deepwiki_markdown(code, ["pallets/flask"])
    assert answer == code
    assert sources == []


@pytest.mark.parametrize("content", [[], [{"type": "text", "text": "  \n"}], [{"type": "image", "data": "example"}]])
def test_no_readable_deepwiki_response_is_an_error(content, isolated_stash):
    result = _normalize_call_tool_result("ask_question", {"content": content}, server_name="deepwiki", arguments={"repoName": "pallets/flask"})
    assert result["ok"] is False
    assert result["data"]["isError"] is True
    assert result["data"]["repo_names"] == ["pallets/flask"]
    assert "no readable answer" in result["error"]
    assert not isolated_stash.exists()


def test_source_metadata_is_bounded_but_full_artifact_keeps_every_citation(isolated_stash):
    long_url = "https://github.com/pallets/flask/blob/HEAD/" + "x" * 2100
    links = [f"[Too long]({long_url})"]
    links.extend(
        f"[{'Long source title ' * 20 if index == 0 else f'Source {index}'}](https://github.com/pallets/flask/blob/HEAD/file-{index}.py#L1-L20)"
        for index in range(80)
    )
    data = deepwiki.normalize_deepwiki_result(
        "read_wiki_contents", mcp_result("\n\n".join(links)), {"repoName": "pallets/flask"},
    )["data"]
    assert data["sources_count"] == 81
    assert data["sources_truncated"] is True
    assert len(data["sources"]) == deepwiki.DEEPWIKI_MAX_SOURCES == 24
    assert all(len(source["url"]) <= 2048 and len(source["title"]) <= 160 for source in data["sources"])
    assert data["sources"][0]["title"].endswith("…")
    assert data["sources"][-1]["url"].endswith("file-23.py#L1-L20")
    saved = (isolated_stash / data["space_id"] / data["filename"]).read_text()
    assert long_url in saved
    assert "file-79.py#L1-L20" in saved
