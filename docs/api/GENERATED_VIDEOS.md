# Generated Videos API

Manage AI-generated videos in the local `data/generated_videos/` folder.

## Base URL

```
http://localhost:8880/api/generated-videos
```

## Endpoints

### List Videos

```http
GET /api/generated-videos
```

List all generated videos with metadata.

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 100 | Max results (1-500) |
| `offset` | int | 0 | Skip N results |
| `search` | string | - | Filter by filename |

**Response**:
```json
{
  "ok": true,
  "count": 2,
  "total_size": 6789012,
  "total_size_human": "6.5 MB",
  "videos": [
    {
      "name": "video_a_cat_playing_20260201_021027.mp4",
      "size": 3456789,
      "size_human": "3.3 MB",
      "modified": "2026-02-01T02:10:27",
      "extension": ".mp4",
      "provider": "xAI",
      "aspect": "16:9",
      "tags": ["ai_generated", "video", "xai", "16:9"],
      "stash_ref": "stash://space_20260201_101028_abc/f_123def",
      "edit_url_status": "available"
    },
    {
      "name": "video_sunset_timelapse_20260131_180045.mp4",
      "size": 3332223,
      "size_human": "3.2 MB",
      "modified": "2026-01-31T18:00:45",
      "extension": ".mp4",
      "provider": "Gemini",
      "aspect": "16:9",
      "tags": ["ai_generated", "video", "gemini", "16:9"],
      "stash_ref": "stash://space_20260131_180045_def/f_456abc",
      "edit_url_status": "expired"
    }
  ]
}
```

**Fields**:
| Field | Type | Description |
|-------|------|-------------|
| `provider` | string | AI provider: `xAI`, `OpenAI`, `Gemini` |
| `aspect` | string | Aspect ratio: `16:9`, `9:16`, `1:1`, etc. |
| `tags` | array | Tags from generation: `ai_generated`, `video`, provider, aspect |
| `stash_ref` | string | Stash reference for cross-tool use (null if stash expired) |
| `edit_url_status` | string | `"available"` (< 4h), `"expired"` (> 4h), or `null` (no URL) |

**Example**:
```bash
# List all videos
curl http://localhost:8880/api/generated-videos

# Search for videos
curl "http://localhost:8880/api/generated-videos?search=cat&limit=10"
```

---

### Get Video File

```http
GET /api/generated-videos/{filename}
```

Download a video file. Supports range requests for video seeking.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `filename` | string | Video filename |

**Response**: Video file (binary)

**Example**:
```bash
# Download video
curl http://localhost:8880/api/generated-videos/video_a_cat_playing_20260201_021027.mp4 -o cat.mp4

# Stream in browser
open http://localhost:8880/api/generated-videos/video_a_cat_playing_20260201_021027.mp4
```

---

### Get Video Info

```http
GET /api/generated-videos/{filename}/info
```

Get detailed metadata about a video.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `filename` | string | Video filename |

**Response**:
```json
{
  "ok": true,
  "name": "video_a_cat_playing_20260201_021027.mp4",
  "size": 3456789,
  "size_human": "3.3 MB",
  "modified": "2026-02-01T02:10:27",
  "extension": ".mp4",
  "mime_type": "video/mp4",
  "path": "data/generated_videos/video_a_cat_playing_20260201_021027.mp4",
  "provider": "xAI",
  "aspect": "16:9",
  "tags": ["ai_generated", "video", "xai", "16:9"],
  "tool_origin": "generate_video",
  "created_at": "2026-02-01T10:10:28Z",
  "stash_ref": "stash://space_20260201_101028_abc/f_123def",
  "space_id": "space_20260201_101028_abc",
  "source_url": "https://vidgen.x.ai/xai-vidgen-bucket/xai-video-abc123.mp4",
  "source_url_created": "2026-02-01T02:10:28.123456",
  "edit_url_status": "available"
}
```

**Editing fields**: Use `source_url` as the `video_url` when calling the generate endpoint for video editing. Check `edit_url_status` first  -- `"expired"` means the provider URL is no longer valid (xAI URLs last ~4 hours).

**Example**:
```bash
curl http://localhost:8880/api/generated-videos/video_a_cat_playing_20260201_021027.mp4/info
```

---

### Delete Video

```http
DELETE /api/generated-videos/{filename}
```

Delete a video file.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `filename` | string | Video filename |

**Response**:
```json
{
  "ok": true,
  "deleted": "video_a_cat_playing_20260201_021027.mp4"
}
```

**Error Response**:
```json
{
  "ok": false,
  "error": "Video not found"
}
```

**Example**:
```bash
curl -X DELETE http://localhost:8880/api/generated-videos/video_a_cat_playing_20260201_021027.mp4
```

---

### Generate Video

```http
POST /api/generated-videos/generate
```

Generate a new AI video using xAI Grok, OpenAI Sora, or Google Gemini (Veo by default, Omni Flash when pinned).

