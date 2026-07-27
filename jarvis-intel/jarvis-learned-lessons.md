# Jarvis Learned Lessons

Lessons discovered during operation. Jarvis appends here when encountering critical tool limitations, provider quirks, or recurring failure patterns. Human reviews periodically and promotes valuable lessons to jarvis-tool-knowledge.md.

## Lessons


[2026-05-07 03:00 PDT]
- **Topic**: xAI Image Aspect Ratio Behavior
- **Lesson**: xAI Grok image model (especially quality mode) treats aspect_ratio as a strong suggestion, not hard constraint. Often produces taller/vertical (9:16-ish) crops even when 1:1 is requested, prioritizing prompt composition. For critical square framing, add explicit prompt text: "square composition, 1:1 aspect ratio, centered subject, no cropping". This should be auto-ingested into memory context for future image generations.

[2026-07-26 21:51 PDT]
- **Topic**: ElevenLabs Music (`generate_music`) Terms of Service / Prompt Filtering
- **Lesson**: ElevenLabs Music API returns HTTP 400 with "Your prompt appears to have violated our Terms of Service" when prompts or titles reference real artists/bands for style cloning (e.g. "like the band Tool", title "Deep Orbit (Tool-inspired)"). Do **not** name specific copyrighted artists, bands, or "inspired by [artist]" in `prompt`, `title`, `genre`, `mood`, or composition text. Describe the sound in original terms instead (e.g. progressive metal, polyrhythmic, dark atmospheric guitars, deep melodic intensity, odd time signatures, heavy drop-tuned riffs) without naming the act. Failed args that triggered ToS: title=`Deep Orbit (Tool-inspired)`, duration_seconds=30, genre=metal, mood=`dark, mysterious, intense`, tempo=medium (user intent was Tool-like deep melodies). Retry without artist reference succeeded as title=`Deep Orbit` instrumental metal. Treat this as a global rule for all future `generate_music` calls.

