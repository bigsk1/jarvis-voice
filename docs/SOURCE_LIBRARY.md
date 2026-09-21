# Source Library

Keep original documents in a private Cloud or Local library and retrieve
verifiable passages in Web chat, voice, and Canvas. The library is separate from
Docs, Memory, Stash, and QMD. QMD and ripgrep search repository documentation;
the Source Library searches saved originals in its own SQLite FTS5 store.
The optional [Project NOMAD tool](tools/project-nomad/README.md) connects to a
separate server and archive; its files and ZIMs are not added to this library.

## Use the Web library

Open **Source library** in the Web sidebar. Choose Cloud or Local, click
**Choose files**, review the list, remove any mistakes, then click **Add to
library**. Choosing files alone does not upload them. Each file
gets its own result row and a retry button if its upload fails. A saved source
can be deleted from its reader or **Manage source** menu after confirmation.
Keyword search is ready as soon as a file is saved. Optional semantic
indexing is queued in the library database and runs in a durable worker, even if
the library tab closes. Native Web starts that worker in its process; Docker
Compose starts a separate `jarvis-library-worker` service. **Refresh library
status** checks progress; a failed embedding batch is marked for explicit
retry. Other uploads and mode switching
remain usable while the worker indexes a source.

Search results stay grouped under their source rather than appearing as six
unrelated chunks. Overlapping passages are collapsed but remain expandable and
citable. **Text match**, **Title match**, and **Related by meaning** come from the
server's retrieval evidence; semantic neighbors are never presented as literal
matches. The active query and optional source filter are visible. Clearing the
query, **Clear search**, or **Browse all** restores the document list.

The reader offers **Extracted passages**, **Rendered view**, and **Original / raw**:

- Passages preserve their 1-based citation numbers, PDF page numbers, and
  original-text line/character offsets. Search highlights are high contrast.
- Markdown is rendered locally with raw HTML disabled, no remote images, and a
  sandboxed frame. Text files can be inspected as raw UTF-8. PDF pages are
  rendered on demand from the SHA-verified original using PyMuPDF; the visual
  layout and extracted searchable text can differ.
- The original can be downloaded byte-for-byte. Text notes can be edited in the
  raw view and **saved as a new source**. This makes a new SHA-256 ID and keeps
  old citations valid. Rename changes only the display title and refreshes
  title-dependent search/index data. Remove deletes only the selected mode's
  source after confirmation. There is no in-place byte mutation.

Scanned/empty PDF pages are called out and are not searchable. Use
`document_ocr` separately and save its text/Markdown result as a new source;
the original PDF remains intact. The library does not transcribe audio/video.

## Large batches and persistence

The browser supports multi-file import. For a large offline collection, place
files under `data/source_library/inbox/local/` or `.../inbox/cloud/` (or the
equivalent `SOURCE_LIBRARY_DIR/inbox/<mode>/`), then use **Check inbox** and
**Queue inbox import**. The Web server scans nested directories, skips symlinks,
previews eligible/skipped counts and a conservative disk estimate, and commits
one import receipt per file. It continues importing after the browser closes
or the server restarts. Failed/changed files are visible and can be requeued.
Inbox originals are *not* consumed or deleted. In Docker, the existing
`./data:/app/data` bind mount is the host-side inbox and library store. The
worker creates both `inbox/local/` and `inbox/cloud/` as private directories
on startup, even before a source is saved; restart Web (native) or
`jarvis-library-worker` (Docker) after upgrading an existing installation.
The runtime inbox and its contents are intentionally not tracked in Git.

The default stores are `data/source_library/cloud.db` and `local.db`. A custom
`SOURCE_LIBRARY_DIR` needs a persistent Docker mount of its own. Source IDs are
the SHA-256 of original bytes and deduplicate within one mode; modified bytes
make another source. Switching modes never copies or merges data. The mode
store includes originals, passages, FTS rows, vectors, and durable import/index
jobs. Browsing an empty library does not create a database. In a native launch,
Web owns the worker; in Docker the separate worker can continue while Web
restarts. Queued work resumes when its worker starts again.
On POSIX, the library directory must be owned by the Jarvis process; Jarvis
tightens it to `0700` and refuses a symlinked library directory or database.
Linux pins the opened directory through `/proc/self/fd` while SQLite opens the
database, including inside Docker on a macOS/Windows host. Native macOS and
Windows do **not** have that pin: replacing the checked directory between the
check and SQLite open remains a path-race risk if its parent is writable by an
attacker. Docker bind mounts, including a custom `SOURCE_LIBRARY_DIR`, must be
owned by the container UID (`JARVIS_DOCKER_UID`) or library requests return 503.
On Docker Desktop, check the ownership seen *inside* the container after
creating an inbox on the host; host ownership may not map as expected.

The Source Library page now warns when its mode's worker process is not
running. Docker also marks `jarvis-library-worker` unhealthy when either mode's
worker lock is not held. This checks process presence, **not** job progress;
inspect the library job states and `docker compose logs jarvis-library-worker`
if work is stuck. A failed library blueprint import leaves chat available and
the library API returns 503. An unsafe/unavailable store also returns 503 for
its requests. A native worker-start failure leaves Web running, but queued
work pauses. These are not guarantees against a native crash or process OOM:
interactive upload/PDF extraction, inbox scan/queue, search, on-demand render,
and explicit Web `POST /<id>/index` still run in Web. The tool's explicit
`index` action runs in its tool process. The Docker service isolates the
durable bulk import/index loop, not every library request or a host-wide outage.

