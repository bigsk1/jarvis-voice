# Jarvis Voice Assistant

A self-hosted, intelligent voice assistant with advanced tool calling, memory, and autonomous coding capabilities.

---

## 🎯 Current Status (November 2025)

**Production Ready** ✅
- Multi-turn tool orchestration with LLM routing
- 17+ working skills (memory, bash, OpenCode, API calls, etc.)
- **Dual database system** with auto-sync (cloud ↔ local)
- **Intelligent memory** with semantic search + configurable thresholds
- OpenCode integration for autonomous coding tasks
- **Tool management** system (enable/disable per mode)
- **Model comparison framework** for testing different LLMs
- MCP server support for extensibility
- Cost tracking and metadata logging
- Dual mode operation (cloud/local)

---

## ✨ Key Features

### Intelligence & Tools
- **Advanced Tool Calling**: LLM-powered routing with 20+ skills
- **Multi-Turn Orchestration**: Chains multiple tools to complete complex tasks
- **Intelligent Memory**: Semantic search + conversation history with auto-save
- **OpenCode Integration**: Autonomous coding agent for building projects
- **MCP Support**: Extensible via Model Context Protocol servers

### Memory System
- **Dual Database**: Separate DBs for cloud (OpenAI embeddings) and local (nomic embeddings)
- **Auto-Sync**: Bidirectional sync between modes on startup
- **Knowledge Base**: Facts, preferences, technical info with embeddings
- **Conversation History**: Full logging with metadata (cost, tokens, model)
- **Semantic Search**: AI embeddings with configurable similarity threshold (tune via .env)
- **Auto-Save**: Automatically remembers project locations, commands, solutions
- **Tool Management**: Enable/disable tools per mode to optimize context window

### Dual Mode Operation
- **Cloud Mode**: Anthropic Claude / OpenAI GPT (more powerful, costs money)
- **Local Mode**: Ollama (qwen3-vl) + faster-whisper + Kokoro TTS (free, offline)

### Voice & Wake Word
- **Wake Detection**: "Hey Jarvis" using OpenWakeWord
- **Fine-tuned Audio**: Optimized for noisy environments + far-field mic
- **Smart Response Formatting**: Auto-condenses verbose outputs for voice

---

## 📁 Project Structure

```
jarvis-voice/
├── bin/                      # Executable scripts & utilities
│   ├── wake_jarvis.py        # Cloud wake word loop
│   ├── wake_jarvis_local.py  # Local wake word loop
│   ├── say.sh / say-local.sh # Text-to-speech
│   ├── question*.sh          # Q&A entry points
│   ├── memory                # Memory CLI tool
│   ├── manage-tools.py       # Enable/disable tools
│   ├── sync-memory-db.py     # Manual database sync
│   └── setup-memory-db.sh    # Initialize databases
├── lib/                      # Core libraries
│   ├── config_loader.py      # Configuration management
│   ├── memory_db.py          # SQLite memory system
│   ├── llm_provider.py       # LLM provider abstraction
│   ├── opencode_client.py    # OpenCode API client
│   ├── cost_estimator.py     # Token cost calculation
│   └── local_model_corrections.py # Post-processing for local models
├── orchestrator/             # Tool orchestration system
│   ├── orchestrator_v2.py    # Main orchestration logic
│   ├── router_v2.py          # LLM-based routing
│   ├── executor.py           # Tool execution engine
│   └── tool_schema.py        # Tool discovery & validation
├── skills/                   # Tool scripts (20+)
│   ├── remember.py           # Store facts
│   ├── recall.py             # Retrieve facts
│   ├── search_memory.py      # Keyword search
│   ├── semantic_recall.py    # AI-powered search
│   ├── get_recent_conversations.py # Conversation history
│   ├── execute_bash.py       # Shell command execution
│   ├── opencode.py           # Autonomous coding agent
│   ├── check_opencode_sessions.py # OpenCode progress monitoring
│   ├── send_webhook.py       # HTTP requests
│   ├── api_call.py           # Generic API calls
│   ├── crypto_price.py       # Crypto prices
│   ├── ingest_intel.py       # Bulk knowledge import
│   └── *.tool.json           # Tool definitions
├── config/                   # Configuration files
│   ├── cloud.env             # Cloud mode settings
│   ├── local.env             # Local mode settings
│   ├── cloud.env.example     # Template (safe for git)
│   ├── local.env.example     # Template (safe for git)
│   └── README.md             # Config documentation
├── data/                     # Runtime data
│   ├── jarvis_memory.db      # Cloud mode database (OpenAI embeddings)
│   └── jarvis_memory_local.db # Local mode database (nomic embeddings)
├── logs/                     # Execution logs
│   ├── tools/                # Tool call logs
│   └── opencode/             # OpenCode session logs
├── tests/                    # Test suites
│   ├── integration/          # Integration tests
│   │   ├── compare-models.sh # Model comparison framework
│   │   ├── test-memory-*.sh  # Memory system tests
│   │   └── logs/             # Test results and analysis
│   ├── e2e/                  # End-to-end tests (future)
│   └── unit/                 # Unit tests (future)
├── docs/                     # Documentation (see below)
├── jarvis-intel/             # Private knowledge base (gitignored)
├── jarvis                    # Launcher (cloud mode)
├── jarvis-local              # Launcher (local mode)
├── test-all-tools.sh         # Run all tool tests (cloud)
├── test-all-tools-local.sh   # Run all tool tests (local)
└── README.md                 # This file
```

