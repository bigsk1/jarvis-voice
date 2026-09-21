"""The Web library worker resumes committed index jobs without a browser."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import source_library as source_module
from source_library import LibraryError, SourceLibrary
from source_library_jobs import LibraryIndexWorker


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR", str(tmp_path / "library"))
    return tmp_path / "library"


def _vector():
    return [1.0] + [0.0] * 767


def test_worker_resumes_batches_after_restart_and_keeps_modes_separate(stores, monkeypatch):
    monkeypatch.setattr(
        source_module, "get_embeddings_batch", lambda texts, **_kwargs: [_vector()] * len(texts)
    )
    worker = LibraryIndexWorker()
    assert worker.poll_once("local") is False
    assert (stores / "inbox" / "local").is_dir()
    assert not (stores / "local.db").exists(), "Polling an empty library must not create a database."

    local = SourceLibrary("local")
    saved = local.save(("Library evidence. " * 2300).encode(), "book.txt")
    sid = saved["source_id"]
    assert saved["index_job_status"] == "pending"
    assert saved["passage_count"] > source_module.INDEX_BATCH_SIZE
    assert worker.poll_once("local") is True
    partial = local.read(sid, limit=1)["source"]
    assert partial["index_job_status"] == "pending"
    assert partial["indexed_passages"] == source_module.INDEX_BATCH_SIZE
    assert worker.poll_once("cloud") is False
    assert (stores / "inbox" / "cloud").is_dir()
    assert not (stores / "cloud.db").exists()

    restarted = LibraryIndexWorker()
    while restarted.poll_once("local"):
        pass
    done = SourceLibrary("local").read(sid, limit=1)["source"]
    assert done["index_job_status"] == "ready"
    assert done["indexed_passages"] == done["passage_count"]


def test_background_worker_finishes_without_any_browser_request(stores, monkeypatch):
    monkeypatch.setattr(
        source_module, "get_embeddings_batch", lambda texts, **_kwargs: [_vector()] * len(texts)
    )
    local = SourceLibrary("local")
    sid = local.save(b"A background-only source", "note.txt")["source_id"]
    worker = LibraryIndexWorker()
    worker.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if local.read(sid)["source"]["index_job_status"] == "ready":
                break
            time.sleep(0.01)
        assert local.read(sid)["source"]["index_job_status"] == "ready"
    finally:
        worker.stop()


@pytest.mark.skipif(os.name == "nt", reason="Standalone worker uses POSIX service signals")
@pytest.mark.parametrize("stop_method", ["terminate", "kill"])
def test_standalone_worker_status_tracks_process_lifetime(stores, stop_method):
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR": str(stores)}
    status_command = [sys.executable, str(root / "bin/jarvis-library-worker"), "status"]
    assert subprocess.run(status_command, cwd=root, env=environment, check=False).returncode == 1
    process = subprocess.Popen(
        [sys.executable, str(root / "bin/jarvis-library-worker")],
        cwd=root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and process.poll() is None:
            if (subprocess.run(status_command, cwd=root, env=environment, check=False).returncode == 0
                    and (stores / "inbox" / "local").is_dir()
                    and (stores / "inbox" / "cloud").is_dir()):
                break
            time.sleep(0.05)
        else:
            error = process.stderr.read().decode(errors="replace") if process.poll() is not None else ""
            assert process.poll() is None, error
            pytest.fail("Standalone worker never became healthy.")
        getattr(process, stop_method)()
        assert (process.wait(timeout=5) == 0) is (stop_method == "terminate")
        assert subprocess.run(status_command, cwd=root, env=environment, check=False).returncode == 1
        assert (stores / "inbox" / "local").is_dir()
        assert (stores / "inbox" / "cloud").is_dir()
        assert not (stores / "local.db").exists(), "An idle worker must not create a database."
        assert not (stores / "cloud.db").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.skipif(os.name == "nt", reason="Worker liveness uses POSIX advisory locks")
def test_worker_lease_requires_live_lock_and_never_follows_status_symlink(stores):
    local = SourceLibrary("local")
    assert local.worker_running() is False
    assert not stores.exists()
    with local.worker_lease():
        assert local.worker_running() is True
        assert not local.path.exists()
    assert local.worker_running() is False

    victim = stores.parent / "outside.txt"
    victim.write_text("KEEP-ME")
    lease_file = stores / ".worker-local.lock"
    lease_file.unlink()
    lease_file.symlink_to(victim)
    with pytest.raises(LibraryError):
        local.worker_running()
    with pytest.raises(LibraryError):
        with local.worker_lease():
            pass
    assert victim.read_text() == "KEEP-ME"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory-descriptor protection")
def test_worker_refuses_symlinked_inbox_without_following_it(stores):
    local = SourceLibrary("local")
    outside = stores.parent / "outside"
    outside.mkdir()
    stores.mkdir()
    (stores / "inbox").symlink_to(outside, target_is_directory=True)
    with pytest.raises(LibraryError, match="inbox"):
        LibraryIndexWorker().poll_once("local")
    assert list(outside.iterdir()) == []


def test_worker_records_error_and_explicit_retry(stores, monkeypatch):
    local = SourceLibrary("local")
    sid = local.save(b"A saved note.", "note.txt")["source_id"]

    def unavailable(*_args, **_kwargs):
        raise source_module.EmbeddingError("offline")

    monkeypatch.setattr(source_module, "get_embeddings_batch", unavailable)
    worker = LibraryIndexWorker()
    assert worker.poll_once("local") is True
    failed = local.read(sid)["source"]
    assert failed["index_job_status"] == "error"
    assert "keyword" in failed["index_error"]
    assert worker.poll_once("local") is False
    assert local.search("saved", semantic=False)["passages"]

    monkeypatch.setattr(
        source_module, "get_embeddings_batch", lambda texts, **_kwargs: [_vector()] * len(texts)
    )
    assert local.queue_index(sid)["queued"] is True
    assert worker.poll_once("local") is True
    assert local.read(sid)["source"]["index_job_status"] == "ready"


def test_queue_missing_source_does_not_create_database(stores):
    with pytest.raises(LibraryError):
        SourceLibrary("local").queue_index("a" * 64)
    assert not stores.exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows symlinks need special privileges")
def test_worker_lock_does_not_follow_or_truncate_symlink(stores):
    local = SourceLibrary("local")
    local.save(b"A note waiting for indexing.", "note.txt")
    victim = stores.parent / "private.txt"
    victim.write_text("KEEP-ME")
    lock = stores / "local.db.index.lock"
    lock.symlink_to(victim)

    with pytest.raises(LibraryError, match="index lock"):
        LibraryIndexWorker().poll_once("local")
    assert victim.read_text() == "KEEP-ME"


@pytest.mark.skipif(os.name == "nt", reason="Windows symlinks need special privileges")
def test_shared_index_lock_is_used_for_manual_index(stores):
    from source_library import index_lock

    local = SourceLibrary("local")
    local.save(b"A note waiting for indexing.", "note.txt")
    victim = stores.parent / "manual-private.txt"
    victim.write_text("KEEP-ME")
    lock = stores / "local.db.index.lock"
    lock.symlink_to(victim)
    with pytest.raises(LibraryError, match="index lock"):
        with index_lock(str(local.path) + ".index.lock"):
            local.index(local.list()["sources"][0]["source_id"])
    assert victim.read_text() == "KEEP-ME"


def test_inbox_bulk_import_survives_browser_close_and_restart(stores, monkeypatch):
    monkeypatch.setattr(
        source_module, "get_embeddings_batch", lambda texts, **_kwargs: [_vector()] * len(texts)
    )
    local = SourceLibrary("local")
    inbox = local.inbox_path
    (inbox / "books").mkdir(parents=True)
    (inbox / "notes").mkdir()
    (inbox / "books" / "guide.md").write_text("# Guide\nOffline orchid reference")
    (inbox / "notes" / "field.txt").write_text("Cedar observation log")
    (inbox / "ignored.png").write_bytes(b"not a document")
    (inbox / "escape.md").symlink_to(stores.parent / "outside.md")
    preview = local.inbox_status()
    assert preview["eligible_count"] == 2 and preview["skipped_count"] == 2
    assert not local.path.exists(), "Inbox inspection must be read-only."
    queued = local.queue_inbox_import()
    assert queued["queued"] == 2
    worker = LibraryIndexWorker()
    assert worker.poll_once("local") is True
    assert local.list()["total"] == 1
    restarted = LibraryIndexWorker()
    while restarted.poll_once("local"):
        pass
    assert local.list()["total"] == 2
    assert all(job["state"] == "done" for job in local.inbox_status()["jobs"])
    assert local.search("orchid", semantic=False)["passages"]
    assert (inbox / "books" / "guide.md").exists(), "Inbox originals are not consumed."
    assert local.queue_inbox_import()["queued"] == 0
    removed_id = local.search("orchid", semantic=False)["passages"][0]["source_id"]
    local.remove(removed_id)
    assert local.inbox_status()["queueable_count"] == 1
    assert local.queue_inbox_import()["queued"] == 1
    assert not (stores / "cloud.db").exists()


def test_changed_inbox_file_fails_then_can_be_requeued(stores):
    local = SourceLibrary("local")
    local.inbox_path.mkdir(parents=True)
    note = local.inbox_path / "note.txt"
    note.write_text("First revision")
    assert local.queue_inbox_import()["queued"] == 1
    note.write_text("Second revision with new content")
    assert LibraryIndexWorker().poll_once("local") is True
    assert local.inbox_status()["jobs"][0]["state"] == "error"
    assert local.list()["total"] == 0
    assert local.queue_inbox_import()["queued"] == 1
    assert LibraryIndexWorker().poll_once("local") is True
    assert local.list()["total"] == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory-descriptor protection")
def test_inbox_import_rejects_intermediate_symlink_swap(stores):
    local = SourceLibrary("local")
    nested = local.inbox_path / "part"
    nested.mkdir(parents=True)
    (nested / "note.txt").write_text("PUBLIC")
    assert local.queue_inbox_import()["queued"] == 1
    job = local.next_import_job()

    outside = stores.parent / "outside"
    outside.mkdir()
    secret = outside / "note.txt"
    secret.write_text("SECRET")
    os.utime(secret, ns=(job["mtime_ns"], job["mtime_ns"]))
    nested.rename(local.inbox_path / "part-old")
    nested.symlink_to(outside, target_is_directory=True)
    result = local.import_queued_file(job)
    assert result["error"]
    assert local.list()["total"] == 0, "An outside file must never enter the library."


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory-descriptor protection")
def test_inbox_mode_symlink_is_not_walked_or_imported(stores):
    local = SourceLibrary("local")
    local.inbox_path.parent.mkdir(parents=True, exist_ok=True)
    outside = stores.parent / "escaped-inbox"
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET")
    local.inbox_path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(LibraryError, match="Inbox path"):
        local.inbox_status()
    with pytest.raises(LibraryError, match="Inbox path"):
        local.queue_inbox_import()
    result = local.import_queued_file({
        "relative_path": "secret.txt",
        "size_bytes": 6,
        "mtime_ns": (outside / "secret.txt").stat().st_mtime_ns,
    })
    assert result["error"]
    assert local.list()["total"] == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-link identity checks")
def test_inbox_hardlink_is_not_imported(stores):
    local = SourceLibrary("local")
    local.inbox_path.mkdir(parents=True)
    secret = stores.parent / "secret.txt"
    secret.write_text("SECRET")
    os.link(secret, local.inbox_path / "note.txt")
    status = local.inbox_status()
    assert status["eligible_count"] == 0
    assert local.queue_inbox_import()["queued"] == 0
    assert local.list()["total"] == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory-descriptor protection")
def test_library_directory_symlink_is_not_walked(stores):
    local = SourceLibrary("local")
    local.inbox_path.mkdir(parents=True)
    (local.inbox_path / "note.txt").write_text("PUBLIC")
    outside = stores.parent / "elsewhere"
    (outside / "inbox" / "local").mkdir(parents=True)
    (outside / "inbox" / "local" / "secret.txt").write_text("SECRET")
    stores.rename(stores.parent / "library-old")
    stores.symlink_to(outside, target_is_directory=True)
    with pytest.raises(LibraryError, match="Inbox path"):
        SourceLibrary("local").inbox_status()
