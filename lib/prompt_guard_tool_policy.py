"""Resolve optional guard policy names from operator-owned tool definitions.

Reading a manifest or MCP configuration never starts tool discovery or a remote
server. External result fields, MCP-reported metadata and tool arguments are not
policy sources. Invalid or missing metadata leaves the ordinary threshold active.
"""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from pathlib import Path

_POLICY_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,93}\Z")
_SOURCE_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_MAX_MCP_CONFIG_BYTES = 4 * 1024 * 1024


def normalize_prompt_guard_policy_name(value: object) -> str | None:
    """Keep a bounded identifier; metadata never carries a raw threshold."""
    return value if isinstance(value, str) and _POLICY_NAME.fullmatch(value) else None


def resolve_mcp_tool_policy_name(server_config: object, tool_name: str) -> str | None:
    """Inherit an operator server policy unless valid per-tool metadata wins.

    Only the local MCP server configuration belongs here. Neither a remote tool
    declaration nor client-reported defaults can assign a Prompt Guard policy.
    """
    if not isinstance(server_config, dict):
        return None
    metadata = server_config.get("tool_metadata")
    row = metadata.get(tool_name) if isinstance(metadata, dict) else None
    override = (
        normalize_prompt_guard_policy_name(row.get("prompt_guard_policy"))
        if isinstance(row, dict) else None
    )
    return override or normalize_prompt_guard_policy_name(server_config.get("prompt_guard_policy"))


def _local_policy_name(tool_name: str, skills_dir: Path) -> str | None:
    try:
        from tool_manifest_files import iter_tool_manifests
    except ModuleNotFoundError as exc:
        if exc.name != "tool_manifest_files":
            raise
        from lib.tool_manifest_files import iter_tool_manifests

    for _, manifest in iter_tool_manifests(skills_dir):
        if manifest["name"] == tool_name:
            return normalize_prompt_guard_policy_name(manifest.get("prompt_guard_policy"))
    return None


def _mcp_policy_name(tool_name: str, config_path: Path) -> str | None:
    try:
        with config_path.open("rb") as stream:
            raw = stream.read(_MAX_MCP_CONFIG_BYTES + 1)
        if len(raw) > _MAX_MCP_CONFIG_BYTES:
            return None
        document = json.loads(raw)
        servers = document.get("mcpServers") if isinstance(document, dict) else None
        if not isinstance(servers, dict):
            return None
        # Match configured server IDs before splitting the raw tool name. This
        # follows the registry's longest-prefix ownership for underscore IDs.
        for server_name, server in sorted(servers.items(), key=lambda item: len(item[0]), reverse=True):
            if not isinstance(server, dict) or not server.get("enabled", True):
                continue
            prefix = f"mcp_{server_name}_"
            if tool_name.startswith(prefix):
                raw_name = tool_name[len(prefix):]
                return resolve_mcp_tool_policy_name(server, raw_name) if raw_name else None
        return None
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def resolve_tool_policy_name(tool_name: str, *, mode: str | None = None) -> str | None:
    """Read trusted policy bindings without loading a registry or executing tools.

    Background completions, callbacks and standalone summarizers use the same
    definitions as foreground execution. ``stash_summary`` is the fixed internal
    input source for the Stash tool, rather than another public callable tool.
    """
    if not isinstance(tool_name, str) or not _SOURCE_NAME.fullmatch(tool_name):
        return None
    try:
        from config_loader import config_scope, get_active_config_mode
    except ModuleNotFoundError as exc:
        if exc.name != "config_loader":
            raise
        from lib.config_loader import config_scope, get_active_config_mode
    try:
        from paths import get_project_root
    except ModuleNotFoundError as exc:
        if exc.name != "paths":
            raise
        from lib.paths import get_project_root

    scope = config_scope(mode) if mode is not None and mode != get_active_config_mode() else nullcontext()
    with scope:
        root = get_project_root()
        if tool_name.startswith("mcp_"):
            return _mcp_policy_name(tool_name, root / "config" / "mcp-servers.json")
        return _local_policy_name("stash" if tool_name == "stash_summary" else tool_name,
                                  root / "skills")
