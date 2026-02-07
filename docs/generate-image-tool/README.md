# generate_image tool

Image generation and editing tool for Jarvis. Three providers, each with different strengths. Currently text-to-image only; image-to-image editing is the next feature to add.

## Files

| File | Purpose |
|------|---------|
| `skills/generate_image.py` | Main tool script. Provider functions + dispatch + stash save |
| `skills/generate_image.tool.json` | Tool definition (params the LLM sees) |
| `jarvis-web/client/js/chat.js` | Web UI modal: action select + provider-specific options |
| `jarvis-web/client/index.html` | Image action modal HTML |
| `jarvis-web/server/sockets/chat.py` | Backend routing: action -> tool_overrides -> orchestrator |
| `orchestrator/orchestrator_v2.py` | Applies tool_overrides before executing tool calls |

## Current providers

### Gemini (default)

- Model: `gemini-2.0-flash-preview-image-generation` (configurable via `GEMINI_IMAGE_MODEL`)
- Supports aspect ratios: 1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2, 4:5, 5:4
- Resolution/size: 1K, 2K, 4K
- Google Search grounding for real-time data (weather, stocks, current events)
- Can accept `context_data` from other Jarvis tools
- API: `POST /v1beta/models/{model}:generateContent` with `responseModalities: ["TEXT", "IMAGE"]`

### OpenAI

- Model: `gpt-image-1.5` (configurable via `OPENAI_IMAGE_MODEL`)
- Best text rendering and instruction following
- Sizes: 1024x1024, 1536x1024, 1024x1536
- Quality: low, medium, high (mapped from 1K/2K/4K)
- Transparent backgrounds (png/webp only)
- Output formats: png, jpeg, webp
- API: `POST /v1/images/generations` (JSON body, base64 response)

### xAI

- Model: `grok-imagine-image` (configurable via `XAI_IMAGE_MODEL`)
- Fast and cheap
- Batch generation: 1-10 images per request
- Aspect ratios: 1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2, 2:1, 1:2, 19.5:9, 9:19.5, 20:9, 9:20
- API: `POST /v1/images/generations` (JSON body, base64 or URL response)

## Provider selection

The provider is determined by `config_loader.py` with this priority:

1. `JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER` env var (set by web UI modal per-request)
2. `IMAGE_TOOL_PROVIDER` in `config/cloud.env` or `config/local.env`
3. Fallback: `gemini`

The `JARVIS_OVERRIDE_` mechanism lets the web UI override the default provider for a single request without changing the global config. The override env var is set in `chat.py` before spawning the orchestrator subprocess.

## Web UI flow (current)

1. User uploads/drops an image in the chat input
2. Image action modal appears with three choices:
   - **Analyze image** - runs vision analysis (default, existing behavior)
   - **Image to video** - routes to `generate_video` with xAI (forces params via tool_overrides)
   - **Image to image** - routes to `generate_image` (forces provider/params via tool_overrides)
3. For "Image to image", the modal shows provider-specific options (Gemini grounding, OpenAI transparency, xAI batch count)
4. Backend stashes the uploaded image, builds `tool_overrides`, and sends to orchestrator
5. Orchestrator applies overrides after the LLM generates creative arguments but before tool execution

## What "Image to image" does today (the problem)

The current flow tells the LLM about the uploaded reference image and asks it to use `generate_image`. But `generate_image.py` has no `reference_image` parameter. None of the three provider functions accept a source image. The result is text-to-image generation where the LLM tries to describe the uploaded image in its prompt. The output is a brand new image, not an edit of the original.

## Image-to-image editing: what each provider API supports

All three providers have image editing APIs. Here's what they look like:

### xAI - same endpoint, add `image_url`

xAI editing uses the same `/v1/images/generations` endpoint. You just add `image_url` to the JSON payload. The model understands the image and applies changes based on the prompt.

