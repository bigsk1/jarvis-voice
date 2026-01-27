# Images API - Cloudflare CDN Upload

Upload images to Cloudflare Images CDN and get permanent, publicly-accessible URLs.

## Overview

The Images API allows Jarvis and external agents (like Samantha) to upload images to Cloudflare's global CDN. This solves the base64 size limitation problem when sharing images across systems.

**Use Cases:**
- Upload AI-generated images for permanent hosting
- Share status visuals across systems
- Store canvas images externally for faster loading
- Enable multi-agent image sharing (Samantha → Jarvis)

## ⚠️ Privacy Warning

**Uploaded images are PUBLICLY ACCESSIBLE** to anyone with the URL. The API endpoint is IP-whitelisted, but the resulting CDN URLs are not protected.

**DO NOT UPLOAD:**
- Screenshots (may contain sensitive info)
- Personal photos
- Documents or PDFs
- Anything with passwords, API keys, or private data
- Medical, financial, or legal documents

**SAFE TO UPLOAD:**
- AI-generated artwork and images
- Status visuals and diagrams
- Shareable infographics
- Public content meant for distribution

## Endpoints

### Upload Image

```
POST /api/images
```

Upload an image from various sources.

**Request Body:**
```json
{
  "source": "https://example.com/image.jpg",
  "source_type": "auto",
  "uploader": "jarvis",
  "category": "status",
  "prompt": "A futuristic dashboard",
  "tags": ["status", "generated"],
  "provider": "gemini"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | Yes | Image source (see below) |
| `source_type` | string | No | `auto`, `file`, `url`, `base64`, `stash` (default: auto) |
| `uploader` | string | No | Who uploaded: `jarvis`, `samantha`, `api` (default: api) |
| `category` | string | No | Category: `status`, `generated`, `stash`, etc. (auto-detected) |
| `prompt` | string | No | Generation prompt (stored as metadata) |
| `tags` | array | No | Tags for the image (stored as metadata) |
| `provider` | string | No | Image provider: `gemini`, `openai`, etc. |

**Source Types:**
- `file` - Local file path (e.g., `data/generated_images/image.jpg`)
- `url` - HTTP/HTTPS URL to download and upload
- `base64` - Base64 encoded data (with or without `data:image/...` prefix)
- `stash` - Stash reference (e.g., `stash://space_20260127_123456/f_abc123`)
- `auto` - Auto-detect from source format

**Response:**
```json
{
  "ok": true,
  "url": "https://imagedelivery.net/xxx/jarvis/2026-01-27/status/dashboard_a1b2c3d4/public",
  "image_id": "jarvis/2026-01-27/status/dashboard_a1b2c3d4",
  "custom_path": "jarvis/2026-01-27/status/dashboard_a1b2c3d4",
  "filename": "dashboard.jpg",
  "source_type": "url",
  "uploader": "jarvis"
}
```

### Upload Base64 Image (Convenience)

```
POST /api/images/base64
```

Simplified endpoint for base64 uploads.

**Request Body:**
```json
{
  "image": "data:image/png;base64,iVBORw0KGgo...",
  "filename": "my_image.png",
  "uploader": "samantha",
  "category": "generated",
  "prompt": "A cute robot dog",
  "tags": ["ai", "robot"],
  "provider": "gemini"
}
```

**Response:** Same as `/api/images`

### Health Check

```
GET /api/images/health
```

Check if Cloudflare credentials are configured.

**Response:**
```json
{
  "ok": true,
  "api_token_configured": true,
  "account_id_configured": true
}
```

## Path Organization

Images are stored with organized custom paths:

```
{uploader}/{date}/{category}/{filename}_{hash}
```

**Examples:**
| Uploader | Category | Result Path |
|----------|----------|-------------|
| jarvis | status | `jarvis/2026-01-27/status/daily_visual_a1b2c3d4` |
| samantha | research | `samantha/2026-01-27/research/ai_news_e5f6g7h8` |
| api | generated | `api/2026-01-27/generated/robot_dog_i9j0k1l2` |

This makes it easy to:
- Browse images by uploader in Cloudflare dashboard
- Filter by date
- Identify image categories
- Track what was uploaded when

## Metadata Storage

Cloudflare stores metadata with each image (not exposed to end users):

**Automatic metadata:**
- `uploader` - Who uploaded (jarvis, samantha, api)
- `uploaded_at` - ISO timestamp
- `original_filename` - Original file name
- `category` - Status, generated, stash, etc.
- `source_type` - base64, url, file, stash

**Optional metadata:**
- `prompt` - Generation prompt
- `tags` - Array of tags
- `provider` - Image provider (gemini, openai)

**From stash uploads:** Automatically extracts metadata from stash (prompt, provider, tags).

View metadata in Cloudflare dashboard or via API:
```bash
curl "https://api.cloudflare.com/client/v4/accounts/{account_id}/images/v1/{image_id}" \
  -H "Authorization: Bearer {token}"
```

## Supported Formats

- PNG
- JPEG/JPG
- GIF (including animations)
- WebP (including animations)
- SVG
- HEIC

## Examples

### cURL - Upload from URL

```bash
curl -X POST http://localhost:8880/api/images \
  -H "Content-Type: application/json" \
  -d '{
    "source": "https://example.com/image.jpg",
    "source_type": "url",
    "uploader": "jarvis",
    "category": "status"
  }'
```

### cURL - Upload Base64

```bash
curl -X POST http://localhost:8880/api/images/base64 \
  -H "Content-Type: application/json" \
  -d '{
    "image": "data:image/png;base64,iVBORw0KGgo...",
    "uploader": "samantha",
    "prompt": "AI-generated artwork",
    "tags": ["art", "generated"]
  }'
```

### Python - Upload from Stash

```python
import requests

response = requests.post(
    "http://localhost:8880/api/images",
    json={
        "source": "stash://space_20260127_123456/f_abc123",
        "source_type": "stash",
        "uploader": "jarvis"
    }
)
print(response.json()["url"])
```

### Use in Canvas

After uploading, use the URL in canvas pages:

```markdown
![Status Dashboard](https://imagedelivery.net/xxx/jarvis/2026-01-27/status/dashboard_abc123/public)
```

## Tool Usage (Jarvis)

The `upload_cloudflare` tool is available for Jarvis to use directly:

```json
{
  "source": "data/generated_images/robot.jpg",
  "uploader": "jarvis",
  "category": "generated",
  "prompt": "A cute robot dog"
}
```

## Configuration

Required environment variables in `cloud.env` and `local.env`:

```bash
# Cloudflare Images API
CLOUDFLARE_API_TOKEN='your_api_token'
CLOUDFLARE_ACCOUNT_ID='your_account_id'
```

Get these from [Cloudflare Dashboard](https://dash.cloudflare.com/) → Images → API Tokens.

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `CLOUDFLARE_API_TOKEN not configured` | Missing env var | Add to cloud.env/local.env |
| `Could not download image from URL` | URL unreachable | Check URL accessibility |
| `Could not decode base64 image data` | Invalid base64 | Verify base64 encoding |
| `Could not resolve stash reference` | Invalid stash ref | Check stash space exists |
| `Upload timed out` | Large file or slow connection | Retry or use smaller image |

## Related Documentation

- [Stash System](../STASH_SYSTEM.md) - Temporary artifact storage
- [Canvas System](../CANVAS_SYSTEM.md) - Visual knowledge viewer
- [Generate Image Tool](../../skills/generate_image.py) - AI image generation
