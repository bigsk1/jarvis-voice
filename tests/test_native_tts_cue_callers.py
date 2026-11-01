"""Native speech callers retain cues for their actual playback configuration."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api.managers import alert_manager
from lib.tts_normalizer import normalize_tts_text
from lib.tts_style_tags import configured_speech_tag_options
from services import follow_up_daemon, reminder_scheduler, self_healing_daemon

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = "Visit [Worcester](/wˈʊstər/). [pause:0.4s]"


def _configure(monkeypatch, module, values):
    monkeypatch.setattr(module, "get_config_value", lambda key, default=None: values.get(key, default))


def _script(root, name):
    path = root / "bin" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def _manager(root, mode):
    manager = alert_manager.AlertManager.__new__(alert_manager.AlertManager)
    manager.project_root = root
    manager.mode = mode
    return manager


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("caller", ["reminder", "follow_up", "self_healing", "alert"])
@pytest.mark.parametrize("provider", ["kokoro", "openai"])
def test_native_callers_keep_only_actual_provider_cues(tmp_path, monkeypatch, mode, caller, provider):
    modules = {
        "reminder": reminder_scheduler,
        "follow_up": follow_up_daemon,
        "self_healing": self_healing_daemon,
        "alert": alert_manager,
    }
    module = modules[caller]
    _configure(monkeypatch, module, {"TTS_PROVIDER": provider})
    suffix = "-local" if mode == "local" else ""
    status = caller in {"follow_up", "alert"}
    path = _script(tmp_path, f"say{'-status' if status else ''}{suffix}.sh")
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(module.subprocess, "run", run)

    if caller == "reminder":
        assert module.speak_reminder({"id": 1, "title": SAMPLE}, mode, tmp_path)
    elif caller == "follow_up":
        assert module.speak_follow_up({"id": 1, "title": SAMPLE}, mode, tmp_path)
    elif caller == "self_healing":
        module._speak_message(SAMPLE, tmp_path, mode)
    else:
        assert _manager(tmp_path, mode)._speak(SAMPLE, blocking=True)

    command = run.call_args.args[0]
    assert command[0] == str(path)
    assert "Visit" in command[1]
    if provider == "kokoro":
        assert SAMPLE in command[1]
    else:
        assert "Worcester" in command[1]
        assert "[pause:" not in command[1]
        assert "(/" not in command[1]


@pytest.mark.parametrize("caller", ["follow_up", "alert"])
@pytest.mark.parametrize("status_exists", [True, False])
@pytest.mark.parametrize("final_model,status_model", [
    ("eleven_v4", "eleven_multilingual_v2"),
    ("eleven_multilingual_v2", "eleven_v4"),
])
def test_status_callers_use_actual_status_model_or_final_fallback(
    tmp_path, monkeypatch, caller, status_exists, final_model, status_model,
):
    module = follow_up_daemon if caller == "follow_up" else alert_manager
    _configure(monkeypatch, module, {
        "TTS_PROVIDER": "elevenlabs",
        "ELEVENLABS_TTS_MODEL": final_model,
        "ELEVENLABS_STATUS_TTS_MODEL": status_model,
    })
    path = _script(tmp_path, "say-status.sh" if status_exists else "say.sh")
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(module.subprocess, "run", run)

    if caller == "follow_up":
        assert module.speak_follow_up({"id": 1, "title": "[curious] Check backup"}, "cloud", tmp_path)
    else:
        assert _manager(tmp_path, "cloud")._speak("[curious] Check backup", blocking=True)

    command = run.call_args.args[0]
    assert command[0] == str(path)
    expected_model = status_model if status_exists else final_model
    assert ("[curious]" in command[1]) is (expected_model == "eleven_v4")


def test_weather_profile_keeps_selected_cues_while_removing_dates(tmp_path, monkeypatch):
    _configure(monkeypatch, alert_manager, {"TTS_PROVIDER": "kokoro"})
    _script(tmp_path, "say-status.sh")
    message = _manager(tmp_path, "cloud")._sanitize_weather_watch_speech(
        f"Fri 2026-04-03. {SAMPLE} 34°F."
    )
    assert "2026-04-03" not in message
    assert SAMPLE in message
    assert "34 degrees" in message


def test_weather_truncation_does_not_send_partial_pronunciation(tmp_path, monkeypatch):
    _configure(monkeypatch, alert_manager, {"TTS_PROVIDER": "kokoro"})
    _script(tmp_path, "say-status.sh")
    manager = _manager(tmp_path, "cloud")
    speak = Mock(return_value=False)
    manager._speak = speak
    detail = "Clear " * 33 + "[New York](/njuː jɔːk/)" + " next. " * 10

    assert manager._speak_alert(1, "Forecast", "high", detail, "weather_watch") is False

    message = speak.call_args.args[0]
    assert message.endswith("...")
    assert "[New York]" not in message or "[New York](/njuː jɔːk/)" in message
    assert len(message.removeprefix("Boss, Urgent alert: Forecast. ")) <= 220


@pytest.mark.parametrize("script_name,provider", [
    ("wake-jarvis.py", "kokoro"),
    ("wake-jarvis-local.py", "kokoro"),
    ("wake-jarvis.py", "openai"),
    ("wake-jarvis-local.py", None),
])
def test_wake_greeting_normalizes_using_effective_provider(script_name, provider):
    # Execute the real handler without importing hardware setup or starting a mic.
    path = ROOT / "bin" / script_name
    tree = ast.parse(path.read_text())
    handler = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "handle_trigger")
    run = Mock(return_value=SimpleNamespace(returncode=0))
    values = {"WAKE_GREETINGS": SAMPLE}
    if provider is not None:
        values["TTS_PROVIDER"] = provider
    namespace = {
        "get_config_value": lambda key, default=None: values.get(key, default),
        "normalize_tts_text": normalize_tts_text,
        "configured_speech_tag_options": configured_speech_tag_options,
        "subprocess": SimpleNamespace(run=run),
        "run_question_with_head_keepalive": lambda _command: SimpleNamespace(returncode=20),
        "stop_stream": lambda: None,
        "emit_head_event": lambda _event: None,
        "SAY": "test-say-script",
        "ASK": "test-question-script",
        "sys": sys,
    }
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(path), "exec"), namespace)

    assert namespace["handle_trigger"]() is False

    speech = run.call_args.args[0][1]
    assert speech == ("Visit Worcester." if provider == "openai" else SAMPLE)
