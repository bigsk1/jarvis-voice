"""Convert-file media codec regressions."""

import importlib.util
import json
import shutil
import sys
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


@pytest.fixture
def background_image(tmp_path):
    from PIL import Image, ImageDraw
    if not (shutil.which('convert') or shutil.which('magick')):
        pytest.skip('ImageMagick is optional')
    image = Image.new('RGB', (80, 64), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 12, 65, 55), fill='black')
    draw.rectangle((30, 22, 45, 40), fill='white')
    source = tmp_path / 'source.jpg'
    image.save(source, quality=95)
    return source


@pytest.mark.parametrize('extension', ['png', 'webp'])
def test_real_solid_removal_keeps_enclosed_white_and_source_bytes(background_image, tmp_path, extension):
    from PIL import Image
    module = _load_module()
    original = background_image.read_bytes()
    output = tmp_path / ('cutout.' + extension)
    info = module.convert_image_to_image(str(background_image), str(output), {'remove_background': True})
    with Image.open(output) as image:
        pixels = image.convert('RGBA')
        assert image.size == (80, 64)
        assert pixels.getpixel((0, 0))[3] == 0
        assert pixels.getpixel((35, 30))[3] == 255
        assert min(pixels.getpixel((35, 30))[:3]) > 240
        assert pixels.getpixel((55, 30))[3] == 255
    assert info['method'] == 'edge_connected_color' and info['background_removed']
    assert info['transparent_pixels'] > 0 and info['visible_pixels'] > 0
    assert background_image.read_bytes() == original


def test_border_padding_removes_mid_edge_region_without_erasing_corner_foreground(tmp_path):
    from PIL import Image, ImageDraw
    module = _load_module()
    if not (shutil.which('convert') or shutil.which('magick')):
        pytest.skip('ImageMagick is optional')
    source, output = tmp_path / 'source.png', tmp_path / 'output.png'
    image = Image.new('RGB', (48, 48), 'black')
    ImageDraw.Draw(image).rectangle((0, 18, 12, 30), fill='white')
    image.save(source)
    module.convert_image_to_image(str(source), str(output), {'remove_background': True, 'background_color': '#ffffff'})
    with Image.open(output) as result:
        assert result.getpixel((0, 0))[3] == 255
        assert result.getpixel((2, 24))[3] == 0


def test_removal_preserves_existing_partial_alpha_and_validates_resize(tmp_path, background_image):
    from PIL import Image, ImageDraw
    module = _load_module()
    source, output = tmp_path / 'alpha.png', tmp_path / 'cutout.png'
    image = Image.new('RGBA', (48, 48), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 35, 35), fill=(0, 0, 200, 255))
    draw.rectangle((18, 18, 26, 26), fill=(220, 0, 0, 128))
    image.save(source)
    module.convert_image_to_image(str(source), str(output), {'remove_background': True})
    with Image.open(output) as result:
        assert result.getpixel((22, 22))[3] == 128
        assert result.getpixel((0, 0))[3] == 0
    info = module.convert_image_to_image(str(background_image), str(output), {'remove_background': True, 'resize': '50%'})
    assert (info['width'], info['height']) == (40, 32)
    for resize in ('100000x100000', '100000%', '0%', '@/etc/passwd'):
        with pytest.raises(ValueError, match='resize'):
            module.convert_image_to_image(str(source), str(output), {'remove_background': True, 'resize': resize})


@pytest.mark.parametrize('options,target', [
    ({'remove_background': True}, 'jpg'), ({'remove_background': 'true'}, 'png'),
    ({'remove_background': True, 'background_color': '@file'}, 'png'),
    ({'remove_background': True, 'background_tolerance': float('nan')}, 'png'),
    ({'remove_background': True, 'background_tolerance': True}, 'png'),
    ({'remove_background': True, 'background_tolerance': 26}, 'png'),
    ({'background_color': '#ffffff'}, 'png'),
])
def test_invalid_removal_settings_fail_before_launch(monkeypatch, tmp_path, options, target):
    module = _load_module()
    monkeypatch.setattr(module, 'check_tool', lambda _: True)
    monkeypatch.setattr(module.subprocess, 'run', lambda *_args, **_kwargs: pytest.fail('Invalid options launched a converter'))
    with pytest.raises(ValueError):
        module.convert_image_to_image('missing.png', str(tmp_path / ('out.' + target)), options)


def test_no_match_and_erased_subject_are_failures_not_successful_exports(tmp_path, background_image):
    from PIL import Image
    module = _load_module()
    with pytest.raises(RuntimeError, match='No new edge-connected'):
        module.convert_image_to_image(str(background_image), str(tmp_path / 'out.png'), {
            'remove_background': True, 'background_color': '#ff0000', 'background_tolerance': 0})
    plain = tmp_path / 'plain.png'
    Image.new('RGB', (32, 32), 'white').save(plain)
    with pytest.raises(RuntimeError, match='entire image'):
        module.convert_image_to_image(str(plain), str(tmp_path / 'blank.png'), {'remove_background': True})


def test_auto_rejects_different_corners_before_launch(tmp_path, background_image, monkeypatch):
    from PIL import Image, ImageDraw
    module = _load_module()
    image = Image.new('RGB', (32, 32), 'red')
    ImageDraw.Draw(image).rectangle((16, 0, 31, 31), fill='blue')
    source = tmp_path / 'different.png'
    image.save(source)
    monkeypatch.setattr(module.subprocess, 'run', lambda *_a, **_k: pytest.fail('Ambiguous corners launched removal'))
    with pytest.raises(ValueError, match='Corner colors differ'):
        module.convert_image_to_image(str(source), str(tmp_path / 'out.png'), {'remove_background': True})


