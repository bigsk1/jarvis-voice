#!/usr/bin/env python3
"""Structural and mode-contract checks for public documentation."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def markdown_without_code(text: str) -> str:
    """Mask Markdown code while preserving offsets and line numbers."""
    masked_lines: list[str] = []
    fence: str | None = None

    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = next((item for item in ("```", "~~~") if stripped.startswith(item)), None)
        if fence is not None:
            masked_lines.append("\n" if line.endswith("\n") else "")
            if marker == fence:
                fence = None
            continue
        if marker is not None:
            fence = marker
            masked_lines.append("\n" if line.endswith("\n") else "")
            continue
        masked_lines.append(re.sub(r"`+[^`\n]*`+", "", line))

    return "".join(masked_lines)


def public_markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "config" / "README.md"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    return [path for path in files if "docs/personal" not in path.as_posix()]


def test_public_markdown_relative_links_exist():
    broken: list[str] = []
    link_pattern = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")

    for path in public_markdown_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        searchable_text = markdown_without_code(text)
        for match in link_pattern.finditer(searchable_text):
            target = match.group(1).strip().split()[0].strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            if not (path.parent / target).resolve().exists():
                line = searchable_text.count("\n", 0, match.start()) + 1
                broken.append(f"{path.relative_to(ROOT)}:{line} -> {target}")

    assert broken == []


def test_markdown_link_scan_ignores_code_without_losing_line_numbers():
    text = """Before `example [label](MISSING_INLINE)`
```markdown
[label](MISSING_FENCED)
```
[real](MISSING_REAL)
"""

    searchable_text = markdown_without_code(text)
    matches = list(re.finditer(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", searchable_text))

    assert [match.group(1) for match in matches] == ["MISSING_REAL"]
    assert searchable_text.count("\n", 0, matches[0].start()) + 1 == 5


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
