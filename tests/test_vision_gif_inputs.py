"""GIF analysis sees bounded chronological samples or an explicit selected frame."""

import base64
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills'))

import analyze_image
import memory_db
import stash_helper
import vision_provider
from stash_helper import SecurityError
from vision_multimodal import gif_vision_frame_indices, normalize_vision_gif_images


def _animation() -> bytes:
    frames = [Image.new('RGB', (1600, 800), color) for color in ('red', 'blue')]
    output = io.BytesIO()
    frames[0].save(output, 'GIF', save_all=True, append_images=frames[1:], duration=100)
    return output.getvalue()


@pytest.mark.parametrize('provider,adapter', [
    ('ollama', '_ollama_vision'),
    ('anthropic', '_anthropic_vision'),
    ('openai', '_openai_compatible_vision'),
    ('xai', '_openai_compatible_vision'),
])
def test_gif_vision_dispatch_sees_later_frames_and_appends_scope(monkeypatch, provider, adapter):
    original = _animation()
    encoded = base64.b64encode(original).decode('ascii')
    captured = []

    def analyze(*args):
        captured.append(args)
        return 'A red frame.'

    monkeypatch.setattr(vision_provider, adapter, analyze)
    scopes = []
    result = vision_provider.analyze_images(
        ['existing-jpeg', encoded], 'Describe the images.', mode='cloud', provider=provider,
        gif_scope_out=scopes,
    )
    args = captured[0]
    images, prompt = (args[1], args[2]) if provider in {'openai', 'xai'} else args[:2]
    assert images[0] == 'existing-jpeg'
    assert images[1] != encoded
    with Image.open(io.BytesIO(base64.b64decode(images[1]))) as frame:
        assert frame.format == 'JPEG'
        assert max(frame.size) <= 1024
        red, _, blue = frame.getpixel((16, 40))
        assert red > 200 and blue < 30
        red, _, blue = frame.getpixel((348, 40))
        assert blue > 200 and red < 30
    assert 'image 2' in prompt
    assert '0 at 0 ms, 1 at 100 ms' in prompt
    assert result.startswith('A red frame.')
    assert 'GIF analysis scope (image 2):' in result
    assert 'not complete continuous-motion analysis' in result
    assert scopes[0]['vision_scope'] == 'sampled_frames'
    assert scopes[0]['frame_indices'] == [0, 1]
    assert scopes[0]['timestamps_ms'] == [0, 100]
    # Normalization never rewrites the persisted/source input.
    assert base64.b64decode(encoded) == original


def test_gif_vision_normalization_keeps_still_images_unchanged():
    assert normalize_vision_gif_images(['jpeg', 'png']) == (['jpeg', 'png'], [])


@pytest.mark.parametrize('payload,error', [
    # The junk descriptor declares an oversized canvas; reject before decoding.
    (b'GIF89a broken', 'decoded-frame safety limit'),
    (b'GIF89a' + b'\x00' * 7, 'valid GIF'),
])
def test_gif_vision_rejects_invalid_animation_before_provider_call(monkeypatch, payload, error):
    called = []
    monkeypatch.setattr(vision_provider, '_ollama_vision', lambda *_args: called.append(True))
    with pytest.raises(SecurityError, match=error):
        vision_provider.analyze_images(
            [base64.b64encode(payload).decode('ascii')],
            'Describe this GIF.', mode='local',
        )
    assert called == []


def test_gif_scope_does_not_hide_empty_provider_analysis(monkeypatch):
    monkeypatch.setattr(vision_provider, '_ollama_vision', lambda *_args: '')
    assert vision_provider.analyze_images(
        [base64.b64encode(_animation()).decode('ascii')], 'Describe it.', mode='local',
    ) == ''


