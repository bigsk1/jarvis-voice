"""Keep deterministic tests independent of operator config and prior test state."""

from __future__ import annotations

import importlib
import os
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SYSTEM_KEYS = {'HOME', 'PATH', 'USER', 'LOGNAME', 'SHELL', 'TMPDIR', 'TEMP', 'TMP'}
_TEST_SWITCHES = {
    'JARVIS_LIVE_BROWSER_TEST', 'JARVIS_TEST_LONG_ENCODE', 'JARVIS_TEST_VIDEO', 'JARVIS_TEST_IMAGE',
}
_ORIGINAL_MODE_READER = None
_REDACTED_MODES: ContextVar[frozenset[str] | None] = ContextVar('suite_redacted_modes', default=None)


def config_modules():
    """The application supports these two import identities; isolate both."""
    for path in (ROOT, ROOT / 'lib'):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return tuple(importlib.import_module(name) for name in ('config_loader', 'lib.config_loader'))


def application_env_keys(root: Path = ROOT) -> set[str]:
    """Read names from public templates, never values from private mode files."""
    keys = set()
    for name in ('cloud.env.example', 'local.env.example'):
        path = root / 'config' / name
        if path.exists():
            keys.update(re.findall(r'^\s*(?:#\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*=', path.read_text(), re.MULTILINE))
    return keys - _SYSTEM_KEYS


def guard_env_reader(reader, operator_files):
    """Only operator mode files are empty; temporary parser fixtures stay real."""
    blocked = {Path(path).resolve() for path in operator_files}

    @wraps(reader)
    def isolated_reader(path):
        if Path(path).resolve() in blocked:
            modes = _REDACTED_MODES.get()
            if modes is not None:
                _REDACTED_MODES.set(modes | {Path(path).stem})
            return {}
        return reader(path)

    return isolated_reader


def guard_config_scope(scope, owned_keys):
    """Redact values without losing the mode ownership checked by the real getter."""
    @wraps(scope)
    @contextmanager
    def isolated_scope(*args, **kwargs):
        token = _REDACTED_MODES.set(frozenset())
        try:
            with scope(*args, **kwargs) as snapshot:
                if snapshot.mode in (_REDACTED_MODES.get() or ()):
                    snapshot.mode_keys = frozenset(snapshot.mode_keys | owned_keys)
                yield snapshot
        finally:
            _REDACTED_MODES.reset(token)

    return isolated_scope


def guard_config_export(exporter, module, owned_keys):
    """Do not reintroduce redacted mode settings through inherited child env."""
    @wraps(exporter)
    def isolated_export(*args, **kwargs):
        token = _REDACTED_MODES.set(frozenset())
        try:
            child = exporter(*args, **kwargs)
            mode = module.resolve_jarvis_mode(args[0] if args else kwargs.get('mode'))
            if mode in (_REDACTED_MODES.get() or ()):
                for key in owned_keys:
                    # The real exporter stamps explicit scope/request overrides
                    # in this namespace. Keep those and process overrides.
                    if f'JARVIS_OVERRIDE_{key}' not in child:
                        child.pop(key, None)
            return child
        finally:
            _REDACTED_MODES.reset(token)

    return isolated_export


def load_live_mode_config(mode: str) -> dict[str, str]:
    """Read operator settings only for an explicitly opted-in live test branch."""
    if os.environ.get('JARVIS_LIVE_BROWSER_TEST') != '1':
        raise RuntimeError('Live browser configuration requires JARVIS_LIVE_BROWSER_TEST=1')
    if mode not in ('cloud', 'local'):
        raise ValueError('Expected cloud or local mode')
    if _ORIGINAL_MODE_READER is None:
        raise RuntimeError('Test isolation has not been installed')
    values = _ORIGINAL_MODE_READER(ROOT / 'config' / f'{mode}.env')
    expand = config_modules()[0]._expand_env_value
    return {key: expand(value) for key, value in values.items()}


def install_default_isolation():
    """Install before test collection, when application modules may hydrate config."""
    global _ORIGINAL_MODE_READER

    keys = application_env_keys()
    for key in list(os.environ):
        if key not in _SYSTEM_KEYS | _TEST_SWITCHES and (key in keys or key.startswith('JARVIS_')):
            os.environ.pop(key, None)
    operator_files = [ROOT / 'config' / f'{mode}.env' for mode in ('cloud', 'local')]
    for module in config_modules():
        if _ORIGINAL_MODE_READER is None:
            _ORIGINAL_MODE_READER = module.load_env_file
        module.load_env_file = guard_env_reader(module.load_env_file, operator_files)
        module.config_scope = guard_config_scope(module.config_scope, keys)
        module.export_config_environment = guard_config_export(module.export_config_environment, module, keys)


@contextmanager
def isolated_test_state():
    """Restore process env and request config after each test, including failures."""
    environment = os.environ.copy()
    scopes = [(module._scoped_config, module._scoped_config.set(None)) for module in config_modules()]
    try:
        yield
    finally:
        for variable, token in reversed(scopes):
            variable.reset(token)
        os.environ.clear()
        os.environ.update(environment)
