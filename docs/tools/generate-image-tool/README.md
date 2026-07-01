# generate_image tool

Image generation and editing tool for Jarvis. Supports text-to-image and image-to-image editing across three providers: Gemini, OpenAI, and xAI.

## Files

| File | Purpose |
|------|---------|
| `skills/generate_image.py` | Main tool script. Provider functions, image resolution, dispatch, stash save |
| `skills/generate_image.tool.json` | Tool definition (params the LLM sees) |
| `jarvis-web/client/js/chat.js` | Web UI modal: action select + provider-specific options |
| `jarvis-web/client/index.html` | Image action modal HTML |
| `jarvis-web/server/sockets/chat.py` | Backend routing: action -> tool_overrides -> orchestrator |
| `orchestrator/orchestrator_v2.py` | Applies tool_overrides before executing tool calls |

## Providers

### Gemini (default)

- Catalog default: `gemini-3.1-flash-image` (optional pin: `GEMINI_IMAGE_MODEL`)
- Aspect ratios: 1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2, 4:5, 5:4
- Resolution/size: 1K, 2K, 4K
- Google Search grounding for real-time data (weather, stocks, current events)
- Can accept `context_data` from other Jarvis tools
- Generation API: `google.genai.Client.models.generate_content()` with typed `GenerateContentConfig` and `ImageConfig`
- Editing: same SDK call with the reference image as a typed content part alongside the text prompt. Current Jarvis tool contract accepts one reference image.

### OpenAI

- Catalog default: `gpt-image-2` (optional pin: `OPENAI_IMAGE_MODEL`)
- Best text rendering and instruction following
- Sizes: legacy models use 1024x1024, 1536x1024, 1024x1536; `gpt-image-2` supports flexible 1K/2K/4K dimensions up to 3840px on the long edge
- Quality: low, medium, high (mapped from 1K/2K/4K)
- Transparent backgrounds (png/webp only) on `gpt-image-1.5`, `gpt-image-1`, and `gpt-image-1-mini`; `gpt-image-2` does not currently support transparent backgrounds
- Output formats: png, jpeg, webp
- Generation API: `POST /v1/images/generations` (JSON body, base64 response)
- Editing API: `POST /v1/images/edits` (multipart/form-data). Image bytes sent as a file field, prompt and other params as form fields. Supports `mask` for inpainting and `input_fidelity` (high/low).

### xAI

- Catalog default: `grok-imagine-image` (optional pin: `XAI_IMAGE_MODEL`)
- Fast and cheap
- Batch generation: 1-10 images per request (text-to-image only)
- Aspect ratios: 1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2, 19.5:9, 9:19.5. The `wide` alias maps to 16:9 because xAI rejects 21:9.
- Generation API: `POST /v1/images/generations` (JSON body, base64 or URL response)
- Editing API: `POST /v1/images/edits` -- separate endpoint from generation. The generations endpoint ignores images even if you pass one. Editing forces `n=1`.

#### xAI editing payload

```json
{
  "model": "grok-imagine-image",
  "prompt": "Change the golden retriever to a black labrador",
  "image": {
    "url": "data:image/jpeg;base64,{base64_data}"
  },
  "n": 1,
  "response_format": "b64_json"
}
```

The `image.url` field accepts a public URL or a base64 data URI. The xAI Python SDK uses gRPC internally (not REST), so the SDK's `image_url` parameter maps differently than the REST API's `image` object. For direct REST calls, use the structure above.

Ref: https://docs.x.ai/developers/model-capabilities/images/generation

## Provider selection

Determined by `config_loader.py` with this priority:

