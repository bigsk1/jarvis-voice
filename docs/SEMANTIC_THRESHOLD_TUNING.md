# Semantic Similarity Threshold Tuning Guide

## Overview

The `SEMANTIC_SIMILARITY_THRESHOLD` controls how strict the dense embedding lane
is when finding related memories. `semantic_recall` also fuses FTS5/BM25
results, so a strong keyword or identifier match can still qualify regardless
of this cosine threshold. You can tune the value in your `.env` file without
changing code.

## Configuration

### Location
```bash
# Cloud mode
config/cloud.env

# Local mode  
config/local.env
```

### Setting
```bash
# Add or modify this line:
SEMANTIC_SIMILARITY_THRESHOLD=0.31  # Unified Jarvis Embedding default; code fallback: 0.40
```

## How It Works

When you ask: "What do I like to eat?"
- Jarvis converts to AI embedding (vector)
- Compares to all stored memories
- FTS5/BM25 ranks keyword evidence in parallel
- The threshold filters dense-only candidates before the rankings are fused

**Example**:
- Memory: "favorite_food: pizza"
- Query: "What do I like to eat?"
- Similarity: 0.40 (40% match)
- Threshold 0.40 → ✅ Found!
- Threshold 0.45 → ❌ Filtered out

## Threshold Values

### 0.30-0.35: Very Lenient
- **More results** (includes loosely related)
- Good for: Broad searches, exploring connections
- Risk: May include unrelated memories
- Example: "food" matches "restaurant review"

### 0.35-0.40: Balanced (Recommended)
- **Moderate results** (catches paraphrasing)
- Good for: Natural language queries with different wording
- Default for most use cases
- Example: "What's my preference?" finds "favorite_food"

### 0.40-0.45: Stricter
- **Fewer results** (closer matches only)
- Good for: Precise lookups, avoiding false positives
- May miss creative paraphrasing
- Example: "cross-origin issue" finds "CORS fix" (55% match)

### 0.45-0.50: Very Strict
- **Very few results** (near-identical only)
- Good for: High-precision needs, minimal noise
- Risk: May miss relevant memories with different wording
- Example: Only finds exact synonyms

## Tuning Process

### Step 1: Test Current Threshold
```bash
# Ask natural language question
./orchestrator/orchestrator_v2.py cloud "What do I like to eat?"

# Check if it found your "favorite_food" memory
```

### Step 2: Adjust Based on Results

**If it DIDN'T find relevant memory:**
```bash
# Lower threshold (more lenient)
SEMANTIC_SIMILARITY_THRESHOLD=0.35
```

**If it found TOO MANY irrelevant memories:**
```bash
# Raise threshold (stricter)
SEMANTIC_SIMILARITY_THRESHOLD=0.45
```

### Step 3: Test Edge Cases
```bash
# Test with paraphrasing
"What food do I love?"
"Tell me my favorite dish"
"What's my preferred cuisine?"

# All should find "favorite_food: pizza"
```

### Step 4: Monitor Over Time
```bash
# Check semantic search logs
tail -20 logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | \
  jq 'select(.tool=="semantic_recall")'

# Look at similarity scores in results
```

## Real-World Examples

### Example 1: Technical Memory
```
Saved: "nginx_cors_fix: Fixed CORS blocked errors..."
Query: "How did I fix the cross-origin issue?"
Similarity: 0.55 (good match)
Threshold 0.40 → ✅ Found
Threshold 0.50 → ✅ Found
Threshold 0.60 → ❌ Missed
```

### Example 2: Personal Preference
```
Saved: "favorite_food: sushi"
Query: "What do I like to eat?"
Similarity: 0.40 (moderate match)
Threshold 0.35 → ✅ Found
Threshold 0.40 → ✅ Found
Threshold 0.45 → ❌ Missed (too strict!)
```

### Example 3: Project Info
```
Saved: "flask_auth_api: Flask API with JWT..."
Query: "What's my authentication system?"
Similarity: 0.62 (strong match)
Threshold 0.40 → ✅ Found
Threshold 0.50 → ✅ Found
Threshold 0.70 → ❌ Missed
```

## Best Practices

### 1. Start with Shipped Defaults (cloud 0.32 / local 0.30)
- Shipped example values work for most installs
- Code fallback is 0.40 if the env var is unset
- Adjust only if you see issues

### 2. Monitor Actual Similarity Scores
```bash
# Look at what scores you're getting
./orchestrator/orchestrator_v2.py cloud "Test query" | \
  jq '.data.semantic_recall.memories[].similarity'
```

### 3. Different Thresholds for Different Modes
```bash
# Cloud (shipped example)
config/cloud.env: SEMANTIC_SIMILARITY_THRESHOLD=0.31

# Local (shipped example)
config/local.env: SEMANTIC_SIMILARITY_THRESHOLD=0.31
```

### 4. Document Your Changes
```bash
# In .env file, add comment:
# Lowered to 0.35 on 2025-11-16 - was missing paraphrased queries
SEMANTIC_SIMILARITY_THRESHOLD=0.35
```

## Troubleshooting

### Problem: Not finding memories I know exist
**Solution**: Lower threshold
```bash
SEMANTIC_SIMILARITY_THRESHOLD=0.35  # or 0.30
```

### Problem: Too many irrelevant results
**Solution**: Raise threshold
```bash
SEMANTIC_SIMILARITY_THRESHOLD=0.45  # or 0.50
```

### Problem: Inconsistent results
**Solution**: Check embedding quality
```bash
# Make sure OpenAI API key is valid
# Check if embeddings are being generated
sqlite3 data/jarvis_memory.db "SELECT COUNT(*) FROM knowledge_base WHERE embedding IS NOT NULL"
```

### Problem: Changes not taking effect
**Solution**: Restart Jarvis
```bash
# Config is loaded at startup
# Kill and restart for changes to apply
```

## Advanced: Per-Call Override

You can override the threshold for specific searches in code:

```python
from memory_db import MemoryDB

db = MemoryDB()

# Use config value (default)
results = db.semantic_search("query")

# Override for this specific call
results = db.semantic_search("query", similarity_threshold=0.30)
```

## Similarity Score Interpretation

| Score Range | Meaning | Typical Cases |
|-------------|---------|---------------|
| 0.80-1.00 | Near-identical | Exact matches, synonyms |
| 0.60-0.79 | Very similar | Clearly related concepts |
| 0.40-0.59 | Moderately similar | Same topic, different phrasing |
| 0.30-0.39 | Loosely related | Might be relevant |
| 0.00-0.29 | Unrelated | Noise, false positives |

## When to Tune

### Tune Higher (0.45+) When:
- Getting too many irrelevant results
- Have very specific memories
- Need high precision over recall
- Favoring precision after validating representative Jarvis Embedding queries

### Tune Lower (0.35-) When:
- Missing relevant memories
- Users ask questions in many different ways
- Favor recall over precision
- Using lower-quality embeddings (local models)

## Quick Reference

```bash
# Shipped cloud default (balanced)
SEMANTIC_SIMILARITY_THRESHOLD=0.31

# More results (lenient)
SEMANTIC_SIMILARITY_THRESHOLD=0.28

# Fewer results (strict)
SEMANTIC_SIMILARITY_THRESHOLD=0.40

# Test your changes
./orchestrator/orchestrator_v2.py cloud "What do I like to eat?"
```

---

**Remember**: There's no "perfect" value - tune based on YOUR actual usage patterns!
