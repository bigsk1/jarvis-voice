"""Incident retention uses real mode parsing and temporary private evidence only."""

from __future__ import annotations

import importlib
import os
import runpy
import stat
import sys
from pathlib import Path

import pytest

from lib import retention_cleanup

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000
LEGACY_NAME = 'pg-' + 'a' * 32 + '.json'
DATED_NAME = '2026-11-09-pg-' + 'b' * 32 + '.json'


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / 'checkout with spaces'
    (root / 'config').mkdir(parents=True)
    for name in ('config_loader', 'lib.config_loader'):
        module = importlib.import_module(name)
        monkeypatch.setattr(module, 'get_project_root', lambda: root)
    for key in (
        'PROMPT_GUARD_INCIDENT_DIR', 'PROMPT_GUARD_INCIDENT_RETENTION_DAYS',
        'JARVIS_OVERRIDE_PROMPT_GUARD_INCIDENT_DIR',
        'JARVIS_OVERRIDE_PROMPT_GUARD_INCIDENT_RETENTION_DAYS',
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(retention_cleanup.time, 'time', lambda: NOW)
    return root


def _config(root: Path, mode: str, settings: str = '') -> None:
    (root / 'config' / f'{mode}.env').write_text('PROMPT_GUARD_ENABLED=false\n' + settings)


def _record(base: Path, mode: str, name: str = LEGACY_NAME, *, days: int = 91) -> Path:
    directory = base / mode
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / name
    # Retention never parses a record; even malformed legacy JSON is eligible.
    path.write_text('private evidence: not valid JSON')
    path.chmod(0o600)
    os.utime(path, (NOW - days * 86400, NOW - days * 86400))
    return path


@pytest.mark.parametrize('modes', [('cloud',), ('local',), ('cloud', 'local')])
def test_cleanup_handles_single_and_mixed_mode_installations(checkout, modes):
    paths = []
    for mode in modes:
        _config(checkout, mode)
        paths.append(_record(checkout / 'logs/prompt-guard/incidents', mode))

    result = retention_cleanup.cleanup_prompt_guard_incidents()

    assert result['errors'] == []
    assert result['deleted_files'] == len(modes)
    assert set(result['modes']) == set(modes)
    assert all(details['retention_days'] == 90 for details in result['modes'].values())
    assert all(not path.exists() for path in paths)


def test_cleanup_resolves_each_modes_custom_root_and_retention(checkout, tmp_path, monkeypatch):
    cloud_root = checkout / 'private incidents'
    local_root = tmp_path / 'local-private'
    _config(checkout, 'cloud', 'PROMPT_GUARD_INCIDENT_DIR=private incidents\n'
            'PROMPT_GUARD_INCIDENT_RETENTION_DAYS=60  # days\n')
    _config(checkout, 'local', f'PROMPT_GUARD_INCIDENT_DIR="{local_root}"\n'
            'PROMPT_GUARD_INCIDENT_RETENTION_DAYS=120\n')
    cloud = _record(cloud_root, 'cloud', days=80)
    local = _record(local_root, 'local', days=100)
    other_cloud = _record(local_root, 'cloud', days=150)
    other_local = _record(cloud_root, 'local', days=150)
    monkeypatch.setenv('JARVIS_MODE', 'cloud')
    # A startup-hydrated value must not become the sibling mode's configuration.
    monkeypatch.setenv('PROMPT_GUARD_INCIDENT_DIR', str(cloud_root))
    monkeypatch.setenv('PROMPT_GUARD_INCIDENT_RETENTION_DAYS', '60')
    before = dict(os.environ)

    result = retention_cleanup.cleanup_prompt_guard_incidents()

    assert result['errors'] == []
    assert result['deleted_files'] == 1
    assert not cloud.exists()
    assert local.exists() and other_cloud.exists() and other_local.exists()
    assert dict(os.environ) == before


def test_sibling_missing_settings_uses_defaults_not_startup_values(checkout, monkeypatch):
    _config(checkout, 'cloud', 'PROMPT_GUARD_INCIDENT_DIR=cloud-private\n'
            'PROMPT_GUARD_INCIDENT_RETENTION_DAYS=60\n')
    _config(checkout, 'local')
    cloud = _record(checkout / 'cloud-private', 'cloud', days=80)
    local = _record(checkout / 'logs/prompt-guard/incidents', 'local', days=80)
    monkeypatch.setenv('PROMPT_GUARD_INCIDENT_DIR', str(checkout / 'cloud-private'))
    monkeypatch.setenv('PROMPT_GUARD_INCIDENT_RETENTION_DAYS', '60')

    result = retention_cleanup.cleanup_prompt_guard_incidents()

    assert result['errors'] == []
    assert not cloud.exists()
    assert local.exists()
    assert result['modes']['local']['retention_days'] == 90


def test_cleanup_uses_mtime_and_exact_names_without_recursive_deletion(checkout, tmp_path):
    _config(checkout, 'cloud')
    base = checkout / 'logs/prompt-guard/incidents'
    old = _record(base, 'cloud')
    dated_old = _record(base, 'cloud', '2099-12-31-pg-' + 'c' * 32 + '.json')
    recent = _record(base, 'cloud', DATED_NAME, days=89)
    ancient_prefix_recent = _record(base, 'cloud', '2000-01-01-pg-' + 'd' * 32 + '.json', days=1)
    untouched = [
        _record(base, 'cloud', name, days=200)
        for name in ('summary.json', 'pg-short.json', f'.{LEGACY_NAME}.tmp', f'x-{LEGACY_NAME}')
    ]
    untouched += [
        _record(base / 'cloud/archive', 'cloud', days=200),
        _record(base.parent / 'benchmarks', 'cloud', days=200),
    ]
    external = _record(tmp_path / 'external', 'cloud', DATED_NAME, days=200)
    link = base / 'cloud' / ('pg-' + 'e' * 32 + '.json')
    link.symlink_to(external)
    directory = base / 'cloud' / ('pg-' + 'f' * 32 + '.json')
    directory.mkdir()

    result = retention_cleanup.cleanup_prompt_guard_incidents()

    assert result['errors'] == []
    assert result['deleted_files'] == 2
    assert not old.exists() and not dated_old.exists()
    assert recent.exists() and ancient_prefix_recent.exists()
    assert all(path.exists() for path in untouched)
    assert link.is_symlink() and external.exists() and directory.is_dir()


def test_dry_run_preserves_evidence_permissions_and_does_not_create_paths(checkout):
    _config(checkout, 'cloud')
    _config(checkout, 'local', 'PROMPT_GUARD_INCIDENT_DIR=does-not-exist\n')
    path = _record(checkout / 'logs/prompt-guard/incidents', 'cloud')
    before = {p: p.lstat() for p in (path, path.parent, path.parent.parent)}

    result = retention_cleanup.cleanup_prompt_guard_incidents(dry_run=True)

    assert result['errors'] == []
    assert result['deleted_files'] == 0
    assert result['candidates'] == [f'cloud/{LEGACY_NAME}']
    assert result['freed_bytes'] == path.stat().st_size
    for candidate, previous in before.items():
        current = candidate.lstat()
        assert current.st_mtime_ns == previous.st_mtime_ns
        assert current.st_mode == previous.st_mode
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not (checkout / 'does-not-exist').exists()


@pytest.mark.parametrize('bad_days', ['0', '-1', 'bad', '1.5', ''])
def test_invalid_sibling_retention_prevents_all_incident_deletions(checkout, bad_days):
    _config(checkout, 'cloud')
    _config(checkout, 'local', f'PROMPT_GUARD_INCIDENT_RETENTION_DAYS={bad_days}\n')
    old = _record(checkout / 'logs/prompt-guard/incidents', 'cloud', days=200)

    result = retention_cleanup.cleanup_prompt_guard_incidents()

    assert result['deleted_files'] == 0
    assert result['errors'] == [{'mode': 'local', 'error': 'invalid_retention_days'}]
    assert old.exists()


@pytest.mark.parametrize('component', ['ancestor', 'base', 'mode'])
def test_symlinked_directory_preflight_prevents_deletion(checkout, tmp_path, component):
    base = checkout / 'private'
    outside = tmp_path / 'outside'
    external = _record(outside, 'local', days=200)
    if component == 'ancestor':
        (checkout / 'linked').symlink_to(tmp_path, target_is_directory=True)
        configured = 'linked/outside'
    elif component == 'base':
        base.symlink_to(outside, target_is_directory=True)
        configured = 'private'
    else:
        base.mkdir()
        (base / 'local').symlink_to(outside / 'local', target_is_directory=True)
        configured = 'private'
    _config(checkout, 'cloud')
    _config(checkout, 'local', f'PROMPT_GUARD_INCIDENT_DIR={configured}\n')
    old = _record(checkout / 'logs/prompt-guard/incidents', 'cloud', days=200)

    result = retention_cleanup.cleanup_prompt_guard_incidents()

    assert result['deleted_files'] == 0
    assert result['errors'] == [{'mode': 'local', 'error': 'unsafe_or_unreadable_directory'}]
    assert old.exists() and external.exists()


def test_open_directory_handle_cannot_be_redirected_by_symlink_swap(checkout, tmp_path, monkeypatch):
    _config(checkout, 'cloud')
    base = checkout / 'logs/prompt-guard/incidents'
    old = _record(base, 'cloud')
    external = _record(tmp_path / 'outside', 'cloud', days=200)
    original = retention_cleanup.os.listdir

    def swap_directory(descriptor):
        (base / 'cloud').rename(base / 'moved-cloud')
        (base / 'cloud').symlink_to(external.parent, target_is_directory=True)
        return original(descriptor)

    monkeypatch.setattr(retention_cleanup.os, 'listdir', swap_directory)

    result = retention_cleanup.cleanup_prompt_guard_incidents()

    assert result['errors'] == []
    assert result['deleted_files'] == 1
    assert not (base / 'moved-cloud' / old.name).exists()
    assert external.exists()


def test_recent_replacement_between_checks_is_preserved(checkout, monkeypatch):
    _config(checkout, 'cloud')
    old = _record(checkout / 'logs/prompt-guard/incidents', 'cloud')
    original = retention_cleanup.os.stat
    changed = False

    def replace_after_stat(path, *args, **kwargs):
        nonlocal changed
        result = original(path, *args, **kwargs)
        if path == LEGACY_NAME and not changed:
            changed = True
            old.unlink()
            old.write_text('new record')
            os.utime(old, (NOW, NOW))
        return result

    monkeypatch.setattr(retention_cleanup.os, 'stat', replace_after_stat)

    result = retention_cleanup.cleanup_prompt_guard_incidents()

    assert result['errors'] == []
    assert result['deleted_files'] == 0
    assert old.read_text() == 'new record'


def test_cleanup_expands_home_path_and_one_off_days_override(checkout, tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    _config(checkout, 'local', 'PROMPT_GUARD_INCIDENT_DIR=${HOME}/private\n'
            'PROMPT_GUARD_INCIDENT_RETENTION_DAYS=120\n')
    old = _record(tmp_path / 'private', 'local', days=80)

    result = retention_cleanup.cleanup_prompt_guard_incidents(retention_days=60)

    assert result['errors'] == []
    assert result['modes']['local']['retention_days'] == 60
    assert not old.exists()


def test_no_configured_modes_creates_no_incident_tree(checkout):
    result = retention_cleanup.cleanup_prompt_guard_incidents()

    assert result['errors'] == []
    assert result['modes'] == {}
    assert not (checkout / 'logs').exists()


def test_cleanup_retention_cli_uses_mode_default_and_rejects_invalid_days(checkout, monkeypatch, capsys):
    _config(checkout, 'local')
    old = _record(checkout / 'logs/prompt-guard/incidents', 'local', days=100)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    command = runpy.run_path(str(ROOT / 'bin/cleanup-retention'))['main']
    monkeypatch.setattr(sys, 'argv', ['cleanup-retention', 'prompt-guard', '--dry-run'])

    assert command() == 0
    output = capsys.readouterr().out
    assert 'Would delete 1 expired Prompt Guard incident(s)' in output
    assert 'local: 90 days' in output
    assert 'private evidence' not in output
    assert old.exists()

    monkeypatch.setattr(sys, 'argv', ['cleanup-retention', 'prompt-guard', '--days', '0'])
    with pytest.raises(SystemExit) as error:
        command()
    assert error.value.code == 2
    assert old.exists()
