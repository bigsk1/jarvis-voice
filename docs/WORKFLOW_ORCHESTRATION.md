# Workflow Orchestration System

> **Status**: 📋 Design Phase  
> **Purpose**: Structured multi-tool workflow execution without hardcoded Python logic  
> **Last Updated**: January 2026

---

## Problem Statement

### Current State

Jarvis has two ways to handle multi-tool tasks:

| Approach | How it works | Limitation |
|----------|--------------|------------|
| **Free-form Loop** | LLM decides next tool each turn | Unreliable for complex sequences, forgets steps |
| **Composite Tools** | Python hardcodes tool orchestration (e.g., `status_recap`) | Requires coding, not reusable |

**The Gap**: No structured way to define and execute multi-tool workflows without:
- Hardcoding Python logic
- Relying on LLM to remember 5-7 step sequences
- Writing verbose prompts that LLMs don't always follow

### Evidence

1. **`status_recap.py`** (560 lines) - Calls 8-10 tools via Python subprocess because LLM couldn't reliably gather all data
2. **`deep_memory_search.py`** (610 lines) - Searches 6 data sources with custom Python because LLM missed sources
3. **`deep_research.md` prompt** (180 lines) - Detailed instructions LLM still doesn't follow consistently

---

## Proposed Solution: Workflow Recipes

### Concept

Create structured **workflow definitions** that the orchestrator can execute step-by-step, while still allowing LLM flexibility for parameters and decisions.

```
┌─────────────────────────────────────────────────────────────────┐
│                    WORKFLOW EXECUTION MODEL                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   User Query                                                     │
│       │                                                          │
│       ▼                                                          │
│   ┌──────────────┐    No Match    ┌──────────────┐              │
│   │   Workflow   │ ─────────────► │  Free-form   │              │
│   │   Matcher    │                │    Loop      │              │
│   └──────┬───────┘                │  (existing)  │              │
│          │ Match                  └──────────────┘              │
│          ▼                                                       │
│   ┌──────────────┐                                              │
│   │   Pipeline   │  Execute steps in order                      │
│   │   Executor   │  LLM fills parameters                        │
│   └──────┬───────┘                                              │
│          │                                                       │
│          ▼                                                       │
│   ┌──────────────┐                                              │
│   │   Step 1     │ → stash.open_space → save output             │
│   ├──────────────┤                                              │
│   │   Step 2     │ → brave_search → save output                 │
│   ├──────────────┤                                              │
│   │   Step 3     │ → crawl_url (for_each) → save outputs        │
│   ├──────────────┤                                              │
│   │   Step N     │ → canvas → final output                      │
│   └──────────────┘                                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Principles

1. **Structured but Flexible**: Define the tool sequence, let LLM decide parameters
2. **Data Flow**: Outputs from steps available to subsequent steps via variables
3. **Graceful Fallback**: If workflow fails, fall back to free-form or prompt
4. **Learning Integration**: Successful workflows inform intelligence layer
5. **Content Validation**: LLM validates data quality before proceeding (see below)

---

## Critical: Content Validation & Retry Logic

### The Garbage Data Problem

Blindly executing steps in sequence will fail when:
- `brave_search` returns but URLs are paywalled
- `crawl_url` gets captcha, cookie consent, or nav-only content
- `mcp_fetch` returns 403/paywall text
- Stash ends up with useless `.txt` files (just nav items)

**If the workflow just proceeds to the next step with garbage data, the entire workflow fails.**

### Solution: LLM-Validated Steps

For data-gathering steps (search, crawl, fetch), the LLM must validate output quality before proceeding:

```
┌─────────────────────────────────────────────────────────────────┐
│              CONTENT VALIDATION FLOW (Per Step)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Execute Step (e.g., crawl_url)                                │
│       │                                                          │
│       ▼                                                          │
│   ┌──────────────┐                                              │
│   │  LLM Check:  │  "Is this content useful for the task?"      │
│   │  Valid Data? │  - Has substantive text (>200 chars)?        │
│   └──────┬───────┘  - Not just nav/menu items?                  │
│          │          - Not paywall/captcha message?              │
│          │          - Contains relevant information?            │
│    ┌─────┴─────┐                                                │
│    │           │                                                │
│   YES          NO                                               │
│    │           │                                                │
│    ▼           ▼                                                │
│  Proceed   ┌──────────────┐                                     │
│  to next   │  Retry with  │  Try alternative URL/source         │
│  step      │  alternative │  (up to max_retries)                │
│            └──────┬───────┘                                     │
│                   │                                             │
│             Still failing?                                      │
│                   │                                             │
│            ┌──────┴──────┐                                      │
│            │             │                                      │
│         required?    optional?                                  │
│            │             │                                      │
│            ▼             ▼                                      │
│         ABORT         SKIP                                      │
│        workflow      this step                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Step Configuration for Validation

