"""Regression coverage for configurable Stash API storage paths."""

import asyncio
import io
from pathlib import Path

from fastapi import UploadFile

from api.routes import stash as stash_routes
from lib.stash_helper import StashFile, open_space


def test_stash_api_reads_from_configured_stash_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(tmp_path))

    space, _is_new = open_space(labels=["configured-path"])
    saved = StashFile(space).save_text("hello", "configured.txt")

    listing = asyncio.run(stash_routes.list_spaces(
        limit=50,
        offset=0,
        label=None,
        pinned=None,
        tool=None,
    ))
    assert [item.space_id for item in listing.spaces] == [space.space_id]

    metadata = stash_routes.get_space_meta(space.space_id)
    assert metadata is not None
    assert metadata["files"][0]["file_id"] == saved["file_id"]

    download = asyncio.run(stash_routes.download_file(space.space_id, saved["file_id"]))
    assert Path(download.path).read_text(encoding="utf-8") == "hello"


def test_stash_api_upload_creates_new_space(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(tmp_path))

    result = asyncio.run(stash_routes.upload_file(
        UploadFile(filename="uploaded.txt", file=io.BytesIO(b"uploaded")),
        labels="test-upload",
        space_id=None,
    ))

    assert result["ok"] is True
    assert result["filename"] == "uploaded.txt"
    assert (tmp_path / result["space_id"] / "uploaded.txt").read_bytes() == b"uploaded"
