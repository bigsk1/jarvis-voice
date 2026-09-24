"""Select the one SSH sudo setting needed by a prepared tool call."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tool_child_environment import (
    PROXY_ENV_KEYS,
    RUNTIME_ENV_KEYS,
    parse_child_environment_policy,
)

_PROTECTED_NAMES = RUNTIME_ENV_KEYS | PROXY_ENV_KEYS | {
    "HOME", "JARVIS_SSH_KEY_HOME", "SSH_AUTH_SOCK",
}


def selected_sudo_environment_names(config_path: Path, arguments: dict[str, Any]) -> frozenset[str]:
    """Return only the selected host's sudo variable when this action uses sudo."""
    action = arguments.get("action", "run")
    if action != "apt_update" and not (action in {"run", "multi"} and arguments.get("sudo")):
        return frozenset()
    host = arguments.get("host")
    if not isinstance(host, str) or not host:
        return frozenset()

    try:
        config = json.loads(config_path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        # Let ssh_remote.py report its own config-file error. This lookup is
        # only for selecting a credential, not validating the tool's config.
        return frozenset()
    if not isinstance(config, dict):
        return frozenset()
    hosts = config.get("hosts", {})
    selected = hosts.get(host, {}) if isinstance(hosts, dict) else {}
    name = selected.get("sudo_env") if isinstance(selected, dict) else None
    if not isinstance(name, str) or not name:
        return frozenset()
    # Use the same name validation as manifest allowlists. A private host
    # config cannot smuggle internal override names into the child environment.
    names = parse_child_environment_policy({"mode": "restricted", "allow": [name]})
    if name in _PROTECTED_NAMES:
        raise ValueError("SSH sudo_env conflicts with a protected child environment name")
    return names or frozenset()
