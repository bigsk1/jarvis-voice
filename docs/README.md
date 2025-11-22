# Jarvis Voice Assistant Documentation

## 📚 Core Documentation

### Getting Started
- **[JARVIS_WORKFLOW.md](JARVIS_WORKFLOW.md)** - 🆕 **Complete workflow guide with visual flowcharts** (START HERE!)
- **[QUICKSTART.md](QUICKSTART.md)** - Quick setup guide
- **[../config/README.md](../config/README.md)** - Configuration guide
- **[XAI_PROVIDER.md](XAI_PROVIDER.md)** - 🆕 **xAI Grok provider** (2M context, 10-15x cheaper!) ⭐ RECOMMENDED

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
# Cloud mode (xAI/Anthropic/OpenAI) - Recommended: xAI Grok
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
| **FTS5_SEARCH_SYSTEM.md** | FTS5 full-text search with BM25 ranking ⭐ NEW |
| **DUAL_DATABASE_SYSTEM.md** | Cloud/local database with auto-sync |
| **SEMANTIC_THRESHOLD_TUNING.md** | How to tune similarity threshold |
| **MEMORY_SYSTEM_TUNING.md** | Advanced memory optimization |
| **MEMORY_INTELLIGENCE_FIXES.md** | Auto-save improvements |

### Tool System
| Document | Purpose |
|----------|---------|
| **TOOL_RAG_STRATEGY.md** | Tool RAG system - Dynamic tool retrieval ⭐ NEW |
| **TOOL_RAG_IMPLEMENTATION_SUMMARY.md** | Tool RAG implementation details ⭐ NEW |
| **TOOL_RAG_TROUBLESHOOTING.md** | Tool RAG debugging guide ⭐ NEW |
| **TEST_SCRIPT_TOOL_RAG_FIX.md** | Test script integration fixes ⭐ NEW |
| **TOOL_CALLING_SYSTEM.md** | Tool orchestration and routing |
| **TOOL_MANAGEMENT.md** | Enable/disable tools |
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
| **COMPREHENSIVE_TESTING.md** | Burn test suite for all features ⭐ NEW |
| **TESTING.md** | Comprehensive testing guide |
| **BASELINE_TOKEN_USAGE.md** | Token usage tracking |
| **../tests/README.md** | Test suite overview |

### System Understanding
| Document | Purpose |
|----------|---------|
| **JARVIS_WORKFLOW.md** | Complete workflow with visual flowcharts |
| **AUTO_CONTEXT_SYSTEM.md** | Short-term conversation memory ⭐ NEW |
| **CONVERSATION_STATE_ARCHITECTURE.md** | State management between cycles ⭐ NEW |
| **api/READY_TO_USE.md** | Proactive API (Phase 1 COMPLETE) - Webhook system for alerts |
| **api/PROACTIVE_ASSISTANT_SYSTEM.md** | Full architecture (5 phases, Phase 1 done) |
| **COMPLETE_SYSTEM_SUMMARY.md** | System overview |

### Configuration & Setup
| Document | Purpose |
|----------|---------|
| **QUICKSTART.md** | Quick setup guide |
| **../config/README.md** | Configuration reference |
| **MCP_QUICKSTART.md** | MCP server setup |
| **MCP_NAMING_CONVENTIONS.md** | MCP snake_case requirements ⭐ NEW |
| **MCP_REGRESSION_FIX.md** | MCP parsing architecture ⭐ NEW |

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

**2025-11-22:**
- ✅ **Tool RAG System** - Dynamic tool retrieval using vector embeddings for infinite scalability
  - Loads only relevant tools per query (5-15 tools instead of all 32+)
  - Vector-based semantic search with configurable similarity threshold
  - "Ghost tools" pattern for always-available core functionality
  - Optimized for local models (smaller context windows)
  - See: `docs/TOOL_RAG_STRATEGY.md`, `docs/TOOL_RAG_IMPLEMENTATION_SUMMARY.md`
- ✅ **Enhanced error propagation** - LLM now receives full error details from failed tools for self-healing
- ✅ **Test script Tool RAG integration** - All test scripts auto-sync tool embeddings after DB cleanup
- ✅ **Tool RAG debugging utilities** - `debug_tool_rag.py` for comprehensive retrieval analysis

**2025-11-21:**
- ✅ **Randomized wake word greetings** - Dynamic greeting selection for personality
- ✅ **Proactive reminder guard** - Prevents unprompted reminder checks by local models
- ✅ **Voice timeout system** - 30-second hard timeout for recording to handle noisy environments
- ✅ **Samantha OS personality** - Added support for custom AI personalities with TTS instructions

**2025-11-20:**
- ✅ **FTS5 Full-Text Search** - SQLite FTS5 with BM25 ranking for faster, more accurate searches
- ✅ **Levenshtein fuzzy matching** - Typo-tolerant reminder cancellation
- ✅ **Generic LLM prompting** - Removed hardcoded examples to improve universal understanding
- ✅ **Configurable Ollama context** - `OLLAMA_CONTEXT_WINDOW` now in `local.env`
- ✅ **MCP snake_case enforcement** - Fixed regression with MCP server name parsing
- ✅ **Comprehensive burn test** - Single modular test suite for all features (`tests/comprehensive_test.py`)
- ✅ **Intel ingestion improvements** - Better fact extraction from prose and headers

**2025-11-19:**
- ✅ **Auto-context system** - Short-term conversation memory across wake word cycles
- ✅ **Temperature control** - Dynamic LLM creativity settings (casual vs detailed modes)
- ✅ **Camera bridge integration** - Ubiquiti Protect webhook middleware (Dockerized)
- ✅ **Fuzzy reminder cancellation** - Cancel reminders by partial title match with safety checks

**2025-11-18:**
- ✅ **Natural language time parsing** - Word numbers ("one hour") and special times ("noon", "midnight")
- ✅ **Enhanced tool descriptions** - Better LLM routing with explicit use cases
- ✅ **Conversation context improvements** - Fixed temporal vs topic-based query routing

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
