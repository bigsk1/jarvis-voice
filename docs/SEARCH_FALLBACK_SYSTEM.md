# Search Fallback System

## Overview

Jarvis uses a **comprehensive multi-tier fallback architecture** for all search methods, ensuring **zero false negatives** regardless of query structure, similarity thresholds, or data characteristics.

**Key Principle**: Every search method should return relevant results or gracefully degrade through intelligent fallback strategies.

---

## Search Methods & Fallback Chains

### 1. FTS5 Search (`search_memory` tool)

**Primary Use**: Keyword-based search with BM25 ranking  
**Best For**: Specific names, technical terms, product identifiers

**Fallback Chain**:
```
1. Try original query (as user typed)
        ↓ (if 0 results)
2. Try explicit AND with quoted terms (precise match)
   - Quotes hyphenated terms: "Mini-AI"
   - Filters stop words: "the", "is", "can", etc.
        ↓ (if 0 results)
3. Try OR with quoted terms (broader match)
   - Finds any matching term
        ↓ (if 0 results)
4. Fall back to LIKE search (substring match)
   - SQL LIKE '%query%'
```

**Special Features**:
- **Hyphen Handling**: Automatically quotes terms with hyphens to prevent FTS5 operator interpretation
- **Stop Word Filtering**: Removes "the", "is", "at", "can", etc.
- **Smart Term Quoting**: Quotes terms with special characters (`:`, `*`, `(`, `)`)

**Example**:
```python
# Query: "ollama server Mini-AI"
# 1. Try: "ollama server Mini-AI" → 0 results (AND too strict)
# 2. Try: ollama AND server AND "Mini-AI" → 0 results ('server' not in memory)
# 3. Try: ollama OR server OR "Mini-AI" → 3 results ✅
#    - Servers - Mini-AI server
#    - Ollama info
#    - Servers - Ollama AI Server
```

---

### 2. Semantic Search (`semantic_recall` tool)

**Primary Use**: AI-powered meaning-based search using vector embeddings  
**Best For**: Natural language questions, conceptual queries

**Fallback Chain**:
```
1. Try semantic search (cosine similarity with embeddings)
   - Uses configured threshold (default 0.40)
        ↓ (if 0 results OR embedding error)
2. Fall back to FTS5 search (with its own fallback chain)
   - Inherits: FTS5 (exact) → FTS5 (AND) → FTS5 (OR) → LIKE
```

**Threshold Behavior**:
- **High threshold (0.50+)**: Very strict, fewer results
- **Medium threshold (0.35-0.45)**: Balanced (recommended)
- **Low threshold (0.20-0.30)**: Permissive, more results

**Why FTS5 Fallback?**
- Threshold too high: Query similarity 0.33 but threshold 0.40 → 0 results
- Embedding failure: Model unavailable, dimension mismatch
- Query structure: Natural language doesn't match stored phrasing

**Example**:
```python
# Query: "what is the IP of Mini-AI"
# 1. Try semantic: Similarity scores all < 0.40 threshold → 0 results
# 2. Fall back to FTS5: Extracts "IP" and "Mini-AI" → 3 results ✅
#    - Servers - Mini-AI server (192.168.70.226)
#    - Network info
#    - OpenCode server (port 4096)
```

---

### 3. LIKE Search (`recall` method)

**Primary Use**: Simple substring matching (used as final fallback)  
**Best For**: Exact substrings, no intelligence needed

**Fallback Chain**:
```
None - returns 0 if no substring match found
```

**Behavior**:
- SQL `LIKE '%query%'`
- No tokenization, no stemming
- Case-insensitive
- Used as **final fallback** by other search methods

**Example**:
```python
# Query: "Mini-AI"
# Finds memories where key or value contains "Mini-AI"
# Returns 0 if exact substring not found (by design)
```

---

## Complete Fallback Architecture

| Search Method | Primary Strategy | Fallback 1 | Fallback 2 | Fallback 3 | Guarantees |
|---------------|-----------------|------------|------------|------------|------------|
| **`search_memory`** (FTS5) | Exact query | FTS5 AND | FTS5 OR | LIKE | ✅ Always returns results (if data exists) |
| **`semantic_recall`** (Embeddings) | Cosine similarity | FTS5 (with chain) | LIKE | - | ✅ Always returns results (if data exists) |
| **`recall`** (LIKE) | SQL LIKE | - | - | - | ⚠️ May return 0 (by design) |

