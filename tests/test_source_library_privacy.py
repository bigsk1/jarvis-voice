"""Retained originals must stay out of Git and Docker build archives."""

import subprocess
import tarfile
from pathlib import Path

from docker.utils.build import tar

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATHS = [
    f"{directory}/{mode}.db{suffix}"
    for directory in ("data/source_library", "private-documents", "custom/nested/archive", ".")
    for mode in ("cloud", "local")
    for suffix in ("", "-journal", "-wal", "-shm", ".backup")
] + ["data/source_library/original.pdf", "data/source_library/inbox/local/private.md"]
PUBLIC_PATHS = ["lib/source_library.py", "docs/SOURCE_LIBRARY.md", "config/local.env.example"]


def test_git_ignores_default_and_custom_library_stores():
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=ROOT,
        input="\n".join(PRIVATE_PATHS + PUBLIC_PATHS) + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert set(result.stdout.splitlines()) == set(PRIVATE_PATHS)


def test_docker_archive_excludes_originals_and_custom_library_sidecars(tmp_path):
    for name in PRIVATE_PATHS + PUBLIC_PATHS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic build-context fixture")
    patterns = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    with tar(str(tmp_path), exclude=patterns) as archive:
        with tarfile.open(fileobj=archive) as bundle:
            names = set(bundle.getnames())
    assert not names.intersection(str(Path(name)) for name in PRIVATE_PATHS)
    assert set(PUBLIC_PATHS) <= names
