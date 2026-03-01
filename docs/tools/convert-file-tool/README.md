# Convert File Tool

Local media file conversion tool using ImageMagick, FFmpeg, and Potrace.

## Overview

The `convert_file` tool converts media files between formats using local system tools. No external APIs - all processing happens on your server.

## Web UI Usage (Recommended)

The easiest way to convert files is using the **🔄 Convert button** in the web UI:

1. **Click the 🔄 button** (next to the 🖼️ attach button)
2. **Select any media file** (image, video, or audio)
3. **Choose target format** from the dropdown
4. **Click "Convert"**

The file uploads directly to stash (bypassing vision analysis) and converts immediately. Results display inline with a **⬇️ Download** button.

### Why use the 🔄 button?
- **Bypasses vision analysis** - no "I can't convert" responses
- **Accepts all media types** - images, video, audio
- **Format selector** with descriptions
- **Advanced options** for fine-tuning conversions
- **Direct download button** on converted files

### Advanced Options

Click "⚙️ Advanced Options" in the modal to reveal format-specific settings:

| Source Type | Available Options |
|-------------|-------------------|
| **Images** | Resize (e.g., "800x600" or "50%"), Quality (1-100), Strip metadata, Grayscale |
| **SVG conversion** | Threshold (black/white cutoff), Speckle size (suppress small dots) |
| **Videos** | Resolution, CRF quality (0-51, lower=better), FPS, Max duration |
| **Audio** | Bitrate (128k-320k), Sample rate (44.1kHz-96kHz), Channels (mono/stereo) |

These options map directly to the tool parameters documented below.

## Supported Conversions

### Image Formats (ImageMagick)

| From | To |
|------|-----|
| JPG, JPEG | PNG, WebP, GIF, TIFF, BMP, ICO |
| PNG | JPG, WebP, GIF, TIFF, BMP |
| WebP | JPG, PNG, GIF |
| GIF | JPG, PNG, WebP |
| TIFF | JPG, PNG, WebP |
| BMP | JPG, PNG, WebP |

### Raster to Vector (Potrace)

| From | To | Notes |
|------|-----|-------|
| JPG, PNG | SVG | Best results with high-contrast images |

Potrace traces bitmap images to vector. Works best on:
- Logos and icons
- Line art
- High-contrast images
- Text/typography

**Not ideal for:** photographs, gradients, complex color images

### Video Formats (FFmpeg)

| From | To |
|------|-----|
| MP4 | WebM, MOV, AVI, MKV |
| WebM | MP4, MOV, AVI |
| MOV | MP4, WebM, AVI |
| AVI | MP4, WebM, MOV |
| MKV | MP4, WebM |

### Audio Formats (FFmpeg)

| From | To |
|------|-----|
| MP3 | WAV, FLAC, OGG, AAC, M4A, Opus |
| WAV | MP3, FLAC, OGG, AAC |
| FLAC | MP3, WAV, OGG |
| OGG | MP3, WAV, FLAC |
| AAC/M4A | MP3, WAV, FLAC |

### Video to Audio Extraction (FFmpeg)

| From | To |
|------|-----|
| Any video | MP3, WAV, FLAC, OGG, AAC |

## Usage

### Via Web UI (Recommended)

Use the **🔄 Convert button** in the chat interface. This is the cleanest method as it:
- Uploads directly to stash (no vision analysis)
- Shows format options with descriptions
- Displays results inline with download button

### Via Voice/Chat

When using voice or typing directly, provide the stash reference:

```
"Convert stash://space_xxx/file_id to PNG"
"Convert the file at stash://space_xxx/f_yyy to SVG using the convert_file tool"
"Extract audio from stash://space_xxx/f_video as MP3"
```

**Note:** Uploading via the 🖼️ button triggers vision analysis first, which may give unhelpful responses before converting. Use the 🔄 button instead.

### Via API

**1. Upload file to stash (Web UI server):**
```bash
curl -X POST http://localhost:5001/api/stash/upload \
  -F "file=@image.jpg" \
  -F "labels=for_conversion"
```

