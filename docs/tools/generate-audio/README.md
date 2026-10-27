# Spoken audio generation

`generate_audio` creates a downloadable voiceover from an exact script. It is
separate from Jarvis reading a reply aloud, `generate_music` composing music, and
`transcribe_audio` turning an existing recording into text.

## Enable in one mode

Add this to the selected `config/cloud.env` or `config/local.env`:

```dotenv
AUDIO_TOOL_PROVIDER=elevenlabs
# Optional tool-specific defaults:
# AUDIO_TOOL_VOICE=your-voice-id
# AUDIO_TOOL_MODEL=eleven_v3
# AUDIO_TOOL_TIMEOUT_SECONDS=180
```

The provider must be explicitly configured; leaving it unset keeps both tools
unavailable even when speech credentials are present. Supported providers are
`elevenlabs`, `openai`, `xai`, `qwen3-tts`, and `kokoro`. The corresponding API key
or self-hosted endpoint must also be configured in that mode. The tool reuses
the provider's existing speech settings and does not add a separate credential.

Restart affected services after changing configuration and sync Tool RAG for
each configured mode that should discover the new tool. Use the production
Python environment for sync, as described in [tool management](../../TOOL_MANAGEMENT.md).
The `openai_only` starter and generation-restricted example profiles disable
this optional tool; enable it explicitly in your chosen profile when wanted.
Existing private profile copies are not rewritten.
For compatibility, older profiles that explicitly disable `generate_music`
also disable `generate_audio` when it has no override. `audio_voices` inherits
that speech restriction, including an explicit `generate_audio: false`.
An explicit per-tool override always wins, so a profile can enable voice lookup
while keeping speech generation disabled.

There is no Web setting for this tool's provider, model, or voice. The Web TTS
provider selector continues to control reply speech only. Mode-file defaults
are not a live voice selector: restart services to reload their configuration.
An individual tool call can explicitly choose another provider, voice, or model
without editing the defaults or changing Jarvis's speaking voice.

## Provider and voice selection

| Choice | Resolution |
| --- | --- |
| Provider | Explicit call argument, otherwise `AUDIO_TOOL_PROVIDER` |
| Voice | Explicit call argument, otherwise `AUDIO_TOOL_VOICE` for the configured default provider, otherwise that provider's existing TTS voice setting |
| Model | Explicit call argument, otherwise `AUDIO_TOOL_MODEL` for the configured default provider, otherwise that provider's existing TTS model setting/default |

Tool voice/model overrides belong only to the configured default provider. A
call switching from ElevenLabs to OpenAI uses OpenAI settings unless it supplies
OpenAI choices explicitly. It never carries the configured ElevenLabs voice ID
into an OpenAI request.

Pass a provider-native voice ID/name. Use `audio_voices` when you know a name or
want to compare available voices. The private `config/elevenlabs_voices.json`
remains an operator reference; neither tool reads or mutates it. You can copy a
returned voice ID into `AUDIO_TOOL_VOICE`, retain the provider's existing TTS
voice, or supply `voice` on an individual request.

## Find and preview voices

`audio_voices` searches the selected provider's catalog without generating audio
or changing any settings. It shares the same `AUDIO_TOOL_PROVIDER` opt-in and
credential requirements as `generate_audio`. An explicit provider argument can
inspect another configured provider without changing the default.

```json
{"provider": "elevenlabs", "search": "British", "limit": 10}
```

Returned `items` carry the provider, exact `voice_id`, name, descriptive labels,
and a `preview_url` when available. Keep the provider with the ID when selecting
a voice; IDs are not interchangeable. Use the returned `next_cursor` for another
page of the same lookup. The page size defaults to 20 and is limited to 50.
Follow-up context retains a compact shortlist so requests such as "use the
second voice" can refer to the actual results.

Catalog source is explicit: OpenAI uses a documented built-in list, ElevenLabs
and xAI query account catalogs, and Qwen3-TTS/Kokoro query their configured
servers. A server without a supported catalog returns a clear lookup failure;
it does not manufacture a list from the configured voice. xAI may return a
partial catalog when custom voices are unavailable. Read its warning before
assuming that every account voice was searched. Provider permissions can allow
generation while denying voice listing.

For an existing public `preview_url`, ask Jarvis to save the sample with `stash`
so Web chat can display its audio player. Providers do not all expose previews;
use a short `generate_audio` request with the returned provider and voice ID to
hear a custom sample. That generation is a separate request and may spend
credits. Neither lookup nor generation changes the default voice. If you want
Jarvis to remember a preferred provider/voice for future requests, ask it to save
that preference with its existing memory tools; remembering a preference does
not edit ENV or change the runtime reply voice.

## Requests and duration

### Delivery instructions and speech tags

Voice lookup returns `delivery_capabilities` for the selected provider/model.
Use those capabilities before adding expressive delivery to a recording:

