"""Canonical startup-environment mode resolution for Jarvis services."""

from __future__ import annotations

import os
from pathlib import Path


VALID_JARVIS_MODES = ("cloud", "local")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class JarvisModeError(ValueError):
    """Raised when a startup mode is invalid or its required config is absent."""


def resolve_jarvis_mode(explicit: str | None = None) -> str:
    """Resolve startup mode from explicit input, ``JARVIS_MODE``, then cloud."""
    value = explicit if explicit is not None else os.environ.get("JARVIS_MODE", "cloud")
    normalized = str(value).strip().lower()
    if normalized not in VALID_JARVIS_MODES:
        source = "explicit mode" if explicit is not None else "JARVIS_MODE"
        raise JarvisModeError(
            f"Invalid {source} {value!r}; expected 'cloud' or 'local'."
        )
    return normalized


def env_file_for_mode(mode: str, project_root: Path | None = None) -> Path:
    """Return the selected config file after validating the mode."""
    resolved = resolve_jarvis_mode(mode)
    return (project_root or PROJECT_ROOT) / "config" / f"{resolved}.env"


def require_local_config(mode: str, project_root: Path | None = None) -> Path:
    """Enforce the explicit local-start contract; cloud stays backward compatible."""
    resolved = resolve_jarvis_mode(mode)
    path = env_file_for_mode(resolved, project_root)
    if resolved == "local" and not path.is_file():
        cloud_path = env_file_for_mode("cloud", project_root)
        guidance = (
            "Create config/local.env, or omit the local selection to use the existing config/cloud.env."
            if cloud_path.is_file()
            else "Create config/local.env or start in cloud mode."
        )
        raise JarvisModeError(
            f"Required startup config not found: {path}. {guidance}"
        )
    return path


def cloud_missing_local_hint(project_root: Path | None = None) -> str | None:
    """Return the native-launch hint for a local-only checkout, if applicable."""
    root = project_root or PROJECT_ROOT
    if not (root / "config" / "cloud.env").is_file() and (root / "config" / "local.env").is_file():
        return "config/cloud.env not found but config/local.env exists. For a local-only setup use: ./bin/start --local"
    return None
