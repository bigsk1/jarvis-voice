"""Fresh discovery must remain independent of the rolling page and video search."""

import json
from pathlib import Path

import pytest

from orchestrator.pipeline_executor import PipelineExecutor

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data/workflows/github_ai_radar_daily.json"
OLD = "OLD_NARRATIVE_DO_NOT_USE: yesterday's repeated projects and star numbers."
FRESH = """# GitHub AI Radar

## Latest Snapshot - Sunday, October 11, 2026
- A new local coding tool makes a useful experiment.

## Notable Projects
| Project | Why look at it | Link |
| --- | --- | --- |
| Fresh tool | Try its newly documented local coding mode. | [Repository](https://github.com/example/fresh-tool) |

<details>
<summary>Advanced details</summary>

## Evidence and caveats
The official announcement describes the feature. Its usefulness still needs
evaluation on your own tasks; no unverified current star figures are reported.

## Sources
- [Announcement](https://example.org/new-release)

</details>
"""


class BriefProvider:
    def __init__(self):
        self.prompts = []

    def chat_with_tools(self, messages, tools, **kwargs):
        assert tools == []
        self.prompts.append(messages[0]["content"])
        text = FRESH
        if len(self.prompts) > 1:
            text = "<details>\n<summary>Recent history</summary>\n\n## Previous Snapshots\n- Yesterday: An older project was discussed.\n\n## Run Log\n- Today: Fresh report published.\n\n</details>"
        return text, None, {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}, None


class RadarTools:
    def __init__(self, existing, tavily):
        self.existing = existing
        self.tavily = tavily
        self.calls = []
        self.saved = {}

    def execute(self, tool, params):
        self.calls.append((tool, dict(params)))
        data = {}
        if tool == "get_time":
            data = {
                "date_formatted": "Sunday, October 11, 2026",
                "day_of_week": "Sunday",
                "time_12h": "10:00 AM",
            }
        elif tool == "canvas" and params["action"] == "read":
            if not self.existing:
                return {"ok": False, "error": "No page found"}
            data = {
                "page_id": "existing-page",
                "title": "Workflows/GitHub AI Radar",
                "content": OLD,
            }
        elif tool == "mcp_brave_search_brave_web_search":
            data = {"results": [{"url": f"https://example.org/web-{i}"} for i in range(3)]}
        elif tool == "brave_llm_context":
            data = {"grounding": {"generic": []}, "sources": {}}
        elif tool == "tavily_search":
            if self.tavily == "failed":
                return {"ok": False, "error": "Tavily unavailable"}
            rows = (
                [{"url": "https://example.org/tavily-only", "snippet": "Independent candidate"}]
                if self.tavily == "results"
                else []
            )
            data = {"results": rows, "results_count": len(rows)}
        elif tool == "serpapi_youtube_search":
            rows = [
                {
                    "url": "https://www.youtube.com/watch?v=video",
                    "title": "Recent roundup",
                    "published_date": "2 days ago",
                }
            ]
            data = {
                "results": rows,
                "top_results": rows,
                "top_url": rows[0]["url"],
                "results_count": 1,
            }
        elif tool == "crawl_url":
            data = {
                "results": [
                    {"url": params["url"], "markdown": "Official project release evidence. " * 25}
                ]
            }
        elif tool == "stash":
            if params["action"] == "open_space":
                data = {"space_id": "test-radar-space"}
            elif params["action"] == "save":
                file_id = f"file-{len(self.saved)}"
                self.saved[file_id] = params["text"]
                data = {
                    "file_id": file_id,
                    "ref": f"stash://test-radar-space/{file_id}",
                    "space_id": "test-radar-space",
                }
            elif params["action"] == "read":
                data = {"content": self.saved[params["file_id"]]}
        elif tool == "canvas":
            data = {"page_id": "existing-page"}
        else:
            raise AssertionError(tool)
        return {"ok": True, "data": data}