One file is limited to 25 MB, 1,000,000 extracted characters, and 1,000 PDF
pages. Supported suffixes: `.pdf`, `.txt`, `.md`, `.markdown`, `.csv`, `.json`,
`.srt`, `.vtt`, `.log`. No new ANN service or larger file limit was chosen
without measurements. A synthetic 1,000-source / 3,000-passage isolated
benchmark showed roughly 2–8 ms keyword retrieval and 39 ms hybrid retrieval
after packed-vector optimization on this machine. A second 2,000-source /
16,000-passage run showed 2–29 ms keyword and 164 ms median hybrid search.
Run
`.venv/bin/python bin/benchmark-source-library.py` to measure yours; the
script uses a temporary database and synthetic embeddings, never personal data.

## Backup, restore, and offline readiness

Keep private backups of *both* mode databases; backing up `jarvis_memory.db`
does not back up this library. The included CLI uses SQLite's backup API and
checks database integrity, FTS row count, references, and every original's
SHA-256 before publishing a backup or restoring it:

```bash
.venv/bin/python bin/source-library-backup.py backup --mode local --output /private/backups/library-local.db
.venv/bin/python bin/source-library-backup.py verify --input /private/backups/library-local.db
.venv/bin/python bin/source-library-backup.py restore --mode local --input /private/backups/library-local.db
.venv/bin/python bin/source-library-backup.py restore --mode local --input /private/backups/library-local.db --apply
```

Restore is a dry run by default, reports required/free disk, and refuses to
overwrite any existing target database. Restore to a missing mode store only;
do not copy a live SQLite file while Web is writing. Backups should remain
outside Git, Docker build contexts, and shared folders.

`Local` only selects `local.db`; it does not itself make Jarvis air-gapped.
Ollama's embedding host chain includes `OLLAMA_EMBEDDING_FALLBACK_URL`, and the
chat model may also be remote. Run
`.venv/bin/python bin/check-source-library-offline.py` for a strict native
preflight: every effective embedding/LLM host must be loopback, the model must
be local, and library assets must be self-hosted. With a real local Ollama
daemon, `--exercise` creates a temporary library, imports/renders/searches a
note, asks the local LLM about a retrieved fact, probes embeddings, and blocks
non-loopback sockets in that process. This is a process-level proof, not a
system-wide network disconnect. The current repository `local.env` lists a
LAN Ollama host, so strict preflight fails until the host chain is changed.
Docker's `host.docker.internal` is also not loopback and needs a separate
container-level offline isolation test; do not interpret Local mode alone as
an air gap.

## Retrieval and citations

Passages are up to 1,800 characters, with 240 characters of overlap inside a
text file or PDF page. `read` starts at passage 1 and returns `next_passage`.
PDF offsets refer to sorted text extraction, not visual coordinates. Text
offsets refer to decoded UTF-8; the original preserves its BOM/line endings.
Character offsets are zero-based/end-exclusive; page and line numbers start at
1. Keyword search uses Unicode tokens with SQLite FTS5; segmentation of
unspaced CJK text remains a known limitation. Semantic search uses compatible
768D Ollama embeddings and reciprocal-rank fusion. Existing JSON vectors are
still readable; new vectors are stored as compact float32 bytes. If embeddings
are absent, incompatible, or unavailable, keyword search remains available and
coverage/reason are reported. A no-hit result is not proof that an original
contains no answer.

Source text is evidence, never instructions. Search excerpts are incomplete;
read the cited passage or source before making a strong claim. Private Jarvis
links in Canvas do not publish originals to public Canvas viewers.

The `source_library` tool supports `save`, `search`, `read`, `list`, `index`,
`rename`, and `remove`. Saving queues semantic work for the library worker;
`index` is still
an explicit one-batch manual action if the worker is not running. The exact
`source_id` is required for read, rename, remove, or in-source search. After a
tool manifest change, refresh Tool RAG in each mode with the documented
`bin/sync-tools.py` procedure and restart Jarvis processes.

Authenticated Web routes use `?mode=cloud|local`:

| Route | Purpose |
|---|---|
| `GET/POST /api/library` | Browse/search or multipart save |
| `GET/PATCH/DELETE /api/library/<id>` | Read, rename, or remove |
| `GET /api/library/<id>/download` | Verified original attachment |
| `GET /api/library/<id>/text` | Raw UTF-8 original |
| `GET /api/library/<id>/rendered` | Safe rendered Markdown |
| `GET /api/library/<id>/page/<n>` | Rendered original PDF page |
| `POST /api/library/<id>/copy` | Save edited text as a new source |
| `POST /api/library/<id>/queue` | Queue/retry durable semantic indexing |
| `POST /api/library/<id>/index` | Manual one-batch indexing |
| `GET /api/library/status?ids=...` | Bounded visible-card index status |
| `GET /api/library/worker` | Mode worker liveness (not job progress) |
| `GET /api/library/inbox` | Read-only inbox/disk/job preview |
| `POST /api/library/inbox/queue` | Queue inbox import |

## Focused verification

The isolated test suite covers original-byte integrity, citations, FTS match
reasons, legacy vectors, worker restart/error/retry, mode isolation, inbox
imports, rendered views, edited copies, backup/restore, and browser lifecycle:

```bash
.venv/bin/python -m pytest tests/test_source_library.py tests/test_source_library_jobs.py tests/test_source_library_archive.py tests/test_source_library_offline.py tests/test_web_source_library.py tests/test_source_library_ui.py -q
```
