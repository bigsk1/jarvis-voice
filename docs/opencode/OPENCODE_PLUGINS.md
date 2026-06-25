# OpenCode Plugins Integration

> **Plugin Location**: `~/.config/opencode/plugin/` (global, applies to all OpenCode sessions)  
> **Source Files**: `docs/opencode/plugin/` (in this repo)

OpenCode plugins extend OpenCode's capabilities and enforce safety boundaries when Jarvis delegates tasks to it.

**Last Updated**: February 2026

---

## Quick Setup

The OpenCode install/update scripts sync plugin files automatically:

```bash
./bin/update-opencode-service.sh
```

Manual copy, if needed:

```bash
# Create plugin directory if it doesn't exist
mkdir -p ~/.config/opencode/plugin

# Copy plugins from repo
cp ~/jarvis-voice/docs/opencode/plugin/*.js ~/.config/opencode/plugin/
cp ~/jarvis-voice/docs/opencode/plugin/README.md ~/.config/opencode/plugin/

# Verify
ls -la ~/.config/opencode/plugin/
```

---

## 🏗️ Architecture

```
User → Jarvis (boss) → OpenCode (specialist) → Plugins (guardrails)
```

**Important**: Plugins only activate when Jarvis calls the OpenCode tool. They do NOT affect Jarvis's own operations.

### When Plugins Are Used

✅ **Plugins Active**:
```
User: "Jarvis, use OpenCode to build a Flask API"
      └─> Jarvis calls opencode.py tool
          └─> OpenCode executes with plugins loaded
```

❌ **Plugins NOT Active**:
```
User: "Jarvis, create a Flask API"
      └─> Jarvis uses execute_bash/other tools directly
          └─> OpenCode not involved, plugins don't run
```

---

## 🛡️ Installed Plugins

### 1. Workspace Protection (`00-workspace-protection.js`)
**Status**: ✅ Active  
**Purpose**: Enforce strict workspace boundaries

**Protection Rules**:
| What | Where | Action |
|------|-------|--------|
| Write/Edit/Delete | Outside `~/jarvis-workspace` | ❌ BLOCKED |
| Any Access | `~/jarvis-voice` (Jarvis code) | ❌ BLOCKED |
| Any Access | System dirs (`/etc`, `/usr`, `/bin`) | ❌ BLOCKED |
| Any Access | Sensitive dirs (`~/.ssh`, `~/.gnupg`) | ❌ BLOCKED |
| All Operations | Within `~/jarvis-workspace` | ✅ ALLOWED |

**Example Blocked Operation**:
```
User: "Jarvis, use OpenCode to edit orchestrator_v2.py"
Jarvis: Delegates to OpenCode
OpenCode: Attempts to edit ~/jarvis-voice/orchestrator/orchestrator_v2.py

❌ BLOCKED: Cannot access Jarvis codebase
   Path: ~/jarvis-voice/orchestrator/orchestrator_v2.py
   Reason: ~/jarvis-voice is protected (read-only from workspace only)
   
   If you need to understand Jarvis APIs, ask Jarvis to provide the information.
```

**Example Allowed Operation**:
```
User: "Jarvis, use OpenCode to build a Flask API"
Jarvis: Delegates to OpenCode
OpenCode: Creates files in ~/jarvis-workspace/projects/flask-api/

✅ ALLOWED: All operations within workspace
```

**Why Essential**:
- Prevents OpenCode from accidentally damaging Jarvis itself
- Critical for local models (Qwen) that may ignore system prompts
- Defense-in-depth security layer
- Protects against runaway code generation

---

## 📂 Plugin Directory Structure

```
~/.config/opencode/plugin/
├── 00-workspace-protection.js    # Safety enforcement (this branch)
├── README.md                      # Plugin documentation
└── (future plugins)
```

**Naming Convention**:
- `00-*`: Safety/protection (load first)
- `10-*`: Core functionality
- `20-*`: Enhancements
- `99-*`: Debug/development

---

## 🧪 Testing

### Test 1: Block Jarvis Code Modification
```bash
./jarvis-local
> "Use OpenCode to add a comment to orchestrator_v2.py"
```
**Expected**: ❌ Error message about protected Jarvis codebase

### Test 2: Block System Directory Access
```bash
./jarvis-local
> "Use OpenCode to create a file at /etc/test.txt"
```
**Expected**: ❌ Error message about protected system directory

