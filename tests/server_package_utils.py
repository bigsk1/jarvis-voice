"""Load app-local ``server`` packages under collision-free test aliases."""

from __future__ import annotations

import importlib.util
import sys
from atexit import register
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType

_CANVAS_STORAGE = ExitStack()
register(_CANVAS_STORAGE.close)


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


def load_canvas_server_package(alias: str) -> ModuleType:
    """Load Canvas with package-local, temporary storage before its eager imports."""
    existing = sys.modules.get(alias)
    if existing is not None:
        return existing

    project_root = Path(__file__).resolve().parents[1]
    storage = Path(_CANVAS_STORAGE.enter_context(TemporaryDirectory(prefix='jarvis-canvas-test-')))
    config = ModuleType(f'{alias}.config')
    config.PROJECT_ROOT = project_root
    config.STATIC_DIR = project_root / 'docs' / 'images'
    config.DEFAULT_HOST = '0.0.0.0'
    config.DEFAULT_PORT = 8890
    for name, directory in (
        ('CANVAS_DIR', 'canvas'),
        ('STASH_DIR', 'stash'),
        ('GENERATED_IMAGES_DIR', 'generated_images'),
        ('GENERATED_VIDEOS_DIR', 'generated_videos'),
        ('GENERATED_AUDIO_DIR', 'generated_music'),
    ):
        path = storage / directory
        path.mkdir()
        setattr(config, name, path)
    sys.modules[config.__name__] = config
    return load_server_package(alias, project_root / 'jarvis-canvas' / 'server')
