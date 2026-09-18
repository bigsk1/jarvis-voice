"""One reentrant cross-process lock for each generated-media catalog."""

from pathlib import Path

from filelock import FileLock


def catalog_lock(catalog_file):
    """Hold across the entire read/modify/replace, including nested helpers."""
    path = Path(catalog_file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path) + '.lock', timeout=30, is_singleton=True)
