"""Shared helpers for multi-image vision requests (web UI + analyze_image tool)."""

from __future__ import annotations

import base64
import io
from typing import Literal, TypedDict

MAX_VISION_IMAGES_CLOUD = 6
MAX_VISION_IMAGES_LOCAL = 2
MAX_GIF_VISION_FRAMES = 6


class GifVisionScope(TypedDict):
    image_index: int
    vision_scope: Literal['sampled_frames', 'selected_frame', 'single_frame']
    frame_count: int
    frame_indices: list[int]
    timestamps_ms: list[int]
    duration_ms: int
    gif_frame: int | None
    transparency_background: str | None


def gif_vision_frame_indices(frame_count: int, gif_frame: int | None = None) -> list[int]:
    """Choose a selected frame or bounded chronological samples including both ends."""
    if gif_frame is not None:
        if isinstance(gif_frame, bool) or not isinstance(gif_frame, int) or gif_frame < 0:
            raise ValueError('gif_frame must be a zero-based non-negative integer')
        if gif_frame >= frame_count:
            raise ValueError(f'gif_frame {gif_frame} is outside this GIF ({frame_count} frames)')
        return [gif_frame]
    count = min(frame_count, MAX_GIF_VISION_FRAMES)
    if count <= 1:
        return [0]
    return [round(index * (frame_count - 1) / (count - 1)) for index in range(count)]


def describe_gif_vision_scope(scope: GifVisionScope) -> str:
    """Describe exactly which source frames the provider can inspect."""
    labels = ', '.join(
        f'{frame} at {timestamp} ms'
        for frame, timestamp in zip(scope['frame_indices'], scope['timestamps_ms'], strict=True)
    )
    prefix = f"GIF analysis scope (image {scope['image_index'] + 1}): "
    if scope['vision_scope'] == 'single_frame':
        detail = 'this GIF contains one frame, shown as frame 0 at 0 ms.'
    elif scope['vision_scope'] == 'selected_frame':
        detail = (
            f'only selected frame {labels} of {scope["frame_count"]} frames is shown; '
            'other frames and continuous motion were not inspected.'
        )
    else:
        detail = (
            f'{len(scope["frame_indices"])} chronological sampled frames '
            f'of {scope["frame_count"]} are shown ({labels}). '
            'This contact sheet supports comparison of sampled states, '
            'not complete continuous-motion analysis.'
        )
    if scope['transparency_background']:
        detail += (
            ' Transparent pixels are displayed on a neutral checkerboard; '
            'the checkerboard is a rendering aid, not image content or an original background.'
        )
    return prefix + detail


