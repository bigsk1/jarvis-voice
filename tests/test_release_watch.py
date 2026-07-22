import json
from pathlib import Path
from types import SimpleNamespace

from orchestrator.pipeline_executor import PipelineExecutor
from skills import release_watch


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
        "git_release_notes",
        "create_alert",
        "release_watch",
    ]
    assert steps[0]["params"]["action"] == "check"
    assert steps[-1]["params"]["action"] == "acknowledge"
    assert steps[-1]["step"] > steps[1]["step"]
    assert steps[-1]["step"] > steps[2]["step"]
    assert steps[1]["params"]["save_to_canvas"] is True
    assert steps[2]["params"]["metadata"]["dedupe_key"] == "${alert_dedupe_key}"
    assert steps[2]["params"]["speak_immediately"] is False


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
        ("git_release_notes", None),
        ("create_alert", None),
        ("release_watch", "acknowledge"),
    ]
    assert calls[2][1]["metadata"]["canvas_page_id"] == "page_release_2026_8_1"
    assert calls[3][1]["version"] == "2026.8.1"
