#!/usr/bin/env python3
"""Configuration loader for Jarvis Voice Assistant."""
import os
import sys
import re
import contextvars
from contextlib import contextmanager
from pathlib import Path
from typing import Mapping

try:
    from jarvis_mode import resolve_jarvis_mode
except ImportError:  # imported as a package (e.g. ``lib.config_loader``)
    from lib.jarvis_mode import resolve_jarvis_mode

DEFAULT_JARVIS_QA_WORD_LIMIT = 75
DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT = 75


class _ScopedConfig:
    """Immutable per-request/run config overlay.

    Holds the active deployment ``mode``, the parsed ``config/<mode>.env`` values
    for that mode, and request-specific ``overrides``. This is installed in a
    :class:`contextvars.ContextVar` so concurrent cloud/local requests in one Web
    process never read each other's provider/model/embedding/URL values.
    """

    __slots__ = ("mode", "config", "overrides", "mode_keys")

    def __init__(
        self,
        mode: str,
        config: Mapping[str, str],
        overrides: Mapping[str, str],
        mode_keys=None,
    ):
        self.mode = mode
        self.config = dict(config)
        self.overrides = dict(overrides)
        self.mode_keys = frozenset(mode_keys or self.config.keys())

    def merged(self) -> dict:
        merged = dict(self.config)
        merged.update(self.overrides)
        return merged


_scoped_config: "contextvars.ContextVar[_ScopedConfig | None]" = contextvars.ContextVar(
    "jarvis_scoped_config", default=None
)


def _expand_env_value(value: str) -> str:
    """Expand ~ and $HOME / ${HOME} so seeded env files work on any Unix user.

    Does not use full ``os.path.expandvars`` — only home-related tokens so values
    containing other ``$`` characters (rare in secrets) are left unchanged.
    """
    if not value or not isinstance(value, str):
        return value
    home = os.environ.get("HOME")
    if home:
        value = value.replace("${HOME}", home).replace("$HOME", home)
    if value.startswith("~"):
        value = os.path.expanduser(value)
    return value


def _strip_inline_comment(value: str) -> str:
    """Strip unquoted trailing comments from env values.

    Keeps hashes inside quoted values or unquoted tokens such as API fragments,
    while allowing common dotenv style values like ``FOO=30  # days``.
    """
    if not value:
        return value
    if value.startswith(('"', "'")):
        return value
    return re.sub(r"\s+#.*$", "", value).strip()


def load_env_file(env_file):
    """Load environment variables from a file."""
    env_vars = {}
    if not os.path.exists(env_file):
        print(f"❌ Config file not found: {env_file}", file=sys.stderr)
        return env_vars
    
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Parse KEY=VALUE
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = _strip_inline_comment(value.strip())
                
                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                
                env_vars[key] = value
    
    return env_vars


def get_project_root():
    """Get the project root directory."""
    # Assume this file is in lib/ under project root
    return Path(__file__).parent.parent.resolve()


def _load_mode_config(mode: str) -> dict:
    """Parse and expand ``config/<mode>.env`` without touching process globals."""
    project_root = get_project_root()
    config_file = project_root / 'config' / f'{mode}.env'
    env_vars = load_env_file(config_file)
    return {k: _expand_env_value(v) for k, v in env_vars.items()}


def get_scoped_config() -> "dict | None":
    """Return the current request/run config overlay (merged), if one exists.

    The result merges the scope's ``config/<mode>.env`` values with any
    request-specific overrides. Returns ``None`` when no scope is active.
    """
    scoped = _scoped_config.get()
    if scoped is None:
        return None
    return scoped.merged()


def get_active_config_mode(explicit: "str | None" = None) -> str:
    """Resolve the active deployment mode.

    Priority: explicit argument -> scoped request mode -> ``JARVIS_MODE`` ->
    cloud. Validation/defaulting is delegated to ``resolve_jarvis_mode``.
    Provider/model names never influence this result.
    """
    if explicit is not None:
        return resolve_jarvis_mode(explicit)
    scoped = _scoped_config.get()
    if scoped is not None:
        return scoped.mode
    return resolve_jarvis_mode(None)


@contextmanager
def config_scope(mode: str, overrides: "Mapping[str, str] | None" = None):
    """Install a mode-specific config overlay for the duration of the block.

    Parses ``config/<mode>.env`` and installs one immutable scoped snapshot
    (mode + parsed values + request overrides) in a ``ContextVar``. Does NOT
    mutate ``os.environ``; the token is always reset in ``finally`` so nested
    or concurrent scopes cannot leak across requests.
    """
    resolved = resolve_jarvis_mode(mode)
    selected_config = _load_mode_config(resolved)
    other_mode = 'local' if resolved == 'cloud' else 'cloud'
    other_path = get_project_root() / 'config' / f'{other_mode}.env'
    other_config = _load_mode_config(other_mode) if other_path.exists() else {}
    snapshot = _ScopedConfig(
        mode=resolved,
        config=selected_config,
        overrides=dict(overrides or {}),
        mode_keys=set(selected_config) | set(other_config),
    )
    token = _scoped_config.set(snapshot)
    try:
        yield snapshot
    finally:
        _scoped_config.reset(token)


