"""Source lifecycle and retrieval with real SQLite/PDFs and controlled embeddings."""

import hashlib
import json
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import source_library as module
from config_loader import config_scope
from source_library import LibraryError, SourceLibrary


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR", str(tmp_path / "library"))
    return SourceLibrary("local")


def vector(index=0):
    value = [0.0] * 768
    value[index] = 1.0
    return value


def test_reads_do_not_create_a_store(library):
    assert library.list()["sources"] == []
    assert library.statuses(["a" * 64])["sources"] == []
    assert library.search("something")["retrieval_mode"] == "empty"
    with pytest.raises(LibraryError):
        library.read("a" * 64)
    assert not library.path.exists()


def test_bounded_status_lookup_keeps_requested_order(library):
    first = library.save(b"First source", "first.txt")
    second = library.save(b"Second source", "second.txt")
    statuses = library.statuses([second["source_id"], first["source_id"]])["sources"]
    assert [source["source_id"] for source in statuses] == [second["source_id"], first["source_id"]]
    assert all(source["index_job_status"] == "pending" for source in statuses)
    with pytest.raises(LibraryError, match="at most 100"):
        library.statuses(["a" * 64] * 101)


def test_complete_text_is_retained_deduplicated_and_read_after_restart(library):
    text = "Routine introduction.\n" * 250 + "The final access code is IRIS-947.\n"
    original = text.encode()
    saved = library.save(original, "manual.txt")
    sid = saved["source_id"]
    assert sid == hashlib.sha256(original).hexdigest()
    assert library.save(original, "renamed.md")["duplicate"] is True
    reopened = SourceLibrary("local")
    assert reopened.download(sid) == (original, "manual.txt", "text/plain")
    result = reopened.search("IRIS-947", semantic=False)
    passage = result["passages"][0]
    assert "IRIS-947" in passage["text"]
    assert passage["char_start"] > 2000
    assert passage["text"] == text[passage["char_start"] : passage["char_end"]]
    assert "lines" in passage["citation"] and "mode=local" in passage["url"]
    assert reopened.read(sid, passage=passage["number"])["passages"][0] == {
        k: v for k, v in passage.items() if k not in {"matched_by", "match_reasons"}
    }
    assert reopened.save(original + b"Changed", "manual.txt")["source_id"] != sid
    assert reopened.list()["total"] == 2


def test_keyword_hit_keeps_fact_spanning_a_passage_boundary(library):
    fact = "Emergency assembly point is the cedar fountain beside the east gate."
    text = "Filler " * 253 + fact + "\nWait for roll call."
    saved = library.save(text.encode(), "boundary.txt")
    result = library.search("cedar fountain", semantic=False)
    assert any(fact in passage["text"] for passage in result["passages"])
    passages = library.read(saved["source_id"], limit=8)["passages"]
    assert len(passages) == 2
    assert passages[1]["char_start"] < passages[0]["char_end"]
    for passage in passages:
        assert passage["text"] == text[passage["char_start"] : passage["char_end"]]
        assert len(passage["text"]) <= 1800
    assert passages[-1]["char_end"] == len(text)


@pytest.mark.parametrize("text", ["x" * 1800, "x" * 1801, "界" * 4500, "a\n" * 2500])
def test_overlapping_passages_cover_source_without_duplicate_tail(library, text):
    saved = library.save(text.encode(), "note.txt")
    passages = library.read(saved["source_id"], limit=8)["passages"]
    covered = 0
    for passage in passages:
        assert passage["char_start"] <= covered < passage["char_end"]
        assert passage["text"] == text[passage["char_start"] : passage["char_end"]]
        covered = passage["char_end"]
    assert covered == len(text)


