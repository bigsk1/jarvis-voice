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

The file uploads directly to Stash (bypassing vision analysis). Foreground conversions return inline with a **⬇️ Download** button. If `convert_file` is selected in Background Tasks, the queued card appears first and the completed media preview returns to the same conversation.

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
| **PNG/WebP images** | Remove solid background, optional background color and tolerance |
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

You can also attach an image with the 🖼️ button and choose **Save to Stash**, then ask to convert it or remove its background. This preserves the full-size source and supplies its Stash reference. Simply changing JPEG to PNG does not make the background transparent.

For example: “Remove the white background from this image and save a transparent PNG using convert_file.”

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
.venv/bin/python skills/convert_file.py '{
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
| `remove_background` | bool | Remove an edge-connected solid color; requires PNG/WebP output | `true` |
| `background_color` | string | Corner-based detection by default, or an explicit RGB color; requires removal enabled | `"auto"` or `"#FFFFFF"` |
| `background_tolerance` | number (0–25) | Color tolerance percentage, default 5; requires removal enabled | `5` |

### Solid-background removal

This local ImageMagick operation is intended for logos, illustrations and objects on a plain background. It removes matching color connected to the image edges, while keeping enclosed matching colors such as white fur inside a dark outline. It preserves existing alpha and creates a new Stash file; the source stays unchanged.

Automatic color selection checks the image corners. Different corner colors cause an error rather than a guessed cutout. An explicit `background_color` can target a known edge-connected color when automatic detection is unsuitable. Reduce tolerance if subject details disappear; increase it cautiously for slightly off-white or JPEG-compressed backgrounds.

Removal accepts single-frame raster images up to 32 megapixels and outputs PNG or WebP with actual transparency. With removal enabled, resize accepts `WIDTHxHEIGHT` (optionally ending in `!`, `<`, `>` or `^`) or `PERCENT%`; the resized output must also stay within 32 megapixels. A no-match result or an entirely erased image is reported as a failure before saving to Stash.

This is color removal, not AI subject segmentation. Scenery, similar-colored subjects, fine hair, shadows and anti-aliased edges may need a mask editor. Thin fringes can remain. No model, GPU, API key or model download is required.

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

### Remove a white background and save a transparent PNG
```json
{
  "source": "stash://space_xxx/f_image",
  "target_format": "png",
  "options": {
    "remove_background": true,
    "background_color": "#FFFFFF",
    "background_tolerance": 5
  }
}
```

Omit `background_color` to detect a consistent corner color. Choose `webp` for a transparent WebP export; JPEG cannot store alpha.

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

Background-removal images use a checkerboard preview in foreground and completed background messages. The checkerboard is only a display aid and is not part of the downloaded image. The result includes `transparent: true`, dimensions, the removal method and a limitation note; `conversion_info` includes the detected color, tolerance and transparent/visible pixel counts.

A queued background receipt has no media yet. Completed PNG/WebP conversions render through the same existing background media path used for generated images, with Open and Download controls. A Stash reference is also retained for follow-up work.

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

These are listed in `system-packages.txt`. The native `./install-system-deps.sh` installer reads that file directly, including ImageMagick and Potrace. Run `./install-system-deps.sh --list` to inspect the package list without installing anything.

Solid-background removal works with ImageMagick 6 (`convert`) or 7 (`magick`). Pillow, already included in Jarvis's Python dependencies, validates the source and delivered alpha. Docker builds need the same ImageMagick package in the container.

## Troubleshooting

### "ImageMagick not installed"
```bash
sudo apt install imagemagick
```

### "Potrace not installed"
```bash
sudo apt install potrace
```

### Background removal fails or looks incomplete
- Choose PNG or WebP and enable `remove_background`; format conversion alone retains the background.
- For “Corner colors differ,” use a known `#RRGGBB` background color or a mask editor for complex scenes.
- For “No matching/new edge-connected background,” check the color and tolerance. If the source is already a cutout, use ordinary conversion to keep its alpha.
- For an entirely erased image, lower tolerance or choose a different color.
- Resize sources above 32 megapixels first. Animated or multipage images need a single-frame export before removal.
- If a downloaded file appears white in another viewer, check it on a colored or checkerboard background; that viewer may be displaying transparent pixels as white.

### SVG conversion looks blocky
- Use higher contrast source image
- Adjust threshold: `"options": {"threshold": "60%"}`
- Potrace is designed for line art, not photos

### Video conversion is slow
- Video transcoding is CPU-intensive
- Consider using GPU acceleration (requires FFmpeg with NVENC/VAAPI)
- Reduce resolution or increase CRF for faster encoding
