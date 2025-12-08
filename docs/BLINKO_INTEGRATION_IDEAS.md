# Blinko Integration with Jarvis - Exploration

> **Status**: Exploration / Design Phase  
> **Created**: 2025-12-06  
> **Blinko**: [GitHub](https://github.com/blinkospace/blinko) | [API Docs](https://blinko.apidocumentation.com/reference)

---

## 🎯 Executive Summary

**Blinko** is an AI-powered card-based note-taking system with RAG (Retrieval-Augmented Generation) capabilities. This document explores how Blinko could complement Jarvis's existing memory system without creating redundancy.

**Key Insight**: Keep them **separate but connected** - Blinko as the user-facing knowledge UI, Jarvis memory_db as the system's operational knowledge.

---

## 📊 Current State Analysis

### What Jarvis Has (Knowledge Systems)

| System | Purpose | Technology | Access |
|--------|---------|------------|--------|
| **memory_db** | Operational knowledge (facts, preferences) | SQLite + embeddings | API/CLI/Voice |
| **Canvas** | Visual content viewer (research, code) | Flask web UI | Browser (localhost:8890) |
| **Intel Files** | Bulk knowledge ingestion | Markdown files | File system |
| **Conversation History** | Full interaction logs | SQLite | API/CLI |

### What Blinko Offers

| Feature | Technology | Benefit |
|---------|------------|---------|
| **Card-based Notes** | React/Tauri UI | Rich, organized note-taking |
| **AI RAG Search** | Embeddings + vector search | Natural language note retrieval |
| **Multi-platform** | macOS, Windows, Android, Linux | Access notes anywhere |
| **Markdown Support** | Full MD rendering | Quick formatting |
| **PostgreSQL** | Robust database | Better than SQLite for notes |
| **Self-hosted** | Docker | Data ownership |

---

## 🤔 Key Questions

### 1. **Why Add Blinko When Jarvis Has Memory?**

**Different Use Cases:**

| Use Case | Best Tool | Reason |
|----------|-----------|--------|
| "Remember my VPN is 192.168.70.0/24" | **Jarvis memory_db** | System operational fact |
| "Note: Meeting with Sarah - discussed Q4 roadmap, budget concerns, hiring freeze" | **Blinko** | Rich user note with context |
| "Save this API endpoint" | **Jarvis memory_db** | Tool will use it |
| "Journal entry: Today's reflections on project architecture..." | **Blinko** | Personal knowledge capture |
| "Research on Kubernetes best practices" | **Canvas** (then optionally Blinko) | Visual + long-term reference |

**Separation of Concerns:**
- **Jarvis memory_db**: "What does the system need to remember to function?"
- **Blinko**: "What do I (the user) want to capture and reflect on?"

### 2. **Won't This Duplicate Canvas?**

**No - Different Purposes:**

| Feature | Canvas | Blinko |
|---------|--------|--------|
| **Purpose** | Temporary visual display | Permanent note storage |
| **Lifespan** | Session/research-based | Long-term knowledge base |
| **Access** | Web UI during research | Multi-platform, always available |
| **Search** | Simple list/search | AI RAG semantic search |
| **Organization** | Pages (flat) | Cards with tags, AI categorization |
| **Mobile** | No | Yes (Android app) |

**Workflow Example:**
1. Jarvis researches topic → saves to **Canvas** (immediate visual review)
2. User reviews Canvas → decides to save summary to **Blinko** (long-term storage)
3. Weeks later → user searches Blinko for "that research I did on..."

### 3. **API Complexity - Too Many Routes?**

**Solution: Minimal Tool Approach**

Instead of exposing all API routes, create a **focused tool** with only essential operations:

```python
# blinko_notes.py - Minimal integration
Operations:
1. create_note(content, tags=[])      # POST /api/v1/note
2. search_notes(query, limit=5)       # GET /api/v1/note/list with search
3. get_recent_notes(limit=10)         # GET /api/v1/note/list
4. update_note(note_id, content)      # PATCH /api/v1/note/{id}
```

**That's it!** 4 operations = ~100 lines of code. No context window flooding.

---

## 🔄 Integration Strategies

### Strategy 1: **Manual Workflow** (Lowest Integration)

**Setup:**
- Run Blinko in Docker on host (port 1111)
- No Jarvis tool integration
- User manually copies info from Jarvis → Blinko

**Pros:**
- ✅ Zero code changes
- ✅ Complete separation
- ✅ Can evaluate Blinko independently

**Cons:**
- ❌ Manual copy/paste friction
- ❌ Can't leverage voice commands

**Verdict:** Good for **trial period** (1-2 weeks evaluation)

---

### Strategy 2: **Minimal Tool Integration** (Recommended)

**Setup:**
- Create `blinko_notes` tool (4 operations)
- Jarvis can save notes via voice/CLI
- Blinko remains independent system

**Architecture:**
```
USER: "Save this to my notes: Meeting insights..."
  ↓
JARVIS: Routes to blinko_notes tool
  ↓
TOOL: POST to Blinko API
  ↓
BLINKO: Stores note with AI embeddings
  ↓
USER: Later searches Blinko UI or via Jarvis
```

**Pros:**
- ✅ Voice-enabled note capture
- ✅ Leverages Blinko's RAG for retrieval
- ✅ Minimal code (~100 lines)
- ✅ Independent systems (easy to remove)

**Cons:**
- ❌ Another service to maintain
- ❌ Potential overlap with memory_db (needs discipline)

**Verdict:** **Best balance** of integration vs. complexity

---

### Strategy 3: **Deep Integration** (Overkill)

**Setup:**
- Replace Jarvis memory_db with Blinko
- Use Blinko as primary knowledge store
- Heavy API usage

**Pros:**
- ✅ Single source of truth
- ✅ Better UI for knowledge management

**Cons:**
- ❌ **High coupling** - hard to remove
- ❌ Blinko downtime = Jarvis broken
- ❌ Performance overhead (HTTP vs direct SQLite)
- ❌ Complex migration
- ❌ Loses Jarvis's tight memory integration

**Verdict:** **NOT RECOMMENDED** - too tightly coupled

---

## 💡 Recommended Use Cases

### When to Use **Jarvis memory_db**

```bash
✅ System facts:
   "My VPN network is 192.168.70.0/24"
   "The n8n webhook URL is https://..."
   "OpenCode workspace is ~/jarvis-workspace"

✅ Operational preferences:
   "I prefer detailed responses"
   "Always use qwen3 for local mode"

✅ Quick lookups:
   "What's my VPN network?" → Fast FTS5/embedding search
```

### When to Use **Blinko**

```bash
✅ Rich notes with context:
   "Meeting notes: Discussed Q4 roadmap. Key points:
    - Budget freeze affecting hiring
    - Need to prioritize features A, B, C
    - Sarah concerned about timeline"

✅ Journal entries:
   "Reflection on today's coding session: Learned that
    Rust's borrow checker is both frustrating and helpful..."

✅ Research summaries:
   "Investigation into Kubernetes networking:
    - CNI plugins comparison
    - Service mesh options (Istio vs Linkerd)
    - Best practices for ingress controllers"

✅ Project documentation:
   "Flask API project notes:
    - Uses port 8091
    - JWT auth implemented
    - TODO: Add rate limiting"
```

### When to Use **Canvas**

```bash
✅ Temporary visual display:
   "Save this API comparison to Canvas for review"
   "Show me the code structure visually"

✅ During active research:
   "I'm researching Docker networking - save findings to Canvas"
```

---

## 🛠️ Implementation Plan (If Proceeding)

### Phase 1: Evaluation (1-2 weeks)

**Goal:** Determine if Blinko fits your workflow

```bash
# 1. Install Blinko
curl -s https://raw.githubusercontent.com/blinko-space/blinko/main/install.sh | bash

# 2. Access UI
open http://localhost:1111

# 3. Manual testing
# - Add notes manually via UI
# - Test AI search
# - Try mobile app
# - Evaluate: "Do I actually use this?"
```

**Decision Point:**
- ✅ If you're using it daily → proceed to Phase 2
- ❌ If it feels redundant → stick with Jarvis memory + Canvas

---

### Phase 2: Minimal Integration

**Goal:** Voice-enable Blinko note creation

**Step 1: Create Tool**

```python
# skills/auto-tools/blinko_notes.py
#!/usr/bin/env python3
"""
Blinko Notes Integration - Save and search notes in Blinko.

Operations:
- create: Save a note to Blinko
- search: Search notes using Blinko's AI RAG
- recent: Get recent notes
"""
import sys
import os
import json
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config, get_config_value

def create_note(content: str, tags: list = None, is_archived: bool = False):
    """Create a note in Blinko."""
    base_url = get_config_value('BLINKO_BASE_URL', 'http://localhost:1111')
    api_key = get_config_value('BLINKO_API_KEY')
    
    response = requests.post(
        f"{base_url}/api/v1/note",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "content": content,
            "type": 0,  # Note type
            "isArchived": is_archived,
            "attachments": [],
            "tags": tags or []
        },
        timeout=10
    )
    response.raise_for_status()
    return response.json()

def search_notes(query: str, limit: int = 5):
    """Search notes using Blinko's AI."""
    base_url = get_config_value('BLINKO_BASE_URL', 'http://localhost:1111')
    api_key = get_config_value('BLINKO_API_KEY')
    
    response = requests.get(
        f"{base_url}/api/v1/note/list",
        headers={"Authorization": f"Bearer {api_key}"},
        params={
            "searchText": query,
            "size": limit,
            "page": 1
        },
        timeout=10
    )
    response.raise_for_status()
    data = response.json()
    return data.get('notes', [])

def get_recent_notes(limit: int = 10):
    """Get recent notes."""
    base_url = get_config_value('BLINKO_BASE_URL', 'http://localhost:1111')
    api_key = get_config_value('BLINKO_API_KEY')
    
    response = requests.get(
        f"{base_url}/api/v1/note/list",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"size": limit, "page": 1},
        timeout=10
    )
    response.raise_for_status()
    data = response.json()
    return data.get('notes', [])

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        operation = args.get('operation', 'create')
        
        if operation == 'create':
            content = args.get('content')
            if not content:
                raise ValueError("content is required for create operation")
            
            tags = args.get('tags', [])
            result = create_note(content, tags)
            
            print(json.dumps({
                "ok": True,
                "speech": "Note saved to Blinko",
                "data": {"note_id": result.get('id'), "content": content[:100]}
            }))
        
        elif operation == 'search':
            query = args.get('query')
            if not query:
                raise ValueError("query is required for search operation")
            
            limit = args.get('limit', 5)
            notes = search_notes(query, limit)
            
            if notes:
                summaries = [f"{n.get('content', '')[:100]}..." for n in notes[:3]]
                speech = f"Found {len(notes)} notes. Top results: {'; '.join(summaries)}"
            else:
                speech = "No notes found matching your query"
            
            print(json.dumps({
                "ok": True,
                "speech": speech,
                "data": {"notes": notes, "count": len(notes)}
            }))
        
        elif operation == 'recent':
            limit = args.get('limit', 10)
            notes = get_recent_notes(limit)
            
            print(json.dumps({
                "ok": True,
                "speech": f"Retrieved {len(notes)} recent notes",
                "data": {"notes": notes, "count": len(notes)}
            }))
        
        else:
            raise ValueError(f"Unknown operation: {operation}")
    
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Blinko error: {e}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()
```

**Step 2: Tool JSON**

```json
{
  "enabled": true,
  "name": "blinko_notes",
  "description": "Save and search notes in Blinko note-taking system. Use for: 'save this note to Blinko', 'search my Blinko notes for X', 'what are my recent notes'. Blinko is for rich user notes (meetings, reflections, research), NOT system facts (use remember/recall for that).",
  "script": "blinko_notes.py",
  "parameters": {
    "type": "object",
    "properties": {
      "operation": {
        "type": "string",
        "enum": ["create", "search", "recent"],
        "description": "Operation: create (save note), search (AI search), recent (list recent)"
      },
      "content": {
        "type": "string",
        "description": "Note content (for create operation)"
      },
      "query": {
        "type": "string",
        "description": "Search query (for search operation)"
      },
      "tags": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Tags for the note (optional)"
      },
      "limit": {
        "type": "integer",
        "description": "Result limit (for search/recent)"
      }
    },
    "required": ["operation"]
  },
  "permissions": {
    "dangerous": false,
    "bash": false,
    "network": true,
    "filesystem": false,
    "auto_approve": true
  }
}
```

**Step 3: Configuration**

Add to `config/cloud.env` and `config/local.env`:

```bash
# Blinko Integration (optional)
BLINKO_BASE_URL="http://localhost:1111"
BLINKO_API_KEY="your-api-key-here"
```

**Step 4: Test**

```bash
# Sync tool
./bin/sync_tools.py cloud

# Test via CLI
./orchestrator/orchestrator_v2.py cloud "Save this to Blinko: Today I learned about Rust's ownership model. Key insight: borrowing prevents data races at compile time."

# Test search
./orchestrator/orchestrator_v2.py cloud "Search my Blinko notes for Rust"

# Test via voice
./jarvis
# Say: "Hey Jarvis, save to Blinko: Meeting with team about Q4 priorities"
```

---

### Phase 3: Workflow Refinement (Optional)

**Auto-save conversation summaries:**

```python
# In orchestrator_v2.py (optional enhancement)
def _save_to_blinko_if_important(self, conversation_summary):
    """Optionally save important conversations to Blinko."""
    # Heuristics:
    # - Multi-turn conversations (>3 turns)
    # - OpenCode builds
    # - Research queries
    # - User explicitly says "save this"
    
    if self._is_important_conversation(conversation_summary):
        # Call blinko_notes tool
        pass
```

**Smart prompting:**

Add to LLM system prompt:
```
If the user asks to "take a note" or "save this for later", use blinko_notes.
For system facts like API keys, ports, URLs, use remember instead.
```

---

## ⚖️ Pros vs Cons

### Pros of Integration

| Benefit | Impact |
|---------|--------|
| **Rich note-taking UI** | Better than SQLite CLI |
| **Mobile access** | Access notes from phone |
| **AI RAG search** | Natural language retrieval |
| **Voice-enabled** | "Save to Blinko via Jarvis" |
| **Cross-platform** | Works on all devices |
| **Visual organization** | Cards, tags, better than flat DB |

### Cons of Integration

| Risk | Mitigation |
|------|------------|
| **Maintenance overhead** | Keep integration minimal (4 operations) |
| **Potential confusion** | Clear guidelines: Blinko=notes, memory=facts |
| **Another service** | Use Docker, systemd for auto-start |
| **API dependency** | Graceful fallback if Blinko down |
| **Overlap with Canvas** | Different purposes (see comparison above) |

---

## 🎯 Decision Framework

### Use This Decision Tree:

```
1. Do you frequently want to capture rich, contextual notes?
   NO  → Don't integrate, use Jarvis memory + Canvas
   YES → Continue to #2

2. Do you want multi-platform access (phone, tablet)?
   NO  → Canvas might be enough
   YES → Continue to #3

3. Are you willing to maintain another Docker service?
   NO  → Stick with existing tools
   YES → Continue to #4

4. Can you maintain discipline between Blinko (notes) vs memory_db (facts)?
   NO  → Risk of confusion, don't integrate
   YES → ✅ PROCEED with minimal integration
```

---

## 📚 Comparison with Alternatives

### Alternative 1: **Obsidian + Syncthing**

| Feature | Blinko | Obsidian + Syncthing |
|---------|--------|---------------------|
| AI Search | ✅ Built-in RAG | ❌ Manual search |
| Self-hosted | ✅ Docker | ⚠️ File sync only |
| API | ✅ REST API | ❌ No API |
| Mobile | ✅ Native app | ✅ Obsidian mobile |
| Complexity | Medium | Low |
| Integration | Easy (API) | Hard (file-based) |

**Verdict:** Blinko better for Jarvis integration

### Alternative 2: **Notion**

| Feature | Blinko | Notion |
|---------|--------|--------|
| Self-hosted | ✅ | ❌ Cloud only |
| AI Search | ✅ | ✅ |
| API | ✅ | ✅ |
| Privacy | ✅ | ❌ Data on their servers |

**Verdict:** Blinko wins on privacy/self-hosting

### Alternative 3: **Just Use Jarvis Memory + Canvas**

| Feature | Memory + Canvas | Blinko Integration |
|---------|----------------|-------------------|
| Setup | ✅ Already there | ⚠️ New service |
| Voice control | ✅ | ✅ (via tool) |
| Mobile | ❌ | ✅ |
| Rich UI | ⚠️ Basic | ✅ Advanced |
| Note organization | ❌ Flat | ✅ Cards + tags |

**Verdict:** Blinko adds value if you need mobile + better UI

---

## 🚀 Recommendation

### **Start with Strategy 2 (Minimal Integration)**

**Implementation Timeline:**

**Week 1-2: Evaluation**
- Install Blinko, use manually
- Determine if it fits your workflow
- No code changes yet

**Week 3: Implementation** (if evaluation positive)
- Create `blinko_notes` tool (4 operations)
- Add config vars
- Test via CLI and voice

**Week 4+: Refinement**
- Add to common workflows
- Refine when to use Blinko vs memory_db
- Optional: auto-save important conversations

**Exit Strategy:**
- If not useful after 1 month → simply disable the tool
- Zero coupling = easy removal

---

## 📝 Summary

**TL;DR:**
1. **Keep them separate** - Blinko for rich user notes, Jarvis memory for system facts
2. **Minimal tool integration** - Just 4 operations (create, search, recent, update)
3. **Trial first** - Use Blinko manually for 1-2 weeks before coding
4. **Clear boundaries** - Blinko=notes, memory=facts, Canvas=visual/temporary

**Next Steps:**
1. ✅ Read this document
2. ⏸️ Install Blinko, trial for 1-2 weeks
3. ⏸️ If valuable → implement minimal tool
4. ⏸️ Refine workflow over time

---

**References:**
- [Blinko GitHub](https://github.com/blinkospace/blinko)
- [Blinko API Docs](https://blinko.apidocumentation.com/reference)
- [Blinko Live Demo](https://demo.blinko.space) (username: blinko, password: blinko)