| Provider/model | Supported delivery control |
| --- | --- |
| OpenAI `gpt-4o-mini-tts` | Separate `instructions`, such as "Speak warmly with a measured pace"; no ElevenLabs bracket tags |
| ElevenLabs v3/v4 models | Supported bracket cues inside the script, such as `[whispers]` or `[laughs]`; no separate instruction field |
| xAI | Supported bracket cues and wrapping speech tags, such as `[laugh]` or `<whisper>text</whisper>` |
| Qwen3-TTS | No separate instructions exposed: the fixed `tts-1` alias does not establish that the backend supports delivery instructions |
| Kokoro and other listed models | No additional delivery field or speech-tag interpretation promised |

`instructions` controls how supported models deliver the script; it is not text
to speak. Unsupported instructions and recognized speech cues from incompatible
providers are rejected before generation.
Supported cues remain part of the supplied script. Avoid copying one provider's
markup into another provider's recording. No speech cues are added automatically,
and saving a recording does not alter Jarvis's runtime delivery settings.

```json
{
  "text": "Welcome to Jarvis Voice. This recording is a reusable voiceover.",
  "provider": "elevenlabs",
  "voice": "your-voice-id"
}
```

The supplied text is the script. It is not summarized, shortened to a time
budget, rewritten, or transcribed with a second model call. Natural requests
such as "about 30 seconds" can guide writing a script before generation; the
tool does not promise an exact duration or silently cut longer scripts. Provider
character limits are checked before requesting generation; oversized scripts
must be shortened or split explicitly. Longer recordings are valid when they
fit those limits and the request deadline.

`AUDIO_TOOL_TIMEOUT_SECONDS` controls the provider request deadline (default
180 seconds, bounded to 1–900). The foreground executor allows another 30 seconds
for artifact storage and process cleanup. This is a time limit on waiting, not
a limit on the resulting recording's duration. The tool performs no automatic
paid retries, provider fallbacks, caching, or background submission.

## Output and storage

A successful generation saves:

- The audio under `data/generated_audio/`, separate from runtime TTS and music.
- An audio copy and the exact original script in Stash.
- Provider, model, voice, format, file references, and measured duration in the
  returned metadata when available.

Use the audio `stash_ref` for downstream tools and `script_ref` for the original
text. The script is text you supplied, not a provider-produced transcript or
word-aligned subtitles. Web chat uses its existing generic Stash audio
player/download handling; playback is manual. A guarded Web media route,
`/api/generated-audio/<filename>`, serves saved MP3/WAV recordings under the
existing Web authentication. It provides playback independently of Stash expiry
and lets a failed Stash save still offer the existing local recording. There is
no audio catalog or Canvas gallery entry.

If reply TTS is enabled, Jarvis can still speak its confirmation through the
normal reply provider. Generating a saved voiceover and speaking that reply
are separate requests. Using the same local speech server can queue work and
increase latency.

### Retention

Stash spaces use the `generated_audio` label and existing `generated_media`
retention policy, controlled by `STASH_GENERATED_MEDIA_TTL_DAYS` (default 30).
Normal Stash retention applies to the copy; it does not delete the separate
`data/generated_audio/` file. `bin/cleanup-audio` removes generated speech files
and their script/metadata sidecars after 60 days by default, independently of its 30-day runtime-audio
policy. Override only speech retention with `--generated-days N`; `--dry-run`
previews both policies. `cleanup-all` includes this policy, so existing cron
invocations pick it up. Eligible files are removed on the next scheduled run;
a weekly schedule means roughly 60–67 days. Music remains excluded. Copy
recordings elsewhere before expiry if you want to keep them.

### Partial saves and timeouts

A recording that was generated but could not be fully enrolled in Stash remains
a failed save with `completion: "completed"`; its local audio URL and file path
are retained for playback and later recovery. The script and a recovery receipt
are saved locally when possible. Jarvis reports that generation already happened
and does not automatically regenerate it. A subprocess timeout has an unknown
outcome, which may already have been billed; inspect existing recordings before
explicitly requesting another generation.

## Use with HeyGen

Generate speech first, then pass its audio reference and your image to
`generate_avatar_video`:

```json
{
  "image_source": "stash://images/portrait",
  "audio_source": "stash://audio/voiceover"
}
```

Do not pass an ElevenLabs voice ID to HeyGen's `voice_id`; that field belongs
to HeyGen's own script-to-speech path. Existing-audio avatar input needs the
audio reference instead. The current avatar integration measures input audio
and rejects recordings longer than 30 seconds. That downstream restriction
does not limit standalone `generate_audio` recordings.

## Verification

```bash
.venv/bin/python -m pytest tests/test_generate_audio_integration.py tests/test_audio_voices_integration.py -q
```

Deterministic checks mock providers and do not spend credits. Native and Docker
use the same HTTP adapters; configured local speech endpoints must be reachable
from the running process/container. No new Python package, service, or database
is required.