@pytest.mark.parametrize('source_kind', ['url', 'file', 'stash'])
@pytest.mark.parametrize('gif_frame,expected_indices', [(None, [0, 1]), (1, [1])])
def test_analyze_image_gif_sources_retain_animation_and_sampled_scope(
    tmp_path, monkeypatch, source_kind, gif_frame, expected_indices,
):
    original = _animation()
    source_file = tmp_path / 'original.gif'
    source_file.write_bytes(original)
    source_space = stash_helper.StashSpace('space_gif_source', tmp_path / 'stash')
    source_space.create()
    source_saved = stash_helper.StashFile(source_space).save_binary(
        original, 'original.gif', mime_type='image/gif',
    )
    saved_space = stash_helper.StashSpace('space_gif_saved', tmp_path / 'stash')
    saved_space.create()
    monkeypatch.setattr(stash_helper, 'get_stash_dir', lambda: tmp_path / 'stash')
    monkeypatch.setattr(stash_helper, 'open_space', lambda **_kwargs: (saved_space, False))
    monkeypatch.setattr(stash_helper, 'safe_download', lambda *_args, **_kwargs: (
        original, 'image/gif', 'https://images.example/animation.gif',
    ))
    monkeypatch.setattr(analyze_image, 'resolve_local_file_tool_path', lambda *_a, **_k: source_file)
    monkeypatch.setattr(analyze_image, 'load_config', lambda: None)
    monkeypatch.setattr(analyze_image, 'get_config_value', lambda key, default=None: {
        'JARVIS_MODE': 'cloud', 'ANALYZE_IMAGE_LLM_PROVIDER': 'openai',
    }.get(key, default))
    memories = []
    monkeypatch.setattr(memory_db, 'MemoryDB', lambda: SimpleNamespace(remember=lambda **data: memories.append(data)))
    monkeypatch.setattr(vision_provider, '_openai_compatible_vision', lambda *_a: 'A red frame.')
    source = {
        'url': 'https://images.example/animation.gif',
        'file': str(source_file),
        'stash': f"stash://{source_space.space_id}/{source_saved['file_id']}",
    }[source_kind]

    result = analyze_image.analyze_image(image=source, stash_after=True, gif_frame=gif_frame)

    assert result['ok'] is True
    assert result['data']['mime_type'] == 'image/gif'
    expected_scope = 'sampled_frames' if gif_frame is None else 'selected_frame'
    assert result['data']['gif_vision_scope']['vision_scope'] == expected_scope
    assert result['data']['gif_vision_scope']['frame_indices'] == expected_indices
    assert result['data']['frame_count'] == 2
    assert ('chronological sampled frames' if gif_frame is None else 'only selected frame') in result['data']['analysis']
    assert result['data']['analysis'].startswith('A red frame.')
    assert source_file.read_bytes() == original
    if source_kind == 'url':
        saved = result['data']['stash']
        assert Path(saved['path']).read_bytes() == original
        metadata = saved_space.meta['files'][0]
        assert metadata['mime_type'] == 'image/gif'
        assert metadata['frame_count'] == 2
        assert metadata['gif_vision_scope']['vision_scope'] == expected_scope
        assert 'Analyzed image: A red frame.' in memories[0]['value']
        assert memories[0]['metadata']['gif_vision_scope']['frame_indices'] == expected_indices


def test_contact_sheet_is_bounded_and_samples_last_frame_with_timestamp():
    frames = [Image.new('RGB', (80, 40), (255, index * 7, 0)) for index in range(11)]
    frames.append(Image.new('RGB', (80, 40), 'blue'))
    durations = [20 + index * 10 for index in range(12)]
    output = io.BytesIO()
    frames[0].save(output, 'GIF', save_all=True, append_images=frames[1:], duration=durations)
    encoded = base64.b64encode(output.getvalue()).decode('ascii')
    sheets, scopes = normalize_vision_gif_images([encoded])
    assert len(sheets) == 1
    assert scopes[0]['frame_indices'] == [0, 2, 4, 7, 9, 11]
    assert scopes[0]['timestamps_ms'][-1] == sum(durations[:-1])
    assert scopes[0]['duration_ms'] == sum(durations)
    with Image.open(io.BytesIO(base64.b64decode(sheets[0]))) as sheet:
        assert sheet.format == 'JPEG'
        assert max(sheet.size) <= 1024
        red, _, blue = sheet.getpixel((2 * 212 + 16, 70 + 40))
        assert blue > 200 and red < 30
        # Each cell has a label strip above the actual source frame.
        assert sheet.getpixel((6, 24)) != sheet.getpixel((6, 1))


