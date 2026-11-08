"""Document conversion through the real restricted local-tool entry point."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
import pytest
from PIL import Image
from tool_child_environment import parse_child_environment_policy, restrict_child_environment

ROOT = Path(__file__).resolve().parents[1]


def conversion_environment(tmp_path: Path) -> dict[str, str]:
    manifest = json.loads((ROOT / 'skills/convert_file.tool.json').read_text())
    policy = parse_child_environment_policy(manifest['child_environment'])
    return restrict_child_environment(
        {'PATH': os.environ.get('PATH', ''), 'STASH_DIR': str(tmp_path / 'stash'),
         'JARVIS_MODE': 'cloud'}, policy, home=str(tmp_path / 'scratch-home'), proxy_policy='off',
    )


@pytest.mark.parametrize('extension', ['md', 'markdown', 'txt'])
def test_document_conversion_reads_complete_unicode_source_and_delivers_pdf(tmp_path, extension):
    source = tmp_path / f'guide.{extension}'
    content = ('# Owner guide — café\n\n'
               'Use “curly quotes” and preserve the complete document.\n\n'
               '[Documentation](https://example.com/docs)\n\n'
               '| Category | Meaning |\n| --- | --- |\n| Kitchen | Finished work |\n\n')
    content += '\n\n'.join(f'## Section {index}\n\nComplete paragraph {index}.' for index in range(110))
    content += '\n\nFINAL_SOURCE_MARKER_4872\n'
    source.write_text(content, encoding='utf-8')
    original = source.read_bytes()
    completed = subprocess.run(
        [sys.executable, str(ROOT / 'skills/convert_file.py')],
        input=json.dumps({'source': str(source), 'target_format': 'pdf',
                          'options': {'title': 'Owner guide — complete'}}),
        cwd=ROOT, env=conversion_environment(tmp_path), capture_output=True, text=True, timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    response = json.loads(completed.stdout)
    assert response['ok'] is True
    data = response['data']
    assert data['mime_type'] == 'application/pdf' and data['source_complete'] is True
    assert data['conversion_info']['source_bytes'] == len(original)
    assert data['conversion_info']['source_characters'] == len(content)
    assert data['stash_ref'].startswith(f"stash://{data['space_id']}/")
    output = next((tmp_path / 'stash' / data['space_id']).glob('*.pdf'))
    with fitz.open(output) as document:
        text = '\n'.join(page.get_text() for page in document)
        assert 'Owner guide — complete' in text
        assert 'café' in text and 'curly quotes' in text
        assert 'Complete paragraph 109.' in text and 'FINAL_SOURCE_MARKER_4872' in text
        assert data['page_count'] == document.page_count and document.page_count > 1
        if extension != 'txt':
            assert any(link.get('uri') == 'https://example.com/docs'
                       for page in document for link in page.get_links())
            assert '| Category | Meaning |' not in text
        else:
            assert '# Owner guide' in text and '| Category | Meaning |' in text
    assert source.read_bytes() == original


def test_invalid_text_encoding_fails_without_creating_stash(tmp_path):
    source = tmp_path / 'invalid.md'
    source.write_bytes(b'# Broken\n\xff\xfe')
    completed = subprocess.run(
        [sys.executable, str(ROOT / 'skills/convert_file.py')],
        input=json.dumps({'source': str(source), 'target_format': 'pdf'}), cwd=ROOT,
        env=conversion_environment(tmp_path), capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode != 0
    response = json.loads(completed.stdout)
    assert response['ok'] is False and 'UTF-8' in response['error']
    assert not (tmp_path / 'stash').exists()


def _stash_report_sources(tmp_path, extension, *, include_gaps=False):
    from config_loader import config_scope
    from stash_helper import StashFile, StashSpace

    with config_scope('cloud', overrides={'STASH_DIR': str(tmp_path / 'stash')}):
        media = StashSpace('space_conversion_media')
        media.create()
        source_space = StashSpace('space_conversion_source')
        source_space.create()
        payload = io.BytesIO()
        image = Image.new('RGB', (72, 36), (180, 40, 20))
        if include_gaps:
            image.save(payload, format='GIF', save_all=True,
                       append_images=[Image.new('RGB', image.size, 'blue')],
                       duration=[100, 200], loop=0)
        else:
            image.save(payload, format='PNG')
        chart = StashFile(media).save_binary(
            payload.getvalue(), 'chart.gif' if include_gaps else 'chart.png',
            mime_type='image/gif' if include_gaps else 'image/png',
        )
        content = f'# Report — chart\n\nFIRST PARAGRAPH\n\n![Revenue chart]({chart["ref"]})\n\n'
        if include_gaps:
            content += (f'![Missing image](stash://{media.space_id}/file_missing)\n\n'
                        '![Private image](http://127.0.0.1/unfetched.png)\n\n')
        content += 'FINAL PARAGRAPH'
        source = StashFile(source_space).save_text(content, f'report.{extension}')
        return source, chart


@pytest.mark.parametrize('extension', ['md', 'markdown'])
def test_restricted_converter_embeds_stash_raster_from_original_markdown_reference(tmp_path, extension):
    source, chart = _stash_report_sources(tmp_path, extension)
    original_source = Path(source['path']).read_bytes()
    original_chart = Path(chart['path']).read_bytes()
    completed = subprocess.run(
        [sys.executable, str(ROOT / 'skills/convert_file.py')],
        input=json.dumps({'source': source['ref'], 'target_format': 'pdf'}), cwd=ROOT,
        env=conversion_environment(tmp_path), capture_output=True, text=True, timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result['ok'] is True
    data = result['data']
    assert data['warnings'] == []
    assert data['source_complete'] is True
    assert data['conversion_info']['source_bytes'] == len(original_source)
    space_dir = tmp_path / 'stash' / data['space_id']
    output = space_dir / data['filename']
    manifest = json.loads((space_dir / 'meta.json').read_text())
    row = next(item for item in manifest['files'] if item['file_id'] == data['file_id'])
    assert row['hash_sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert row['size_bytes'] == data['output_size_bytes'] == output.stat().st_size
    with fitz.open(output) as document:
        text = ''.join(page.get_text() for page in document)
        assert 'FIRST PARAGRAPH' in text and 'FINAL PARAGRAPH' in text
        assert '[Image:' not in text
        assert any((image[2], image[3]) == (72, 36)
                   for page in document for image in page.get_images(full=True))
    assert Path(source['path']).read_bytes() == original_source
    assert Path(chart['path']).read_bytes() == original_chart


def test_restricted_converter_returns_image_warnings_and_preserves_gif_first_frame(tmp_path):
    source, animation = _stash_report_sources(tmp_path, 'md', include_gaps=True)
    original = Path(animation['path']).read_bytes()
    completed = subprocess.run(
        [sys.executable, str(ROOT / 'skills/convert_file.py')],
        input=json.dumps({'source': source['ref'], 'target_format': 'pdf'}), cwd=ROOT,
        env=conversion_environment(tmp_path), capture_output=True, text=True, timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result['ok'] is True
    data = result['data']
    assert data['warnings'] == data['conversion_info']['warnings']
    assert len(data['warnings']) >= 3
    assert any('first frame' in warning.lower() for warning in data['warnings'])
    output = tmp_path / 'stash' / data['space_id'] / data['filename']
    with fitz.open(output) as document:
        text = ''.join(page.get_text() for page in document)
        assert 'Missing image' in text and 'Private image' in text and 'FINAL PARAGRAPH' in text
        references = {image[0] for page in document for image in page.get_images(full=True)}
        assert references
        for reference in references:
            with Image.open(io.BytesIO(document.extract_image(reference)['image'])) as image:
                assert image.convert('RGB').getpixel((36, 18)) == (180, 40, 20)
    assert Path(animation['path']).read_bytes() == original


@pytest.mark.parametrize('extension', ['md', 'markdown'])
def test_restricted_converter_embeds_relative_raster_from_original_source_directory(tmp_path, extension):
    source_dir = tmp_path / 'source-documents'
    image_dir = source_dir / 'images'
    image_dir.mkdir(parents=True)
    chart = image_dir / 'quarterly chart.png'
    Image.new('RGB', (84, 42), (30, 140, 90)).save(chart)
    source = source_dir / f'report.{extension}'
    source.write_text(
        '# Relative image report\n\n![Quarterly chart](<./images/quarterly chart.png>)\n\nSOURCE TAIL',
        encoding='utf-8',
    )
    original = chart.read_bytes()

    completed = subprocess.run(
        [sys.executable, str(ROOT / 'skills/convert_file.py')],
        input=json.dumps({'source': str(source), 'target_format': 'pdf'}), cwd=ROOT,
        env=conversion_environment(tmp_path), capture_output=True, text=True, timeout=90,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result['ok'] is True
    assert result['data']['warnings'] == []
    output = tmp_path / 'stash' / result['data']['space_id'] / result['data']['filename']
    with fitz.open(output) as document:
        assert any((image[2], image[3]) == (84, 42)
                   for page in document for image in page.get_images(full=True))
        text = ''.join(page.get_text() for page in document)
        assert 'SOURCE TAIL' in text and '[Image:' not in text
    assert chart.read_bytes() == original
