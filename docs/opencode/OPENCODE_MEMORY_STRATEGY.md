# OpenCode Memory Strategy

## The Problem

Not all memories are useful for OpenCode. We need to distinguish:

**❌ Conversational Memory** (Jarvis-only):
- "I like ice cream"
- "My favorite restaurant is Thai Bloom"
- "I prefer casual conversation"

**✅ Technical Memory** (OpenCode-relevant):
- Network topology and service IPs
- Command patterns and procedures
- Coding preferences and standards
- Project structures and patterns
- Deployment procedures

## Real-World Use Cases

### 1. Network Topology & Services
```python
# Store in memory (category: "network_topology")
{
    "key": "pihole_server",
    "value": "PiHole running at 192.168.1.2:80, admin password in 1Password",
    "category": "network_topology"
}

{
    "key": "amazon_firetv",
    "value": "Fire TV at 192.168.1.15, use adb for control",
    "category": "network_topology"
}

{
    "key": "ollama_server",
    "value": "Ollama at OLLAMA_BASE_URL:11434 (remote on mini-ai)",
    "category": "network_topology"
}
```

**OpenCode can use this to:**
- Generate monitoring scripts
- Create service health check dashboards
- Build automation for reboots/restarts
- Write network diagnostic tools

### 2. Command Patterns
```python
# Store in memory (category: "command_pattern")
{
    "key": "restart_nginx",
    "value": "sudo systemctl restart nginx && sudo systemctl status nginx",
    "category": "command_pattern"
}

{
    "key": "check_docker_logs",
    "value": "docker logs --tail 100 -f <container_name>",
    "category": "command_pattern"
}

{
    "key": "deploy_flask_app",
    "value": "cd /app && source venv/bin/activate && gunicorn -w 4 -b 0.0.0.0:8000 app:app",
    "category": "command_pattern"
}
```

**OpenCode can use this to:**
- Generate scripts with correct patterns
- Build deployment automation
- Create service management tools

### 3. Coding Preferences
```python
# Store in memory (category: "coding_preference")
{
    "key": "python_style",
    "value": "Use type hints, prefer async/await, pytest over unittest, black formatting",
    "category": "coding_preference"
}

{
    "key": "docker_preference",
    "value": "Multi-stage builds, Alpine base, non-root user, minimal layers",
    "category": "coding_preference"
}

{
    "key": "api_design",
    "value": "RESTful, versioned (/api/v1/), proper HTTP status codes, JSON responses",
    "category": "coding_preference"
}
```

**OpenCode can use this to:**
- Generate code matching your style
- Build Dockerfiles your way
- Design APIs consistently

### 4. Project Context
```python
# Store in memory (category: "project_context")
{
    "key": "jarvis_project",
    "value": "Voice assistant at /home/boss/jarvis-voice, Python 3.11, uses Ollama/OpenAI",
    "category": "project_context"
}

{
    "key": "active_webapp",
    "value": "Flask app in /workspace/projects/websites/my-app, uses PostgreSQL, Redis cache",
    "category": "project_context"
}
```

**OpenCode can use this to:**
- Understand existing projects
- Make compatible changes
- Add features that fit architecture

---

## OpenCode Session History Strategy

### Current: We Log Everything
`logs/opencode/opencode-YYYY-MM-DD.jsonl` contains full conversations.

**Pros:**
- Complete audit trail
- Debugging information
- Can review what happened

**Cons:**
- Not searchable by meaning
- No way to find "similar past work"
- Can't learn from past sessions

### Proposed: Store Session Summaries with Embeddings

After each OpenCode task completes, create a memory entry:

```python
{
    "key": "opencode_session_20251111_flask_api",
    "value": """
    Built Flask API with user authentication.
    Created:
    - /workspace/projects/websites/auth-api/app.py (234 lines)
    - /routes/users.py, /routes/auth.py
    - PostgreSQL models with SQLAlchemy
    - JWT token authentication
    - Docker compose for local dev
    
    Challenges: Had to fix CORS issues, added middleware
    Duration: 45 seconds
    Model: Claude Sonnet 4
    """,
    "category": "opencode_session",
    "importance": 7,
    "embedding": [0.234, -0.123, ...]  # Vector for semantic search
}
```

**Benefits:**
1. **Learn from past work**: "Build another Flask API like last time"
2. **Avoid past mistakes**: Remember CORS fix needed
3. **Consistent patterns**: Reuse successful approaches
4. **Context-aware**: Only load relevant past sessions

---

## Smart Context Injection

### Current Approach (Basic)
```python
# Get ALL preferences
preferences = db.recall(query="coding")

# Pass everything to OpenCode
context = {"preferences": preferences}
```

**Problem**: Sends irrelevant info, wastes tokens