### Test 3: Allow Workspace Operations
```bash
./jarvis-local
> "Use OpenCode to create a simple Python hello world script in the workspace"
```
**Expected**: ✅ File created in `~/jarvis-workspace/`

### Test 4: Verify Plugin Loaded
```bash
# Check OpenCode logs for plugin initialization
tail -f logs/opencode/opencode-*.jsonl | grep "Workspace Protection"
```
**Expected**: See "🛡️ Workspace Protection Plugin loaded" message

---

## 🔧 Plugin Management

### View Installed Plugins
```bash
ls -la ~/.config/opencode/plugin/
```

### Check Plugin Syntax
```bash
node --check ~/.config/opencode/plugin/00-workspace-protection.js
```

### Temporarily Disable Plugin
```bash
mv ~/.config/opencode/plugin/00-workspace-protection.js \
   ~/.config/opencode/plugin/00-workspace-protection.js.disabled
```

### Re-enable Plugin
```bash
mv ~/.config/opencode/plugin/00-workspace-protection.js.disabled \
   ~/.config/opencode/plugin/00-workspace-protection.js
```

**Note**: Restart OpenCode server after enabling/disabling plugins:
```bash
pkill -f opencode
./bin/start-opencode
```

---

## 📚 Plugin Development

For adding new plugins, see:
- **Ideas & Planning**: `docs/OPENCODE_PLUGIN_IDEAS.md` (comprehensive list)
- **OpenCode Docs**: https://opencode.ai/docs/plugins/
- **Plugin Examples**: `~/.config/opencode/plugin/README.md`

**Current Philosophy**:
- Start with safety (workspace protection)
- Add complexity only when needed
- Prefer Jarvis tools over OpenCode plugins when possible
- Keep plugins simple and focused

---

## 🐛 Troubleshooting

### Plugin Not Working?

**1. Check if plugin is loaded**:
```bash
tail -100 logs/opencode/opencode-*.jsonl | grep -i plugin
```

**2. Verify OpenCode is running**:
```bash
curl http://localhost:4096/health
```

**3. Check for JavaScript errors**:
```bash
node --check ~/.config/opencode/plugin/00-workspace-protection.js
```

**4. Restart OpenCode**:
```bash
pkill -f opencode
./bin/start-opencode
sleep 2
curl http://localhost:4096/health
```

### Plugin Blocking Valid Operations?

**Check the error message** - it will specify:
- What was blocked (tool + path)
- Why it was blocked (protection rule)
- What's allowed (workspace path)

**Common issues**:
- Using absolute paths outside workspace → Use relative paths or workspace root
- Trying to reference Jarvis code → Ask Jarvis to provide the info instead
- System directory access → Work within `~/jarvis-workspace`

---

## 🎯 Future Enhancements

See `docs/OPENCODE_PLUGIN_IDEAS.md` for detailed proposals.

**Candidates** (not implemented yet):
- Docker sandbox for safe code execution
- Smart port allocation with availability checks
- Enhanced telemetry and logging
- Web research tools (scraping, downloads)
- Document processing (PDF, OCR)
- Data analysis tools

**Decision**: Implement only when real-world usage demonstrates need.

---

## 📊 Git Branch

This plugin infrastructure was added in branch: `opencode-plugins`

**Files in Jarvis Repo**:
- `docs/OPENCODE_PLUGINS.md` (this file)
- `docs/OPENCODE_PLUGIN_IDEAS.md` (comprehensive ideas list)

**Files Outside Jarvis Repo** (global OpenCode config):
- `~/.config/opencode/plugin/00-workspace-protection.js`
- `~/.config/opencode/plugin/README.md`

---

## 🔗 Related Documentation

- `docs/OPENCODE.md` - OpenCode integration overview
- `docs/OPENCODE_API_REFERENCE.md` - API endpoints and usage
- `docs/OPENCODE_AGENTS.md` - Multi-agent coordination
- `docs/OPENCODE_PLUGIN_IDEAS.md` - Future plugin ideas
- `skills/opencode.py` - Jarvis's OpenCode tool implementation

---

**Architecture Reminder**: Jarvis is the boss, OpenCode is the specialist, plugins are the guardrails. Information flows up, decisions flow down.