---

## 🚀 Quick Start

### 1. Initial Setup

```bash
cd /home/boss/jarvis-voice
./setup.sh
```

This will:
- Check dependencies
- Create directories
- Initialize git repository
- Create convenience symlinks

### 2. Configure

Copy and edit the example configs:

```bash
# For cloud mode (Anthropic/OpenAI)
cp config/cloud.env.example config/cloud.env
nano config/cloud.env  # Add your ANTHROPIC_API_KEY

# For local mode (Ollama)
cp config/local.env.example config/local.env
nano config/local.env  # Adjust Ollama endpoint
```

See `config/README.md` for detailed configuration options.

### 3. Install Dependencies

```bash
# Python environment
python3 -m venv ~/jarvis-venv
source ~/jarvis-venv/bin/activate
pip install -r requirements.txt

# System packages (Ubuntu/Debian)
sudo apt install sox ffmpeg jq sqlite3

# Ollama (for local mode)
curl https://ollama.ai/install.sh | sh
ollama pull qwen3-vl
ollama pull nomic-embed-text

# OpenCode (optional, for coding tasks)
# See docs/OPENCODE.md for installation
```

### 4. Run Jarvis

```bash
source ~/jarvis-venv/bin/activate

# Cloud mode (Anthropic Claude)
./jarvis

# Local mode (Ollama)
./jarvis-local

# CLI mode (no voice)
./orchestrator/orchestrator_v2.py cloud "What time is it?"
./orchestrator/orchestrator_v2.py local "What time is it?"
```

Say **"Hey Jarvis"** to wake it up!

---

## 🛠️ Tool System

### Available Skills (20+)

**Memory Management:**
- `remember` - Store facts, preferences, technical info
- `recall` - Retrieve specific memories by category/key
- `search_memory` - Keyword search across knowledge base
- `semantic_recall` - AI-powered conceptual search
- `update_memory` - Modify existing memories
- `forget` - Delete memories
- `get_recent_conversations` - Access conversation history
- `search_conversations` - Search past interactions

**Action Tools:**
- `execute_bash` - Run shell commands
- `send_webhook` - HTTP POST requests
- `api_call` - Generic HTTP API calls
- `crypto_price` - Get cryptocurrency prices
- `get_time` - Current time

