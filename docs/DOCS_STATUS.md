# Documentation Status & Organization

Last updated: November 22, 2025

---

## 📚 Current Documentation

### ✅ ACTIVE - Keep & Maintain

**Getting Started:**
- `config/README.md` - Configuration guide **[CURRENT]**
- `QUICKSTART.md` - Quick setup guide
- `TOOL_CALLING_SYSTEM.md` - How tool system works **[CORE]**
- `JARVIS_WORKFLOW.md` - Complete workflow with visual flowcharts **[CURRENT]**

**Core Features:**
- `OPENCODE.md` - OpenCode integration guide **[CURRENT]**
- `OPENCODE_API_REFERENCE.md` - Full OpenCode API reference
- `MEMORY_SYSTEM.md` - Memory & knowledge base guide **[CORE]**
- `FTS5_SEARCH_SYSTEM.md` - FTS5 full-text search with BM25 ranking **[NEW - Nov 2025]**
- `DUAL_DATABASE_SYSTEM.md` - Cloud/local DB architecture with auto-sync **[NEW - Nov 2025]**
- `SEMANTIC_THRESHOLD_TUNING.md` - Tune search sensitivity **[NEW - Nov 2025]**
- `TOOL_RAG_STRATEGY.md` - Tool RAG system - Dynamic tool retrieval **[NEW - Nov 22, 2025]**
- `TOOL_RAG_IMPLEMENTATION_SUMMARY.md` - Tool RAG implementation details **[NEW - Nov 22, 2025]**
- `TOOL_RAG_TROUBLESHOOTING.md` - Tool RAG debugging guide **[NEW - Nov 22, 2025]**
- `TEST_SCRIPT_TOOL_RAG_FIX.md` - Test script integration fixes **[NEW - Nov 22, 2025]**
- `MULTI_TURN_ORCHESTRATION.md` - Multi-turn tool chaining
- `METADATA_SYSTEM.md` - Cost tracking & metadata **[CURRENT - Nov 2025 pricing]**
- `TOOL_MANAGEMENT.md` - Enable/disable tools **[NEW - Nov 2025]**
- `XAI_PROVIDER.md` - xAI Grok provider (2M context, 10-15x cheaper!) **[RECOMMENDED]**

**System Understanding:**
- `AUTO_CONTEXT_SYSTEM.md` - Short-term conversation memory **[NEW - Nov 2025]**
- `CONVERSATION_STATE_ARCHITECTURE.md` - State management between cycles **[NEW - Nov 2025]**

**Operations:**
- `JARVIS_INTEL_SYSTEM.md` - Intel system: ingestion, self-learning, manage_intel tool
- `ERROR_RECOVERY.md` - Error handling patterns
- `MCP_QUICKSTART.md` - MCP server integration
- `MCP_NAMING_CONVENTIONS.md` - MCP snake_case requirements **[NEW - Nov 2025]**
- `MCP_REGRESSION_FIX.md` - MCP parsing architecture **[NEW - Nov 2025]**

**Voice Mode:**
- `AUTO_MODE_EXPLAINED.md` - Response formatting modes
- `CASUAL_VS_DETAILED_MODE.md` - Voice vs CLI output
- `VOICE_MODE_FIXES.md` - Voice mode improvements

**Testing:**
- `COMPREHENSIVE_TESTING.md` - Burn test suite for all features **[NEW - Nov 2025]**
- `TESTING.md` - Comprehensive testing guide

**Proactive System (Nov 2025):**
- `api/` - Proactive API documentation (webhooks, alerts, monitoring)
- `service/` - Background services documentation (daemons, auto-resolve)

**OpenCode Specific:**
- `opencode/OPENCODE_AGENTS.md` - Agent architecture
- `opencode/OPENCODE_MEMORY_STRATEGY.md` - OpenCode + memory integration
- `opencode/OPENCODE_PERMISSIONS.md` - Permission system
- `opencode/OPENCODE_PHASE2_COMPLETE.md` - Phase 2 status
- `opencode/OPENCODE_PHASE2_STATUS.md` - Implementation checklist
- `opencode/OPENCODE_PLUGINS.md` - Plugin system