1. `JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER` in a child tool environment (exported from the Web UI's request-local config scope)
2. `IMAGE_TOOL_PROVIDER` in `config/cloud.env` or `config/local.env`
3. Fallback: `gemini`

The Web UI keeps the provider in a request-local config scope and exports the
`JARVIS_OVERRIDE_` form only to child tools. This preserves a single request's
choice without mutating the long-lived Web process environment.

## Model selection and pricing metadata

Image and video model defaults live in `lib/model_catalog.py`, alongside their
capabilities, known retired-model replacements, and provider-specific pricing.
The provider model env variables are optional pins: leave them unset to follow
the catalog default, or set one when an installation intentionally needs a
different or newly released model. Unknown explicit model IDs are preserved so
new provider releases remain usable before the catalog is updated.

The attachment UI does not expose a model selector. Its current generic cost
estimate is unchanged; the catalog pricing is available for a later UI cost
estimator without duplicating model data in the client.

## Image-to-image editing

### How it works

The `reference_image` parameter on the tool accepts any of:
- `stash://` ref (resolved to local path, then read + base64 encoded)
- Local file path (read + base64 encoded)
- `http`/`https` URL (downloaded + base64 encoded)
- `data:` URI (base64 extracted directly)

The helper function `_resolve_image_to_base64(image_source)` handles all of these and returns `(base64_data, mime_type)`.

When `reference_image` is present, each provider switches from its generation endpoint/mode to its editing mode:
- **Gemini**: adds the image as an `inline_data` part in the contents array (same endpoint)
- **OpenAI**: switches from `/v1/images/generations` to `/v1/images/edits` and changes from JSON to multipart/form-data
- **xAI**: switches from `/v1/images/generations` to `/v1/images/edits` and nests the image as `{"image": {"url": "data:..."}}`

The output data includes `"is_edit": true` when editing, and stash entries are tagged `image_edited` instead of `ai_generated`.

### Prompt tips for editing

Editing models work best with short, direct prompts. "Change the rabbit head to a goat head" produces better results than a multi-sentence description of textures, lighting, and composition. The web UI's `chat.py` instructs the LLM to keep editing prompts brief.

## Web UI flow

1. User uploads/drops an image in the chat input
2. Image action modal appears with three choices:
   - **Analyze image** -- runs vision analysis (default, existing behavior)
   - **Image to video** -- routes to `generate_video` with provider params forced via tool_overrides
   - **Image to image** -- routes to `generate_image` with provider/reference_image forced via tool_overrides
3. For "Image to image", the modal shows provider-specific options (Gemini grounding, OpenAI transparency, xAI batch count)
4. Backend stashes the uploaded image, builds `tool_overrides` including `reference_image: stash_ref`, and sends to orchestrator
5. Orchestrator applies overrides after the LLM generates creative arguments but before tool execution
6. User types their edit instructions in the chat (the LLM sees the image context and knows to call `generate_image`)

## tool_overrides mechanism

The orchestrator accepts a `tool_overrides` dict keyed by tool name. After the LLM decides which tool to call and generates arguments, but before execution, the orchestrator merges the overrides into the arguments:

```python
if tool_name in tool_overrides:
    arguments.update(tool_overrides[tool_name])
```

This lets the web UI force parameters like `provider`, `aspect_ratio`, `reference_image` without the LLM needing to know about them. The LLM focuses on the creative prompt; the UI handles the technical settings.

## Testing

```bash
# Direct tool test via FastAPI
curl -X POST http://localhost:8880/api/images/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Change the bunny head to a goat head",
    "provider": "xai",
    "reference_image": "stash://space_xxx/file_xxx"
  }'

# Web UI
# Upload image -> select "Image to Image" -> pick provider -> type edit instructions -> send

# CLI
./orchestrator/orchestrator_v2.py cloud "edit the image at stash://xxx to change the dog to a cat"
```

## Orchestrator integration

The `generate_image` tool has config in several places beyond this skill. Search for `@TOOL_CONFIG` to find all locations:

- **Single-call cap**: `orchestrator_v2.py` limits `generate_image` to 1 call per request (prevents LLM retry loops)
- **Follow-up extraction**: `chat.py` extracts `provider`, `model`, `size`, `style` from results for conversation context
- **Execution timeout**: `executor.py` sets 5-minute timeout for image generation
- **Response formatting**: `orchestrator_v2.py` categorizes the tool for speech output formatting

## Edge cases

- **Large images**: base64 encoding roughly doubles file size. A 10MB image becomes ~13MB in base64. No explicit resize, but providers have their own input limits.
- **Missing/invalid stash ref**: if the ref can't be resolved, the tool falls back to text-to-image with a warning rather than failing.
- **Aspect ratio mismatch**: the reference image might be 9:16 but the user selects 1:1. Each provider handles this differently (crop, pad, or ignore). The tool passes the requested ratio and lets the provider decide.
- **xAI batch + editing**: xAI editing forces `n=1`. Batch editing is not supported by their API.
