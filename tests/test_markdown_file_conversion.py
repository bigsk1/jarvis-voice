"""Document conversion through the real restricted local-tool entry point."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
import pytest
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