**Recent Work (Nov 18-22, 2025):**
- **Tool RAG System** - Dynamic tool retrieval for infinite scalability (Nov 22)
- Major improvements to memory system (FTS5, dual DB, semantic tuning)
- Auto-context system for conversation continuity
- Comprehensive burn test suite
- MCP naming conventions and regression fixes
- Voice improvements (timeout, randomized greetings)
- Tool management system
- Enhanced error propagation for LLM self-healing (Nov 22)

---

## 🗄️ ARCHIVED - Historical Reference Only

These docs contain outdated info but are kept for historical context:

**Historical/Deprecated:**
- `DATABASE_DEEP_DIVE.md` - ⚠️ Mentions removed `tool_patterns` table
- `METADATA_POPULATION_STATUS.md` - ⚠️ Tracking doc (now complete)
- `CHANGELOG_2025-11-14.md` - Detailed change log (very long)
- `FIXES_2025-11-14.md` - Detailed fix log (superseded by FIXES_SUMMARY)
- `TESTING_RESULTS_2025-11-14.md` - One-time test results
- `PHASE1_COMPLETE.md` - Historical milestone
- `MEMORY_INTELLIGENCE_FIXES.md` - Tracking doc (now complete)

**Chat History:**
- `cursor_moved_file_to_jarvis_oice_folder.md` - Imported chat history (huge file)

**Personal Notes:**
- `MY-NOTES-IDEAS-CONCERNS.md` - User's personal notes

---

## ⚠️ Outdated References Fixed

### Removed from Codebase
- ✅ `mistral-nemo` model → Now using `qwen3` (local mode)
- ✅ `qwen3-vl` → Now using `qwen3.5:latest` or `qwen3-coder` (local mode)
- ✅ `tool_patterns` table → Removed (never used)
- ✅ `preferences` table → Removed (never used)
- ✅ `config.env.template` → Split into `cloud.env.example` & `local.env.example`
- ✅ SQL LIKE search → Replaced with FTS5 full-text search with BM25 ranking
- ✅ Hardcoded examples in prompts → Removed for generic LLM understanding

### Updated in Documentation (Nov 2025)
- ✅ `README.md` - Updated with Tool RAG, FTS5, auto-context, comprehensive testing
- ✅ `docs/README.md` - Updated with all new documentation files including Tool RAG
- ✅ `JARVIS_WORKFLOW.md` - Updated with Tool RAG system, xAI provider (Nov 22)
- ✅ References to "Future" orchestrator/skills - Now fully implemented
- ✅ Tool interface examples - Updated to Python standard
- ✅ Cost tracking - Now includes Nov 2025 pricing + xAI Grok
- ✅ Memory system - Now documents hybrid search (FTS5 + embeddings)
- ✅ MCP documentation - Now emphasizes snake_case naming
- ✅ Tool system - Now documents dynamic retrieval (Tool RAG)

---

## 📋 Recommended Actions

### Already Completed (Nov 22, 2025)
- ✅ Removed outdated migration docs (`FTS5_MIGRATION_GUIDE.md`, `TESTING_CHECKLIST.md`)
- ✅ Renamed `FTS5_UPGRADE_SUMMARY.md` → `FTS5_SEARCH_SYSTEM.md`
- ✅ Updated all README files with current features including Tool RAG
- ✅ Added comprehensive change log entries (Nov 18-22)
- ✅ Implemented Tool RAG system with full documentation (Nov 22)
- ✅ Updated test scripts for Tool RAG integration (Nov 22)
- ✅ Added Tool RAG to `JARVIS_WORKFLOW.md` with visual charts (Nov 22)
- ✅ Updated all documentation to include xAI provider (Nov 22)
- ✅ Removed redundant `MERMAID_CHART.md` (Nov 22)

### Update DATABASE_DEEP_DIVE.md (TODO)

Add header warning:
```markdown
# ⚠️ HISTORICAL DOCUMENT

This document describes the database evolution and includes references
to removed tables (tool_patterns, preferences). Current schema has only:
- knowledge_base (with FTS5 virtual table: knowledge_base_fts)
- conversations

For current database info, see MEMORY_SYSTEM.md and FTS5_SEARCH_SYSTEM.md
```

