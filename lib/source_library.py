"""Durable, mode-scoped originals and verifiable passage retrieval.

Reads never create a database. Original bytes, extracted passages and FTS rows
commit together; embedding batches commit separately and can be resumed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from config_loader import get_active_config_mode, get_config_value, get_project_root
from embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingError,
    cosine_similarity,
    get_embedding,
    get_embedding_fingerprint,
    get_embeddings_batch,
)

MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHARS = 1_000_000
MAX_PAGES = 1000
PASSAGE_CHARS = 1800
PASSAGE_OVERLAP_CHARS = 240
INDEX_BATCH_SIZE = 16
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".srt", ".vtt", ".log"}
_ID = re.compile(r"^[0-9a-f]{64}$")
_STOP_WORDS = set(
    "a an and are as at be by can did do does for from how i in is it me my of on or that the this to was what when where which who with you".split()
)


class LibraryError(ValueError):
    """An actionable input or source availability error."""


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise LibraryError(f"{name} must be an integer from {low} to {high}.")
    return value


def _fingerprint():
    return json.dumps(
        {
            **get_embedding_fingerprint("document"),
            "input_format": "source-library-title-passage-v1",
        },
        sort_keys=True,
    )


def _vector(value):
    if (
        not isinstance(value, list)
        or len(value) != EMBEDDING_DIMENSIONS
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in value)
        or not any(value)
    ):
        raise EmbeddingError("Invalid source embedding.")
    return value


def extract_passages(payload: bytes, filename: str) -> tuple[str, list[dict], list[int]]:
    """Extract complete text, retaining offsets in each original text/page unit."""
    if not payload or len(payload) > MAX_SOURCE_BYTES:
        raise LibraryError("Choose a non-empty source no larger than 25 MB.")
    suffix = Path(filename).suffix.lower()
    units = []
    empty_pages = []
    if suffix == ".pdf":
        import fitz

        try:
            with fitz.open(stream=payload, filetype="pdf") as doc:
                if doc.needs_pass:
                    raise LibraryError("Unlock this PDF before saving it to the library.")
                if doc.page_count > MAX_PAGES:
                    raise LibraryError("PDFs must have at most 1,000 pages.")
                total = 0
                for number, page in enumerate(doc, 1):
                    text = page.get_text("text", sort=True)
                    total += len(text)
                    if total > MAX_TEXT_CHARS:
                        raise LibraryError("Extracted text must have at most 1,000,000 characters.")
                    if not text.strip():
                        empty_pages.append(number)
                    units.append((number, text))
        except (fitz.FileDataError, RuntimeError) as exc:
            raise LibraryError("This PDF could not be read.") from exc
        mime = "application/pdf"
    elif suffix in TEXT_SUFFIXES:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise LibraryError("Text sources must use UTF-8 encoding.") from exc
        if "\x00" in text:
            raise LibraryError("This source contains binary data, not readable text.")
        if len(text) > MAX_TEXT_CHARS:
            raise LibraryError("Text sources must have at most 1,000,000 characters.")
        units = [(None, text)]
        mime = "text/plain"
    else:
        raise LibraryError("Save a PDF, UTF-8 note, Markdown, CSV, JSON, subtitle, or text log.")
    passages = []
    for page, text in units:
        start = 0
        while start < len(text):
            end = min(start + PASSAGE_CHARS, len(text))
            if end < len(text):
                newline = text.rfind("\n", start + PASSAGE_CHARS // 2, end)
                if newline < 0:
                    newline = text.rfind(" ", start + PASSAGE_CHARS // 2, end)
                if newline >= 0:
                    end = newline + 1
            excerpt = text[start:end]
            if excerpt.strip():
                passages.append(
                    {
                        "page": page,
                        "text": excerpt,
                        "char_start": start,
                        "char_end": end,
                        "line_start": text.count("\n", 0, start) + 1,
                        "line_end": text.count("\n", 0, end - 1) + 1,
                    }
                )
            if end == len(text):
                break
            # Keep boundary facts together without changing page-relative offsets.
            start = max(start + 1, end - PASSAGE_OVERLAP_CHARS)
    if not passages:
        raise LibraryError(
            "No searchable text was found. For scanned PDFs, run document_ocr and save its text output."
        )
    return mime, passages, empty_pages


class SourceLibrary:
    def __init__(self, mode=None):
        self.mode = get_active_config_mode(mode)
        root = (
            get_config_value("SOURCE_LIBRARY_DIR", "")
            or get_project_root() / "data" / "source_library"
        )
        self.path = Path(root).expanduser() / f"{self.mode}.db"

    @contextmanager
    def _connect(self, *, write=False):
        if not write and not self.path.exists():
            yield None
            return
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.path) if write else self.path.resolve().as_uri() + "?mode=ro",
            uri=not write,
            timeout=5,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            if write:
                conn.execute("PRAGMA secure_delete=ON")
                self.path.chmod(0o600)
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS sources (
                        id TEXT PRIMARY KEY, filename TEXT NOT NULL, title TEXT NOT NULL,
                        mime TEXT NOT NULL, original BLOB NOT NULL, origin TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                        empty_pages TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS passages (
                        id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                        number INTEGER NOT NULL, page INTEGER, text TEXT NOT NULL,
                        char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
                        line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
                        embedding TEXT, fingerprint TEXT,
                        UNIQUE(source_id, number)
                    );
                    CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(title, text);
                """)
            yield conn
            if write:
                conn.commit()
        except BaseException:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    def _id(self, source_id):
        if not isinstance(source_id, str) or not _ID.fullmatch(source_id):
            raise LibraryError("Use an exact source_id returned by the library.")
        return source_id

    def _source(self, conn, source_id):
        self._id(source_id)
        row = (
            conn.execute(
                "SELECT id,filename,title,mime,origin,created_at,empty_pages,length(original) AS size_bytes FROM sources WHERE id=?",
                (source_id,),
            ).fetchone()
            if conn
            else None
        )
        if row is None:
            raise LibraryError(
                "This source is not in the selected mode's library. It may have been removed."
            )
        return row

    def _metadata(self, conn, row):
        result = dict(row)
        result["empty_pages"] = json.loads(result["empty_pages"])
        result["source_id"] = result.pop("id")
        result["mode"] = self.mode
        result["source_ref"] = f"library://{self.mode}/{result['source_id']}"
        result["url"] = f"/library?mode={self.mode}&source={result['source_id']}"
        result["download_url"] = f"/api/library/{result['source_id']}/download?mode={self.mode}"
        try:
            fingerprint = _fingerprint()
        except EmbeddingError:
            fingerprint = ""
        counts = conn.execute(
            "SELECT count(*),sum(CASE WHEN fingerprint=? AND embedding IS NOT NULL THEN 1 ELSE 0 END) FROM passages WHERE source_id=?",
            (fingerprint, result["source_id"]),
        ).fetchone()
        result["passage_count"], result["indexed_passages"] = counts[0], counts[1] or 0
        result["index_status"] = (
            "ready" if counts[0] == counts[1] else "partial" if counts[1] else "keyword_only"
        )
        return result

    def save(self, payload, filename, *, title=None, origin="", cancel_check=None):
        if (
            not isinstance(filename, str)
            or not filename
            or len(filename) > 200
            or Path(filename).name != filename
            or "\\" in filename
            or any(ord(c) < 32 for c in filename)
        ):
            raise LibraryError("Use a filename without directories (at most 200 characters).")
        title = title or filename
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise LibraryError("Source titles must contain 1 to 200 characters.")
        if not isinstance(origin, str) or len(origin) > 1000:
            raise LibraryError("Source origin must be at most 1,000 characters.")
        mime, passages, empty_pages = extract_passages(payload, filename)
        source_id = hashlib.sha256(payload).hexdigest()
        if cancel_check and cancel_check():
            raise LibraryError("Save cancelled before the source was stored.")
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO sources(id,filename,title,mime,original,origin,empty_pages) VALUES(?,?,?,?,?,?,?)",
                    (
                        source_id,
                        filename,
                        title.strip(),
                        mime,
                        payload,
                        origin,
                        json.dumps(empty_pages),
                    ),
                )
                for number, passage in enumerate(passages, 1):
                    cursor = conn.execute(
                        "INSERT INTO passages(source_id,number,page,text,char_start,char_end,line_start,line_end) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            source_id,
                            number,
                            passage["page"],
                            passage["text"],
                            passage["char_start"],
                            passage["char_end"],
                            passage["line_start"],
                            passage["line_end"],
                        ),
                    )
                    conn.execute(
                        "INSERT INTO passages_fts(rowid,title,text) VALUES(?,?,?)",
                        (cursor.lastrowid, title.strip(), passage["text"]),
                    )
                if cancel_check and cancel_check():
                    raise LibraryError("Save cancelled before the source was stored.")
            result = self._metadata(conn, self._source(conn, source_id))
        return {**result, "duplicate": bool(exists)}

    def list(self, *, offset=0, limit=30):
        _integer(offset, "offset", 0, 1_000_000)
        _integer(limit, "limit", 1, 100)
        with self._connect() as conn:
            total = conn.execute("SELECT count(*) FROM sources").fetchone()[0] if conn else 0
            rows = (
                conn.execute(
                    "SELECT id,filename,title,mime,origin,created_at,empty_pages,length(original) AS size_bytes FROM sources ORDER BY created_at DESC,id LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
                if conn
                else []
            )
            return {
                "sources": [self._metadata(conn, row) for row in rows],
                "total": total,
                "offset": offset,
                "next_offset": offset + len(rows) if offset + len(rows) < total else None,
                "mode": self.mode,
            }

    def _passage(self, row, meta):
        return {
            **{
                key: row[key]
                for key in (
                    "number",
                    "page",
                    "text",
                    "char_start",
                    "char_end",
                    "line_start",
                    "line_end",
                )
            },
            "source_id": meta["source_id"],
            "source_ref": meta["source_ref"],
            "title": meta["title"],
            "mode": self.mode,
            "url": f"{meta['url']}&passage={row['number']}",
            "citation": f"{meta['title']} — "
            + (f"page {row['page']}, " if row["page"] else "")
            + f"lines {row['line_start']}–{row['line_end']} (passage {row['number']})",
        }

    def read(self, source_id, *, passage=1, limit=3):
        _integer(passage, "passage", 1, 1_000_000)
        _integer(limit, "limit", 1, 8)
        with self._connect() as conn:
            meta = self._metadata(conn, self._source(conn, source_id))
            if passage > meta["passage_count"]:
                raise LibraryError("That passage is outside this source.")
            rows = conn.execute(
                "SELECT * FROM passages WHERE source_id=? AND number>=? ORDER BY number LIMIT ?",
                (source_id, passage, limit),
            ).fetchall()
            end = passage + len(rows)
            return {
                "source": meta,
                "passages": [self._passage(row, meta) for row in rows],
                "next_passage": end if end <= meta["passage_count"] else None,
                "mode": self.mode,
            }

    def download(self, source_id):
        with self._connect() as conn:
            meta = dict(self._source(conn, source_id))
            payload = conn.execute(
                "SELECT original FROM sources WHERE id=?", (source_id,)
            ).fetchone()[0]
            if hashlib.sha256(payload).hexdigest() != source_id:
                raise LibraryError("The stored original failed its integrity check.")
            return payload, meta["filename"], meta["mime"]

    def remove(self, source_id):
        with self._connect() as conn:
            self._source(conn, source_id)
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._source(conn, source_id)
            conn.execute(
                "DELETE FROM passages_fts WHERE rowid IN (SELECT id FROM passages WHERE source_id=?)",
                (source_id,),
            )
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
        return {"source_id": source_id, "removed": True, "mode": self.mode}

    def index(self, source_id, *, cancel_check=None):
        """Index one bounded batch; existing batches survive interruption/restart."""
        with self._connect() as conn:
            meta = self._metadata(conn, self._source(conn, source_id))
            try:
                fingerprint = _fingerprint()
            except EmbeddingError:
                return {
                    "source": meta,
                    "remaining": meta["passage_count"],
                    "index_error": "Embedding configuration is incompatible. Saved text remains searchable by keywords.",
                }
            rows = conn.execute(
                "SELECT id,text FROM passages WHERE source_id=? AND (embedding IS NULL OR fingerprint IS NULL OR fingerprint!=?) ORDER BY number LIMIT ?",
                (source_id, fingerprint, INDEX_BATCH_SIZE),
            ).fetchall()
        if not rows:
            return {"source": meta, "remaining": 0}
        if cancel_check and cancel_check():
            raise LibraryError(
                "Indexing cancelled. The original and completed batches are still saved."
            )
        try:
            vectors = get_embeddings_batch(
                [row["text"] for row in rows], role="document", titles=[meta["title"]] * len(rows)
            )
            if len(vectors) != len(rows):
                raise EmbeddingError("Embedding batch count did not match the passages.")
            vectors = [_vector(vector) for vector in vectors]
        except (EmbeddingError, OSError, ValueError) as exc:
            return {
                "source": meta,
                "remaining": meta["passage_count"] - meta["indexed_passages"],
                "index_error": "Embedding service unavailable or incompatible. Saved text remains searchable by keywords.",
                "error_type": type(exc).__name__,
            }
        if cancel_check and cancel_check():
            raise LibraryError(
                "Indexing cancelled. The original and completed batches are still saved."
            )
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._source(
                conn, source_id
            )  # Never resurrect a concurrently removed source.
            if current["created_at"] != meta["created_at"] or current["title"] != meta["title"]:
                raise LibraryError(
                    "This source was replaced during indexing. Retry for the current source."
                )
            for row, vector in zip(rows, vectors):
                conn.execute(
                    "UPDATE passages SET embedding=?,fingerprint=? WHERE id=? AND source_id=? AND text=?",
                    (json.dumps(vector), fingerprint, row["id"], source_id, row["text"]),
                )
            meta = self._metadata(conn, self._source(conn, source_id))
        return {"source": meta, "remaining": meta["passage_count"] - meta["indexed_passages"]}

    def search(self, query, *, source_id=None, limit=6, semantic=True):
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise LibraryError("Search text must contain 1 to 1,000 characters.")
        _integer(limit, "limit", 1, 8)
        if type(semantic) is not bool:
            raise LibraryError("semantic must be true or false.")
        words = list(dict.fromkeys(re.findall(r"\w+", query.lower(), re.UNICODE)))
        terms = [word for word in words if word not in _STOP_WORDS] or words
        expression = " OR ".join('"' + word + '"' for word in terms[:40])
        with self._connect() as conn:
            if source_id is not None:
                self._source(conn, source_id)
            total = conn.execute("SELECT count(*) FROM sources").fetchone()[0] if conn else 0
            if not total:
                return {
                    "passages": [],
                    "retrieval_mode": "empty",
                    "source_count": 0,
                    "mode": self.mode,
                }
            clause = " AND p.source_id=?" if source_id else ""
            args = [source_id] if source_id else []
            lexical = (
                conn.execute(
                    "SELECT p.* FROM passages_fts JOIN passages p ON p.id=passages_fts.rowid WHERE passages_fts MATCH ?"
                    + clause
                    + " ORDER BY bm25(passages_fts,2,1),p.id LIMIT 60",
                    [expression, *args],
                ).fetchall()
                if expression
                else []
            )
            dense = []
            reason = None
            indexed_count = 0
            passage_count = conn.execute(
                "SELECT count(*) FROM passages p WHERE 1=1" + clause, args
            ).fetchone()[0]
            if semantic:
                try:
                    fingerprint = _fingerprint()
                    available = conn.execute(
                        "SELECT count(*) FROM passages p WHERE fingerprint=?" + clause,
                        [fingerprint, *args],
                    ).fetchone()[0]
                    indexed_count = available
                    if available:
                        query_vector = _vector(get_embedding(query, role="query"))
                        for row in conn.execute(
                            "SELECT p.* FROM passages p WHERE fingerprint=?" + clause,
                            [fingerprint, *args],
                        ):
                            score = cosine_similarity(
                                query_vector, _vector(json.loads(row["embedding"]))
                            )
                            if score >= 0.3:
                                dense.append((score, row))
                        dense.sort(key=lambda item: (-item[0], item[1]["id"]))
                        dense = dense[:60]
                    else:
                        reason = (
                            "No compatible indexed passages; use Index to enable semantic search."
                        )
                except (EmbeddingError, OSError, ValueError) as exc:
                    reason = f"Semantic search unavailable ({type(exc).__name__}); showing keyword matches."
                    dense = []
            scores, matches, found = {}, {}, {}
            for kind, ranking in (("keyword", lexical), ("semantic", [row for _, row in dense])):
                for rank, row in enumerate(ranking, 1):
                    key = row["id"]
                    scores[key] = scores.get(key, 0) + 1 / (60 + rank)
                    matches.setdefault(key, []).append(kind)
                    found[key] = row
            passages, metadata = [], {}
            for key in sorted(scores, key=lambda key: (-scores[key], key))[:limit]:
                row = found[key]
                sid = row["source_id"]
                if sid not in metadata:
                    metadata[sid] = self._metadata(conn, self._source(conn, sid))
                passages.append({**self._passage(row, metadata[sid]), "matched_by": matches[key]})
            return {
                "passages": passages,
                "sources": list(metadata.values()),
                "query": query,
                "retrieval_mode": "hybrid" if semantic and not reason else "keyword",
                "semantic_unavailable_reason": reason,
                "source_count": total,
                "mode": self.mode,
                "total_passages": passage_count,
                "semantic_indexed_passages": indexed_count,
                "semantic_coverage_incomplete": semantic and indexed_count < passage_count,
            }
