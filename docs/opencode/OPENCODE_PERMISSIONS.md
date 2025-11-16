# OpenCode Permissions for Jarvis Integration

## The Problem

OpenCode's default permission model is designed for **interactive use** (TUI):
- User sees a prompt: "Allow OpenCode to edit file X?"
- User responds: Yes/No

**This doesn't work with Jarvis** (autonomous operation):
```
JARVIS → OpenCode: "Create app.py"
OpenCode → ???: "Need permission to edit"
(No one to ask - task hangs or fails)
```

## The Solution

**Set permissions to `allow` for Jarvis integration:**

```json
{
  "permission": {
    "edit": "allow",
    "bash": "allow"
  }
}
```

**Why this is safe:**
1. **Workspace boundaries** enforce what OpenCode can access
   - Via global `AGENTS.md` rules
   - Via system prompt (ABSOLUTE RULES)
   - OpenCode cannot modify `/home/boss/jarvis-voice`

2. **Jarvis is the permission layer**
   - User already approved by speaking to Jarvis
   - Jarvis routes to OpenCode only when appropriate
   - User trusts Jarvis → Jarvis trusts OpenCode

3. **Audit trail**
   - All OpenCode actions logged in `logs/opencode/*.jsonl`
   - All file operations visible in logs
   - Can review what OpenCode did

## Permission Modes

### `ask` (Interactive - NOT for Jarvis)
```json
"permission": {
  "edit": "ask",     // Prompts user for each edit
  "bash": "ask"      // Prompts user for each bash command
}
```
**Use case**: TUI mode, manual control
**Problem**: Blocks API calls, requires human input

### `allow` (Autonomous - FOR Jarvis)
```json
"permission": {
  "edit": "allow",   // Auto-allows all edits
  "bash": "allow"    // Auto-allows all bash commands
}
```
**Use case**: API mode, automated workflows
**Safety**: Enforced via workspace boundaries and logging

### `deny` (Locked Down)
```json
"permission": {
  "edit": "deny",    // Never allows edits
  "bash": "deny"     // Never allows bash
}
```
**Use case**: Read-only analysis mode
**Limitation**: Can't build anything

## Workspace Security Model

**Permissions are permissive, but boundaries are strict:**

| What | Permission | Boundary Enforcement |
|------|-----------|---------------------|
| Edit `/home/boss/jarvis-workspace/test.py` | ✅ Allowed | ✅ In workspace |
| Edit `/home/boss/jarvis-voice/config.py` | ✅ Allowed | ❌ **BLOCKED by AGENTS.md** |
| Bash in workspace | ✅ Allowed | ✅ In workspace |
| Bash `rm -rf /` | ✅ Allowed | ❌ **User wouldn't request this** |

**The real security is:**
1. **User intent** - What they ask Jarvis to do
2. **Jarvis routing** - Only routes appropriate tasks to OpenCode
3. **OpenCode training** - Follows AGENTS.md rules
4. **Logging** - Everything is auditable

## Current Configuration

**Location**: `~/.config/opencode/opencode.json`

**For Jarvis integration (recommended):**
```json
{
  "$schema": "https://opencode.ai/config.json",
  "permission": {
    "edit": "allow",
    "bash": "allow"
  },
  "provider": { ... },
  "autoupdate": true
}
```

**Global rules**: `~/.config/opencode/AGENTS.md`
- Workspace boundaries (READ ONLY for jarvis-voice)
- Code standards
- Response format

## Verification

**Check current permissions:**
```bash
cat ~/.config/opencode/opencode.json | jq '.permission'
```

**Test workspace boundaries:**
```bash
cd /home/boss/jarvis-voice
python3 << 'EOF'
import sys
sys.path.insert(0, 'lib')
from opencode_client import OpenCodeClient
from config_loader import load_config

load_config("cloud")
client = OpenCodeClient()

# Should be REFUSED despite "allow" permissions
result = client.execute_task(
    task="Create test.py in /home/boss/jarvis-voice/",
    context={}
)
# Check logs - OpenCode should refuse due to AGENTS.md rules
EOF
```

**Restart OpenCode to apply changes:**
```bash
sudo systemctl restart opencode-jarvis.service
```

## Alternatives Considered

### Option 1: Keep "ask" + Build Permission Handler
**Complexity**: High
**Maintenance**: Ongoing
**Benefit**: Marginal (workspace boundaries already enforce security)

### Option 2: Use "deny" + Whitelist Specific Operations
**Complexity**: Very High
**Limitation**: Can't build anything useful
**Benefit**: None (too restrictive)

### Option 3: Use "allow" + Strong Boundaries (CHOSEN ✅)
**Complexity**: Low
**Maintenance**: Minimal (AGENTS.md rules)
**Benefit**: Fully functional, secure, auditable

## Summary

**For Jarvis integration:**
- ✅ Set permissions to `allow`
- ✅ Enforce boundaries via `AGENTS.md` (global + project-specific)
- ✅ Log everything for audit
- ✅ Trust the user → Jarvis → OpenCode chain

**Security comes from:**
1. Workspace boundaries (enforced by AI, not filesystem)
2. User intent (Jarvis only routes appropriate tasks)
3. Audit logs (everything is traceable)
4. Code review (user sees what was built)

This model matches how other AI assistants (Cursor, Continue, etc.) operate in trusted environments.

