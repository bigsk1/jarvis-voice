# Qwen3-TTS Integration Guide

**Server**: `http://192.168.70.226:8881`  
**API**: OpenAI-compatible `/v1/audio/speech`  
**GPU**: NVIDIA RTX 5060 Ti (16GB VRAM)  
**Model**: Qwen3-TTS-12Hz-1.7B-Base (Voice Cloning)

> **Use Case**: Drop-in replacement for OpenAI TTS or Kokoro TTS. Same API, local GPU inference, 28 custom cloned voices.

---

## Quick Start

### Replace OpenAI TTS (One Line Change)

```python
from openai import OpenAI

# BEFORE: OpenAI Cloud TTS
# client = OpenAI(api_key="sk-...")

# AFTER: Local Qwen3-TTS
client = OpenAI(
    base_url="http://192.168.70.226:8881/v1",
    api_key="not-needed"
)

# Same code works for both!
response = client.audio.speech.create(
    model="tts-1",
    voice="Jarvis",      # Your custom cloned voice
    input="Hello! This is your local TTS server speaking.",
    response_format="mp3"
)

response.stream_to_file("output.mp3")
```

---

## Switching Between OpenAI and Qwen3-TTS

### Option 1: Environment Variable Toggle

```python
import os
from openai import OpenAI

# Set in environment or .env file:
# TTS_PROVIDER=qwen3  (local) or TTS_PROVIDER=openai (cloud)

TTS_PROVIDER = os.getenv("TTS_PROVIDER", "qwen3")

if TTS_PROVIDER == "qwen3":
    client = OpenAI(
        base_url="http://192.168.70.226:8881/v1",
        api_key="not-needed"
    )
    default_voice = "Jarvis"  # Custom cloned voice
else:
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY")
    )
    default_voice = "alloy"  # OpenAI voice

def text_to_speech(text: str, voice: str = None) -> bytes:
    """Generate speech - works with both OpenAI and Qwen3-TTS."""
    response = client.audio.speech.create(
        model="tts-1",
        voice=voice or default_voice,
        input=text,
        response_format="mp3"
    )
    return response.content
```

### Option 2: Provider Class

```python
import os
from openai import OpenAI
from typing import Optional

class TTSProvider:
    """Switchable TTS provider supporting OpenAI and Qwen3-TTS."""
    
    def __init__(self, provider: str = "qwen3"):
        self.provider = provider
        
        if provider == "qwen3":
            self.client = OpenAI(
                base_url="http://192.168.70.226:8881/v1",
                api_key="not-needed"
            )
            self.voices = [
                "Jarvis", "Paddington", "Professor", "Victoria",
                "Josh", "John", "Mark", "Adam", "Russell",
                "Lucy", "Carmen", "Caroline", "Joanne", "Natasha"
            ]
        else:
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    
    def speak(self, text: str, voice: Optional[str] = None, 
              output_file: Optional[str] = None) -> bytes:
        """Generate speech audio."""
        response = self.client.audio.speech.create(
            model="tts-1",
            voice=voice or self.voices[0],
            input=text,
            response_format="mp3"
        )
        
        if output_file:
            response.stream_to_file(output_file)
        
        return response.content
    
    def list_voices(self) -> list:
        """Return available voices for current provider."""
        return self.voices


# Usage
tts = TTSProvider("qwen3")  # or "openai"
tts.speak("Hello world!", voice="Jarvis", output_file="output.mp3")
```

---

## Custom Cloned Voices (28 Total)

These voices are cloned from reference audio samples. First request per voice takes ~8-18s to build the voice profile, subsequent requests are ~4-6s.

### Male Voices

| Voice | Description | Style |
|-------|-------------|-------|
| **Jarvis** | Calm and soothing | AI assistant, narration |
| **Paddington** | British narrator, deep and warm | Audiobooks, storytelling |
| **Professor** | British, trustworthy | Educational, documentary |
| **Josh** | Deep voice, American | Podcasts, voiceover |
| **John** | Deep male | General narration |
| **Mark** | Natural conversations | Casual, dialogue |
| **Adam** | Late night radio | Smooth, relaxed |
| **Russell** | Dramatic British TV | Drama, announcements |
| **Curt** | Cosmic storyteller, joker | Entertainment, fun |
| **Eustis** | Fast speaking | Energetic content |
| **General_Joe** | WWII Narrator | Historical, military |
| **Grandpa** | Elderly male | Warm, storytelling |
| **Nigel** | Mysterious, intriguing | Mystery, thriller |
| **Richard** | Clear male | Professional |
| **Valentino** | Smooth male | Romance, luxury |
| **Wildebeest** | Deep male voice | Powerful narration |

