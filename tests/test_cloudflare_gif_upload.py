"""Cloudflare sharing validates GIF bytes before any public upload."""

import asyncio
import base64
import io
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills'))

import upload_cloudflare  # noqa: E402

from api.routes import generated_images, images  # noqa: E402


def animation(width=8, height=8):
    output = io.BytesIO()
    Image.new('RGB', (width, height), 'red').save(
        output, 'GIF', save_all=True,
        append_images=[Image.new('RGB', (width, height), 'blue')], duration=[80, 120], loop=0,
    )
    return output.getvalue()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(upload_cloudflare, 'CLOUDFLARE_API_TOKEN', 'fixture-token')
    monkeypatch.setattr(upload_cloudflare, 'CLOUDFLARE_ACCOUNT_ID', 'fixture-account')


def successful_upload():
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
        'success': True,
        'result': {'id': 'asset-id', 'filename': 'loop.gif', 'variants': [
            'https://imagedelivery.net/account/asset-id/public',
        ]},
    })


@pytest.mark.parametrize('source_type', ['file', 'stash', 'base64', 'url'])
def test_all_upload_sources_preserve_validated_gif_bytes(configured, monkeypatch, tmp_path, source_type):
    original = animation()
    path = tmp_path / 'loop.gif'
    path.write_bytes(original)
    monkeypatch.setattr(upload_cloudflare, 'resolve_stash_path', lambda _source: str(path))
    monkeypatch.setattr(upload_cloudflare, 'get_stash_metadata', lambda _source: {})
    monkeypatch.setattr(upload_cloudflare, 'download_from_url', lambda _source: str(path))
    sent = []

    def post(_url, **kwargs):
        sent.append((kwargs['files']['file'][1].read(), kwargs['timeout']))
        return successful_upload()

    monkeypatch.setattr(upload_cloudflare.requests, 'post', post)
    source = {
        'file': str(path), 'stash': 'stash://space_fixture/f_fixture',
        'url': 'https://images.example/loop.gif',
        'base64': 'data:image/gif;base64,' + base64.b64encode(original).decode('ascii'),
    }[source_type]
    result = upload_cloudflare.upload_image(source, source_type)
    assert result['ok'] is True
    assert result['image_id'] == 'asset-id'
    assert sent == [(original, (10, 60))]


@pytest.mark.parametrize('problem', ['bytes', 'pixels', 'edge', 'invalid', 'disguised'])
def test_invalid_or_oversized_gifs_fail_before_public_upload(configured, monkeypatch, tmp_path, problem):
    path = tmp_path / ('disguised.png' if problem == 'disguised' else 'loop.gif')
    path.write_bytes(animation(12_001 if problem == 'edge' else 8))
    if problem == 'bytes':
        with path.open('r+b') as stream:
            stream.truncate(upload_cloudflare.CLOUDFLARE_IMAGE_MAX_BYTES + 1)
    elif problem in {'pixels', 'disguised'}:
        monkeypatch.setattr(upload_cloudflare, 'CLOUDFLARE_ANIMATION_MAX_PIXELS', 64)
    elif problem == 'invalid':
        path.write_bytes(b'GIF89a broken')
    post = Mock()
    monkeypatch.setattr(upload_cloudflare.requests, 'post', post)
    result = upload_cloudflare.upload_to_cloudflare(str(path))
    assert result['ok'] is False
    assert result['error']
    post.assert_not_called()


@pytest.mark.parametrize('result', [
    {'variants': ['https://cdn.example/image']}, {'id': 'asset-id', 'variants': []},
])
def test_incomplete_provider_receipts_cannot_claim_upload_success(configured, monkeypatch, tmp_path, result):
    path = tmp_path / 'loop.gif'
    path.write_bytes(animation())
    post = Mock(return_value=SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
        'success': True, 'result': result,
    }))
    monkeypatch.setattr(upload_cloudflare.requests, 'post', post)
    uploaded = upload_cloudflare.upload_to_cloudflare(str(path))
    assert uploaded['ok'] is False
    assert 'URL or image ID' in uploaded['error']
    assert post.call_count == 1


def test_upload_timeout_is_not_retried(configured, monkeypatch, tmp_path):
    path = tmp_path / 'loop.gif'
    path.write_bytes(animation())
    post = Mock(side_effect=upload_cloudflare.requests.exceptions.Timeout())
    monkeypatch.setattr(upload_cloudflare.requests, 'post', post)
    result = upload_cloudflare.upload_to_cloudflare(str(path))
    assert result['ok'] is False
    assert 'may have received' in result['error']
    assert post.call_count == 1


