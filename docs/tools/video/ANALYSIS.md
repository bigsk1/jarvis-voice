# Understand a video

Attach a screen recording or clip in Jarvis Web and ask about what happens on
screen and what is said. Silent videos work too. You can combine a video with
PDFs, notes, recordings, or images: “Compare this demonstration with the steps
in the PDF.” Video counts as one source in the existing six-source cloud /
two-source local attachment limit.

Jarvis reads the original through `analyze_video`. It samples up to six frames,
labels them with their actual timestamps, and optionally transcribes audio from
the same interval. The result card shows the interval, sampled timestamps,
available evidence, warnings, and source playback. Audio-only MP4/WebM files
retain the existing audio transcription behavior. Some container/codec pairs
can be analyzed even when the browser cannot play them; download the original
from its source link in that case.

## Follow up and save

- “What is the error between 20 and 35 seconds?” requests a new, narrower read.
- “What does the speaker say?” uses the selected interval's transcript.
- “Save these findings to Canvas, with source and time references” uses the
  existing Canvas tool / Send to Canvas action.

The saved conversation preserves the original source reference, interval,
analysis excerpts, and audio/visual status across reloads. A narrower re-read
uses the original video, not a generated frame or transcript. Source links
retain their upload mode. If the modes use different Stash directories, switch
back to the original mode before re-reading a source. Expired sources must be
attached again; video uploads use the existing source-artifact retention policy.

Samples cannot prove what happened between frames. Jarvis reports a partial
result when it reads only part of a longer video or a requested evidence source
is unavailable. It can use successful visual evidence if transcription fails,
or the transcript if vision is unavailable, while naming the missing evidence.
No usable evidence is an error. Transcripts are bounded excerpts, and they are
not word-level timestamp alignments.

## Limits and configuration

No new Python dependency or database migration is required. FFmpeg and ffprobe
must be installed, and the selected mode must have a working vision provider.
Local mode uses the existing `OLLAMA_VISION_MODEL` pin; cloud uses the selected
image-analysis/chat provider and model. Optional speech uses the existing
`AUDIO_TRANSCRIBE_*` / `STT_*` configuration and its configured fallback policy.
Uploading alone never invokes a model; sending a request does.

| Setting | Default and maximum |
| --- | --- |
| `VIDEO_ANALYZE_MAX_FILE_MB` | 250 MB |
| `VIDEO_ANALYZE_MAX_DURATION_SECONDS` | 7200 seconds |
| `VIDEO_ANALYZE_MAX_WINDOW_SECONDS` | 300 seconds per read |
| `WEB_VIDEO_UPLOAD_RATE_LIMIT_PER_MINUTE` | 4 uploads; 0 disables this limiter |

The first three settings may lower the caps. Without an explicit end, analysis
starts at `start_seconds` (default 0) and stops at the interval cap or the end of
the video. Longer requests need additional, explicit intervals. Decoded input
is limited to 8192 pixels per dimension / 32 megapixels; frame images are scaled
to fit 1568 pixels. Processing has a ten-minute deadline. Stop uses the existing
tool process cancellation boundary; generated frames stay in memory and
extracted audio is temporary. Cloud providers retain their normal usage costs.

This works in native and Docker Web deployments. Chat only must be off for
video analysis. Existing tool profiles and disabled-tool settings still apply.
The tool accepts Stash references or policy-approved local files. To inspect a
remote video, use the existing download tool first; `analyze_video` does not
fetch remote URLs. FFmpeg input uses protocol and container restrictions
([FFmpeg protocol documentation](https://ffmpeg.org/ffmpeg-protocols.html)).

After reviewing and installing the change, restart Jarvis Web to load the new
upload and chat paths. The Web upload supplies an enabled-tool hint so it can
find the reader before a Tool RAG index refresh. For normal voice/CLI semantic
discovery, perform your usual mode-specific Tool RAG sync. Validation of this
change does not run that sync against live indexes.

Tool example:

```json
{
  "source": "stash://space_web_video_EXAMPLE/f_EXAMPLE",
  "question": "What error is visible, and what did the speaker say?",
  "start_seconds": 20,
  "end_seconds": 35,
  "include_audio": true
}
```

## Manual verification

1. Attach a short silent MP4 and a note. Send a comparison question; confirm a
   video reader result, timestamped findings, and “No audio stream” status.
2. Attach a spoken clip. Confirm the transcript refers to the same interval as
   the visual findings. Ask about a narrower interval and check its timestamps.
3. Reload the conversation, play/download the original, and ask to save the
   findings to Canvas with source and time references.
4. Stop during upload and during analysis. The draft or saved cancelled task
   should remain coherent; retry must not duplicate an admitted request.
5. In local mode, verify the two-source limit. With Chat only enabled, video
   submission should be rejected before a conversation task starts.
