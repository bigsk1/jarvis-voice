# ElevenLabs Music Generation Tool

> **Tool**: `generate_music`  
> **Added**: December 2025  
> **API**: ElevenLabs Music API

This is the provider-specific ElevenLabs reference. For the current
provider-neutral tool, storage, Audio Gallery, and FastAPI behavior, see the
canonical [`generate_music` tool guide](../tools/generate-music-tool/README.md).

## Overview

The `generate_music` tool uses ElevenLabs' AI music generation API to create original songs, instrumentals, jingles, and soundtracks from text prompts.

## Configuration

### Required Environment Variables

Add to `config/cloud.env`:

```bash
# ElevenLabs API (also used for TTS)
ELEVENLABS_API_KEY=your_api_key_here
```

Get your API key from: https://elevenlabs.io/app/settings/api-keys

### Timeout Configuration

Music generation can take 1-5 minutes depending on duration. The executor is configured with a 10-minute timeout:

```python
# orchestrator/executor.py
elif tool_name == "generate_music":
    timeout = 600  # 10 minutes
```

## Usage

### Basic Usage (Voice/Terminal)

```bash
# Simple request
./orchestrator/orchestrator_v2.py cloud "create a 30 second upbeat jazz jingle"

# With genre and mood
./orchestrator/orchestrator_v2.py cloud "make a chill lo-fi hip hop beat, 2 minutes"

# Instrumental only
./orchestrator/orchestrator_v2.py cloud "generate an epic cinematic trailer soundtrack, instrumental, 1 minute"
```

### Web UI Usage

1. Type `@generate_music` to load the music prompt template
2. Describe your music idea
3. Click send - the tool will generate and return a playable audio player

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | Yes | Detailed description of the music |
| `title` | string | No | Name for the track |
| `genre` | string | No | Musical genre (pop, rock, jazz, etc.) |
| `mood` | string | No | Emotional tone (happy, sad, energetic, calm) |
| `tempo` | string | No | Speed: "slow", "medium", "fast", or BPM number |
| `duration_seconds` | int | No | Length in seconds (3-600, default: 60) |
| `instrumental` | bool | No | Force no vocals (default: false) |
| `output_format` | string | No | "mp3_low", "mp3_medium", "mp3_high", "opus_low", "opus_medium", "opus_high" |

## Best Practices (from ElevenLabs)

### 1. Write Detailed Prompts

**Bad**: "happy music"

**Good**: "An upbeat summer pop song with catchy guitar riffs, bright synths, and a driving drum beat. Energetic and optimistic, perfect for a beach party or road trip montage."

### 2. Reference Styles and Eras

- "80s synthwave with retro drums and analog synths"
- "Modern trap beat with heavy 808s"
- "Classical orchestral piece in the style of Hans Zimmer"

### 3. Set the Scene

Describe the atmosphere:
- "Dark rainy night in a jazz club"
- "Sunset beach with gentle waves"
- "High-energy video game boss battle"

### 4. Use Composition Plans for Complex Songs

For detailed control, structure your request:

```
Create a pop song with:
- Intro (8 bars): Soft piano, building anticipation
- Verse 1: Add drums and bass, mellow energy
- Chorus: Full instrumentation, catchy hook, high energy
- Verse 2: Slight variation, add strings
- Bridge: Break down to piano and vocals
- Final Chorus: Maximum energy, harmonies
- Outro: Fade out on main melody
```

### 5. Specify Instruments

Be explicit about instrumentation:
- "Acoustic guitar fingerpicking with light brush drums"
- "Full orchestra with strings, brass, and timpani"
- "Electronic synths, 808 bass, hi-hats"

## Genre Reference

### Upbeat/Energetic
- Pop, Dance, EDM, Funk, Disco
- House, Techno, Drum & Bass

### Chill/Relaxed
- Lo-fi, Ambient, Jazz, Bossa Nova
- Chillhop, Downtempo, New Age

### Intense/Dramatic
- Rock, Metal, Dubstep
- Epic/Trailer, Orchestral

