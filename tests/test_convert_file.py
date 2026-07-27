"""Convert-file media codec regressions."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "skills" / "convert_file.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("convert_file_tool", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_video_to_ogg_extraction_uses_vorbis(monkeypatch, tmp_path):
    module = _load_module()
    captured = {}

    monkeypatch.setattr(module, "check_tool", lambda tool_name: tool_name == "ffmpeg")

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.extract_audio_from_video(
        str(tmp_path / "input.mp4"),
        str(tmp_path / "output.ogg"),
    )

    assert captured["command"] == [
        "ffmpeg",
        "-y",
        "-i",
        str(tmp_path / "input.mp4"),
        "-vn",
        "-c:a",
        "libvorbis",
        str(tmp_path / "output.ogg"),
    ]
