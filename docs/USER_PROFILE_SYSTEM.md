# User Profile System

## Overview

Jarvis supports **two complementary approaches** for user profile management:

1. **Intel Files** (Static baseline) - Comprehensive documentation
2. **Profile Memories** (Dynamic updates) - Real-time preference learning

---

## Approach 1: Intel File (Recommended for Baseline)

### Location
`jarvis-intel/user_profile.md` or `jarvis-intel/user_profile_enhanced.md`

### When to Use
- ✅ Initial setup / comprehensive profile
- ✅ Technical stack documentation
- ✅ Communication style preferences
- ✅ Environment-specific notes
- ✅ Project context

### How It Works

**1. Create/Edit Intel File**:
```markdown
# User Profile
## Technical Preferences
- Prefer FastAPI over Flask
- Use Docker for all deployments
- Port range: 8091+

## Communication Style
- Direct, technical, no hand-holding
- Code first, explanations second
```

**2. Ingest**:
```bash
./skills/ingest_intel.py '{"path":"jarvis-intel"}'
```

**3. Jarvis Uses It**:
- Semantic search finds relevant profile info automatically
- Context influences tool selection and response style
- Persists across sessions

### Advantages
✅ Version controlled (git)  
✅ Comprehensive documentation  
✅ Survives database resets  
✅ Easy manual editing  

### Limitations
⚠️ Requires manual re-ingest after updates  
⚠️ Not immediately updated  

---

## Approach 2: Profile Memories (Dynamic Updates)

### Category: `profile`

Use the `remember` tool with category `profile` for dynamic preferences.

### When to Use
- ✅ Real-time preference updates
- ✅ Learning from corrections
- ✅ Temporary context (current project focus)
- ✅ Quick preference changes

### How It Works

**User**: "I prefer Next.js over Express for new web projects now"

**Jarvis**: 
```bash
remember(
    category="profile",
    key="web_framework_preference",
    value="Next.js (preferred over Express for new projects)",
    importance=8
)
```

**Later Query**: "Build a web dashboard"

**Jarvis Internal Context**:
- Checks `search_memory("web framework preference")` → Finds Next.js preference
- Builds with Next.js instead of defaulting to Express

### Advantages
✅ Immediate updates (no re-ingest needed)  
✅ Survives across sessions  
✅ Synced between cloud/local  
✅ Can be updated by both user and LLM  

### Limitations
⚠️ Lost on database reset (unless backed up)  
⚠️ Not version controlled  
⚠️ May need cleanup over time  

---

## Hybrid Approach (Best Practice) 🌟

**Use BOTH for maximum effectiveness**:

### Intel File = Baseline
Comprehensive, stable, rarely changing information:
- Technical stack
- Infrastructure details
- Communication style
- Project list
- Environment specifics

### Profile Memories = Dynamic Layer
Real-time updates and learning:
- Current focus ("Working on X project this week")
- Temporary preferences ("Testing Y framework")
- Learned corrections ("User prefers Z approach")
- Session context ("Debugging issue with Q")

### Example Workflow

**Initial Setup**:
```bash
# 1. Create comprehensive intel file
vim jarvis-intel/user_profile.md

# 2. Ingest it
./skills/ingest_intel.py '{"path":"jarvis-intel"}'
```

**Dynamic Updates**:
```bash
# User: "I'm focusing on the monitoring project this week"
# Jarvis remembers:
remember(
    category="profile",
    key="current_focus",
    value="jarvis-monitor project - remote monitoring with Docker agents",
    importance=7
)

# User: "I prefer pnpm over npm now"
# Jarvis remembers:
remember(
    category="profile",
    key="nodejs_package_manager",
    value="pnpm (preferred over npm/yarn)",
    importance=8
)
```

**Jarvis Behavior**:
When you ask "Add feature X to monitoring", Jarvis:
1. Searches memories for "monitoring" + "current_focus"
2. Finds jarvis-monitor context
3. Searches for package manager preference
4. Uses pnpm in commands

---

## Auto-Update Mechanism (Experimental)

### Pattern Recognition

Jarvis can learn to suggest profile updates based on patterns:

**Example 1: Tool Preference Shift**
```
User asks: "Build X with Bun"
User asks: "Create Y with Bun" (different day)
User asks: "Set up Z with Bun"

Jarvis notices pattern → Suggests:
"I notice you've used Bun for the last 3 projects. Should I remember that you 
prefer Bun over Node.js for new projects?"

User: "Yes" → Jarvis calls remember()
```

**Example 2: Correction Pattern**
```
Jarvis suggests: Flask for API
User: "Use FastAPI instead"

Jarvis suggests: Flask for API (next time)
User: "I said FastAPI"

Jarvis: "I notice you prefer FastAPI over Flask. Should I remember this?"
User: "Yes" → Jarvis calls remember()
```

### Implementation Status
🚧 **Not yet implemented** - Would require:
- Pattern tracking across conversations
- Threshold for "noticed pattern"
- Confirmation mechanism

---

## Profile Query Patterns

### How Jarvis Uses Your Profile

**Automatic Context Injection**:
When you ask a question, Jarvis can automatically:
1. Search memories for profile-related context
2. Apply preferences to tool selection
3. Format responses in your preferred style

