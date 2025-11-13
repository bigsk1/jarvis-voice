# OpenCode API Reference

**OpenCode Server:** http://localhost:4096  
**Documentation:** http://localhost:4096/doc  
**Interactive UI:** http://localhost:4096/openapi

---

## Current Jarvis Integration

Jarvis currently uses a **minimal subset** of the OpenCode API:
- Creates sessions
- Sends tasks
- Receives responses

**Location:** `lib/opencode_client.py`

---

## Complete API Endpoints

### 🎯 Task Execution (Currently Used by Jarvis)

#### `POST /session`
**Purpose:** Create a new OpenCode session

**Request:**
```json
{
  "title": "Session name",
  "agent": "build",  // or "plan"
  "model": {
    "provider": "anthropic",
    "modelID": "claude-sonnet-4"
  }
}
```

**Response:**
```json
{
  "sessionId": "uuid",
  "status": "created"
}
```

**Jarvis Use:** Called automatically when executing tasks

---

#### `POST /session/{sessionId}/message`
**Purpose:** Send a message/task to OpenCode

**Request:**
```json
{
  "role": "user",
  "content": [
    {
      "type": "text",
      "text": "Build a Flask app"
    }
  ]
}
```

**Response:**
```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text", 
      "text": "I've built the Flask app..."
    }
  ],
  "stopReason": "end_turn",
  "usage": {
    "inputTokens": 150,
    "outputTokens": 300
  }
}
```

**Jarvis Use:** Core task execution - sends every task here

---

#### `POST /session/{sessionId}/abort`
**Purpose:** Cancel a running task

**Request:** Empty body

**Response:**
```json
{
  "status": "aborted"
}
```

**Jarvis Use:** Timeout handling (not currently implemented)

---

### 📂 Session Management (NOT Currently Used)

#### `GET /sessions`
**Purpose:** List all OpenCode sessions

**Response:**
```json
{
  "sessions": [
    {
      "id": "uuid",
      "title": "Build Tetris Game",
      "agent": "build",
      "created": "2025-11-12T20:00:00Z",
      "lastActivity": "2025-11-12T20:05:00Z",
      "messageCount": 12
    }
  ]
}
```

**Potential Use:**
- "Jarvis, list my OpenCode projects"
- "Jarvis, what has OpenCode built recently?"
- Show session history to user

---

#### `GET /sessions/{sessionId}`
**Purpose:** Get full session details and conversation history

**Response:**
```json
{
  "id": "uuid",
  "title": "Build Tetris Game",
  "agent": "build",
  "messages": [
    {
      "role": "user",
      "content": "Build a tetris game"
    },
    {
      "role": "assistant",
      "content": "I'll create a web-based tetris game..."
    }
  ],
  "metadata": {
    "filesCreated": ["server.py", "tetris.html"],
    "tokensUsed": 15000
  }
}
```

**Potential Use:**
- "Jarvis, show me the full tetris conversation"
- Review what OpenCode did step-by-step
- Export project documentation

---

#### `DELETE /sessions/{sessionId}`
**Purpose:** Delete a session

**Response:**
```json
{
  "status": "deleted"
}
```

**Potential Use:**
- "Jarvis, delete old OpenCode sessions"
- Cleanup via voice command
- Automated maintenance

---

#### `POST /sessions/{sessionId}/rename`
**Purpose:** Rename a session

**Request:**
```json
{
  "title": "New session name"
}
```

**Potential Use:**
- "Jarvis, rename the tetris project to 'Web Tetris Game'"
- Better organization

---

### 📁 File Operations (NOT Currently Used)

#### `GET /files`
**Purpose:** List all files in OpenCode workspace

**Query Params:**
- `path`: Directory to list (default: root)
- `recursive`: Include subdirectories

**Response:**
```json
{
  "files": [
    {
      "path": "projects/tetris-game/server.py",
      "size": 1700,
      "modified": "2025-11-12T20:03:00Z",
      "type": "file"
    }
  ]
}
```

**Potential Use:**
- "Jarvis, what files did OpenCode create?"
- List project structure
- Verify builds without bash commands

---

#### `GET /files/{path}`
**Purpose:** Read a file from workspace

**Response:**
```json
{
  "path": "projects/tetris-game/server.py",
  "content": "#!/usr/bin/env python3\n...",
  "encoding": "utf-8"
}
```

**Potential Use:**
- "Jarvis, show me the tetris server code"
- Quick file inspection
- Code review without execute_bash

---

#### `POST /files`
**Purpose:** Create or update a file

**Request:**
```json
{
  "path": "projects/test/config.json",
  "content": "{\n  \"port\": 5000\n}",
  "overwrite": true
}
```

**Potential Use:**
- "Jarvis, change the port to 8000 in server.py"
- Quick config updates without full rebuild
- Hotfixes

---

#### `DELETE /files/{path}`
**Purpose:** Delete a file or directory

**Response:**
```json
{
  "status": "deleted",
  "path": "projects/old-project"
}
```

**Potential Use:**
- "Jarvis, delete the old test project"
- Workspace cleanup

---

### 🤖 Agent Management (NOT Currently Used)

#### `GET /agents`
**Purpose:** List available agents and their capabilities

**Response:**
```json
{
  "agents": [
    {
      "name": "build",
      "description": "Full development agent",
      "permissions": {
        "fileEdit": "allow",
        "bash": "allow",
        "git": "allow"
      }
    },
    {
      "name": "plan", 
      "description": "Read-only analysis agent",
      "permissions": {
        "fileEdit": "ask",
        "bash": "ask",
        "git": "deny"
      }
    }
  ]
}
```