```json
{
  "step": 3,
  "tool": "crawl_url",
  "for_each": "${search_results.urls}",
  
  "validation": {
    "type": "llm",
    "prompt": "Does this content contain useful information about ${topic}? Not just navigation, paywall, or error messages?",
    "min_content_length": 200,
    "reject_patterns": ["subscribe to continue", "enable javascript", "captcha", "access denied"]
  },
  
  "retry": {
    "max_attempts": 3,
    "strategy": "next_url",
    "fallback_tools": ["mcp_fetch_fetch", "screenshot_url"]
  },
  
  "on_all_fail": "skip",
  "required_success_count": 2
}
```

### Validation Types

| Type | How it works | When to use |
|------|--------------|-------------|
| **llm** | LLM judges content quality | Complex content assessment |
| **heuristic** | Check length, patterns, structure | Fast pre-filter |
| **hybrid** | Heuristic first, LLM if passes | Best of both |

### Heuristic Checks (Fast, No LLM Call)

```python
def quick_content_check(content: str) -> bool:
    """Fast validation before LLM check."""
    
    # Too short = garbage
    if len(content.strip()) < 200:
        return False
    
    # Known garbage patterns
    garbage_patterns = [
        "subscribe to continue",
        "enable javascript",
        "captcha",
        "access denied",
        "403 forbidden",
        "please verify you are human",
        "cookies must be enabled",
        "create an account",
    ]
    content_lower = content.lower()
    if any(p in content_lower for p in garbage_patterns):
        return False
    
    # Mostly links/nav (high link-to-text ratio)
    link_count = content.count("](")  # Markdown links
    word_count = len(content.split())
    if word_count > 0 and link_count / word_count > 0.3:
        return False  # Probably nav/menu
    
    return True
```

### Retry Strategies

| Strategy | Description |
|----------|-------------|
| **next_url** | Try next URL from search results |
| **alternative_tool** | Try different fetch tool (crawl → mcp_fetch → screenshot) |
| **broaden_search** | Run new search with modified query |
| **skip** | Mark step as failed, continue if optional |

### Example: Research Workflow with Validation

```json
{
  "steps": [
    {
      "step": 1,
      "tool": "stash",
      "action": "open_space",
      "validation": null
    },
    {
      "step": 2,
      "tool": "brave_search",
      "validation": {
        "type": "heuristic",
        "min_results": 3
      }
    },
    {
      "step": 3,
      "tool": "crawl_url",
      "for_each": "${search_results.urls[:5]}",
      "validation": {
        "type": "hybrid",
        "heuristic": {"min_length": 200, "reject_patterns": ["paywall", "subscribe"]},
        "llm_prompt": "Is this substantive content about ${topic}?"
      },
      "retry": {
        "max_attempts": 5,
        "strategy": "next_url"
      },
      "required_success_count": 2,
      "on_all_fail": "abort_with_message"
    },
    {
      "step": 4,
      "tool": "stash",
      "action": "save",
      "for_each": "${validated_articles}",
      "validation": null
    }
  ]
}
```

### Workflow-Level Policies

```json
{
  "validation_policy": {
    "default_validation": "hybrid",
    "abort_threshold": 0.5,
    "max_total_retries": 10,
    "retry_delay_ms": 500
  }
}
```

| Policy | Description |
|--------|-------------|
| `abort_threshold` | Abort if >50% of required steps fail |
| `max_total_retries` | Cap total retries across all steps |
| `retry_delay_ms` | Delay between retries (rate limiting) |

### What This Prevents

| Failure Mode | Without Validation | With Validation |
|--------------|-------------------|-----------------|
| Paywall URL | Stash garbage, proceed | Retry next URL |
| Captcha page | Save captcha text | Skip, try alternative |
| Nav-only content | Create useless canvas | Reject, try new source |
| All sources fail | Silent garbage workflow | Abort with clear message |

