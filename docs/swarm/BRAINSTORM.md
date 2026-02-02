# Swarm Mode - Brainstorm Document

> **Status:** Brainstorming / Design Phase
> **Created:** 2026-02-02
> **Goal:** Enable parallel subagent execution for complex tasks

## The Problem

Jarvis currently executes tools **sequentially** (pipeline model):
```
Query → Tool 1 → Tool 2 → Tool 3 → Response
```

This is limiting for:
- Multi-faceted research (search multiple topics simultaneously)
- Tasks requiring diverse data sources
- Complex analysis needing different perspectives
- Time-sensitive operations where parallelism helps

## The Vision: Swarm Mode

```
Query → Swarm Orchestrator
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
 Agent 1   Agent 2   Agent 3    (parallel execution)
    │         │         │
    └─────────┼─────────┘
              ▼
        Swarm Boss (synthesizer)
              │
              ▼
    Jarvis Response (speech + canvas)
```

## Key Concepts

### 1. Subagent Profiles

Each subagent type has a profile:

```
data/subagents/
  researcher/
    config.json    # Static: model, tools, limits (human-defined)
    SKILL.md       # Dynamic: generated from user query OR pre-written
```

**config.json** (human-defined parameters):
```json
{
  "name": "researcher",
  "description": "Web research and data gathering",
  "models": ["grok-4-1-fast", "gemini-2.0-flash"],
  "tools": ["brave_search", "fetch", "crawl_url"],
  "max_turns": 5,
  "timeout_seconds": 120,
  "max_tokens": 50000
}
```

**SKILL.md** (guidance for the agent):
```markdown
# Researcher Agent

You are a research specialist. Your job is to:
- Search thoroughly using multiple queries
- Verify facts from multiple sources
- Cite your sources with URLs
- Return structured data (not prose)

## Output Format
Return JSON:
{
  "findings": [...],
  "sources": [...],
  "confidence": 0.0-1.0
}
```

### 2. Quantity Parameter (qty)

Spin up multiple agents of the same type for parallel work:

```json
{
  "swarm": {
    "agents": [
      {"profile": "researcher", "qty": 2, "task_split": "topic"},
      {"profile": "analyst", "qty": 1}
    ]
  }
}
```

- `qty: 2` → Two researcher agents run simultaneously
- Each can use different provider/model for diversity
- Results merged for comprehensive coverage

### 3. Provider/Model Diversity

Different agents can use different LLMs:
```
Agent 1 (researcher): grok-4-1-fast + brave_search
Agent 2 (researcher): gemini-flash + fetch
Agent 3 (researcher): claude-haiku + crawl_url
```

**Benefits:**
- Different models have different strengths
- Diverse search results (different biases)
- Compare/verify across providers
- Cost optimization (mix fast cheap + slow smart)

### 4. Swarm Boss (Synthesizer)

After all agents complete, a "boss" agent:
- Receives all agent outputs
- Merges/deduplicates data
- Filters noise, keeps relevant facts
- Formats for Jarvis output (speech + canvas)
- Uses a smarter/larger model (can afford latency here)

```python
swarm_boss_prompt = """
You are the Swarm Boss. You received these results from {n} research agents:

{agent_outputs}

Your task:
1. Merge overlapping findings
2. Remove duplicates and noise
3. Rank by relevance to: "{original_query}"
4. Create a structured report
5. Identify gaps needing more research

Output: JSON with 'summary', 'findings', 'sources', 'gaps'
"""
```

## Architecture Details

### MCP Server Considerations

**Problem:** We prevent duplicate MCP servers (had 10 fetch instances running).

**Solution:** Single MCP server handles multiple requests:
- MCP servers are designed for concurrent requests
- Use request IDs to track which agent gets which response
- If server overloaded, queue requests

```python
# MCP request with agent tracking
mcp_request = {
    "tool": "brave_search",
    "args": {"query": "..."},
    "agent_id": "researcher_1",
    "swarm_id": "swarm_abc123"
}
```

### Logging Structure

```
logs/
  swarm/
    swarm_20260202_143000_abc123/
      manifest.json       # Swarm config, query, start time
      agent_researcher_1.jsonl
      agent_researcher_2.jsonl
      agent_analyst_1.jsonl
      boss_synthesis.json
      final_result.json
```

**Per-agent log entry:**
```json
{
  "timestamp": "2026-02-02T14:30:05Z",
  "agent_id": "researcher_1",
  "turn": 1,
  "tool": "brave_search",
  "args": {"query": "..."},
  "tokens": {"input": 1500, "output": 800},
  "duration_ms": 2500,
  "result_preview": "..."
}
```

### Timeout & Resource Management