```
POST https://api.x.ai/v1/images/generations
{
  "model": "grok-imagine-image",
  "prompt": "Change the golden retriever to a black labrador",
  "image_url": "data:image/jpeg;base64,{base64_data}",
  "response_format": "b64_json"
}
```

`image_url` accepts:
- A public URL pointing to an image
- A base64 data URI: `data:image/jpeg;base64,...`

xAI also supports multi-turn editing (feed output URL back as input) and style transfer.

Ref: https://docs.x.ai/developers/model-capabilities/images/generation

### Gemini - include image in contents array

Gemini editing uses the same `generateContent` endpoint. Include the image as `inline_data` in the `contents[].parts[]` array alongside the text prompt.

```
POST /v1beta/models/gemini-2.5-flash-image:generateContent
{
  "contents": [{
    "parts": [
      {"text": "Change the bunny head to a goat head"},
      {"inline_data": {"mime_type": "image/jpeg", "data": "<base64>"}}
    ]
  }],
  "generationConfig": {
    "responseModalities": ["TEXT", "IMAGE"]
  }
}
```

gemini-3-pro-image-preview supports up to 14 reference images in a single request. The model uses advanced reasoning ("Thinking") to handle complex multi-image compositions.

Ref: https://ai.google.dev/gemini-api/docs/image-generation

### OpenAI - two options

OpenAI has two APIs that support image editing:

**Option A: Images API** (`POST /v1/images/edits`) - multipart/form-data

```
POST https://api.openai.com/v1/images/edits
Content-Type: multipart/form-data

-F "image[]=@source.png"
-F "prompt=Change the bunny head to a goat head"
-F "model=gpt-image-1"
-F "size=1024x1024"
-F "quality=medium"
```

Supports up to 16 input images (gpt-image-1/1.5). Also supports `mask` for inpainting, `input_fidelity` (high/low) for controlling how closely to match the source. Response is the same format as generations (base64_json).

Python's `requests` handles multipart cleanly:
```python
response = requests.post(
    "https://api.openai.com/v1/images/edits",
    headers={"Authorization": f"Bearer {api_key}"},
    files={"image": ("image.png", image_bytes, "image/png")},
    data={"model": "gpt-image-1", "prompt": prompt, "size": size},
    timeout=180
)
```

**Option B: Responses API** (`POST /v1/responses`) - JSON, no multipart

The Responses API accepts images 3 ways: public URL, base64 data URL, or File ID. It's JSON-based. But it's a completely different API surface -- it wraps image generation as a tool inside a chat/agent flow. More complex to integrate, designed for multi-turn conversational editing.

**Recommendation: Option A (Images API).** It's a direct edit call that returns the same response format as the current generation endpoint. The multipart difference is ~5 lines of code.

Ref: https://platform.openai.com/docs/api-reference/images/createEdit

## Implementation plan

### 1. Add `reference_image` parameter to the tool

New parameter in `generate_image.tool.json`:

```json
"reference_image": {
  "type": "string",
  "description": "Source image for editing. Accepts: stash:// ref, local file path, public URL, or base64 data URI. When provided, the tool edits this image based on the prompt instead of generating from scratch."
}
```

This follows the same pattern as `generate_video`'s `image_url` parameter, which already handles stash refs, local paths, URLs, and base64 data URIs.

### 2. Add `_resolve_image_to_base64()` helper in `generate_image.py`

Resolves the reference image from any supported format to raw base64 + mime_type. Reuse logic from `generate_video.py`'s `_resolve_image_source()` and `safe_resolve_file()`.

```python
def _resolve_image_to_base64(image_source: str) -> tuple[str, str]:
    """
    Resolve image source to (base64_data, mime_type).
    
    Handles:
    - stash:// refs -> resolve to local path -> read + encode
    - Local file paths -> read + encode
    - http/https URLs -> download + encode
    - data: URIs -> extract base64 + mime
    - Raw base64 -> pass through (assume jpeg)
    """
```

### 3. Update each provider function