@pytest.mark.parametrize('upload_result', [
    {'ok': False, 'error': 'GIF exceeds Cloudflare limits'},
    {'ok': True, 'url': 'https://cdn.example/no-identity'},
])
def test_rejected_upload_does_not_write_cdn_catalog(tmp_path, monkeypatch, upload_result):
    (tmp_path / 'loop.gif').write_bytes(animation())
    catalog = tmp_path / 'cdn_catalog.json'
    catalog.write_text(json.dumps({'existing.gif': {
        'url': 'https://cdn.example/existing', 'image_id': 'existing-id',
    }}))
    before = catalog.read_bytes()
    monkeypatch.setattr(generated_images, 'GENERATED_IMAGES_DIR', tmp_path)
    monkeypatch.setattr(generated_images, 'CDN_CATALOG_FILE', catalog)
    monkeypatch.setattr(upload_cloudflare, 'upload_image', lambda *_args, **_kwargs: upload_result)
    result = asyncio.run(generated_images.get_or_create_cdn_url('loop.gif'))
    assert result.ok is False
    assert result.error
    assert catalog.read_bytes() == before


def test_cached_gif_url_and_identity_are_reused_without_upload(tmp_path, monkeypatch):
    (tmp_path / 'loop.gif').write_bytes(animation())
    catalog = tmp_path / 'cdn_catalog.json'
    entry = {'url': 'https://cdn.example/existing', 'image_id': 'existing-id'}
    catalog.write_text(json.dumps({'loop.gif': entry}))
    before = catalog.read_bytes()
    monkeypatch.setattr(generated_images, 'GENERATED_IMAGES_DIR', tmp_path)
    monkeypatch.setattr(generated_images, 'CDN_CATALOG_FILE', catalog)
    upload = Mock()
    monkeypatch.setattr(upload_cloudflare, 'upload_image', upload)
    result = asyncio.run(generated_images.get_or_create_cdn_url('loop.gif'))
    assert result.ok is True
    assert result.cached is True
    assert result.url == entry['url']
    assert result.image_id == entry['image_id']
    assert catalog.read_bytes() == before
    upload.assert_not_called()


def test_confirmed_gif_upload_adds_catalog_row_without_changing_existing_entries(tmp_path, monkeypatch):
    (tmp_path / 'loop.gif').write_bytes(animation())
    catalog = tmp_path / 'cdn_catalog.json'
    existing = {'url': 'https://cdn.example/existing', 'image_id': 'existing-id'}
    catalog.write_text(json.dumps({'existing.gif': existing}))
    monkeypatch.setattr(generated_images, 'GENERATED_IMAGES_DIR', tmp_path)
    monkeypatch.setattr(generated_images, 'CDN_CATALOG_FILE', catalog)
    thread_ids = []

    def upload(*_args, **_kwargs):
        thread_ids.append(threading.get_ident())
        return {'ok': True, 'url': 'https://cdn.example/new', 'image_id': 'new-id'}

    monkeypatch.setattr(upload_cloudflare, 'upload_image', upload)
    result = asyncio.run(generated_images.get_or_create_cdn_url('loop.gif'))
    saved = json.loads(catalog.read_text())
    assert result.ok is True and result.cached is False
    assert result.url == saved['loop.gif']['url'] == 'https://cdn.example/new'
    assert result.image_id == saved['loop.gif']['image_id'] == 'new-id'
    assert saved['existing.gif'] == existing
    assert thread_ids and thread_ids[0] != threading.get_ident()


def test_optional_cdn_failure_preserves_generation_and_reports_error(monkeypatch):
    monkeypatch.setattr(generated_images.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stderr='', stdout=json.dumps({'ok': True, 'data': {
            'saved': {'filename': 'loop.gif', 'path': 'data/generated_images/loop.gif'},
        }}),
    ))
    monkeypatch.setattr(upload_cloudflare, 'upload_image', lambda *_args, **_kwargs: {
        'ok': False, 'error': 'GIF exceeds Cloudflare limits',
    })
    save = Mock()
    monkeypatch.setattr(generated_images, 'set_cdn_url', save)
    response = asyncio.run(generated_images.generate_image(generated_images.GenerateRequest(
        prompt='A loop', upload_to_cdn=True,
    )))
    assert response.ok is True
    assert response.data['saved']['filename'] == 'loop.gif'
    assert response.data['cdn_error'] == 'GIF exceeds Cloudflare limits'
    assert response.cdn_url is None
    save.assert_not_called()


@pytest.mark.parametrize('base64_route', [False, True])
def test_public_upload_routes_report_shared_preflight_error(monkeypatch, base64_route):
    thread_ids = []

    def upload(*_args, **_kwargs):
        thread_ids.append(threading.get_ident())
        return {'ok': False, 'error': 'GIF exceeds Cloudflare limits'}

    monkeypatch.setattr(upload_cloudflare, 'upload_image', upload)
    if base64_route:
        response = asyncio.run(images.upload_base64_image({'image': 'GIF base64'}))
    else:
        response = asyncio.run(images.upload_image(images.ImageUploadRequest(source='loop.gif')))
    assert response.ok is False
    assert response.error == 'GIF exceeds Cloudflare limits'
    assert thread_ids and thread_ids[0] != threading.get_ident()