@pytest.mark.parametrize(
    "existing,tavily", [(True, "results"), (False, "results"), (True, "empty"), (True, "failed")]
)
def test_radar_keeps_fresh_evidence_and_history_separate(existing, tavily):
    tools = RadarTools(existing, tavily)
    provider = BriefProvider()
    executor = PipelineExecutor("cloud", tools, provider=provider)
    result = executor.execute(json.loads(WORKFLOW.read_text()), "/github_ai_radar")
    assert result["ok"]
    crawled = [p["url"] for name, p in tools.calls if name == "crawl_url"]
    expected = ["https://example.org/web-0", "https://example.org/web-1"]
    if tavily == "results":
        expected.append("https://example.org/tavily-only")
    assert crawled == expected
    assert OLD not in provider.prompts[0]
    assert '"url": "https://example.org/web-0"' in provider.prompts[0]
    if tavily == "results":
        assert "https://example.org/tavily-only" in provider.prompts[0]
    else:
        assert "https://example.org/tavily-only" not in provider.prompts[0]
    writes = [
        p for name, p in tools.calls if name == "canvas" and p["action"] in {"create", "update"}
    ]
    assert len(writes) == 1
    assert writes[0]["content"].startswith(FRESH)
    assert "<summary>Recent history</summary>" in writes[0]["content"]
    assert len(provider.prompts) == (2 if existing else 1)
    if existing:
        assert OLD in provider.prompts[1]
        assert FRESH not in provider.prompts[1]
    generated_saves = [
        p
        for name, p in tools.calls
        if name == "stash"
        and p.get("action") == "save"
        and set(p.get("tags", [])) & {"fresh-brief", "history"}
    ]
    assert [p["name"] for p in generated_saves] == (
        ["radar-fresh-brief.md", "radar-history.md"] if existing else ["radar-fresh-brief.md"]
    )
    assert all("${" not in prompt for prompt in provider.prompts)


def test_radar_generated_files_use_real_stash_and_keep_distinct_names(tmp_path):
    from config_loader import config_scope

    from skills import stash

    class RealStashTools(RadarTools):
        def execute(self, tool, params):
            if tool == "stash":
                self.calls.append((tool, dict(params)))
                return {
                    "open_space": stash.action_open_space,
                    "save": stash.action_save,
                    "read": stash.action_read,
                }[params["action"]](params)
            return super().execute(tool, params)

    tools = RealStashTools(existing=True, tavily="results")
    executor = PipelineExecutor("cloud", tools, provider=BriefProvider())
    with config_scope("cloud", overrides={"STASH_DIR": str(tmp_path)}):
        result = executor.execute(json.loads(WORKFLOW.read_text()), "/github_ai_radar")
    assert result["ok"]
    space = next(tmp_path.glob("space_*"))
    metadata = json.loads((space / "meta.json").read_text())
    by_name = {file["name"]: file for file in metadata["files"]}
    assert "radar-fresh-brief.md" in by_name
    assert "radar-history.md" in by_name
    assert by_name["radar-fresh-brief.md"]["file_id"] != by_name["radar-history.md"]["file_id"]
    assert (space / by_name["radar-fresh-brief.md"]["stored_name"]).read_text() == FRESH.strip()
    assert (
        "<summary>Recent history</summary>"
        in (space / by_name["radar-history.md"]["stored_name"]).read_text()
    )
    assert next(p for name, p in tools.calls if name == "canvas" and p["action"] == "update")[
        "content"
    ].startswith(FRESH.strip())


def test_named_search_binding_cannot_replace_another_engine():
    executor = PipelineExecutor.__new__(PipelineExecutor)
    variables = {}
    for name, binding, url in [
        ("brave_search", "search_results", "https://example.org/web"),
        ("tavily_search", "tavily_results", "https://example.org/independent"),
        ("serpapi_youtube_search", "video_results", "https://www.youtube.com/watch?v=video"),
    ]:
        executor._apply_output_transforms(
            {"search_output_var": binding},
            {"ok": True, "data": {"results": [{"url": url}]}},
            variables,
            name,
            "",
        )
    assert variables["search_results"]["urls"] == ["https://example.org/web"]
    assert variables["tavily_results"]["urls"] == ["https://example.org/independent"]
    assert variables["video_results"]["urls"] == ["https://www.youtube.com/watch?v=video"]
    failed = {"ok": False, "data": {"results": []}}
    executor._apply_output_transforms(
        {"search_output_var": "tavily_results"}, failed, variables, "tavily_search", ""
    )
    assert not failed["ok"]
    assert variables["tavily_results"]["urls"] == []
    assert variables["search_results"]["urls"] == ["https://example.org/web"]


def test_legacy_search_recovers_only_when_urls_exist():
    executor = PipelineExecutor.__new__(PipelineExecutor)
    variables = {"search_results": {"urls": ["https://example.org/kept"]}}
    failed = {"ok": False, "data": {"results": []}}
    executor._apply_output_transforms({}, failed, variables, "brave_search", "")
    assert not failed["ok"]
    assert "recovered" not in failed
    assert variables["search_results"]["urls"] == ["https://example.org/kept"]

    recovered = {"ok": False, "data": {"results": [{"url": "https://example.org/new"}]}}
    executor._apply_output_transforms({}, recovered, variables, "brave_search", "")
    assert recovered["ok"] and recovered["recovered"]
    assert variables["search_results"]["urls"] == ["https://example.org/new"]


