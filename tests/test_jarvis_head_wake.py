"""Behavioral Phase 4 tests for wake/head state cleanup."""

from __future__ import annotations

import importlib.util
import sys
import threading
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _Result:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def _load_wake_module(monkeypatch, script_name: str):
    config_loader = types.ModuleType("config_loader")
    config_loader.load_config = lambda _mode=None: {}
    config_loader.get_config_value = lambda _key, default=None: default
    config_loader.get_int = lambda _key, default=0: default
    config_loader.get_float = lambda _key, default=0.0: default

    head_events = types.ModuleType("head_events")
    head_events.emit = lambda _event: False

    sounddevice = types.ModuleType("sounddevice")
    sounddevice.query_devices = lambda: [{"name": "Test microphone", "max_input_channels": 1}]
    sounddevice.default = types.SimpleNamespace(device=(0, 0))
    sounddevice.InputStream = lambda **_kwargs: types.SimpleNamespace(
        start=lambda: None,
        stop=lambda: None,
        close=lambda: None,
    )

    openwakeword = types.ModuleType("openwakeword")
    openwakeword.__path__ = []
    openwakeword_model = types.ModuleType("openwakeword.model")
    openwakeword_model.Model = lambda **_kwargs: types.SimpleNamespace(
        models={},
        predict=lambda _audio: {},
    )

    tool_schema = types.ModuleType("tool_schema")

    class EmptyToolRegistry:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def list_tools(self) -> list[str]:
            return []

    tool_schema.ToolRegistry = EmptyToolRegistry

    model_catalog = types.ModuleType("model_catalog")
    model_catalog.get_provider_fallback_model = lambda provider: f"{provider}-test"
    tts_normalizer = types.ModuleType("tts_normalizer")
    tts_normalizer.normalize_tts_text = lambda text: text

    stubs = {
        "config_loader": config_loader,
        "head_events": head_events,
        "sounddevice": sounddevice,
        "openwakeword": openwakeword,
        "openwakeword.model": openwakeword_model,
        "tool_schema": tool_schema,
        "model_catalog": model_catalog,
        "tts_normalizer": tts_normalizer,
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)

    module_name = f"test_{script_name.replace('-', '_').replace('.', '_')}"
    script_path = PROJECT_ROOT / "bin" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script_name", ["wake-jarvis.py", "wake-jarvis-local.py"])
def test_normal_rearm_emits_listen_then_sleep(monkeypatch, script_name):
    wake = _load_wake_module(monkeypatch, script_name)
    steps: list[str] = []
    wake.emit_head_event = lambda event: steps.append(event)
    wake.stop_stream = lambda: steps.append("stop_stream")
    wake.start_stream = lambda: steps.append("start_stream")
    monkeypatch.setattr(wake.time, "sleep", lambda _seconds: None)

    def fake_run(command, **_kwargs):
        steps.append("say" if command[0] == wake.SAY else "ask")
        return _Result(0)

    monkeypatch.setattr(wake.subprocess, "run", fake_run)

    assert wake.handle_trigger() is True
    assert steps == ["listen", "stop_stream", "say", "ask", "start_stream", "sleep"]


@pytest.mark.parametrize("script_name", ["wake-jarvis.py", "wake-jarvis-local.py"])
def test_voice_exit_emits_sleep_before_returning(monkeypatch, script_name):
    wake = _load_wake_module(monkeypatch, script_name)
    events: list[str] = []
    wake.emit_head_event = lambda event: events.append(event)
    wake.stop_stream = lambda: None
    wake.start_stream = lambda: pytest.fail("voice exit must not re-arm the stream")

    def fake_run(command, **_kwargs):
        return _Result(0 if command[0] == wake.SAY else 20)

    monkeypatch.setattr(wake.subprocess, "run", fake_run)

    assert wake.handle_trigger() is False
    assert events == ["listen", "sleep"]


@pytest.mark.parametrize("script_name", ["wake-jarvis.py", "wake-jarvis-local.py"])
def test_question_exception_rearms_and_leaves_head_asleep(monkeypatch, script_name):
    wake = _load_wake_module(monkeypatch, script_name)
    events: list[str] = []
    rearmed: list[bool] = []
    wake.emit_head_event = lambda event: events.append(event)
    wake.stop_stream = lambda: None
    wake.start_stream = lambda: rearmed.append(True)
    monkeypatch.setattr(wake.time, "sleep", lambda _seconds: None)

    def fake_run(command, **_kwargs):
        if command[0] == wake.SAY:
            return _Result(0)
        raise OSError("question process unavailable")

    monkeypatch.setattr(wake.subprocess, "run", fake_run)

    assert wake.handle_trigger() is True
    assert rearmed == [True]
    assert events == ["listen", "sleep"]


@pytest.mark.parametrize("script_name", ["wake-jarvis.py", "wake-jarvis-local.py"])
def test_long_question_renews_listen_until_process_returns(monkeypatch, script_name):
    wake = _load_wake_module(monkeypatch, script_name)
    events: list[str] = []
    heartbeat_seen = threading.Event()

    def record_event(event):
        events.append(event)
        if events.count("listen") >= 2:
            heartbeat_seen.set()

    wake.emit_head_event = record_event
    wake.stop_stream = lambda: None
    wake.start_stream = lambda: None
    monkeypatch.setattr(wake, "HEAD_QA_KEEPALIVE_INTERVAL", 0.01)
    monkeypatch.setattr(wake, "COOLDOWN_AFTER_QA", 0)

    def fake_run(command, **_kwargs):
        if command[0] == wake.SAY:
            return _Result(0)
        assert heartbeat_seen.wait(0.5), "Q&A head keepalive never fired"
        return _Result(0)

    monkeypatch.setattr(wake.subprocess, "run", fake_run)

    assert wake.handle_trigger() is True
    assert events.count("listen") >= 2
    assert events[-1] == "sleep"


@pytest.mark.parametrize("script_name", ["wake-jarvis.py", "wake-jarvis-local.py"])
def test_ctrl_c_runs_stream_and_head_cleanup(monkeypatch, script_name):
    wake = _load_wake_module(monkeypatch, script_name)
    steps: list[str] = []
    wake.start_stream = lambda: steps.append("start_stream")
    wake.stop_stream = lambda: steps.append("stop_stream")
    wake.emit_head_event = lambda event: steps.append(event)
    wake.trigger_evt = types.SimpleNamespace(
        wait=lambda **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
        clear=lambda: None,
    )

    wake.main()

    assert steps == ["start_stream", "stop_stream", "sleep"]


@pytest.mark.parametrize("script_name", ["wake-jarvis.py", "wake-jarvis-local.py"])
def test_startup_exception_still_runs_head_cleanup(monkeypatch, script_name):
    wake = _load_wake_module(monkeypatch, script_name)
    steps: list[str] = []
    wake.start_stream = lambda: (_ for _ in ()).throw(RuntimeError("no microphone"))
    wake.stop_stream = lambda: steps.append("stop_stream")
    wake.emit_head_event = lambda event: steps.append(event)

    with pytest.raises(RuntimeError, match="no microphone"):
        wake.main()

    assert steps == ["stop_stream", "sleep"]
