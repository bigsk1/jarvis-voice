import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.pipeline_executor import PipelineExecutor
from skills import git_release_notes, release_watch


def _pypi_payload(*versions: str) -> dict:
    releases = {}
    for version in versions:
        releases[version] = [{
            "yanked": False,
            "upload_time_iso_8601": f"{version[:4]}-07-04T22:00:00Z",
        }]
    return {
        "info": {"summary": "A feature-rich command-line audio/video downloader"},
        "releases": releases,
    }


def test_pypi_watch_baselines_then_waits_for_acknowledgement(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_WATCH_STATE_DIR", str(tmp_path))
    payloads = iter([
        _pypi_payload("2026.6.9"),
        _pypi_payload("2026.6.9", "2026.7.4"),
        _pypi_payload("2026.6.9", "2026.7.4"),
        _pypi_payload("2026.6.9", "2026.7.4"),
    ])
    monkeypatch.setattr(release_watch, "_request_json", lambda _url: next(payloads))

    baseline = release_watch.check_release(
        watch_id="yt-dlp-stable", source="pypi", project="yt-dlp"
    )
    assert baseline["initialized"] is True
    assert baseline["changed"] is False
    assert json.loads((tmp_path / "yt-dlp-stable.json").read_text())["version"] == "2026.6.9"

    changed = release_watch.check_release(
        watch_id="yt-dlp-stable", source="pypi", project="yt-dlp"
    )
    assert changed["changed"] is True
    assert changed["current_version"] == "2026.7.4"
    assert changed["alert_dedupe_key"] == "release-watch:yt-dlp-stable:2026.7.4"

    repeated = release_watch.check_release(
        watch_id="yt-dlp-stable", source="pypi", project="yt-dlp"
    )
    assert repeated["changed"] is True

    release_watch.acknowledge_release(
        watch_id="yt-dlp-stable",
        source="pypi",
        project="yt-dlp",
        version="2026.7.4",
        release_url=changed["release_url"],
        published_at=changed["published_at"],
    )
    unchanged = release_watch.check_release(
        watch_id="yt-dlp-stable", source="pypi", project="yt-dlp"
    )
    assert unchanged["changed"] is False
    assert json.loads((tmp_path / "yt-dlp-stable.json").read_text())["version"] == "2026.7.4"


def test_pypi_watch_ignores_prereleases_and_yanked_files(monkeypatch):
    payload = _pypi_payload("2026.7.4", "2026.8.1rc1")
    payload["releases"]["2026.9.1"] = [{"yanked": True}]
    monkeypatch.setattr(release_watch, "_request_json", lambda _url: payload)

    latest = release_watch._latest_pypi_release("yt-dlp")

    assert latest["version"] == "2026.7.4"


def test_github_versions_are_normalized_for_comparison(monkeypatch):
    monkeypatch.setattr(release_watch, "_request_json", lambda _url: {
        "tag_name": "2026.07.04",
        "html_url": "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.07.04",
        "published_at": "2026-07-04T22:41:44Z",
        "name": "yt-dlp 2026.07.04",
    })

    latest = release_watch._latest_github_release("yt-dlp/yt-dlp")

    assert latest["version"] == "2026.07.04"
    assert latest["normalized_version"] == "2026.7.4"
    assert release_watch._is_newer("2026.07.04", "2026.7.4") == (False, False)


def test_watch_id_cannot_escape_state_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_WATCH_STATE_DIR", str(tmp_path))

    try:
        release_watch._state_path("../escape")
    except ValueError as exc:
        assert "watch_id" in str(exc)
    else:
        raise AssertionError("unsafe watch_id was accepted")


def test_workflow_orders_canvas_alert_and_acknowledgement():
    workflow_path = Path(__file__).parents[1] / "data" / "workflows" / "yt_dlp_release_watch.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["steps"]

    assert [step["tool"] for step in steps] == [
        "release_watch",
        "canvas",
        "git_release_notes",
        "create_alert",
        "release_watch",
    ]
    assert steps[0]["params"]["action"] == "check"
    assert steps[1]["action"] == "read"
    assert steps[-1]["params"]["action"] == "acknowledge"
    assert steps[-1]["step"] > steps[2]["step"]
    assert steps[-1]["step"] > steps[3]["step"]
    assert steps[2]["params"]["save_to_canvas"] is True
    assert steps[2]["params"]["canvas_title"] == (
        "Release Notes: ${github_project} ${current_version}"
    )
    assert steps[3]["params"]["metadata"]["dedupe_key"] == "${alert_dedupe_key}"
    assert steps[3]["params"]["speak_immediately"] is False


def test_changed_workflow_acknowledges_only_after_canvas_and_alert():
    workflow_path = Path(__file__).parents[1] / "data" / "workflows" / "yt_dlp_release_watch.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    calls = []

    def execute(tool, params):
        calls.append((tool, params))
        if tool == "release_watch" and params["action"] == "check":
            return {
                "ok": True,
                "data": {
                    "changed": True,
                    "initialized": False,
                    "previous_version": "2026.7.4",
                    "current_version": "2026.8.1",
                    "release_url": "https://pypi.org/project/yt-dlp/2026.8.1/",
                    "published_at": "2026-08-01T12:00:00Z",
                    "alert_title": "New yt-dlp release: 2026.8.1",
                    "alert_description": "yt-dlp moved from 2026.7.4 to 2026.8.1.",
                    "alert_severity": "medium",
                    "alert_dedupe_key": "release-watch:yt-dlp-stable:2026.8.1",
                },
            }
        if tool == "canvas":
            return {"ok": True, "data": {"matches": [], "count": 0}}
        if tool == "git_release_notes":
            return {
                "ok": True,
                "data": {
                    "canvas_page_id": "page_release_2026_8_1",
                    "release_tag": "2026.08.01",
                    "release_url": "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.01",
                },
            }
        if tool == "create_alert":
            return {"ok": True, "data": {"duplicate_suppressed": False}}
        if tool == "release_watch" and params["action"] == "acknowledge":
            return {"ok": True, "data": {"acknowledged": True, "version": params["version"]}}
        raise AssertionError(f"Unexpected call: {tool} {params}")

    executor = PipelineExecutor(
        mode="cloud",
        executor=SimpleNamespace(execute=execute),
        provider=SimpleNamespace(),
    )

    result = executor.execute(workflow, "/yt_dlp_release_watch")

    assert result["ok"] is True
    assert [(tool, params.get("action")) for tool, params in calls] == [
        ("release_watch", "check"),
        ("canvas", "read"),
        ("git_release_notes", None),
        ("create_alert", None),
        ("release_watch", "acknowledge"),
    ]
    assert calls[2][1]["canvas_title"] == "Release Notes: yt-dlp/yt-dlp 2026.8.1"
    assert calls[3][1]["metadata"]["canvas_page_id"] == "page_release_2026_8_1"
    assert calls[4][1]["version"] == "2026.8.1"


def test_unchanged_workflow_recovers_missing_canvas_without_alert_or_acknowledgement():
    workflow_path = Path(__file__).parents[1] / "data" / "workflows" / "yt_dlp_release_watch.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    calls = []

    def execute(tool, params):
        calls.append((tool, params))
        if tool == "release_watch":
            assert params["action"] == "check"
            return {
                "ok": True,
                "data": {
                    "changed": False,
                    "initialized": False,
                    "previous_version": "2026.8.19",
                    "current_version": "2026.8.19",
                    "release_url": "https://pypi.org/project/yt-dlp/2026.8.19/",
                    "published_at": "2026-08-19T23:48:59Z",
                    "alert_title": "New yt-dlp release: 2026.8.19",
                    "alert_description": "yt-dlp remains at 2026.8.19.",
                    "alert_severity": "medium",
                    "alert_dedupe_key": "release-watch:yt-dlp-stable:2026.8.19",
                },
            }
        if tool == "canvas":
            assert params == {
                "search": "Release Notes: yt-dlp/yt-dlp 2026.8.19",
                "action": "read",
            }
            return {"ok": True, "data": {"matches": [], "count": 0}}
        if tool == "git_release_notes":
            return {
                "ok": True,
                "data": {
                    "canvas_page_id": "page_release_2026_8_19",
                    "release_tag": "2026.08.19",
                    "release_url": "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19",
                },
            }
        raise AssertionError(f"Recovery must not create an alert or acknowledge: {tool}")

    executor = PipelineExecutor(
        mode="cloud",
        executor=SimpleNamespace(execute=execute),
        provider=SimpleNamespace(),
    )

    result = executor.execute(workflow, "/yt_dlp_release_watch")

    assert result["ok"] is True
    assert [tool for tool, _params in calls] == [
        "release_watch",
        "canvas",
        "git_release_notes",
    ]
    assert calls[2][1]["canvas_title"] == (
        "Release Notes: yt-dlp/yt-dlp 2026.8.19"
    )
    assert result["data"]["variables"]["canvas_page_id"] == (
        "page_release_2026_8_19"
    )


def test_unchanged_workflow_skips_release_notes_when_canvas_exists():
    workflow_path = Path(__file__).parents[1] / "data" / "workflows" / "yt_dlp_release_watch.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    calls = []

    def execute(tool, params):
        calls.append((tool, params))
        if tool == "release_watch":
            return {
                "ok": True,
                "data": {
                    "changed": False,
                    "initialized": False,
                    "previous_version": "2026.8.19",
                    "current_version": "2026.8.19",
                    "release_url": "https://pypi.org/project/yt-dlp/2026.8.19/",
                    "published_at": "2026-08-19T23:48:59Z",
                    "alert_title": "New yt-dlp release: 2026.8.19",
                    "alert_description": "yt-dlp remains at 2026.8.19.",
                    "alert_severity": "medium",
                    "alert_dedupe_key": "release-watch:yt-dlp-stable:2026.8.19",
                },
            }
        if tool == "canvas":
            return {
                "ok": True,
                "data": {
                    "page_id": "page_release_2026_8_19",
                    "title": "Release Notes: yt-dlp/yt-dlp 2026.8.19",
                },
            }
        raise AssertionError(f"Existing artifact should make later steps skip: {tool}")

    executor = PipelineExecutor(
        mode="cloud",
        executor=SimpleNamespace(execute=execute),
        provider=SimpleNamespace(),
    )

    result = executor.execute(workflow, "/yt_dlp_release_watch")

    assert result["ok"] is True
    assert [tool for tool, _params in calls] == ["release_watch", "canvas"]


def test_git_release_notes_preserves_canvas_subprocess_error(monkeypatch):
    failed = SimpleNamespace(
        returncode=1,
        stdout=json.dumps({
            "ok": False,
            "error": "Canvas content contains truncated URLs: ['https://example.com/...']",
        }),
        stderr="",
    )
    monkeypatch.setattr(git_release_notes.subprocess, "run", lambda *args, **kwargs: failed)

    page_id, error = git_release_notes.save_report_to_canvas(
        title="Release Notes",
        content="# Notes",
        source_query="owner/repo",
    )

    assert page_id is None
    assert error == "Canvas content contains truncated URLs: ['https://example.com/...']"


def test_git_release_notes_fails_when_requested_canvas_save_fails(
    monkeypatch,
    capsys,
):
    target = SimpleNamespace(owner="yt-dlp", repo="yt-dlp")
    context = {
        "release": {
            "tag_name": "2026.08.19",
            "name": "yt-dlp 2026.08.19",
            "html_url": "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19",
            "published_at": "2026-08-19T23:48:43Z",
        },
        "prev_tag": "2026.07.04",
        "prs": [],
        "issues": [],
    }
    monkeypatch.setattr(git_release_notes, "load_config", lambda: None)
    monkeypatch.setattr(git_release_notes, "parse_repo_target", lambda *_args: target)
    monkeypatch.setattr(git_release_notes, "GitHubClient", lambda: object())
    monkeypatch.setattr(git_release_notes, "fetch_release_context", lambda **_kwargs: context)
    monkeypatch.setattr(git_release_notes, "build_highlights", lambda _context: {
        "stats": {"commits": 40, "prs": 25, "issues": 14},
        "breaking_changes": [],
    })
    monkeypatch.setattr(git_release_notes, "build_markdown_report", lambda *_args: "# Notes")
    canvas_call = {}

    def fail_canvas_save(**kwargs):
        canvas_call.update(kwargs)
        return None, "Canvas rejected the report"

    monkeypatch.setattr(git_release_notes, "save_report_to_canvas", fail_canvas_save)
    monkeypatch.setattr(git_release_notes, "remember_artifact", lambda **_kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "git_release_notes.py",
            json.dumps({
                "target": "yt-dlp/yt-dlp",
                "save_to_canvas": True,
                "canvas_title": "Release Notes: yt-dlp/yt-dlp 2026.8.19",
                "save_to_stash": False,
            }),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        git_release_notes.main()

    result = json.loads(capsys.readouterr().out)
    assert exc_info.value.code == 1
    assert result["ok"] is False
    assert result["error"] == (
        "Failed to save release notes to Canvas: Canvas rejected the report"
    )
    assert canvas_call["title"] == "Release Notes: yt-dlp/yt-dlp 2026.8.19"


def test_changed_workflow_stops_before_alert_when_release_notes_fail():
    workflow_path = Path(__file__).parents[1] / "data" / "workflows" / "yt_dlp_release_watch.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    calls = []

    def execute(tool, params):
        calls.append((tool, params))
        if tool == "release_watch" and params["action"] == "check":
            return {
                "ok": True,
                "data": {
                    "changed": True,
                    "initialized": False,
                    "previous_version": "2026.7.4",
                    "current_version": "2026.8.19",
                    "release_url": "https://pypi.org/project/yt-dlp/2026.8.19/",
                    "published_at": "2026-08-19T23:48:59Z",
                    "alert_title": "New yt-dlp release: 2026.8.19",
                    "alert_description": "yt-dlp moved from 2026.7.4 to 2026.8.19.",
                    "alert_severity": "medium",
                    "alert_dedupe_key": "release-watch:yt-dlp-stable:2026.8.19",
                },
            }
        if tool == "canvas":
            return {"ok": True, "data": {"matches": [], "count": 0}}
        if tool == "git_release_notes":
            return {
                "ok": False,
                "error": "Failed to save release notes to Canvas: rejected",
            }
        raise AssertionError(f"Unexpected call after release-note failure: {tool}")

    executor = PipelineExecutor(
        mode="cloud",
        executor=SimpleNamespace(execute=execute),
        provider=SimpleNamespace(),
    )

    result = executor.execute(workflow, "/yt_dlp_release_watch")

    assert result["ok"] is False
    assert result["data"]["aborted_at_step"] == 3
    assert [tool for tool, _params in calls] == [
        "release_watch",
        "canvas",
        "git_release_notes",
    ]
