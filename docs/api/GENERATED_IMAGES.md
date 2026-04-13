# Generated Images API

Generate, edit, and manage locally generated images in `data/generated_images/`.

Unlike `/api/images` (Cloudflare CDN uploads), these routes manage the **local** generated images folder where AI-generated images are stored privately. Supports both text-to-image generation and image-to-image editing with all 3 providers.

**Base URL**: `http://localhost:8880/api/generated-images`

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all images |
| GET | `/{filename}` | Get image file |
| GET | `/{filename}/base64` | Get image as base64 |
| DELETE | `/{filename}` | Delete image |
| POST | `/generate` | Generate new image |
| GET | `/{filename}/cdn-url` | Get/create CDN URL |
| GET | `/cdn-catalog` | List all CDN URLs |
| GET | `/health` | Check status |

---

## List Images

```bash
curl http://localhost:8880/api/generated-images
```

**Query Parameters:**
- `limit` (int, 1-500, default 100) - Max results
- `offset` (int, default 0) - Skip N results  
- `search` (string) - Filter by filename

**Response:**
```json
{
  "ok": true,
  "count": 42,
  "total_size": 156789012,
  "total_size_human": "149.5 MB",
  "images": [
    {
      "name": "generated_a_cute_robot_dog_20260128_123456.jpg",
      "size": 245678,
      "size_human": "239.9 KB",
      "modified": "2026-01-28T12:34:56",
      "extension": ".jpg"
    }
  ]
}
```

**Examples:**
```bash
# Search for robot images
curl "http://localhost:8880/api/generated-images?search=robot"

# Get first 10 images
curl "http://localhost:8880/api/generated-images?limit=10"

# Pagination
curl "http://localhost:8880/api/generated-images?limit=20&offset=40"
```

---

## Get Image File

```bash
curl http://localhost:8880/api/generated-images/my_image.jpg -o my_image.jpg
```

Returns the raw image file. Use for downloading or embedding in HTML.

---

## Get Image as Base64

```bash
curl http://localhost:8880/api/generated-images/my_image.jpg/base64
```

**Response:**
```json
{
  "ok": true,
  "name": "my_image.jpg",
  "base64": "data:image/jpeg;base64,/9j/4AAQ...",
  "mime_type": "image/jpeg",
  "size": 245678
}
```

Useful for APIs that need base64 encoded images (e.g., sending to LLMs).

---

## Delete Image

```bash
curl -X DELETE http://localhost:8880/api/generated-images/my_image.jpg
```

**Response:**
```json
{
  "ok": true,
  "deleted": "my_image.jpg"
}
```

**Error Response:**
```json
{
  "ok": false,
  "error": "Image not found"
}
```

---

## Get CDN URL

Get a Cloudflare CDN URL for an image. Uploads to Cloudflare if not already uploaded, then caches the URL in `cdn_catalog.json` for instant retrieval.

```bash
curl http://localhost:8880/api/generated-images/my_image.jpg/cdn-url
```

**Response (first time - uploads):**
```json
{
  "ok": true,
  "name": "my_image.jpg",
  "url": "https://imagedelivery.net/xxx/yyy/public",
  "cached": false,
  "image_id": "yyy"
}
```

**Response (cached - instant):**
```json
{
  "ok": true,
  "name": "my_image.jpg",
  "url": "https://imagedelivery.net/xxx/yyy/public",
  "cached": true,
  "image_id": "yyy"
}
```

---

## CDN Catalog

List all images that have been uploaded to Cloudflare. This catalog is stored in `data/generated_images/cdn_catalog.json`.

```bash
curl http://localhost:8880/api/generated-images/cdn-catalog
```

**Response:**
```json
{
  "ok": true,
  "count": 5,
  "entries": [
    {
      "filename": "generated_robot_20260128.jpg",
      "url": "https://imagedelivery.net/xxx/aaa/public",
      "image_id": "aaa",
      "uploaded_at": "2026-01-28T12:34:56"
    },
    {
      "filename": "generated_sunset_20260127.jpg",
      "url": "https://imagedelivery.net/xxx/bbb/public",
      "image_id": "bbb",
      "uploaded_at": "2026-01-27T10:00:00"
    }
  ]
}
```

