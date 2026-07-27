# `generate_music` tool

AI music generation for Jarvis. The tool creates songs, instrumentals, jingles,
beats, and soundtracks, then makes saved tracks available to chat, stash, the
Canvas Audio Gallery, and the generated-music FastAPI.

ElevenLabs is the only implemented provider today. Provider selection is kept
behind a stable `provider` contract so additional music services can be added
without changing callers.

## Files

| File | Purpose |
|------|---------|
| `skills/generate_music.py` | Provider resolution, generation, durable save, stash save, and catalog update |
| `skills/generate_music.tool.json` | Tool schema, permissions, and provider availability |
| `api/routes/generated_music.py` | FastAPI generation, health, and saved-track streaming |
| `lib/audio_catalog.py` | Provider-neutral Audio Gallery metadata |
| `jarvis-canvas/server/routes/audio_gallery.py` | Audio Gallery list, playback, favorite, download, and delete routes |
| `jarvis-web/data/prompts/generate_music.md` | `@generate_music` prompt guidance |
| `data/generated_music/audio_catalog.json` | Durable generated-track metadata |

## Configuration

Add the provider and its credential to the active mode file:

```bash
# config/cloud.env or config/local.env
MUSIC_TOOL_PROVIDER="elevenlabs"
ELEVENLABS_API_KEY="..."
```

Provider resolution order:

1. Per-call `provider`
2. `MUSIC_TOOL_PROVIDER` in the active mode configuration
3. `elevenlabs`

An unknown provider returns an explicit error. It does not silently fall back
to ElevenLabs.

The tool availability manifest also uses `MUSIC_TOOL_PROVIDER` to apply the
credential requirements for the selected adapter. Currently, `elevenlabs`
requires `ELEVENLABS_API_KEY`.

## Usage

### Jarvis

```bash
jarvis cloud "Create a 30 second upbeat jazz jingle"
jarvis cloud "Make a two minute instrumental lo-fi study track at 75 BPM"
```

In Jarvis Web, type `@generate_music` to load the music-prompt guidance before
describing the track.

### Direct tool invocation

Use the repository environment:

```bash
.venv/bin/python skills/generate_music.py '{
  "prompt": "Warm cinematic ambient music for a space documentary",
  "title": "Deep Orbit",
  "duration_seconds": 45,
  "genre": "cinematic",
  "mood": "hopeful",
  "instrumental": true,
  "tempo": "slow",
  "output_format": "mp3_high",
  "save": true
}'
```

The process writes one JSON result to stdout and exits nonzero with a structured
JSON error when generation fails.

### FastAPI

```bash
curl -X POST http://localhost:8880/api/generated-music/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Warm cinematic ambient music for a space documentary",
    "title": "Deep Orbit",
    "duration_seconds": 45,
    "instrumental": true
  }'
```

See [Generated Music API](../../api/GENERATED_MUSIC.md) for the complete HTTP
request, response, health, authentication, rate-limit, and streaming contract.

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `prompt` | string | Yes | — | Description of the desired music |
| `title` | string | No | Prompt excerpt | Display title and filename basis |
| `duration_seconds` | integer | No | `60` | Length from 3 to 600 seconds |
| `genre` | string | No | — | Genre or production style |
| `mood` | string | No | — | Emotional direction |
| `instrumental` | boolean | No | `false` | Exclude vocals |
| `tempo` | string | No | — | `slow`, `medium`, `fast`, or a BPM value |
| `output_format` | string | No | `mp3_medium` | MP3 or Opus quality preset |
| `composition_plan` | object | No | — | Structured sections, styles, and lyrics |
| `provider` | string | No | Configured provider | Per-call provider override |
| `save` | boolean | No | `true` | Keep durable, stash, catalog, and memory records |

The public tool and FastAPI contracts expose these formats:

| Preset | Provider format |
|--------|-----------------|
| `mp3_low` | `mp3_22050_32` |
| `mp3_medium` | `mp3_44100_128` |
| `mp3_high` | `mp3_44100_192` |
| `opus_low` | `opus_48000_32` |
| `opus_medium` | `opus_48000_128` |
| `opus_high` | `opus_48000_192` |

## Prompt-based generation

The simple path adds structured hints to the supplied prompt:

- A known `genre` expands to a production-oriented genre hint.
- `mood` is added as an emotional direction.
- `tempo` is added as a speed direction.
- `instrumental=true` is sent as the provider's force-instrumental option.

Example:

```json
{
  "prompt": "A focused background track with mellow piano and vinyl texture",
  "title": "Late Night Focus",
  "duration_seconds": 90,
  "genre": "lo-fi",
  "mood": "calm",
  "tempo": "75 BPM",
  "instrumental": true
}
```

Good prompts name the intended use, instrumentation, energy, musical arc, and
whether vocals are wanted. Describe musical characteristics directly instead
of using an artist name as the only style description.

## Composition plans

Use `composition_plan` when the track needs explicit sections or lyrics:

```json
{
  "prompt": "An uplifting orchestral theme",
  "title": "New Horizon",
  "instrumental": true,
  "composition_plan": {
    "global_styles": ["cinematic", "orchestral", "polished production"],
    "sections": [
      {
        "section_name": "intro",
        "duration_seconds": 20,
        "styles": ["soft strings", "restrained dynamics"],
        "lyrics": []
      },
      {
        "section_name": "theme",
        "duration_seconds": 40,
        "styles": ["full orchestra", "rising brass"],
        "lyrics": []
      }
    ]
  }
}
```

FastAPI validates a maximum of 20 sections, 3–120 seconds per section, and 600
seconds total. When a composition plan is present, its section durations control
the generated length instead of `duration_seconds`.

