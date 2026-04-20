# Jarvis Tool Knowledge and Operational Guidelines

This file contains knowledge about Jarvis tools, provider limitations, common failure patterns, and best practices. When uncertain about a tool or encountering errors, search memory for relevant guidance before retrying blindly.

## General Rules

- If a tool fails or returns unexpected results, do not retry with the same parameters. Search memory first for known limitations.
- If a provider ignores a parameter you set (like duration or resolution), that is an API limitation, not a fixable error. Inform the user.
- Never retry an expensive tool (video, image, music generation) more than once per request. If the first result is not what the user wants, explain what happened and ask how to proceed.
- When a tool returns a stash ref (stash://space_xxx/file_xxx), that ref is permanent. Provider URLs (like vidgen.x.ai or platform.openai.com links) expire and are temporary.

## Video Generation (generate_video)

### Provider: xAI (Grok)

- xAI video editing (video_url parameter) can only change visual content and style. It cannot change duration, aspect ratio, or resolution. Those are locked to the original video.
- If the user wants a different duration or aspect ratio, do not use video editing. Regenerate from the source image using image_url instead.
- xAI editing requires a public http/https URL. Stash refs (stash://) do not work for xAI video editing.
- xAI public video URLs (vidgen.x.ai) expire after approximately 4 hours. After that, the video can only be referenced by its stash ref but cannot be edited.
- xAI supports durations: 5 seconds and 10 seconds only (closest to requested). Maximum video length for editing is 8.7 seconds.
- If you request 8 seconds on an edit, xAI will return 5 seconds. This is normal, not an error.

### Provider: OpenAI (Sora)

- OpenAI Sora supports 4, 8, and 12 second durations.
- Sora uses video_id (starts with "video_") for remix/editing, not URLs.
- OpenAI video URLs expire after approximately 60 minutes.
- Sora supports native audio generation (dialogue and sound effects).
- Sora aspect ratios: 16:9 and 9:16 only. Resolutions: 720p and 1080p.

### Provider: Google Gemini

- Gemini video generation supports image-to-video (provide image_url).
- Gemini video URLs have unknown expiration, treat as 4 hours to be safe.

### Common Video Mistakes

- Do not call generate_video repeatedly when the result duration does not match. The provider decides the actual duration based on its own constraints.
- Do not attempt to extend a 5-second video to 8 seconds via editing. Editing preserves the original duration. To get a longer video, generate a new one from the source image.
- When the user says "make it longer" for a video, use image_url with the original source image and a longer duration, not video_url editing.

## Image Generation (generate_image)

### Provider: Gemini (default)

- Supports up to 14 reference images per editing request.
- Google Search grounding available for real-time data in images (weather, stock prices, current events).
- Aspect ratios: 1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2, 4:5, 5:4.

### Provider: OpenAI

- Best for text rendering and detailed instruction following.
- Sizes: 1024x1024, 1536x1024, 1024x1536.
- Quality levels: low, medium, high.
- Supports transparent backgrounds (png/webp only).

### Provider: xAI

- Fastest and cheapest option.
- Batch generation: 1 to 10 images per request (text-to-image only, editing forces n=1).
- Does not support quality parameter.

### Common Image Mistakes

- For editing, keep prompts short and direct. "Change the dog to a cat" works better than a paragraph describing the entire scene.
- xAI image editing uses a separate endpoint from generation. The generations endpoint ignores reference images.

## Music Generation (generate_music)

- ElevenLabs is the only supported provider.
- Generation can take 30 to 90 seconds. Do not retry if it seems slow.
- Custom mode allows specifying lyrics separately from the style prompt.

## Email (send_email)

- Contacts are resolved by name from the contacts file. Use names, not email addresses when possible.
- Attachments support stash refs and direct file paths.
- Do not send the same email twice in one conversation. The system has rate limiting (60 seconds minimum between sends).

## Phone Calls (phone_call)

- Multiple personas available: Jarvis, James (professional), Jay (casual), Samantha (female).
- Sync mode waits for call completion. Async mode returns immediately and the user checks later.
- Call status can be checked with a follow-up call. This is a legitimate multi-call pattern.

## Supa-Crawl-Knowledge and `supa_crawl_knowledge.md`

- `supa_crawl_knowledge` with `action=list_sites` and `limit=100` returns the full crawled-site list in `data.sites` when `returned` matches `count`.
- When the user asks to update `jarvis-intel/supa_crawl_knowledge.md` with **all** sites (for auto-context / memory ranking), you must: (1) `list_sites`, (2) `manage_intel` `update` with markdown that includes **every** site row—never a partial preview or a note to use the tool instead of listing them in the file.
- Recommended columns: id, site name, pages, seed URL. Duplicates in display names can exist (e.g. two "Selfh St" with different URLs); keep both rows.

## Memory and Search Tools

- search_memory: Best for keyword lookups. Uses FTS5 with BM25 ranking. Has the deepest fallback chain (FTS5 then AND then OR then LIKE).
- semantic_recall: Best for natural language questions and meaning-based search. Falls back to FTS5 if semantic search returns nothing.
- recall: Simple keyword matching with SQL LIKE. Use as a last resort or for category-filtered lookups.
- When uncertain about anything, use search_memory first (faster, broader fallback), then semantic_recall if keywords fail.

## Stash System

- Stash refs are permanent identifiers for saved artifacts (stash://space_xxx/file_xxx).
- Provider URLs (video URLs, image URLs from cloud services) are temporary and expire.
- Always reference artifacts by stash ref for reliability. Use provider URLs only when a tool specifically requires a public URL.
- meta.json in each stash space contains source_url and source_url_created for checking URL freshness.

## Web UI Prompts

- Users can type @prompt_name before their message to inject specialized instructions.
- Available prompts include: research, quick, debug, compare, email, deep_research, code_review, and others.
- Prompts guide your behavior for that specific request without changing your general capabilities.

## Response Guidelines

- Never say "I have completed the task using X tools." Always summarize what was actually found or done.
- Never start with "Great!" or "Perfect!" or "I have successfully..." - get straight to the answer.
- If a tool partially succeeded (got some data but not all), report what you found rather than saying it failed.
- File names from stash are auto-generated and long. Say "saved to stash" instead of reading the full filename.
- Phrases to avoid in spoken responses: "I have successfully", "Let me", "Sure thing", "Absolutely", "Great question", "Here is what I found for you".
