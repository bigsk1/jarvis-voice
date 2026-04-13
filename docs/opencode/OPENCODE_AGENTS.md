# OpenCode Agent Modes

OpenCode has two primary agent modes that control permissions and behavior:

## 1. Build Agent (Default) ✅

**Mode**: `build`  
**Permissions**: Full access, no prompts  
**Use case**: Active development, building features, creating files

**What it can do:**
- Create/edit/delete files without asking
- Run bash commands without prompts
- Full access to all tools
- Make changes immediately

**When Jarvis uses it:**
- "Use OpenCode to create a Flask API"
- "Build a website with contact form"
- "Fix the bug in my script"
- "Deploy the application"

**Example:**
```python
client.execute_task(
    task="Create a Python hello world script",
    agent_mode="build"  # ← Full permissions
)
```

---

## 2. Plan Agent (Restricted)

**Mode**: `plan`  
**Permissions**: Ask before changes  
**Use case**: Analysis, planning, suggestions (read-only tasks)

**What it does:**
- Analyzes code without modifying
- Suggests changes but doesn't implement
- Creates plans and architecture docs
- Asks permission for file edits/bash commands

**When Jarvis would use it:**
- "Analyze my codebase for issues"
- "Create a plan for adding authentication"
- "Review this code for best practices"
- "Suggest improvements to my API"

**Example:**
```python
client.execute_task(
    task="Analyze the Flask app and suggest improvements",
    agent_mode="plan"  # ← Ask before changes
)
```

**Problem with Plan mode for Jarvis:**
OpenCode will ask "Allow file edit?" but Jarvis can't respond interactively.

---

## Jarvis Integration Strategy

### Default: Use Build Mode

**Why:**
1. **User intent is clear** - When user asks Jarvis to build something, they want it built
2. **Workspace boundaries protect** - AGENTS.md rules prevent access to jarvis-voice
3. **No interactive prompts** - Build mode doesn't block on permission requests
4. **Full logging** - Everything is auditable in logs/opencode/

### When to Use Plan Mode

**Rarely, and only for true read-only tasks:**
- Code analysis
- Architecture review
- Generating documentation
- Creating TODO lists

**Implementation:**
```python
# In router_v2.py - detect intent
if "analyze" in query or "review" in query or "suggest" in query:
    agent_mode = "plan"  # Read-only
else:
    agent_mode = "build"  # Default: do the work
```

---

## Permission Model Comparison

| Action | Build Mode | Plan Mode | Jarvis Integration |
|--------|-----------|-----------|-------------------|
| Create file | ✅ Allowed | ❓ Asks | Build: Works ✅ |
| Edit file | ✅ Allowed | ❓ Asks | Build: Works ✅ |
| Run bash | ✅ Allowed | ❓ Asks | Build: Works ✅ |
| Read file | ✅ Allowed | ✅ Allowed | Both work ✅ |
| Analyze code | ✅ Allowed | ✅ Allowed | Both work ✅ |

---

## Configuration

### OpenCode Config (`~/.config/opencode/opencode.json`)

**No longer need to set permissions** - Agent mode handles this:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": { ... },
  "permission": {
    "edit": "ask",    // ← Ignored when using "build" agent
    "bash": "ask"     // ← Ignored when using "build" agent
  }
}
```

**Agent mode overrides global permissions:**
- `build` agent: Always allows
- `plan` agent: Always asks

### Jarvis Tool Schema (`skills/opencode.tool.json`)

```json
{
  "name": "opencode",
  "description": "Execute complex tasks using OpenCode autonomous agent",
  "parameters": {
    "task": {
      "type": "string",
      "description": "Task description"
    },
    "agent_mode": {
      "type": "string",
      "description": "Agent mode: 'build' (default, full permissions) or 'plan' (ask before changes)",
      "enum": ["build", "plan"],
      "default": "build"
    }
  }
}
```

---

## Implementation Details

### In `lib/opencode_client.py`:

```python
def create_session(self, agent_mode: str = "build") -> Dict[str, Any]:
    """Create session with specific agent mode."""
    payload = {"agent": {"mode": agent_mode}}
    response = requests.post(f"{self.base_url}/session", json=payload)
    return response.json()

def execute_task(
    self,
    task: str,
    agent_mode: str = "build",  # ← Add parameter
    ...
):
    session = self.create_session(agent_mode=agent_mode)
    ...
```

### In `skills/opencode.py`:

```python
def main():
    input_data = json.loads(sys.argv[1])
    task = input_data.get("task")
    agent_mode = input_data.get("agent_mode", "build")  # Default to build
    
    result = client.execute_task(
        task=task,
        agent_mode=agent_mode
    )
```

---

## Security Model

### Build Mode Security

**Protected by:**
1. **Workspace boundaries** (AGENTS.md global rules)
   - OpenCode CANNOT access `~/jarvis-voice`
   - OpenCode MUST work in `~/jarvis-workspace`

2. **User intent** (Jarvis routing)
   - User explicitly asked for the task
   - Jarvis verified it's appropriate for OpenCode

3. **Audit trail** (logs/opencode/*.jsonl)
   - Every action logged
   - Full session history preserved

4. **AI training**
   - OpenCode is trained to follow rules
   - Refuses unauthorized operations
   - Explains security boundaries

### Why Build Mode is Safe

**Traditional permission systems:**
```
User → Ask permission → User approves → Execute
```

**Jarvis + OpenCode model:**
```
User (voice) → Jarvis (validates) → OpenCode (executes with boundaries)
                     ↓
                 Audit logs
```

**The permission was already granted** when user spoke to Jarvis.

---

## Examples

### 1. Building a Flask API (Build Mode - Default)
```bash
./jarvis
"Hey Jarvis, use OpenCode to create a Flask API with user authentication"
```

**Behind the scenes:**
```python
client.execute_task(
    task="Create Flask API with user auth",
    agent_mode="build"  # ← Full permissions
)
# OpenCode creates files immediately, no prompts
```

### 2. Code Analysis (Plan Mode - Optional)
```bash
./jarvis
"Hey Jarvis, use OpenCode to analyze my Flask app for security issues"
```

**Behind the scenes:**
```python
client.execute_task(
    task="Analyze Flask app for security",
    agent_mode="plan"  # ← Read-only analysis
)
# OpenCode analyzes but doesn't modify
```

---

## Summary

**Use Build mode (default):**
- ✅ No permission prompts
- ✅ Full functionality
- ✅ Works with Jarvis automation
- ✅ Protected by workspace boundaries

**Avoid Plan mode unless:**
- ❌ Task is truly read-only
- ❌ You want suggestions, not implementation
- ❌ You'll handle permission prompts manually

**For Jarvis integration:**
- **Always use `build` agent mode** (current default)
- Workspace boundaries provide security
- Logging provides accountability
- User intent (via Jarvis) provides authorization

---

## Quick Reference

```python
# Default (recommended for Jarvis)
client.execute_task(task="Build something", agent_mode="build")

# Read-only analysis (rarely needed)
client.execute_task(task="Analyze something", agent_mode="plan")
```

**Current status**: ✅ Build mode implemented as default