Use this to:
- Check if an image has already been uploaded
- Get URLs without re-uploading
- Find images by their CDN URL or image_id

---

## Generate or Edit Image

Generate a new image from text, or edit an existing image by providing a `reference_image`.

```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cute robot dog playing in a sunny park",
    "aspect_ratio": "landscape",
    "image_size": "2K"
  }'
```

### Request Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | string | **required** | What to generate, or edit instructions when `reference_image` is provided |
| `reference_image` | string | null | Source image to edit. Accepts: `stash://` ref, local file path, public URL, or base64 data URI. When provided, edits this image instead of generating from scratch. |
| `aspect_ratio` | string | "square" | square, landscape, portrait, wide, tall, 16:9, 4:3 |
| `image_size` | string | "2K" | 1K, 2K, or 4K (Gemini/OpenAI only) |
| `style` | string | null | Art style (photorealistic, watercolor, anime, etc.) |
| `negative_prompt` | string | null | Things to avoid |
| `use_grounding` | bool | false | Use Google Search for real-time data (Gemini only) |
| `provider` | string | null | Override provider: "gemini", "openai", or "xai" |
| `transparent` | bool | false | Transparent background (OpenAI only, png/webp) |
| `n` | int | 1 | Number of images to generate, 1-10 (xAI only; forced to 1 when editing) |
| `save` | bool | true | Save to disk and stash |
| `mode` | string | "cloud" | "cloud" uses cloud.env, "local" uses local.env |
| `upload_to_cdn` | bool | false | Upload to Cloudflare CDN and return public URL |

### Response

```json
{
  "ok": true,
  "speech": "Generated image with gemini: A cute robot dog playing in a sunny park",
  "data": {
    "prompt": "A cute robot dog playing in a sunny park",
    "provider": "gemini",
    "model": "gemini-3-pro-image-preview",
    "aspect_ratio": "landscape",
    "dimensions": "1536x1024",
    "saved": {
      "path": "data/generated_images/generated_a_cute_robot_dog_playing_20260128_123456.jpg",
      "filename": "generated_a_cute_robot_dog_playing_20260128_123456.jpg"
    },
    "stash": {
      "space_id": "space_20260128_123456",
      "url": "stash://space_20260128_123456/f_abc123"
    }
  }
}
```

### Examples

**With style:**
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A mountain landscape at sunset",
    "style": "watercolor painting",
    "aspect_ratio": "wide"
  }'
```

**Using OpenAI with transparent background:**
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A logo with the text JARVIS in futuristic font",
    "provider": "openai",
    "transparent": true
  }'
```

**Using xAI (fast & cheap):**
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A futuristic cityscape at night",
    "provider": "xai",
    "aspect_ratio": "landscape"
  }'
```

**Batch generation (xAI only - multiple variations):**
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cute robot mascot",
    "provider": "xai",
    "n": 4
  }'
```

Response with multiple images:
```json
{
  "ok": true,
  "speech": "Generated image with xai: A cute robot mascot (4 images)",
  "data": {
    "image_count": 4,
    "saved": {
      "filename": "generated_a_cute_robot_mascot_20260202_123456.png",
      "space_id": "space_20260202_123456_abc123"
    },
    "additional_images": [
      { "filename": "..._2.png", "stash_ref": "stash://space_.../f_..." },
      { "filename": "..._3.png", "stash_ref": "stash://space_.../f_..." },
      { "filename": "..._4.png", "stash_ref": "stash://space_.../f_..." }
    ]
  }
}
```

All images are saved to `data/generated_images/` and the same stash space.

**With CDN upload** (get public URL in one step):
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cute robot dog playing in a park",
    "upload_to_cdn": true
  }'
```

Response includes `cdn_url` at the top level:
```json
{
  "ok": true,
  "cdn_url": "https://imagedelivery.net/xxx/yyy/public",
  "data": {
    "saved": { "filename": "..." },
    "cdn": { "url": "...", "image_id": "..." }
  }
}
```

**With grounding (Gemini - for real-time subjects):**
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "The current CEO of Tesla",
    "use_grounding": true
  }'
```

