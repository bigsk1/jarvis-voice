"""Deep-memory stash search uses the configured storage root."""

import json

from skills import deep_memory_search


def test_stash_search_uses_configured_root_for_content_and_metadata(tmp_path, monkeypatch):
    stash_root = tmp_path / "custom-stash"
    space = stash_root / "space-1"
    space.mkdir(parents=True)
    token = "configured_stash_search_probe"
    (space / "note.txt").write_text(f"A note about {token}.", encoding="utf-8")
    (space / "meta.json").write_text(
        json.dumps({
            "space_id": "space-1",
            "labels": ["research"],
            "created_at": "2026-09-21T00:00:00Z",
            "files": [{"name": "note.txt", "tool_origin": "stash"}],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(deep_memory_search, "PROJECT_ROOT", tmp_path / "checkout")
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(stash_root))

    results = deep_memory_search.search_stash_spaces(token, 5)

    assert len(results) == 1
    assert results[0]["space_id"] == "space-1"
    assert results[0]["matched_file"] == "note.txt"
    assert results[0]["file_names"] == ["note.txt"]
    assert token in results[0]["content_preview"]