### Female Voices

| Voice | Description | Style |
|-------|-------------|-------|
| **Lucy** | Sweet and sensual | Soft narration |
| **Carmen** | Realistic, casual, lovely | Natural dialogue |
| **Caroline** | Excellent for narration | Audiobooks |
| **Joanne** | Pensive, introspective, soft | Thoughtful content |
| **Victoria** | Classy British mature woman | Elegant, sophisticated |
| **Natasha** | Valley girl | Casual, youthful |
| **Bianca** | City girl | Urban, modern |
| **Cecile** | Old woman, confident, authoritative | Wise, commanding |
| **Emmaline** | Young British girl | Youthful British |
| **Monika** | Indian female | Diverse accents |
| **Tally** | Expressive, phenomenal range | Dramatic, emotional |
| **Villain** | Sexy female villain | Dramatic, character |

---

## API Reference

### Generate Speech

```bash
POST /v1/audio/speech

{
  "model": "tts-1",           # or "tts-1-hd", "qwen3-tts"
  "voice": "Jarvis",          # any custom voice name
  "input": "Text to speak",
  "response_format": "mp3",   # mp3, opus, aac, flac, wav, pcm
  "speed": 1.0                # 0.25 to 4.0
}
```

### cURL Example

```bash
curl -X POST http://192.168.70.226:8881/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "tts-1",
    "voice": "Jarvis",
    "input": "Hello, this is Jarvis speaking.",
    "response_format": "mp3"
  }' \
  --output output.mp3
```

### List Voices

```bash
curl http://192.168.70.226:8881/v1/voices
```

### Health Check

```bash
curl http://192.168.70.226:8881/health
```

---

## Language Support

Force a specific language with model suffix:

| Model | Language |
|-------|----------|
| `tts-1-en` | English |
| `tts-1-zh` | Chinese |
| `tts-1-ja` | Japanese |
| `tts-1-ko` | Korean |
| `tts-1-de` | German |
| `tts-1-fr` | French |
| `tts-1-es` | Spanish |
| `tts-1-ru` | Russian |
| `tts-1-pt` | Portuguese |
| `tts-1-it` | Italian |

---

## Audio Formats

| Format | Use Case |
|--------|----------|
| `mp3` | Universal, good compression |
| `opus` | Best quality/size, streaming |
| `aac` | Apple devices |
| `flac` | Lossless quality |
| `wav` | Uncompressed, editing |
| `pcm` | Raw audio data |

---

## Performance

| Metric | Value |
|--------|-------|
| **First request (new voice)** | ~8-18s (builds voice profile) |
| **Cached voice requests** | ~4-6s |
| **VRAM usage** | ~3.9 GB |
| **Sample rate** | 24kHz |
| **Model** | Qwen3-TTS-12Hz-1.7B-Base |

---

## Framework Integration Examples

### FastAPI Backend

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from openai import OpenAI
import io

app = FastAPI()

tts_client = OpenAI(
    base_url="http://192.168.70.226:8881/v1",
    api_key="not-needed"
)

