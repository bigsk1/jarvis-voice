"""Load app-local ``server`` packages under collision-free test aliases."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_server_package(alias: str, package_dir: Path) -> ModuleType:
    """Load one app's server package without claiming the global ``server`` name."""
    existing = sys.modules.get(alias)
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location(
        alias,
        package_dir / "__init__.py",
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load test package {alias} from {package_dir}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module