---

## Workflow Management

### Enabled Flag & Variants

Workflows support an `enabled` flag for easy toggling without deletion:

```json
{
  "id": "deep_research_v1",
  "enabled": false,
  "name": "Deep Research (Conservative)"
},
{
  "id": "deep_research_v2", 
  "enabled": true,
  "name": "Deep Research (Aggressive)"
}
```

**Use Cases:**
- A/B test different workflow configurations
- Disable problematic workflows without deleting
- Keep experimental workflows ready to enable
- Version control with multiple variants

**Loading Rules:**
- Only `enabled: true` workflows are loaded
- If multiple workflows match the same trigger, first enabled match wins
- Workflows can share trigger patterns if only one is enabled

---

## Parameter Control: Layered Approach

Tools like `crawl_url` have many parameters (stealth, wait_for_js, css_selector, etc.). The question: **Who decides the values?**

### The Three Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                    PARAMETER RESOLUTION ORDER                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   1. STEP PARAMS (highest priority)                             │
│      Explicit values in step definition                         │
│      Example: {"css_selector": ".article-body"}                 │
│          │                                                       │
│          ▼                                                       │
│   2. WORKFLOW TOOL_DEFAULTS (middle priority)                   │
│      Defaults for all uses of a tool in this workflow           │
│      Example: crawl_url always uses stealth=true                │
│          │                                                       │
│          ▼                                                       │
│   3. LLM DECISION (lowest priority)                             │
│      LLM fills in remaining parameters based on context         │
│      Example: LLM decides wait_for based on site type           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Why Layering Matters

| Scenario | Without Layering | With Layering |
|----------|-----------------|---------------|
| Research workflow needs stealth | LLM might forget | `tool_defaults.crawl_url.stealth: true` ensures it |
| One step needs specific selector | Can't override | Step `params` override defaults |
| LLM should pick URL | Must hardcode | LLM fills `url` since not in params |

### Example: crawl_url in Research Workflow

```json
{
  "tool_defaults": {
    "crawl_url": {
      "stealth": true,
      "wait_for_js": true,
      "exclude_tags": ["nav", "footer", "aside"]
    }
  },
  
  "steps": [
    {
      "step": 3,
      "tool": "crawl_url",
      "params": {
        "css_selector": ".main-content"
      },
      "for_each": "${search_results.urls}"
    }
  ]
}
```

**Resolution for this step:**
```
stealth: true          ← from tool_defaults
wait_for_js: true      ← from tool_defaults  
exclude_tags: [...]    ← from tool_defaults
css_selector: ".main-content"  ← from step params (override)
url: "https://..."     ← from for_each variable
wait_for: null         ← LLM can decide if needed
js_code: null          ← LLM can decide if needed
```

### Parameter Types

| Type | Who Decides | Example |
|------|-------------|---------|
| **Fixed** | Workflow author | `stealth: true` (always for this workflow) |
| **Variable** | From previous step | `url: ${search_results.urls[0]}` |
| **LLM-Decided** | LLM at runtime | `wait_for` based on site structure |
| **Conditional** | LLM with guidance | `"if news site, use css_selector='.article'"` |

### LLM Guidance for Parameters

For complex decisions, provide hints instead of values:

```json
{
  "step": 3,
  "tool": "crawl_url",
  "params": {
    "stealth": true
  },
  "llm_hints": {
    "css_selector": "Look for main content area, typically .article, .content, main, or #post",
    "wait_for": "If site appears to be SPA or React, wait for .loaded or main content"
  }
}
```

### When to Pre-Set vs Let LLM Decide

| Pre-Set in Workflow | Let LLM Decide |
|---------------------|----------------|
| Security settings (stealth) | Content-dependent selectors |
| Performance settings (priority) | Site-specific wait conditions |
| Consistent filtering (exclude_tags) | Dynamic JS code |
| Known problematic sites | URL from search results |

---

## Implementation Options

### Option 1: Workflow Recipes (Full System)

Create `data/workflows/` folder with JSON workflow definitions:

```json
{
  "id": "deep_research",
  "name": "Deep Research Workflow",
  "description": "Comprehensive research with stash artifacts, memory, and canvas output",
  "enabled": true,
  "version": "1.0",
  
  "triggers": {
    "patterns": ["research about", "deep dive on", "comprehensive analysis of"],
    "keywords": ["research", "investigate", "deep dive"],
    "explicit": ["/research"]
  },
  
  "variables": {
    "topic": {"from": "query", "extract": "main subject"}
  },
  
  "tool_defaults": {
    "crawl_url": {
      "stealth": true,
      "wait_for_js": true,
      "exclude_tags": ["nav", "footer", "aside", "script", "style", "header"]
    },
    "stash": {
      "tags": ["research", "auto"]
    }
  },
  
  "steps": [
    {
      "step": 1,
      "tool": "stash",
      "action": "open_space",
      "params": {"labels": ["research", "${topic}"]},
      "output_var": "space_id",
      "required": true
    },
    {
      "step": 2,
      "tool": "brave_search",
      "params": {"query": "${topic}"},
      "output_var": "search_results",
      "required": true,
      "validation": {
        "type": "heuristic",
        "min_results": 3
      },
      "retry": {
        "max_attempts": 2,
        "strategy": "broaden_search"
      }
    },
    {
      "step": 3,
      "tool": "crawl_url",
      "for_each": "${search_results.urls[:5]}",
      "output_var": "articles",
      "params": {},
      "llm_hints": {
        "css_selector": "Look for main content: .article, .post-content, main, .entry-content",
        "wait_for": "If React/SPA site, wait for content to load"
      },
      "validation": {
        "type": "hybrid",
        "heuristic": {
          "min_length": 200,
          "reject_patterns": ["paywall", "subscribe to continue", "captcha", "enable javascript", "403", "access denied"]
        },
        "llm_prompt": "Does this content contain substantive information about ${topic}? Not just navigation, ads, or error messages?"
      },
      "retry": {
        "max_attempts": 5,
        "strategy": "next_url",
        "fallback_tools": ["mcp_fetch_fetch"]
      },
      "required_success_count": 2,
      "on_all_fail": "abort_with_message"
    },
    {
      "step": 4,
      "tool": "stash",
      "action": "save",
      "for_each": "${validated_articles}",
      "params": {"space_id": "${space_id}"},
      "required": true
    },
    {
      "step": 5,
      "tool": "remember",
      "condition": "${llm_decides}",
      "llm_prompt": "What key findings should be saved to long-term memory?",
      "required": false
    },
    {
      "step": 6,
      "tool": "canvas",
      "action": "create",
      "params": {
        "title": "Research: ${topic}",
        "content": "${llm_synthesize}"
      },
      "required": true
    }
  ],
  
  "llm_controls": [
    "url_selection",
    "memory_content", 
    "canvas_synthesis"
  ],
  
  "fallback_prompt": "deep_research.md",
  
  "success_speech": "Research complete. Canvas created with ${articles.length} sources.",
  "partial_speech": "Research partially complete. Some sources couldn't be retrieved."
}
```

**Pros**: Full control, explicit data flow, reusable
**Cons**: High implementation effort, new execution engine needed

---

### Option 2: Enhanced Commands with `tool_chain` (Quick Win)

Extend existing command format with tool sequencing:

```json
{
  "name": "research",
  "description": "Deep research workflow",
  "icon": "🔬",
  "instruction": "Follow the tool_chain sequence for comprehensive research.",
  
  "tool_chain": [
    {"tool": "stash", "action": "open_space", "note": "Create research bucket"},
    {"tool": "brave_search", "note": "Find sources"},
    {"tool": "crawl_url", "repeat": "as_needed", "note": "Get full articles"},
    {"tool": "stash", "action": "save", "repeat": "for_each_article", "note": "Save to stash"},
    {"tool": "remember", "optional": true, "note": "Save key findings"},
    {"tool": "canvas", "note": "Create synthesis"}
  ],
  
  "chain_mode": "guided",
  "force_tool": null,
  "exclude_tools": [],
  "response_style": "detailed"
}
```

**Router Injection**: When command matches, inject structured tool chain into LLM context:

```
WORKFLOW: research
Execute these tools IN ORDER:
1. stash (open_space) - Create research bucket → save space_id
2. brave_search - Find sources → save URLs
3. crawl_url - Get full articles (repeat as needed)
4. stash (save) - Save each article to space_id
5. remember - Save key findings (optional)
6. canvas - Create final synthesis

Pass data between steps. Complete all required steps before responding.
```

