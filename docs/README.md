# Jarvis Voice Assistant Documentation

## 📚 Core Documentation

### Getting Started
- **[QUICKSTART.md](QUICKSTART.md)** - Quick setup guide
- **[../config/README.md](../config/README.md)** - Configuration guide

### Main Features
- **[MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)** - Memory database with semantic search
- **[DUAL_DATABASE_SYSTEM.md](DUAL_DATABASE_SYSTEM.md)** - Cloud/local DB architecture (NEW)
- **[SEMANTIC_THRESHOLD_TUNING.md](SEMANTIC_THRESHOLD_TUNING.md)** - Tune search sensitivity (NEW)
- **[opencode/OPENCODE.md](opencode/OPENCODE.md)** - Autonomous coding agent
- **[TOOL_CALLING_SYSTEM.md](TOOL_CALLING_SYSTEM.md)** - Tool orchestration system
- **[TOOL_MANAGEMENT.md](TOOL_MANAGEMENT.md)** - Enable/disable tools (NEW)

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
./test-all-tools.sh
./test-all-tools-local.sh
./tests/integration/test-memory-tools.sh
./tests/integration/compare-models.sh local qwen3-vl qwen2.5:7b
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

## 📖 Full Documentation Index

### Memory System
| Document | Purpose |
|----------|---------|
| **MEMORY_SYSTEM.md** | Memory database architecture and tools |
| **DUAL_DATABASE_SYSTEM.md** | Cloud/local database with auto-sync (NEW) |
| **SEMANTIC_THRESHOLD_TUNING.md** | How to tune similarity threshold (NEW) |
| **MEMORY_SYSTEM_TUNING.md** | Advanced memory optimization |
| **MEMORY_INTELLIGENCE_FIXES.md** | Auto-save improvements |

### Tool System
| Document | Purpose |
|----------|---------|
| **TOOL_CALLING_SYSTEM.md** | Tool orchestration and routing |
| **TOOL_MANAGEMENT.md** | Enable/disable tools (NEW) |
| **MULTI_TURN_ORCHESTRATION.md** | Multi-turn tool chaining |
| **ERROR_RECOVERY.md** | Error handling and retries |

### OpenCode (Autonomous Coding)
| Document | Purpose |
|----------|---------|
| **opencode/OPENCODE.md** | Main OpenCode guide |
| **opencode/OPENCODE_API_REFERENCE.md** | Full API reference |
| **opencode/OPENCODE_AGENTS.md** | Agent system architecture |
| **opencode/OPENCODE_MEMORY_STRATEGY.md** | Memory integration |
| **opencode/OPENCODE_PERMISSIONS.md** | Permission system |
| **opencode/OPENCODE_PLUGINS.md** | Plugin system |

### Testing & Analysis
| Document | Purpose |
|----------|---------|
| **TESTING.md** | Comprehensive testing guide |
| **BASELINE_TOKEN_USAGE.md** | Token usage tracking |
| **../tests/README.md** | Test suite overview |

### Configuration & Setup
| Document | Purpose |
|----------|---------|
| **QUICKSTART.md** | Quick setup guide |
| **../config/README.md** | Configuration reference |
| **MCP_QUICKSTART.md** | MCP server setup |

### Advanced Features
| Document | Purpose |
|----------|---------|
| **PROMPT_CACHING.md** | Anthropic prompt caching |
| **EXTENDED_THINKING.md** | Extended thinking mode |
| **CASUAL_VS_DETAILED_MODE.md** | Response styles |
| **AUTO_MODE_EXPLAINED.md** | Auto formatting mode |
| **METADATA_SYSTEM.md** | Cost tracking and metadata |
| **VOICE_MODE_FIXES.md** | Voice mode improvements |

### Reference & Archives
| Document | Purpose |
|----------|---------|
| **COMPLETE_SYSTEM_SUMMARY.md** | System overview |
| **DATABASE_DEEP_DIVE.md** | Database evolution |
| **JARVIS_INTEL_SYSTEM.md** | Intel file ingestion |
| **FUTURE_ENHANCEMENTS.md** | Planned features |
| **archive/** | Historical docs and changelogs |

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