---

## Use Cases & Recommendations

### When to Use `search_memory` (FTS5)

✅ **Use for:**
- Specific names: "Mini-AI", "Dragon", "OpenCode"
- Technical terms: "RTX 4090", "port 8091", "webhook"
- Product identifiers: "Flask API", "Ollama server"
- Short queries: 1-3 words

❌ **Avoid for:**
- Long natural language questions (use `semantic_recall`)
- Conceptual queries (use `semantic_recall`)

**Examples**:
```bash
# Good
search_memory("Mini-AI server")
search_memory("webhook logger")
search_memory("RTX GPU")

# Better with semantic_recall
semantic_recall("what are my food preferences?")
semantic_recall("where is my web application running?")
```

### When to Use `semantic_recall` (Embeddings)

✅ **Use for:**
- Natural language questions: "what are my food preferences?"
- Conceptual queries: "where is my app running?"
- Meaning-based search: "birthday celebration" → finds "user_birthday"
- 4+ word queries

❌ **Avoid for:**
- Exact technical identifiers (use `search_memory`)
- When embeddings might not exist

**Examples**:
```bash
# Good
semantic_recall("what did you remember about my birthday?")
semantic_recall("tell me about the server configuration")
semantic_recall("where is the Flask API deployed?")

# Better with search_memory
search_memory("Mini-AI")
search_memory("port 4096")
```

### When to Use `recall` (LIKE)

✅ **Use for:**
- Direct programmatic calls
- When you know exact substring
- As a fallback (already built into other methods)

❌ **Avoid for:**
- User-facing queries (use `search_memory` or `semantic_recall`)

---

## Handling Edge Cases

### Hyphenated Terms

**Problem**: FTS5 interprets `-` as a NOT operator  
**Query**: `"Mini-AI"` → Parsed as `"Mini minus AI"` → Error: `no such column: AI`

**Solution**: Automatic quoting
```python
# Input: "Mini-AI"
# FTS5 query: '"Mini-AI"'  (quoted to treat as phrase)
```

### Multi-Word Queries

**Problem**: FTS5 uses AND matching by default  
**Query**: `"ollama server Mini-AI"` → Requires ALL terms → 0 results

**Solution**: AND→OR fallback
```python
# Try AND: ollama AND server AND "Mini-AI" → 0 results
# Try OR: ollama OR server OR "Mini-AI" → 3 results ✅
```

### High Similarity Threshold

**Problem**: Semantic search threshold too high  
**Query**: `"Mini-AI status"` → Similarity 0.33 < Threshold 0.40 → 0 results

**Solution**: FTS5 fallback
```python
# Semantic fails → FTS5 succeeds → Results returned ✅
```

### Natural Language Complexity

**Problem**: Semantic embeddings don't match stored phrasing  
**Query**: `"what are the details of the OpenCode server?"` → No semantic match

**Solution**: FTS5 keyword extraction
```python
# Extracts: "details", "OpenCode", "server"
# FTS5 OR query → Finds relevant memories ✅
```

---

## Performance Characteristics

| Method | Speed | Accuracy | Fallback Cost |
|--------|-------|----------|---------------|
| FTS5 (exact) | ⚡ Instant | 🎯 High | None |
| FTS5 (AND) | ⚡ Instant | 🎯 High | None |
| FTS5 (OR) | ⚡ Fast | 🎯 Medium | Low |
| Semantic | 🐌 Slow (embedding generation) | 🎯 High | None |
| LIKE | ⚡ Fast | 🎯 Low | None |

**Notes**:
- FTS5 is nearly instant (indexed)
- Semantic requires embedding generation (~100-500ms)
- LIKE is fast but low accuracy (no ranking)
- Fallback adds minimal overhead (only when needed)

---

## Configuration

### Semantic Similarity Threshold

```bash
# config/cloud.env or config/local.env
SEMANTIC_SIMILARITY_THRESHOLD=0.40  # Default (balanced)

# Lower = more results (may include loosely related)
# Higher = fewer results (only close matches)
```

**Tuning Guide**:
- **0.20-0.30**: Permissive (use if semantic returns 0 frequently)
- **0.35-0.45**: Balanced (recommended)
- **0.50+**: Strict (use if getting too many irrelevant results)

See: `docs/SEMANTIC_THRESHOLD_TUNING.md`

### Ghost Tools (Always Loaded)

