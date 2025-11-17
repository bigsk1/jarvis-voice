# API Mode Selection (Cloud vs Local)

## Starting the API Server

### Cloud Mode (Default)
Uses OpenAI/Anthropic TTS via `bin/say.sh`

```bash
./bin/jarvis-api
```

### Local Mode
Uses Kokoro TTS via `bin/say-local.sh`

```bash
./bin/jarvis-api --local
```

## How It Works

The `--local` flag:
1. Loads `config/local.env` instead of `config/cloud.env`
2. Sets `LLM_PROVIDER=ollama`
3. Routes TTS to `say-local.sh`
4. Uses `jarvis_memory_local.db`

## Mode Detection

The API auto-detects mode based on:
- **Command flag**: `--local` → local mode
- **Environment variable**: `LLM_PROVIDER=ollama` → local mode
- **Default**: cloud mode

## Testing

```bash
# Start cloud mode API
./bin/jarvis-api

# Test (uses OpenAI TTS)
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Test", "source": "test", "severity": "high"}'

# Should speak via OpenAI TTS
```

```bash
# Start local mode API
./bin/jarvis-api --local

# Test (uses Kokoro TTS)
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Test", "source": "test", "severity": "high"}'

# Should speak via Kokoro TTS (offline)
```

## Database Sync

Both modes use their respective databases:
- **Cloud**: `data/jarvis_memory.db`
- **Local**: `data/jarvis_memory_local.db`

Auto-sync runs on mode switch (via `lib/auto_sync_memory.py`).

## Security Note

CORS is set to `*` (all origins) for now since this runs on local network only.

For production deployment on public internet, update `api/server.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Specific origins only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Full Offline Mode

To run completely offline:

1. Start local Jarvis: `./jarvis-local`
2. Start local API: `./bin/jarvis-api --local`
3. All TTS, LLM, and embeddings use Ollama (no internet needed)