| Parameter | Default | Description |
|-----------|---------|-------------|
| `agent_timeout` | 120s | Max time per agent |
| `tool_timeout` | 30s | Max time per tool call |
| `max_tokens` | 50k | Context limit per agent |
| `swarm_timeout` | 300s | Max total swarm time |
| `max_parallel` | 4 | Max concurrent agents |

If agent exceeds limits → gracefully terminate, return partial results.

### Integration with Jarvis

**Option A: Direct Integration**
```python
# In orchestrator, detect swarm task
if should_use_swarm(query):
    result = await swarm_executor.run(query, swarm_config)
    return format_for_jarvis(result)
```

**Option B: API Call**
```python
# Swarm runs separately, calls Jarvis API when done
POST /api/swarm/complete
{
    "swarm_id": "abc123",
    "result": {...},
    "canvas_artifacts": [...]
}
```

**Option C: Queue (if Jarvis busy)**
```python
# Swarm result goes to queue
# Jarvis processes when available
swarm_queue.push(result)
# Jarvis polls: GET /api/swarm/pending
```

## Triggering Swarm Mode

### Explicit Trigger
```
"Hey Jarvis, use swarm mode to research X"
"/swarm research Bitcoin competitors"
```

### Auto-Detection
Jarvis detects swarm-worthy queries:
- Multiple distinct topics in one query
- Research + analysis + report keywords
- "Compare X and Y and Z"
- Complexity score > threshold

```python
SWARM_INDICATORS = [
    r"research .* and .*",
    r"compare .* vs .*",
    r"create a (report|analysis) on",
    r"find .* from multiple sources",
]
```

## First Use Case: Research Swarm

### Scenario
User: "Research the top 3 AI coding assistants and create a comparison"

### Execution
```
1. Jarvis detects: research + comparison → swarm mode

2. Swarm config generated:
   - researcher_1: "AI coding assistant Cursor features"
   - researcher_2: "AI coding assistant GitHub Copilot features"  
   - researcher_3: "AI coding assistant Claude Code features"
   - analyst: Wait for researchers, then compare

3. Parallel execution:
   [researcher_1] → brave_search, fetch docs
   [researcher_2] → brave_search, fetch docs
   [researcher_3] → brave_search, fetch docs
   
4. Results merge (when all complete):
   [analyst] → receives all data, creates comparison matrix

5. Swarm boss synthesis:
   - Formats as canvas report
   - Creates speech summary
   - Identifies any gaps

6. Return to Jarvis:
   - Speech: "I've compared 3 AI coding assistants..."
   - Canvas: Detailed comparison table + findings
```

## User in the Loop

After swarm completes, user can:
1. **Accept:** "Looks good, save this"
2. **Iterate:** "Go deeper on X" → new swarm with preserved context
3. **Expand:** "Also research Y" → add to existing data
4. **Reject:** "Start over with different approach"

```
User: "Research AI assistants"
Jarvis: [swarm runs] "Here's what I found..." [canvas report]
User: "Go deeper on pricing"
Jarvis: [incremental swarm] "Updated with pricing details..." [merged report]
```

## Open Questions

1. **SKILL.md generation:** Should Jarvis auto-generate from query, or use pre-written templates?

2. **Agent communication:** Do agents share context during execution, or only combine at end?

3. **Failure handling:** If 1 of 3 agents fails, proceed with partial results or retry?

4. **Cost tracking:** How to surface token costs per swarm to user?

5. **Persistent swarms:** Save swarm results for future reference? (like canvas pages)

6. **Streaming:** Show progress while agents work? ("Agent 1 found 5 results...")

## Implementation Phases

### Phase 1: Proof of Concept
- Hardcoded 2-agent research swarm
- Sequential execution (fake parallel)
- Simple merge logic
- Manual trigger only

### Phase 2: Basic Swarm
- True parallel execution (asyncio)
- config.json profiles
- Logging infrastructure
- Auto-detection trigger

### Phase 3: Full Swarm
- SKILL.md generation
- Swarm boss synthesis
- User iteration loop
- Canvas integration
- Progress streaming

### Phase 4: Advanced
- Dynamic agent spawning
- Cross-swarm learning
- Cost optimization
- Multi-provider diversity

## Related Systems

- **Pipeline Executor:** Current Jarvis tool execution (deterministic)
- **Workflow System:** JSON-defined multi-step processes
- **OpenCode:** Autonomous coding agent (inspiration for autonomy)
- **Tool RAG:** Finding relevant tools (could help agent tool selection)
- **Feedback System:** Could rate swarm results for improvement

## References

- OpenAI Swarm: https://github.com/openai/swarm
- CrewAI: https://github.com/joaomdmoura/crewAI
- AutoGen: https://github.com/microsoft/autogen
- LangGraph: Multi-agent orchestration

---

*This is a living document. Add ideas, questions, and refinements as we iterate.*
