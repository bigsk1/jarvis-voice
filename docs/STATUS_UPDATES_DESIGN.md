# Status Updates Feature - Design Document

> **Purpose**: Provide real-time voice updates during long-running tasks to keep the user informed without requiring terminal access.

---

## Table of Contents

1. [Overview](#overview)
2. [Configuration](#configuration)
3. [Architecture](#architecture)
4. [Codebase Integration Points](#codebase-integration-points)
5. [Update Types & Triggers](#update-types--triggers)
6. [Edge Cases & Race Conditions](#edge-cases--race-conditions)
7. [Implementation Phases](#implementation-phases)
8. [Testing Plan](#testing-plan)

---

## Overview

### Problem
When Jarvis executes long tasks (OpenCode builds, multi-tool searches, API calls with retries), the user sits in silence wondering if anything is happening. The only feedback is the final speech output, which can take 30-300+ seconds.

### Solution
Periodic voice updates that:
- Inform the user of progress
- Alert on significant errors (immediately)
- Feel natural and conversational
- Don't spam or overlap with final output

### Example Flow
```
User: "Build me a Flask API with user authentication"

[0s]   Jarvis: "Got it, let me work on that"
[25s]  Jarvis: "OpenCode is setting up the project structure"
[50s]  Jarvis: "Writing the authentication logic, looking good"
[75s]  Jarvis: "Running tests, almost done"
[90s]  Jarvis: [FINAL] "Your Flask API is ready at port 8091..."
```

---

## Configuration

### New Environment Variables

```bash
# config/cloud.env and config/local.env

# ===== Status Updates (Voice Progress) =====
# Enable/disable voice status updates during long tasks
STATUS_UPDATES_ENABLED=true

# Minimum seconds between status updates (prevents spam)
# Note: Actual interval may be longer due to TTS generation time (~2-3s)
STATUS_UPDATE_INTERVAL=20

# Use existing JARVIS_RESPONSE_STYLE for update verbosity:
#   casual   → "Still working on it..."
#   detailed → "OpenCode: Installing dependencies (3/5 complete)"
#   auto     → Adapts based on task type
# (No new STATUS_UPDATE_STYLE needed - reuse existing)
```

### Defaults
| Variable | Default | Notes |
|----------|---------|-------|
| `STATUS_UPDATES_ENABLED` | `false` | Opt-in feature |
| `STATUS_UPDATE_INTERVAL` | `20` | 20s minimum between updates |

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        JARVIS MAIN LOOP                              │
│  (jarvis script / orchestrator)                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐ │
│  │   Router     │────▶│   Executor   │────▶│  StatusUpdater       │ │
│  │ (router_v2)  │     │ (executor)   │     │  (NEW: lib/)         │ │
│  └──────────────┘     └──────────────┘     └──────────┬───────────┘ │
│                              │                        │              │
│                              │ emit_status()          │ speak()      │
│                              ▼                        ▼              │
│                       ┌──────────────┐     ┌──────────────────────┐ │
│                       │    Tools     │     │   TTS Engine         │ │
│                       │  (skills/)   │     │  (existing: aplay)   │ │
│                       └──────────────┘     └──────────────────────┘ │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### StatusUpdater Class

```python
# lib/status_updater.py

class StatusUpdater:
    """
    Manages voice status updates during long-running tasks.
    
    Features:
    - Rate limiting (min interval between updates)
    - Priority system (errors bypass rate limit)
    - Collision detection (don't overlap with final output)
    - Background TTS (non-blocking)
    """
    
    def __init__(self):
        self.enabled = get_config_value('STATUS_UPDATES_ENABLED', 'false').lower() == 'true'
        self.interval = get_int('STATUS_UPDATE_INTERVAL', 20)
        self.style = get_config_value('JARVIS_RESPONSE_STYLE', 'casual')
        self.last_update_time = 0
        self.task_complete = False  # Flag to prevent overlap
        self.error_count = 0        # Track consecutive errors
        self._lock = threading.Lock()
    
    def update(self, message: str, priority: str = 'normal', context: dict = None):
        """
        Queue a status update.
        
        Args:
            message: The status message (will be adapted to style)
            priority: 'normal', 'high' (errors), or 'final' (task complete)
            context: Optional dict with tool_name, turn_number, etc.
        """
        pass
    
    def mark_complete(self):
        """Signal that task is done - suppress further updates."""
        pass
    
    def reset(self):
        """Reset for new task."""
        pass
```

---

## Codebase Integration Points

### 1. `orchestrator/orchestrator_v2.py` - Main Entry

**Location**: Main orchestration loop

**Changes**:
```python
# At start of handle_query()
status_updater.reset()

# After final response
status_updater.mark_complete()
```

**Why**: Initialize/cleanup status updater per query.

---

### 2. `orchestrator/executor.py` - Tool Execution

**Location**: `execute_tool()` and `execute_tools()` methods

**Changes**:
```python
# Before executing a tool
if tool_name == 'opencode':
    status_updater.update("OpenCode is working on your request", context={'tool': 'opencode'})
elif tool_name in ['mcp_brave_search_brave_web_search', 'mcp_fetch_fetch']:
    status_updater.update("Searching the web", context={'tool': tool_name})

# On tool error with retry
if not result.get('ok') and will_retry:
    status_updater.update("Hit a snag, trying another approach", priority='normal')

# On HTTP 500 error
if '500' in str(error) or 'Internal Server Error' in str(error):
    status_updater.update("Server error encountered", priority='high')

# On repeated failures (same tool 3+ times)
if consecutive_failures >= 3:
    status_updater.update("Having trouble with this, trying alternatives", priority='high')
```

**Why**: This is where tools actually run - best place to emit status.

---

### 3. `orchestrator/router_v2.py` - Multi-Turn Routing

**Location**: `route()` method, multi-turn handling

**Changes**:
```python
# On turn 3+ of multi-turn execution
if turn_number >= 3:
    status_updater.update(f"Making progress, on step {turn_number}", context={'turn': turn_number})

# When switching strategies
if previous_tool_failed and selecting_different_tool:
    status_updater.update("Trying a different approach")
```

**Why**: Multi-turn tasks are where users wait longest.

---

### 4. `skills/opencode.py` - OpenCode Tool

**Location**: OpenCode execution and waiting

**Current State**: 
- 360 second timeout for complex builds
- Blocking `requests.post()` call to OpenCode API
- Already has stderr message: "⏳ OpenCode is building..."
- Has `check_opencode_sessions` tool for checking logs separately

**Problem**: The blocking request means we can't emit updates during execution.

**Solution - Background Thread + Callback**:
```python
# In skills/opencode.py

def main():
    # ... setup ...
    
    # Create status callback for long tasks
    if status_updates_enabled() and is_complex:
        status_thread = threading.Thread(
            target=status_update_loop,
            args=(session_id, task),
            daemon=True
        )
        status_thread.start()
    
    # Execute (blocking)
    result = client.execute_task(task=task, ...)
    
    # Stop status updates
    stop_status_updates()

def status_update_loop(session_id: str, task: str):
    """Background thread that emits status updates during OpenCode execution."""
    interval = get_int('STATUS_UPDATE_INTERVAL', 20)
    style = get_config_value('JARVIS_RESPONSE_STYLE', 'casual')
    
    messages_casual = [
        "OpenCode is working on it",
        "Still building, making progress",
        "Almost there, finishing up",
    ]
    
    messages_detailed = [
        "OpenCode is setting up your project",
        "Installing dependencies and configuring",
        "Writing code and running tests",
        "Finalizing build",
    ]
    
    messages = messages_casual if style == 'casual' else messages_detailed
    idx = 0
    
    while not should_stop():
        time.sleep(interval)
        if should_stop():
            break
        
        # Get actual session status if available
        try:
            session = client.get_session(session_id)
            if session.get('status') == 'error':
                speak_status("Hit an issue, but still trying")
                continue
        except:
            pass
        
        # Speak progress message
        msg = messages[min(idx, len(messages)-1)]
        speak_status(msg)
        idx += 1
```

**Why Background Thread**: OpenCode API is blocking (360s timeout). Can't poll mid-request. Background thread with separate status speaker works alongside.

**Better Approach - OpenCode Session Polling**:
OpenCode HAS a session status endpoint! Use it for real progress:

```python
# Poll actual OpenCode session for real status
def get_opencode_status(session_id: str) -> str:
    """Get real status from OpenCode session endpoint."""
    response = requests.get(f"{OPENCODE_BASE_URL}/sessions/{session_id}", timeout=5)
    if response.status_code == 200:
        session = response.json()
        # Extract meaningful status from session data
        status = session.get('status', 'working')
        last_message = session.get('messages', [{}])[-1]
        
        # Check for tool calls, errors, etc.
        if last_message.get('type') == 'tool_call':
            tool = last_message.get('tool', {}).get('name', 'working')
            return f"Running {tool}"
        elif status == 'error':
            return "Hit an issue, recovering"
        elif status == 'complete':
            return None  # Don't speak, about to finish
        else:
            return "Making progress"
    return None

# API Docs: http://192.168.70.228:4096/doc
# Session endpoint: GET /sessions/<uuid>
```

---

### 5. `jarvis` / `jarvis-local` Scripts - TTS Output

**Location**: Main voice loop scripts

**Changes**:
```python
# Add collision detection before final TTS
status_updater.mark_complete()  # Stop any pending updates
time.sleep(0.5)  # Brief pause to let any in-flight TTS finish
play_tts(final_response)
```

**Why**: Prevent status update overlapping with final response.

---

### 6. `bin/say.sh` - Existing TTS Script

**Location**: TTS generation and playback

**Current Flow**:
```bash
# bin/say.sh
1. Build JSON with model, voice, input, instructions
2. Call OpenAI TTS API → get audio
3. Convert with ffmpeg → WAV
4. Add 200ms lead-in padding (sox)
5. Play with aplay
```

**Changes for Status Updates**:

Both cloud and local modes need support, reusing existing env vars for voice consistency:

```bash
# bin/say-status.sh (NEW) - Cloud mode status TTS
#!/bin/bash
# Lightweight status TTS for cloud mode
# - Reuses ALL existing TTS env vars (VOICE, TTS_MODEL, TTS_INSTRUCTIONS, etc.)
# - Skips lead-in padding (status is short)
# - Non-blocking option via background process

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "cloud"

TEXT="$1"
BLOCKING="${2:-true}"

OUTFILE="/tmp/jarvis-status-$$.wav"

# Build TTS JSON with existing env vars (same voice as main responses)
TTS_JSON=$(jq -n \
  --arg model "$TTS_MODEL" \
  --arg voice "$VOICE" \
  --arg input "$TEXT" \
  --arg instructions "$TTS_INSTRUCTIONS" \
  '{model:$model, voice:$voice, input:$input, instructions:$instructions}')

curl -s -X POST "https://api.openai.com/v1/audio/speech" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$TTS_JSON" \
  | ffmpeg -hide_banner -loglevel error -i - -ar "$RATE" -ac 2 -f wav -y "$OUTFILE"

if [ "$BLOCKING" = "true" ]; then
    aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null
else
    aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null &
fi
rm -f "$OUTFILE" 2>/dev/null || true
```

```bash
# bin/say-status-local.sh (NEW) - Local mode status TTS
#!/bin/bash
# Lightweight status TTS for local mode
# Uses local TTS (e.g., piper, espeak, or local API)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "local"

TEXT="$1"
BLOCKING="${2:-true}"

OUTFILE="/tmp/jarvis-status-$$.wav"

# Local TTS options (configure in local.env):
# Option 1: Piper TTS (fast, offline)
# Option 2: Local OpenAI-compatible API
# Option 3: espeak fallback

if [ -n "${LOCAL_TTS_API_URL:-}" ]; then
    # Local TTS API (OpenAI-compatible)
    curl -s -X POST "$LOCAL_TTS_API_URL/v1/audio/speech" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"${LOCAL_TTS_MODEL:-tts-1}\",\"voice\":\"${VOICE:-alloy}\",\"input\":\"$TEXT\"}" \
      | ffmpeg -hide_banner -loglevel error -i - -ar "$RATE" -ac 2 -f wav -y "$OUTFILE"
elif command -v piper &>/dev/null; then
    # Piper TTS (offline)
    echo "$TEXT" | piper --model "${PIPER_MODEL:-en_US-lessac-medium}" --output_file "$OUTFILE"
else
    # espeak fallback
    espeak -w "$OUTFILE" "$TEXT" 2>/dev/null
fi

if [ "$BLOCKING" = "true" ]; then
    aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null
else
    aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null &
fi
rm -f "$OUTFILE" 2>/dev/null || true
```

**Python Wrapper** (mode-aware):
```python
# In lib/status_updater.py
def _speak(self, message: str, blocking: bool = False):
    """Speak via appropriate TTS script based on mode."""
    script_name = 'say-status-local.sh' if self.mode == 'local' else 'say-status.sh'
    script = os.path.join(self.project_root, 'bin', script_name)
    blocking_arg = 'true' if blocking else 'false'
    subprocess.Popen([script, message, blocking_arg], 
                     stdout=subprocess.DEVNULL, 
                     stderr=subprocess.DEVNULL)
```

**Why**: 
- Reuses existing TTS infrastructure and env vars
- Same voice personality across all responses
- Supports both cloud (OpenAI) and local (Piper/espeak) modes

---

## Update Types & Triggers

### Trigger Matrix

| Trigger | When | Message (casual) | Message (detailed) | Priority |
|---------|------|------------------|-------------------|----------|
| **Task Start** | Query received | "On it" | "Starting your request" | normal |
| **Web Search** | brave_search called | "Searching..." | "Searching web for X" | normal |
| **OpenCode Start** | opencode tool called | "Building..." | "OpenCode starting build" | normal |
| **OpenCode Progress** | Every 20s during build | "Still building" | "OpenCode: [log summary]" | normal |
| **Multi-Turn 3+** | Turn 3+ starts | "Making progress" | "Step 3: gathering more data" | normal |
| **Tool Retry** | Tool fails, retrying | "Trying again" | "Retrying with different params" | normal |
| **HTTP 500** | Server error | "Server hiccup" | "Server error, retrying" | **high** |
| **Repeated Fails** | Same tool fails 3x | "Having trouble" | "Multiple failures, changing approach" | **high** |
| **Near Complete** | Final tool starting | "Almost done" | "Finishing up" | normal |
| **Long Wait** | 45s+ no update | "Still working" | "Processing, please wait" | normal |

### Error Deduplication

```python
# Prevent spam on repeated errors
class StatusUpdater:
    def __init__(self):
        self.recent_errors = []  # Track last 5 error messages
        self.error_cooldown = 30  # Don't repeat same error within 30s
    
    def _should_speak_error(self, error_msg: str) -> bool:
        """Check if this error should be spoken (not a repeat)."""
        error_key = self._normalize_error(error_msg)
        
        # Check if same error spoken recently
        for prev_error, timestamp in self.recent_errors:
            if prev_error == error_key and time.time() - timestamp < self.error_cooldown:
                return False  # Skip - already spoken
        
        # Add to recent errors
        self.recent_errors.append((error_key, time.time()))
        self.recent_errors = self.recent_errors[-5:]  # Keep last 5
        return True
```

---

## Edge Cases & Race Conditions

### 1. Update at 20s, Task Done at 21s

**Problem**: Status update speaks, then immediately final response speaks = overlap.

**Solution**:
```python
# In StatusUpdater
def update(self, message, priority='normal', context=None):
    with self._lock:
        if self.task_complete:
            return  # Task done, don't speak
        
        # Check if we're too close to expected completion
        if context and context.get('estimated_remaining', 999) < 5:
            return  # Too close to end, skip update

# In orchestrator, before final TTS
status_updater.mark_complete()
time.sleep(0.3)  # Let any in-flight audio finish
```

### 2. TTS Generation Delay

**Problem**: TTS takes 2-3s to generate. If we trigger update at 20s, it speaks at 23s.

**Solution**: Account for TTS latency in interval calculation.
```python
EFFECTIVE_INTERVAL = STATUS_UPDATE_INTERVAL + 3  # Add TTS buffer
```

### 3. Concurrent Updates

**Problem**: Multiple tools running in parallel could trigger updates simultaneously.

**Solution**: Use lock + queue.
```python
def update(self, message, ...):
    with self._lock:
        now = time.time()
        if now - self.last_update_time < self.interval:
            return  # Rate limited
        self.last_update_time = now
        self._speak_async(message)
```

### 4. User Speaks During Update

**Problem**: User might try to speak while status update is playing.

**Solution**: Keep updates SHORT (< 3 seconds of audio). Natural pause after.

### 5. Tool Fails 10 Times in Loop

**Problem**: Bad credentials or broken tool retries repeatedly = 10 error messages?

**Solution**: Error deduplication (see above) + max errors per task.
```python
MAX_SPOKEN_ERRORS_PER_TASK = 2

def _should_speak_error(self, error_msg):
    if self.spoken_errors_count >= MAX_SPOKEN_ERRORS_PER_TASK:
        return False
    # ... deduplication logic ...
    self.spoken_errors_count += 1
    return True
```

---

## Implementation Phases

### Phase 1: Core Infrastructure (MVP)
**Files**: `lib/status_updater.py`, `config/*.env`

- [ ] Create `StatusUpdater` class
- [ ] Add config variables
- [ ] Implement rate limiting
- [ ] Implement basic TTS integration (blocking first)
- [ ] Add to executor for basic "working on it" messages

**Test**: Single long task gets 1-2 status updates.

### Phase 2: Smart Updates
**Files**: `orchestrator/executor.py`, `orchestrator/router_v2.py`

- [ ] Add tool-specific messages
- [ ] Add multi-turn progress updates
- [ ] Implement error priority system
- [ ] Add collision detection with final output

**Test**: Multi-turn task with errors gets appropriate updates.

### Phase 3: OpenCode Integration
**Files**: `skills/opencode.py`

- [ ] Add log polling during OpenCode execution
- [ ] Implement log summarization for status
- [ ] Style-aware summaries (casual vs detailed)

**Test**: OpenCode build task gets progress updates from actual build logs.

### Phase 4: Polish & Background TTS
**Files**: `lib/status_updater.py`, TTS integration

- [ ] Non-blocking TTS playback
- [ ] Audio overlap prevention
- [ ] Error deduplication
- [ ] Tuning intervals and messages

**Test**: Rapid tasks don't cause audio overlap.

---

## Testing Plan

### Manual Tests

```bash
# Test 1: Basic status update
./orchestrator/orchestrator_v2.py cloud "Build a Flask API with OpenCode"
# Expected: Hear "Working on it" after ~20s, then final response

# Test 2: Multi-turn with updates
./orchestrator/orchestrator_v2.py cloud "Search the web for latest AI news and summarize"
# Expected: Hear "Searching..." then "Found some results..." then final

# Test 3: Error handling
# (Temporarily break an API key)
./orchestrator/orchestrator_v2.py cloud "Get the weather in Seattle"
# Expected: Hear "Having trouble" once (not 10 times), then error response

# Test 4: Disable feature
STATUS_UPDATES_ENABLED=false ./orchestrator/orchestrator_v2.py cloud "Build something"
# Expected: No status updates, only final response

# Test 5: Collision prevention
# (Set interval to 5s, run 7s task)
# Expected: No overlap between status and final
```

### Integration Test Script

```bash
# tests/integration/test-status-updates.sh

echo "Test: Status updates enabled"
export STATUS_UPDATES_ENABLED=true
export STATUS_UPDATE_INTERVAL=10

# Run long task, capture audio output timestamps
# Verify: Updates at ~10s intervals, no overlap with final
```

---

## File Summary

| File | Changes | Phase |
|------|---------|-------|
| `lib/status_updater.py` | **NEW** - Core status manager | 1 |
| `config/cloud.env` | Add STATUS_UPDATES_* vars | 1 |
| `config/local.env` | Add STATUS_UPDATES_* vars | 1 |
| `orchestrator/executor.py` | Emit status on tool execution | 1-2 |
| `orchestrator/router_v2.py` | Emit status on multi-turn | 2 |
| `orchestrator/orchestrator_v2.py` | Init/cleanup status updater | 1 |
| `skills/opencode.py` | Poll logs, emit summaries | 3 |
| `jarvis` / `jarvis-local` | Collision detection | 4 |
| `lib/tts.py` (or existing) | Background TTS playback | 4 |

---

## Open Questions

1. **TTS Provider**: Use same OpenAI TTS as main responses? Or faster/lighter alternative for status?
2. **Audio Queue**: Should status updates queue or interrupt each other?
3. **Visual Feedback**: Add terminal output alongside voice? (for debugging)
4. **Disable Mid-Task**: Should user be able to say "stop updates" during a task?

---

## Dynamic Phrase System

### Why Dynamic?
- **Feels natural**: Random selection = never know what you'll get
- **Extensible**: Add phrases without code changes
- **Personality**: Humor, sass, encouragement as toggle options
- **Tool-agnostic**: Tools come and go, messages adapt

### Phrase Configuration File

```json
// config/status_phrases.json
{
  "version": "1.0",
  "settings": {
    "humor_enabled": true,
    "sass_level": 1,          // 0=professional, 1=light, 2=sassy
    "encouragement": true
  },
  
  "categories": {
    "task_start": {
      "standard": [
        "On it",
        "Got it",
        "Working on that",
        "Let me handle that"
      ],
      "humor": [
        "Challenge accepted",
        "Consider it done... eventually",
        "Ooh, this looks fun"
      ]
    },
    
    "progress": {
      "standard": [
        "Still working on it",
        "Making progress",
        "Getting there",
        "Hang tight"
      ],
      "humor": [
        "Rome wasn't built in a day, but I'm faster",
        "Still cooking, almost ready to serve",
        "Halfway there... I think"
      ],
      "encouragement": [
        "This is going well",
        "Looking good so far",
        "Smooth sailing"
      ]
    },
    
    "searching": {
      "standard": [
        "Searching the web",
        "Looking that up",
        "Gathering information"
      ],
      "humor": [
        "Consulting the oracle",
        "Diving into the internet rabbit hole",
        "Asking the hive mind"
      ]
    },
    
    "building": {
      "standard": [
        "Building your project",
        "OpenCode is working",
        "Setting things up"
      ],
      "detailed": [
        "Installing dependencies",
        "Writing code",
        "Running tests",
        "Finalizing build"
      ],
      "humor": [
        "Teaching electrons to dance",
        "Turning coffee into code",
        "Assembling digital Legos"
      ]
    },
    
    "error_retry": {
      "standard": [
        "Hit a snag, trying again",
        "Small hiccup, working around it",
        "Trying a different approach"
      ],
      "humor": [
        "Well that didn't work, Plan B",
        "First attempt was just a warm-up",
        "Okay, let's try that again"
      ]
    },
    
    "near_complete": {
      "standard": [
        "Almost there",
        "Wrapping up",
        "Just finishing"
      ],
      "humor": [
        "Home stretch!",
        "The finish line is in sight",
        "Putting the cherry on top"
      ]
    },
    
    "long_wait": {
      "standard": [
        "Still working, shouldn't be long",
        "Taking a bit longer than expected",
        "Patience, grasshopper"
      ],
      "humor": [
        "Good things come to those who wait",
        "I'm not frozen, I promise",
        "Worth the wait, trust me"
      ]
    }
  },
  
  "tool_specific": {
    "_description": "Override messages for specific tools. Falls back to categories if not defined.",
    "opencode": {
      "start": ["OpenCode is on it", "Starting the build"],
      "progress": ["Build in progress", "OpenCode is cooking"],
      "error": ["Build hit an issue", "OpenCode stumbled, recovering"]
    },
    "mcp_brave_search_brave_web_search": {
      "start": ["Searching the web"],
      "progress": ["Found some results, analyzing"]
    }
    // New tools automatically use category defaults - no config needed
  }
}
```

### Phrase Selection Logic

```python
# lib/status_phrases.py

import json
import random
from pathlib import Path

class StatusPhrases:
    """Dynamic phrase selection for status updates."""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / 'config' / 'status_phrases.json'
        
        self.config = self._load_config(config_path)
        self.settings = self.config.get('settings', {})
        self.categories = self.config.get('categories', {})
        self.tool_specific = self.config.get('tool_specific', {})
    
    def get_phrase(self, category: str, tool_name: str = None, style: str = 'casual') -> str:
        """
        Get a random phrase for the given category.
        
        Args:
            category: 'task_start', 'progress', 'searching', 'building', etc.
            tool_name: Optional tool name for tool-specific overrides
            style: 'casual' or 'detailed'
        
        Returns:
            Random phrase from appropriate pool
        """
        # Check tool-specific first
        if tool_name and tool_name in self.tool_specific:
            tool_phrases = self.tool_specific[tool_name]
            # Map category to tool-specific key (start/progress/error)
            key = self._category_to_key(category)
            if key in tool_phrases:
                return random.choice(tool_phrases[key])
        
        # Fall back to category
        if category not in self.categories:
            return "Working on it"  # Ultimate fallback
        
        cat = self.categories[category]
        
        # Build pool based on settings and style
        pool = list(cat.get('standard', []))
        
        if style == 'detailed' and 'detailed' in cat:
            pool = list(cat['detailed'])  # Replace with detailed
        
        if self.settings.get('humor_enabled') and 'humor' in cat:
            # Add humor phrases with lower weight
            pool.extend(cat['humor'])
        
        if self.settings.get('encouragement') and 'encouragement' in cat:
            pool.extend(cat['encouragement'])
        
        return random.choice(pool) if pool else "Working on it"
    
    def _category_to_key(self, category: str) -> str:
        """Map category to tool-specific key."""
        mapping = {
            'task_start': 'start',
            'progress': 'progress',
            'building': 'progress',
            'searching': 'start',
            'error_retry': 'error',
            'near_complete': 'progress'
        }
        return mapping.get(category, 'progress')
    
    def _load_config(self, path: Path) -> dict:
        """Load config, return defaults if missing."""
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            return self._default_config()
    
    def _default_config(self) -> dict:
        """Minimal default if config file missing."""
        return {
            'settings': {'humor_enabled': False},
            'categories': {
                'progress': {'standard': ['Working on it', 'Making progress']},
                'error_retry': {'standard': ['Trying again']}
            }
        }
```

### Adding New Tools

When a new tool is added, it **automatically** uses category defaults. No config changes needed.

To add tool-specific messages (optional):
```json
// Just add to config/status_phrases.json
"tool_specific": {
  "my_new_tool": {
    "start": ["Starting my new tool"],
    "progress": ["My tool is working hard"]
  }
}
```

### Config Toggles in .env

```bash
# config/cloud.env

# Status phrase personality
STATUS_HUMOR_ENABLED=true        # Include funny phrases
STATUS_SASS_LEVEL=1              # 0=pro, 1=light, 2=sassy
STATUS_ENCOURAGEMENT=true        # Include encouraging phrases
```

---

## Appendix: Default Phrase Examples

### Casual Style (from standard pool)
```
"On it"
"Searching the web"
"Still working on it"
"OpenCode is building"
"Making progress"
"Almost there"
"Hit a snag, trying something else"
```

### Detailed Style (from detailed pool)
```
"Starting your request"
"Installing dependencies"
"Running tests, 3 of 5 passing"
"Step 4 of multi-step task"
"Finalizing build"
```

### With Humor Enabled (random mix)
```
"Challenge accepted"
"Consulting the oracle"
"Teaching electrons to dance"
"First attempt was just a warm-up"
"Home stretch!"
```

---

*Document Version: 1.0*
*Created: 2025-11-29*
*Status: Design Phase*