def test_pdf_page_provenance_original_and_empty_page_warning(library):
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Introduction only")
        pdf.new_page()
        pdf.new_page().insert_text((72, 72), "Orchid evacuation rendezvous: east gate")
        original = pdf.tobytes()
    saved = library.save(original, "plan.pdf")
    assert saved["empty_pages"] == [2]
    result = library.search("Orchid evacuation", semantic=False)["passages"][0]
    assert result["page"] == 3
    assert "page 3" in result["citation"]
    assert library.download(saved["source_id"])[0] == original
    assert library.read(saved["source_id"])["source"]["page_count"] == 3
    assert library.rendered_pdf_page(saved["source_id"], 3).startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(LibraryError, match="outside"):
        library.rendered_pdf_page(saved["source_id"], 4)


def test_raw_and_rendered_markdown_do_not_fetch_remote_assets_or_run_html(library):
    original = (
        "# Private notes\n\n![remote](https://example.test/pixel.png)\n\n"
        "<script>alert(1)</script> [safe](https://example.test/page)\n"
    )
    sid = library.save(original.encode(), "notes.md")["source_id"]
    assert library.original_text(sid) == (original, "notes.md")
    rendered = library.rendered_markdown(sid)
    assert "<h1>Private notes</h1>" in rendered
    assert "[Image: remote]" in rendered and "<img" not in rendered
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered
    assert "javascript:" not in rendered
    assert 'rel="noopener noreferrer"' in rendered
    with pytest.raises(LibraryError, match="PDFs only"):
        library.rendered_pdf_page(sid, 1)


def test_editing_a_note_saves_new_original_and_keeps_old_citations(library):
    original = library.save(b"First journal entry", "journal.md", title="Journal")
    edited = library.save_edited_copy(original["source_id"], "Second journal entry")
    assert edited["source_id"] != original["source_id"]
    assert edited["origin"] == f"Edited from library://local/{original['source_id']}"
    assert library.download(original["source_id"])[0] == b"First journal entry"
    assert library.download(edited["source_id"])[0] == b"Second journal entry"
    assert library.search("First", semantic=False)["passages"][0]["source_id"] == original["source_id"]
    with pytest.raises(LibraryError, match="UTF-8 text"):
        library.save_edited_copy(original["source_id"], None)


@pytest.mark.parametrize(
    "data,name",
    [
        (b"", "empty.txt"),
        (b"\xff", "bad.txt"),
        (b"\x00text", "binary.md"),
        (b"bad PDF", "bad.pdf"),
        (b"hello", "image.png"),
        (b"text", "../secret.txt"),
        (b"text", "dir\\secret.txt"),
        (b"  \n", "blank.txt"),
    ],
)
def test_rejected_input_never_creates_a_source(library, data, name):
    with pytest.raises(LibraryError):
        library.save(data, name)
    assert not library.path.exists()


def test_encrypted_and_scanned_pdfs_are_actionable(library):
    with fitz.open() as pdf:
        pdf.new_page()
        with pytest.raises(LibraryError, match="document_ocr"):
            library.save(pdf.tobytes(), "scan.pdf")
        pdf[0].insert_text((72, 72), "Private")
        encrypted = pdf.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret"
        )
        with pytest.raises(LibraryError, match="Unlock"):
            library.save(encrypted, "locked.pdf")


def test_modes_are_independent_and_request_overrides_are_honored(tmp_path):
    for mode in ("cloud", "local"):
        with config_scope(mode, {"SOURCE_LIBRARY_DIR": str(tmp_path)}):
            lib = SourceLibrary()
            assert lib.list()["total"] == 0
            lib.save(mode.encode(), "mode.txt")
    for mode in ("cloud", "local"):
        with config_scope(mode, {"SOURCE_LIBRARY_DIR": str(tmp_path)}):
            result = SourceLibrary().list()["sources"]
            assert len(result) == 1 and result[0]["mode"] == mode


def test_cancel_before_commit_rolls_back_all_content(library):
    calls = iter([False, True])
    with pytest.raises(LibraryError, match="cancelled"):
        library.save(b"important content", "note.txt", cancel_check=lambda: next(calls))
    assert library.list()["total"] == 0
    assert library.search("important", semantic=False)["passages"] == []