### Nostalgic
- 80s Synth, 90s R&B
- Classic Rock, Motown

## Output Files

### Storage Locations

Generated music is saved to:
1. **Primary**: `data/generated_music/music_<title>_<timestamp>.mp3`
2. **Stash**: `data/stash/space_<id>/` with metadata

### Stash Metadata

Each generation creates a stash entry with:
- File ID for retrieval
- Title, duration, genre, mood
- Generation parameters
- SHA256 hash for integrity

### Web UI Playback

The web UI automatically detects music generation results and shows an audio player. Files are served via:
- `/api/music/<filename>` - Direct file access
- `/api/stash/<space_id>/<file_id>` - Stash-based access

## API Reference

### ElevenLabs Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/music` | Simple generation or a structured composition plan |
| `POST /v1/music/detailed` | Simple generation with a detailed response |

### Rate Limits

- Depends on your ElevenLabs subscription tier
- Free tier: Limited generations per month
- Pro tier: Higher limits and priority

### Response Format

```json
{
  "ok": true,
  "speech": "Created 'Track Title' - 60 second jazz track",
  "data": {
    "title": "Track Title",
    "file_path": "data/generated_music/music_track_title_20251230_123456.mp3",
    "audio_url": "/api/stash/space_xxx/f_yyy",
    "stash_ref": "stash://space_xxx/f_yyy",
    "duration_seconds": 60,
    "file_size_bytes": 480000,
    "genre": "jazz",
    "mood": "relaxed"
  }
}
```

## Troubleshooting

### Tool Times Out

**Cause**: Music generation takes longer than expected (especially for 2+ minute tracks).

**Solution**: The timeout is set to 10 minutes. For very long tracks, consider:
- Breaking into shorter segments
- Using lower quality output format

### 404 on Audio Playback

**Cause**: Stash file resolution failed.

**Solution**: Check that:
- The stash space exists in `data/stash/`
- The `meta.json` has correct `file_id` mapping
- Web server has access to the stash directory

### Empty or Silent Audio

**Cause**: Poor prompt or API issue.

**Solution**: 
- Make prompt more descriptive
- Check ElevenLabs API status
- Verify API key has sufficient credits

### API Key Invalid

**Cause**: Missing or incorrect `ELEVENLABS_API_KEY`.

**Solution**:
```bash
# Verify key is set
grep ELEVENLABS_API_KEY config/cloud.env

# Test key
curl -H "xi-api-key: YOUR_KEY" https://api.elevenlabs.io/v1/user
```

## Examples

### Jingle (15-30 seconds)

```
"Create a 20 second jingle for a coffee shop. Warm, inviting, acoustic guitar with soft percussion. End on a satisfying chord."
```

### Background Music (1-2 minutes)

```
"Generate 90 seconds of lo-fi study music. Mellow piano, vinyl crackle, jazzy chords, slow tempo around 75 BPM. Instrumental only, perfect for focus."
```

### Full Song (2-3 minutes)

```
"Compose a 2 minute indie rock song about summer adventures. Jangly guitars, driving drums, nostalgic vocals. Verse-chorus-verse-chorus-bridge-chorus structure. Upbeat and anthemic."
```

### Cinematic Score (1 minute)

```
"Create a 60 second epic orchestral piece for a movie trailer. Start mysterious with low strings, build through brass crescendo, climax with full orchestra and timpani, end dramatically."
```

## Related Files

- **Tool Script**: `skills/generate_music.py`
- **Tool Definition**: `skills/generate_music.tool.json`
- **Prompt Template**: `jarvis-web/data/prompts/generate_music.md`
- **Output Directory**: `data/generated_music/`

## Links

- [ElevenLabs Music API Docs](https://elevenlabs.io/docs/api-reference/music/compose)
- [Best Practices Guide](https://elevenlabs.io/docs/overview/capabilities/music/best-practices)
- [Composition Plans](https://elevenlabs.io/docs/api-reference/music/compose-detailed)
