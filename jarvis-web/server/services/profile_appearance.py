"""Shared display identity for the Web profile and browser companion."""

import base64
import io
import json
import os
import tempfile
import threading
import unicodedata
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import JARVIS_ROOT

PROFILE_PATH = JARVIS_ROOT / 'data' / 'web_profile_appearance.json'
MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000
DEFAULT_NAME = 'Administrator'
_lock = threading.RLock()


def get_profile_appearance():
    """Read a mode-independent identity; a missing file retains the defaults."""
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'display_name': DEFAULT_NAME, 'avatar': None}
    if not isinstance(data, dict) or not isinstance(data.get('display_name'), str):
        raise ValueError('Stored profile appearance is invalid.')
    return {'display_name': data['display_name'], 'avatar': data.get('avatar')}


def _avatar_data(upload):
    raw = upload.stream.read(MAX_AVATAR_BYTES + 1)
    if len(raw) > MAX_AVATAR_BYTES:
        raise ValueError('Choose an image smaller than 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {'PNG', 'JPEG', 'WEBP'}:
                    raise ValueError('Choose a PNG, JPEG, or WebP image.')
                if source.width * source.height > MAX_AVATAR_PIXELS:
                    raise ValueError('Choose an image with at most 16 million pixels.')
                source.load()
                oriented = ImageOps.exif_transpose(source)
                resized = ImageOps.fit(oriented.convert('RGBA'), (256, 256), method=Image.Resampling.LANCZOS)
                # A new raster drops EXIF, text chunks and all original metadata.
                clean = Image.new('RGBA', resized.size)
                clean.paste(resized)
                output = io.BytesIO()
                clean.save(output, format='PNG')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError('This image could not be read. Choose a PNG, JPEG, or WebP image.') from exc
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')


def save_profile_appearance(display_name, *, avatar=None, remove_avatar=False):
    """Validate before atomically replacing the single saved display profile."""
    if not isinstance(display_name, str):
        raise ValueError('Enter a display name.')
    name = display_name.strip() or DEFAULT_NAME
    if len(name) > 80 or any(unicodedata.category(char).startswith('C') for char in name):
        raise ValueError('Use a display name of at most 80 characters without control characters.')
    if avatar is not None and remove_avatar:
        raise ValueError('Choose an image or restore the default, not both.')
    encoded = _avatar_data(avatar) if avatar is not None else None
    with _lock:
        current = get_profile_appearance()
        saved = {
            'display_name': name,
            'avatar': encoded if avatar is not None else None if remove_avatar else current['avatar'],
        }
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=PROFILE_PATH.parent,
                                             prefix='.web-profile-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(saved, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, PROFILE_PATH)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return saved
