# Jarvis Documentation

Welcome to the Jarvis documentation! This folder contains all guides and references for the Jarvis voice assistant system.

## 📚 Documentation Index

### Getting Started
- **[QUICKSTART.md](QUICKSTART.md)** - Installation and first-time setup
- **[TOOL_CALLING_SYSTEM.md](TOOL_CALLING_SYSTEM.md)** - How Jarvis tools work

### Feature Guides
- **[MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)** - Using Jarvis memory and database management
- **[MCP_QUICKSTART.md](MCP_QUICKSTART.md)** - Setting up MCP servers for web search and more
- **[ERROR_RECOVERY.md](ERROR_RECOVERY.md)** - How Jarvis handles errors and retries

### Testing & Development
- **[TESTING.md](TESTING.md)** - Comprehensive testing guide for all tools and features
- **[FUTURE_ENHANCEMENTS.md](FUTURE_ENHANCEMENTS.md)** - Roadmap and planned features

## 🎯 Quick Links by Use Case

### I want to...

**Get started with Jarvis**
→ Read [QUICKSTART.md](QUICKSTART.md)

**Understand how tools work**
→ Read [TOOL_CALLING_SYSTEM.md](TOOL_CALLING_SYSTEM.md)

**Enable web search**
→ Read [MCP_QUICKSTART.md](MCP_QUICKSTART.md)

**Use and manage memory**
→ Read [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)

**Test all functionality**
→ Read [TESTING.md](TESTING.md)

**See what's coming next**
→ Read [FUTURE_ENHANCEMENTS.md](FUTURE_ENHANCEMENTS.md)

**Debug an error**
→ Read [ERROR_RECOVERY.md](ERROR_RECOVERY.md)

## 🏗️ System Architecture

```
┌─────────────────────────────────────────┐
│          Voice Interface                 │
│  (Wake Word → STT → TTS)                │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│       Orchestrator v2                    │
│  • Router (LLM-based intent detection)  │
│  • Executor (tool execution)            │
│  • Response Formatter                    │
└──────────────┬──────────────────────────┘
               │
      ┌────────┴────────┐
      │                 │
┌─────▼──────┐   ┌─────▼──────┐
│Local Tools │   │ MCP Tools  │
│• Time      │   │• Web Search│
│• Crypto    │   │• URL Fetch │
│• Bash      │   └────────────┘
│• API       │
│• Memory    │
└────────────┘
      │
┌─────▼──────┐
│  Database  │
│• Memories  │
│• Logs      │
└────────────┘
```

## 🔑 Key Concepts

### Tools
Self-contained scripts that Jarvis can execute. Each tool has:
- Schema (`.tool.json`) - defines parameters and description
- Script (`.py`, `.sh`) - performs the actual work
- Permissions - controls what the tool can do

### MCP Servers
External Docker containers that provide additional tools via the Model Context Protocol. Currently integrated:
- DuckDuckGo (web search)
- Fetch (URL content)

### Memory System
SQLite database that stores:
- **Knowledge Base** - Facts, preferences, instructions
- **Conversations** - Full interaction history
- **Embeddings** - Vector representations for semantic search

### Response Styles
How Jarvis formats output:
- **Casual** - Natural conversation, voice-optimized (default)
- **Detailed** - Raw data output for debugging
- **Auto** - Smart selection based on tool type

## 🛠️ Configuration

Main configuration files:
- `config/cloud.env` - Cloud mode settings (OpenAI, Anthropic)
- `config/local.env` - Local mode settings (Ollama, Faster-Whisper)
- `config/mcp-servers.json` - MCP server definitions

Key settings:
```bash
# Response formatting
JARVIS_RESPONSE_STYLE="casual"  # or "detailed", "auto"

# LLM provider
LLM_PROVIDER="anthropic"  # or "openai", "ollama"

# MCP servers
# Edit config/mcp-servers.json to enable/disable
```

## 📊 Current Status

**Version:** 1.0  
**Status:** Stable  

**Working Features:**
- ✅ Voice activation (cloud & local)
- ✅ 12 local tools
- ✅ 3 MCP web tools
- ✅ Intelligent memory system
- ✅ Natural response formatting
- ✅ Error recovery & retries
- ✅ Tool logging
- ✅ Permission system

**Known Issues:**
- MCP discovery runs twice (cosmetic, doesn't affect functionality)
- Local mode requires tool-optimized Ollama models

## 🆘 Need Help?

1. **Check the relevant guide** in this folder
2. **Look at [TESTING.md](TESTING.md)** for troubleshooting
3. **Review [ERROR_RECOVERY.md](ERROR_RECOVERY.md)** for common errors
4. **Check tool logs:** `./bin/tool-logs`
5. **Check memory:** `./bin/memory stats`

## 📝 Documentation Standards

When adding new features, please update:
1. Relevant guide (or create new one)
2. [TESTING.md](TESTING.md) with test cases
3. [FUTURE_ENHANCEMENTS.md](FUTURE_ENHANCEMENTS.md) if it affects roadmap
4. This README if it's a major feature

Keep docs:
- Clear and concise
- Example-driven
- Up-to-date with code
- Organized by use case

---

**Last Updated:** 2025-11-11  
**Docs Version:** 1.0

