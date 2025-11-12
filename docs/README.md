# Jarvis Voice Assistant Documentation

## 📚 Core Documentation

### Main Docs
- **[MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)** - Intelligent memory database with semantic search
- **[TESTING.md](TESTING.md)** - Comprehensive testing guide
- **[OPENCODE.md](OPENCODE.md)** - OpenCode autonomous agent integration ⭐ NEW

### System Architecture
- **Tool system** - Located in `skills/` directory with JSON schemas
- **Orchestrator** - `orchestrator/orchestrator_v2.py` - Main routing logic
- **MCP Integration** - External tools via Model Context Protocol

## 🚀 Quick Start

```bash
# Cloud mode (OpenAI/Anthropic)
./jarvis

# Local mode (Ollama)
./jarvis-local

# Run tests
./tests/integration/test-all-tools.sh
./tests/integration/test-all-tools-local.sh
./tests/integration/test-opencode-integration.sh
```

## 🛠️ Key Features

**Memory System:**
- Semantic search with embeddings
- Auto-remembers important info
- Self-manages (edit/delete old data)

**OpenCode Integration:**
- Autonomous coding agent
- Workspace-isolated (`~/jarvis-workspace`)
- Systemd service for reliability

**Tool Ecosystem:**
- Local tools (time, crypto, memory, bash, etc.)
- MCP servers (web search, fetch, etc.)
- OpenCode (complex tasks)

## 📖 Documentation Index

| Document | Purpose | Audience |
|----------|---------|----------|
| **MEMORY_SYSTEM.md** | Memory DB architecture | Developers |
| **TESTING.md** | How to test Jarvis | Users & Developers |
| **OPENCODE.md** | OpenCode integration guide | All Users |
| **FUTURE_ENHANCEMENTS.md** | Planned features | Contributors |

## 🔧 Configuration

**Main config files:**
- `config/cloud.env` - Cloud mode (OpenAI, Anthropic)
- `config/local.env` - Local mode (Ollama)
- `~/.config/opencode/opencode.json` - OpenCode config

**Key environment variables:**
- `LLM_PROVIDER` - openai | anthropic | ollama
- `JARVIS_RESPONSE_STYLE` - casual | detailed
- `OPENCODE_ENABLED` - true | false

## 📊 System Overview

```
YOU (voice)
    ↓
JARVIS (wake word detection)
    ↓
ORCHESTRATOR (routing)
    ├─→ Local Tools (time, memory, crypto, etc.)
    ├─→ MCP Servers (web search, fetch)
    └─→ OpenCode (complex coding tasks)
        ↓
    Response (natural language)
    ↓
YOU (hear result)
```

## 🧪 Testing

```bash
# Test all tools (cloud)
./tests/integration/test-all-tools.sh

# Test all tools (local)
./tests/integration/test-all-tools-local.sh

# Test OpenCode
./tests/integration/test-opencode-integration.sh

# Check logs
./bin/tool-logs
./bin/opencode-logs
```

## 🐛 Troubleshooting

**Check health:**
```bash
# Jarvis tools
./orchestrator/orchestrator_v2.py cloud "what time is it?"

# OpenCode
systemctl status opencode-jarvis.service
curl http://localhost:4096/health

# Logs
tail -f logs/tools/tool-calls-*.jsonl
./bin/opencode-logs --verbose
```

## 🤝 Contributing

1. Read relevant docs (MEMORY_SYSTEM.md, OPENCODE.md, etc.)
2. Follow code style in `AGENTS.md` (root)
3. Add tests for new features
4. Update documentation

## 📝 Change Log

**2025-11-11:**
- ✅ OpenCode integration complete
- ✅ Workspace isolation enforced
- ✅ Detailed logging system
- ✅ Documentation consolidated (9 → 1 doc)

**2025-11-10:**
- ✅ Memory system with semantic search
- ✅ Natural language responses
- ✅ MCP server integration

---

**Need help?** Check the relevant doc above or run the integration tests to verify your setup.