### Better Approach (Contextual)
```python
def get_smart_context(task: str, mode: str) -> dict:
    """Intelligently select relevant context for the task."""
    
    context = {
        "relevant_memories": [],
        "preferences": [],
        "past_sessions": [],
        "network_info": []
    }
    
    # 1. Always get coding preferences
    if any(word in task.lower() for word in ["code", "script", "app", "api", "website"]):
        context["preferences"] = db.recall(
            query="coding preference",
            category="coding_preference",
            limit=5
        )
    
    # 2. Get network info if task involves services
    if any(word in task.lower() for word in ["server", "service", "restart", "check", "monitor", "ip", "network"]):
        context["network_info"] = db.recall(
            query=task,
            category="network_topology",
            limit=10
        )
    
    # 3. Get command patterns if task involves bash/deployment
    if any(word in task.lower() for word in ["deploy", "run", "command", "bash", "script"]):
        context["command_patterns"] = db.recall(
            query=task,
            category="command_pattern",
            limit=5
        )
    
    # 4. Find similar past OpenCode sessions (semantic search)
    similar_sessions = db.semantic_search(
        query=task,
        provider=mode,
        category="opencode_session",
        limit=3  # Only top 3 most relevant
    )
    
    # Only include highly relevant sessions (>70% similarity)
    context["past_sessions"] = [
        {
            "summary": session["value"],
            "relevance": f"{session['similarity'] * 100:.0f}%"
        }
        for session in similar_sessions
        if session.get("similarity", 0) > 0.7
    ]
    
    return context
```

---

## Implementation Plan

### Phase 1: Memory Categories ✅ (Already have this)
Add specific categories for technical info:
- `network_topology`
- `command_pattern`
- `coding_preference`
- `project_context`
- `opencode_session`

### Phase 2: Store OpenCode Sessions
After each OpenCode task:
```python
# In skills/opencode.py after task completes
def store_session_summary(result, task, context):
    """Store OpenCode session in memory for future reference."""
    
    # Extract what was done
    summary = f"""
    Task: {task}
    Duration: {result.get('duration_ms', 0)}ms
    Success: {result.get('ok', False)}
    
    Context:
    - Mode: {context['jarvis_mode']}
    - Type: {context['task_type']}
    
    Result: {result.get('speech', 'No summary')}
    """
    
    # Store with embedding for semantic search
    db.remember(
        category="opencode_session",
        key=f"opencode_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        value=summary,
        importance=5,  # Medium importance
        metadata={
            "session_id": result.get('session_id'),
            "model": context.get('model'),
            "success": result.get('ok', False)
        }
    )
```

### Phase 3: Smart Context Selection
Replace current `get_memory_context()` with contextual version above.

---

## Example Scenarios

### Scenario 1: Network Monitoring Script
**User**: "Hey Jarvis, use OpenCode to create a script that monitors my Pi-hole"

**OpenCode receives**:
```python
{
    "network_info": [
        {"key": "pihole_server", "value": "PiHole at 192.168.1.2:80"}
    ],
    "command_patterns": [
        {"key": "check_service_status", "value": "curl -s http://IP:PORT/admin/api.php"}
    ],
    "coding_preference": [
        {"key": "python_style", "value": "Use type hints, async/await"}
    ]
}
```

**OpenCode builds**: Python script with correct IP, async requests, type hints

### Scenario 2: Deploy Flask App (2nd time)
**User**: "Hey Jarvis, use OpenCode to build another Flask API like last time"

**OpenCode receives**:
```python
{
    "past_sessions": [
        {
            "summary": "Built Flask API with JWT auth, PostgreSQL, Docker...",
            "relevance": "95%"
        }
    ],
    "coding_preference": [...]
}
```

**OpenCode builds**: Similar structure, reuses patterns, avoids past issues

### Scenario 3: Restart Service (Plan Mode)
**User**: "Hey Jarvis, how do I restart my Fire TV?"

**OpenCode receives** (plan mode):
```python
{
    "network_info": [
        {"key": "amazon_firetv", "value": "Fire TV at 192.168.1.15, use adb"}
    ],
    "command_patterns": [
        {"key": "adb_reboot", "value": "adb connect IP:5555 && adb reboot"}
    ]
}
```

**OpenCode suggests**: Command to run (doesn't execute)  
**Jarvis translates**: "To restart your Fire TV, run: adb connect 192.168.1.15:5555 && adb reboot"

---

## Token Optimization

**Without smart context**: 5000+ tokens (all memories)  
**With smart context**: 500-1000 tokens (only relevant)

**Savings**: 80-90% reduction in context size

---

## Next Steps

1. **Add memory categories to existing system** ✅ (schema supports this)
2. **Create helper to store OpenCode sessions**
3. **Implement smart context selection**
4. **Add example memories for testing**
5. **Update OpenCode tool to use smart context**

---

## Quick Reference

**Store technical info:**
```bash
./bin/memory remember network_topology pihole_server "PiHole at 192.168.1.2:80"
./bin/memory remember command_pattern restart_nginx "sudo systemctl restart nginx"
./bin/memory remember coding_preference python_style "Use type hints, async/await"
```

**OpenCode will find relevant info automatically via semantic search.**

