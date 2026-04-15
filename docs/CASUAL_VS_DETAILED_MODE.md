# Casual vs Detailed vs Auto Mode

## Overview

Jarvis has three response style modes that control how tool results and Q&A responses are formatted for voice output. The key distinction is:

- **Internal LLM processing** - Always has full access to URLs, stash refs, file paths
- **Final speech output** - Formatted based on mode (casual/auto strip technical details)

---

## Quick Reference

| Mode | Best For | Word Limits | Technical Details |
|------|----------|-------------|-------------------|
| `casual` | Voice/TTS | Q&A: `JARVIS_QA_WORD_LIMIT`, Multi-turn: `JARVIS_MULTI_TURN_WORD_LIMIT`, Tool: 35 | Stripped |
| `auto` | Voice (smart) | Same configured limits as casual | Stripped (mostly) |
| `detailed` | CLI/debugging | No limit | Preserved |

---

## Mode Descriptions

### `JARVIS_RESPONSE_STYLE="casual"` (Voice-Friendly)

**Best for:** Voice mode, speakers, TTS

**Behavior:**
- Q&A responses: Up to `JARVIS_QA_WORD_LIMIT` (current cloud example: 100 words)
- Multi-turn summaries: Up to `JARVIS_MULTI_TURN_WORD_LIMIT` (current cloud example: 75 words)
- Tool confirmations: 35 words max (hardcoded)
- **Strips from speech:** stash:// refs, long URLs, file paths (added 2026-02-02)

**Examples:**
```
User: "What time is it?"
Output: "It's 12:34 AM on November 13th"

User: "What's the price of bitcoin?"
Output: "Bitcoin is $103,664, down 0.17% today"

User: "Generate an image of a cat"
Output: "Image generated and saved to stash"  (NOT stash://space_xxx/f_xxx)
```

---

### `JARVIS_RESPONSE_STYLE="auto"` (RECOMMENDED)

**Best for:** Voice mode with smart formatting decisions

**Behavior:**
- **Multi-turn (turn_num > 0):** Always uses `_format_multi_turn_summary()` to condense ALL tool results
- **Single-turn decisions based on tool type:**

| Tool Category | Examples | Behavior |
|---------------|----------|----------|
| **Search tools** | search_memory, brave_search | Always condense, remove URLs |
| **Simple tools** | get_time, crypto_price, weather | Keep if <25 words, condense if longer |
| **Complex tools** | opencode, execute_bash | Keep detailed if >75 words |
| **Unlisted tools** | (anything else) | Default to condense |

**GAP:** Complex tools with >75 word responses bypass `_format_single_turn_casual()`. Standard TTS still sanitizes spoken output, so this is mainly a displayed-text cleanliness gap.

---

### `JARVIS_RESPONSE_STYLE="detailed"`

**Best for:** CLI/debugging, terminal output

**Behavior:**
- Uses LLM's raw response verbatim
- No word limits
- URLs, stash refs, file paths preserved
- Markdown, emojis, numbered lists allowed

**Examples:**
```
User: "Start the tetris server"
Output: "The tetris server has been successfully started! 

Here's what was done:
1. Located the project at ~/jarvis-workspace/projects/tetris-game/
2. Activated the Python virtual environment
3. Started the Flask server in the background (PID: 128712)
4. Verified the server is responding on port 5000

The server is now accessible at http://localhost:5000"
```

---

## Configuration

### Environment Variables (cloud.env / local.env)

```bash
# Response style: casual, detailed, auto
JARVIS_RESPONSE_STYLE="auto"

# Word limit for Q&A/single-turn (used by _format_single_turn_casual)
# Example current cloud value: 100 words
JARVIS_QA_WORD_LIMIT=100

# Word limit for multi-turn/multi-tool summaries (used by _format_multi_turn_summary)
# Example current cloud value: 75 words
JARVIS_MULTI_TURN_WORD_LIMIT=75
```

### Web UI Overrides

`jarvis-web` can now override these values per mode from **Settings → AI Config**:

- `JARVIS_RESPONSE_STYLE`
- `JARVIS_QA_WORD_LIMIT`
- `JARVIS_MULTI_TURN_WORD_LIMIT`

Behavior:

- `cloud` and `local` overrides are stored separately in `jarvis-web/config/web_config.json`
- Blank value in the UI means "use env default"
- The router system prompt now reflects the live effective values, not stale generic defaults
- Final speech formatting also reads the live effective values through `get_config_value()`

### One-off Testing

```bash
# Test casual mode
JARVIS_RESPONSE_STYLE=casual ./orchestrator/orchestrator_v2.py cloud "query" --speak

# Test detailed mode  
JARVIS_RESPONSE_STYLE=detailed ./orchestrator/orchestrator_v2.py cloud "query"

# Test auto mode
JARVIS_RESPONSE_STYLE=auto ./orchestrator/orchestrator_v2.py cloud "query" --speak
```

---

## Technical Implementation

### Code Flow (orchestrator_v2.py)

```
raw_speech (LLM's verbose response with URLs, stash refs, etc.)
    ↓
[Check response_style]
    ↓
casual/auto mode? ──────────────────────────────────┐
    ↓                                               │
turn_num > 0? ──yes──► _format_multi_turn_summary() │
    ↓ no                                            │
tools_used? ──no──► _format_single_turn_casual()    │
    ↓ yes                                           │
[auto mode: check tool category]                    │
    ↓                                               │
detailed mode? ─────────────────► speech = raw_speech (no formatting)
    ↓
speech (final TTS output)
```

### Key Functions

| Function | Called By | Word Limit | Strips Refs |
|----------|-----------|------------|-------------|
| `_format_single_turn_casual()` | casual, auto | `JARVIS_QA_WORD_LIMIT` | ✅ Yes |
| `_format_multi_turn_summary()` | casual, auto | `JARVIS_MULTI_TURN_WORD_LIMIT` | ✅ Yes |
| `_format_auto_mode()` | auto only | varies | ✅ Mostly |
| `_format_tool_speech()` | tool confirmations | 35 | ❌ No |

### What Gets Stripped (casual/auto modes)

Added 2026-02-02 to prevent TTS from speaking technical references:

1. **stash:// references** → "saved to stash" or "image generated"
2. **Long URLs (>30 chars)** → domain only or "link saved"
3. **File paths** → just the filename

---

## WebUI vs Terminal

Both use the **same orchestrator** formatting:

- **WebUI (jarvis-web):** Calls `orchestrator.process()` → gets `speech` field → sends to TTS
- **Terminal (--speak):** Calls `orchestrator.process()` → gets `speech` field → sends to say.sh

The `raw_llm_response` is preserved in the response for "expand details" in the WebUI.

---

## Summary

| Mode | Use Case | Formatting | Strips Technical Refs |
|------|----------|------------|----------------------|
| `casual` | Voice | Always condense | ✅ Yes |
| `auto` | Voice (smart) | Condense based on tool type | ✅ Mostly |
| `detailed` | CLI/debug | No formatting | ❌ No |

---

*Last updated: 2026-03-29*  
*See also: `config/cloud.env` for full configuration options*
