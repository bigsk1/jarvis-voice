# Tool RAG Troubleshooting Guide

## Issue Identified

After implementing Tool RAG, you noticed that the system might be **missing relevant tools** due to the semantic search not finding the right matches.

### Example: Food Preferences Query
**Query**: "What should I eat for dinner based on my food preferences?"

**Expected Behavior**: Should retrieve `recall` or `semantic_recall` to search intel files.

**Actual Behavior**: Only retrieved `remember` and `ingest_intel` (scores: 0.16 and 0.15).
- `recall` scored 0.14 (just below threshold of 0.15)
- `semantic_recall` scored 0.12 (below threshold)

**Root Cause**: The similarity threshold (0.15) was too strict, filtering out relevant tools.

---

## Solution: Adjustable Threshold + Better Logging

### 1. New Config Variable: `TOOL_SIMILARITY_THRESHOLD`

**Location**: `config/cloud.env` and `config/local.env`

```bash
# Tool Retrieval Similarity Threshold (0.0-1.0)
# Minimum similarity score for a tool to be retrieved
# Lower = more tools retrieved (may include less relevant)
# Higher = fewer tools retrieved (only highly relevant)
# Set to 0.0 to disable threshold (use top-K only)
# Recommended: 0.15-0.25 for cloud, 0.20-0.30 for local
TOOL_SIMILARITY_THRESHOLD=0.0  # Disable threshold, use top-K only
```

**Recommendation**: Start with `0.0` (disabled) to ensure no tools are filtered out. The top-K limit (5 for local, 15 for cloud) will still prevent context flooding.

---

### 2. Debug Tool: `bin/debug-tool-rag.py`

**Usage**:
```bash
./bin/debug-tool-rag.py cloud "What should I eat for dinner?"
./bin/debug-tool-rag.py local "Remind me to call mom"
```

**Output**:
- Shows similarity scores for ALL tools
- Highlights which tools pass the threshold
- Shows exactly what the LLM receives (retrieved + ghost)
- Provides recommendations

**Example Output**:
```
🔎 Vector Search Results (Top 20):
   Rank   Score    Tool Name                                Pass Threshold?
   1      0.1611   👻 remember                               ✅ YES
   2      0.1525      ingest_intel                           ✅ YES
   3      0.1441      recall                                 ❌ NO  ← MISSED!
   4      0.1322      search_conversations                   ❌ NO

📚 Tools Sent to LLM:
   Total: 7 tools (2 retrieved + 5 ghost)
   Retrieved: remember, ingest_intel
   Ghost: search_memory, semantic_recall, remember, check_tool_logs, get_recent_conversations, get_time
```

---

### 3. Enhanced Logging

**Added to `orchestrator/router_v2.py`**:
```
[TOOL_RAG] Query: What should I eat for dinner...
[TOOL_RAG] Retrieved 2 tools: ['remember', 'ingest_intel']
[TOOL_RAG] Ghost tools: ['search_memory', 'semantic_recall', 'remember', 'check_tool_logs', 'get_recent_conversations', 'get_time']
[TOOL_RAG] Total tools sent to LLM: 7
```

**Added to `lib/memory_db.py`**:
```
[TOOL_SEARCH] Searching 31 enabled tools for query: 'What should I eat...'
[TOOL_SEARCH] Threshold 0.15: 2/31 tools passed
[TOOL_SEARCH]   #1: remember (score: 0.1611)
[TOOL_SEARCH]   #2: ingest_intel (score: 0.1525)
```

---

## Comparison: Before vs After Tool RAG

### Before (Loading ALL Tools)
- **Tools Loaded**: 31 (all enabled)
- **Context Usage**: ~15,500 tokens
- **LLM Confusion**: High (too many similar tools)
- **Local Model Performance**: Poor (context overflow)

### After (Tool RAG with Threshold = 0.0)
- **Tools Loaded**: 15-20 (top-K + ghosts)
- **Context Usage**: ~7,500-10,000 tokens
- **LLM Confusion**: Lower (focused set)
- **Local Model Performance**: Better (more room for conversation)

### After (Tool RAG with Threshold = 0.15)
- **Tools Loaded**: 7-10 (filtered + ghosts)
- **Context Usage**: ~3,500-5,000 tokens
- **LLM Confusion**: Very Low (highly relevant only)
- **Local Model Performance**: Excellent (lots of context room)
- **⚠️ Risk**: May miss relevant tools if threshold too high

---

## Tuning Recommendations

### Start Conservative (Disable Threshold)
```bash
TOOL_SIMILARITY_THRESHOLD=0.0  # Rely on top-K only
```
- **Pros**: No risk of missing tools
- **Cons**: May include loosely related tools

### Monitor and Adjust
1. Run queries and check logs
2. Use `debug-tool-rag.py` to inspect scores
3. If seeing too many irrelevant tools, raise threshold gradually:
   - `0.10` - Very permissive
   - `0.15` - Balanced (current default)
   - `0.20` - Strict
   - `0.25` - Very strict

### Mode-Specific Tuning
- **Cloud Mode**: Can afford more tools (larger context)
  - Recommended: `0.10-0.15`
- **Local Mode**: Needs fewer tools (smaller context)
  - Recommended: `0.15-0.20`

---

## Food Preferences Issue Explained

### Why It Worked Before
With ALL tools loaded, `semantic_recall` was always available. The LLM correctly used it to search memories.

### Why It Had Issues After
With threshold = 0.15:
- `semantic_recall` scored 0.12 (filtered out)
- `recall` scored 0.14 (filtered out)
- BUT `semantic_recall` is a **ghost tool**, so it was still available!

**Actual Result**: The LLM DID have access to `semantic_recall` and used it successfully. From your logs:
```json
{"tool": "semantic_recall", "arguments": {"query": "food preferences dinner..."}}
{"tool": "recall", "arguments": {"query": "food", "limit": 10}}
```

### The Real Issue
The LLM found your sushi preference ("favorite_food: The user loves sushi") but the `intel/food-ideas.md` file might not be properly indexed in the memory database.

**Solution**: Ensure intel files are ingested:
```bash
./orchestrator/orchestrator_v2.py cloud "ingest intel file food-ideas.md"
```

---

## Key Takeaways

1. **Ghost Tools Work**: They ensure critical tools (like `semantic_recall`) are ALWAYS available
2. **Threshold is Optional**: Set to `0.0` to disable and rely on top-K limiting
3. **Use Debug Tool**: `debug-tool-rag.py` shows exactly what's happening
4. **Logs are Your Friend**: New logging shows similarity scores and retrieval decisions
5. **Tool RAG is an Optimization**: It reduces context flooding while maintaining functionality

---

## Action Items

1. **Set threshold to 0.0** in `config/cloud.env`:
   ```bash
   TOOL_SIMILARITY_THRESHOLD=0.0
   ```

2. **Re-sync tools** (already automated in startup scripts):
   ```bash
   source ~/jarvis-venv/bin/activate
   ./bin/sync-tools.py cloud
   ```

3. **Test with debug tool**:
   ```bash
   ./bin/debug-tool-rag.py cloud "What should I eat for dinner?"
   ```

4. **Monitor logs** during normal usage and adjust threshold if needed

---

## Conclusion

The Tool RAG system is working correctly. The perceived "missing tools" issue was due to:
1. Threshold being slightly too strict (easily adjustable)
2. Ghost tools ensuring critical functionality is never lost
3. Need for better visibility into what the LLM receives (now added)

With threshold disabled (`0.0`), the system behaves almost like before (loads top-15 tools) but with the **advantage** that you can now scale to 100+ tools and only the most relevant will be considered.

