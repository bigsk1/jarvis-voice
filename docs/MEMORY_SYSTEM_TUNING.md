# Memory System Fine-Tuning

**Status**: Almost there! Minor tweaks needed for production-level intelligence.

## Current Status: What Works ✅

1. **Proactive auto-save guidance** in system prompt (router_v2.py lines 101-141)
2. **Memory recall guidance** in system prompt (lines 97-100)
3. **Semantic search** working (vector embeddings)
4. **Conversation search** working (text search)
5. **Tool definitions** have good descriptions

## Issues Found 🔍

### 1. **Category Mismatch** (Priority: High)

**Problem**: Different tools use different category sets

```python
# remember.tool.json defines:
["contact", "personal", "preference", "location", "fact", "other"]

# ingest_intel.py actually uses:
["technical", "network", "credentials", "project", "system"]
```

**Impact**: 
- Intel ingests use "technical" but it's not in the remember tool enum
- LLM gets confused about which categories to use
- Example: httpbin URL saved as "other" (vague) instead of "location" or "technical"

**Fix**: Harmonize categories across all tools

### 2. **LLM Not Always Searching Memory** (Priority: High)

**Test Case**: "When do I celebrate my birth date?"
- **Expected**: Call `semantic_recall` → Find "birthday: December 25th" → Answer
- **Actual**: Respond directly "I don't have your birth date"
- **Why**: LLM didn't route to memory search tool

**Root Cause**: 
- System prompt has guidance (line 97: "ALWAYS use recall/search_memory/semantic_recall FIRST")
- But LLM sometimes ignores it (probabilistic behavior)

**Possible Fixes**:
1. **Strengthen system prompt** with more examples
2. **Add explicit memory check** in orchestrator before QA response
3. **Train/fine-tune** model to prefer memory tools for "what/when/who" questions

### 3. **Importance Scoring Inconsistent** (Priority: Medium)

**Observations**:
- Birthday: importance 9 (good - personal data is important)
- Favorite color: importance 5 (seems low for personal preference)
- Webhook URL: importance 5 (depends - test URLs are ephemeral, but project URLs should be higher)
- Intel files: importance 8 (good default for technical knowledge)

**Issue**: LLM is choosing importance somewhat randomly

**Fix**: Add guidance to tool description about importance scoring

### 4. **Search Strategy Unclear** (Priority: Medium)

**Current State**:
- `search_memory`: Text search in knowledge_base (keyword matching)
- `semantic_recall`: Vector search in knowledge_base (conceptual matching)
- `search_conversations`: Text search in conversations table
- `recall`: Exact key lookup (deprecated?)

**Problem**: LLM doesn't know which tool to use when

**Example Confusion**:
- "When do I celebrate my birth date?" → Should use `semantic_recall` (conceptual: "celebrate" ≈ "birthday")
- "What's my birthday?" → Could use `search_memory` (keyword: "birthday")
- "Tell me about that webhook I sent" → Should use `search_conversations` (action history, not stored fact)

**Fix**: Add clearer guidance in system prompt about tool selection

## Proposed Fixes

### Fix 1: Harmonize Categories (CRITICAL)

Update `remember.tool.json` to include all categories:

```json
"category": {
  "type": "string",
  "enum": [
    "contact",      // People (doctor, dentist, friend names)
    "personal",     // Personal facts (birthday, family, bio)
    "preference",   // User preferences (favorite food, settings)
    "location",     // Places, URLs, endpoints, addresses
    "technical",    // Technical knowledge (commands, configs, solutions)
    "network",      // Network info (IPs, VLANs, hosts)
    "credentials",  // Passwords, keys, tokens
    "project",      // Project paths, repos, build commands
    "system",       // Internal tracking (file hashes, etc.)
    "fact"          // General facts
  ],
  "description": "Type of information (use 'location' for URLs/endpoints, 'technical' for commands/configs, 'personal' for birthday/family, 'preference' for favorites)"
}
```

### Fix 2: Strengthen Memory Search Prompting

**Add to router_v2.py system prompt** (after line 100):

```python
**When to use which memory tool:**
- "What's my [thing]?" → search_memory (keyword: "thing")
- "When do I [action]?" → semantic_recall (conceptual match)
- "Tell me about that [recent action]" → search_conversations (for things you DID)
- "What did I say about [topic]?" → search_conversations (past conversations)

**Examples:**
✅ "When is my birthday?" → semantic_recall (query: "birthday")
✅ "What's my favorite food?" → search_memory (query: "favorite food")  
✅ "What webhook did I test earlier?" → search_conversations (query: "webhook")
✅ "Show me that API I built last week" → search_conversations (query: "API")

**Critical**: If user asks about personal info (birthday, family, preferences), ALWAYS check memory first.
```

