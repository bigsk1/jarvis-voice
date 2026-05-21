# Jarvis Learned Lessons

Lessons discovered during operation. Jarvis appends here when encountering critical tool limitations, provider quirks, or recurring failure patterns. Human reviews periodically and promotes valuable lessons to jarvis-tool-knowledge.md.

## Lessons


[2026-05-07 03:00 PDT]
- **Topic**: xAI Image Aspect Ratio Behavior
- **Lesson**: xAI Grok image model (especially quality mode) treats aspect_ratio as a strong suggestion, not hard constraint. Often produces taller/vertical (9:16-ish) crops even when 1:1 is requested, prioritizing prompt composition. For critical square framing, add explicit prompt text: "square composition, 1:1 aspect ratio, centered subject, no cropping". This should be auto-ingested into memory context for future image generations.

[2026-05-21 09:49 PDT]
- **Topic**: User correction (experience 1)
- **Lesson**: Boss corrected a prior answer (clarification): "No, I meant Portland OR, not Portland ME.". Avoid repeating this failure pattern in similar follow-up tasks.
