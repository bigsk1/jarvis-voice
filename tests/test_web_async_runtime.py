"""Regression coverage for the non-monkey-patched Jarvis Web runtime."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def test_web_uses_threading_socketio_without_eventlet_monkey_patch():
    app_source = (PROJECT_ROOT / "jarvis-web/server/app.py").read_text()
    launcher_source = (PROJECT_ROOT / "bin/jarvis-web").read_text()

    assert "async_mode='threading'" in app_source
    assert "allow_unsafe_werkzeug=True" in app_source
    assert "eventlet.monkey_patch" not in app_source
    assert "eventlet.monkey_patch" not in launcher_source
    assert "pip install eventlet" not in launcher_source


def test_eventlet_is_not_a_direct_project_dependency():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()
    requirements = (PROJECT_ROOT / "requirements.txt").read_text()
    web_requirements = (PROJECT_ROOT / "jarvis-web/requirements.txt").read_text()

    assert '"eventlet' not in pyproject
    assert "\neventlet" not in requirements
    assert "\neventlet" not in web_requirements
    assert "simple-websocket>=1.0.0" in pyproject
    assert "simple-websocket>=1.0.0" in requirements
    assert "simple-websocket>=1.0.0" in web_requirements