**Request Body**:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | Yes | - | Video description |
| `duration` | int | No | 5 | Video length |
| `aspect_ratio` | string | No | `16:9` | Video shape |
| `resolution` | string | No | `720p` | Video quality |
| `image_url` | string | No | - | Image for image-to-video (all providers) |
| `video_url` | string | No | - | Video to edit (xAI: public URL only, ≤8.7s source, expires ~4h) or remix (OpenAI video ID). Use `source_url` from `/info`. Cannot change duration/aspect/resolution. |
| `negative_prompt` | string | No | - | What to avoid (Gemini only) |
| `provider` | string | No | `xai` | Video provider: `xai`, `openai`, or `gemini` |
| `save` | bool | No | true | Save to disk and stash |
| `mode` | string | No | `cloud` | Config mode (cloud/local) |

**Provider Comparison**:

| Feature | xAI Grok | OpenAI Sora | Google Gemini |
|---------|----------|-------------|------------|
| Duration | 1-15s (any) | 4, 8, or 12s | Veo: 4/6/8s; Omni: 3-10s |
| Aspect Ratios | 7 options | 2 options | 2 options |
| Resolution | 720p, 480p | 720p, 1080p | Veo: 720p-4k; Omni: 720p |
| Native Audio | ❌ | ✅ | ✅ |
| Image-to-Video | ✅ | ✅ | ✅ |
| Video Editing | ✅ | ✅ (remix) | Omni API supports it; Jarvis follow-ups planned |
| Negative Prompt | ❌ | ❌ | Veo: native; Omni: prompt guidance |
| Cost/second | $0.05+ | $0.10-0.50 | $0.10+ |

**Duration Options**:

| Provider | Range | Notes |
|----------|-------|-------|
| xAI | 1-15 seconds | Any integer value |
| OpenAI | 4, 8, or 12 seconds | Discrete values only |
| Gemini Veo | 4, 6, or 8 seconds | Rounded to nearest |
| Gemini Omni Flash | 3-10 seconds | Clamped to range |

**Aspect Ratio Options**:

| Value | Description | xAI | OpenAI | Gemini |
|-------|-------------|-----|--------|--------|
| `16:9` | Widescreen (default) | ✅ | ✅ | ✅ |
| `4:3` | Classic | ✅ | ➡️ 16:9 | ➡️ 16:9 |
| `1:1` | Square | ✅ | ➡️ 16:9 | ➡️ 16:9 |
| `9:16` | Vertical | ✅ | ✅ | ✅ |
| `3:4` | Portrait | ✅ | ➡️ 9:16 | ➡️ 9:16 |
| `3:2` | Photo standard | ✅ | ➡️ 16:9 | ➡️ 16:9 |
| `2:3` | Tall portrait | ✅ | ➡️ 9:16 | ➡️ 9:16 |

**Resolution Options**:

| Value | xAI | OpenAI | Gemini | Notes |
|-------|-----|--------|--------|-------|
| `720p` | ✅ | ✅ | ✅ | HD (default) |
| `480p` | ✅ | ➡️ 720p | ➡️ 720p | SD |
| `1080p` | ❌ | ✅ (pro) | ✅ Veo | Full HD |
| `4k` | ❌ | ❌ | ✅ Veo | Ultra HD (Veo 8s only) |

**Response**:
```json
{
  "ok": true,
  "speech": "Generated 5s video with xai: A cat playing with a ball...",
  "data": {
    "prompt": "A cat playing with a ball",
    "provider": "xai",
    "model": "grok-imagine-video",
    "duration": 5,
    "aspect_ratio": "16:9",
    "resolution": "720p",
    "video_url": "https://video.xai.ai/...",
    "saved": {
      "saved": true,
      "stash_ref": "stash://space_20260201_101028_05045a8d/video_a_cat_playing_20260201_021027.mp4",
      "space_id": "space_20260201_101028_05045a8d",
      "path": "~/jarvis-voice/data/generated_videos/video_a_cat_playing_20260201_021027.mp4",
      "filename": "video_a_cat_playing_20260201_021027.mp4",
      "size_bytes": 3456789,
      "stash": true
    },
    "file_path": "~/jarvis-voice/data/generated_videos/video_a_cat_playing_20260201_021027.mp4"
  }
}
```

**Error Response**:
```json
{
  "ok": false,
  "error": "Video generation timed out (10 min limit)"
}
```

**Examples**:

