"""Shared discovery rules for local tool manifests."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

_logger = logging.getLogger(__name__)


def iter_tool_manifest_files(skills_dir: Path) -> Iterator[Path]:
    """Yield direct manifests in shared, generated, then personal order."""
    skills_dir = Path(skills_dir)
    for directory in (skills_dir, skills_dir / "auto-tools", skills_dir / "personal"):
        yield from sorted(directory.glob("*.tool.json"))


def iter_tool_manifests(skills_dir: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield valid, uniquely named manifests before applying enablement rules.

    A disabled definition still owns its name. Personal tools cannot replace
    shared/generated tools or use the reserved MCP prefix.
    """
    skills_dir = Path(skills_dir)
    owners: dict[str, Path] = {}
    for path in iter_tool_manifest_files(skills_dir):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            name = manifest.get("name") if isinstance(manifest, dict) else None
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Manifest requires a non-empty name")
        except (OSError, ValueError) as exc:
            _logger.warning("Skipping invalid tool manifest %s: %s", path, exc)
            continue
        if path.parent == skills_dir / "personal" and name.startswith("mcp_"):
            _logger.warning("Ignoring personal tool %r in %s: mcp_ is reserved for MCP tools", name, path)
            continue
        if name in owners:
            _logger.warning(
                "Ignoring duplicate tool name %r in %s; first defined in %s. "
                "Rename the duplicate to load it.",
                name, path, owners[name],
            )
            continue
        owners[name] = path
        yield path, manifest
