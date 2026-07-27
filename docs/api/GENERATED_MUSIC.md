# Generated Music API

Generate AI music through Jarvis and stream the durable files saved in
`data/generated_music/`.

For tool behavior, provider integration, storage, and Audio Gallery details, see
the [`generate_music` tool guide](../tools/generate-music-tool/README.md).

## Base URL

```text
http://localhost:8880/api/generated-music
```

The FastAPI server's normal authentication policy applies. When
`JARVIS_API_AUTH=true`, remote callers must send the configured bearer token.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/generate` | Generate a track |
| GET | `/health` | Check provider and storage readiness |
| GET | `/{filename}` | Stream or download a saved track |

Browsing, favorites, and manual deletion remain available in the Canvas Audio
Gallery at `http://localhost:8890/audio-gallery`.

## Generate Music

```http
POST /api/generated-music/generate
Content-Type: application/json
```

This is a synchronous generation request. Short tracks may still take several
minutes. The API timeout scales with the requested or composition-plan duration.
When global API rate limiting is enabled, non-loopback requests to the
generated-music API have a separate limit of 10 requests per minute per IP by
default. Set `API_RATE_LIMIT_GENERATED_MUSIC_PER_MINUTE` to override it, or set
it to `0` to disable this bucket. Loopback requests are trusted and exempt.

### Request fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | Yes | — | Song, instrumental, jingle, or soundtrack description |
| `title` | string | No | Prompt excerpt | Display title and filename basis |
| `duration_seconds` | integer | No | `60` | 3–600 seconds; ignored when a composition plan supplies section durations |
| `genre` | string | No | — | Genre such as ambient, cinematic, pop, rock, or lo-fi |
| `mood` | string | No | — | Emotional direction such as calm, energetic, dark, or hopeful |
| `instrumental` | boolean | No | `false` | Generate without vocals |
| `tempo` | string | No | — | `slow`, `medium`, `fast`, or a value such as `120 BPM` |
| `output_format` | string | No | `mp3_medium` | MP3 or Opus quality preset |
| `composition_plan` | object | No | — | Advanced sections, styles, and lyrics |
| `provider` | string | No | `MUSIC_TOOL_PROVIDER` | Provider override; currently `elevenlabs` |
| `save` | boolean | No | `true` | Save to `data/generated_music/` and stash |
| `mode` | string | No | `cloud` | `cloud` or `local` configuration |

Current output presets:

- `mp3_low`, `mp3_medium`, `mp3_high`
- `opus_low`, `opus_medium`, `opus_high`

### Basic example

```bash
curl -X POST http://localhost:8880/api/generated-music/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Warm cinematic ambient music for a space documentary",
    "title": "Deep Orbit",
    "duration_seconds": 45,
    "genre": "cinematic",
    "mood": "hopeful",
    "instrumental": true,
    "tempo": "slow",
    "output_format": "mp3_high"
  }'
```

### Composition-plan example

```bash
curl -X POST http://localhost:8880/api/generated-music/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "An uplifting orchestral theme",
    "title": "New Horizon",
    "instrumental": true,
    "composition_plan": {
      "global_styles": ["cinematic", "orchestral"],
      "sections": [
        {
          "section_name": "intro",
          "duration_seconds": 20,
          "styles": ["soft strings"]
        },
        {
          "section_name": "theme",
          "duration_seconds": 40,
          "styles": ["full orchestra"]
        }
      ]
    }
  }'
```

Composition plans may contain up to 20 sections. Each section must be 3–120
seconds, and the total cannot exceed 600 seconds.

### Successful response

```json
{
  "ok": true,
  "speech": "Generated 45 second instrumental music in cinematic style: Deep Orbit",
  "error": null,
  "data": {
    "title": "Deep Orbit",
    "duration_seconds": 45,
    "genre": "cinematic",
    "mood": "hopeful",
    "instrumental": true,
    "tempo": "slow",
    "mime_type": "audio/mpeg",
    "size_bytes": 1080000,
    "song_id": "example-song-id",
    "provider": "ElevenLabs",
    "model": "music_v1",
    "output_format": "mp3_44100_192",
    "saved": {
      "filename": "music_deep_orbit_20260726_230000.mp3",
      "path": "/path/to/jarvis-voice/data/generated_music/music_deep_orbit_20260726_230000.mp3",
      "stash": true,
      "stash_ref": "stash://space_example/file_example"
    }
  },
  "audio_url": "/api/generated-music/music_deep_orbit_20260726_230000.mp3"
}
```

When `save=false`, generation metadata is returned but `audio_url` is null
because no durable file is retained.

## Provider configuration

```bash
MUSIC_TOOL_PROVIDER="elevenlabs"
ELEVENLABS_API_KEY="..."
```

The request and route are provider-neutral, but ElevenLabs is the only
implemented adapter today. Unknown providers return an explicit error and never
fall back to ElevenLabs. Future providers can be added behind the same
`provider` field and response contract.

## Health

```bash
curl http://localhost:8880/api/generated-music/health
```

The response includes:

- Configured and supported providers
- Configured model
- Whether the selected provider's credential is configured
- Supported output presets
- Durable track count and storage directory

Credential values are never returned.

## Stream or download

```bash
curl http://localhost:8880/api/generated-music/music_deep_orbit_20260726_230000.mp3 \
  -o deep-orbit.mp3
```

Only recognized audio filenames inside `data/generated_music/` are served.
Path traversal and symlink escapes are rejected.

## Related documentation

- [`generate_music` tool guide](../tools/generate-music-tool/README.md)
- [Stash API](STASH.md)
- [Canvas API](CANVAS.md)