## Provider implementation

The current ElevenLabs adapter:

- Uses model `music_v1`
- Sends simple generation to `POST /v1/music`
- Sends detailed-response generation to `POST /v1/music/detailed`
- Sends structured composition plans through the composition-plan payload on
  `POST /v1/music`
- Uses a provider timeout of at least five minutes and scales it to three times
  the requested duration
- Returns provider, model, format, song ID, MIME type, and byte size metadata

The FastAPI wrapper is synchronous and invokes the tool in a subprocess with the
requested `JARVIS_MODE`. Its timeout is at least ten minutes and scales for
longer tracks.

## Storage and discovery

With `save=true`, one generation is projected into several surfaces:

```text
generate_music
    |
    +-- data/generated_music/<filename>      durable gallery file
    +-- data/generated_music/audio_catalog.json
    +-- data/stash/<space>/                  workflow copy
    +-- memory DB stash_artifact record      later discovery
```

The durable file is written before the stash copy. If stash is unavailable, the
track and audio-catalog entry remain available and the response includes a stash
failure note.

`audio_catalog.json` stores provider-neutral metadata including title, prompt,
provider, model, genre, mood, tempo, duration, format, favorite state, stash
reference, and creation time. Catalog updates preserve an existing favorite.

### Retention

`cleanup-audio` only handles runtime TTS/STT files under `audio/`; it does not
scan `data/generated_music/`. `cleanup-all` currently has no local-file cleanup
for generated music. The separate stash copy remains subject to stash retention.

## Audio Gallery

Open:

```text
http://localhost:8890/audio-gallery
```

The Canvas Audio Gallery provides:

- Audio playback with exclusive-playback behavior
- Search and sorting
- Provider and favorites filters
- Provider, format, duration, and size metadata
- Favorite, download, and delete actions
- Responsive navigation with the music-note icon on narrow screens

Gallery favorites are stored in `audio_catalog.json` and survive catalog
backfills and metadata updates.

The first version does not include audio conversion, trimming, splicing, or
"use in video" actions. Downloaded files can be edited with an external audio
tool until a first-class editing workflow is added.

## FastAPI boundaries

The generated-music API exposes:

| Method | Route | Purpose |
|--------|-------|---------|
| `POST` | `/api/generated-music/generate` | Generate a track |
| `GET` | `/api/generated-music/health` | Provider and storage readiness |
| `GET` | `/api/generated-music/{filename}` | Stream a durable track inline |

All routes pass through the shared FastAPI authentication and rate-limit
middleware. When global API rate limiting is enabled, non-loopback requests to
`/api/generated-music/*` have a separate default limit of 10 requests per minute
per IP, configurable with `API_RATE_LIMIT_GENERATED_MUSIC_PER_MINUTE`. Loopback
requests are trusted and exempt, matching the other API buckets.

Direct durable-file streaming does not resolve through stash. The route accepts
only recognized audio extensions, rejects path separators and traversal, checks
that the resolved file remains under `data/generated_music/`, and rejects
symlinks.

## Adding another provider

Keep the external tool and FastAPI contract stable:

1. Add the provider name to `SUPPORTED_MUSIC_PROVIDERS`.
2. Implement a provider adapter that returns the existing normalized result
   fields: audio bytes, MIME type, extension, duration, provider, model, format,
   and provider track ID when available.
3. Dispatch after `resolve_music_provider()` instead of falling back to another
   provider.
4. Add the provider to the tool manifest enum and
   `availability.provider_requirements`.
5. Map the common MP3/Opus presets to provider-specific formats.
6. Extend health reporting with the selected model and credential readiness.
7. Add route, adapter, failure, and catalog tests.

Provider-specific capabilities can be added as optional fields, but callers
that use the common contract should continue to work unchanged.

## Testing

Run the focused music and gallery coverage:

```bash
.venv/bin/python -m pytest \
  tests/test_generated_music_route.py \
  tests/test_canvas_audio_gallery.py \
  tests/test_tool_availability.py \
  -q
```

Validate the manifest and documentation:

```bash
.venv/bin/python -m json.tool skills/generate_music.tool.json >/dev/null
.venv/bin/python -m pytest tests/test_docs_integrity.py -q
```

Focused tests mock provider generation and do not incur API charges.

## Troubleshooting

### Tool is unavailable

Confirm that the active mode file contains both:

```bash
MUSIC_TOOL_PROVIDER="elevenlabs"
ELEVENLABS_API_KEY="..."
```

Then restart or resync the process that loaded tool availability.

### Unsupported music provider

The configured or per-call provider is not implemented. Use `elevenlabs` until
the new adapter, manifest entry, and credential requirements are added.

### Generation times out

Long tracks can take several minutes. Try a shorter duration first and verify
provider status and account limits. The tool and API already use extended,
duration-aware timeouts.

### Track was generated but stash failed

Check the returned `data.saved.note`. The durable file should still exist under
`data/generated_music/` and remain visible in the Audio Gallery.

### Track is absent from the Audio Gallery

Confirm that the file has a supported audio extension and exists in
`data/generated_music/`. Loading the gallery synchronizes legacy files into
`audio_catalog.json`.

## Related documentation

- [Generated Music FastAPI](../../api/GENERATED_MUSIC.md)
- [ElevenLabs-specific music notes](../../11labs/MUSIC_GENERATION.md)
- [Stash system](../../STASH_SYSTEM.md)
- [Jarvis Web UI](../../JARVIS_WEB_UI.md)
- [Background service cleanup](../../service/README.md)