**Pros**: Low effort, extends existing system, immediate value
**Cons**: Still relies on LLM following instructions (better than prose prompts though)

---

### Option 3: Intelligence-Driven Macro Skills

Leverage the existing intelligence layer to learn and surface workflows:

```sql
-- Intelligence layer already tracks tool_sequence
-- When same sequence appears 3+ times for similar queries with success:

INSERT INTO insights (
  insight_type,
  description,
  applies_to_pattern,
  preferred_tools,
  confidence
) VALUES (
  'macro_skill',
  'For research queries, use: stash→search→crawl→save→canvas',
  'research queries, deep dive requests',
  '["stash", "brave_search", "crawl_url", "stash", "canvas"]',
  0.85
);
```

**Router Integration**:
```python
def route(self, query):
    # Check for macro_skill insights that match this query
    macro_skills = self.intelligence.get_macro_skills(query)
    if macro_skills:
        return {
            "mode": "guided",
            "suggested_sequence": macro_skills[0].preferred_tools,
            "confidence": macro_skills[0].confidence
        }
    return {"mode": "freeform"}
```

**Pros**: Self-learning, no manual workflow definition, leverages existing code
**Cons**: Needs enough successful examples to learn, emergent not prescribed

---

## Critical Analysis: Why Options 2 & 3 Are Problematic

### Option 2 Problem: Tool Chain is Just Prompt Injection

When we inject a "tool_chain" into the LLM context, the LLM is STILL presented with:

```
┌─────────────────────────────────────────────────────────────────┐
│              WHAT LLM SEES DURING ROUTING                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ✓ Ghost tools (always included)                               │
│   ✓ Tool RAG results (similar tools to query)                   │
│   ✓ Conversation history (if AUTO_CONTEXT enabled)              │
│   ✓ Intelligence insights (learned preferences)                 │
│   ✓ System prompt (base instructions)                           │
│   ✓ "Tool chain" injection ← Just ONE MORE competing signal    │
│                                                                  │
│   LLM must weigh ALL of these. Tool chain can be ignored.       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**The tool chain is NOT deterministic** - it's a suggestion that competes with:
- Insights saying "use X tool for this pattern"
- Tool RAG surfacing similar-but-different tools
- Ghost tools that might seem more relevant
- Conversation history implying different approach

**Result**: LLM might ignore the chain, skip steps, or use different tools. Same unreliability as prompts, just slightly more structured.

### Option 3 Problem: Learned Patterns Fight Intentional Changes

```
Scenario: Research workflow v1 works, intelligence learns it

    v1: stash → search → crawl → canvas  (learned, confidence 0.85)

You modify to v2: stash → search → crawl → pdf_read → canvas

    Intelligence still has v1 pattern with high confidence!
    LLM sees: "For research, use stash→search→crawl→canvas" 
    LLM ignores your new pdf_read step because learned pattern disagrees
```

**This is exactly what happened with pdf_read vs pdf_create** - learned bias toward old tool.

**Potential fix**: Hash workflow definition, invalidate learned patterns when hash changes.
But this adds complexity and the fundamental problem remains: **learned patterns are emergent, not prescribed**.

### The Real Solution: True Pipeline Mode

Option 1 (Workflow Recipes) with a **dedicated pipeline executor** that BYPASSES the normal routing:

```
┌─────────────────────────────────────────────────────────────────┐
│              PIPELINE MODE vs FREEFORM MODE                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   FREEFORM (current):                                           │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Query → Router → [Ghost tools + RAG + Insights + ...]   │  │
│   │       → LLM decides tool → Execute → Repeat              │  │
│   └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│   PIPELINE (proposed):                                          │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Query → Workflow Match? → YES → Pipeline Executor       │  │
│   │                                                          │  │
│   │  Pipeline Executor:                                      │  │
│   │  - Step 1: Execute tool (NO LLM tool selection)          │  │
│   │  - LLM ONLY fills parameters for THIS step               │  │
│   │  - Validate output → Step 2 → ... → Step N               │  │
│   │                                                          │  │
│   │  Ghost tools: NOT consulted                              │  │
│   │  Tool RAG: NOT consulted                                 │  │
│   │  Insights: NOT consulted for tool selection              │  │
│   │  LLM context: ONLY current step + previous outputs       │  │
│   └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline Mode: What LLM Sees Per Step

