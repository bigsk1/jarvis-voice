# Mixed-source requests in Jarvis Web

Attach several PDFs, notes, recordings, videos, and images to one message, then ask
Jarvis to compare them, extract decisions, or build a report from the combined
material. For example: attach two proposals, a screenshot, and a voice note,
then ask “Compare the proposals against the requirements in my recording and
screenshot. Cite the sources for each difference.”

Use the paperclip or drag files onto the composer. Document cards are numbered
**Source 1**, **Source 2**, and so on; images have their own **Image 1**,
**Image 2** numbering. These labels follow the displayed document/image order.
Filenames plus exact Stash references distinguish sources with the same name.
Remove individual cards before sending if needed.

## Limits and supported modes

| Constraint | Behavior |
|---|---|
| Total selected sources | 6 in cloud mode; 2 in local mode, including images |
| Text/Markdown | UTF-8 `.txt` and `.md`; at most 100KB combined |
| PDF | Existing 50MB default per-file upload limit |
| Images | Existing 30MB per-image upload limit; choose Analyze for mixed requests |
| Recordings | Existing `AUDIO_TRANSCRIBE_*` size, duration, and provider limits |
| Videos | Up to 250MB / two hours; analyze up to five minutes and six sampled frames per tool call |
| Image editing/video generation | One reference image; send other sources separately |
| Chat only | Text notes allowed; images, PDFs, recordings, and videos require tools enabled |

The same Web behavior is available natively and in Docker. Uploads and their
validation use the selected cloud/local configuration. Local mode retains its
existing provider and tool-profile restrictions; uploading a source does not
enable an unavailable transcription, OCR, or vision provider. Video containers
use [video analysis](tools/video/ANALYSIS.md), including silent clips; audio-only
MP4/WebM containers retain the audio transcription path.
Switching to local mode never silently drops excess sources: remove enough
cards before sending.

## Upload, processing, and retry

PDFs, recordings, and notes are uploaded on Send. Selecting them does not run
models or tools. Images retain their existing selection-time upload and action
picker. Nothing is submitted to chat until all selected uploads succeed.

If an upload fails, the draft remains available. Successful document uploads
retain their references and retry identities. Failed image selections remain
visible with Retry/remove controls and block Send until resolved. Stop during
preparation prevents submission; switching conversations prevents a late
upload from being sent into the new conversation.

While a conversation is loading, Send and new attachments are paused. A
successful switch clears the selected sources with a notice. A failed load or
refresh of the same conversation keeps them available; New chat clears them.

An uploaded PDF/audio filename is metadata, not evidence of its contents.
Jarvis must read the exact PDF or transcribe the exact recording before making
content claims. Text is read from the committed server copy. Image analysis
receives the image pixels and original question, separately from the documents.

If image analysis fails in a mixed request, Jarvis can continue with the other
sources. The response explicitly names the unavailable images and remains a
partial result. If another tool also fails, that failure remains visible.
Image-only requests retain their existing retryable vision-error behavior.
Stopping during server preparation is recorded in conversation history. Stop
during browser uploads keeps the draft without submitting a conversation turn.

## Follow-up questions and retention

The saved conversation retains source references, filenames, and ordering.
After reload, ask “What did Source 2 say about delivery?” or “Compare the two
transcripts.” Repeated reads and transcriptions retain separate source/output
references rather than collapsing to the last tool result.

Workflow source steps also retain their resolved input identities, including
individual loop iterations. Saved results from older workflows may lack that
metadata; Jarvis must reread the source when its output cannot be matched
reliably. Skipped results retain their original execution positions, with
unsupported-result omissions distinguished from the history size limit.

History includes all source handles separately from the ordinary prose limit.
Text excerpts share a 4,000-character budget per prior bundle, with an explicit
excerpt marker. Jarvis can retrieve the original text through Stash when more
is needed; Chat only cannot perform that retrieval. The normal conversation
history window still applies.

Source download links and audio players retain the source's original mode.
Model follow-up reads use the current request mode. If cloud and local use
different `STASH_DIR` directories, return to the source's original mode or
attach it again after switching modes.

New text uploads use the existing `source_artifact` retention policy, default
120 days, like uploaded PDFs and recordings. An expired/missing source must be
attached again. Images retain their existing image Stash/upload retention.
This feature is not permanent corpus ingestion and does not migrate missing
contents from old text-only chats: older clients previously saved only a name.

## Implementation and compatibility

- `client/js/chat.js`: ordered document selection, image retry queue, request
  ownership, upload/send, and source previews; `app.js` restores all sources.
- `server/services/text_upload.py`: bounded UTF-8 validation, atomic commit,
  integrity checks, and idempotent retries. `/api/upload-text` follows existing
  authenticated upload routes; its optional
  `WEB_TEXT_UPLOAD_RATE_LIMIT_PER_MINUTE` defaults to 12 (0 disables that limiter).
- `server/services/attachment_bundle.py`: count/type/reference validation and
  bounded saved metadata. Existing single PDF/audio payloads remain valid;
  legacy `file_context` text is committed through the same trusted text boundary.
- `server/sockets/chat.py`: mode-scoped intake, source-aware prompts, separate
  image evidence, partial failures, and preparation cancellation.
- `server/services/followup_extractor.py` and `orchestrator/context_assembler.py`:
  separate repeated source results, original versus generated references, and
  bounded source context outside ordinary prose truncation.
- `orchestrator/pipeline_executor.py`: source-only arguments bound to each
  successful workflow step/iteration, preserved through saved result flattening.

These changes add metadata to existing conversation JSON and use the existing
Stash format. There is no database migration, new dependency, new tool, or
required configuration setting. Existing tool permissions, provider choices,
explicit workflows, and Send to Canvas remain in place.

## Manual verification

1. In cloud mode, attach two different small PDFs with the same filename, a
   UTF-8 note, a short recording, and an image. Confirm every selected item is
   visible, then request a comparison with source citations.
2. Confirm PDF/transcription tools access the sources before content claims.
   Inspect the response and source links/players. Reload and ask a specific
   question about Source 2 and the recording.
3. In local mode, select two sources; adding a third must leave the existing
   draft intact and explain the limit. Text-only Chat only should work; adding
   a PDF should ask you to turn Chat only off.
4. Simulate an upload failure using browser network controls. The draft must
   remain, and Send must not submit a subset. Restore connectivity and retry.
   Stop or switch conversations during an upload and confirm no stale send.
5. With a deliberately unavailable vision provider in a test setup, submit an
   image plus a note. The response must identify the missing image evidence and
   preserve the note. Image-only failure should remain retryable.

Automated coverage uses synthetic files, temporary Stash/conversation storage,
mocked providers, and executable Node browser-state tests. It does not certify
live provider answer quality or hardware performance.
