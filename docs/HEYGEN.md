# Optional HeyGen video integration

HeyGen uses its v3 HTTPS API and the API wallet associated with the active
mode's `HEYGEN_API_KEY`. It does not use HeyGen's OAuth MCP subscription credits.
There is no extra enable flag: a missing, blank, or commented key hides HeyGen's
provider/model choices, dedicated tools, credential card, and demo workflow from
the Web UI. Runtime preflight also rejects calls without the key. Cloud and local
mode credentials remain independent.
Bundled profiles that disable cloud video generation also disable the dedicated HeyGen
tools, including the OpenAI-only and offline templates.
Older installed or custom profiles with `generate_video: false` also disable
the new HeyGen tools unless an explicit per-tool override enables them. No
private profile files need to be replaced or recopied.

```bash
# config/cloud.env; add separately to local.env only if external video is wanted there.
HEYGEN_API_KEY=your-api-key
# Optional model pin and maximum observer wait (0-900 seconds).
# HEYGEN_VIDEO_MODEL=heygen-video-1
# HEYGEN_WAIT_SECONDS=300
```

Adding the key does not change `VIDEO_TOOL_PROVIDER`. Choose HeyGen in the media
modal, or deliberately set `VIDEO_TOOL_PROVIDER=heygen` to change the default.
If a selected HeyGen provider loses its key, Settings and the media modal ask
you to choose a video provider. They do not display xAI as a replacement or
silently change the saved selection. Restore the key to restore that selection,
or explicitly choose another available provider.
After adding/removing credentials, reload Settings/tools; restart native
services or recreate Docker services when their startup environment changed.
New tool definitions also need the normal Tool RAG sync in the affected mode.
Use the production environment for that command, not repository `.venv`:

```bash
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
```

## Tools

### `generate_video` with HeyGen

HeyGen Video 1 supports text-to-video and a still image as the first frame,
including generated dialogue/ambience. This release accepts whole durations of
5-15 seconds and `480p`, `768p`, `1080p`, or `2k`; the generic `720p` default maps
to HeyGen's actual `768p` and the result reports that actual resolution. Supported
landscape/portrait/square aspect ratios come from the model catalog. Image mode
follows the supplied image rather than promising to resize it.
The new `21:9`, `768p`, and `2k` choices are rejected before submission when
the selected provider is xAI or Gemini; they cannot silently buy a differently
sized clip from another provider.

```json
{"prompt":"Slow camera movement and gentle waves; quiet ocean ambience.","provider":"heygen","duration":5,"resolution":"480p","image_url":"stash://space_example/f_example"}
```

Saved Web/ENV settings control normal model-selected tool calls. Explicit media
modal/API selections use a temporary trusted scope. A deterministic workflow can
likewise declare a literal `params.provider` for a media step without changing
the saved default; model-filled or query-substituted providers cannot create that
scope.

### `generate_avatar_video`

Create a short Avatar IV presenter video using exactly one existing avatar look
or photo and exactly one script or audio recording. Discover real IDs first with
`heygen`: avatar **look IDs**, not group IDs, are passed as `avatar_id`.
Saved-avatar requests explicitly select Avatar IV. Photo requests use HeyGen's
implicit photo engine and omit `engine`, which the strict `type: image` request
schema does not accept.

```json
{"image_source":"stash://space_example/f_portrait","script":"Welcome to Jarvis Voice. Your assistant. Your choice.","voice_id":"a-real-discovered-voice-id","resolution":"720p"}
```

For existing audio, replace `script` and `voice_id` with `audio_source`. This
accepts a Stash reference, local file, or public HTTPS URL. This lets an existing
ElevenLabs or other TTS output pass through Stash without regenerating its voice
inside HeyGen. Scripts are preserved exactly and limited to 75 words/1,000
characters; audio is limited to 30 seconds. PNG/JPEG photos and WAV/MP3 audio are
accepted, up to 32 MB each. MP3 duration validation uses the existing `ffprobe`
command; WAV validation uses Python's standard library. Local inputs are uploaded
as HeyGen assets, never exposed through a temporary public Jarvis URL.

### `heygen`

