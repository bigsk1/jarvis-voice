#!/usr/bin/env python3
"""Structural and mode-contract checks for public documentation."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def public_markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "config" / "README.md"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    return [path for path in files if "docs/personal" not in path.as_posix()]


def test_public_markdown_relative_links_exist():
    broken: list[str] = []
    link_pattern = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")

    for path in public_markdown_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in link_pattern.finditer(text):
            target = match.group(1).strip().split()[0].strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            if not (path.parent / target).resolve().exists():
                line = text.count("\n", 0, match.start()) + 1
                broken.append(f"{path.relative_to(ROOT)}:{line} -> {target}")

    assert broken == []


def test_public_markdown_code_fences_are_balanced():
    unbalanced: list[str] = []
    for path in public_markdown_files():
        fence_count = sum(
            1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.lstrip().startswith("```")
        )
        if fence_count % 2:
            unbalanced.append(f"{path.relative_to(ROOT)} ({fence_count} fences)")

    assert unbalanced == []


def test_mode_guides_keep_mode_and_provider_separate():
    guide_paths = [
        ROOT / "README.md",
        ROOT / "config" / "README.md",
        ROOT / "docs" / "README.md",
        ROOT / "docs" / "INSTALL_GUIDE.md",
        ROOT / "docs" / "QUICKSTART.md",
        ROOT / "docs" / "ollama" / "README.md",
        ROOT / "docs" / "docker" / "README.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in guide_paths)

    assert "OLLAMA_CLOUD_MODEL" in combined
    assert "JARVIS_MODE" in combined
    assert "LLM_PROVIDER" in combined
    assert "Cloud mode ignores Ollama" not in combined
    assert "docs/personal/ollama-cloud-primary-provider-plan.md" not in combined