**`generate_image_xai()`** - add `image_url` param:
- If `reference_image` is provided, resolve to base64 data URI
- Add `image_url` field to the JSON payload
- Same endpoint, same response handling
- Simplest change of the three

**`generate_image_gemini()`** - add `reference_image` param:
- If provided, resolve to base64 bytes
- Add as `inline_data` part in the `contents[].parts[]` array (after the text prompt)
- Same endpoint, same response handling
- Also straightforward

**`generate_image_openai()`** - add `reference_image` param:
- If provided, switch from `/v1/images/generations` to `/v1/images/edits`
- Change from JSON body to multipart/form-data (using `requests` `files=` + `data=`)
- Send image as file bytes, prompt as form field
- Response format stays the same (base64_json)
- About 5 extra lines vs the generation code path -- add an `if reference_image:` branch

### 4. Update the dispatch function

`generate_image()` gains the `reference_image` param and passes it through to whichever provider is active.

### 5. Update `main()` to parse `reference_image` from args

Same pattern as the existing params: `args.get('reference_image')`.

### 6. Update `chat.py` to pass `reference_image` in tool_overrides

The "Image to image" action in `chat.py` already stashes the uploaded image and gets a `stash_ref`. Currently that ref is only mentioned in the LLM's context message. With this change, it also goes into `tool_overrides['generate_image']['reference_image']`.

```python
# In the 'image' action block:
tool_overrides['generate_image'] = {
    'reference_image': stash_ref,  # NEW: actual image editing
    # ... existing provider, aspect_ratio, etc.
}
```

### 7. Update tool_overrides metadata

Add `reference_image` to the response data so the output shows whether the image was generated from scratch or edited from a reference. Tag stash entries with `'image_edited'` vs `'ai_generated'`.

### 8. Sync tool definitions

After updating `generate_image.tool.json`:
```bash
./bin/sync_tools.py cloud
```

## Edge cases to handle

- **Large images**: base64 encoding doubles file size. A 10MB image becomes 13MB+ in base64. Set reasonable limits or resize before encoding.
- **Missing/invalid stash ref**: If the stash ref can't be resolved, fall back to text-to-image with a warning rather than failing.
- **Provider doesn't support editing**: Not applicable here (all three do), but the code should handle it gracefully if a future provider lacks support.
- **Aspect ratio mismatch**: The reference image might be 9:16 but the user selects 1:1. Each provider handles this differently. Document the behavior and let the provider decide.
- **xAI batch + editing**: Does xAI support `n > 1` with `image_url`? Need to test. If not, force `n=1` when editing.

## Testing plan

Test each provider with a simple edit (change a color, swap an element):

```bash
# xAI: change dog breed in a photo
./orchestrator/orchestrator_v2.py cloud "edit the image at stash://xxx to change the dog to a cat"

# Direct tool test via FastAPI
curl -X POST http://localhost:8880/api/tools/generate_image \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Change the bunny head to a goat head",
    "provider": "xai",
    "reference_image": "stash://space_xxx/file_xxx"
  }'

# Web UI test
# 1. Upload image -> select "Image to Image" -> pick xAI -> type edit instructions -> send
```

## File change summary

| File | Change |
|------|--------|
| `skills/generate_image.py` | Add `_resolve_image_to_base64()`, update all 3 provider functions + dispatch |
| `skills/generate_image.tool.json` | Add `reference_image` parameter |
| `jarvis-web/server/sockets/chat.py` | Pass `reference_image: stash_ref` in tool_overrides for image action |
| -- | Run `./bin/sync_tools.py cloud` after tool.json update to refresh LLM's tool list |

The web UI modal (`index.html`, `chat.js`) and orchestrator (`orchestrator_v2.py`) need no changes -- they already handle the flow correctly. The modal collects params, `chat.py` builds overrides, and the orchestrator applies them. We just need to add the actual image data to the override payload and teach the tool how to use it.