**Potential Use:**
- Show user agent capabilities
- Auto-select agent based on task type

---

#### `POST /agents/switch`
**Purpose:** Switch agent mid-session

**Request:**
```json
{
  "sessionId": "uuid",
  "agent": "plan"
}
```

**Potential Use:**
- "Jarvis, switch to plan mode to analyze this code"
- Dynamic permission adjustment

---

### 💬 Chat Interface (NOT Currently Used)

#### `POST /chat`
**Purpose:** Interactive streaming chat (like web UI)

**Request:**
```json
{
  "message": "What's the best way to handle authentication?",
  "stream": true
}
```

**Response:** Server-Sent Events (streaming)

**Potential Use:**
- "Jarvis, ask OpenCode about Flask best practices"
- Quick technical Q&A without building
- Code consultation

---

### 🔧 System & Health

#### `GET /health`
**Purpose:** Server health check

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.57",
  "uptime": 86400
}
```

**Current Use:** Already checked in `lib/opencode_client.py` during init

---

#### `GET /models`
**Purpose:** List available LLM models

**Response:**
```json
{
  "models": [
    {
      "provider": "anthropic",
      "modelID": "claude-sonnet-4",
      "available": true
    },
    {
      "provider": "ollama",
      "modelID": "qwen2.5-coder:32b",
      "available": true
    }
  ]
}
```

**Potential Use:**
- "Jarvis, what models can OpenCode use?"
- Show available options
- Auto-fallback if model unavailable

---

## Token Usage Tracking

Every response includes usage stats:
```json
{
  "usage": {
    "inputTokens": 1500,
    "outputTokens": 3000,
    "totalTokens": 4500
  }
}
```

**Visible in:**
- Web UI (http://localhost:4096/openapi)
- API responses
- Jarvis logs: `logs/opencode/opencode-*.jsonl`

---

## Potential Jarvis Enhancements

### 🎯 High Value (Streamline Workflow)

1. **Session History**
   - "Show me recent OpenCode projects"
   - `GET /sessions` → format for voice

2. **File Inspection**
   - "What files are in the tetris project?"
   - `GET /files?path=projects/tetris-game` → list without bash

3. **Quick Edits**
   - "Change port to 8000 in server.py"
   - `POST /files` → direct update, no full rebuild

### 🔍 Medium Value (Nice to Have)

4. **Session Management**
   - "Delete old OpenCode sessions"
   - `DELETE /sessions/{id}` → voice-controlled cleanup

5. **Code Review**
   - "Show me the Flask server code"
   - `GET /files/{path}` → read without execute_bash

6. **Chat Mode**
   - "Ask OpenCode about Flask best practices"
   - `POST /chat` → Q&A without building

### 📊 Low Value (Already Have Solutions)

7. **Health Checks** - Already implemented
8. **Model Selection** - Could be useful with Ollama testing
9. **Agent Switching** - Jarvis already selects mode intelligently

---

## Current Limitations

**Jarvis uses only:**
- Session creation
- Task execution  
- Response parsing

**Doesn't use:**
- File operations (uses `execute_bash` instead)
- Session management (uses Jarvis's own logs)
- Chat interface (always builds, doesn't consult)

---

## Implementation Notes

### If Adding New Endpoints:

1. **Update `lib/opencode_client.py`:**
   ```python
   def list_sessions(self):
       response = requests.get(f"{self.base_url}/sessions")
       return response.json()
   ```

2. **Add new tool or extend opencode tool:**
   - Option A: New tool `opencode_sessions.py`
   - Option B: Add parameters to existing `opencode` tool
   
3. **Update router system prompt:**
   - Teach Jarvis when to use new capabilities

4. **Test with voice:**
   - "Hey Jarvis, list OpenCode sessions"
   - Verify natural response

---

## Testing Endpoints

### Via curl:
```bash
# List sessions
curl http://localhost:4096/sessions | jq

# Get session details
curl http://localhost:4096/sessions/<uuid> | jq

# List files
curl http://localhost:4096/files | jq

# Read a file
curl http://localhost:4096/files/projects/tetris-game/server.py
```

### Via Web UI:
http://localhost:4096/openapi
- Interactive testing
- See token usage
- View all sessions

---

## Related Documentation

- [OpenCode Integration](OPENCODE.md) - Overview
- [OpenCode Phase 2 Complete](OPENCODE_PHASE2_COMPLETE.md) - Current state
- [OpenCode Memory Strategy](OPENCODE_MEMORY_STRATEGY.md) - Context injection
- [Multi-Turn Orchestration](MULTI_TURN_ORCHESTRATION.md) - How Jarvis chains tools

---

## Questions to Consider

1. **Session Management:**
   - Worth adding voice-controlled session cleanup?
   - Or is TUI/Web UI sufficient?

2. **File Operations:**
   - Faster to use API than execute_bash?
   - Trade-off: Simplicity vs efficiency

3. **Chat Mode:**
   - Use case: Quick questions without building
   - Example: "Ask OpenCode best practices for X"
   - Worth the added complexity?

4. **Token Tracking:**
   - Already visible in logs and Web UI
   - Surface this to user via voice?
   - "How many tokens did that build use?"

---

**Next Step:** Review endpoints, identify which (if any) would streamline your workflow with Jarvis! 🚀