Or via main API:
```bash
curl -X POST http://localhost:8880/api/stash/upload \
  -F "file=@image.jpg" \
  -F "labels=for_conversion"
```

Response:
```json
{
  "ok": true,
  "stash_ref": "stash://space_20260205_123456_abc/f_xyz789",
  "filename": "image.jpg"
}
```

**2. Convert via orchestrator:**
```bash
curl -X POST http://localhost:8880/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Convert stash://space_xxx/f_xyz to svg using the convert_file tool"}'
```

**3. Download result (via Web UI server):**
```bash
curl -O http://localhost:5001/api/stash/{space_id}/{file_id}
```

Or via main API:
```bash
curl -O http://localhost:8880/api/stash/space/{space_id}/file/{file_id}/download
```

### Direct Tool Call

```bash
python3 skills/convert_file.py '{
  "source": "stash://space_xxx/f_yyy",
  "target_format": "png",
  "options": {"quality": 90}
}'
```

## Options

### Image Options

| Option | Type | Description | Example |
|--------|------|-------------|---------|
| `quality` | int (1-100) | JPEG/WebP quality | `90` |
| `resize` | string | Resize dimensions | `"800x600"` or `"50%"` |
| `strip_metadata` | bool | Remove EXIF data | `true` |

### SVG (Potrace) Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `threshold` | string | Black/white threshold | `"50%"` |
| `turdsize` | int | Suppress speckles smaller than N | `2` |
| `alphamax` | float | Corner smoothness (0-1.34) | `1.0` |

### Video Options

| Option | Type | Description | Example |
|--------|------|-------------|---------|
| `crf` | int (0-51) | Quality (lower=better) | `23` |
| `resolution` | string | Output resolution | `"1920x1080"` |
| `fps` | int | Frame rate | `30` |
| `duration` | int | Max seconds | `60` |

### Audio Options

| Option | Type | Description | Example |
|--------|------|-------------|---------|
| `bitrate` | string | Audio bitrate | `"192k"` |
| `sample_rate` | int | Sample rate Hz | `44100` |
| `channels` | int | 1=mono, 2=stereo | `2` |

## Examples

### Convert JPG to PNG with resize
```json
{
  "source": "/path/to/image.jpg",
  "target_format": "png",
  "options": {"resize": "800x600", "strip_metadata": true}
}
```

### Convert PNG to SVG (vectorize)
```json
{
  "source": "stash://space_xxx/f_logo",
  "target_format": "svg",
  "options": {"threshold": "40%"}
}
```

### Convert video to WebM
```json
{
  "source": "/path/to/video.mp4",
  "target_format": "webm",
  "options": {"crf": 30, "resolution": "1280x720"}
}
```

### Extract audio from video
```json
{
  "source": "stash://space_xxx/f_video",
  "target_format": "mp3",
  "options": {"bitrate": "320k"}
}
```

## Output

Converted files are saved to **stash** (not generated_images/videos). 

### In Web UI

Converted files display **inline** in the chat:
- **Images**: Thumbnail with lightbox (click to expand)
- **Video**: Video player with controls
- **Audio**: Audio player with controls
- **Other**: Download card

All formats show a **⬇️ Download** button for direct download.

### Via API

Access converted files:
- Web UI server: `/api/stash/{space_id}/{file_id}`
- Main API: `/api/stash/space/{space_id}/file/{file_id}/download`
- Stash reference: `stash://space_xxx/f_yyy`

## Requirements

System packages (Ubuntu/Debian):
```bash
sudo apt install imagemagick potrace ffmpeg
```

These are listed in `system-packages.txt`.

## Troubleshooting

### "ImageMagick not installed"
```bash
sudo apt install imagemagick
```

### "Potrace not installed"
```bash
sudo apt install potrace
```

### SVG conversion looks blocky
- Use higher contrast source image
- Adjust threshold: `"options": {"threshold": "60%"}`
- Potrace is designed for line art, not photos

### Video conversion is slow
- Video transcoding is CPU-intensive
- Consider using GPU acceleration (requires FFmpeg with NVENC/VAAPI)
- Reduce resolution or increase CRF for faster encoding