@contextmanager
def config_override_scope(overrides: "Mapping[str, str] | None" = None):
    """Temporarily add overrides to the active config scope.

    This is useful for decisions made after a request scope has started, such
    as disabling feedback sampling for one Completion Guard run. It never
    mutates ``os.environ`` and preserves all outer mode/config values.
    """
    current = _scoped_config.get()
    if current is None:
        raise RuntimeError("config_override_scope() requires an active config_scope()")

    merged_overrides = dict(current.overrides)
    merged_overrides.update(dict(overrides or {}))
    snapshot = _ScopedConfig(
        current.mode,
        current.config,
        merged_overrides,
        mode_keys=current.mode_keys,
    )
    token = _scoped_config.set(snapshot)
    try:
        yield snapshot
    finally:
        _scoped_config.reset(token)


def export_config_environment(mode: str, overrides: "Mapping[str, str] | None" = None) -> dict:
    """Materialize one scoped snapshot as a child-process environment dict.

    Starts from a copy of the current process environment (so PATH and other
    runtime essentials survive), overlays the selected mode's config values and
    request overrides, and stamps ``JARVIS_MODE`` explicitly. It never mutates
    the parent process and is the only sanctioned bridge to subprocesses.
    """
    resolved = resolve_jarvis_mode(mode)
    child_env = dict(os.environ)
    selected_config = _load_mode_config(resolved)
    other_mode = 'local' if resolved == 'cloud' else 'cloud'
    other_path = get_project_root() / 'config' / f'{other_mode}.env'
    other_config = _load_mode_config(other_mode) if other_path.exists() else {}

    # Remove stale direct values owned only by the other mode. Explicit
    # JARVIS_OVERRIDE_* process settings remain authoritative by design.
    for key in set(other_config) - set(selected_config):
        child_env.pop(key, None)
    for key, value in selected_config.items():
        child_env[key] = value
    scoped = _scoped_config.get()
    effective_overrides = {}
    if scoped is not None and scoped.mode == resolved:
        effective_overrides.update(scoped.overrides)
    effective_overrides.update(dict(overrides or {}))

    for key, value in effective_overrides.items():
        if value is None:
            continue
        key = str(key)
        value = str(value)
        child_env[key] = value
        # Child scripts commonly call load_config(), which rehydrates their
        # mode env file. Mirror request overrides into the existing override
        # namespace so those values retain precedence in the child process.
        if not key.startswith('JARVIS_OVERRIDE_'):
            child_env[f'JARVIS_OVERRIDE_{key}'] = value
    child_env['JARVIS_MODE'] = resolved
    return child_env


def load_config(mode=None):
    """
    Hydrate startup/CLI process configuration for the resolved mode.

    Args:
        mode: 'cloud' or 'local', or None to resolve from the active scope /
              ``JARVIS_MODE`` / cloud default. Provider names are NOT inspected.

    Returns:
        dict: Configuration values

    When called inside an active ``config_scope`` this returns the scoped values
    and does NOT rehydrate process globals, so request handlers cannot clobber a
    concurrent request's configuration.
    """
    scoped = get_scoped_config()
    if scoped is not None:
        return scoped

    resolved = get_active_config_mode(mode)
    expanded_vars = _load_mode_config(resolved)

    # Web UI overrides are prefixed with JARVIS_OVERRIDE_ and take precedence
    # over env file values. This prevents load_config() from overwriting
    # runtime overrides set by the web UI settings panel.
    override_prefix = 'JARVIS_OVERRIDE_'

    # Set environment variables
    for key, value in expanded_vars.items():
        # Don't overwrite if a web UI override exists for this key
        if f'{override_prefix}{key}' in os.environ:
            continue
        os.environ[key] = value

    return expanded_vars


def get_config_value(key, default=None):
    """Get a configuration value with scope-aware precedence.

    Priority:
      1. scoped request override (per-request overrides dict)
      2. process ``JARVIS_OVERRIDE_<KEY>`` (web UI settings)
      3. scoped config overlay (``config/<mode>.env`` for the active scope)
      4. startup ``os.environ``
      5. caller default
    """
    scoped = _scoped_config.get()
    if scoped is not None and key in scoped.overrides:
        return scoped.overrides[key]

    override = os.environ.get(f'JARVIS_OVERRIDE_{key}')
    if override is not None:
        return override

    if scoped is not None and key in scoped.config:
        return scoped.config[key]

    # A key owned by either mode file but absent from the selected one must not
    # fall through to process globals hydrated from the other mode.
    if scoped is not None and key in scoped.mode_keys:
        return default

    return os.environ.get(key, default)


def get_int(key, default=0):
    """Get integer config value."""
    try:
        return int(get_config_value(key, default))
    except (ValueError, TypeError):
        return default


def get_float(key, default=0.0):
    """Get float config value."""
    try:
        return float(get_config_value(key, default))
    except (ValueError, TypeError):
        return default


def get_bool(key, default=False):
    """Get boolean config value."""
    value = get_config_value(key, str(default)).lower()
    return value in ('true', '1', 'yes', 'on')