### Image-to-Image Editing

Edit an existing image by providing a `reference_image`. All 3 providers (Gemini, OpenAI, xAI) support editing. Keep prompts short and direct for best results.

**Edit with stash reference:**
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Change the dog to a cat, keep everything else the same",
    "reference_image": "stash://space_20260207_061950_d52e6091/f_8f9e57ebe3d3",
    "provider": "xai"
  }'
```

**Edit with URL:**
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Make the sky a sunset orange",
    "reference_image": "https://example.com/landscape.jpg",
    "provider": "gemini"
  }'
```

**Edit with local file path:**
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Add a hat to the character",
    "reference_image": "~/jarvis-voice/data/generated_images/my_character.png",
    "provider": "openai"
  }'
```

**Edit + upload to CDN (one step):**
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Change the background to a beach scene",
    "reference_image": "stash://space_xxx/file_id",
    "upload_to_cdn": true
  }'
```

Response includes both the edited image and CDN URL:
```json
{
  "ok": true,
  "speech": "Edited image with xai: Change the background...",
  "cdn_url": "https://imagedelivery.net/xxx/yyy/public",
  "data": {
    "prompt": "Change the background to a beach scene",
    "provider": "xai",
    "is_edit": true,
    "saved": { "filename": "generated_change_the_background_20260206_221950.png" },
    "cdn": { "url": "https://imagedelivery.net/xxx/yyy/public", "image_id": "yyy" }
  }
}
```

**Editing tips:**
- Keep prompts short: "change X to Y" works better than long descriptions
- The model preserves the rest of the image automatically
- xAI uses a separate `/v1/images/edits` endpoint (not the generation endpoint)
- OpenAI uses multipart `/v1/images/edits` endpoint
- Gemini includes the image inline in the request body
- `n` is forced to 1 when editing (batch editing not supported)

---

## Health Check

```bash
curl http://localhost:8880/api/generated-images/health
```

**Response:**
```json
{
  "ok": true,
  "directory": "~/jarvis-voice/data/generated_images",
  "exists": true,
  "image_count": 42,
  "total_size": 156789012,
  "total_size_human": "149.5 MB",
  "configured_provider": "gemini"
}
```

---

## Provider Configuration

The default provider is set in `config/cloud.env`:

```bash
# Provider: gemini (default), openai, or xai
IMAGE_TOOL_PROVIDER="gemini"

# Gemini model
GEMINI_IMAGE_MODEL="gemini-3-pro-image-preview"

# OpenAI model (if using openai provider)
OPENAI_IMAGE_MODEL="gpt-image-1.5"

# xAI model (if using xai provider)
# XAI_IMAGE_MODEL="grok-imagine-image"  # default
```

You can override the provider per-request using the `provider` parameter.

### Provider Comparison

| Feature | Gemini | OpenAI | xAI |
|---------|--------|--------|-----|
| Model | gemini-2.0-flash-preview | gpt-image-1.5 | grok-imagine-image |
| Image-to-image editing | ✅ | ✅ | ✅ |
| Grounding (real-time data) | ✅ | ❌ | ❌ |
| Text rendering | Good | Best | Good |
| Transparent backgrounds | ❌ | ✅ | ❌ |
| Batch generation (n > 1) | ❌ | ❌ | ✅ (1-10 images) |
| Quality parameter | ✅ (1K/2K/4K) | ✅ (low/med/high) | ❌ (not supported) |
| Speed | Medium | Slow | Fast |
| Cost | Medium | High | Low |

---

## Comparison: /api/images vs /api/generated-images

| Feature | /api/images | /api/generated-images |
|---------|-------------|----------------------|
| Purpose | Upload to Cloudflare CDN | Manage local images |
| Storage | Cloud (public URLs) | Local (private) |
| List images | No | Yes |
| Delete | No | Yes |
| Generate | No | Yes |
| Base64 export | No | Yes |
| Use case | Share publicly | Private management |

---

## Security

- Path traversal protection on all filename parameters
- Filenames cannot contain `..`, `/`, or `\`
- Images are only accessible via the API (not exposed to public internet)