- `account`: API wallet/subscription status without personal profile fields.
- `list_avatars`, `list_voices`: paginated, bounded IDs and preview metadata.
- `status`: check an existing `video_id`, with `kind=model` or `kind=avatar`.
- `collect`: retrieve a completed existing job into Stash and the video gallery.

```json
{"action":"collect","video_id":"the-original-provider-video-id","kind":"model"}
```

Collection is idempotent for the same job. It does not submit a new render. Saved
artifacts include the provider, model, native ID, MIME type, gallery file and
Stash reference. Media catalogs and Stash remain shared artifact surfaces, as
before; each submission receipt records the original credential mode.

## Jobs, costs and interruption

Generation submits once with a fresh idempotency key. A request receipt is saved
in Stash before submission; the returned native ID is saved and emitted as tool
progress before polling. Submission rejection, confirmed provider failure,
completed generation with a local save failure, and unknown completion remain
distinct. Never rerun generation merely to check progress.
An interrupted intro workflow includes validated job/request IDs and its Stash
receipt in the visible failure message and failed tool card when available.
Use those identifiers to inspect or collect existing work; the workflow does
not automatically submit a replacement.

Web can opt the generation tools into the existing Linux background worker.
Voice, CLI, workflow and foreground clients use a bounded observer wait. A lost
observer does not cancel HeyGen's paid work. The generic remote adapter does not
automatically resume polling after worker restart: use the retained ID with
`heygen status/collect`. A submission whose response was lost may have only a
request receipt, not a native video ID; inspect the provider before authorizing
another submission.

Estimates use the published rates reviewed on 2026-10-26: short text/image clips
are $0.01/s at 480p, $0.018/s at 768p, $0.04/s at 1080p and $0.05/s at 2K. Avatar IV
photo and studio/digital-twin rates differ; script-based estimates use an
approximate speaking speed and are not invoices. Billing and generation quality
must be checked against the actual wallet/provider result. There is no automatic
paid fallback, retry, auto-reload, training, voice cloning, batch generation,
Video Agent, reference-to-video or real-time LiveAvatar in this integration.

## Demo workflow

Run `/heygen_intro` explicitly. It checks account access, retains the public
[Jarvis Voice README](https://github.com/bigsk1/jarvis-voice), generates original
first-frame artwork with the configured image tool, uploads its Stash reference
to HeyGen for one 8-second 480p clip, and links the results in Canvas. Each run
starts new paid work: approximately $0.08 for HeyGen plus the configured image
and helper-model usage. The recipe is excluded from autonomous workflow-tool
selection. A failed optional Canvas step does not discard the completed video.
If generation is interrupted, collect the existing ID rather than rerunning.

## Installation and interfaces

No new SDK, Python dependency, database schema, port or service is required.
Foreground and background local tools have separately reviewed restricted child
environments. The shared video tool receives its supported provider settings and
the embedding settings used by its existing optional artifact-memory index;
HeyGen-only tools receive only their own key/settings, Stash paths and common
runtime/TLS settings. The audio-probe subprocess receives no API credentials.

Native Linux and Docker can use the existing worker. Native macOS supports
foreground/status operation, while background jobs require the Linux Docker
worker. Temporary audio downloads and atomic video saves use Python-managed
temporary directories or files beside the destination, not a hardcoded `/tmp`.
Firefox can view the resulting media and Web task updates without a new extension
release; its existing background-admission limitations remain unchanged.

FastAPI adds `heygen` to `/api/generated-videos/generate` and exposes:

- `GET /api/heygen/account`, `/avatars`, `/voices`
- `POST /api/heygen/avatar`: submit once and return an HTTP 202 native receipt
- `GET /api/heygen/status/{video_id}?kind=model|avatar`
- `POST /api/heygen/collect`: collect an existing completed job

All use the caller-selected mode and existing API authentication. Missing key
requests fail before a provider call; no incoming provider webhook is necessary.

Sources: [HeyGen Video](https://developers.heygen.com/docs/models/heygen-video),
[avatar videos](https://developers.heygen.com/reference/create-video),
[asset uploads](https://developers.heygen.com/docs/upload-assets),
[current API pricing](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained),
[v3 migration](https://developers.heygen.com/endpoint-version-comparison).
