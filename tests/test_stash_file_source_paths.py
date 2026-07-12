"""Regression coverage for stash kind=file source path checks."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import stash  # noqa: E402


class _FakeSpace:
    space_id = "space_test"


class _FakeStashFile:
    saved = {}

    def __init__(self, space):
        self.space = space

    def save_binary(self, data, name, mime_type=None, on_conflict="error", tags=None, tool_origin="stash"):
        self.saved = {
            "data": data,
            "name": name,
            "mime_type": mime_type,
            "on_conflict": on_conflict,
            "tags": tags,
            "tool_origin": tool_origin,
        }
        return {
            "file_id": "file_test",
            "name": name,
            "size_bytes": len(data),
            "ref": "stash://space_test/file_test",
        }


def test_file_save_allows_source_under_resolved_temp_symlink(monkeypatch, tmp_path):
    real_tmp = tmp_path / "private_tmp"
    real_tmp.mkdir()
    source = real_tmp / "sample.txt"
    source.write_bytes(b"stash me")

    link_tmp = tmp_path / "tmp"
    link_tmp.symlink_to(real_tmp, target_is_directory=True)
    symlinked_source = link_tmp / "sample.txt"

    monkeypatch.setattr(stash, "open_space", lambda scope="session": (_FakeSpace(), True))
    monkeypatch.setattr(stash, "StashFile", _FakeStashFile)
    monkeypatch.setattr(stash, "_allowed_file_source_prefixes", lambda: (real_tmp.resolve(),))

    result = stash.action_save({
        "kind": "file",
        "file_path": str(symlinked_source),
        "name": "sample.txt",
    })

    assert result["ok"] is True
    assert result["data"]["ref"] == "stash://space_test/file_test"


def test_file_source_prefix_check_does_not_use_raw_string_prefix(tmp_path):
    allowed = tmp_path / "tmp"
    allowed.mkdir()
    sibling = tmp_path / "tmp_not_allowed"
    sibling.mkdir()

    assert stash._path_is_under_prefix(allowed / "file.txt", allowed)
    assert not stash._path_is_under_prefix(sibling / "file.txt", allowed)
