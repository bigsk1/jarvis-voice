# Qwen3-TTS Available Voices

Server: `http://localhost:8881`

## Custom Cloned Voices (28)

### Male Voices
| Voice | Description |
|-------|-------------|
| **Jarvis** | Calm, soothing AI assistant |
| **Paddington** | British narrator, deep and warm |
| **Professor** | British, trustworthy, educational |
| **Josh** | Deep American voice |
| **John** | Deep male narration |
| **Mark** | Natural conversations |
| **Adam** | Late night radio, smooth |
| **Russell** | Dramatic British TV |
| **Curt** | Cosmic storyteller, joker |
| **Eustis** | Fast speaking, energetic |
| **General Joe** | WWII Narrator style |
| **Grandpa** | Elderly male, warm |
| **Nigel** | Mysterious, intriguing |
| **Richard** | Clear, professional male |
| **Valentino** | Smooth, romance style |
| **Wildebeest** | Deep, powerful narration |

### Female Voices
| Voice | Description |
|-------|-------------|
| **Lucy** | Sweet and sensual |
| **Carmen** | Realistic, casual, lovely |
| **Caroline** | Excellent for narration |
| **Joanne** | Pensive, introspective, soft |
| **Victoria** | Classy British mature woman |
| **Natasha** | Valley girl, casual |
| **Bianca** | City girl, urban |
| **Cecile** | Old woman, authoritative |
| **Emmaline** | Young British girl |
| **Monika** | Indian female accent |
| **Samantha** | Young American girl |
| **Tally** | Expressive, phenomenal range |
| **Villain** | Sexy female villain |

## OpenAI-Compatible Voices (6)

For drop-in replacement compatibility:

| Voice | Maps To |
|-------|---------|
| alloy | Vivian |
| echo | Ryan |
| fable | Sophia |
| nova | Isabella |
| onyx | Evan |
| shimmer | Lily |

## Quick Usage

```bash
# Test a voice
curl -X POST http://localhost:8881/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"tts-1","voice":"Jarvis","input":"Hello!"}' \
  -o test.mp3

# List all voices
curl http://localhost:8881/v1/voices
```

## Performance

- First request per voice: ~8-18s (builds voice profile)
- Cached voice requests: ~2-6s
- VRAM usage: ~3.9 GB
- Sample rate: 24kHz
