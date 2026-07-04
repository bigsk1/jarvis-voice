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
    "get_restricted_read_paths",
    "get_restricted_read_match",
    "is_path_under_prefix",
    "assert_not_restricted_read_path",
    "resolve_local_file_tool_path",
    "resolve_local_file_tool_output_path",
    "validate_tool_output_filename",
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


def get_restricted_read_paths() -> list[str]:
    """
    Subtrees tools must not read (shell, attachments, PDF/image tools, etc.).

    Keeps dated backups, ``data/secrets/`` (Docker-friendly secret mounts), and live
    ``config/`` (``.env``, contacts, keys) out of agent tool output.
    """
    root = get_project_root().resolve()
    return [
        str((root / "data" / "backups").resolve()),
        str((root / "data" / "secrets").resolve()),
        str((root / "config").resolve()),
    ]


def is_path_under_prefix(path: str | Path, prefix: str | Path) -> bool:
    """Return True when ``path`` equals ``prefix`` or is a descendant of it."""
    normalized = str(Path(path).expanduser().resolve())
    prefix_norm = os.path.normpath(str(prefix))
    return normalized == prefix_norm or normalized.startswith(prefix_norm + os.sep)


def get_restricted_read_match(path: str | Path) -> str | None:
    """Return the restricted prefix matched by ``path``, or None if readable."""
    normalized = str(Path(path).expanduser().resolve())
    for restricted in get_restricted_read_paths():
        if is_path_under_prefix(normalized, restricted):
            return restricted
    return None


def assert_not_restricted_read_path(path: str | Path, *, label: str = "Path") -> Path:
    """Raise ``ValueError`` when ``path`` falls under :func:`get_restricted_read_paths`."""
    resolved = Path(path).expanduser().resolve()
    matched = get_restricted_read_match(resolved)
    if matched:
        raise ValueError(
            f"{label} is in a restricted location ({matched}). Use stash refs instead."
        )
    return resolved


def resolve_local_file_tool_path(
    file_path: str | Path,
    *,
    include_pictures: bool = True,
) -> Path:
    """
    Resolve a local file path for read-only file tools.

    Enforces :func:`get_local_file_tool_allowed_dirs` and blocks
    :func:`get_restricted_read_paths`.
    """
    resolved = assert_not_restricted_read_path(file_path, label="File path")
    for directory in get_local_file_tool_allowed_dirs(include_pictures=include_pictures):
        try:
            resolved.relative_to(directory)
            return resolved
        except ValueError:
            continue
    raise ValueError("File path not in allowed directories. Use stash_ref instead.")


def validate_tool_output_filename(name: str | Path, *, label: str = "Output name") -> str:
    """Validate a caller-provided filename that must not contain a directory path."""
    value = str(name).strip()
    if (
        not value
        or value in {".", ".."}
        or Path(value).is_absolute()
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError(f"{label} must be a filename without directory components")
    return value


def resolve_local_file_tool_output_path(
    output_path: str | Path,
    *,
    base_dir: str | Path | None = None,
    label: str = "Output path",
) -> Path:
    """
    Resolve a tool output path without allowing traversal or sensitive destinations.

    When ``base_dir`` is provided, ``output_path`` must be a plain filename beneath
    that directory. Otherwise, the resolved path must be under a shared allowed-write
    directory such as ``data/``, ``stash/``, ``/tmp``, Downloads, or Documents.
    """
    if base_dir is not None:
        filename = validate_tool_output_filename(output_path, label=label)
        base = Path(base_dir).expanduser().resolve()
        resolved = (base / filename).resolve()
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"{label} must remain under {base}") from exc
    else:
        resolved = Path(output_path).expanduser().resolve()

    resolved = assert_not_restricted_read_path(resolved, label=label)
    if base_dir is not None:
        return resolved

    for allowed in get_allowed_write_paths():
        if is_path_under_prefix(resolved, allowed):
            return resolved
    raise ValueError(f"{label} is not in an allowed output directory")


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