### Fix 3: Importance Scoring Guidance

**Update remember.tool.json description**:

```json
"importance": {
  "type": "integer",
  "description": "How important this is (1-10): Critical personal data (birthday, family) = 9-10, Important preferences/projects = 7-8, Useful technical knowledge = 5-6, Temporary/test data = 3-4, Ephemeral data = 1-2",
  "minimum": 1,
  "maximum": 10
}
```

### Fix 4: Auto-Save Intelligence Enhancement

**Add to router_v2.py system prompt** (after line 124):

```python
**Smart Category Selection:**
- User shares birthday, family info → category: "personal", importance: 9
- User shares favorite food, color → category: "preference", importance: 7
- You build a project → category: "project", importance: 8
- You deploy to URL/port → category: "location", importance: 8
- You find a working solution → category: "technical", importance: 7
- Test data (webhooks to httpbin, etc.) → importance: 3 (or don't save at all)

**DO NOT SAVE:**
- Temporary test URLs (httpbin.org, webhook.site)
- Current time/date
- Current crypto prices (unless user explicitly asks to remember a milestone)
- One-time API responses (unless user asks to save it)
```

### Fix 5: Semantic Search Integration

**Option A**: Automatic memory check in orchestrator (less flexible)
**Option B**: Strengthen LLM prompting (more flexible) ← **RECOMMENDED**

Strengthen the system prompt to make memory searches MORE compelling:

```python
**MEMORY-FIRST APPROACH:**
Before answering ANY question about:
- User's personal info (birthday, family, name, etc.)
- User's preferences (favorites, settings, etc.)
- Past projects/builds/deployments
- Commands/configs you've set up

→ ALWAYS search memory FIRST (semantic_recall or search_memory)

If you don't find it → THEN say "I don't have that stored"
If you find it → Use it in your response

**Never guess or assume user data - ALWAYS check memory.**
```

## Testing Strategy

After implementing fixes, test these scenarios:

### Test 1: Semantic Recall
```bash
./orchestrator/orchestrator_v2.py cloud "Remember my birthday is March 15th"
./orchestrator/orchestrator_v2.py cloud "When do I celebrate my birth date?"
# Expected: Should find "birthday" via semantic_recall
```

### Test 2: Smart Categorization
```bash
./orchestrator/orchestrator_v2.py cloud "Remember my doctor is Dr. Smith"
# Expected: category="contact", importance=8

./orchestrator/orchestrator_v2.py cloud "Remember I love pizza"
# Expected: category="preference", importance=7
```

### Test 3: Auto-Save After Build
```bash
./orchestrator/orchestrator_v2.py cloud "Use OpenCode to create a simple Express API on port 8091"
# Expected: After build, should call remember() with:
#   category="project", key="Express API location", value="~/jarvis-workspace/...", importance=8
#   category="location", key="Express API endpoint", value="http://localhost:8091", importance=8
```

### Test 4: Don't Save Ephemeral
```bash
./orchestrator/orchestrator_v2.py cloud "What time is it?"
# Expected: Should NOT call remember() - time is ephemeral

./orchestrator/orchestrator_v2.py cloud "What's Bitcoin price?"
# Expected: Should NOT call remember() - price changes constantly
```

### Test 5: Search Conversations vs Knowledge
```bash
./orchestrator/orchestrator_v2.py cloud "Send a webhook to httpbin.org"
./orchestrator/orchestrator_v2.py cloud "What webhook did I just test?"
# Expected: Should call search_conversations (recent action), not semantic_recall
```

## Implementation Priority

1. **High Priority** (Do immediately):
   - [ ] Fix category mismatch (harmonize remember.tool.json)
   - [ ] Add importance scoring guidance
   - [ ] Strengthen "ALWAYS check memory first" in system prompt

2. **Medium Priority** (Next iteration):
   - [ ] Add tool selection guidance (which search to use when)
   - [ ] Add smart category selection examples
   - [ ] Enhance auto-save guidance with "DO NOT SAVE" section

3. **Low Priority** (Future enhancement):
   - [ ] Consider automatic memory check in orchestrator
   - [ ] Consider memory TTL (expire ephemeral data)
   - [ ] Consider memory importance-based retention policy

## Expected Outcome

After these fixes:
- ✅ LLM consistently searches memory before answering personal questions
- ✅ Categories are meaningful and consistent
- ✅ Importance scores reflect actual value (birthday=9, test data=3)
- ✅ Auto-save happens for valuable data (projects, deployments)
- ✅ Ephemeral data NOT saved (time, temp prices, test URLs)
- ✅ Conversation history used appropriately (recent actions)

**Result**: Production-level intelligent memory system 🎯

