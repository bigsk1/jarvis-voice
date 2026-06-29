# OpenCode Plugins for Jarvis

This directory contains OpenCode plugins that enforce safety and enhance capabilities when Jarvis delegates tasks to OpenCode.

**Important**: These plugins only activate when Jarvis calls the OpenCode tool. They do NOT affect Jarvis's own operations.

---

## Installed Plugins

### 🛡️ `00-workspace-protection.js`
**Status**: ✅ Active
**Purpose**: Enforce strict workspace boundaries for OpenCode

**Safety Rules**:
1. ✅ Block write/edit/delete outside `~/jarvis-workspace`
2. ✅ Block all access to `~/jarvis-voice` (Jarvis codebase)
3. ✅ Block system directories (`/etc`, `/usr`, `/bin`, `/sys`, `/proc`)
4. ✅ Block sensitive home directories (`~/.ssh`, `~/.gnupg`, `~/.config/*`)
5. ✅ Allow OpenCode to work freely within its workspace

**When it triggers**:
```
User: "Jarvis, use OpenCode to build a Flask API"
Jarvis: Calls OpenCode tool
OpenCode: Works in ~/jarvis-workspace ✅ Allowed
OpenCode: Tries to edit ~/jarvis-voice/orchestrator.py ❌ BLOCKED
```

**Error messages** (when boundaries are violated):
```
❌ BLOCKED: Cannot access Jarvis codebase
   Path: ~/jarvis-voice/orchestrator.py
   Reason: ~/jarvis-voice is protected (read-only from workspace only)

   If you need to understand Jarvis APIs, ask Jarvis to provide the information.
```

**Why it's essential**:
- Prevents OpenCode from accidentally damaging Jarvis itself
- Critical for local models (Qwen) that may ignore system prompts
- Defense-in-depth security layer

---

## Plugin Load Order

Plugins are loaded alphabetically. Use prefixes to control order:
- `00-*`: Safety/protection plugins (load first)
- `10-*`: Core functionality plugins
- `20-*`: Enhancement plugins
- `99-*`: Debug/development plugins

---

## Testing the Plugin

To verify the workspace protection plugin is working:

```bash
# Start the service installed by bin/install-opencode-service.sh
sudo systemctl start opencode-jarvis.service

# Test via Jarvis (should be blocked)
./jarvis-local
> "Use OpenCode to edit the file ~/jarvis-voice/README.md"
# Expected: ❌ BLOCKED error message

# Test via Jarvis (should work)
./jarvis-local
> "Use OpenCode to create a test file in the workspace"
# Expected: ✅ File created in ~/jarvis-workspace
```

Or test directly via OpenCode API (if you want to test without Jarvis):

```bash
# This requires calling OpenCode API directly - see opencode docs
curl -X POST http://localhost:4096/message \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "test-session",
    "message": "Write a test file to /etc/test.txt"
  }'
# Expected: Error with plugin block message
```

---

## Plugin Architecture

```
┌─────────────────────────────────────┐
│ User: "Use OpenCode to do X"       │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Jarvis (orchestrator)               │
│ - Routes to opencode.py tool        │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ OpenCode Server (localhost:4096)    │
│ - Loads plugins from this directory │
│ - Executes task                     │
│ - Plugins intercept tool calls      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Plugin: tool.execute.before         │
│ - Validates file paths              │
│ - Blocks operations if needed       │
│ - Returns error or allows           │
└─────────────────────────────────────┘
```

**Key Point**: Plugins run INSIDE OpenCode, not in Jarvis. They are OpenCode's guardrails.

---

## Adding New Plugins

Create a new `.js` file in this directory:

```javascript
// ~/.config/opencode/plugin/10-my-plugin.js

export const MyPlugin = async ({ project, client, $, directory, worktree }) => {
  console.log("🔌 My Plugin loaded");

  return {
    // Hook into tool execution
    "tool.execute.before": async (input, output) => {
      // Validate or modify tool calls
    },

    // Hook into events
    "event": async ({ event }) => {
      // React to session events
    },

    // Add custom tools
    "tool": {
      my_custom_tool: {
        description: "Does something useful",
        args: { /* ... */ },
        execute: async (args, ctx) => {
          // Tool implementation
        }
      }
    }
  };
};
```

See: https://opencode.ai/docs/plugins/

---

## Troubleshooting

**Plugin not loading?**
- Check OpenCode logs: `tail -f ~/jarvis-voice/logs/opencode/opencode-*.jsonl`
- Verify syntax: `node --check ~/.config/opencode/plugin/00-workspace-protection.js`
- Restart OpenCode server: `sudo systemctl restart opencode-jarvis.service`

**Plugin blocking valid operations?**
- Check the error message for specific reason
- Verify paths are absolute or relative to workspace
- Ensure operation is within `~/jarvis-workspace`

**Need to disable temporarily?**
- Rename: `mv 00-workspace-protection.js 00-workspace-protection.js.disabled`
- Restart OpenCode server

---

## Future Plugins (Ideas)

See: `~/jarvis-voice/docs/opencode/OPENCODE_PLUGIN_IDEAS.md`

Candidates:
- Docker sandbox for safe code execution
- Smart port allocation
- Environment file protection
- Web research tools
- Document processing tools

**Decision**: Start simple with safety, add complexity only when needed.

---

**Last Updated**: November 15, 2025
**Maintainer**: Jarvis Dev Team
**Architecture**: Jarvis (boss) → OpenCode (specialist) → Plugins (guardrails)
