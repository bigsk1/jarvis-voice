"""Safety and mode-isolation regression coverage for unattended self-play."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import self_play


def _bare_engine(mode="local"):
    engine = self_play.SelfPlayEngine.__new__(self_play.SelfPlayEngine)
    engine.mode = mode
    engine.project_root = PROJECT_ROOT
    engine.logs_dir = PROJECT_ROOT / "logs" / "self-play"
    engine.excluded_tools = ["send_email", "remember"]
    return engine


def test_default_exclusions_cover_persistent_and_external_actions():
    excluded = set(self_play.DEFAULT_EXCLUDED_TOOLS)
    assert {
        "acknowledge_alerts",
        "api_call",
        "create_alert",
        "create_social_clip",
        "forget",
        "ingest_intel",
        "memory_deduper",
        "price_alert",
        "remember",
        "speaker_volume",
        "stash",
        "update_memory",
        "upload_cloudflare",
        "youtube_video",
    } <= excluded


def test_google_trends_is_reviewed_for_read_only_self_play():
    assert "serpapi_google_local" in self_play.DEFAULT_ALLOWED_TOOLS
    assert "serpapi_google_local_services" in self_play.DEFAULT_ALLOWED_TOOLS
    assert "serpapi_google_images_light" in self_play.DEFAULT_ALLOWED_TOOLS
    assert "serpapi_google_news_light" in self_play.DEFAULT_ALLOWED_TOOLS
    assert "serpapi_google_shopping_light" in self_play.DEFAULT_ALLOWED_TOOLS
    assert "serpapi_google_sports" in self_play.DEFAULT_ALLOWED_TOOLS
    assert "serpapi_google_trends" in self_play.DEFAULT_ALLOWED_TOOLS
    assert "serpapi_google_trending_now" in self_play.DEFAULT_ALLOWED_TOOLS


def test_registry_is_fail_closed_for_new_or_unreviewed_tools():
    class FakeRegistry:
        def __init__(self, *_args, **_kwargs):
            self.tools = {
                "weather": SimpleNamespace(permissions={"dangerous": False}),
                "brand_new_action": SimpleNamespace(permissions={"dangerous": False}),
                "dangerous_read_name": SimpleNamespace(permissions={"dangerous": True}),
            }

        def list_tools(self):
            return list(self.tools)

        def get_tool(self, name):
            return self.tools[name]

    engine = _bare_engine()
    with patch("tool_schema.ToolRegistry", FakeRegistry), patch.object(
        self_play, "get_config_value", return_value=""
    ):
        excluded = set(engine._get_excluded_tools())

    assert "weather" not in excluded
    assert "brand_new_action" in excluded
    assert "dangerous_read_name" in excluded


def test_registry_failure_aborts_instead_of_running_fail_open():
    class BrokenRegistry:
        def __init__(self, *_args, **_kwargs):
            raise ValueError("broken registry")

    engine = _bare_engine()
    with patch("tool_schema.ToolRegistry", BrokenRegistry), patch.object(
        self_play, "get_config_value", return_value=""
    ):
        try:
            engine._get_excluded_tools()
        except RuntimeError as exc:
            assert "refusing to run fail-open" in str(exc)
        else:
            raise AssertionError("self-play must abort when its safety registry is unavailable")


def test_execute_query_uses_sanitized_mode_environment():
    engine = _bare_engine("local")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"ok": True, "speech": "done", "tools_used": []}),
            stderr="",
        )

    with patch.object(
        self_play,
        "export_config_environment",
        return_value={"JARVIS_MODE": "local", "LOCAL_ONLY_SENTINEL": "yes"},
    ) as export_env, patch.object(self_play.subprocess, "run", side_effect=fake_run):
        result = engine.execute_query("What time is it?", "information", collect_feedback=False)

    export_env.assert_called_once_with("local")
    assert result.ok is True
    assert captured["env"]["JARVIS_MODE"] == "local"
    assert captured["env"]["JARVIS_SELF_PLAY"] == "true"
    assert captured["env"]["JARVIS_TTS_DISABLED"] == "true"
    assert captured["env"]["JARVIS_SELF_PLAY_EXCLUDED_TOOLS"] == "send_email,remember"


def test_orchestrator_skips_cross_mode_memory_sync_for_self_play():
    source = (PROJECT_ROOT / "orchestrator/orchestrator_v2.py").read_text()
    assert 'os.environ.get("JARVIS_SELF_PLAY", "").strip().lower() != "true"' in source
    assert "auto_sync_on_startup(mode, verbose=False)" in source


def test_session_reader_does_not_initialize_execution_safety():
    with patch.object(self_play.SelfPlayEngine, "_get_excluded_tools") as exclusions:
        engine = self_play.SelfPlayEngine.session_reader("local")

    exclusions.assert_not_called()
    assert engine.mode == "local"
    assert engine.excluded_tools == []


def test_dashboard_self_play_commands_match_current_cli():
    dashboard = (PROJECT_ROOT / "bin/jarvis-dashboard").read_text()
    expected = (
        "./bin/jarvis-self-play --queries 5 --mode cloud",
        "./bin/jarvis-self-play --queries 20 --mode cloud",
        "./bin/jarvis-self-play --queries 10 --mode local",
        "./bin/jarvis-self-play list",
        "./bin/jarvis-self-play results --session latest",
        "logs/self-play/self-play-$(date +%Y-%m-%d).jsonl",
    )
    for command in expected:
        assert command in dashboard

    assert "Quick guarded live session" in dashboard
    assert "Recent sessions from both modes" in dashboard