```bash
# Basic text-to-video (xAI, default)
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cat playing with a ball, slow motion",
    "duration": 5,
    "aspect_ratio": "16:9"
  }'

# Vertical video for social media (xAI)
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Product showcase of a coffee cup with steam",
    "duration": 5,
    "aspect_ratio": "9:16",
    "provider": "xai"
  }'

# Image-to-video (both providers)
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Animate this landscape with gentle movement",
    "image_url": "https://example.com/landscape.jpg",
    "duration": 8
  }'

# Edit existing video style (xAI only — cannot change duration/aspect/resolution)
# Use source_url from the /info endpoint (expires ~4h after generation)
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Make the colors more vibrant",
    "video_url": "https://vidgen.x.ai/xai-vidgen-bucket/xai-video-abc123.mp4",
    "provider": "xai"
  }'

# High-quality with native audio (Gemini)
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A stunning 4K drone view of mountains at sunset with wind sounds",
    "duration": 8,
    "resolution": "4k",
    "provider": "gemini"
  }'

# OpenAI Sora with audio
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A close-up of a woman saying Hello world! in a cafe with background chatter",
    "duration": 8,
    "provider": "openai"
  }'

# Video with dialogue (Gemini)
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Close-up of a man saying \"Hello world!\" in a cafe with background chatter",
    "duration": 6,
    "provider": "gemini"
  }'

# Using negative prompt (Gemini)
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A beautiful sunset over mountains",
    "negative_prompt": "cartoon, low quality, blurry, text",
    "duration": 8,
    "provider": "gemini"
  }'
```

**Notes**:
- Generation takes 30-120+ seconds depending on provider, duration, and resolution
- API timeout is 10 minutes
- The `video_url` in response is the provider's temporary URL (xAI expires ~4h, OpenAI ~60min)
- Local file path and stash_ref are permanent storage
- xAI video editing can only change visual content/style, not duration, aspect ratio, or resolution
- xAI video editing requires a public http(s) URL (use `source_url` from `/info`, not `stash_ref`)
- OpenAI and Gemini videos include native audio (dialogue, sound effects)
- OpenAI 1080p requires sora-2-pro model ($0.30-0.50/s)
- Gemini Veo 1080p/4k requires 8-second duration; Omni Flash is 720p only
- OpenAI videos also viewable at platform.openai.com/playground/videos

---

### Health Check

```http
GET /api/generated-videos/health
```

Check video generation service status.

**Response**:
```json
{
  "ok": true,
  "directory": "~/jarvis-voice/data/generated_videos",
  "exists": true,
  "video_count": 5,
  "total_size": 16789012,
  "total_size_human": "16.0 MB",
  "configured_provider": "openai",
  "configured_model": "sora-2"
}
```

**Example**:
```bash
curl http://localhost:8880/api/generated-videos/health
```

---

## Storage

Videos are stored in multiple locations:

### 1. File System
```
data/generated_videos/
├── video_a_cat_playing_20260201_021027.mp4
├── video_sunset_timelapse_20260131_180045.mp4
├── ...
└── video_catalog.json  ← Metadata catalog (provider, tags, aspect)
```

### 2. Video Catalog (Feb 2026)

The `video_catalog.json` file stores metadata for all videos:

```json
{
  "video_a_cat_playing_20260201_021027.mp4": {
    "provider": "xAI",
    "aspect": "16:9",
    "tags": ["ai_generated", "video", "xai", "16:9"],
    "tool_origin": "generate_video",
    "created_at": "2026-02-01T10:10:28Z",
    "stash_ref": "stash://space_20260201_101028_abc/f_123def",
    "space_id": "space_20260201_101028_abc",
    "source_url": "https://vidgen.x.ai/xai-vidgen-bucket/xai-video-abc123.mp4",
    "source_url_created": "2026-02-01T02:10:28.123456",
    "edit_url_status": "expired"
  }
}
```

**How it syncs:**
1. When listing videos, the API auto-syncs the catalog with actual files
2. New videos → metadata pulled from stash, added to catalog
3. Deleted videos → removed from catalog
4. Stash TTL expires → catalog still has all metadata (persistent)

**Benefits:**
- Provider/tags survive stash cleanup (7-day TTL)
- Both `jarvis-api` (port 8880) and `jarvis-canvas` (port 8890) share the same catalog
- No sidecar files needed - single source of truth

### 3. Stash (for cross-tool use)
```
data/stash/space_{timestamp}_{id}/
├── meta.json
└── video_filename.mp4
```

### 4. Memory (for discovery)
Videos are indexed in memory with:
- Category: `stash_artifact`
- Type: `video`
- Searchable by prompt

---

## Error Codes

| Code | Error | Description |
|------|-------|-------------|
| 400 | Invalid filename | Path traversal attempt |
| 404 | Video not found | File doesn't exist |
| 500 | Generation failed | xAI API error |
| 504 | Timeout | Generation took >10 minutes |

---

## Rate Limits

- Generation is rate-limited by xAI API
- Large videos (>10s) may take longer
- Consider using shorter durations for testing

---

## See Also

- [Video Generation Guide](../tools/video/README.md)
- [xAI Provider Docs](../XAI_PROVIDER.md)
- [Generated Images API](GENERATED_IMAGES.md)
