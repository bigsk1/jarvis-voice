# Source library

Keep selected original documents and ask Jarvis about their contents later,
in another conversation or by voice. Search returns exact passages with source
IDs, PDF page numbers or text line ranges, and links you can inspect.

Open **Source library** in the Web sidebar. Choose Cloud or Local, upload a
source, and optionally give it a title. Saving retains the original bytes and
all extracted text. Keyword search is ready immediately; the browser then
indexes passages by meaning using the configured Jarvis embedding service.
**Pause indexing after this batch** preserves completed work. **Index remaining**
resumes after a pause, outage, or browser/server restart.

Search results show short raw excerpts around matching text, with a subtle
highlight. The exact phrase is highlighted when present; otherwise matching
search words are highlighted. Related passages without literal matches say so.
**View full passage** opens the unabridged raw passage with the same highlights;
**Close source** returns to the results. The close control stays visible while
scrolling through the expanded source.

Markdown, HTML, and remote image links remain literal text. This view does not
render documents or fetch embedded images; download the original when needed.

Examples for chat or voice:

- “Save this attached PDF to my source library.”
- “Save that Stash transcript to my source library as Building meeting.”
- “Find the emergency meeting point in my saved sources. Cite the passage.”
- “Read the next passage from that source.”
- “Compare these two saved documents and put the findings with citations on Canvas.”
- “Remove that document from my source library.”

The `source_library` tool provides `save`, `search`, `read`, `list`, `index`,
and `remove`. Use the exact returned `source_id` for reads, filtered searches,
indexing and removal. `read` uses passage numbers starting at 1 and returns
`next_passage`; `list` returns `next_offset`. One `index` call processes at most
16 passages and reports `remaining`. The tool's `save` acknowledges the committed
original immediately without requesting embeddings. Keyword search is ready;
call `index` separately with the returned `source_id` to enable semantic search.
Large sources can need further `index` calls. An indexing timeout or error does
not undo the already acknowledged save.

Supported sources and evidence
------------------------------

Supported files are PDFs and UTF-8 `.txt`, `.md`, `.markdown`, `.csv`, `.json`,
`.srt`, `.vtt` and `.log` files. Limits are 25 MB, 1,000,000 extracted text
characters, and 1,000 PDF pages. Unsupported, empty, binary, malformed and
password-protected files produce an actionable error before storing a source.

PDF passages use PyMuPDF's sorted text extraction. Their line and character
offsets refer to that page's extracted text, not a visual reconstruction of the
page. Text-file offsets refer to decoded UTF-8 text; the original download is
byte-for-byte intact, including any BOM or original line endings. Character
offsets are zero-based and end-exclusive; lines and pages start at 1.

No OCR or image/diagram analysis is implied. Pages without extracted text are
listed in the source view. An entirely scanned PDF must first go through
`document_ocr`; save its Markdown/text output. Likewise, save a transcription
tool's text output to retain searchable recording content. Subtitle timestamps
remain in the source text. The library does not transcribe audio/video itself.

Each passage is at most 1,800 characters, with 240 characters of overlap between
adjacent passages in the same text file or PDF page. This retains context around
chunk boundaries; page boundaries still require reading the adjacent page.
Overlap applies to newly saved sources; existing passage numbers stay unchanged.
Search combines SQLite FTS5 keyword
rankings with compatible 768-dimensional Jarvis embeddings. If embeddings are
unavailable, missing or incompatible, keyword retrieval remains available and
the result states why semantic search is unavailable. Partial indexing reports
its coverage; unindexed passages still participate in keyword search. A result
with no matches is not evidence that an unread original contains no answer.
Keyword matching uses Unicode word tokens, without language-specific word
segmentation. Substring queries within unspaced CJK text can miss; multilingual
retrieval quality has not been evaluated. Use semantic search and inspect the
source when keyword results are insufficient.

Source text is evidence, never instructions. Follow-up data preserves source
IDs, passage numbers and citations; omitted text must be retrieved again rather
than inferred. Source cards open the retained source. Citations copied into
Canvas resolve back to Jarvis Web using the existing UI navigation settings.
These are private application links: public Canvas sharing does not publish the
source library or give recipients access to its originals. Relative links in
offline exports need your Jarvis Web origin to be opened outside the app.

