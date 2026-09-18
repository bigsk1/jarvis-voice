"""Cross-process catalog transactions and collision-resistant media saves."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('kind', ['image', 'audio', 'video'])
def test_processes_preserve_all_catalog_entries(tmp_path, kind):
    script = '''
import importlib, sys, time
from pathlib import Path
module = importlib.import_module('lib.' + sys.argv[2] + '_catalog')
original = getattr(module, 'load_' + sys.argv[2] + '_catalog')
def slow_read(path):
    result = original(path)
    time.sleep(.01)
    return result
setattr(module, 'load_' + sys.argv[2] + '_catalog', slow_read)
upsert = getattr(module, 'upsert_' + sys.argv[2] + '_catalog_entry')
for index in range(8):
    upsert(Path(sys.argv[1]), sys.argv[3] + str(index), {'model': 'fixture-model'})
'''
    catalog = tmp_path / 'catalog.json'
    children = [subprocess.Popen([sys.executable, '-c', script, str(catalog), kind, str(i)], cwd=ROOT)
                for i in range(4)]
    try:
        for child in children:
            assert child.wait(timeout=20) == 0
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()
    entries = json.loads(catalog.read_text())
    assert len(entries) == 32
    assert all(entry['model'] == 'fixture-model' for entry in entries.values())


@pytest.mark.parametrize('kind', ['image', 'audio'])
def test_favorite_transaction_survives_generator_upsert(tmp_path, kind):
    import importlib
    from lib.catalog_lock import catalog_lock

    module = importlib.import_module('lib.' + kind + '_catalog')
    path = tmp_path / 'catalog.json'
    upsert = getattr(module, 'upsert_' + kind + '_catalog_entry')
    load = getattr(module, 'load_' + kind + '_catalog')
    save = getattr(module, 'save_' + kind + '_catalog')
    upsert(path, 'existing', {'model': 'original'})
    script = '''
import importlib, sys
from pathlib import Path
module = importlib.import_module('lib.' + sys.argv[2] + '_catalog')
Path(sys.argv[3]).touch()
getattr(module, 'upsert_' + sys.argv[2] + '_catalog_entry')(
    Path(sys.argv[1]), 'existing', {'model': 'updated'})
'''
    marker = tmp_path / 'started'
    with catalog_lock(path):
        entries = load(path)
        child = subprocess.Popen([sys.executable, '-c', script, str(path), kind, str(marker)], cwd=ROOT)
        try:
            import time
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            assert marker.exists() and child.poll() is None
            entries['existing'].update(favorite=True, favorited_at='fixture-time')
            save(path, entries)
        except BaseException:
            child.kill()
            child.wait()
            raise
    try:
        assert child.wait(timeout=10) == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    assert load(path)['existing'] == {'model': 'updated', 'favorite': True, 'favorited_at': 'fixture-time'}


def test_same_prompt_same_second_keeps_distinct_image_files(tmp_path, monkeypatch):
    import base64
    from datetime import datetime
    from test_generated_media_model_catalogs import _load_module

    skill = _load_module('concurrent_image_save_test', ROOT / 'skills/generate_image.py')
    import stash_helper

    class FrozenDatetime:
        @staticmethod
        def now():
            return datetime(2026, 1, 1)

    monkeypatch.setattr(skill, 'datetime', FrozenDatetime)
    monkeypatch.setattr(skill, 'GENERATED_IMAGES_DIR', tmp_path)
    monkeypatch.setattr(skill, 'IMAGE_CATALOG_FILE', tmp_path / 'catalog.json')
    monkeypatch.setattr(stash_helper, 'open_space', lambda **kw: (_ for _ in ()).throw(RuntimeError('fixture')))
    results = [skill.save_to_stash({'image_base64': base64.b64encode(body).decode(),
                                   'mime_type': 'image/png'}, 'Identical prompt')
               for body in (b'first-image', b'second-image')]
    assert results[0]['filename'] != results[1]['filename']
    assert [Path(r['path']).read_bytes() for r in results] == [b'first-image', b'second-image']
    assert len(json.loads((tmp_path / 'catalog.json').read_text())) == 2
