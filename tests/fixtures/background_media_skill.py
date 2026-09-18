"""Test-only bootstrap: actual media CLI/save paths, scripted providers, isolated writes."""

import base64
import importlib.util
import io
import os
import sys
import time
import types
import wave
from pathlib import Path

root = Path(os.environ['FIXTURE_JARVIS_ROOT'])
output = Path(os.environ['FIXTURE_MEDIA_OUTPUT'])
name = Path(__file__).stem
sys.path.insert(0, str(root / 'lib'))
import config_loader

config_loader.get_project_root = lambda: Path(os.environ['FIXTURE_CONFIG_ROOT'])


class NoMemoryWrites:
    def __init__(self, *args, **kwargs):
        raise RuntimeError('Memory writes are disabled in this isolated fixture')


sys.modules['memory_db'] = types.SimpleNamespace(MemoryDB=NoMemoryWrites)
import requests


def no_network(*args, **kwargs):
    raise AssertionError('Real provider/network calls are forbidden in this fixture')


requests.sessions.Session.request = no_network
spec = importlib.util.spec_from_file_location('isolated_media', root / 'skills' / (name + '.py'))
skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill)
output.mkdir(parents=True, exist_ok=True)
skill.PROJECT_ROOT = output
for key in ('GENERATED_IMAGES_DIR', 'GENERATED_VIDEOS_DIR', 'GENERATED_MUSIC_DIR'):
    if hasattr(skill, key):
        setattr(skill, key, output)
for key in ('IMAGE_CATALOG_FILE', 'VIDEO_CATALOG_FILE', 'AUDIO_CATALOG_FILE'):
    if hasattr(skill, key):
        setattr(skill, key, output / (key.lower() + '.json'))

# Video's downloader computes its directory from __file__ inside the function.
skill.__file__ = str(output / 'skills' / (name + '.py'))
(output / 'data').mkdir()


def write_guard(event, args):
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)) and (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)):
            resolved = Path(os.fsdecode(path)).resolve()
            if resolved.is_relative_to(root / 'data') or resolved.is_relative_to(root / 'logs'):
                raise PermissionError('Fixture attempted a live data/log write')


sys.addaudithook(write_guard)


def generate(*args, **kwargs):
    with (output / 'provider.started').open('x') as stream:
        stream.write(name)
    while not (output / 'provider.release').exists():
        time.sleep(.01)
    common = {'prompt': kwargs.get('prompt', 'Fixture media'), 'model': 'fixture-model',
              'provider': 'xai', 'aspect_ratio': '1:1'}
    if name == 'generate_image':
        from PIL import Image
        data = io.BytesIO()
        Image.new('RGB', (16, 16), '#7659ef').save(data, format='PNG')
        return {**common, 'image_base64': base64.b64encode(data.getvalue()).decode(),
                'mime_type': 'image/png', 'image_size': '1K'}
    if name == 'generate_video':
        return {**common, 'video_bytes': b'isolated-provider-video-bytes', 'duration': 1,
                'resolution': '720p'}
    data = io.BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x00\x01' * 8000)
    return {**common, 'audio_bytes': data.getvalue(), 'extension': 'wav', 'mime_type': 'audio/wav',
            'duration_ms': 1000, 'size_bytes': len(data.getvalue()), 'provider': 'ElevenLabs'}


if name == 'create_social_clip':
    # Exercise the real create/poll/download/stash path with scripted HTTP only.
    # The production skill downloads to a fixed /tmp directory; redirect that
    # Path in this fixture so even temporary videos belong to the test root.
    skill.Path = lambda value: output if str(value) == '/tmp/jarvis_social_clips' else Path(value)

    class Response:
        status_code = 200

        def __init__(self, body=None):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

        def iter_content(self, chunk_size):
            yield b'isolated-social-clip-bytes'

    def post(url, **kwargs):
        assert url == 'https://moneyprinter.invalid/api/v1/videos'
        assert kwargs['json']['video_subject'] == 'Fixture media'
        with (output / 'provider.started').open('x') as stream:
            stream.write(name)  # A repeated submission fails, even in one attempt.
        return Response({'status': 200, 'data': {'task_id': 'fixture-social-task'}})

    def get(url, **kwargs):
        if url == 'https://moneyprinter.invalid/api/v1/tasks/fixture-social-task':
            while not (output / 'provider.release').exists():
                time.sleep(.01)
            return Response({'data': {'state': 1, 'progress': 100,
                'videos': ['/tasks/fixture-social-task/final.mp4']}})
        assert url == 'https://moneyprinter.invalid/tasks/fixture-social-task/final.mp4'
        (output / 'download.started').touch()
        return Response()

    skill.requests.post, skill.requests.get = post, get
else:
    setattr(skill, name, generate)
skill.main()
