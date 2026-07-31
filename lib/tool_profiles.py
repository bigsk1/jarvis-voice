#!/usr/bin/env python3
"""
Tool profile overlays: merge per-tool enabled flags without editing skills/*.tool.json.

Active profile: JARVIS_TOOL_PROFILE (default: default). Respects JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE.

Profile files live under skills/profiles/<name>.json. Git tracks a small set of
ready-to-use baselines plus skills/profiles/examples/*.json templates; other
stems are local.

Shape:
  { "description": "optional", "overrides": { "tool_name": true|false } }

If a tool name is absent from overrides, the value from the tool's .tool.json is used.
If present, the override wins (so you can force-enable a tool that is disabled in the file).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from config_loader import get_config_value, get_project_root

_logger = logging.getLogger(__name__)

CONFIG_KEY = "JARVIS_TOOL_PROFILE"


def get_profiles_dir() -> Path:
    return get_project_root() / "skills" / "profiles"


def get_active_profile_name() -> str:
    raw = get_config_value(CONFIG_KEY, "default")
    if raw is None:
        return "default"
    name = str(raw).strip()
    return name if name else "default"


def _load_profile_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("Could not load tool profile %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def load_profile_overrides(profile_name: str) -> dict[str, bool]:
    """
    Load overrides map for a named profile.
    Returns tool_name -> enabled (True/False only for keys listed in overrides).
    """
    safe = profile_name.replace(os.sep, "").replace("/", "").strip() or "default"
    path = get_profiles_dir() / f"{safe}.json"
    data = _load_profile_file(path)
    raw = data.get("overrides", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, bool] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        out[k.strip()] = bool(v)
    return out


def load_active_profile_overrides() -> dict[str, bool]:
    return load_profile_overrides(get_active_profile_name())


def effective_enabled(tool_name: str, base_enabled: bool, overrides: dict[str, bool] | None) -> bool:
    """Apply profile overrides on top of the tool file's enabled flag."""
    if not overrides:
        return base_enabled
    if tool_name in overrides:
        return overrides[tool_name]
    return base_enabled


def list_profile_names() -> list[str]:
    """Return sorted stem names for *.json in skills/profiles (excluding backups)."""
    d = get_profiles_dir()
    if not d.is_dir():
        return []
    names: list[str] = []
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".bak.json"):
            continue
        names.append(p.stem)
    return names


def describe_active_profile(verbose: bool = False) -> str:
    """Human-readable one-line summary for logging."""
    name = get_active_profile_name()
    ov = load_active_profile_overrides()
    n = len(ov)
    line = f"{CONFIG_KEY}={name} ({n} override(s))"
    if verbose and ov:
        sample = ", ".join(f"{k}={'on' if v else 'off'}" for k, v in sorted(ov.items())[:8])
        if len(ov) > 8:
            sample += ", ..."
        line += f" — {sample}"
    return line


def warn_missing_profile_file() -> None:
    """If active profile is not default and file is missing, log once (TTY-friendly)."""
    name = get_active_profile_name()
    if name == "default":
        return
    path = get_profiles_dir() / f"{name}.json"
    if path.is_file():
        return
    msg = (
        f"Tool profile '{name}' has no file {path}; "
        f"treating as empty overrides (use skills/profiles/{name}.json)."
    )
    _logger.warning(msg)
    if sys.stdout.isatty() and not os.environ.get("JARVIS_JSON_MODE"):
        print(f"⚠️  {msg}", file=sys.stderr)
