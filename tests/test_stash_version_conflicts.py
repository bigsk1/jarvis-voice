"""Regression coverage for versioned Stash filenames and metadata."""

from __future__ import annotations

from lib.stash_helper import StashFile, StashSpace, open_space


def test_open_space_reopens_existing_space_without_touch_typeerror(tmp_path, monkeypatch):
    monkeypatch.setenv("STASH_DIR", str(tmp_path))

    space, is_new = open_space(labels=["test"])
    assert is_new is True

    reopened, is_new_again = open_space(space_id=space.space_id)
    assert is_new_again is False
    assert reopened.space_id == space.space_id
    assert reopened.meta["last_used_at"] >= space.meta["last_used_at"]


def test_touch_updates_last_used_at_without_preloading_meta(tmp_path):
    space = StashSpace("space_test", tmp_path)
    space.create()
    original_last_used = space.meta["last_used_at"]

    fresh = StashSpace("space_test", tmp_path)
    assert fresh._meta is None

    fresh.touch()

    assert fresh.meta["last_used_at"] >= original_last_used


def test_version_conflicts_preserve_each_file_and_make_names_reachable(tmp_path):
    space = StashSpace("space_test", tmp_path)
    space.create()
    writer = StashFile(space)

    first = writer.save_text("first", "report.txt")
    second = writer.save_text("second", "report.txt", on_conflict="version")
    third = writer.save_text("third", "report.txt", on_conflict="version")

    assert [first["name"], second["name"], third["name"]] == [
        "report.txt",
        "report_2.txt",
        "report_3.txt",
    ]
    assert [first["stored_name"], second["stored_name"], third["stored_name"]] == [
        "report.txt",
        "report_2.txt",
        "report_3.txt",
    ]
    assert StashFile(space, name="report.txt").read()["content"] == "first"
    assert StashFile(space, name="report_2.txt").read()["content"] == "second"
    assert StashFile(space, name="report_3.txt").read()["content"] == "third"
    assert (space.space_path / "report_2.txt").read_text() == "second"


def test_versioning_skips_stored_name_from_legacy_broken_metadata(tmp_path):
    space = StashSpace("space_test", tmp_path)
    space.create()
    writer = StashFile(space)
    writer.save_text("first", "report.txt")
    second = writer.save_text("legacy second", "other.txt")

    # Reproduce metadata written by the old bug: the display name remained the
    # original while the file was stored under the versioned name.
    legacy = next(item for item in space.meta["files"] if item["file_id"] == second["file_id"])
    legacy["name"] = "report.txt"
    legacy["stored_name"] = "report_2.txt"
    (space.space_path / "other.txt").rename(space.space_path / "report_2.txt")
    space._save_meta()

    third = writer.save_text("third", "report.txt", on_conflict="version")

    assert third["name"] == "report_3.txt"
    assert (space.space_path / "report_2.txt").read_text() == "legacy second"
    assert (space.space_path / "report_3.txt").read_text() == "third"
