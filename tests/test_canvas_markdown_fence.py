#!/usr/bin/env python3
"""Regression tests for outer ```markdown fence unwrapping."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from skills.canvas import _unwrap_outer_markdown_fence  # noqa: E402


def test_unwrap_outer_markdown_fence_preserves_inner_crypto_chart_blocks():
    raw = """```markdown
# Report

```crypto-chart
{"title":"Bitcoin 7-day Chart","endpoint":"/api/prices/crypto/bitcoin/chart?days=7&points_limit=120"}
```

```crypto-chart
{"title":"Solana 7-day Chart","endpoint":"/api/prices/crypto/solana/chart?days=7&points_limit=120"}
```
```"""
    out = _unwrap_outer_markdown_fence(raw)
    assert out.startswith("# Report")
    assert out.count("```crypto-chart") == 2
    assert not out.startswith("```")


def test_plain_markdown_unchanged():
    raw = "# Hello\n\n```python\nprint('x')\n```\n"
    assert _unwrap_outer_markdown_fence(raw) == raw


def test_md_alias_unwrapped():
    raw = "```md\n# Title\n```"
    assert _unwrap_outer_markdown_fence(raw) == "# Title"
