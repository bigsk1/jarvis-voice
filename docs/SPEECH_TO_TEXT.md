# Speech-to-Text

Jarvis supports three speech-to-text (STT) providers. Provider selection is
independent of Jarvis mode: cloud and local mode may each use OpenAI,
Faster-Whisper, or a separate OpenAI-compatible endpoint.

## Provider overview

| Provider | `STT_PROVIDER` | Runs where | Credential | Default model |
|----------|----------------|------------|------------|---------------|
| OpenAI | `openai` | OpenAI API | `OPENAI_API_KEY` | `whisper-1` if `STT_MODEL` is unset |
| Faster-Whisper | `faster-whisper` | Jarvis host | none | `small.en` |
| OpenAI-compatible | `openai-compatible` | Configured server | `STT_API_KEY` when required | `parakeet-en` if `STT_MODEL` is unset |

The shipped defaults remain:

- Cloud mode: OpenAI with `gpt-4o-mini-transcribe`
- Local mode: Faster-Whisper with `small.en` on CPU using `int8`

These are defaults, not restrictions. For example, cloud mode can use
Faster-Whisper on the Jarvis CPU or a Parakeet server on a LAN GPU while the LLM
and TTS continue using their cloud providers.

The selected mode determines which file supplies the settings:

- Cloud: `config/cloud.env`
- Local: `config/local.env`

Web push-to-talk, wake-word transcription, and the native microphone scripts all
use the same mode-specific STT configuration. Existing-file transcription is a
separate first-class tool described below.

## OpenAI

```env
STT_PROVIDER="openai"
STT_MODEL="gpt-4o-mini-transcribe"
OPENAI_API_KEY="your-openai-key"
STT_TIMEOUT_SECONDS="30"
```

This sends recorded audio to OpenAI and may incur API charges. Jarvis always
uses OpenAI's official transcription endpoint for this provider;
`STT_BASE_URL` and `STT_API_KEY` are not used.

## Faster-Whisper on the Jarvis host

```env
STT_PROVIDER="faster-whisper"
STT_MODEL="small.en"
STT_DEVICE="cpu"
STT_COMPUTE_TYPE="int8"
```

Faster-Whisper runs on the Jarvis host with no API key, network request, or STT
charge. These settings can be placed in either mode's ENV file. Using them in
`cloud.env` changes only STT; it does not change the configured LLM, TTS,
database, or other cloud-mode behavior.

## OpenAI-compatible endpoint

```env
STT_PROVIDER="openai-compatible"
STT_BASE_URL="http://192.168.1.50:5092/v1"
STT_API_KEY="your-stt-server-key"
STT_MODEL="parakeet-en"
STT_TIMEOUT_SECONDS="30"
```

`STT_API_KEY` is deliberately separate from `OPENAI_API_KEY`. Jarvis never
sends the OpenAI credential to a compatible endpoint.

`STT_BASE_URL` accepts any of these forms:

```text
http://192.168.1.50:5092
http://192.168.1.50:5092/v1
http://192.168.1.50:5092/v1/audio/transcriptions
```

Use an address reachable from the Jarvis host. `127.0.0.1` works only when the
STT server runs on that same host or shares its network namespace. A LAN IP,
reserved DHCP address, DNS hostname, or Tailscale IP can be used for a remote
server.

### Self-hosted Parakeet

