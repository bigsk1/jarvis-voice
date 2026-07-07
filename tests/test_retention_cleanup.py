import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib.retention_cleanup import (
    cleanup_web_uploads,
    collect_conversation_asset_references,
    find_upload_stash_fallback,
)
from lib.stash_helper import (
    StashFile,
    cleanup_expired,
    get_space,
    open_space,
)


def _age(path: Path, *, days: int) -> None:
    timestamp = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp))


def test_web_upload_cleanup_preserves_saved_conversation_references(tmp_path):
    uploads = tmp_path / "uploads"
    conversations = tmp_path / "conversations"
    uploads.mkdir()
    conversations.mkdir()
    referenced = uploads / "referenced.jpg"
    unreferenced = uploads / "unreferenced.jpg"
    referenced.write_bytes(b"referenced")
    unreferenced.write_bytes(b"unreferenced")
    _age(referenced, days=90)
    _age(unreferenced, days=90)
    (conversations / "conversation.json").write_text(
        json.dumps({"messages": [{"data": {"image_url": "/api/uploads/referenced.jpg"}}]}),
        encoding="utf-8",
    )

    result = cleanup_web_uploads(uploads, conversations, retention_days=60)

    assert referenced.exists()
    assert not unreferenced.exists()
    assert result["preserved_referenced"] == 1
    assert result["deleted_files"] == 1


def test_new_stash_spaces_receive_artifact_aware_retention(tmp_path, monkeypatch):
    monkeypatch.setenv("STASH_DIR", str(tmp_path / "stash"))

    temporary, _ = open_space(labels=["research"])
    media, _ = open_space(labels=["generated_images"])
    source, _ = open_space(labels=["pdf"])
    converted, _ = open_space(labels=["converted_files"], scope="project")

    assert (temporary.meta["retention_policy"], temporary.meta["ttl_days"]) == (
        "temporary", 7,
    )
    assert (media.meta["retention_policy"], media.meta["ttl_days"]) == (
        "generated_media", 30,
    )
    assert (source.meta["retention_policy"], source.meta["ttl_days"]) == (
        "source_artifact", 120,
    )
    assert (converted.meta["retention_policy"], converted.meta["ttl_days"]) == (
        "source_artifact", 120,
    )


def test_conversation_stash_reference_protects_expired_space(tmp_path, monkeypatch):
    stash_dir = tmp_path / "stash"
    conversations = tmp_path / "conversations"
    conversations.mkdir()
    monkeypatch.setenv("STASH_DIR", str(stash_dir))
    space, _ = open_space(labels=["temporary"])
    StashFile(space).save_text("keep", "keep.txt")
    space._meta["last_used_at"] = "2026-01-01T00:00:00Z"
    space._save_meta()
    (conversations / "conversation.json").write_text(
        json.dumps({"messages": [{"data": {"stash_ref": f"stash://{space.space_id}/f_any"}}]}),
        encoding="utf-8",
    )
    references = collect_conversation_asset_references(conversations)

    result = cleanup_expired(protected_space_ids=references.stash_space_ids)

    assert get_space(space.space_id).exists
    assert result["protected_spaces"] == 1


def test_stash_cleanup_migrates_policy_before_deleting(tmp_path, monkeypatch):
    stash_dir = tmp_path / "stash"
    monkeypatch.setenv("STASH_DIR", str(stash_dir))

    generated, _ = open_space(labels=["generated_videos"])
    generated._meta.pop("retention_policy", None)
    generated._meta["ttl_days"] = 7
    generated._meta["last_used_at"] = (
        datetime.now(timezone.utc) - timedelta(days=10)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    generated._save_meta()

    temporary, _ = open_space(labels=["temporary"])
    temporary._meta.pop("retention_policy", None)
    temporary._meta["ttl_days"] = 7
    temporary._meta["last_used_at"] = (
        datetime.now(timezone.utc) - timedelta(days=10)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    temporary._save_meta()

    explicit, _ = open_space(labels=["temporary"], ttl_days=45)
    explicit._meta.pop("retention_policy", None)
    explicit._meta["last_used_at"] = (
        datetime.now(timezone.utc) - timedelta(days=20)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    explicit._save_meta()

    result = cleanup_expired()

    assert get_space(generated.space_id).meta["ttl_days"] == 30
    assert get_space(generated.space_id).meta["retention_policy"] == "generated_media"
    assert not temporary.space_path.exists()
    assert get_space(explicit.space_id).meta["ttl_days"] == 45
    assert get_space(explicit.space_id).meta["retention_policy"] == "legacy_explicit"
    assert result["deleted_spaces"] == 1
    assert result["errors"] == []


def test_missing_upload_can_fall_back_to_associated_conversation_stash(tmp_path, monkeypatch):
    stash_dir = tmp_path / "stash"
    conversations = tmp_path / "conversations"
    conversations.mkdir()
    monkeypatch.setenv("STASH_DIR", str(stash_dir))
    space, _ = open_space(labels=["image", "web_upload"])
    saved = StashFile(space).save_binary(b"image", "stash-copy.jpg", "image/jpeg")
    (conversations / "conversation.json").write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "data": {"image_url": "/api/uploads/missing.jpg"}},
                    {"role": "assistant", "data": {"stash": {"stash_ref": saved["ref"]}}},
                ]
            }
        ),
        encoding="utf-8",
    )

    fallback = find_upload_stash_fallback("missing.jpg", conversations, stash_dir)

    assert fallback is not None
    assert fallback.read_bytes() == b"image"


def test_stash_cleanup_limits_backlog_deletion_per_run(tmp_path, monkeypatch):
    stash_dir = tmp_path / "stash"
    monkeypatch.setenv("STASH_DIR", str(stash_dir))
    older, _ = open_space(labels=["older"])
    newer, _ = open_space(labels=["newer"])
    older._meta["last_used_at"] = "2025-01-01T00:00:00Z"
    older._save_meta()
    newer._meta["last_used_at"] = "2025-06-01T00:00:00Z"
    newer._save_meta()

    result = cleanup_expired(
        protected_space_ids=frozenset(),
        max_delete_spaces=1,
        max_delete_bytes=1024 * 1024,
    )

    assert result["expired_spaces"] == 2
    assert result["deleted_spaces"] == 1
    assert result["deferred_spaces"] == 1
    assert not older.space_path.exists()
    assert newer.space_path.exists()
