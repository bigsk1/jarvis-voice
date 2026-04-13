# OpenCode Plugin Management Commands

Quick reference for managing OpenCode plugins with systemd service.

---

## ✅ Verify Plugin is Loaded

### Method 1: Check OpenCode Config (Best)
```bash
curl -s http://localhost:4096/config | jq -r '.plugin[]'
```

**Expected Output**:
```
file://~/.config/opencode/plugin/00-workspace-protection.js
```

### Method 2: Check Config with Full Details
```bash
curl -s http://localhost:4096/config | jq '.plugin'
```

### Method 3: Check if OpenCode is Running
```bash
systemctl status opencode-jarvis.service
```

---

## 🔄 Restart OpenCode Service

When you add/modify/remove plugins:

```bash
# Restart the service
sudo systemctl restart opencode-jarvis.service

# Check status
systemctl status opencode-jarvis.service

# Verify plugin loaded
curl -s http://localhost:4096/config | jq -r '.plugin[]'
```

---

## 📋 View OpenCode Logs

### Systemd Journal (Live Logs)
```bash
# Follow logs in real-time
sudo journalctl -u opencode-jarvis.service -f

# Last 50 lines
sudo journalctl -u opencode-jarvis.service -n 50

# Since specific time
sudo journalctl -u opencode-jarvis.service --since "5 minutes ago"
```

### OpenCode JSONL Logs (Tool Execution)
```bash
# Most recent log file
ls -lt ~/jarvis-voice/logs/opencode/*.jsonl | head -1

# View last 20 entries
tail -20 ~/jarvis-voice/logs/opencode/opencode-$(date +%Y-%m-%d).jsonl

# Watch for new entries (during testing)
tail -f ~/jarvis-voice/logs/opencode/opencode-$(date +%Y-%m-%d).jsonl
```

**Note**: Plugin `console.log()` messages go to systemd journal, not JSONL logs.  
JSONL logs are for OpenCode's internal events (session_start, message_sent, etc).

---

## 🧪 Test Plugin Protection

### Test 1: Verify Plugin Blocks Jarvis Code
```bash
./jarvis-local
```
Then say:
```
"Use OpenCode to edit the file orchestrator_v2.py"
```

**Expected**: ❌ Error message:
```
❌ BLOCKED: Cannot access Jarvis codebase
   Path: ~/jarvis-voice/orchestrator/orchestrator_v2.py
   Reason: ~/jarvis-voice is protected
```

### Test 2: Verify Plugin Blocks System Directories
```bash
./jarvis-local
```
Then say:
```
"Use OpenCode to create a test file at /etc/test.txt"
```

**Expected**: ❌ Error message:
```
❌ BLOCKED: Cannot access system directories
   Path: /etc/test.txt
   Reason: System directories are protected
```

### Test 3: Verify Plugin Allows Workspace
```bash
./jarvis-local
```
Then say:
```
"Use OpenCode to create a simple hello world Python script"
```

**Expected**: ✅ File created in `~/jarvis-workspace/`

---

## 📁 Plugin File Locations

### Global Plugin Directory
```bash
~/.config/opencode/plugin/
├── 00-workspace-protection.js  # Active plugin
└── README.md                    # Plugin docs
```

### View Plugin Code
```bash
cat ~/.config/opencode/plugin/00-workspace-protection.js
```

### Edit Plugin
```bash
nano ~/.config/opencode/plugin/00-workspace-protection.js

# Then restart service
sudo systemctl restart opencode-jarvis.service
```

---

## 🔌 Plugin Load Order

Plugins load alphabetically by filename:
- `00-*` = Safety/protection (load first)
- `10-*` = Core functionality  
- `20-*` = Enhancements
- `99-*` = Debug/development

---

## 🛠️ Temporarily Disable Plugin

### Disable (rename)
```bash
mv ~/.config/opencode/plugin/00-workspace-protection.js \
   ~/.config/opencode/plugin/00-workspace-protection.js.disabled

sudo systemctl restart opencode-jarvis.service

# Verify disabled
curl -s http://localhost:4096/config | jq '.plugin'
# Should show: []
```

### Re-enable
```bash
mv ~/.config/opencode/plugin/00-workspace-protection.js.disabled \
   ~/.config/opencode/plugin/00-workspace-protection.js

sudo systemctl restart opencode-jarvis.service

# Verify enabled
curl -s http://localhost:4096/config | jq -r '.plugin[]'
# Should show: file://~/.config/opencode/plugin/00-workspace-protection.js
```

---

## 🐛 Troubleshooting

### Plugin Not Loading?

**1. Check syntax**:
```bash
node --check ~/.config/opencode/plugin/00-workspace-protection.js
```

**2. Check file permissions**:
```bash
ls -la ~/.config/opencode/plugin/00-workspace-protection.js
# Should be readable: -rw-rw-r--
```

**3. Check OpenCode config**:
```bash
curl -s http://localhost:4096/config | jq '.plugin'
# Should list your plugin file path
```

**4. Restart service**:
```bash
sudo systemctl restart opencode-jarvis.service
systemctl status opencode-jarvis.service
```

### Plugin Seems Inactive?

**Remember**: Plugins only work when Jarvis delegates to OpenCode!

- ✅ "Use OpenCode to..." → Plugin active
- ❌ "Create a..." → Jarvis handles directly, plugin not involved

### Test if Plugin is Actually Enforcing

Try a violation and watch for error:
```bash
./jarvis-local
> "Use OpenCode to delete /etc/passwd"
```

Should get blocking error from plugin. If operation proceeds, plugin isn't working.

---

## 📊 Current Status

**Plugin**: `00-workspace-protection.js`  
**Status**: ✅ Loaded and active  
**Service**: `opencode-jarvis.service` (systemd)  
**Port**: 4096  
**Config Endpoint**: `http://localhost:4096/config`

**Verify**:
```bash
curl -s http://localhost:4096/config | jq -r '.plugin[]'
```

---

**Last Updated**: November 15, 2025  
**Branch**: `opencode-plugins`