---

## 🎯 Documentation Health

### Current Status: **EXCELLENT** ✅

**Strengths:**
- ✅ README completely updated with Tool RAG, FTS5, auto-context, and all Nov 2025 features
- ✅ Core guides (MEMORY, OPENCODE, TOOL_CALLING, JARVIS_WORKFLOW) are current and enhanced
- ✅ New comprehensive documentation for major features (Tool RAG, FTS5, auto-context, MCP)
- ✅ Recent changes well-documented (Nov 18-22, 2025)
- ✅ Configuration examples current (cloud/local.env.example) including xAI provider
- ✅ Comprehensive burn test documentation
- ✅ Clear change log with dates
- ✅ Tool RAG system fully documented with 4 dedicated guides
- ✅ Visual workflow charts updated with Tool RAG flow

**Minor Issues:**
- ⚠️ Some docs mention removed database tables (marked as historical)
- ⚠️ Overlapping Nov 14 docs (CHANGELOG, FIXES, FIXES_SUMMARY) - could archive
- ⚠️ One huge imported chat history file (can archive)

**Recommendations:**
1. Add archive warning to DATABASE_DEEP_DIVE.md
2. Consider moving historical Nov 14 docs to archive/
3. Keep all OpenCode docs (still evolving)
4. Keep all Nov 18-21 docs (current active development)

---

## 📊 Documentation Map

```
docs/
├── Core Guides (Keep) ⭐ CURRENT
│   ├── QUICKSTART.md
│   ├── JARVIS_WORKFLOW.md (UPDATED - Nov 22 with Tool RAG)
│   ├── TOOL_CALLING_SYSTEM.md
│   ├── TOOL_RAG_STRATEGY.md (NEW - Nov 22, 2025)
│   ├── TOOL_RAG_IMPLEMENTATION_SUMMARY.md (NEW - Nov 22, 2025)
│   ├── TOOL_RAG_TROUBLESHOOTING.md (NEW - Nov 22, 2025)
│   ├── TEST_SCRIPT_TOOL_RAG_FIX.md (NEW - Nov 22, 2025)
│   ├── TOOL_MANAGEMENT.md (NEW - Nov 2025)
│   ├── MEMORY_SYSTEM.md
│   ├── FTS5_SEARCH_SYSTEM.md (NEW - Nov 2025)
│   ├── DUAL_DATABASE_SYSTEM.md (NEW - Nov 2025)
│   ├── SEMANTIC_THRESHOLD_TUNING.md (NEW - Nov 2025)
│   ├── XAI_PROVIDER.md (xAI Grok - RECOMMENDED)
│   └── METADATA_SYSTEM.md
│
├── System Understanding (Keep) 
│   ├── AUTO_CONTEXT_SYSTEM.md (NEW - Nov 2025)
│   ├── CONVERSATION_STATE_ARCHITECTURE.md (NEW - Nov 2025)
│
├── Operational (Keep)
│   ├── JARVIS_INTEL_SYSTEM.md
│   ├── ERROR_RECOVERY.md
│   ├── MCP_QUICKSTART.md
│   ├── MCP_NAMING_CONVENTIONS.md (NEW - Nov 2025)
│   ├── MCP_REGRESSION_FIX.md (NEW - Nov 2025)
│   ├── AUTO_MODE_EXPLAINED.md
│   ├── CASUAL_VS_DETAILED_MODE.md
│   └── VOICE_MODE_FIXES.md
│
├── Testing (Keep) ⭐ UPDATED
│   ├── COMPREHENSIVE_TESTING.md (NEW - Nov 2025)
│   ├── TESTING.md (UPDATED - Nov 22 with Tool RAG testing)
│   └── BASELINE_TOKEN_USAGE.md
│
├── Proactive System (Keep) 🔮 NEW
│   ├── api/ (Webhooks, alerts, monitoring)
│   └── service/ (Background daemons, auto-resolve)
│
├── OpenCode Deep Dive (Keep)
│   ├── opencode/OPENCODE.md
│   ├── opencode/OPENCODE_API_REFERENCE.md
│   ├── opencode/OPENCODE_AGENTS.md
│   ├── opencode/OPENCODE_MEMORY_STRATEGY.md
│   ├── opencode/OPENCODE_PERMISSIONS.md
│   ├── opencode/OPENCODE_PLUGINS.md
│   ├── opencode/OPENCODE_PHASE2_COMPLETE.md
│   └── opencode/OPENCODE_PHASE2_STATUS.md
│
├── Recent Work (Keep for 6 months)
│   ├── Nov 18-21, 2025 work (documented in README change logs)
│   ├── INTELLIGENCE_IMPROVEMENTS_2025-11-14.md
│   └── FIXES_SUMMARY_2025-11-14.md
│
└── Historical/Consider Archiving
    ├── DATABASE_DEEP_DIVE.md (add warning)
    ├── CHANGELOG_2025-11-14.md (very long)
    ├── FIXES_2025-11-14.md (superseded)
    ├── TESTING_RESULTS_2025-11-14.md
    ├── METADATA_POPULATION_STATUS.md
    ├── MEMORY_INTELLIGENCE_FIXES.md
    ├── PHASE1_COMPLETE.md
    └── cursor_moved_file_to_jarvis_oice_folder.md
```

