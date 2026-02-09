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
      "tags": ["ai_generated", "video", "xai", "16:9"]
    },
    {
      "name": "video_sunset_timelapse_20260131_180045.mp4",
      "size": 3332223,
      "size_human": "3.2 MB",
      "modified": "2026-01-31T18:00:45",
      "extension": ".mp4",
      "provider": "Gemini",
      "aspect": "16:9",
      "tags": ["ai_generated", "video", "gemini", "16:9"]
    }
  ]
}
```

**New Fields (Feb 2026)**:
| Field | Type | Description |
|-------|------|-------------|
| `provider` | string | AI provider: `xAI`, `OpenAI`, `Gemini`, `Runway`, etc. |
| `aspect` | string | Aspect ratio: `16:9`, `9:16`, `1:1`, etc. |
| `tags` | array | Tags from generation: `ai_generated`, `video`, provider, aspect |

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
  "created_at": "2026-02-01T10:10:28Z"
}
```

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

Generate a new AI video using xAI Grok, OpenAI Sora, or Google Gemini Veo.

**Request Body**:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | Yes | - | Video description |
| `duration` | int | No | 5 | Video length |
| `aspect_ratio` | string | No | `16:9` | Video shape |
| `resolution` | string | No | `720p` | Video quality |
| `image_url` | string | No | - | Image for image-to-video (all providers) |
| `video_url` | string | No | - | Video to edit (xAI ≤8.7s) or remix (OpenAI video ID) |
| `negative_prompt` | string | No | - | What to avoid (Gemini only) |
| `provider` | string | No | `xai` | Video provider: `xai`, `openai`, or `gemini` |
| `save` | bool | No | true | Save to disk and stash |
| `mode` | string | No | `cloud` | Config mode (cloud/local) |

**Provider Comparison**:

| Feature | xAI Grok | OpenAI Sora | Gemini Veo |
|---------|----------|-------------|------------|
| Duration | 1-15s (any) | 4, 8, or 12s | 4, 6, or 8s |
| Aspect Ratios | 7 options | 2 options | 2 options |
| Resolution | 720p, 480p | 720p, 1080p | 720p-4k |
| Native Audio | ❌ | ✅ | ✅ |
| Image-to-Video | ✅ | ✅ | ✅ |
| Video Editing | ✅ | ✅ (remix) | ❌ |
| Negative Prompt | ❌ | ❌ | ✅ |
| Cost/second | $0.05 | $0.10-0.50 | $0.15+ |

**Duration Options**:

| Provider | Range | Notes |
|----------|-------|-------|
| xAI | 1-15 seconds | Any integer value |
| OpenAI | 4, 8, or 12 seconds | Discrete values only |
| Gemini | 4, 6, or 8 seconds | Rounded to nearest |

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
| `1080p` | ❌ | ✅ (pro) | ✅ | Full HD |
| `4k` | ❌ | ❌ | ✅ | Ultra HD (8s only) |

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
      "path": "/home/boss/jarvis-voice/data/generated_videos/video_a_cat_playing_20260201_021027.mp4",
      "filename": "video_a_cat_playing_20260201_021027.mp4",
      "size_bytes": 3456789,
      "stash": true
    },
    "file_path": "/home/boss/jarvis-voice/data/generated_videos/video_a_cat_playing_20260201_021027.mp4"
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

# Edit existing video (xAI only)
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Make the colors more vibrant",
    "video_url": "https://example.com/my-video.mp4",
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
- The `video_url` in response is temporary (may expire)
- Local file path is permanent storage
- OpenAI and Gemini videos include native audio (dialogue, sound effects)
- OpenAI 1080p requires sora-2-pro model ($0.30-0.50/s)
- Gemini 1080p/4k requires 8-second duration
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
  "directory": "/home/boss/jarvis-voice/data/generated_videos",
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
    "created_at": "2026-02-01T10:10:28Z"
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

- [Video Generation Guide](../video/README.md)
- [xAI Provider Docs](../XAI_PROVIDER.md)
- [Generated Images API](GENERATED_IMAGES.md)
