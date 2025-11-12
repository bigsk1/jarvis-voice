# OpenCode Integration - Critical Refinements Summary

**Date**: 2025-11-11  
**Status**: Planning Complete - Ready for Implementation

---

## 🎯 **Key Concerns Addressed**

### 1. ✅ **Credential Security**
**Problem**: Don't store actual credentials in memory DB  
**Solution**: Store environment variable references only

```python
# Memory stores: {"service": "vercel", "env_var": "VERCEL_TOKEN"}
# Actual token: os.environ["VERCEL_TOKEN"] or config/cloud.env
```

**Benefits**:
- Credentials can be updated without touching memory DB
- No secrets in SQLite database
- Works with existing config system
- Secure injection into OpenCode via auth API

---

### 2. ✅ **Workspace Isolation**
**Problem**: Where does OpenCode build projects? Don't pollute jarvis-voice root  
**Solution**: Dedicated `~/jarvis-workspace/` with permission-based access

```
/home/boss/jarvis-workspace/
├── projects/
│   ├── websites/      # Full access for builds
│   ├── scripts/       # Utility scripts
│   └── experiments/   # Prototypes
├── temp/              # Auto-cleanup 24h
└── deployments/       # Ready artifacts
```

**Permission Matrix**:
- `build_website` → Can create/delete in `projects/websites/`
- `fix_bug` → Works in current git repo, can read Jarvis code
- `experiment` → Isolated in `temp/`, auto-cleanup
- `analyze_code` → Read-only anywhere

---

### 3. ✅ **Path Context Resolution**
**Problem**: "list Python files" - which directory?  
**Solution**: Intelligent multi-level resolution

**Priority Order**:
1. Explicit path in command ("list files in /path/to/project")
2. Current OpenCode session workspace
3. Recent conversation context
4. Shell working directory
5. Default to `~/jarvis-workspace`

**Examples**:
```bash
# After "build a portfolio"
"list the files" → ~/jarvis-workspace/projects/websites/portfolio

# Explicit
"list files in jarvis-voice" → /home/boss/jarvis-voice

# Conversational
"I'm working on my blog"  [context stored]
"show me the posts" → ~/jarvis-workspace/projects/blog
```

---

### 4. ✅ **Dynamic Model Selection**
**Problem**: Need cheaper models for simple tasks, powerful for complex  
**Solution**: Automatic complexity-based routing

**Model Strategy**:
- **Simple** ("list files", "what is X") → `gpt-4o` (fast/cheap)
- **Coding** ("build", "fix bug", "deploy") → `claude-3-5-sonnet-20241022` (optimal)
- **Complex** ("research", "analyze", "design") → `claude-sonnet-4-5-20250929` (powerful)

**User Override**: Can specify model explicitly if needed

---

### 5. ✅ **OpenCode Health Management**
**Problem**: Jarvis needs full control over OpenCode lifecycle  
**Solution**: Health checks + systemd service management

**Capabilities**:
- Check OpenCode server status
- Restart service automatically if unhealthy
- Query active sessions
- Monitor via `systemctl --user status opencode-jarvis`

---

### 6. ✅ **OpenCode Configuration Awareness**
**Problem**: Jarvis should know all OpenCode capabilities  
**Solution**: Fetch OpenAPI spec + query config dynamically

**Implementation**:
```python
# Get available providers
providers = opencode_client.config.providers()

# Fetch full API spec
spec = fetch("http://localhost:4096/doc")

# Check capabilities
sessions = opencode_client.session.list()
```

---

## 📋 **Setup Instructions**

### **Step 1: Create Workspace**
```bash
cd /home/boss/jarvis-voice
./setup_opencode_workspace.sh
```

This creates:
- `~/jarvis-workspace/` directory structure
- README files explaining usage
- Proper permissions

### **Step 2: Configure Credentials**
```bash
# Add to config/cloud.env or ~/.bashrc
export VERCEL_TOKEN="your_token_here"
export GITHUB_TOKEN="your_token_here"
export ANTHROPIC_API_KEY="your_key_here"
```

Then tell Jarvis:
```
"Hey Jarvis, remember my Vercel credentials are in VERCEL_TOKEN"
```

### **Step 3: Setup OpenCode Service** (Optional but recommended)
```bash
# Create systemd service
mkdir -p ~/.config/systemd/user/
cat > ~/.config/systemd/user/opencode-jarvis.service << 'EOF'
[Unit]
Description=OpenCode Server for Jarvis
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/boss/jarvis-voice
ExecStart=/home/boss/.opencode/bin/opencode serve --port 4096 --hostname 127.0.0.1
Restart=always

[Install]
WantedBy=default.target
EOF

# Enable and start
systemctl --user daemon-reload
systemctl --user enable opencode-jarvis
systemctl --user start opencode-jarvis

# Check status
systemctl --user status opencode-jarvis
```

---

## 🎯 **Updated Integration Flow**

### **Example: "Build me a blog and deploy to Vercel"**

