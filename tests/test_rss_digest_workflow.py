"""The digest uses two bounded model calls and acknowledges only after publishing."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from rss_feeds.service import RSSFeedService

from data.workflows.skill.skill import _check_workflow
from orchestrator.pipeline_executor import PipelineExecutor
from orchestrator.workflow_loader import WorkflowLoader
from skills import rss_feed

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data/workflows/rss_digest.json"
SHORTLIST = '{"ids":["rss-one","rss-two"]}'
BRIEF = """# Reading/Daily Technology

Checked: 2026-10-27T16:00:00Z

## At a glance
- A practical change in a research tool is worth considering today.

## Stories
### A useful research release
The project's announcement describes a concrete improvement. The supplied
article explains how the feature works and what has changed.
Why it matters: This may help the reader evaluate local research tools.
[Original article](https://example.org/one)

## Sources
- [Project announcement](https://example.org/one)
"""


class DigestProvider:
    def __init__(self, shortlist=SHORTLIST, brief=BRIEF):
        self.outputs = [shortlist, brief]
        self.prompts = []

    def chat_with_tools(self, messages, tools, **kwargs):
        assert tools == []
        self.prompts.append(messages[0]["content"])
        return self.outputs[len(self.prompts) - 1], None, {"input_tokens": 8, "output_tokens": 8, "total_tokens": 16}, None


class DigestTools:
    def __init__(self, *, empty=False, selection_empty=False, fail=None):
        self.empty = empty
        self.selection_empty = selection_empty
        self.fail = fail
        self.calls = []

    def execute(self, tool, params):
        self.calls.append((tool, dict(params)))
        action = params.get("action")
        if self.fail is not None and (self.fail == action or self.fail == tool):
            return {"ok": False, "error": "Controlled failure"}
        if tool == "rss_feed" and action == "read":
            items = [] if self.empty else [
                {"id": "rss-one", "title": "Research release", "url": "https://example.org/one", "summary": "Feed description only."},
                {"id": "rss-two", "title": "Another useful release", "url": "https://example.org/two", "summary": "Another feed description."},
            ]
            data = {"profile": params["profile"], "title": "Reading/Daily Technology", "interests": ["research tools"], "exclude": ["celebrity"], "max_stories": 8, "batch_id": "batch-1", "items": items, "candidate_count": len(items), "has_items": bool(items), "coverage_note": "", "source_status": [{"private_debug": "DO_NOT_PUBLISH_RAW_STATUS"}], "checked_at": "2026-10-27T16:00:00Z"}
        elif tool == "rss_feed" and action == "resolve_selection":
            # The service, rather than the engine, turns the bounded text into
            # typed IDs/URLs intersected with the staged candidates.
            assert params["text"] == params["content"] == params["body"]
            if self.fail == "invalid_selection":
                return {"ok": False, "error": "Unknown candidate ID"}
            items = [] if self.selection_empty else [{"id": "rss-one", "url": "https://example.org/one", "title": "Research release", "summary": "Feed description only."}, {"id": "rss-two", "url": "https://example.org/two", "title": "Second release", "summary": "Feed description only."}]
            data = {"selected_items": items, "urls": [item["url"] for item in items], "has_selection": bool(items)}
        elif tool == "crawl_url":
            data = {"results": [{"url": params["url"], "markdown": "Verified article body about the concrete release. " * 10}]}
        elif tool == "canvas":
            assert params["action"] == "create"
            assert params["content"] == BRIEF.strip()
            data = {"page_id": "page_20261027_090000", "url": "https://canvas.example.org/page_test"}
        elif tool == "rss_feed" and action == "acknowledge":
            assert params["page_id"] == "page_20261027_090000"
            data = {"publication_status": "Published the digest to Canvas."}
        else:
            raise AssertionError((tool, params))
        return {"ok": True, "data": data}


def run(tools, provider=None, query="/rss_digest", **kwargs):
    provider = provider or DigestProvider()
    executor = PipelineExecutor("cloud", tools, provider=provider)
    result = executor.execute(json.loads(WORKFLOW.read_text()), query, **kwargs)
    return result, provider


def test_two_model_calls_read_only_selected_articles_and_publish_before_acknowledging():
    tools = DigestTools()
    result, provider = run(tools)
    assert result["ok"]
    assert len(provider.prompts) == 2
    assert tools.calls[0] == ("rss_feed", {"action": "read", "profile": "daily_tech"})
    crawls = [params for tool, params in tools.calls if tool == "crawl_url"]
    assert [params["url"] for params in crawls] == ["https://example.org/one", "https://example.org/two"]
    assert all(params["cache_mode"] == "bypass" for params in crawls)
    assert [tool for tool, _ in tools.calls][-2:] == ["canvas", "rss_feed"]
    assert tools.calls[-1][1]["action"] == "acknowledge"
    assert "Verified article body" in provider.prompts[1]
    assert "DO_NOT_PUBLISH_RAW_STATUS" not in "\n".join(provider.prompts)
    assert all("${" not in prompt for prompt in provider.prompts)
    assert "Published the digest" in result["speech"]


def test_empty_feed_preserves_existing_canvas_without_model_or_acknowledgment():
    tools = DigestTools(empty=True)
    result, provider = run(tools)
    assert result["ok"]
    assert len(tools.calls) == 1
    assert not provider.prompts
    assert "current Canvas page was kept" in result["speech"]


def test_editor_can_select_nothing_without_publishing_or_acknowledging():
    tools = DigestTools(selection_empty=True)
    result, provider = run(tools, DigestProvider(shortlist='{"ids":[]}'))
    assert result["ok"]
    assert len(provider.prompts) == 1
    assert all(tool == "rss_feed" for tool, _ in tools.calls)
    assert len(tools.calls) == 2
    assert "current Canvas page was kept" in result["speech"]


@pytest.mark.parametrize("fail", ["read", "invalid_selection", "canvas"])
def test_failure_before_publication_never_acknowledges(fail):
    tools = DigestTools(fail=fail)
    result, _ = run(tools)
    assert not result["ok"]
    assert not any(params.get("action") == "acknowledge" for _, params in tools.calls)


def test_invalid_editorial_markdown_fails_before_canvas_and_acknowledgment():
    tools = DigestTools()
    result, _ = run(tools, DigestProvider(brief="I cannot write that digest."))
    assert not result["ok"]
    assert not any(tool == "canvas" or params.get("action") == "acknowledge" for tool, params in tools.calls)


def test_failed_crawls_keep_feed_evidence_without_inventing_article_text():
    tools = DigestTools(fail="crawl_url")
    result, provider = run(tools)
    assert result["ok"]
    assert "[No articles gathered]" in provider.prompts[1]
    assert "Feed description only" in provider.prompts[1]
    assert "Never claim an article was read in full" in provider.prompts[1]


def test_acknowledgment_failure_does_not_report_publication_success():
    tools = DigestTools(fail="acknowledge")
    result, _ = run(tools)
    assert not result["ok"]
    assert any(tool == "canvas" for tool, _ in tools.calls)
    assert tools.calls[-1][1]["action"] == "acknowledge"


def test_explicit_profile_reaches_feed_reader():
    tools = DigestTools(empty=True)
    result, _ = run(tools, query="/rss_digest science")
    assert result["ok"]
    assert tools.calls[0][1]["profile"] == "science"


def test_shared_workflow_loads_and_passes_authoring_checks():
    workflow = json.loads(WORKFLOW.read_text())
    assert _check_workflow(workflow) == ([], [])
    assert WorkflowLoader().get_workflow("rss_digest")["id"] == "rss_digest"
    assert workflow["allow_workflow_tool"] is True
    assert workflow["disable_server_side_tools"] is True


def test_real_service_budget_cuts_trigger_crawls_before_digest_publication(tmp_path, monkeypatch):
    config = tmp_path / "rss.yaml"
    config.write_text(yaml.safe_dump({"v": 1, "profiles": {"daily_tech": {
        "canvas_title": "Reading/Daily Technology",
        "feeds": [{"name": "Engineering", "url": "https://example.org/feed.xml"}],
    }}}))
    now = datetime(2026, 10, 27, 16, tzinfo=timezone.utc)
    rows = [{"url": f"https://example.org/{name}", "title": f"Engineering release {i}",
             "summary": "Feed evidence.", "content": "界" * 3500,
             "content_chars": 3500, "content_truncated": False,
             "content_kind": "inline", "needs_fetch": False}
            for i, name in enumerate(["one", "two", "three", "four", "five", "six", "seven", "eight"])]
    canvas_dir = tmp_path / "canvas"
    canvas_dir.mkdir()
    service = RSSFeedService(config_path=config, state_dir=tmp_path / "state",
                             canvas_dir=canvas_dir, now=now,
                             reader=lambda url, **_: {"url": url, "items": rows})
    batch = service.execute(profile="daily_tech")
    provider = DigestProvider(shortlist=json.dumps({"ids": [row["id"] for row in batch["items"]]}))
    monkeypatch.setattr(rss_feed, "RSSFeedService", lambda: service)
    monkeypatch.setattr(rss_feed, "load_config", lambda: {})

    class ActualFeedTools(DigestTools):
        def execute(self, tool, params):
            if tool == "rss_feed":
                self.calls.append((tool, dict(params)))
                if params.get("action") == "read":
                    return {"ok": True, "data": batch}
                return rss_feed.execute(params)
            if tool == "canvas":
                (canvas_dir / "page_20261027_090000.json").write_text(json.dumps({
                    "id": "page_20261027_090000", "title": params["title"],
                    "content": params["content"],
                }))
            return super().execute(tool, params)

    tools = ActualFeedTools()
    result, provider = run(tools, provider)
    assert result["ok"]
    crawled = [params["url"] for tool, params in tools.calls if tool == "crawl_url"]
    assert crawled == [row["url"] for row in rows]
    assert '"content_truncated": true' in provider.prompts[1]
    assert "Verified article body" in provider.prompts[1]
    assert "truncated excerpt" in provider.prompts[1]
    assert "Published the digest to Canvas" in result["speech"]