def test_selected_frame_and_single_frame_gif_have_exact_scope(monkeypatch):
    captured = []
    monkeypatch.setattr(vision_provider, '_ollama_vision', lambda *args: captured.append(args) or 'Blue.')
    scopes = []
    result = vision_provider.analyze_images(
        [base64.b64encode(_animation()).decode('ascii')], 'Describe.', mode='local',
        gif_frame=1, gif_scope_out=scopes,
    )
    assert scopes[0]['vision_scope'] == 'selected_frame'
    assert scopes[0]['frame_indices'] == [1]
    assert scopes[0]['timestamps_ms'] == [100]
    assert result.startswith('Blue.')
    with Image.open(io.BytesIO(base64.b64decode(captured[0][0][0]))) as frame:
        red, _, blue = frame.getpixel((20, 40))
        assert blue > 200 and red < 30
    output = io.BytesIO()
    Image.new('RGB', (12, 12), 'blue').save(output, 'GIF')
    scopes = []
    result = vision_provider.analyze_images(
        [base64.b64encode(output.getvalue()).decode('ascii')], 'Describe.', mode='local',
        gif_scope_out=scopes,
    )
    assert scopes[0]['vision_scope'] == 'single_frame'
    assert 'contains one frame' in result
    assert 'other frames' not in result
    assert 'later frames' not in result


def test_transparent_gif_uses_checkerboard_and_labels_it_as_rendering_aid():
    frame = Image.new('RGBA', (48, 32), (0, 0, 0, 0))
    output = io.BytesIO()
    frame.save(output, 'GIF', transparency=0)
    sheets, scopes = normalize_vision_gif_images([base64.b64encode(output.getvalue()).decode('ascii')])
    assert scopes[0]['transparency_background'] == 'checkerboard'
    with Image.open(io.BytesIO(base64.b64decode(sheets[0]))) as sheet:
        pixel1 = sheet.getpixel((11, 29))
        pixel2 = sheet.getpixel((23, 29))
        assert max(pixel1) < 220 and min(pixel1) > 100
        assert abs(pixel1[0] - pixel2[0]) > 20
    from vision_multimodal import describe_gif_vision_scope

    description = describe_gif_vision_scope(scopes[0])
    assert 'rendering aid' in description
    assert 'not image content or an original background' in description


@pytest.mark.parametrize('frame', [-1, 1.2, True, '1', 2])
def test_selected_gif_frame_rejects_invalid_indices_before_provider(monkeypatch, frame):
    called = []
    monkeypatch.setattr(vision_provider, '_ollama_vision', lambda *_args: called.append(True))
    with pytest.raises(ValueError, match='gif_frame'):
        vision_provider.analyze_images(
            [base64.b64encode(_animation()).decode('ascii')], 'Describe.', mode='local', gif_frame=frame,
        )
    assert called == []


def test_explicit_gif_frame_rejects_mixed_sources_and_sampling_preserves_source_budgets():
    encoded = base64.b64encode(_animation()).decode('ascii')
    with pytest.raises(ValueError, match='exactly one GIF'):
        normalize_vision_gif_images([encoded, 'still-image'], gif_frame=0)
    for count in (2, 6):
        sheets, scopes = normalize_vision_gif_images([encoded] * count)
        assert len(sheets) == count
        assert len(scopes) == count
    assert gif_vision_frame_indices(256) == [0, 51, 102, 153, 204, 255]


def test_gif_url_and_file_inputs_use_shared_30_mib_cap(tmp_path, monkeypatch):
    original = _animation()
    # Valid GIF with trailing bytes crosses the former 20 MiB rejection point
    # without constructing an enormous decoded canvas.
    larger_gif = original + b'\0' * (20 * 1024 * 1024 + 1 - len(original))
    source = tmp_path / 'larger.gif'
    source.write_bytes(larger_gif)
    monkeypatch.setattr(analyze_image, 'resolve_local_file_tool_path', lambda *_a, **_k: source)
    seen_limits = []

    def download(_url, *, max_size):
        seen_limits.append(max_size)
        return larger_gif, 'image/gif', 'https://images.example/larger.gif'

    monkeypatch.setattr(stash_helper, 'safe_download', download)
    for loaded in (
        analyze_image._load_from_file(str(source)),
        analyze_image._load_from_url('https://images.example/larger.gif'),
    ):
        assert loaded is not None
        assert loaded['mime_type'] == 'image/gif'
        assert loaded['size_bytes'] == len(larger_gif)
    assert seen_limits == [stash_helper.GIF_MAX_FILE_SIZE]
    assert stash_helper.GIF_MAX_FILE_SIZE == 30 * 1024 * 1024
