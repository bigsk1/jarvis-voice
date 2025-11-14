# Jarvis Configuration

This directory contains configuration files for Jarvis Voice Assistant.

## Quick Start

1. **Choose your mode:**
   - **Cloud mode**: Uses Anthropic/OpenAI APIs (requires API keys, best performance)
   - **Local mode**: Uses Ollama (no API keys, runs offline, requires GPU)

2. **Copy the example file:**
   ```bash
   # For cloud mode:
   cp cloud.env.example cloud.env
   
   # For local mode:
   cp local.env.example local.env
   ```

3. **Edit your config file:**
   ```bash
   # Edit and add your API keys (cloud mode only)
   nano cloud.env
   # or
   nano local.env
   ```

4. **Run Jarvis:**
   ```bash
   # Cloud mode
   ./jarvis  # voice mode
   ./orchestrator/orchestrator_v2.py cloud "What time is it?"  # CLI
   
   # Local mode
   ./jarvis-local  # voice mode
   ./orchestrator/orchestrator_v2.py local "What time is it?"  # CLI
   ```

## Configuration Files

### `cloud.env` (Cloud Mode)
- **Uses**: Anthropic Claude or OpenAI GPT
- **Requires**: API keys (costs money per request)
- **Best for**: Production use, maximum accuracy, complex tasks
- **OpenCode**: Can use Claude (recommended) or OpenAI

### `local.env` (Local Mode)
- **Uses**: Ollama with local models (qwen3-vl recommended)
- **Requires**: GPU with 8GB+ VRAM
- **Best for**: Development, offline work, privacy, no API costs
- **OpenCode**: Can use local Ollama models OR Anthropic (safer)

### Example Files (Safe for Git)
- `cloud.env.example` - Template for cloud mode
- `local.env.example` - Template for local mode
- **Never commit** `cloud.env` or `local.env` (contains API keys!)

## Important Settings

### LLM Provider Selection

**Jarvis Tool Calling** (main LLM):
```bash
# Cloud mode
LLM_PROVIDER="anthropic"
ANTHROPIC_MODEL="claude-sonnet-4-5-20250929"

# Local mode
LLM_PROVIDER="ollama"
OLLAMA_MODEL="qwen3-vl"
```

**OpenCode Agent** (coding tasks):
```bash
# Recommended: Use Claude even in local mode (safer for code execution)
OPENCODE_PROVIDER="anthropic"
OPENCODE_MODEL="claude-sonnet-4-5-20250929"

# Experimental: Local Ollama models (less safe, less reliable)
OPENCODE_PROVIDER="ollama"
OPENCODE_MODEL="qwen2.5-coder:32b"
```

### Response Style

```bash
JARVIS_RESPONSE_STYLE="auto"  # Recommended
# Options:
#   "auto" - Smart formatting based on context
#   "casual" - Always concise (8-12 words for voice)
#   "detailed" - Full LLM output (debugging)
```

## Security Notes

1. **API Keys**: Never commit files with real API keys
2. **Git Ignore**: The `.gitignore` should include:
   ```
   config/cloud.env
   config/local.env
   ```

3. **OpenCode Safety**: 
   - Local models can execute arbitrary code
   - Recommended: Use Claude for OpenCode even in local mode
   - Workspace is sandboxed to `/home/boss/jarvis-workspace`

## Troubleshooting

### "OpenCode server not reachable"
```bash
# Start OpenCode
systemctl --user start opencode
# or
cd ~/opencode && npm start
```

### "Ollama connection failed"
```bash
# Check Ollama status
curl http://192.168.70.226:11434
# Start Ollama
ollama serve
```

### "Model not found"
```bash
# Install recommended models
ollama pull qwen3-vl
ollama pull nomic-embed-text
```

## Advanced Configuration

### Network Setup (WireGuard VPN example)
```bash
# If services run on different machine:
OLLAMA_BASE_URL="http://192.168.70.226:11434"
OPENCODE_BASE_URL="http://192.168.70.226:4096"
```

### GPU Optimization
```bash
# Adjust for your VRAM (16GB example)
OLLAMA_CONTEXT_LENGTH=32768
MAX_CONTEXT_TOKENS=32768
```

### Hybrid Mode
```bash
# Use Ollama for Jarvis, Claude for OpenCode
LLM_PROVIDER="ollama"  # Free, offline
OPENCODE_PROVIDER="anthropic"  # Paid, safer
```

## Model Recommendations

### Cloud Mode (Anthropic)
- **Best overall**: `claude-sonnet-4-5-20250929`
- **Fastest**: `claude-sonnet-4-20250514`
- **Legacy**: `claude-3-7-sonnet-20250219`

### Local Mode (Ollama)
- **Best for Jarvis**: `qwen3-vl` (8B, 256K context, excellent tool calling)
- **Best for OpenCode**: Use Claude API (more reliable)
- **Experimental OpenCode**: `qwen2.5-coder:32b` (32B, needs lots of VRAM)

## Support

For issues, see:
- Main README: `/home/boss/jarvis-voice/README.md`
- Docs: `/home/boss/jarvis-voice/docs/`
- Logs: `/home/boss/jarvis-voice/logs/`