def test_concurrent_duplicate_saves_have_one_original(library):
    with ThreadPoolExecutor(max_workers=4) as pool:
        saved = list(pool.map(lambda _: library.save(b"concurrent source", "note.txt"), range(8)))
    assert sum(not item["duplicate"] for item in saved) == 1
    assert library.list()["total"] == 1
    assert len(library.search("concurrent", semantic=False)["passages"]) == 1


def test_delete_removes_original_fts_and_vectors_only_in_selected_mode(library, monkeypatch):
    monkeypatch.setattr(module, "get_embeddings_batch", lambda texts, **_: [vector()] * len(texts))
    sid = library.save(b"violet delete target", "target.txt")["source_id"]
    library.index(sid)
    other = SourceLibrary("cloud")
    other.save(b"violet delete target", "target.txt")
    library.remove(sid)
    assert library.list()["total"] == 0
    assert library.search("violet", semantic=False)["passages"] == []
    with pytest.raises(LibraryError):
        library.download(sid)
    assert other.list()["total"] == 1
    with sqlite3.connect(library.path) as conn:
        assert conn.execute("SELECT count(*) FROM passages").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM passages_fts").fetchone()[0] == 0


def test_semantic_only_match_and_keyword_match_both_reach_hybrid(library, monkeypatch):
    first = library.save(b"The automobile is kept in the underground garage.", "parking.txt")
    second = library.save(b"Vehicle permit expires in October.", "permit.txt")
    monkeypatch.setattr(module, "get_embeddings_batch", lambda texts, **_: [vector()] * len(texts))
    monkeypatch.setattr(module, "get_embedding", lambda *_args, **_kwargs: vector())
    library.index(first["source_id"])
    library.index(second["source_id"])
    result = library.search("vehicle")
    assert result["retrieval_mode"] == "hybrid"
    assert result["passages"][0]["source_id"] == second["source_id"]
    assert result["passages"][0]["matched_by"] == ["keyword", "semantic"]
    assert result["passages"][1]["matched_by"] == ["semantic"]
    assert result["passages"][0]["match_reasons"] == ["text", "semantic"]
    assert result["passages"][1]["match_reasons"] == ["semantic"]


def test_legacy_json_vectors_remain_searchable_after_packed_vector_upgrade(library, monkeypatch):
    monkeypatch.setattr(module, "get_embeddings_batch", lambda texts, **_: [vector()] * len(texts))
    monkeypatch.setattr(module, "get_embedding", lambda *_args, **_kwargs: vector())
    sid = library.save(b"An automobile in the garage", "legacy.txt")["source_id"]
    library.index(sid)
    with sqlite3.connect(library.path) as conn:
        row = conn.execute("SELECT id,embedding FROM passages WHERE source_id=?", (sid,)).fetchone()
        assert isinstance(row[1], bytes)
        conn.execute("UPDATE passages SET embedding=? WHERE id=?", (json.dumps(vector()), row[0]))
    result = library.search("vehicle")
    assert result["passages"][0]["source_id"] == sid
    assert result["passages"][0]["match_reasons"] == ["semantic"]


def test_match_reasons_distinguish_title_from_passage_text(library):
    title = library.save(b"Unrelated passage", "title.txt", title="Orchid handbook")
    text = library.save(b"Orchid appears in this passage", "text.txt", title="Botany note")
    result = library.search("orchid", semantic=False)
    reasons = {p["source_id"]: p["match_reasons"] for p in result["passages"]}
    assert reasons[title["source_id"]] == ["title"]
    assert reasons[text["source_id"]] == ["text"]


def test_rename_preserves_identity_and_rebuilds_title_dependent_indexes(library, monkeypatch):
    monkeypatch.setattr(module, "get_embeddings_batch", lambda texts, **_: [vector()] * len(texts))
    sid = library.save(b"Only passage body", "note.txt", title="Old orchid")["source_id"]
    assert library.index(sid)["remaining"] == 0
    renamed = library.rename(sid, "New cedar")
    assert renamed["source_id"] == sid
    assert renamed["index_status"] == "keyword_only"
    assert library.download(sid)[0] == b"Only passage body"
    assert library.search("orchid", semantic=False)["passages"] == []
    assert library.search("cedar", semantic=False)["passages"][0]["match_reasons"] == ["title"]
    assert library.index(sid)["source"]["index_status"] == "ready"
    with pytest.raises(LibraryError, match="titles"):
        library.rename(sid, " ")


