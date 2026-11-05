"""Animated images keep their bytes and identity across Stash and Canvas."""

from __future__ import annotations

import importlib
import io
import json

import pytest
from flask import Flask
from PIL import Image
from server_package_utils import load_canvas_server_package
from test_canvas_media_display_names import SETUP
from test_web_attachment_bundle_ui import run_browser

from lib import stash_helper


def _gif_bytes() -> bytes:
    frames = [Image.new('RGBA', (12, 8), color) for color in ('red', 'green', 'blue')]
    output = io.BytesIO()
    frames[0].save(
        output, 'GIF', save_all=True, append_images=frames[1:],
        duration=[80, 120, 160], loop=0, disposal=2, transparency=0,
    )
    return output.getvalue()


def test_stash_and_canvas_serve_original_animated_gif_and_recover_metadata(tmp_path, monkeypatch):
    alias = 'canvas_gif_images_test_server'
    load_canvas_server_package(alias)
    gallery = importlib.import_module(f'{alias}.routes.gallery')
    stash_route = importlib.import_module(f'{alias}.routes.stash')
    generated = tmp_path / 'generated_images'
    generated.mkdir()
    stash_root = tmp_path / 'stash'
    space = stash_helper.StashSpace('space_gif_test', stash_root)
    space.create(labels=['generated_images'])
    original = _gif_bytes()
    filename = 'generated_animation.gif'
    saved = stash_helper.StashFile(space).save_binary(
        original, filename, mime_type='image/gif', tags=['openai'],
        tool_origin='generate_image',
    )
    metadata = stash_helper.inspect_gif_image(original)
    for item in space.meta['files']:
        if item['file_id'] == saved['file_id']:
            item.update(metadata, model='gpt-image-2.6-sunburst')
    space._save_meta()
    (generated / filename).write_bytes(original)
    catalog_file = generated / 'image_catalog.json'
    catalog_file.write_text(json.dumps({filename: {
        'provider': 'OpenAI', 'model': 'gpt-image-2.6-sunburst', 'favorite': True,
    }}))
    monkeypatch.setattr(gallery, 'GENERATED_IMAGES_DIR', generated)
    monkeypatch.setattr(gallery, 'IMAGE_CATALOG_FILE', catalog_file)
    monkeypatch.setattr(gallery, 'CDN_CATALOG_FILE', generated / 'cdn_catalog.json')
    monkeypatch.setattr(gallery, 'get_stash_dir', lambda: stash_root)
    monkeypatch.setattr(stash_route, 'get_stash_dir', lambda: stash_root)
    app = Flask(__name__)
    app.register_blueprint(gallery.gallery_bp)
    app.register_blueprint(stash_route.stash_bp)
    client = app.test_client()

    listed = client.get('/api/gallery/images').get_json()['images'][0]
    assert listed['format'] == 'gif'
    assert listed['animated'] is True
    assert listed['frame_count'] == 3
    assert listed['duration_ms'] == 360
    assert listed['favorite'] is True
    assert listed['model'] == 'gpt-image-2.6-sunburst'
    # Recovery must work for an existing model row and a complete catalog rebuild.
    catalog_file.unlink()
    rebuilt = client.get('/api/gallery/images').get_json()['images'][0]
    assert rebuilt['animated'] is True
    assert rebuilt['duration_ms'] == 360
    assert rebuilt['model'] == 'gpt-image-2.6-sunburst'
    for url in (
        f'/api/gallery/images/{filename}',
        f'/api/gallery/images/{filename}/download',
        f"/api/stash/{space.space_id}/{saved['file_id']}",
    ):
        response = client.get(url)
        assert response.status_code == 200
        assert response.mimetype == 'image/gif'
        assert response.data == original
        with Image.open(io.BytesIO(response.data)) as animation:
            assert animation.n_frames == 3
            assert animation.info['loop'] == 0
            assert 'transparency' in animation.info
            durations = []
            for index in range(animation.n_frames):
                animation.seek(index)
                durations.append(animation.info['duration'])
            assert durations == [80, 120, 160]
        response.close()


def test_strict_downloader_only_preserves_gif_with_explicit_opt_in(monkeypatch):
    original = _gif_bytes()
    monkeypatch.setattr(stash_helper, 'safe_download', lambda *_args, **_kwargs: (
        original, 'application/octet-stream', 'https://cdn.example/animation.gif',
    ))
    with pytest.raises(stash_helper.SecurityError, match='supported JPEG'):
        stash_helper.safe_download_image('https://example.test/image')
    data, mime_type, _, metadata = stash_helper.safe_download_image(
        'https://example.test/image', allow_gif=True,
    )
    assert data == original
    assert mime_type == 'image/gif'
    assert metadata['frame_count'] == 3
    assert metadata['duration_ms'] == 360
    assert metadata['recompressed_for_safety'] is False


@pytest.mark.parametrize('limits,error', [
    ({'max_size': 1}, 'byte'),
    ({'max_frames': 2}, 'frame'),
    ({'max_pixels': 12 * 8 * 2}, 'decoded-frame'),
])
def test_gif_validation_bounds_bytes_frames_and_cumulative_pixels(limits, error):
    with pytest.raises(stash_helper.SecurityError, match=error):
        stash_helper.inspect_gif_image(_gif_bytes(), **limits)


def test_gif_gallery_uses_original_url_and_hands_off_to_image_editing():
    run_browser(SETUP + r"""
sandbox.window.location={href:'http://localhost:8890/gallery'};
sandbox.window.open=(url)=>{sandbox.handoffUrl=url;};
sandbox.URL=URL;
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-canvas/client/static/js/gallery.js','utf8'),sandbox);
vm.runInContext(`
  showToast=()=>{};
  const filename='generated_animation.gif';
  const item={name:filename,format:'gif',animated:true,size:100,modified:'2026-11-05'};
  images=[item];filteredImages=[item];renderGallery();
  const html=document.getElementById('gallery').innerHTML;
  if(!html.includes('>GIF</span>'))throw Error('GIF label missing');
  if(!html.includes('/api/gallery/images/'+filename))throw Error('Original GIF URL missing');
  openLightboxByIndex(0);
  if(document.getElementById('lightboxImage').src!=='/api/gallery/images/'+filename)throw Error('Lightbox flattened GIF');
  sendImageToJarvisWebByIndex(0);
`,sandbox);
const url=new URL(sandbox.handoffUrl);
assert.equal(url.searchParams.get('media_filename'),'generated_animation.gif');
assert.equal(url.searchParams.get('media_action'),'image');
""")
