"""Convert-file media codec regressions."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize('background', [False, True])
@pytest.mark.parametrize('method,defaults', [
    ('convert_image_to_image', [120]), ('convert_raster_to_svg', [60,120]),
    ('convert_video', [600]), ('convert_audio', [300]),
    ('extract_audio_from_video', [300]), ('get_media_info', [30]),
])
def test_each_conversion_stage_shares_background_deadline_or_keeps_foreground_wait(
        monkeypatch, tmp_path, background, method, defaults):
    module = _load_module()
    now, timeouts = [1000.0], []
    monkeypatch.setattr(module, 'time', SimpleNamespace(time=lambda:now[0]))
    monkeypatch.setattr(module, 'check_tool', lambda name:True)
    if background:
        monkeypatch.setenv('JARVIS_BACKGROUND_DEADLINE', '1900')
    else:
        monkeypatch.delenv('JARVIS_BACKGROUND_DEADLINE', raising=False)
    def run(command, **kwargs):
        timeouts.append(kwargs['timeout'])
        now[0] += 40
        return SimpleNamespace(returncode=0, stdout='{}', stderr='')
    monkeypatch.setattr(module.subprocess, 'run', run)
    args = [str(tmp_path/'input.png')]
    if method != 'get_media_info':
        args.append(str(tmp_path/'output.flac'))
    getattr(module,method)(*args)
    assert timeouts == ([900-40*index for index in range(len(defaults))] if background else defaults)


@pytest.mark.parametrize('deadline', ['1000', '999', 'nan', 'inf'])
def test_expired_or_invalid_background_deadline_prevents_launch(monkeypatch, deadline):
    module = _load_module()
    monkeypatch.setattr(module, 'time', SimpleNamespace(time=lambda:1000))
    monkeypatch.setenv('JARVIS_BACKGROUND_DEADLINE', deadline)
    monkeypatch.setattr(module, 'check_tool', lambda name:True)
    def never_run(*args, **kwargs):
        pytest.fail('Expired background execution must not launch another stage')
    monkeypatch.setattr(module.subprocess, 'run', never_run)
    with pytest.raises(TimeoutError):
        module.convert_video('input.mp4', 'output.mp4')
