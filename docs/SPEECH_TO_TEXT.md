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
use the same mode-specific STT configuration.

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
