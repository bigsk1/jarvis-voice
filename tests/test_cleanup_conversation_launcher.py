"""Exercise the real cleanup entry point in a fresh, isolated interpreter."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_conversation_cleanup_loads_background_store_from_any_directory(tmp_path):
    source = Path(__file__).resolve().parents[1]
    checkout = tmp_path / "checkout with spaces"
    for relative in (
        "bin/cleanup-web-conversations",
        "jarvis-web/server/__init__.py",
        "jarvis-web/server/services/__init__.py",
        "jarvis-web/server/services/conversation_store.py",
    ):
        target = checkout / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    shutil.copytree(
        source / "lib",
        checkout / "lib",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    conversations = checkout / "data/web_conversations"
    conversations.mkdir(parents=True)
    index = conversations / "index.json"
    original = '{"conversations": []}'
    index.write_text(original)

    result = subprocess.run(
        [sys.executable, str(checkout / "bin/cleanup-web-conversations"), "--dry-run"],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "HOME": str(tmp_path / "empty-home"),
            "PYTHONPATH": "",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Would delete 0 unpinned conversation(s)" in result.stdout
    assert index.read_text() == original
    assert not (checkout / "data/background_tasks.db").exists()