def test_embedding_outage_preserves_original_and_reports_keyword_only(library, monkeypatch):
    sid = library.save(b"salmon migration observations", "note.txt")["source_id"]

    def unavailable(*args, **kwargs):
        raise module.EmbeddingError("private endpoint must not appear in result")

    monkeypatch.setattr(module, "get_embeddings_batch", unavailable)
    result = library.index(sid)
    assert result["index_error"] and "private endpoint" not in json.dumps(result)
    assert result["remaining"] == 1
    assert library.download(sid)[0].startswith(b"salmon")
    search = library.search("salmon")
    assert search["retrieval_mode"] == "keyword" and search["semantic_unavailable_reason"]


def test_resume_batches_and_cancel_during_embedding(library, monkeypatch):
    sid = library.save(("Passage content. " * 4000).encode(), "large.txt")["source_id"]
    batches = []

    def embed(texts, **kwargs):
        batches.append(len(texts))
        return [vector()] * len(texts)

    monkeypatch.setattr(module, "get_embeddings_batch", embed)
    first = library.index(sid)
    assert first["remaining"] > 0
    assert first["source"]["indexed_passages"] == 16
    reopened = SourceLibrary("local")
    calls = iter([False, True])
    with pytest.raises(LibraryError, match="cancelled"):
        reopened.index(sid, cancel_check=lambda: next(calls))
    assert reopened.read(sid)["source"]["indexed_passages"] == 16
    while reopened.index(sid)["remaining"]:
        pass
    assert reopened.read(sid)["source"]["index_status"] == "ready"
    assert max(batches) == 16


def test_delete_during_embedding_cannot_resurrect_source(library, monkeypatch):
    sid = library.save(b"source to remove", "gone.txt")["source_id"]

    def embed(texts, **kwargs):
        library.remove(sid)
        return [vector()] * len(texts)

    monkeypatch.setattr(module, "get_embeddings_batch", embed)
    with pytest.raises(LibraryError, match="not in"):
        library.index(sid)
    assert library.list()["total"] == 0


def test_changed_fingerprint_never_compares_incompatible_vectors(library, monkeypatch):
    sid = library.save(b"rare zephyr data", "note.txt")["source_id"]
    monkeypatch.setattr(module, "get_embeddings_batch", lambda texts, **_: [vector()] * len(texts))
    library.index(sid)
    with sqlite3.connect(library.path) as conn:
        conn.execute("UPDATE passages SET fingerprint='old-model'")
    monkeypatch.setattr(
        module,
        "get_embedding",
        lambda *a, **k: pytest.fail("incompatible vectors must not be queried"),
    )
    result = library.search("zephyr")
    assert result["retrieval_mode"] == "keyword"
    assert result["passages"][0]["matched_by"] == ["keyword"]
    assert library.index(sid)["remaining"] == 0


@pytest.mark.parametrize("bad", [[1], [float("nan")] * 768, [0.0] * 768])
def test_invalid_provider_vectors_are_never_persisted(library, monkeypatch, bad):
    sid = library.save(b"data", "note.txt")["source_id"]
    monkeypatch.setattr(module, "get_embeddings_batch", lambda *a, **k: [bad])
    assert library.index(sid)["index_error"]
    assert library.read(sid)["source"]["indexed_passages"] == 0


def test_pagination_and_input_validation(library):
    for i in range(3):
        library.save(f"source {i}".encode(), f"note-{i}.txt")
    page = library.list(limit=2)
    assert page["next_offset"] == 2
    assert library.list(offset=2)["next_offset"] is None
    for value in (-1, True, "1"):
        with pytest.raises(LibraryError):
            library.list(offset=value)
    for query in ("", "x" * 1001, None):
        with pytest.raises(LibraryError):
            library.search(query)
    assert library.search('" OR * - :') is not None


