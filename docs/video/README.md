# Video Generation

Generate AI videos using xAI Grok Imagine Video or Google Gemini Veo directly from Jarvis.

## Overview

The `generate_video` tool creates AI-generated videos from text prompts or images. Videos are saved locally and indexed in stash for use with other tools.

## Quick Start

```bash
# Via CLI (uses default provider)
jarvis cloud "Generate a video of a cat playing with a ball"

# Specify provider
jarvis cloud "Generate a video of a sunset over mountains" --provider gemini

# Via API
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A cat playing with a ball", "duration": 5}'
```

## Providers

| Provider | Model | Duration | Audio | Resolution | Status |
|----------|-------|----------|-------|------------|--------|
| xAI | `grok-imagine-video` | 1-15s | ❌ | 720p, 480p | ✅ Active |
| Gemini | `veo-3.1-generate-preview` | 4/6/8s | ✅ Native | 720p, 1080p, 4k | ✅ Active |

Configure in `config/cloud.env`:
```bash
# Choose default provider
VIDEO_TOOL_PROVIDER="xai"  # or "gemini"

# xAI configuration
XAI_VIDEO_MODEL="grok-imagine-video"

# Gemini configuration
GEMINI_VIDEO_MODEL="veo-3.1-generate-preview"  # or veo-3.1-fast-generate-preview
```

## Provider Comparison

| Feature | xAI Grok | Gemini Veo |
|---------|----------|------------|
| **Duration Range** | 1-15 seconds (any) | 4, 6, or 8 seconds (discrete) |
| **Aspect Ratios** | 7 options | 2 options (16:9, 9:16) |
| **Resolution** | 720p, 480p | 720p, 1080p, 4k |
| **Native Audio** | ❌ No | ✅ Yes (dialogue, SFX) |
| **Video Editing** | ✅ Yes | ❌ No |
| **Negative Prompt** | ❌ No | ✅ Yes |
| **High Resolution** | ❌ No | ✅ 4k support |

## Parameters

### Duration
Video length in seconds.

| Provider | Range | Notes |
|----------|-------|-------|
| xAI | 1-15 seconds | Any integer value |
| Gemini | 4, 6, or 8 seconds | Rounded to nearest |

**Note**: Longer videos take more time to generate and cost more. Gemini 1080p/4k requires 8s duration.

### Aspect Ratio
Video shape/orientation.

| Value | Description | xAI | Gemini |
|-------|-------------|-----|--------|
| `16:9` | Widescreen (default) | ✅ | ✅ |
| `4:3` | Classic TV ratio | ✅ | ➡️ 16:9 |
| `1:1` | Square | ✅ | ➡️ 16:9 |
| `9:16` | Vertical | ✅ | ✅ |
| `3:4` | Portrait | ✅ | ➡️ 9:16 |
| `3:2` | Photo standard | ✅ | ➡️ 16:9 |
| `2:3` | Tall portrait | ✅ | ➡️ 9:16 |

### Resolution
Video quality.

| Value | xAI | Gemini | Notes |
|-------|-----|--------|-------|
| `720p` | ✅ | ✅ | HD (default) |
| `480p` | ✅ | ➡️ 720p | SD |
| `1080p` | ❌ | ✅ | Full HD (8s only) |
| `4k` | ❌ | ✅ | Ultra HD (8s only) |

## Generation Modes

### Text-to-Video
Generate from a text prompt:
```json
{
  "prompt": "A serene mountain landscape with clouds moving slowly",
  "duration": 10,
  "aspect_ratio": "16:9"
}
```

### Image-to-Video
Animate an existing image (both providers):
```json
{
  "prompt": "Animate this image with gentle movement",
  "image_url": "https://example.com/my-image.jpg",
  "duration": 5
}
```

### Video Editing (xAI only)
Edit an existing video:
```json
{
  "prompt": "Make the colors more vibrant",
  "video_url": "https://example.com/my-video.mp4",
  "provider": "xai"
}
```

**Note**: Input video for editing must be ≤8.7 seconds.

### With Audio (Gemini only)
Gemini Veo generates native audio including dialogue and sound effects:
```json
{
  "prompt": "A close-up of a man saying 'Hello world!' with birds chirping in the background",
  "duration": 8,
  "provider": "gemini"
}
```

### Negative Prompt (Gemini only)
Specify what to avoid:
```json
{
  "prompt": "A beautiful sunset over mountains",
  "negative_prompt": "cartoon, low quality, blurry, text",
  "provider": "gemini"
}
```

## Storage

Videos are stored in multiple locations:

### 1. File System
```
data/generated_videos/
├── video_a_cat_playing_20260201_021027.mp4
├── video_sunset_timelapse_20260131_180045.mp4
├── ...
└── video_catalog.json  ← Metadata catalog
```

### 2. Video Catalog (Feb 2026)
The `video_catalog.json` stores persistent metadata for all videos:

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

**How it works:**
- When videos are generated, metadata is saved to stash AND catalog
- Catalog syncs automatically - new files get metadata from stash
- Catalog survives stash TTL (7-day cleanup) - metadata persists
- Shared by `jarvis-api` (8880) and `jarvis-canvas` (8890)

### 3. Stash (Cross-Tool Use)
```
data/stash/space_{timestamp}_{id}/
├── meta.json    ← Original tags: ai_generated, video, {provider}, {aspect}
└── video_file.mp4
```