@app.post("/api/tts")
async def text_to_speech(text: str, voice: str = "Jarvis"):
    try:
        response = tts_client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            response_format="mp3"
        )
        return StreamingResponse(
            io.BytesIO(response.content),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "attachment; filename=speech.mp3"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Node.js / TypeScript

```typescript
import OpenAI from 'openai';
import fs from 'fs';

const ttsClient = new OpenAI({
  baseURL: 'http://192.168.70.226:8881/v1',
  apiKey: 'not-needed',
});

async function speak(text: string, voice: string = 'Jarvis'): Promise<Buffer> {
  const response = await ttsClient.audio.speech.create({
    model: 'tts-1',
    voice: voice,
    input: text,
  });
  
  return Buffer.from(await response.arrayBuffer());
}

// Usage
const audio = await speak('Hello from TypeScript!', 'Paddington');
fs.writeFileSync('output.mp3', audio);
```

### Gradio App

```python
import gradio as gr
from openai import OpenAI

client = OpenAI(
    base_url="http://192.168.70.226:8881/v1",
    api_key="not-needed"
)

VOICES = ["Jarvis", "Paddington", "Professor", "Victoria", "Josh", 
          "Lucy", "Carmen", "Caroline", "Natasha", "Russell"]

def generate_speech(text, voice):
    response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
        response_format="mp3"
    )
    
    output_path = "/tmp/gradio_tts.mp3"
    with open(output_path, "wb") as f:
        f.write(response.content)
    return output_path

demo = gr.Interface(
    fn=generate_speech,
    inputs=[
        gr.Textbox(label="Text to speak", lines=3),
        gr.Dropdown(VOICES, label="Voice", value="Jarvis")
    ],
    outputs=gr.Audio(label="Generated Speech"),
    title="Qwen3-TTS Voice Cloning"
)

demo.launch()
```

### Open WebUI Integration

Add as TTS provider in Open WebUI settings:
- **URL**: `http://192.168.70.226:8881/v1`
- **API Key**: `not-needed`
- **Model**: `tts-1`
- **Voice**: `Jarvis` (or any custom voice)

### Home Assistant

```yaml
tts:
  - platform: openai_tts
    api_key: "not-needed"
    base_url: "http://192.168.70.226:8881/v1"
    model: "tts-1"
    voice: "Jarvis"
```

---

## Adding New Voices

To add your own voice samples:

1. **Prepare audio**: 3-10 seconds of clear speech (.wav preferred)
2. **Name the file**: `VoiceName.wav` (e.g., `MyVoice.wav`)
3. **Copy to server**:
   ```bash
   scp Samantha.wav boss@192.168.70.226:/home/boss/apps/Qwen3-TTS-Openai-Fastapi/sample-voices-xtts/
   ```
4. **Restart container**:
   ```bash
   docker compose restart qwen3-tts-gpu
   ```
5. **Use the voice**: `voice="MyVoice"`

Trim the audio to 8 seconds:
```bash
ffmpeg -i sample-voices-xtts/Samantha.wav -t 8 -y sample-voices-xtts/Samantha_trimmed.wav && mv sample-voices-xtts/Samantha_trimmed.wav sample-voices-xtts/Samantha.wav
```

---

## Server Management

```bash
# View logs
docker compose logs -f qwen3-tts-gpu

# Restart
docker compose restart qwen3-tts-gpu

# Stop
docker compose down

# Start
docker compose up -d qwen3-tts-gpu

# Check health
curl http://192.168.70.226:8881/health
```

---

## Troubleshooting

### Voice not found
Check exact spelling. Voice names are case-insensitive but must match file names.

### Slow first request for a voice
Normal - first request builds the voice profile (~8-18s). Subsequent requests are fast (~4-6s).

### Connection refused
Check if container is running: `docker compose ps`

### Out of memory
VRAM usage is ~3.9GB. RTX 5060 Ti (16GB) has plenty of headroom.

---

## Comparison: Qwen3-TTS vs OpenAI TTS

| Feature | Qwen3-TTS (Local) | OpenAI TTS (Cloud) |
|---------|-------------------|-------------------|
| **Cost** | Free (GPU power) | $15/1M chars |
| **Privacy** | 100% local | Data sent to cloud |
| **Latency** | ~4-6s | ~1-2s |
| **Voices** | 28 custom cloned | 6 preset |
| **Voice Cloning** | ✅ Yes | ❌ No |
| **Custom Voices** | ✅ Add your own | ❌ No |
| **API Compatible** | ✅ Same API | ✅ Native |
| **Offline** | ✅ Yes | ❌ No |

---

## Quick Voice Reference

```
Male Voices:
  Jarvis, Paddington, Professor, Josh, John, Mark, Adam, Russell,
  Curt, Eustis, General_Joe, Grandpa, Nigel, Richard, Valentino, Wildebeest

Female Voices:
  Lucy, Carmen, Caroline, Joanne, Victoria, Natasha, Bianca,
  Cecile, Emmaline, Monika, Tally, Villain
```

---

*Last updated: January 2026*  
*Server: 192.168.70.226:8881*  
*Model: Qwen3-TTS-12Hz-1.7B-Base*
