# Voice Mode JSON Parsing Fixes

## Problem
Voice mode (`./jarvis`) was crashing with `jq: parse error` when Jarvis executed tools, breaking the wake loop.

## Root Cause
**Stdout contamination**: Even with `--json` flag set, some code was printing to stdout instead of stderr, causing non-JSON output that broke `jq` parsing in `question-orchestrator.sh`.

## Files Fixed

### 1. `/orchestrator/executor.py` (Line 81)
**Before:**
```python
print(f"⚠️  Permission check: {warning}")
```

**After:**
```python
# Only print if not in JSON mode (for voice scripts)
if sys.stdout.isatty() or os.environ.get('JARVIS_JSON_MODE') != '1':
    print(f"⚠️  Permission check: {warning}", file=sys.stderr)
```

**Impact**: Permission warnings were leaking to stdout, breaking JSON output.

---

### 2. `/lib/mcp_client.py` (Lines 203, 263)
**Before:**
```python
print(f"Error listing tools from MCP server {self.name}: {e}")
# ...
print(f"MCP tool error details: {error_detail}")
```

**After:**
```python
print(f"Error listing tools from MCP server {self.name}: {e}", file=sys.stderr)
# ...
print(f"MCP tool error details: {error_detail}", file=sys.stderr)
```

**Impact**: MCP errors were contaminating stdout.

---

## How Voice Mode Works

```bash
./jarvis → question-orchestrator.sh → orchestrator_v2.py --json → jq parse → TTS
```

**Critical Flow:**
1. `question-orchestrator.sh` calls: `python3 orchestrator_v2.py cloud "$TRANSCRIPT" --json`
2. Orchestrator sets `JARVIS_JSON_MODE=1` environment variable
3. All output to stdout MUST be pure JSON
4. Errors/warnings/debug info → `stderr` only
5. `jq` parses JSON from stdout: `jq -r '.speech'`

## The --json Flag Contract

When `--json` flag is used:
- ✅ **stdout** = Pure JSON only (no extra text, no debug messages)
- ✅ **stderr** = All human-readable messages, warnings, errors
- ✅ **Environment** = `JARVIS_JSON_MODE=1` is set for all child processes

## Testing

### Test JSON mode directly:
```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate

# Should output ONLY JSON to stdout
python3 orchestrator/orchestrator_v2.py cloud "what time is it" --json

# Should be parseable by jq
python3 orchestrator/orchestrator_v2.py cloud "what time is it" --json | jq -r '.speech'
```

### Test multi-turn with complex tools:
```bash
# This should work without jq errors
python3 orchestrator/orchestrator_v2.py cloud "use opencode to create a hello world app" --json | jq '.'
```

### Test voice mode end-to-end:
```bash
# Should not crash with jq errors
./bin/question-orchestrator.sh "what time is it"
```

## Future Prevention

### Code Review Checklist:
- [ ] All `print()` statements go to `stderr` unless outputting final JSON result
- [ ] Check for `sys.stdout.isatty()` or `JARVIS_JSON_MODE` before printing
- [ ] Use `file=sys.stderr` parameter in print statements
- [ ] Test with `--json` flag before committing

### For New Skills/Tools:
```python
# ❌ BAD - breaks JSON mode
print("Processing...")

# ✅ GOOD - respects JSON mode
import sys
print("Processing...", file=sys.stderr)

# ✅ BETTER - only if interactive
if sys.stdout.isatty():
    print("Processing...", file=sys.stderr)
```

## Other Issues Discovered (Process Improvements)

### Issue #2: Background Commands Timeout
**Problem**: `execute_bash` with background commands (`&`) hangs for 15s timeout.

**Example**: 
```bash
python3 -m http.server 8080 &
```

**Why**: Tool waits for subprocess to complete, but background processes never "complete".

**Solution Options**:
1. **Don't use `&` in commands** - Let the tool handle backgrounding if needed
2. **Create dedicated scripts** - Use systemd, screen, or tmux for long-running processes
3. **Use nohup properly** - Redirect all output: `nohup command > /dev/null 2>&1 &`

**Better Approach**:
```bash
# Instead of this:
cd ~/project && python server.py &

# Do this:
# 1. Create a start script
# 2. Use systemd service
# 3. Or use screen/tmux
screen -dmS tetris bash -c "cd ~/project && python server.py"
```

---

### Issue #3: Jarvis Forgetting Context
**Problem**: Jarvis tried multiple random approaches (xdg-open, http.server) instead of using existing Flask server.

**Root Cause**: Memory system not being queried for project details.

**Solution**: 
1. Ensure project details are saved to memory after OpenCode builds
2. Update router to check memory for "how to run X" queries
3. Add intel file: `jarvis-intel/projects.md` with common project patterns

---

### Issue #4: xdg-open Doesn't Work Headless
**Problem**: Tried to open HTML file with `xdg-open` (GUI command) in headless environment.

**Solution**: Jarvis should:
- Check if GUI is available: `if [ -n "$DISPLAY" ]; then`
- Default to command-line approaches for servers
- Use `curl` or `wget` to verify web servers

---

## Summary of Fixes

| Issue | Impact | Fix | Status |
|-------|--------|-----|--------|
| Stdout contamination | Voice mode crash | Redirect to stderr | ✅ Fixed |
| Background command timeout | 15s delays | Better command patterns | 📝 Documented |
| Context forgetting | Wrong approaches | Memory integration | 🔄 Ongoing |
| GUI commands headless | Command failures | Headless detection | 📝 Documented |

## Next Steps

1. **Test voice mode thoroughly** - Try various commands with wake word
2. **Monitor logs** - Check for any remaining stdout leaks
3. **Update memory system** - Ensure project details are persisted
4. **Create project templates** - Add common patterns to intel system

---

*Last updated: 2025-11-13*
*Issue discovered during: Tetris game testing with multi-turn orchestration*

