"""Shared helpers for multi-image vision requests (web UI + analyze_image tool)."""

from __future__ import annotations

MAX_VISION_IMAGES_CLOUD = 6
MAX_VISION_IMAGES_LOCAL = 2


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