### 4. Memory (Discovery)
Entry created for cross-session recall:
- Category: `stash_artifact`
- Searchable by prompt and metadata

## Generation Time

Video generation is async and takes time:

| Duration | xAI | Gemini |
|----------|-----|--------|
| 4-5 seconds | 30-60s | 30-90s |
| 8-10 seconds | 60-90s | 60-120s |
| 15 seconds | 90-120+s | N/A |

Both SDKs handle polling automatically.

## File Sizes

Approximate file sizes:

| Resolution | 5 seconds | 8 seconds |
|------------|-----------|-----------|
| 480p | ~1-2 MB | ~2-4 MB |
| 720p | ~3-5 MB | ~5-8 MB |
| 1080p | N/A | ~10-15 MB |
| 4k | N/A | ~30-50 MB |

## Web UI

### Jarvis Web Chat
Generated videos appear in the chat with:
- Video player with play/pause controls
- Duration indicator
- Downloadable link

### Video Gallery (Feb 2026)
Browse all generated videos at `http://localhost:8890/video-gallery`:

**Features:**
- Grid view with hover preview
- Provider badges (xAI, Gemini) from video catalog
- Lightbox viewer with controls below video
- Search and sort (date, name, size, duration)
- Download and delete functionality
- Keyboard shortcuts (arrows, space, escape)

**Access:**
- Direct URL: `http://localhost:8890/video-gallery`
- Canvas header: "🎬 Videos" link

## API Endpoints

See [API Documentation](../api/GENERATED_VIDEOS.md) for full endpoint reference.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/generated-videos` | GET | List all videos (with provider, aspect, tags) |
| `/api/generated-videos/{filename}` | GET | Download video |
| `/api/generated-videos/{filename}/info` | GET | Video metadata (with provider, aspect, tags) |
| `/api/generated-videos/{filename}` | DELETE | Delete video + remove from catalog |
| `/api/generated-videos/generate` | POST | Generate new video |
| `/api/generated-videos/health` | GET | Health check |

**New response fields (Feb 2026):**
- `provider`: AI provider name (xAI, Gemini, etc.)
- `aspect`: Aspect ratio (16:9, 9:16, etc.)
- `tags`: Array of tags from generation
- `tool_origin`: Tool that created the video
- `created_at`: ISO timestamp

## Requirements

**For xAI:**
- xAI SDK >= 1.6.1 (video support added in 1.6.0)
- `XAI_API_KEY` configured in cloud.env
- Sufficient xAI API credits

**For Gemini:**
- google-genai >= 1.0.0
- `GEMINI_API_KEY` configured in cloud.env
- Sufficient Gemini API credits

Install both:
```bash
pip install xai-sdk>=1.6.1 google-genai>=1.0.0
```

## Costs

Video generation costs vary by provider, duration, and resolution:

| Provider | Pricing Info |
|----------|--------------|
| xAI | [console.x.ai](https://console.x.ai) |
| Gemini | [ai.google.dev/pricing](https://ai.google.dev/gemini-api/docs/pricing#veo-3.1) |

**Note**: Gemini 4k videos are significantly more expensive than 720p.

## Troubleshooting

### "Client object has no attribute 'video'" (xAI)
Upgrade xAI SDK:
```bash
pip install --upgrade xai-sdk
```
Requires version 1.6.0 or higher.

### "google-genai not installed" (Gemini)
Install Google GenAI:
```bash
pip install google-genai
```

### Generation timeout
- Video generation can take 30-120+ seconds
- API has 10-minute timeout
- Try shorter duration videos or lower resolution

### Video not appearing in UI
- Check `data/generated_videos/` for the file
- Verify the `/api/videos/{filename}` route is accessible
- Check browser console for errors

### Gemini aspect ratio not supported
Gemini only supports 16:9 and 9:16. Other ratios are automatically mapped:
- Portrait ratios → 9:16
- Landscape/square ratios → 16:9

## Examples

### Cinematic Scene (xAI)
```json
{
  "prompt": "Epic drone shot flying over a foggy forest at sunrise, cinematic lighting",
  "duration": 10,
  "aspect_ratio": "16:9",
  "resolution": "720p",
  "provider": "xai"
}
```

### Social Media Short (xAI)
```json
{
  "prompt": "Product showcase of a coffee cup with steam rising, modern kitchen background",
  "duration": 5,
  "aspect_ratio": "9:16",
  "provider": "xai"
}
```

### Animation from Image (Both)
```json
{
  "prompt": "Add subtle movement to the clouds and water",
  "image_url": "https://example.com/landscape.jpg",
  "duration": 8,
  "aspect_ratio": "16:9"
}
```

### High-Quality with Audio (Gemini)
```json
{
  "prompt": "A stunning 4K drone view of the Grand Canyon at sunset. Wind sounds and ambient nature.",
  "duration": 8,
  "resolution": "4k",
  "provider": "gemini"
}
```

### Dialogue Video (Gemini)
```json
{
  "prompt": "Close-up of two people. Man says 'This is amazing!' Woman replies 'I know, right?' Background cafe ambiance.",
  "duration": 8,
  "aspect_ratio": "16:9",
  "provider": "gemini"
}
```

### Video Edit (xAI only)
```json
{
  "prompt": "Make the ball larger and add more contrast",
  "video_url": "https://example.com/original-video.mp4",
  "provider": "xai"
}
```