```python
# 1. Router Decision
task_type = "build_website"
complexity = "complex"  # build + deploy

# 2. Workspace Setup
workspace = "/home/boss/jarvis-workspace/projects/websites/blog"
os.makedirs(workspace, exist_ok=True)

# 3. Credential Resolution
vercel_var = memory_db.recall("credentials.vercel")  # Returns "ENV:VERCEL_TOKEN"
vercel_token = os.environ["VERCEL_TOKEN"]

# 4. Model Selection
model = {
    "providerID": "anthropic",
    "modelID": "claude-sonnet-4-5-20250929"  # Complex task = best model
}

# 5. OpenCode Session
session = opencode.create_session(
    workspace=workspace,
    model=model
)

# 6. Inject Context (secure)
opencode.auth.set({
    "path": {"id": "vercel"},
    "body": {"type": "api", "key": vercel_token}
})

# 7. Execute
result = session.prompt("Build a blog with Next.js and deploy to Vercel")

# 8. Voice Response
speech = f"Your blog is live at {extract_url(result)}"
speak(speech)

# 9. Store Session
memory_db.store_opencode_session(
    session_id=session.id,
    workspace=workspace,
    result_summary=speech
)
```

---

## 🔒 **Security Model**

### **Credentials**
- ❌ **Never** in memory DB (plaintext)
- ✅ **Always** in environment variables or encrypted vault
- ✅ Memory stores **references** only: `"ENV:VARIABLE_NAME"`

### **Filesystem**
- Jarvis codebase: **Read-only** for OpenCode builds
- Workspace: **Full access** within permissions
- Other directories: **Conditional** based on task type

### **Permissions**
```python
PERMISSIONS = {
    "build_website": {
        "allowed_dirs": ["~/jarvis-workspace/projects/websites"],
        "can_create": True,
        "can_delete": True,
        "can_access_jarvis": False  # Can't modify Jarvis code
    },
    "fix_bug": {
        "allowed_dirs": ["$CURRENT_GIT_REPO"],
        "can_create": False,
        "can_delete": False,
        "can_access_jarvis": True  # Can read Jarvis for reference
    }
}
```

---

## 🧪 **Testing Scenarios**

### **Test 1: Credential Security**
```bash
# Setup
echo 'export TEST_TOKEN="secret123"' >> ~/.bashrc
./orchestrator.py cloud "Remember my test credentials are in TEST_TOKEN"

# Verify memory (should NOT contain "secret123")
sqlite3 data/jarvis_memory.db "SELECT * FROM knowledge_base WHERE key='test';"
# Should show: "ENV:TEST_TOKEN"

# Use credential
./orchestrator.py cloud "Use test credentials to make API call"
# Should work, but credential never logged
```

### **Test 2: Workspace Isolation**
```bash
# Build website
./orchestrator.py cloud "Build a test website"

# Verify location
ls ~/jarvis-workspace/projects/websites/test/
# Should exist

# Verify Jarvis untouched
git status /home/boss/jarvis-voice
# Should be clean
```

### **Test 3: Path Context**
```bash
# Set context
./orchestrator.py cloud "I'm working on my blog project"

# Follow-up without path
./orchestrator.py cloud "List the files"
# Should list: ~/jarvis-workspace/projects/blog/
```

### **Test 4: Model Selection**
```bash
# Simple task (should use cheap model)
./orchestrator.py cloud "List Python files" --show-model
# Expected: gpt-4o-mini

# Complex task (should use powerful model)
./orchestrator.py cloud "Build and deploy a website" --show-model
# Expected: claude-sonnet-4-5
```

---

## 📊 **Decision Matrix**

| Scenario | Workspace | Model | Permissions |
|----------|-----------|-------|-------------|
| "Build a website" | `projects/websites/` | Claude Sonnet 4.5 | Full create/delete |
| "List files" | Context-aware | GPT-4o-mini | Read-only |
| "Fix bug in Jarvis" | `/home/boss/jarvis-voice` | Claude 3.5 Sonnet | Modify current repo |
| "Test API call" | `temp/` (auto-cleanup) | GPT-4o-mini | Isolated temp |
| "Research topic" | N/A (web only) | Claude Sonnet 4.5 | No filesystem |

---

## 🎬 **Next Steps**

All concerns addressed! Ready to proceed with Phase 1 implementation:

1. ✅ Workspace structure defined
2. ✅ Credential security model designed
3. ✅ Path resolution strategy documented
4. ✅ Model selection logic specified
5. ✅ Permission system architected
6. ✅ Health management planned

**Proceed to**: `docs/OPENCODE_PLAN.md` Phase 1 implementation

---

## 📚 **Related Documents**

- [OPENCODE_PLAN.md](./OPENCODE_PLAN.md) - Full integration plan
- [OPENCODE_INTEGRATION_STATUS.md](./OPENCODE_INTEGRATION_STATUS.md) - Current status
- [MEMORY_SYSTEM.md](./MEMORY_SYSTEM.md) - Memory DB structure

---

**Summary**: All critical concerns addressed with secure, scalable solutions. System maintains Jarvis's simplicity while gaining OpenCode's power. Ready to build! 🚀
