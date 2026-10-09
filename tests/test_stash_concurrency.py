"""Independent Stash writers must keep both bytes and manifest edits."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from filelock import Timeout

from lib.stash_helper import StashFile, StashSpace


def test_concurrent_versioned_saves_refresh_stale_snapshots(tmp_path):
    original = StashSpace('space_concurrent', tmp_path)
    original.create()
    barrier = Barrier(8)
    def save(index):
        space = StashSpace(original.space_id, tmp_path)
        assert space.meta['files'] == []  # Every writer starts with a stale snapshot.
        barrier.wait()
        return StashFile(space).save_text(str(index), 'report.txt', on_conflict='version')
    with ThreadPoolExecutor(max_workers=8) as pool:
        saved = list(pool.map(save, range(8)))
    fresh = StashSpace(original.space_id, tmp_path)
    assert len(fresh.meta['files']) == 8
    assert len({entry['stored_name'] for entry in saved}) == 8
    assert {StashFile(fresh, file_id=entry['file_id']).read()['content'] for entry in saved} == {str(i) for i in range(8)}
    assert not list(fresh.space_path.glob('.meta-*'))


def test_stale_metadata_annotation_retains_other_writers_files_and_fields(tmp_path):
    first = StashSpace('space_annotations', tmp_path)
    first.create()
    one = StashFile(first).save_text('first', 'first.txt')
    second = StashSpace(first.space_id, tmp_path)
    _ = second.meta
    StashFile(first).save_text('second', 'second.txt')
    first.update(pinned=True)
    second.meta['files'][0]['source_url'] = 'https://example.test/source'
    second._save_meta()
    fresh = StashSpace(first.space_id, tmp_path)
    assert len(fresh.meta['files']) == 2
    assert fresh.meta['pinned'] is True
    assert StashFile(fresh, file_id=one['file_id']).meta['source_url'] == 'https://example.test/source'


def test_lock_identity_follows_shared_inode_and_leaves_no_artifacts(tmp_path):
    root = tmp_path / 'stash'
    root.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(root, target_is_directory=True)
    native = StashSpace('space_same', root)
    container = StashSpace('space_same', alias)
    assert native._lock is container._lock
    with native.transaction():
        with container.transaction(timeout=0):
            native.create()
            container.delete()
    assert list(root.iterdir()) == []


def test_stale_annotation_does_not_resurrect_deleted_manifest_record(tmp_path):
    first = StashSpace('space_deleted', tmp_path)
    first.create()
    StashFile(first).save_text('content', 'first.txt')
    stale = StashSpace(first.space_id, tmp_path)
    _ = stale.meta
    first.meta['files'] = []
    first._save_meta()
    stale.meta['files'][0]['source_url'] = 'https://example.test/source'
    stale._save_meta()
    assert StashSpace(first.space_id, tmp_path).meta['files'] == []


def test_waiting_process_keeps_same_lock_after_space_deletion(tmp_path):
    space = StashSpace('space_recreated', tmp_path / 'stash')
    space.create()
    code = '''
import sys
from pathlib import Path
from lib.stash_helper import StashSpace
space = StashSpace('space_recreated', Path(sys.argv[1]))
print('waiting', flush=True)
with space.transaction(timeout=5):
    space.create()
    print('acquired', flush=True)
    sys.stdin.readline()
    space.delete()
'''
    process = None
    try:
        with space.transaction():
            process = subprocess.Popen([sys.executable, '-c', code, str(space.stash_dir)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert process.stdout.readline().strip() == 'waiting'
            space.delete()
            assert list(space.stash_dir.iterdir()) == []
        assert process.stdout.readline().strip() == 'acquired'
        with pytest.raises(Timeout):
            with StashSpace(space.space_id, space.stash_dir).transaction(timeout=0.05):
                pytest.fail('A waiting writer must keep locking the same inode')
        _, error = process.communicate('\n', timeout=5)
        assert process.returncode == 0, error
        assert list(space.stash_dir.iterdir()) == []
    finally:
        if process and process.poll() is None:
            process.kill()
            process.communicate()


def test_concurrent_process_saves_preserve_all_versioned_bytes(tmp_path):
    space = StashSpace('space_processes', tmp_path)
    space.create()
    code = '''
import sys
from pathlib import Path
from lib.stash_helper import StashSpace, StashFile
space = StashSpace('space_processes', Path(sys.argv[1]))
_ = space.meta
StashFile(space).save_text(sys.argv[2] * 10000, 'report.txt', on_conflict='version')
'''
    def save(index):
        subprocess.run([sys.executable, '-c', code, str(tmp_path), str(index)],
                       capture_output=True, text=True, check=True, timeout=10)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, range(4)))
    fresh = StashSpace(space.space_id, tmp_path)
    assert len(fresh.meta['files']) == 4
    assert len({row['stored_name'] for row in fresh.meta['files']}) == 4
    assert {StashFile(fresh, file_id=row['file_id']).read()['content'] for row in fresh.meta['files']} == {
        str(index) * 10000 for index in range(4)
    }