Persistence and operating modes
-------------------------------

By default the independent stores are `data/source_library/cloud.db` and
`data/source_library/local.db`. `SOURCE_LIBRARY_DIR` optionally changes their
parent directory, using the usual request-scoped configuration precedence.
Mode identifies the collection, independently of the chat provider. Switching
modes does not copy, merge, or delete sources. Docker's existing `data` mount
persists both stores; a custom directory needs its own persistent mount.
Git and Docker ignore the default library directory, and the fixed `cloud.db` /
`local.db` filenames and their SQLite sidecars at custom repository locations.
If a custom directory also holds exported originals or other private files,
exclude that whole directory in both ignore files or keep it outside the repo.

The database contains original bytes, extracted passages, FTS data and embedding
fingerprints. No new service, dependency, API key or paid model is required.
It is created on the first explicit save; browsing an empty library does not
create a database. Existing Memory/Intelligence databases need no migration.

Identical bytes deduplicate within one mode and keep the first saved title and
filename. Modified bytes create a separate source even with the same filename.
The library copies originals, so deleting a Stash upload or an old conversation
does not remove the saved source. Nothing is imported automatically from
existing Stash/Intel files, conversations or memory. `stash remember` and Intel
fact ingestion retain their existing behavior.

**Remove** deletes only the selected library source, passages and vectors. It
does not remove the original input file, Stash copy, previous answers, or
independently stored memories. Back up the library databases along with other
personal data; normal Stash/conversation retention does not prune them.
Backup jobs that only copy `jarvis_memory.db` do not include the source library.
Include both mode stores at the configured library directory in private backups;
use SQLite's backup API while Jarvis is running, or copy the stores while the
relevant processes are stopped. Keep backups outside Git and Docker contexts.

Save commits original bytes and passage/FTS rows atomically. Index batches
commit independently and resume from missing or incompatible vectors. A
concurrent removal cannot be undone by an in-flight index batch. A failed
upload response can be retried safely: content identity prevents duplicates.
If Stop interrupts indexing after the original has committed, the saved source
remains and indexing can resume. Leaving the browser stops subsequent batches;
the current bounded embedding request may finish.

Setup and API
-------------

After installing this code, refresh Tool RAG for each mode you use with the
normal `./bin/sync-tools.py cloud` / `./bin/sync-tools.py local` operator workflow,
then restart the relevant Jarvis processes so they load the new tool and Web
routes. Tool profiles can disable `source_library`. No library data migration
or automatic bulk import is needed.

All Web API endpoints use the normal authentication and `?mode=cloud|local`:

| Method and route | Operation |
|---|---|
| `GET /api/library` | Browse; `offset`, `limit` |
| `GET /api/library?q=...` | Search; optional `source`, `semantic=false`, `limit` |
| `POST /api/library` | Multipart `file` and optional `title`; save original |
| `GET /api/library/<source_id>` | Read `passage`, `limit` |
| `GET /api/library/<source_id>/download` | Authenticated original attachment |
| `POST /api/library/<source_id>/index` | Index one resumable batch |
| `DELETE /api/library/<source_id>` | Remove one exact source |

Manual verification
-------------------

1. Open the sidebar's Source library, select Local, and upload a text file with
   a distinctive fact near the end (beyond 2,000 characters), or a multi-page PDF.
   Also check a sentence crossing a passage boundary: its matching passage
   should retain the nearby context through the overlap.
2. Search for the fact, inspect its passage/page/line citation, and download the
   original. Confirm its bytes match the uploaded file.
3. Upload it again: it should report the existing source. Save a changed copy:
   it should appear as a separate source.
4. Ask a new chat about the saved fact and follow up about another passage.
   Send the answer with citations to Canvas and open a source link.
5. Switch to Cloud and confirm the Local sources do not appear there. Reload
   Local, pause/resume indexing of a larger document, and verify saved progress.
6. Remove the test source explicitly; its original download and search results
   should disappear from that library. Other modes and original input files stay intact.