Instead of full routing context, LLM gets **focused step context**:

```
STEP 3 of 6: crawl_url

Previous outputs:
- space_id: "space_20260121_abc123"
- search_results: {urls: ["https://...", "https://..."], ...}

Your task: Fill parameters for crawl_url
- url: (pick from search_results.urls)
- css_selector: (optional, look for main content area)
- wait_for: (optional, if SPA site)

Workflow defaults applied: stealth=true, wait_for_js=true

Respond with JSON parameters only.
```

**Key difference**: LLM is NOT choosing which tool. It's ONLY filling parameters for the predetermined tool.

### Summary: Option Viability

| Option | Deterministic? | Future-Proof? | Recommendation |
|--------|---------------|---------------|----------------|
| **Option 1 (Recipes + Pipeline)** | ✅ Yes | ✅ Yes | **Implement this** |
| **Option 2 (Tool Chain Injection)** | ❌ No | ⚠️ Partial | Skip or use as fallback only |
| **Option 3 (Intelligence Learning)** | ❌ No | ❌ No | Don't use for workflow execution |

---

## Recommended Approach (Revised)

**After analysis, Option 1 (Workflow Recipes + Pipeline Executor) is the only viable path.**

### Why Skip Options 2 & 3

| Option | Problem |
|--------|---------|
| **Option 2** | Tool chain injection is just prompt injection - competes with ghost tools, RAG, insights |
| **Option 3** | Learned patterns fight intentional changes - exactly what happened with pdf_read/pdf_create |

### Phase 1: Workflow Recipes + Pipeline Executor

Build the full system (no shortcuts):

