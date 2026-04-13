"""
Single source for user home, repository root, Jarvis workspace, and security path lists.

Prefer importing from this module instead of hardcoding host-specific paths (e.g. ``/home/.../``).

Environment:

- ``JARVIS_WORKSPACE_ROOT`` — If set, overrides the default workspace directory
  (``<user_home>/jarvis-workspace``). Used for OpenCode-style project roots and
  future portability work.
"""
from __future__ import annotations

import os
from pathlib import Path

from config_loader import get_project_root

__all__ = [
    "get_user_home",
    "get_project_root",
    "get_jarvis_workspace",
    "get_protected_paths",
    "get_allowed_write_paths",
    "get_local_file_tool_allowed_dirs",
]


def get_user_home() -> Path:
    """Return the current user's home directory (``Path.home().resolve()``)."""
    return Path.home().resolve()


def get_jarvis_workspace() -> Path:
    """
    Default: ``<user_home>/jarvis-workspace``.

    Override with ``JARVIS_WORKSPACE_ROOT`` (absolute or user-expandable path).
    """
    override = os.environ.get("JARVIS_WORKSPACE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return get_user_home() / "jarvis-workspace"


def get_protected_paths() -> list[str]:
    """
    Paths that must not be modified except where :func:`get_allowed_write_paths` allows writes.

    Built from :func:`get_project_root` and :func:`get_user_home` plus fixed system prefixes.
    """
    h = get_user_home()
    root = get_project_root().resolve()
    return [
        str(root),
        str((h / ".ssh").resolve()),
        str((h / ".gnupg").resolve()),
        str((h / ".config").resolve()),
        "/etc",
        "/usr",
        "/bin",
        "/sbin",
        "/boot",
        "/root",
        "/var/log",
    ]


def get_allowed_write_paths() -> list[str]:
    """Subtrees where writes are allowed (overrides protection of repo root)."""
    h = get_user_home()
    root = get_project_root().resolve()
    return [
        str((root / "data").resolve()),
        str((root / "logs").resolve()),
        str((root / "stash").resolve()),
        "/tmp",
        str((h / "Downloads").resolve()),
        str((h / "Documents").resolve()),
    ]


def get_local_file_tool_allowed_dirs(*, include_pictures: bool = True) -> list[Path]:
    """
    Directories from which ``analyze_image`` / ``pdf_read`` may read local file paths.

    ``include_pictures``: image tool historically allowed ``~/Pictures``; PDF tool omits it.
    """
    h = get_user_home()
    root = get_project_root().resolve()
    dirs: list[Path] = [
        (root / "data").resolve(),
        (root / "stash").resolve(),
        (h / "Downloads").resolve(),
        (h / "Documents").resolve(),
        Path("/tmp").resolve(),
    ]
    if include_pictures:
        dirs.append((h / "Pictures").resolve())
    return dirs