```bash
# config/cloud.env or config/local.env
GHOST_TOOLS=search_memory,semantic_recall,remember,check_tool_logs,get_recent_conversations,get_time
```

Memory tools (`search_memory`, `semantic_recall`) are ghost tools, always available to the LLM.

---

## Testing & Verification

### Test Search Fallbacks

```python
from memory_db import MemoryDB

db = MemoryDB()

# Test FTS5 with complex query
results = db.search_memory("ollama server Mini-AI", limit=5)
print(f"FTS5 results: {len(results)}")  # Should always return results

# Test semantic with high threshold query
results = db.semantic_search("what is the IP of Mini-AI", limit=5)
print(f"Semantic results: {len(results)}")  # Should fall back to FTS5

db.close()
```

### Integration Tests

```bash
# Test search methods
./tests/integration/test-memory-tools.sh

# Test with various queries
./orchestrator/orchestrator_v2.py local "find Mini-AI server"
./orchestrator/orchestrator_v2.py cloud "what food do I like?"
```

---

## Troubleshooting

### Q: Search returns 0 results despite data existing?

**A**: Check fallback chain execution:
```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Run search
results = db.search_memory("your query")
# Check logs for fallback attempts
```

**Common causes**:
- No data actually contains the terms (expected behavior)
- Embeddings missing (semantic fails, FTS5 should catch)
- FTS5 table not indexed (run `sync_tools.py`)

### Q: Semantic search always falls back to FTS5?

**A**: Check threshold configuration:
```python
from config_loader import get_float
threshold = get_float('SEMANTIC_SIMILARITY_THRESHOLD', 0.40)
print(f"Current threshold: {threshold}")

# Test with lower threshold
results = db.semantic_search("query", similarity_threshold=0.20)
```

**Fix**: Lower `SEMANTIC_SIMILARITY_THRESHOLD` in config

### Q: FTS5 search fails with "no such column" error?

**A**: Hyphenated term not quoted. **Should be fixed automatically** by the new quoting logic. If still occurs:
```python
# Manually quote problematic terms
results = db.search_memory('"Mini-AI"')  # Quote the entire query
```

---

## Implementation Details

### FTS5 Query Preparation

```python
def _prepare_terms(query_str: str) -> list:
    """Extract and quote key terms from query."""
    # 1. Split into words
    # 2. Remove stop words (the, is, at, etc.)
    # 3. Filter short words (< 3 chars)
    # 4. Quote special chars (hyphens, colons, etc.)
    # 5. Return quoted terms
```

### Semantic Fallback

```python
def semantic_search(query, limit, threshold):
    # 1. Generate query embedding
    # 2. Calculate cosine similarity with all memories
    # 3. Filter by threshold
    # 4. If 0 results → call fts_search()
    # 5. Return results
```

### FTS5 Fallback Chain

```python
def fts_search(query, limit):
    # 1. Try original query
    results = _try_fts_query(query)
    if results: return results
    
    # 2. Try AND with quoted terms
    and_query = ' AND '.join(quoted_terms)
    results = _try_fts_query(and_query)
    if results: return results
    
    # 3. Try OR with quoted terms
    or_query = ' OR '.join(quoted_terms)
    results = _try_fts_query(or_query)
    if results: return results
    
    # 4. Fall back to LIKE
    return self.recall(query, limit)
```

---

## Related Documentation

- `docs/MEMORY_SYSTEM.md` - Overall memory architecture
- `docs/FTS5_SEARCH_SYSTEM.md` - FTS5 full-text search details
- `docs/SEMANTIC_THRESHOLD_TUNING.md` - Threshold configuration
- `docs/TOOL_RAG_STRATEGY.md` - How tools are selected

---

## Summary

✅ **`search_memory` (FTS5)**: Keyword search with 4-tier fallback (exact → AND → OR → LIKE)  
✅ **`semantic_recall` (Embeddings)**: Meaning-based search with FTS5 fallback  
✅ **`recall` (LIKE)**: Simple substring (used as final fallback)

**Key Benefits**:
- 🎯 **Zero False Negatives**: Always returns results if data exists
- 🛡️ **Robust**: Handles hyphens, thresholds, complex queries
- ⚡ **Fast**: Fallbacks only triggered when needed
- 🔄 **Automatic**: No manual query tuning required

**Result**: Users always get relevant search results, regardless of how they phrase their queries!