1. **Workflow JSON schema** - Define structure for `data/workflows/*.json`
2. **Workflow loader + matcher** - Load enabled workflows, match triggers to queries
3. **Pipeline executor** - The core value:
   - Execute steps in order (tool selection is NOT LLM's choice)
   - LLM only fills parameters per step with **focused context**
   - **Bypass** ghost tools, tool RAG, insights for tool selection
   - Handle validation, retry, data flow between steps
4. **Fallback to freeform** - If no workflow matches, use existing routing

### What LLM Sees: Pipeline vs Freeform

```
FREEFORM (current):
  LLM sees: 50+ tools, RAG results, insights, history, system prompt
  LLM decides: Which tool to call
  Problem: Too many competing signals

PIPELINE (proposed):
  LLM sees: "Step 3: crawl_url. Fill these parameters. Here's previous step output."
  LLM decides: Parameter values only
  Benefit: Focused task, no competing tool choices
```

### Optional: Intelligence for Analytics Only

Intelligence layer can still:
- ✅ **Record** workflow executions and success rate
- ✅ **Suggest** new workflow candidates from repeated patterns  
- ❌ **NOT influence** active workflow execution (no learned bias)

### Implementation Priority

| Task | Effort | Impact | Order |
|------|--------|--------|-------|
| Workflow JSON schema | Low | Foundation | 1 |
| Workflow loader + enabled filter | Low | Management | 2 |
| Workflow matcher (triggers) | Medium | Enables recipes | 3 |
| Pipeline executor (core loop) | High | **The actual value** | 4 |
| Parameter resolution (layering) | Medium | Flexibility | 5 |
| Validation + retry logic | Medium | Reliability | 6 |
| Fallback to freeform | Low | Safety net | 7 |

---

## Data Flow Between Steps

### Variable System

```
Step 1 output → ${step1_output}
Step 2 output → ${step2_output}
Named output  → ${space_id}, ${articles}
```

### Example Flow

```
Step 1: stash.open_space
  Input:  labels=["research", "quantum computing"]
  Output: space_id="space_20260121_abc123"
  
Step 2: brave_search
  Input:  query="quantum computing breakthroughs 2026"
  Output: search_results={urls: [...], snippets: [...]}
  
Step 3: crawl_url (for_each)
  Input:  url=${search_results.urls[0]}
  Output: articles[0]={content: "...", title: "..."}
  
Step 4: stash.save (for_each)
  Input:  space_id=${space_id}, content=${articles[0].content}
  Output: file_ref="space_20260121_abc123/article_1.txt"
```

---

## Execution Modes

| Mode | Description | When to Use |
|------|-------------|-------------|
| **freeform** | LLM decides tools each turn (current) | Simple queries, unknown patterns |
| **guided** | Inject tool chain, LLM follows | Known workflows via commands |
| **pipeline** | Execute steps programmatically | Complex workflows with data flow |

### Mode Selection Logic

```python
def select_mode(self, query, command_match, workflow_match):
    if workflow_match:
        return "pipeline"
    elif command_match and command_match.get("tool_chain"):
        return "guided"
    else:
        return "freeform"
```

---

## Integration Points

### Router (`lib/router_v2.py`)
- Match workflows by trigger patterns
- Inject tool chain into LLM context
- Select execution mode

### Executor (`orchestrator/executor.py`)
- New pipeline execution path
- Variable substitution engine
- Step result tracking

### Commands (`jarvis-web/data/commands/`)
- Extended JSON schema with `tool_chain`
- Chain mode configuration

### Workflows (`data/workflows/`)
- New folder for workflow JSON files
- Workflow validation on load

### Intelligence (`lib/intelligence.py`)
- Record workflow executions
- Generate macro_skill insights
- Surface learned sequences

---

## Example Workflows to Implement

### 1. Deep Research
```
stash.open_space → brave_search → crawl_url* → stash.save* → remember? → canvas
```

### 2. Status Briefing (Replace composite tool)
```
get_time → weather → crypto_price* → stock_price* → list_alerts → list_reminders → system_monitor → canvas
```

### 3. Document Creation
```
stash.list → stash.read* → pdf_create → printer? | send_email?
```

### 4. Web Archive
```
crawl_url → stash.save → stash.remember → canvas
```

---

## Comparison: Current vs. Proposed

| Aspect | Current (Free-form) | Proposed (Workflows) |
|--------|---------------------|----------------------|
| Tool selection | LLM each turn | Prescribed sequence |
| Data flow | Implicit in context | Explicit variables |
| Reliability | Inconsistent | Deterministic |
| Flexibility | Full LLM control | LLM controls parameters |
| Learning | Post-hoc recording | Can inform future |
| Implementation | Existing | New executor needed |

---

## Open Questions

### Addressed in This Design
- ✅ **Error Recovery**: Retry with alternatives, skip optional, abort required (see Content Validation section)
- ✅ **Partial Success**: `required_success_count` and `abort_threshold` policies
- ✅ **Garbage Data**: LLM + heuristic validation before proceeding

### Still Open
1. **Branching**: How to handle conditional paths (if/else based on content)?
   - Option A: LLM decides at branch points
   - Option B: Explicit conditions in workflow JSON
   
2. **User Override**: Can user interrupt mid-workflow?
   - "Stop researching, I found what I need"
   - "Skip the canvas, just tell me the summary"
   
3. **Nested Workflows**: Can one workflow call another?
   - E.g., "research" workflow calls "web_archive" sub-workflow
   
4. **Cost/Time Budgets**: Should workflows have limits?
   - Max LLM calls for validation
   - Max execution time before abort
   
5. **Parallel Steps**: Can independent steps run concurrently?
   - E.g., crawl 3 URLs simultaneously

---

## Related Documentation

- [MULTI_TURN_ORCHESTRATION.md](MULTI_TURN_ORCHESTRATION.md) - Current free-form loop
- [TOOL_CALLING_SYSTEM.md](TOOL_CALLING_SYSTEM.md) - How tools are invoked
- [INTELLIGENCE_LAYER.md](INTELLIGENCE_LAYER.md) - Learning from experiences
- [STASH_SYSTEM.md](STASH_SYSTEM.md) - Artifact storage for workflows
- [phone/MULTI_TOOL_WORKFLOWS.md](phone/MULTI_TOOL_WORKFLOWS.md) - Phone call workflow examples

---

## Next Steps

- [ ] Decide: Phase 1 (commands) vs Phase 2 (full recipes)
- [ ] Design tool_chain JSON schema
- [ ] Prototype router injection
- [ ] Test with `research` workflow
- [ ] Document learnings

---

**Questions or ideas?** This is a design doc - implementation details TBD based on chosen approach.
