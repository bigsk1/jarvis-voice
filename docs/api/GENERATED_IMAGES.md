# Generated Images API

Manage locally generated images in `data/generated_images/`.

Unlike `/api/images` (Cloudflare CDN uploads), these routes manage the **local** generated images folder where AI-generated images are stored privately.

**Base URL**: `http://localhost:8880/api/generated-images`

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all images |
| GET | `/{filename}` | Get image file |
| GET | `/{filename}/base64` | Get image as base64 |
| DELETE | `/{filename}` | Delete image |
| POST | `/generate` | Generate new image |
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

## Generate New Image

Generate a new image using the configured AI provider (Gemini or OpenAI).

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
| `prompt` | string | **required** | What to generate |
| `aspect_ratio` | string | "square" | square, landscape, portrait, wide, tall, 16:9, 4:3 |
| `image_size` | string | "2K" | 1K, 2K, or 4K |
| `style` | string | null | Art style (photorealistic, watercolor, anime, etc.) |
| `negative_prompt` | string | null | Things to avoid |
| `use_grounding` | bool | false | Use Google Search for real-time data (Gemini only) |
| `provider` | string | null | Override provider: "gemini" or "openai" |
| `transparent` | bool | false | Transparent background (OpenAI only, png/webp) |
| `save` | bool | true | Save to disk and stash |
| `mode` | string | "cloud" | "cloud" uses cloud.env, "local" uses local.env |

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

**With grounding (Gemini - for real-time subjects):**
```bash
curl -X POST http://localhost:8880/api/generated-images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "The current CEO of Tesla",
    "use_grounding": true
  }'
```

---

## Health Check

```bash
curl http://localhost:8880/api/generated-images/health
```

**Response:**
```json
{
  "ok": true,
  "directory": "/home/boss/jarvis-voice/data/generated_images",
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
# Provider: gemini (default) or openai
IMAGE_TOOL_PROVIDER="gemini"

# Gemini model
GEMINI_IMAGE_MODEL="gemini-3-pro-image-preview"

# OpenAI model (if using openai provider)
OPENAI_IMAGE_MODEL="gpt-image-1.5"
```

You can override the provider per-request using the `provider` parameter.

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