def normalize_vision_gif_images(
    images_base64: list[str], *, gif_frame: int | None = None,
) -> tuple[list[str], list[GifVisionScope]]:
    """Render one bounded contact sheet per GIF while retaining original bytes."""
    normalized = []
    scopes: list[GifVisionScope] = []
    gif_inputs = [encoded.startswith(('R0lGODdh', 'R0lGODlh')) for encoded in images_base64]
    if gif_frame is not None and (len(images_base64) != 1 or not all(gif_inputs)):
        raise ValueError('gif_frame requires exactly one GIF source image')
    for index, encoded in enumerate(images_base64):
        # Other callers already supply normalized still images. Leave those
        # payloads unchanged, including their historical test/adapter contracts.
        if not encoded.startswith(('R0lGODdh', 'R0lGODlh')):
            normalized.append(encoded)
            continue

        from PIL import Image, ImageDraw
        from stash_helper import GIF_MAX_FILE_SIZE, SecurityError, inspect_gif_image

        max_bytes = GIF_MAX_FILE_SIZE
        if len(encoded) > 4 * ((max_bytes + 2) // 3):
            raise SecurityError('GIF exceeds the 30 MiB vision input safety limit')
        data = base64.b64decode(encoded, validate=True)
        metadata = inspect_gif_image(data)
        frame_indices = gif_vision_frame_indices(metadata['frame_count'], gif_frame)
        frames = []
        timestamps = []
        has_transparency = False
        with Image.open(io.BytesIO(data)) as animation:
            timestamp = 0
            for frame_index in range(metadata['frame_count']):
                animation.seek(frame_index)
                if frame_index in frame_indices:
                    frame = animation.convert('RGBA')
                    thumbnail_size = (1000, 970) if len(frame_indices) == 1 else (320, 320)
                    frame.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
                    alpha = frame.getchannel('A')
                    transparent = alpha.getextrema()[0] < 255
                    has_transparency = has_transparency or transparent
                    background = Image.new('RGB', frame.size, (144, 144, 144))
                    if transparent:
                        checker = ImageDraw.Draw(background)
                        for y in range(0, frame.height, 12):
                            for x in range(0, frame.width, 12):
                                if (x // 12 + y // 12) % 2:
                                    checker.rectangle((x, y, x + 11, y + 11), fill=(184, 184, 184))
                    background.paste(frame, mask=alpha)
                    frames.append(background)
                    timestamps.append(timestamp)
                timestamp += max(0, int(animation.info.get('duration') or 0))

        columns = min(3, len(frames))
        rows = (len(frames) + columns - 1) // columns
        cell_width = max(200, max(frame.width for frame in frames)) + 12
        cell_height = max(frame.height for frame in frames) + 30
        sheet = Image.new('RGB', (columns * cell_width, rows * cell_height), (40, 40, 40))
        drawing = ImageDraw.Draw(sheet)
        for position, frame in enumerate(frames):
            x = position % columns * cell_width
            y = position // columns * cell_height
            drawing.text((x + 6, y + 5), f'Frame {frame_indices[position]} @ {timestamps[position]} ms', fill='white')
            sheet.paste(frame, (x + 6, y + 24))
        output = io.BytesIO()
        sheet.save(output, 'JPEG', quality=85)
        normalized.append(base64.b64encode(output.getvalue()).decode('ascii'))
        scopes.append({
            'image_index': index,
            'vision_scope': (
                'single_frame' if metadata['frame_count'] == 1
                else 'selected_frame' if gif_frame is not None else 'sampled_frames'
            ),
            'frame_count': metadata['frame_count'],
            'frame_indices': frame_indices,
            'timestamps_ms': timestamps,
            'duration_ms': metadata['duration_ms'],
            'gif_frame': gif_frame,
            'transparency_background': 'checkerboard' if has_transparency else None,
        })
    return normalized, scopes


def max_vision_images(mode: str) -> int:
    return MAX_VISION_IMAGES_LOCAL if mode == 'local' else MAX_VISION_IMAGES_CLOUD


def normalize_web_image_payload(image_data: dict | None) -> dict | None:
    """
    Normalize web UI socket payload to {action, settings, images: [{base64?, url, filename}, ...]}.
    Accepts legacy single-image shape for backward compatibility.
    """
    if not image_data or not isinstance(image_data, dict):
        return None

    if image_data.get('images'):
        images = [
            img for img in image_data['images']
            if isinstance(img, dict) and (img.get('base64') or img.get('filename') or img.get('url'))
        ]
    elif image_data.get('base64') or image_data.get('filename') or image_data.get('url'):
        images = [{
            'base64': image_data.get('base64'),
            'url': image_data.get('url'),
            'filename': image_data.get('filename'),
        }]
    else:
        return None

    if not images:
        return None

    return {
        'action': image_data.get('action', 'analyze'),
        'settings': image_data.get('settings') or {},
        'images': images,
    }


def build_ollama_prompt(prompt: str, num_images: int) -> str:
    """Label images in the prompt so local models can disambiguate."""
    if num_images <= 1:
        return prompt
    labels = '\n'.join(f'Image {index + 1}:' for index in range(num_images))
    return f'{labels}\n\n{prompt}'


def build_anthropic_content(images_base64: list[str], prompt: str) -> list[dict]:
    content: list[dict] = []
    for index, image_base64 in enumerate(images_base64):
        if len(images_base64) > 1:
            content.append({'type': 'text', 'text': f'Image {index + 1}:'})
        content.append({
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': 'image/jpeg',
                'data': image_base64,
            },
        })
    content.append({'type': 'text', 'text': prompt})
    return content


def build_openai_style_content(
    images_base64: list[str],
    prompt: str,
    detail: str = 'high',
) -> list[dict]:
    content: list[dict] = []
    for image_base64 in images_base64:
        content.append({
            'type': 'image_url',
            'image_url': {
                'url': f'data:image/jpeg;base64,{image_base64}',
                'detail': detail,
            },
        })
    content.append({'type': 'text', 'text': prompt})
    return content


def openai_model_supports_original_detail(model: str | None) -> bool:
    """Return true when OpenAI `detail=original` is supported by the selected model."""
    lowered = str(model or '').strip().lower()
    if any(marker in lowered for marker in ('mini', 'nano', 'codex')):
        return False
    return lowered.startswith(('gpt-5.4', 'gpt-5.5'))


def openai_vision_detail(
    model: str | None,
    configured_detail: str | None,
    log_fn=None,
) -> str:
    """Return an OpenAI-supported image detail value for the selected model."""
    detail = str(configured_detail or 'high').strip().lower()
    if detail in ('low', 'high', 'auto'):
        return detail
    if detail == 'original' and openai_model_supports_original_detail(model):
        return detail
    if detail == 'original' and log_fn:
        log_fn(f"OpenAI model {model} does not support VISION_DETAIL=original; using high")
    return 'high'