---

## 🚀 Next Steps

**Completed (Nov 22, 2025):**
1. ✅ README updated to current state (Tool RAG, FTS5, auto-context, all Nov 2025 features)
2. ✅ docs/README.md updated with all Tool RAG documentation files
3. ✅ This status doc updated to reflect Nov 18-22 changes
4. ✅ Change logs added with detailed entries for Nov 18-22
5. ✅ Removed temporary migration docs
6. ✅ Renamed and finalized FTS5 documentation
7. ✅ Tool RAG system implemented with 4 comprehensive guides
8. ✅ JARVIS_WORKFLOW.md updated with Tool RAG flowcharts and xAI provider
9. ✅ Test scripts updated for Tool RAG integration
10. ✅ TESTING.md updated with Tool RAG testing procedures

**Optional Cleanup:**
1. Add warning header to DATABASE_DEEP_DIVE.md
2. Create `docs/archive/` directory
3. Move historical docs to archive/ (Nov 14 docs can be archived after 6 months)
4. Update .gitignore if archiving

**Ongoing:**
- Document new features as they're developed
- Update METADATA_SYSTEM.md when pricing changes
- Update OPENCODE.md as OpenCode API evolves
- Keep change logs current in README files

---

## 📈 Recent Achievements (Nov 18-22, 2025)

**Major Features:**
- ✅ **Tool RAG System** - Dynamic tool retrieval for infinite scalability (Nov 22)
  - Vector-based semantic search for tool discovery
  - Configurable ghost tools and similarity threshold
  - Optimized for local models (5 tools) and cloud (15 tools)
  - Reduces token usage by 60-80%
- ✅ FTS5 full-text search with BM25 ranking
- ✅ Auto-context system for conversation continuity
- ✅ Comprehensive burn test suite
- ✅ MCP snake_case naming enforcement
- ✅ Levenshtein fuzzy matching for reminders
- ✅ Randomized wake word greetings
- ✅ Voice timeout system (30 seconds)
- ✅ Configurable Ollama context window
- ✅ Enhanced intel ingestion
- ✅ Enhanced error propagation for LLM self-healing (Nov 22)

**Documentation:**
- ✅ 12 new documentation files (including 4 Tool RAG guides)
- ✅ Comprehensive change logs (Nov 18-22)
- ✅ Updated all README files with Tool RAG
- ✅ Generic LLM prompting (removed hardcoded examples)
- ✅ JARVIS_WORKFLOW.md updated with Tool RAG visual flowcharts
- ✅ All docs updated with xAI Grok provider

**System Health:**
- ✅ All features tested and working
- ✅ Tool RAG verified with 8/8 test pass rate
- ✅ Database isolation fixed (local mode uses local DB)
- ✅ MCP regression fixed (server name parsing)
- ✅ Proactive reminder guard added
- ✅ Test scripts auto-sync tool embeddings