**Development:**
- `opencode` - Autonomous coding agent (builds apps, games, APIs)
- `check_opencode_sessions` - Monitor OpenCode progress
- `ingest_intel` - Bulk import knowledge from markdown files
- `check_tool_logs` - View tool execution history

**System:**
- MCP servers (DuckDuckGo search, web fetch, etc.)

### How Tool Calling Works

```
User: "Build a Flask API and test it"
  ↓
LLM Router: Analyzes request
  ↓
Turn 1: Call 'opencode' → Build Flask API
  ↓
Turn 2: Call 'api_call' → Test endpoint
  ↓
Turn 3: Q&A response → "Flask API running on port 8091"
```

**Features:**
- Multi-turn orchestration (chains tools automatically)
- Error recovery with retries
- Timeout handling
- Cost tracking (cloud mode)
- Metadata logging
- Permission system

### Managing Tools (Enable/Disable)

Control which tools are loaded to optimize context window and performance:

```bash
# List all tools and their status
./bin/manage-tools.py list

# Disable a tool
./bin/manage-tools.py disable crypto_price

# Enable a tool
./bin/manage-tools.py enable crypto_price

# Enable all tools
./bin/manage-tools.py enable-all

# Disable multiple tools for local mode (reduce context)
./bin/manage-tools.py disable opencode check_opencode_sessions ingest_intel
```

**Benefits:**
- Reduce token count for local models (Ollama has smaller context windows)
- Create tool profiles (development vs. production)
- Disable experimental/buggy tools without deleting code
- All tools auto-discovered on startup (only enabled ones load)

See `docs/TOOL_MANAGEMENT.md` for details.

---

## 🧠 Memory System

### Knowledge Base

Stores facts, preferences, and technical information with semantic search:

```bash
# Store a fact
"Remember my WireGuard VPN is 192.168.70.0/24"

# Retrieve later (uses semantic search automatically)
"What's my VPN network?"  # Finds it via AI embeddings

# View all memories
./bin/memory list

# Tune semantic search sensitivity (in config/cloud.env or local.env)
SEMANTIC_SIMILARITY_THRESHOLD=0.40  # Default: 0.40 (balanced)
# Lower (0.30-0.35) = more results, may include loosely related
# Higher (0.45-0.50) = fewer results, only close matches
```

See `docs/SEMANTIC_THRESHOLD_TUNING.md` for optimization guide.

### Auto-Save Intelligence

Jarvis automatically remembers:
- ✅ Project locations and run commands (after OpenCode builds)
- ✅ Working solutions (port conflicts, config changes)
- ✅ URLs and endpoints you create/use
- ✅ Technical facts from intel files
- ❌ Ephemeral data (current time, transient prices)

### Conversation History

Full conversation logging with metadata:
- User queries and responses
- Tools used per session
- Model, tokens, and cost tracking
- Session IDs for grouping

---

## 🤖 OpenCode Integration

OpenCode is an autonomous coding agent that can build entire projects.

### Usage

```bash
# Via voice
"Use OpenCode to create a Flask API on port 8091"

# Via CLI
./orchestrator/orchestrator_v2.py cloud "Build a Tetris game"
```

### What OpenCode Can Do

- Build web apps (Flask, Express, React)
- Create games (Tetris, Snake, etc.)
- Write scripts and tools
- Install dependencies
- Test and verify builds

### Configuration

```bash
# In cloud.env or local.env
OPENCODE_MODEL="claude-sonnet-4-20250514"  # Or qwen2.5-coder:32b
OPENCODE_PROVIDER="anthropic"              # Or ollama
OPENCODE_BASE_URL="http://localhost:4096"
```

**Workspace:** All OpenCode projects go to `~/jarvis-workspace/projects/`

See `docs/OPENCODE.md` for details.

---

## 💾 Database & Costs

### Memory Database (Dual System)

Jarvis uses separate databases for cloud and local modes:

**Cloud Mode** - `data/jarvis_memory.db`:
- Uses OpenAI embeddings (1536 dimensions)
- Optimized for Claude/GPT

