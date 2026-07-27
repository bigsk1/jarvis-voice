import json
from datetime import datetime, timedelta, timezone

from lib.video_catalog import sync_video_catalog


def _write_stash_metadata(stash_dir, filename, *, created):
    space = stash_dir / "space_video"
    space.mkdir(parents=True)
    (space / "meta.json").write_text(
        json.dumps(
            {
                "space_id": "space_video",
                "labels": ["generated_videos"],
                "files": [
                    {
                        "file_id": "f_video",
                        "stored_name": filename,
                        "tags": ["ai_generated", "video", "xai", "16:9"],
                        "model": "grok-imagine-video",
                        "tool_origin": "generate_video",
                        "created_at": created.isoformat(),
                        "source_url": "https://example.test/video.mp4",
                        "source_url_created": created.isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_sync_enriches_an_existing_incomplete_shared_catalog_entry(tmp_path):
    generated_dir = tmp_path / "generated_videos"
    stash_dir = tmp_path / "stash"
    generated_dir.mkdir()
    filename = "generated.mp4"
    (generated_dir / filename).write_bytes(b"video")

    created = datetime(2026, 7, 7, 12, tzinfo=timezone.utc)
    _write_stash_metadata(stash_dir, filename, created=created)
    catalog_file = generated_dir / "video_catalog.json"
    catalog_file.write_text(
        json.dumps(
            {
                filename: {
                    "provider": "xAI",
                    "aspect": "16:9",
                    "tags": ["xai", "16:9"],
                    "tool_origin": "generate_video",
                    "created_at": created.isoformat(),
                }
            }
        ),
        encoding="utf-8",
    )

    catalog = sync_video_catalog(
        generated_dir,
        stash_dir,
        catalog_file,
        now=created + timedelta(hours=1),
    )

    assert catalog[filename]["stash_ref"] == "stash://space_video/f_video"
    assert catalog[filename]["model"] == "grok-imagine-video"
    assert catalog[filename]["space_id"] == "space_video"
    assert catalog[filename]["source_url"] == "https://example.test/video.mp4"
    assert catalog[filename]["source_url_created"] == created.isoformat()
    assert catalog[filename]["edit_url_status"] == "available"


def test_sync_recomputes_cached_edit_url_status_as_time_advances(tmp_path):
    generated_dir = tmp_path / "generated_videos"
    stash_dir = tmp_path / "stash"
    generated_dir.mkdir()
    stash_dir.mkdir()
    filename = "generated.mp4"
    (generated_dir / filename).write_bytes(b"video")

    created = datetime(2026, 7, 7, 12, tzinfo=timezone.utc)
    catalog_file = generated_dir / "video_catalog.json"
    catalog_file.write_text(
        json.dumps(
            {
                filename: {
                    "source_url": "https://example.test/video.mp4",
                    "source_url_created": created.isoformat(),
                    "edit_url_status": "available",
                }
            }
        ),
        encoding="utf-8",
    )

    catalog = sync_video_catalog(
        generated_dir,
        stash_dir,
        catalog_file,
        now=created + timedelta(hours=5),
    )

    assert catalog[filename]["edit_url_status"] == "expired"
    persisted = json.loads(catalog_file.read_text(encoding="utf-8"))
    assert persisted[filename]["edit_url_status"] == "expired"