[bigsk1/parakeet](https://github.com/bigsk1/parakeet) packages NVIDIA Parakeet
behind an authenticated OpenAI-compatible API. It supports Docker deployment on
GPU or CPU, exposes `parakeet-en`, and accepts WAV, WebM/Opus, MP3, M4A, FLAC,
and OGG input.

Follow that repository's installation guide on the STT host. After it creates
its private `.env`, configure Jarvis with one value from the server's
`PARAKEET_API_KEYS` list:

```env
STT_PROVIDER="openai-compatible"
STT_BASE_URL="http://STT_HOST_IP:5092/v1"
STT_API_KEY="one-parakeet-api-key"
STT_MODEL="parakeet-en"
```

Keep the Parakeet `.env` and Jarvis mode ENV files out of Git. The public sample
ENV files contain placeholders only.

The current Parakeet gateway defaults `PARAKEET_MAX_UPLOAD_MB` to 64 MB, but its
underlying `parakeet.cpp` engine can require substantially more device memory as
audio duration grows. The upstream project has an
[open long-audio memory report](https://github.com/mudler/parakeet.cpp/issues/55)
where a 10-minute clip exhausts device memory while a 5-minute clip succeeds.
Jarvis therefore ships 300-second file-tool chunks even though its conservative
compatible upload cap remains 25 MB. Operators with a proven engine/GPU
combination may raise the chunk duration; upload size alone is not evidence that
a longer chunk is safe.

## Existing audio files: `transcribe_audio`

The `transcribe_audio` tool accepts an existing Stash artifact or a
policy-approved local file. Web audio attachments are uploaded to Stash first;
Internet audio should use `stash` with `kind=url` before transcription. The full
transcript is saved as a new Stash text artifact, while only a bounded excerpt
is placed in the immediate model context. That transcript reference can then be
used with Canvas, `remember`, `manage_intel`, or summarization tools.

This is a Python library/tool path, not a daemon. The native CLI and wake-word
chain continue to call `bin/stt.py` and do not depend on Jarvis Web being up.

By default the tool inherits the active mode's `STT_PROVIDER` and `STT_MODEL`:

```env
AUDIO_TRANSCRIBE_PROVIDER=""
AUDIO_TRANSCRIBE_MODEL=""
```

Set a dedicated provider/model when short microphone requests and long file
transcriptions need different hardware or quality:

```env
AUDIO_TRANSCRIBE_PROVIDER="openai-compatible"
AUDIO_TRANSCRIBE_MODEL="parakeet-en"
# Optional dedicated endpoint/key pair. When the URL is blank, both values
# inherit from STT_BASE_URL/STT_API_KEY. A dedicated URL never inherits STT_API_KEY.
AUDIO_TRANSCRIBE_BASE_URL="http://STT_HOST_IP:5092/v1"
AUDIO_TRANSCRIBE_API_KEY="your-stt-server-key"
```

`openai-compatible` remains the standard multipart
`/v1/audio/transcriptions` contract. It never receives `OPENAI_API_KEY`.
`openai` always uses OpenAI's official endpoint and existing
`OPENAI_API_KEY`. Provider/model are administrator policy and are not LLM tool
arguments; Web/runtime overrides such as
`JARVIS_OVERRIDE_AUDIO_TRANSCRIBE_PROVIDER` retain normal precedence.

Long-file controls are intentionally separate from interactive STT:

```env
AUDIO_TRANSCRIBE_FALLBACK_PROVIDER=""
# AUDIO_TRANSCRIBE_FALLBACK_MODEL="small.en"
AUDIO_TRANSCRIBE_TIMEOUT_SECONDS="900"
AUDIO_TRANSCRIBE_REQUEST_TIMEOUT_SECONDS="300"
AUDIO_TRANSCRIBE_PROVIDER_MAX_MB="25"
AUDIO_TRANSCRIBE_MAX_FILE_MB="250"
AUDIO_TRANSCRIBE_MAX_DURATION_SECONDS="7200"
AUDIO_TRANSCRIBE_CHUNK_SECONDS="300"
# Optional Faster-Whisper overrides; blank values inherit STT_DEVICE/type.
# AUDIO_TRANSCRIBE_DEVICE="cpu"
# AUDIO_TRANSCRIBE_COMPUTE_TYPE="int8"
```

Jarvis inspects size, duration, and the presence of an audio stream before any
provider request. Every remote input is normalized into mono 16 kHz PCM WAV so
the accepted upload formats do not depend on the selected service. Recordings
above the configured chunk duration are split near detected silence
when possible, sent sequentially, and stitched without LLM rewriting. This
remote normalization requires `ffmpeg`; Faster-Whisper continues to decode the
original file directly. OpenAI's
current documented per-file limit is 25 MB, which is why that is the shipped
compatible default; raise or lower it only to match the selected endpoint.
Files above the Jarvis hard size/duration limits fail before billable work.
`AUDIO_TRANSCRIBE_TIMEOUT_SECONDS` is a monotonic deadline for inspection,
conversion, every provider request, and local inference. Each request timeout is
clamped to the remaining overall budget; the executor retains a 30-second
cleanup window so a partial remote transcript can be saved if a later chunk
fails or reaches the deadline.

The Web upload route runs in the selected cloud/local config scope and uses the
same bounded file-size and duration reader as the tool. A recording accepted by
Web therefore cannot be rejected later because Web and the tool resolved
different mode limits.

File-tool fallback does **not** inherit `STT_FALLBACK_PROVIDER`. Configure
`AUDIO_TRANSCRIBE_FALLBACK_PROVIDER` explicitly if desired. This avoids a
short-form microphone policy silently moving a long recording to a billed or
external provider. A tool profile may disable `transcribe_audio` entirely on a
host that should not process long recordings.

Complete transcripts are durable source artifacts in Stash. `save_to_stash`
must be a JSON boolean. When false, a transcript that exceeds the inline limit
is still forced into Stash so paid output is not discarded. If Stash saving
fails after provider work, the complete transcript is returned inline and the
result reports `transcript_save_error`. The result emits `transcript` or
`transcript_excerpt`, never both.

## Failure and fallback behavior

STT hard-fails by default:

```env
STT_FALLBACK_PROVIDER=""
```

This is intentional. A disconnected local server must not silently send audio
to a billed cloud service.

To opt into fallback, configure a different provider and, optionally, its model:

```env
STT_FALLBACK_PROVIDER="faster-whisper"
STT_FALLBACK_MODEL="small.en"
```

Faster-Whisper is the safest fallback for either mode because it adds no network
egress or API billing. An explicit `openai` fallback is supported, but it sends
audio to OpenAI, requires `OPENAI_API_KEY`, and may incur charges.

Fallback is attempted for transient availability failures:

- Connection failure or timeout
- HTTP 408, 425, or 429
- Upstream HTTP 5xx response
- A Web Faster-Whisper subprocess timeout

Fallback is not attempted for:

- Missing or invalid credentials
- Unknown models or endpoints
- Invalid provider configuration
- Malformed successful responses
- Empty audio, silence, or noise that produces no transcript

The fallback provider must differ from `STT_PROVIDER`. Jarvis logs when a
fallback occurs but does not log API keys or transcript text.

## Browser microphone requirement

Jarvis Web push-to-talk depends on the browser microphone API. Browsers normally
allow microphone capture only from a secure context: HTTPS or `localhost`.
Opening Jarvis Web from another machine over plain HTTP may therefore hide or
block microphone access even when the STT provider itself is healthy.

Wake-word and native microphone flows do not use the browser microphone API and
are unaffected by that browser restriction.

## Testing

Check a compatible server before testing Jarvis:

```bash
curl -fsS http://STT_HOST_IP:5092/health
curl -fsS http://STT_HOST_IP:5092/readyz
curl -fsS http://STT_HOST_IP:5092/v1/models \
  -H "Authorization: Bearer $STT_API_KEY"
```

Test the same mode-aware command used by native Jarvis microphone flows:

```bash
./bin/stt.py --mode cloud /path/to/recording.wav
./bin/stt.py --mode local /path/to/recording.wav
```

Test the first-class existing-file tool without starting Jarvis Web:

```bash
.venv/bin/python skills/transcribe_audio.py \
  '{"source":"/path/to/recording.m4a"}'
```

For the Parakeet server itself, use the contract and SDK tests included in the
[Parakeet repository](https://github.com/bigsk1/parakeet). Those tests validate
the remote service independently of Jarvis.

## Troubleshooting

| Symptom | Likely cause | Check |
|---------|--------------|-------|
| HTTP 401 | Wrong or missing compatible-server key | `STT_API_KEY`; do not use `OPENAI_API_KEY` |
| Connection refused | Wrong address, port, bind address, or stopped server | `/health`, Docker status, firewall |
| Unknown model | Jarvis model does not match the server's advertised model | Authenticated `/v1/models` |
| No speech detected | Silence/noise or microphone recording problem | Test the captured audio; this does not trigger fallback |
| Browser mic unavailable | Page is not HTTPS or localhost | Use HTTPS, localhost, wake word, or native mic flow |
| Faster-Whisper model fails | Missing model/dependency or incompatible device settings | `STT_MODEL`, `STT_DEVICE`, `STT_COMPUTE_TYPE` |
| Unexpected cloud usage | An OpenAI provider or fallback was explicitly enabled | `STT_PROVIDER`, `STT_FALLBACK_PROVIDER` |
