"""Keep Spotify OAuth helpers aligned with the live tool contract."""

from __future__ import annotations

import ast
from pathlib import Path

from skills.spotify import SCOPES as TOOL_SCOPES


ROOT = Path(__file__).resolve().parents[1]


def _declared_scopes(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "SCOPES" for target in node.targets):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "join"
        ):
            value = value.args[0]
        return ast.literal_eval(value)
    raise AssertionError(f"SCOPES not found in {path}")


def test_auth_helpers_request_every_scope_used_by_spotify_tool():
    expected = set(TOOL_SCOPES)

    assert set(_declared_scopes(ROOT / "bin" / "spotify-auth")) == expected
    assert set(_declared_scopes(ROOT / "bin" / "spotify-reauth")) == expected
