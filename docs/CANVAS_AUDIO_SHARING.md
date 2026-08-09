# Canvas xAI Audio Sharing

Jarvis can publish retained tracks from the Canvas Audio Gallery as animated
waveform MP4s through the xAI Files API. The original MP3, Opus, WAV, or other
supported audio file remains unchanged in `data/generated_music/`. FastAPI
creates a temporary MP4 containing the complete track because xAI public URLs
accept `video/mp4` but do not accept native audio content types.

## Architecture

The browser never receives the xAI or internal Jarvis API key:

```text
Canvas Audio Gallery
  -> authenticated Canvas Flask proxy
  -> authenticated internal FastAPI generated-music route
  -> temporary animated waveform MP4
  -> xAI Files API
```

FastAPI owns validation, conversion, upload and revoke operations, share
history, and share-aware local deletion. Canvas owns only the browser UI and
protected proxy routes. The temporary MP4 is removed after the upload attempt;
it is not added to the local Video Gallery.

## Enable sharing

Add these settings to the mode file used by both Jarvis API and Canvas, then
restart both services:

```dotenv
XAI_API_KEY="your-xai-api-key"
CANVAS_XAI_AUDIO_SHARE=true
CANVAS_XAI_AUDIO_SHARE_DEFAULT_TTL_DAYS=7
CANVAS_XAI_AUDIO_SHARE_MAX_BYTES=48000000
```

The **Share** action appears only when the feature is enabled, `XAI_API_KEY` is
nonblank, and the retained file uses a supported audio extension. Grok CLI OAuth
does not authorize the xAI Files API. Enabling this in local mode is an explicit
cloud-egress choice.

## Publish, expire, and revoke

1. Review the complete track in the Canvas Audio Gallery.
2. Select **Share**, then choose 1, 7, or 30 days.
3. Confirm that the waveform MP4 will be public and publish it.
4. Copy or open the resulting `https://files-cdn.x.ai/...` URL.
5. Use **Revoke** in Share History to revoke the URL and delete the xAI file
   before its scheduled expiry.

The animated 854x480 MP4 uses H.264 video and 128-kbps AAC audio. Jarvis assigns
the video bitrate dynamically from the track duration and configured byte limit,
so shorter tracks retain substantially more waveform detail while longer tracks
remain within xAI's upload boundary. Conversion removes source container
metadata and chapters, preserves the full audio timeline, and creates a
browser-streamable fast-start file. The configured byte limit applies to the
final MP4, not the original audio file.

Jarvis gives the xAI file the selected lifetime before creating its public URL.
The public URL inherits that lifetime, so xAI automatically deletes the
underlying file when it expires. Expired rows remain in the local registry as
history.

The registry is stored at
`data/generated_music/.shares/xai_audio_registry.json`. It contains xAI file
and share IDs, public URLs, source hashes, sizes, and lifecycle timestamps. It
contains neither API keys nor audio or video bytes. The cleanup scripts exclude
`data/generated_music/`, including this registry.

Deleting retained local audio checks the registry first. When active shares
exist, Canvas offers to revoke the public URLs, delete the xAI files, and only
then delete the local track. A failed remote revoke prevents local deletion so
the public copy is not forgotten.

## Validation boundary

Before conversion, FastAPI enforces filename/path containment, rejects symbolic
links, validates the audio stream with `ffprobe`, and fingerprints the complete
source file. Publishing must present the same fingerprint that Canvas reviewed.
FastAPI checks the fingerprint again after conversion and enforces the final MP4
size before upload.

Jarvis does not transcribe or scan the audio content for secrets. The dialog
therefore requires the user to review the complete track and explicitly
acknowledge that it will be public.