**Local Mode** - `data/jarvis_memory_local.db`:
- Uses nomic-embed-text (768 dimensions)
- Optimized for Ollama models

**Auto-Sync**: On startup, newer memories are synced between databases with re-embedded vectors for the target mode's model. See `docs/DUAL_DATABASE_SYSTEM.md`.

**Tables**:
- `knowledge_base` - Facts, preferences, embeddings
- `conversations` - Full conversation history with metadata

### Cost Tracking (Cloud Mode)

Every conversation logs:
- Model used
- Input/output tokens
- Cost in USD
- Tool count
- Execution time

View costs:
```bash
sqlite3 data/jarvis_memory.db "
SELECT 
  date(timestamp) as date,
  SUM(json_extract(metadata, '$.cost_usd')) as total_cost,
  COUNT(*) as conversations
FROM conversations
GROUP BY date(timestamp)
ORDER BY date DESC
LIMIT 7;"
```

---

## 📚 Documentation

### Key Documents

**Getting Started:**
- `config/README.md` - Configuration guide
- `docs/QUICKSTART.md` - Quick setup guide
- `docs/TOOL_CALLING_SYSTEM.md` - How tools work

**Memory System (Updated Nov 2025):**
- `docs/DUAL_DATABASE_SYSTEM.md` - **NEW**: Cloud/local DB architecture with auto-sync
- `docs/SEMANTIC_THRESHOLD_TUNING.md` - **NEW**: How to tune similarity threshold
- `docs/MEMORY_SYSTEM.md` - Memory & knowledge base overview
- `docs/MEMORY_SYSTEM_TUNING.md` - Memory system optimization
- `docs/MEMORY_INTELLIGENCE_FIXES.md` - Auto-save improvements

**Tool Management:**
- `docs/TOOL_MANAGEMENT.md` - Enable/disable tools, create profiles
- `docs/TOOL_CALLING_SYSTEM.md` - How tool system works

**Features:**
- `docs/OPENCODE.md` - OpenCode integration
- `docs/MULTI_TURN_ORCHESTRATION.md` - How tool chaining works
- `docs/METADATA_SYSTEM.md` - Cost tracking & metadata

**Advanced:**
- `docs/OPENCODE_API_REFERENCE.md` - Full OpenCode API
- `docs/MCP_QUICKSTART.md` - MCP server integration
- `docs/ERROR_RECOVERY.md` - Error handling

**Testing:**
- `tests/integration/compare-models.sh` - Model comparison framework
- `tests/integration/test-memory-tools.sh` - Memory tool selection tests
- `tests/integration/test-memory-real-world.sh` - Complex scenario tests

### Historical/Reference Docs

The following docs are kept for historical context but describe features that have been deprecated or improved:
- `CHANGELOG_2025-11-14.md` - Detailed change log
- `DATABASE_DEEP_DIVE.md` - Database evolution (mentions removed tables)
- `FIXES_2025-11-14.md` - Bug fix details
- `METADATA_POPULATION_STATUS.md` - Metadata implementation tracking

---

## 🔧 Development

### Adding a New Tool

1. **Create the tool script:**
   ```bash
   nano skills/my_tool.py
   ```

2. **Follow the standard interface:**
   ```python
   #!/usr/bin/env python3
   import sys
   import json
   
   def main():
       args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
       
       # Your logic here
       result = do_something(args)
       
       # Return JSON
       print(json.dumps({
           "ok": True,
           "speech": "Task completed",
           "data": result
       }))
   
   if __name__ == "__main__":
       main()
   ```

3. **Create tool definition:**
   ```bash
   nano skills/my_tool.tool.json
   ```
   ```json
   {
     "name": "my_tool",
     "description": "What the tool does",
     "input_schema": {
       "type": "object",
       "properties": {
         "param": {"type": "string", "description": "Parameter description"}
       },
       "required": ["param"]
     }
   }
   ```

4. **Make it executable:**
   ```bash
   chmod +x skills/my_tool.py
   ```