@pytest.mark.parametrize('case', ['oversized', 'animated'])
def test_removal_rejects_large_or_multiframe_sources_before_converter_launch(monkeypatch, tmp_path, case):
    from PIL import Image
    module = _load_module()
    source = tmp_path / 'source.gif'
    if case == 'oversized':
        Image.new('L', (8000, 4001), 255).save(source, format='PNG')
        expected = '32 megapixels'
    else:
        Image.new('RGB', (16, 16), 'white').save(source, save_all=True,
            append_images=[Image.new('RGB', (16, 16), 'black')])
        expected = 'single-frame'
    monkeypatch.setattr(module.subprocess, 'run', lambda *_a, **_k: pytest.fail('Rejected image launched converter'))
    with pytest.raises(ValueError, match=expected):
        module.convert_image_to_image(str(source), str(tmp_path / 'out.png'), {'remove_background': True})


def test_existing_alpha_without_new_removal_is_not_reported_as_success(tmp_path, background_image):
    from PIL import Image, ImageDraw
    module = _load_module()
    source = tmp_path / 'existing.png'
    image = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((8, 8, 23, 23), fill='black')
    image.save(source)
    with pytest.raises(RuntimeError, match='No new edge-connected'):
        module.convert_image_to_image(str(source), str(tmp_path / 'out.png'), {
            'remove_background': True, 'background_color': '#ffffff', 'background_tolerance': 0})


def test_restricted_child_tilde_source_uses_account_home_not_scratch_home(monkeypatch, tmp_path):
    import os
    if os.name != 'posix':
        pytest.skip('POSIX account home lookup')
    import pwd
    module = _load_module()
    actual_home = tmp_path / 'operator-home'
    actual_home.mkdir()
    source = actual_home / 'source.png'
    source.write_bytes(b'image')
    monkeypatch.setenv(module.RESTRICTED_ENV_MARKER, '1')
    monkeypatch.setenv('HOME', str(tmp_path / 'scratch'))
    monkeypatch.setattr(pwd, 'getpwuid', lambda _: SimpleNamespace(pw_dir=str(actual_home)))
    path, _ = module.resolve_source('~/source.png')
    assert path == str(source)
    assert os.environ['HOME'] == str(tmp_path / 'scratch')


def test_new_removal_stage_uses_existing_background_deadline(background_image, tmp_path, monkeypatch):
    module = _load_module()
    original_run = module.subprocess.run
    timeouts = []
    monkeypatch.setenv('JARVIS_BACKGROUND_DEADLINE', str(module.time.time() + 50))
    def capture(command, **kwargs):
        timeouts.append(kwargs['timeout'])
        return original_run(command, **kwargs)
    monkeypatch.setattr(module.subprocess, 'run', capture)
    module.convert_image_to_image(str(background_image), str(tmp_path / 'out.png'), {'remove_background': True})
    assert len(timeouts) == 1 and 0 < timeouts[0] <= 50


def test_main_rejects_incompatible_format_before_any_stash_save(monkeypatch, capsys):
    module = _load_module()
    monkeypatch.setattr(module, 'load_config', lambda: None)
    monkeypatch.setattr(module, 'open_space', lambda *_a, **_k: pytest.fail('Invalid target created Stash'))
    monkeypatch.setattr(module, 'resolve_source', lambda *_a: pytest.fail('Invalid target resolved source'))
    monkeypatch.setattr(sys, 'argv', ['convert_file', json.dumps({
        'source': 'stash://uploads/input', 'target_format': 'jpg', 'options': {'remove_background': True}})])
    with pytest.raises(SystemExit):
        module.main()
    result = json.loads(capsys.readouterr().out)
    assert not result['ok'] and 'JPEG cannot store transparency' in result['error']


def test_restricted_env_preserves_stash_policy_without_provider_secrets():
    from tool_child_environment import parse_child_environment_policy, restrict_child_environment

    from lib.background_tasks import production
    from lib.background_tasks.local_skill import restrict_child_environment as background_env
    manifest = json.loads((PROJECT_ROOT / 'skills/convert_file.tool.json').read_text())
    names = parse_child_environment_policy(manifest['child_environment'])
    source = {'STASH_DIR': '/tmp/custom-stash', 'STASH_SOURCE_ARTIFACT_TTL_DAYS': '40',
              'STASH_MAX_SPACE_SIZE_MB': '600', 'OPENAI_API_KEY': 'unrelated',
              'GOOGLE_WORKSPACE_MCP_TOKEN': 'unrelated', 'JARVIS_MODE': 'local',
              'JARVIS_BACKGROUND_DEADLINE': '1000', 'PATH': '/usr/bin'}
    foreground = restrict_child_environment(source, names, home='/tmp/scratch', proxy_policy='off')
    background = background_env(source, production.CHILD_ENVIRONMENT_POLICIES['convert_file'], {}, '/tmp/scratch')
    for env in (foreground, background):
        assert env['STASH_DIR'] == source['STASH_DIR'] and env['STASH_SOURCE_ARTIFACT_TTL_DAYS'] == '40'
        assert 'OPENAI_API_KEY' not in env and 'GOOGLE_WORKSPACE_MCP_TOKEN' not in env
    assert foreground['JARVIS_BACKGROUND_DEADLINE'] == '1000'
