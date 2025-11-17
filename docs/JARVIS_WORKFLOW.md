# Jarvis Voice Assistant - Complete Workflow Guide

> **Visual guide to understanding how Jarvis processes queries, makes decisions, and executes tasks**

This document provides a comprehensive overview of Jarvis's internal workflow, from receiving a user query to delivering the final response. It includes flowcharts, decision trees, and real-world examples showcasing the full feature set.

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Main Processing Flow](#main-processing-flow)
3. [Memory-First Strategy](#memory-first-strategy)
4. [Tool Selection & Execution](#tool-selection--execution)
5. [Multi-Turn Orchestration](#multi-turn-orchestration)
6. [Configuration Impact](#configuration-impact)
7. [Real-World Examples](#real-world-examples)

---

## High-Level Architecture

```mermaid
graph TB
    User[👤 User Query] --> Voice[🎤 Voice Input / CLI]
    Voice --> Orchestrator[🎯 Orchestrator v2]
    
    Orchestrator --> Config[⚙️ Load Config]
    Config --> Cloud{Mode?}
    Cloud -->|cloud| CloudDB[(jarvis_memory.db)]
    Cloud -->|local| LocalDB[(jarvis_memory_local.db)]
    
    Orchestrator --> AutoSync[🔄 Auto-Sync Memory]
    AutoSync --> Router[🧭 Router v2]
    
    Router --> Thinking{Thinking Enabled?}
    Thinking -->|Yes| ShowThinking[🧠 Display Reasoning]
    Thinking -->|No| SkipThinking[⏩ Skip Display]
    ShowThinking --> Intent
    SkipThinking --> Intent
    
    Intent{Intent?}
    Intent -->|Tool Call| Executor[⚡ Executor]
    Intent -->|Q&A| Formatter[💬 Response Formatter]
    
    Executor --> Tools[🛠️ Tool Registry]
    Tools --> MCPServers[🔌 MCP Servers]
    Tools --> LocalTools[📦 Local Skills]
    
    Executor --> Result[✅ Tool Result]
    Result --> MultiTurn{More Tools?}
    MultiTurn -->|Yes| Router
    MultiTurn -->|No| Final[📊 Final Response]
    
    Formatter --> Final
    Final --> TTS[🔊 Text-to-Speech]
    TTS --> User
    
    style Orchestrator fill:#4a90e2
    style Router fill:#f39c12
    style Executor fill:#27ae60
    style Thinking fill:#9b59b6
    style CloudDB fill:#3498db
    style LocalDB fill:#16a085
```

---

## Main Processing Flow

### Complete Request Lifecycle

```mermaid
sequenceDiagram
    participant U as User
    participant O as Orchestrator
    participant C as Config Loader
    participant S as Auto-Sync
    participant R as Router
    participant T as Thinking Module
    participant E as Executor
    participant M as Memory DB
    participant Tool as Tool Script
    participant F as Formatter
    
    U->>O: "What time is it and what's my favorite food?"
    O->>C: Load config (cloud/local mode)
    C-->>O: Config loaded
    O->>S: Auto-sync memories between DBs
    S-->>O: Sync complete
    
    O->>R: Route query with full context
    R->>T: Check if thinking enabled
    alt Thinking Enabled
        T->>R: Extract & log reasoning
        R-->>O: 🧠 Display thinking
    end
    
    R->>M: Search memory first (MEMORY-FIRST rule)
    M-->>R: "favorite_food: sushi"
    
    R-->>O: Intent: tool_call (get_time)
    O->>E: Execute tool: get_time
    E->>Tool: Run skills/time.sh
    Tool-->>E: {"time": "14:30", "date": "2025-11-16"}
    E-->>O: Tool result
    
    O->>R: Continue with tool result (multi-turn)
    R-->>O: Intent: qa (enough info to answer)
    O->>F: Format final response
    F-->>O: "It's 2:30 PM on November 16th, and you love sushi!"
    O-->>U: Speech output + JSON
```

---

## Memory-First Strategy

Jarvis follows a **MEMORY-FIRST RULE**: Always check memory before making assumptions or asking for clarification.

### Memory Lookup Flow

```mermaid
graph TB
    Query[User Query] --> Analyze[Analyze Query]
    Analyze --> NeedInfo{Need stored information?}
    
    NeedInfo -->|No| DirectTool[Execute Tool Directly]
    NeedInfo -->|Yes| SearchType{Query Type?}
    
    SearchType -->|"1-3 keywords"| KeywordSearch[🔍 search_memory]
    SearchType -->|"Natural language"| SemanticSearch[🤖 semantic_recall]
    SearchType -->|"Past conversations"| ConversationSearch[💬 search_conversations]
    
    KeywordSearch --> MemDB[(Memory Database)]
    SemanticSearch --> EmbedModel[Embedding Model]
    ConversationSearch --> MemDB
    
    EmbedModel --> VectorSearch[Vector Similarity Search]
    VectorSearch --> MemDB
    
    MemDB --> Found{Found?}
    Found -->|Yes| UseMemory[Use Stored Data]
    Found -->|No| UseOtherTool[Call Other Tools]
    
    UseMemory --> Response[Build Response]
    UseOtherTool --> Response
    DirectTool --> Response
    
    style KeywordSearch fill:#3498db
    style SemanticSearch fill:#9b59b6
    style ConversationSearch fill:#e74c3c
```

**Tool Details:**
- **search_memory**: SQL LIKE fuzzy matching for 1-3 keywords
- **semantic_recall**: AI embedding search for natural language (4+ words, sentence structure)
- **search_conversations**: Historical context from past interactions
- **Similarity Threshold**: Default 0.40 (configurable in `.env`)

### Memory Tool Selection Examples

| Query | Tool Used | Why |
|-------|-----------|-----|
| "pizza" | `search_memory` | Single keyword → SQL LIKE |
| "webhook url" | `search_memory` | 2 keywords → SQL LIKE |
| "Where is my Flask app?" | `semantic_recall` | Natural language question → AI embeddings |
| "What did I say about John?" | `semantic_recall` | Contextual question → AI understanding |
| "What did I ask yesterday?" | `search_conversations` | Historical lookup → conversation log |

---

## Tool Selection & Execution

### Router Decision Process

```mermaid
graph TB
    Start[User Query] --> Router[🧭 Router LLM]
    
    Router --> Thinking{Thinking Mode?}
    Thinking -->|Enabled| LogReason[📝 Log Reasoning Process]
    Thinking -->|Disabled| SkipLog[⏭️ Skip Logging]
    
    LogReason --> Analyze
    SkipLog --> Analyze
    
    Analyze[Analyze Intent] --> CheckMem[Apply MEMORY-FIRST Rule]
    
    CheckMem --> ToolReg[📚 Load Tool Registry]
    ToolReg --> FilterTools{Filter Tools}
    
    FilterTools --> Enabled[✅ Only Load Enabled Tools]
    Enabled --> ToolList[Available Tools List]
    
    ToolList --> Decision{Decision Type}
    
    Decision -->|"Simple task"| SingleTool[🛠️ Single Tool Call]
    Decision -->|"Complex task"| MultiTool[⚙️ Multi-Tool Chain]
    Decision -->|"Info request"| QA[💬 Q&A Response]
    Decision -->|"Save data"| AutoSave[💾 Auto-Save Memory]
    
    SingleTool --> Execute[Execute Tool]
    MultiTool --> Execute
    AutoSave --> Execute
    
    Execute --> Validate[Validate Result]
    Validate --> Success{Success?}
    
    Success -->|Yes| CheckNext{More tools needed?}
    Success -->|No| Retry{Retry count < 3?}
    
    Retry -->|Yes| Execute
    Retry -->|No| Error[❌ Return Error]
    
    CheckNext -->|Yes| Router
    CheckNext -->|No| Format[Format Response]
    
    QA --> Format
    Error --> Format
    Format --> Done[✅ Done]
    
    style Router fill:#f39c12
    style Thinking fill:#9b59b6
    style Execute fill:#27ae60
    style Error fill:#e74c3c
```

**Decision Types:**
- **Single Tool**: Simple tasks (e.g., "What time is it?")
- **Multi-Tool Chain**: Complex tasks requiring multiple steps
- **Q&A Response**: Information requests that don't need tools
- **Auto-Save**: Automatically saves important info to memory

### Tool Registry & Enable/Disable

```bash
# List all tools (enabled and disabled)
./bin/manage-tools.py list

# Disable a tool (reduces token count)
./bin/manage-tools.py disable crypto_price

# Enable a tool
./bin/manage-tools.py enable crypto_price

# Enable all tools
./bin/manage-tools.py enable-all
```

**In `skills/*.tool.json`:**
```json
{
  "enabled": true,  // Set to false to disable
  "name": "get_time",
  "description": "..."
}
```

---

## Multi-Turn Orchestration

Jarvis can chain multiple tools in sequence to complete complex tasks.

### Multi-Turn Flow Example

```mermaid
sequenceDiagram
    participant U as User
    participant O as Orchestrator
    participant R as Router
    participant E as Executor
    
    U->>O: "Search DuckDuckGo for Jarvis AI and tell me about it"
    
    Note over O: Turn 1: Initial analysis
    O->>R: Analyze query
    R-->>O: Intent: tool_call (mcp_duckduckgo_search)
    O->>E: Execute mcp_duckduckgo_search
    E-->>O: Search results (raw data)
    
    Note over O: Turn 2: Process results
    O->>R: Continue with search results
    R-->>O: Intent: tool_call (mcp_fetch_fetch)
    O->>E: Fetch page content from top result
    E-->>O: Page content
    
    Note over O: Turn 3: Summarize
    O->>R: Continue with page content
    R-->>O: Intent: qa (summarize findings)
    O-->>U: "Jarvis AI is an open-source voice assistant..."
    
    Note over O: Auto-save decision
    O->>R: Should we save this?
    R-->>O: No (ephemeral info, not personal)
```

**Max turns**: 10 (configurable via `MAX_ORCHESTRATION_TURNS`)  
**Max retries**: 3 per tool

---

## Configuration Impact

### Mode Selection (Cloud vs Local)

```mermaid
graph LR
    Start[Start Jarvis] --> Mode{Mode?}
    
    Mode -->|cloud| CloudConfig[Load config/cloud.env]
    Mode -->|local| LocalConfig[Load config/local.env]
    
    CloudConfig --> CloudLLM[LLM: Anthropic/OpenAI]
    LocalConfig --> LocalLLM[LLM: Ollama]
    
    CloudLLM --> CloudDB[(jarvis_memory.db)]
    LocalLLM --> LocalDB[(jarvis_memory_local.db)]
    
    CloudDB --> CloudTools[Cloud Tools]
    LocalDB --> LocalTools[Local Tools]
    
    CloudTools --> Execute[Execute Tasks]
    LocalTools --> Execute
    
    style CloudConfig fill:#3498db
    style LocalConfig fill:#16a085
    style CloudDB fill:#5dade2
    style LocalDB fill:#48c9b0
```

**Database Details:**
- **Cloud**: OpenAI text-embedding-3-small (1536 dimensions) 
- **Local**: nomic-embed-text (768 dimensions)
- **Models**: Claude Sonnet 4.5, GPT-4o (cloud) | qwen3:14b, qwen3-vl (local)

### Key Configuration Variables

| Variable | Impact | Example Values |
|----------|--------|----------------|
| `LLM_PROVIDER` | Which LLM to use | `anthropic`, `openai`, `ollama` |
| `ANTHROPIC_MODEL` | Cloud model selection | `claude-sonnet-4-5-20250929` |
| `OLLAMA_MODEL` | Local model selection | `qwen3:14b`, `qwen3-vl`, `deepseek-r1` |
| `JARVIS_DEBUG_THINKING` | Show LLM reasoning | `true`, `false` |
| `SEMANTIC_SIMILARITY_THRESHOLD` | Memory search sensitivity | `0.40` (default), `0.30-0.50` range |
| `JARVIS_RESPONSE_STYLE` | Output formatting | `casual`, `detailed`, `auto` |
| `OPENCODE_ENABLED` | Enable autonomous coding | `true`, `false` |

### Response Style Impact

```mermaid
graph TB
    ToolResult[Tool Returns Data] --> Style{JARVIS_RESPONSE_STYLE}
    
    Style -->|casual| LLM[Format with LLM]
    Style -->|detailed| Raw[Use raw output]
    Style -->|auto| Smart{Smart Decision}
    
    Smart -->|Search results| LLM
    Smart -->|Other tools| Raw
    
    LLM --> Voice[Voice-friendly output]
    Raw --> Data[Raw data output]
    
    Voice --> User[👤 User]
    Data --> User
    
    style LLM fill:#9b59b6
    style Raw fill:#e74c3c
```

**Examples:**
- **casual**: "It's 2:30 PM on November 16th"
- **detailed**: `{"time": "14:30", "date": "2025-11-16"}`
- **auto**: Smart decision (LLM format for search, raw for others)

---

## Real-World Examples

### Example 1: Simple Tool Call (Time Query)

**User**: "What time is it?"

```mermaid
graph LR
    Q["What time is it?"] --> R[Router]
    R --> T{Thinking?}
    T -->|Yes| Think[🧠 Reasoning]
    T -->|No| Skip[Skip display]
    Think --> E[Execute get_time]
    Skip --> E
    E --> Result[Tool Result]
    Result --> Format[Format Response]
    Format --> User[👤 User]
    
    style Think fill:#9b59b6
    style Result fill:#27ae60
```

**Thinking Output** (if enabled):
```
🧠 Reasoning: Need current time → Use get_time tool → No parameters needed
```

**Final Output:**
```
✅ It's 2:30 PM on November 16th, 2025.
```

**With Thinking Enabled:**
```
🧠 LLM Thinking:
   Okay, the user is asking "What time is it?" 
   I need to check the current time. The available tools include 
   get_time, which returns date and time. The parameters for 
   get_time are empty, so I just need to call that tool.

🗣️ Speech Output: It's 2:30 PM on November 16th, 2025.
```

---

### Example 2: Memory-First Lookup (Personal Data)

**User**: "What's my favorite food?"

```mermaid
sequenceDiagram
    participant U as User
    participant R as Router
    participant M as Memory
    participant T as Thinking
    
    U->>R: "What's my favorite food?"
    R->>T: Analyze query
    T-->>R: Natural language → semantic_recall
    R->>M: semantic_recall(query="favorite food")
    M-->>R: Found: "favorite_food: sushi" (similarity: 0.87)
    R-->>U: "You love sushi!"
    
    Note over R: No tool calls needed - Memory answered directly
```

**Flow:**
1. Router recognizes this is a question about stored info
2. Applies MEMORY-FIRST rule
3. Uses `semantic_recall` (natural language query)
4. Finds stored memory: `favorite_food: sushi`
5. Responds directly with Q&A intent

---

### Example 3: Multi-Tool Complex Task (Web Search + Memory)

**User**: "Search for Python tutorials and remember that I'm learning Python"

```mermaid
sequenceDiagram
    participant U as User
    participant O as Orchestrator
    participant R as Router
    participant MCP as MCP DuckDuckGo
    participant Mem as Memory DB
    
    U->>O: "Search for Python tutorials and remember I'm learning Python"
    
    Note over O: Turn 1: Search
    O->>R: Analyze query
    R-->>O: Intent: tool_call (mcp_duckduckgo_search)
    O->>MCP: search(query="Python tutorials")
    MCP-->>O: Search results
    
    Note over O: Turn 2: Save memory
    O->>R: Continue (save learning preference)
    R-->>O: Intent: tool_call (remember)
    O->>Mem: remember(key="learning_language", value="Python")
    Mem-->>O: Saved
    
    Note over O: Turn 3: Respond
    O->>R: Finalize response
    R-->>O: Intent: qa
    O-->>U: Response with search results + saved memory
```

**Tools Used:**
1. `mcp_duckduckgo_search` - Web search
2. `remember` - Save to memory
3. Q&A - Final response

**Auto-Save Decision:**
- "I'm learning Python" → Personal, persistent info
- Category: `learning`, Importance: `8`
- Router intelligently saves this automatically

---

### Example 4: MCP Server Integration (Fetch URL)

**User**: "Fetch the content from example.com"

```mermaid
graph TB
    Query["Fetch content from example.com"] --> Router[Router]
    Router --> MCPCheck{MCP Tools Available?}
    
    MCPCheck -->|Yes| MCPRegistry[Load mcp_fetch_fetch]
    MCPCheck -->|No| Error[❌ Tool not available]
    
    MCPRegistry --> Execute[Execute Tool]
    Execute --> MCPServer[🔌 MCP Fetch Server]
    MCPServer --> HTTP[HTTP Request]
    HTTP --> Content[Page Content]
    Content --> Parse[Parse Response]
    Parse --> Format[Format Output]
    Format --> User[👤 User]
    
    style MCPServer fill:#f39c12
    style Execute fill:#27ae60
```

**MCP Server Tools:**
- `mcp_duckduckgo_search` - Web search
- `mcp_fetch_fetch` - HTTP fetch
- Auto-discovered on startup
- Prefixed with `mcp_<server>_<tool>`

---

### Example 5: OpenCode Integration (Complex Coding Task)

**User**: "Build a Flask API for managing todos"

```mermaid
sequenceDiagram
    participant U as User
    participant J as Jarvis
    participant OC as OpenCode Agent
    participant WS as Workspace
    participant Mem as Memory
    
    U->>J: "Build a Flask API for managing todos"
    J->>J: Recognize complex coding task
    J->>OC: Delegate to OpenCode
    
    Note over OC: Multi-step autonomous work
    OC->>WS: Create project structure
    OC->>WS: Write Flask app.py
    OC->>WS: Create requirements.txt
    OC->>WS: Write tests
    OC->>WS: Run and verify
    
    OC-->>J: Task complete (port 8091)
    J->>Mem: Auto-save project location
    Mem-->>J: Saved
    J-->>U: Flask API built successfully
```

**Response:**
```
Flask API built at ~/jarvis-workspace/projects/flask-todo-api
Running on http://localhost:8091
```

**OpenCode Features:**
- Autonomous coding (multi-step tasks)
- Workspace isolation (`~/jarvis-workspace`)
- Auto-save project location to memory
- Uses dedicated LLM (Claude Sonnet 4.5 recommended)

---

### Example 6: Thinking Mode Deep Dive

**User**: "Should I invest in Bitcoin?"

**With Thinking Enabled (`--debug-thinking`):**

```
🧠 LLM Thinking:
   The user is asking about Bitcoin investment. This is a complex 
   financial question. Let me consider:
   
   1. Do I have stored preferences about their risk tolerance?
      → Check memory first (MEMORY-FIRST rule)
      → No memories found about investment preferences
   
   2. Should I provide financial advice?
      → Financial advice requires disclaimers
      → I should be cautious and informative
   
   3. Tool selection:
      → crypto_price to get current BTC price
      → Then provide balanced information, not advice
   
   4. Auto-save decision:
      → This is a one-time query, not persistent info
      → Don't save unless they express ongoing interest

🗣️ Speech Output: Bitcoin is currently at $95,822. However, I can't 
provide investment advice. Consider your risk tolerance and consult 
a financial advisor for personalized guidance.
```

**Thinking Log Saved To:**
`logs/thinking/2025-11-16_decisions.jsonl`

**Benefits:**
- Transparency in decision-making
- Debugging tool selection
- Understanding auto-save logic
- Model accountability

---

## Configuration Flags & Toggles

### CLI Flags

```bash
# Enable thinking mode (overrides .env)
./orchestrator/orchestrator_v2.py cloud "query" --debug-thinking

# JSON-only output (no pretty formatting)
./orchestrator/orchestrator_v2.py cloud "query" --json

# Specify mode
./orchestrator/orchestrator_v2.py cloud "query"   # Cloud mode
./orchestrator/orchestrator_v2.py local "query"   # Local mode
```

### Environment Variables (`.env` files)

**Memory System:**
- `SEMANTIC_SIMILARITY_THRESHOLD` - Search sensitivity (0.30-0.50)

**Thinking Mode:**
- `JARVIS_DEBUG_THINKING` - Enable thinking display (`true`/`false`)

**Response Style:**
- `JARVIS_RESPONSE_STYLE` - Output format (`casual`/`detailed`/`auto`)

**OpenCode:**
- `OPENCODE_ENABLED` - Enable autonomous coding (`true`/`false`)
- `OPENCODE_MODEL` - Model for coding tasks
- `OPENCODE_PROVIDER` - Provider (Anthropic recommended)

**Model Selection:**
- `LLM_PROVIDER` - Main LLM (`anthropic`, `openai`, `ollama`)
- `ANTHROPIC_MODEL` - Claude model
- `OLLAMA_MODEL` - Local model

---

## Decision Matrix

### When Does Jarvis Choose Each Path?

| Scenario | Memory Check | Tool(s) Used | Multi-Turn | Auto-Save |
|----------|--------------|--------------|------------|-----------|
| "What time is it?" | No | `get_time` | No | No |
| "What's my name?" | ✅ Yes | `semantic_recall` | No | No |
| "Remember I love pizza" | No | `remember` | No | ✅ Yes |
| "Search and summarize OpenAI" | No | `mcp_duckduckgo_search` → Q&A | ✅ Yes | No |
| "Build a Flask API" | No | `opencode` | ✅ Yes | ✅ Yes (location) |
| "What's Bitcoin price?" | No | `crypto_price` | No | No |
| "Update my favorite food to sushi" | ✅ Yes | `semantic_recall` → `update_memory` | ✅ Yes | ✅ Yes |

---

## Performance Characteristics

### Cloud Mode (Anthropic/OpenAI)

- **Speed**: ⚡⚡⚡ Very fast (1-3 seconds)
- **Cost**: 💰 Pay per token (~$0.01-0.10 per query)
- **Capabilities**: Extended thinking, prompt caching, native tool calling
- **Context Window**: 200K tokens (Claude Sonnet 4.5)

### Local Mode (Ollama)

- **Speed**: ⚡ Moderate (3-10 seconds, model-dependent)
- **Cost**: 💰 Free (runs locally)
- **Capabilities**: Structured prompting, offline operation
- **Context Window**: 32K-256K tokens (model-dependent)
- **VRAM**: 8-16GB GPU recommended

---

## Summary

Jarvis is a **multi-modal, memory-aware, tool-orchestrating voice assistant** with the following key capabilities:

✅ **Memory-First Strategy** - Always checks stored info before asking  
✅ **Intelligent Tool Selection** - LLM-based routing with 50+ tools  
✅ **Multi-Turn Orchestration** - Chains tools to complete complex tasks  
✅ **MCP Server Integration** - Extensible via Model Context Protocol  
✅ **Dual-Database System** - Cloud/local modes with auto-sync  
✅ **Thinking Mode** - Transparent LLM reasoning for debugging  
✅ **OpenCode Integration** - Autonomous coding for complex tasks  
✅ **Configurable Behavior** - Fine-tune via `.env` and CLI flags  

---

## Next Steps

- **For Users**: See [QUICKSTART.md](QUICKSTART.md) to get started
- **For Developers**: See [AGENTS.md](../AGENTS.md) for coding guidelines
- **For Memory Tuning**: See [SEMANTIC_THRESHOLD_TUNING.md](SEMANTIC_THRESHOLD_TUNING.md)
- **For Tool Development**: See [TOOL_MANAGEMENT.md](TOOL_MANAGEMENT.md)
- **For OpenCode**: See [opencode/OPENCODE.md](opencode/OPENCODE.md)

---

**Last Updated**: 2025-11-16  
**Version**: 2.0 (Multi-turn orchestration with thinking mode)

