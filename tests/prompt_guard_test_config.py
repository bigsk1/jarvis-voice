"""Small explicit JSON v2 policies for isolated Prompt Guard test scopes."""

import json
from collections.abc import Iterable
from pathlib import Path


def write_guard_config(
    path: Path, *, tools: Iterable[str] = (), summarizers_enabled: bool = True,
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "v": 2,
        "tools": list(tools),
        "summarizers": {"enabled": summarizers_enabled},
        "policies": {"web_content": 0.8, "document_text": 0.8},
        "rules": [],
    }))
    return str(path)
