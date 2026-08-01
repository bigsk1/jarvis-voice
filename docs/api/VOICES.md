# Voice API

The Voice API enables text-to-speech playback through Jarvis's local speakers. Supports multiple TTS providers with per-request overrides for multi-agent voice identity.

## TTS Normalization

Before playback, Jarvis runs outgoing speech through the shared normalizer in `lib/tts_normalizer.py`.

This keeps voice output safer and more natural by:
- removing URLs, markdown links, bare domains, and `stash://` references
- stripping visual-only source blocks that are useful in chat but noisy in speech
- converting symbols like `34°F` to `34 degrees`, `10°C` to `10 degrees Celsius`, and `25%` to `25 percent`
- applying context-specific cleanup where needed, such as weather-watch ISO date stripping

Named profiles currently include `weather_watch`, `camera_alert`, `price_quote`, and `timestamped`.

The Voice API, Web UI TTS, orchestrator `--speak`, alerts, reminders, and daemon speech all use this shared normalization layer.

## Endpoints

### POST /api/voice/speak

Speak a message through local speakers with optional TTS provider/voice override.

**Request:**
```json
{
  "message": "Hello! This is a test message.",
  "mode": "cloud",
  "tts_provider": "elevenlabs",
  "voice": "pgCnBQgKPGkIP8fJuita",
  "profile": "weather_watch"
}
```

**Parameters:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `message` | string | Yes | - | Text to speak |
| `mode` | string | No | `cloud` | `cloud` or `local` (selects say.sh or say-local.sh) |
| `tts_provider` | string | No | From env | Override TTS provider: `elevenlabs`, `xai`, `qwen3-tts`, `openai`, `kokoro` |
| `voice` | string | No | From env | Override voice (provider-specific) |
| `profile` | string | No | none | Optional TTS normalization profile: `weather_watch`, `camera_alert`, `price_quote`, `timestamped` |

**Response:**
```json
{
  "ok": true,
  "message": "Spoken successfully",
  "text": "Hello! This is a test message.",
  "provider": "elevenlabs",
  "voice": "pgCnBQgKPGkIP8fJuita",
  "profile": "weather_watch"
}
```

### POST /api/voice/announce

Simple announce endpoint (auto-detects mode). Easier for external integrations.

**Request:**
```json
{
  "message": "Package delivered at front door"
}
```

**Response:** Same as `/speak`

---

## TTS Providers

| Provider | Env Var | Voice Env Var | Notes |
|----------|---------|---------------|-------|
| `elevenlabs` | `ELEVENLABS_API_KEY` | `ELEVENLABS_TTS_VOICE` | Best quality, paid |
| `xai` | `XAI_API_KEY` | `XAI_TTS_VOICE` | Native xAI TTS; 26 built-in voices plus custom voice IDs |
| `qwen3-tts` | `QWEN3_TTS_URL` | `QWEN3_TTS_VOICE` | Local network, 28 cloned voices, free |
| `openai` | `OPENAI_API_KEY` | `VOICE` | alloy, echo, fable, onyx, nova, shimmer |
| `kokoro` | `KOKORO_TTS_URL` | `KOKORO_TTS_VOICE` | Local, lightweight, free |

---

## Multi-Agent Voice Identity

The Voice API supports per-request TTS overrides, enabling different AI agents to speak with distinct voices through Jarvis's speakers.

### Example: Samantha's Voice

Samantha (secondary AI on VPS2) can speak through Jarvis's speakers with her own cloned voice:

```bash
curl -X POST http://localhost:8880/api/voice/speak \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello! This is Samantha speaking.",
    "mode": "cloud",
    "tts_provider": "qwen3-tts",
    "voice": "Samantha"
  }'
```

### Voice Identity Setup

| Agent | Provider | Voice | Description |
|-------|----------|-------|-------------|
| **Jarvis** | `elevenlabs` | `pgCnBQgKPGkIP8fJuita` | Default male voice (from cloud.env) |
| **Samantha** | `qwen3-tts` | `Samantha` | Cloned female voice on local TTS server |

This allows multi-agent conversations where each assistant has their own distinct voice!

---

## Qwen3-TTS Voices

The local Qwen3-TTS server supports 28 cloned voices:

**Male:** Jarvis, James, Jay, Morgan, Ethan, Marcus, Oliver, Liam, Noah, Benjamin, Theodore

**Female:** Samantha, Nicole, Sarah, Emma, Olivia, Ava, Isabella, Sophia, Mia, Charlotte, Amelia

**OpenAI-Compatible:** alloy, echo, fable, onyx, nova, shimmer (mapped to clones)

See: [docs/qwen3-tts/voices.md](../qwen3-tts/voices.md)

---

## Usage Examples

### Basic Speak (Uses Default Provider)
```bash
curl -X POST http://localhost:8880/api/voice/speak \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello world"}'
```

### Override Provider and Voice
```bash
curl -X POST http://localhost:8880/api/voice/speak \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Testing a different voice",
    "tts_provider": "qwen3-tts",
    "voice": "Morgan"
  }'
```

### Use a TTS Normalization Profile
```bash
curl -X POST http://localhost:8880/api/voice/speak \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Forecast low 34°F tonight. Fri 2026-04-04 high 61°F.",
    "profile": "weather_watch"
  }'
```

This lets external callers opt into the same context-aware speech cleanup used internally by alerts and workflows.

### Simple Announce (Auto Mode)
```bash
curl -X POST http://localhost:8880/api/voice/announce \
  -H "Content-Type: application/json" \
  -d '{"message": "Dinner is ready!"}'
```

### From External System (e.g., Home Assistant)
```yaml
# Home Assistant automation
action:
  - service: rest_command.jarvis_speak
    data:
      message: "Motion detected at front door"
```

---

## Implementation Details

The override mechanism uses special environment variables that take precedence AFTER config loads:

- `TTS_PROVIDER_OVERRIDE` → overrides `TTS_PROVIDER` from env
- `QWEN3_TTS_VOICE_OVERRIDE` → overrides `QWEN3_TTS_VOICE`
- `ELEVENLABS_TTS_VOICE_OVERRIDE` → overrides `ELEVENLABS_TTS_VOICE`
- `XAI_TTS_VOICE_OVERRIDE` → overrides `XAI_TTS_VOICE`
- `OPENAI_VOICE_OVERRIDE` → overrides `VOICE`
- `KOKORO_TTS_VOICE_OVERRIDE` → overrides `KOKORO_TTS_VOICE`

This ensures API call parameters always win over config file settings.

`profile` is validated against an allowlist in `api/routes/voice.py`. When you add a new profile to `lib/tts_normalizer.py`, also add it to that allowlist so external callers can use it.

---

## Related Documentation

- [TTS Providers Overview](../qwen3-tts/QWEN3_TTS_INTEGRATION_GUIDE.md)
- [Qwen3-TTS Voices](../qwen3-tts/voices.md)
- [API Overview](API_OVERVIEW.md)