5. **Test it:**
   ```bash
   ./orchestrator/orchestrator_v2.py cloud "use my_tool with X"
   ```

The tool will be auto-discovered!

### Testing

```bash
# Test all tools (cloud)
./test-all-tools.sh

# Test all tools (local)
./test-all-tools-local.sh

# Test memory system (principle-based)
./tests/integration/test-memory-tools.sh

# Test real-world complex scenarios
./tests/integration/test-memory-real-world.sh

# Compare two models side-by-side (creates backups!)
./tests/integration/compare-models.sh local qwen3-vl qwen2.5:7b
./tests/integration/compare-models.sh cloud claude-sonnet-4-5 gpt-4o

# Test specific tool
./orchestrator/orchestrator_v2.py cloud "remember test fact"
```

**Note**: The model comparison script backs up your database before testing. Results are saved to `tests/integration/logs/` with AI-generated analysis.

### Git Workflow

```bash
# Create feature branch
git checkout -b feature/new-tool

# Make changes and test
./jarvis  # Test thoroughly

# Commit
git add skills/new_tool.py skills/new_tool.tool.json
git commit -m "Add new_tool for X"

# Merge to main
git checkout master
git merge feature/new-tool

# Rollback if needed
git reset --hard HEAD~1
```

---

## 🐛 Troubleshooting

### Common Issues

**"OpenCode server not reachable"**
```bash
systemctl --user start opencode
# or
cd ~/opencode && npm start
```

**"Ollama connection failed"**
```bash
curl http://192.168.70.226:11434
ollama serve
```

**"Model not found"**
```bash
ollama pull qwen3-vl
ollama pull nomic-embed-text
```

**"Permission denied on skills/tool.py"**
```bash
chmod +x skills/*.py
```

**Database issues**
```bash
# Check database
sqlite3 data/jarvis_memory.db ".tables"

# Backup before experiments
cp data/jarvis_memory.db data/jarvis_memory.db.backup
cp data/jarvis_memory_local.db data/jarvis_memory_local.db.backup

# Manual sync between cloud and local databases
./bin/sync-memory-db.py cloud  # Sync from local → cloud
./bin/sync-memory-db.py local  # Sync from cloud → local

# Restore from backup (after compare-models.sh tests)
mv data/jarvis_memory_local.db.backup-compare-models data/jarvis_memory_local.db
```

### Logs

Check logs for debugging:
```bash
# Tool execution logs
cat logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl

# OpenCode logs
cat logs/opencode/opencode-$(date +%Y-%m-%d).jsonl

# View recent tool calls
./orchestrator/orchestrator_v2.py cloud "show recent tool logs"
```

---

## 🎯 Roadmap

**Completed (November 2025):**
- ✅ Multi-turn tool orchestration
- ✅ Intelligent memory system with semantic search
- ✅ **Dual database system** (cloud/local with auto-sync)
- ✅ **Tool management** (enable/disable per mode)
- ✅ **Model comparison framework** with AI analysis
- ✅ **Configurable semantic threshold** tuning
- ✅ OpenCode integration
- ✅ Cost tracking and metadata logging
- ✅ MCP server support
- ✅ Auto-save intelligence
- ✅ Conversation history

**In Progress:**
- Voice mode improvements
- Additional MCP servers
- Performance optimization for local models

**Planned:**
- Web UI for memory management
- Scheduled tasks / cron integration
- Home automation tools
- Multi-user support
- Voice command customization

---

## 📝 License

Private project - Not licensed for public use.

---

## 🙏 Acknowledgments

- **OpenAI** - GPT, Whisper, TTS
- **Anthropic** - Claude (primary LLM)
- **Ollama** - Local LLM inference
- **OpenWakeWord** - Wake word detection
- **OpenCode** - Autonomous coding agent

---

**Current Version:** v2.1 (November 2025)  
**Status:** Production Ready ✅  
**Latest Features:** Dual database system, tool management, model comparison framework