def test_min_urls_is_opt_in_and_requires_extracted_search_urls():
    executor = PipelineExecutor.__new__(PipelineExecutor)
    result = {"ok": True, "data": {"results": [{"title": "Candidate"}] * 3}}
    step = {"validation": {"type": "heuristic", "min_results": 3}}
    assert executor._validate_result(result, step, {})
    step["validation"]["min_urls"] = 3
    assert not executor._validate_result(result, step, {})
    result["data"]["results"] = [
        {"url": "https://example.org/0"},
        {"url": "https://example.org/1"},
        {"title": "Candidate without URL"},
    ]
    assert not executor._validate_result(result, step, {})
    result["data"]["results"][2]["url"] = "https://example.org/2"
    assert executor._validate_result(result, step, {})


def test_radar_rejects_title_only_search_before_publishing():
    class TitleOnlyTools(RadarTools):
        def execute(self, tool, params):
            if tool == "mcp_brave_search_brave_web_search":
                self.calls.append((tool, dict(params)))
                return {"ok": True, "data": {"results": [{"title": "Candidate"}] * 3}}
            return super().execute(tool, params)

    tools = TitleOnlyTools(existing=True, tavily="results")
    provider = BriefProvider()
    result = PipelineExecutor("cloud", tools, provider=provider).execute(
        json.loads(WORKFLOW.read_text()), "/github_ai_radar"
    )
    assert not result["ok"]
    assert not provider.prompts
    assert not any(name == "crawl_url" for name, _ in tools.calls)
    assert not any(
        name == "canvas" and params["action"] in {"create", "update"}
        for name, params in tools.calls
    )


def test_unnamed_stash_filler_keeps_legacy_filename():
    executor = PipelineExecutor("cloud", RadarTools(True, "results"), provider=BriefProvider())
    assert executor._llm_fill_params(
        {"tool": "stash", "action": "save", "llm_prompt": "Write the report"}, {}
    ) == {"text": FRESH.strip(), "name": "research_source_1.txt"}


def test_crypto_save_keeps_authored_filename_in_separate_run_spaces(tmp_path):
    from config_loader import config_scope

    from skills import stash

    class StashOnlyTools:
        def execute(self, tool, params):
            assert tool == "stash"
            return {"open_space": stash.action_open_space, "save": stash.action_save}[
                params["action"]
            ](params)

    workflow = json.loads((ROOT / "data/workflows/crypto_market_report.json").read_text())
    open_step = next(step for step in workflow["steps"] if step["step"] == 8)
    save_step = next(step for step in workflow["steps"] if step["step"] == 9)
    spaces = []
    with config_scope("cloud", overrides={"STASH_DIR": str(tmp_path)}):
        for _ in range(2):
            executor = PipelineExecutor("cloud", StashOnlyTools(), provider=BriefProvider())
            opened = executor._execute_single(open_step, "stash", "open_space", {}, {}, {})
            assert opened["ok"]
            space_id = opened["data"]["space_id"]
            spaces.append(space_id)
            saved = executor._execute_single(
                save_step,
                "stash",
                "save",
                {},
                {"space_id": space_id, "report_date": "2026-10-11"},
                {},
            )
            assert saved["ok"]
            assert saved["data"]["ref"].startswith(f"stash://{space_id}/")
            metadata = json.loads((tmp_path / space_id / "meta.json").read_text())
            assert [file["name"] for file in metadata["files"]] == [
                "crypto_report_2026-10-11.txt"
            ]
    assert spaces[0] != spaces[1]


def test_authoring_guard_accepts_only_a_validated_full_page_prefix():
    from data.workflows.skill.skill import _check_workflow

    workflow = json.loads(WORKFLOW.read_text())
    assert _check_workflow(workflow)[0] == []
    update = next(
        step
        for step in workflow["steps"]
        if step["tool"] == "canvas" and step.get("action") == "update"
    )
    update["params"]["content"] = "${radar_existing_content}"
    assert any("allow_content_shrink" in error for error in _check_workflow(workflow)[0])
    update["params"]["content"] = "${fresh_radar_content}"
    fresh = next(
        step
        for step in workflow["steps"]
        if step.get("description")
        == "Write a fresh reader-friendly brief without prior Canvas content"
    )
    fresh.pop("llm_output_validation")
    assert any("allow_content_shrink" in error for error in _check_workflow(workflow)[0])