def test_original_integrity_failure_is_reported(library):
    sid = library.save(b"authentic original", "note.txt")["source_id"]
    with sqlite3.connect(library.path) as conn:
        conn.execute("UPDATE sources SET original=? WHERE id=?", (b"damaged", sid))
    with pytest.raises(LibraryError, match="integrity"):
        library.download(sid)


def test_query_outage_keeps_keyword_search_and_source_filter(library, monkeypatch):
    monkeypatch.setattr(module, "get_embeddings_batch", lambda texts, **_: [vector()] * len(texts))
    first = library.save(b"spruce assembly location", "first.txt")["source_id"]
    second = library.save(b"spruce alternative location", "second.txt")["source_id"]
    library.index(first)
    library.index(second)

    def offline(*args, **kwargs):
        raise module.EmbeddingError("private endpoint")

    monkeypatch.setattr(module, "get_embedding", offline)
    result = library.search("spruce", source_id=first)
    assert result["retrieval_mode"] == "keyword"
    assert result["semantic_unavailable_reason"]
    assert [p["source_id"] for p in result["passages"]] == [first]
    assert "private endpoint" not in json.dumps(result)


def test_replaced_title_during_indexing_does_not_receive_stale_vectors(library, monkeypatch):
    original = b"same original bytes"
    sid = library.save(original, "note.txt", title="Old title")["source_id"]

    def replace(texts, **kwargs):
        library.remove(sid)
        library.save(original, "note.txt", title="New title")
        return [vector()] * len(texts)

    monkeypatch.setattr(module, "get_embeddings_batch", replace)
    with pytest.raises(LibraryError, match="replaced"):
        library.index(sid)
    source = library.read(sid)["source"]
    assert source["title"] == "New title" and source["indexed_passages"] == 0


@pytest.mark.skipif(os.name == "nt", reason="Windows symlinks need special privileges")
def test_library_store_rejects_a_symlink_database(library, tmp_path):
    victim = tmp_path / "private.env"
    victim.write_text("SECRET=1")
    library.path.parent.mkdir(parents=True, exist_ok=True)
    library.path.symlink_to(victim)
    with pytest.raises(LibraryError, match="regular"):
        library.save(b"A note", "note.txt")
    assert victim.read_text() == "SECRET=1"


@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-link identity checks")
def test_library_store_rejects_a_hardlinked_database(library, tmp_path):
    victim = tmp_path / "private.env"
    victim.write_text("SECRET=1")
    original_mode = victim.stat().st_mode
    library.path.parent.mkdir(parents=True, exist_ok=True)
    os.link(victim, library.path)
    with pytest.raises(LibraryError, match="singly linked"):
        library.save(b"A note", "note.txt")
    assert victim.read_text() == "SECRET=1"
    assert victim.stat().st_mode == original_mode


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow directory handles")
def test_library_store_rejects_a_symlinked_directory(library, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    library.path.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(LibraryError, match="directory"):
        library.save(b"A note", "note.txt")
    assert not (outside / "local.db").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
def test_existing_library_directory_is_made_private(library):
    library.path.parent.mkdir(mode=0o775)
    library.path.parent.chmod(0o775)
    saved = library.save(b"A private note", "note.txt")
    assert library.read(saved["source_id"])["source"]["source_id"] == saved["source_id"]
    assert library.path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux pinned directory path")
def test_library_store_stays_in_pinned_directory_after_name_swap(library, tmp_path, monkeypatch):
    import source_library as source_module

    root = library.path.parent
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original_connect = source_module.sqlite3.connect
    swapped = False

    def swap_before_sqlite_connect(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            root.rename(tmp_path / "original-library")
            root.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(source_module.sqlite3, "connect", swap_before_sqlite_connect)
    with library._connect(write=True) as conn:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
    assert swapped
    assert (tmp_path / "original-library" / "local.db").exists()
    assert not (outside / "local.db").exists()