**Example Flow**:
```
User: "Build a monitoring dashboard"

Jarvis internally:
1. search_memory("technical preferences docker")
   → Finds: "Use Docker for all deployments, port 8091+"
2. search_memory("monitoring project")
   → Finds: "Current focus: jarvis-monitor"
3. Decides: FastAPI + Docker + port 8091 + connect to jarvis-monitor

Response: Complete Dockerfile, docker-compose.yml, FastAPI code
```

### Explicit Profile Queries

**Check what Jarvis knows**:
```bash
"What do you know about my preferences?"
"What's my current project focus?"
"Show me my profile"
```

Jarvis will use `search_memory` or `semantic_recall` to find profile info.

---

## Managing Profile Memories

### View Profile Memories
```bash
# Search for all profile-category memories
"Show me all my profile preferences"

# Jarvis uses:
search_memory(query="profile", category="profile", limit=50)
```

### Update Profile Memory
```bash
# User: "Update my package manager preference to pnpm"

# Jarvis:
update_memory(
    search_query="package manager preference",
    category="profile",
    new_value="pnpm (preferred over npm/yarn)",
    importance=8
)
```

### Remove Profile Memory
```bash
# User: "Forget my current project focus"

# Jarvis:
# 1. Searches for memory
# 2. Calls forget(memory_id)
```

---

## Best Practices

### ✅ DO

**Intel File**:
- Store stable, comprehensive information
- Include technical stack details
- Document communication preferences
- List active projects and infrastructure

**Profile Memories**:
- Store temporary context ("focusing on X this week")
- Learn from corrections ("prefers Y over Z")
- Track evolving preferences
- Use high importance (7-9) for core preferences

### ❌ DON'T

**Never Store**:
- ❌ Credentials, API keys, passwords
- ❌ Sensitive personal information beyond technical context
- ❌ Frequently changing data that belongs in memory (use regular memories)
- ❌ Duplicate info (if it's in intel file, no need in profile memory)

**Avoid**:
- ⚠️ Overly specific one-time preferences
- ⚠️ Information that contradicts intel file (update intel file instead)
- ⚠️ Non-technical personal details

---

## Profile Categories Structure

### Recommended Memory Keys

```
profile/technical_preferences
profile/communication_style
profile/current_focus
profile/framework_preferences
profile/deployment_preferences
profile/tool_preferences
profile/environment_context
```

### Example Memories

```python
# Technical preference
{
    "category": "profile",
    "key": "api_framework_preference",
    "value": "FastAPI for Python APIs (over Flask/Django)",
    "importance": 8
}

# Communication style
{
    "category": "profile",
    "key": "response_style",
    "value": "Direct, technical, no hand-holding. Provide complete code.",
    "importance": 9
}

# Current focus
{
    "category": "profile",
    "key": "current_project_focus",
    "value": "Working on jarvis-monitor (remote Docker monitoring) this week",
    "importance": 7
}

# Tool preference
{
    "category": "profile",
    "key": "package_manager",
    "value": "pnpm for Node.js projects",
    "importance": 8
}
```

---

## Integration with Other Systems

### Auto-Context System
Profile memories are separate from auto-context (recent conversation history).

**Auto-Context**: Last 3 conversations  
**Profile**: Persistent preferences

### Tool RAG
Profile preferences can influence tool selection:
- If profile says "prefer local AI", prioritize Ollama tools
- If profile says "Docker-first", suggest Docker-based solutions

### Semantic Threshold
Profile memories should have high importance (7-9) to ensure they're found even with higher similarity thresholds.

---

## Maintenance

### Periodic Review
Recommended: Monthly review of profile memories

```bash
# List all profile memories
"Show me all my profile preferences sorted by importance"

# Jarvis shows list, you can then:
# - Update outdated preferences
# - Remove obsolete ones
# - Consolidate duplicates
```

### Backup & Restore
Profile memories are in the database, so they're included in database sync.

**Backup**:
```bash
# Profile memories are synced with:
./bin/sync-memory-db.py --from local --to cloud
```

**Restore**:
```bash
# After database reset, re-ingest intel file:
./skills/ingest_intel.py '{"path":"jarvis-intel"}'

# Profile memories are automatically synced on startup
```

---

## Future Enhancements

### Planned Features
- 🔮 **Auto-profile learning**: Detect patterns and suggest updates
- 🔮 **Profile versioning**: Track how preferences change over time
- 🔮 **Profile templates**: Quick setup for common user types
- 🔮 **Profile export/import**: Share preferences across instances

### Experimental Ideas
- **Context-aware profile injection**: Only inject relevant parts of profile based on query type
- **Profile confidence scoring**: Track how often preferences are followed vs corrected
- **Multi-user profiles**: Support multiple users with separate profiles

---

## Summary

**Best Approach**: Use BOTH

| Aspect | Intel File | Profile Memories |
|--------|------------|------------------|
| **Stability** | High (rarely changes) | Low (updates frequently) |
| **Scope** | Comprehensive | Specific preferences |
| **Update Method** | Manual edit + ingest | remember tool |
| **Persistence** | Git + embeddings | Database |
| **Best For** | Baseline context | Real-time learning |

**Example Timeline**:
1. **Initial Setup**: Create comprehensive intel file
2. **First Week**: Jarvis learns corrections → profile memories
3. **Monthly**: Review profile memories, consolidate to intel file
4. **As Needed**: Update intel file for major changes

This hybrid approach gives you both stability and flexibility!

