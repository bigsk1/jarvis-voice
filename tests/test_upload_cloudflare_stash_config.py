"""Regression coverage for configurable Cloudflare stash source paths."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import upload_cloudflare
from lib.stash_helper import StashFile, open_space


def test_cloudflare_reads_stash_sources_from_configured_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(tmp_path))
    space, _is_new = open_space(labels=["cloudflare-configured-path"])
    saved = StashFile(space).save_binary(b"image", "configured-image.png", "image/png")

    assert upload_cloudflare.resolve_stash_path(saved["ref"]) == saved["path"]
    assert upload_cloudflare.get_stash_metadata(saved["ref"])["stash_ref"] == saved["ref"]

    uploaded = {}

    def fake_upload(file_path, **_kwargs):
        uploaded["file_path"] = file_path
        return {"ok": True, "url": "https://example.test/configured-image.png"}

    monkeypatch.setattr(upload_cloudflare, "upload_to_cloudflare", fake_upload)
    result = upload_cloudflare.upload_image(saved["stored_name"], source_type="file")

    assert result["ok"] is True
    assert uploaded["file_path"] == saved["path"]
