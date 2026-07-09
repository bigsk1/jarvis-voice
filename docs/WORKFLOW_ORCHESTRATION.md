# Workflow Orchestration System

> **Status**: ✅ Implemented
> **Purpose**: Structured multi-tool workflow execution without hardcoded Python logic
> **Last Updated**: February 4, 2026

---

![workflow-graph](images/workflow-info-graph.jpeg)

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

## 🚀 Token Efficiency: The Hidden Superpower

> **TL;DR**: Workflows bypass the entire LLM routing overhead, reducing token usage from ~25,000+ to near-zero for orchestration.

### Normal LLM Chat vs Workflows

| Aspect | Normal LLM Chat | Workflow |
|--------|----------------|----------|
| System prompt | ~5,000 tokens | **0 tokens** |
| Tool definitions (57 tools) | ~30,000 tokens | **0 tokens** |
| MCP server descriptions | ~1,000 tokens | **0 tokens** |
| Tool selection decision | ~500 tokens per turn | **0 tokens** |
| Multi-turn context | Accumulates | **0 tokens** |
| **Total orchestration overhead** | **~35,000+ tokens** | **~0-500 tokens** |

### Real-World Example: `/quick_note`

```
Workflow: get_time → remember → canvas

Normal LLM routing would cost:
  System prompt:     5,245 tokens
  Tool definitions: 29,838 tokens
  Query + response:    500 tokens
  ─────────────────────────────────
  TOTAL:            35,583 tokens

Workflow actually costs:
  LLM orchestration:     0 tokens  (deterministic)
  Parameter filling:   244 tokens  (if using llm_prompt)
  ─────────────────────────────────
  TOTAL:               244 tokens  ✅ 99.3% savings!
```

### Why This Matters for Local Models

| Context Window | Normal Chat Baseline | With Workflows |
|----------------|---------------------|----------------|
| 32K (Qwen3) | 35K tokens = **OVERFLOW** | 244 tokens = **0.8%** |
| 8K (small models) | 35K tokens = **IMPOSSIBLE** | 244 tokens = **3%** |
| 128K (Claude) | 35K tokens = 27% | 244 tokens = **0.2%** |

**For local models with limited context windows, workflows are the ONLY way to execute complex multi-tool tasks reliably.**

### What Uses LLM Tokens in Workflows?

Only these optional features use LLM:

1. **`llm_prompt`** - Dynamic parameter generation
2. **Content validation** - Quality checks on results
3. **Conditional decisions** - `llm_decide` for branching

If your workflow doesn't use these features, it uses **0 LLM tokens** for orchestration - pure deterministic execution.

### Token Tracking in WebUI

The WebUI token counter shows:
- **Normal chat**: Full token usage (system prompt + tools + conversation)
- **Workflows**: Only LLM tokens used for parameter filling/validation

A workflow showing "0 tokens" means it executed entirely deterministically - no LLM overhead at all!

---

## Quick Start: Creating a Workflow

### Step 1: Create the JSON file

Create a new file in `data/workflows/` (e.g., `my_workflow.json`):

```json
{
  "id": "my_workflow",
  "name": "My Workflow",
  "description": "Description shown in WebUI",
  "enabled": true,
  "version": "1.0",

  "triggers": {
    "explicit": ["/mycommand"]
  },

  "variables": {
    "topic": {"from": "query", "extract": "main_subject"}
  },

  "steps": [
    {
      "step": 1,
      "tool": "brave_search",
      "params": {"query": "${topic}"},
      "output_var": "search_results",
      "required": true
    },
    {
      "step": 2,
      "tool": "canvas",
      "action": "create",
      "params": {"title": "Results: ${topic}"},
      "llm_prompt": "Summarize these search results:\n${search_results}",
      "required": true
    }
  ],

  "success_speech": "Workflow complete!",
  "abort_speech": "Workflow failed."
}
```

### Step 2: Test via CLI

```bash
source ~/jarvis-venv/bin/activate
./orchestrator/orchestrator_v2.py cloud "/mycommand quantum computing"
```

### Step 3: Use via WebUI

Restart WebUI, then type `/mycommand topic` in chat. The workflow appears in `/` autocomplete.

---

## Workflow JSON Reference

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (used in logs) |
| `name` | string | Display name |
| `enabled` | boolean | Set `false` to disable without deleting |
| `triggers.explicit` | array | Commands like `["/research"]` |
| `steps` | array | List of step objects |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Shown in WebUI workflow list |
| `version` | string | For tracking changes |
| `variables` | object | Extract variables from query |
| `tool_defaults` | object | Default params per tool |
| `success_speech` | string | Spoken on success |
| `abort_speech` | string | Spoken on failure |

### Step Object

```json
{
  "step": 1,                          // Step number (for ordering/logging)
  "tool": "tool_name",                // Tool to execute
  "action": "action_name",            // For tools with actions (stash, canvas)
  "params": {"key": "value"},         // Tool parameters (supports ${variables})
  "output_var": "my_var",             // Store result in variable
  "extract": {"var_name": "path"},    // Extract specific fields from result
  "llm_prompt": "Generate content",   // LLM generates content parameter
  "validation": {...},                // Validation rules
  "retry": {...},                     // Retry configuration
  "required": true,                   // Abort if fails (default: true)
  "on_fail": "continue",              // Override abort behavior
  "description": "What this does"     // For logging
}
```

---

## Variable System

### Variable Sources

1. **From query** - Extracted from user input via `variables` section
2. **From steps** - `output_var` and `extract` from previous steps
3. **Built-in** - `timestamp`, `topic`

### Variable Syntax

| Syntax | Example | Description |
|--------|---------|-------------|
| `${var}` | `${topic}` | Simple variable |
| `${obj.key}` | `${article.url}` | Nested path |
| `${arr[0]}` | `${urls[0]}` | Array index |
| `${arr[:N]}` | `${urls[:5]}` | Array slice (first N) |

### Extracting Variables from Query

```json
"variables": {
  "url": {"from": "query", "extract": "url"},
  "topic": {"from": "query", "extract": "main_subject"}
}
```

**Supported extractions:**
- `url` - Extracts URL from query (auto-adds `https://` to bare domains)
- `main_subject` - Extracts topic after the command

**Example:** `/archive bigsk1.com` extracts:
- `url` = `https://bigsk1.com`
- `topic` = `bigsk1.com`

### Variable Transforms

Derive variables from other variables using `transform`:

```json
"variables": {
  "url": {"from": "query", "extract": "url"},
  "url_domain": {"from": "url", "transform": "domain"}
}
```

**Supported transforms:**
| Transform | Input | Output |
|-----------|-------|--------|
| `domain` | `https://www.bigsk1.com/page` | `bigsk1.com` |
| `lowercase` | `HELLO` | `hello` |
| `uppercase` | `hello` | `HELLO` |
| `strip` | `  text  ` | `text` |

**Use case:** Canvas folder organization
```json
"params": {
  "title": "Workflows/Archive/${url_domain}"
}
```
Creates: `Workflows/Archive/bigsk1.com` instead of broken folder from URL.

### Extracting Data from Step Results

Use `extract` to pull specific fields from tool output:

```json
{
  "step": 2,
  "tool": "stash",
  "action": "save",
  "output_var": "stash_result",
  "extract": {
    "stash_ref": "ref",           // data.ref -> ${stash_ref}
    "space_id": "space_id"        // data.space_id -> ${space_id}
  }
}
```

**Common extraction paths by tool:**

| Tool | Field | Path |
|------|-------|------|
| `stash` (save) | Reference | `ref` |
| `stash` (save) | Space ID | `space_id` |
| `remember` | Memory ID | `memory_id` |
| `canvas` | Page ID | `page_id` |
| `crawl_url` | Content | `results[0].markdown` |
| `brave_search` | URLs | `results[*].url` |

### Built-in Output Transforms

Some tools have automatic extraction (no `extract` needed):

**`crawl_url`** - Automatically creates `${article}` with:
- `${article.title}` - Page title
- `${article.content}` - Markdown content
- `${article.url}` - Source URL

**Search tools** - Automatically creates `${search_results.urls}` array

---

## LLM Parameter Filling

### Using `llm_prompt`

When a step needs LLM-generated content (e.g., summaries), use `llm_prompt`:

```json
{
  "step": 4,
  "tool": "canvas",
  "action": "create",
  "params": {
    "title": "Archive: ${article.url}",
    "tags": ["archive"]
  },
  "llm_prompt": "Create a summary of this webpage.\n\nURL: ${article.url}\nContent:\n${article.content}\n\nGenerate markdown with key points.",
  "required": true
}
```

**How it works:**
1. Variables in `llm_prompt` are resolved (e.g., `${article.content}` → actual content)
2. LLM generates content based on the prompt
3. Result is passed as `content` parameter to the tool

### Variable Resolution in Prompts

All `${...}` variables in `llm_prompt` are resolved:
- Simple: `${topic}` → `"quantum computing"`
- Nested: `${article.url}` → `"https://bigsk1.com"`
- Objects: `${stash_result}` → JSON representation

---

## Working Example: Web Archive Workflow

This workflow demonstrates all key patterns:

```json
{
  "id": "web_archive",
  "name": "Web Archive Workflow",
  "description": "Fetch a URL, save to stash, and create a canvas summary.",
  "enabled": true,
  "version": "1.0",

  "triggers": {
    "explicit": ["/archive"]
  },

  "variables": {
    "url": {"from": "query", "extract": "url"},
    "topic": {"from": "query", "extract": "main_subject"}
  },

  "tool_defaults": {
    "crawl_url": {
      "stealth": true,
      "wait_for_js": true
    }
  },

  "steps": [
    {
      "step": 1,
      "tool": "crawl_url",
      "params": {"url": "${url}"},
      "output_var": "article",
      "validation": {
        "type": "heuristic",
        "heuristic": {
          "min_length": 200,
          "reject_patterns": ["paywall", "captcha required", "403 forbidden"]
        }
      },
      "required": true,
      "description": "Fetch article content"
    },
    {
      "step": 2,
      "tool": "stash",
      "action": "save",
      "params": {
        "kind": "text",
        "text": "${article.content}",
        "name": "archive_${timestamp}.txt",
        "tags": ["archive", "${topic}"]
      },
      "extract": {
        "stash_ref": "ref"
      },
      "required": true,
      "description": "Save to stash"
    },
    {
      "step": 3,
      "tool": "stash",
      "action": "remember",
      "params": {
        "search": "${stash_ref}",
        "key": "Archived: ${article.url}",
        "category": "archive",
        "importance": 6
      },
      "required": false,
      "on_fail": "continue",
      "description": "Save to memory (optional)"
    },
    {
      "step": 4,
      "tool": "canvas",
      "action": "create",
      "params": {
        "title": "Archive: ${article.url}",
        "tags": ["archive", "${topic}"]
      },
      "llm_prompt": "Create a summary of this archived webpage.\n\nSource URL: ${article.url}\nStash reference: ${stash_ref}\nDate archived: ${timestamp}\n\nContent:\n${article.content}\n\nGenerate markdown with:\n- Title/source\n- Key points (3-5 bullets)\n- Stash reference\n- Archive date",
      "required": true,
      "description": "Create canvas summary"
    }
  ],

  "success_speech": "Article archived. I saved it to stash, added the key points to memory, and created a canvas summary.",
  "abort_speech": "I couldn't archive that page. It may be paywalled or have access restrictions."
}
```

**Usage:** `/archive https://example.com` or `/archive example.com`

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

### Trigger Behavior: Explicit Commands Only (Safe Default)

**By default, workflows ONLY trigger on explicit commands like `/research` or `/archive`.**

This prevents workflows from accidentally hijacking normal queries:

```
# Default behavior (explicit_only=True):
"research about quantum computing"  →  No match (goes to freeform)
"/research quantum computing"       →  Matches deep_research workflow

# With explicit_only=False (risky):
"research about quantum computing"  →  Matches deep_research workflow
```

**Why explicit-only is the default:**
- Workflows are deterministic multi-step pipelines
- User should consciously choose to run a workflow vs. normal query
- Prevents "I just wanted a quick search" from triggering 6-step research
- Pattern matching can be too aggressive (e.g., "save" matches web_archive)

**Trigger types in workflow JSON:**
```json
"triggers": {
  "explicit": ["/research"],      // ALWAYS checked (safe)
  "patterns": ["research about"], // Only if explicit_only=False
  "keywords": ["research", "deep"] // Only if explicit_only=False
}
```

**To enable pattern matching** (use with caution):
```python
loader = WorkflowLoader(explicit_only=False)
```

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
│   ✓ Ghost tools (prioritized inside Tool RAG cap)               │
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
  LLM sees: selected Tool RAG schemas, insights, history, system prompt
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

## Implementation Architecture

### Current Orchestrator Structure

```
orchestrator/
├── orchestrator_v2.py   # Main Orchestrator class, process() entry point
├── router_v2.py         # LLMRouter - decides which tool (freeform mode)
└── executor.py          # ToolExecutor - executes individual tools
```

### Proposed New Files

```
orchestrator/
├── workflow_loader.py   # NEW: Load workflows, match triggers
├── pipeline_executor.py # NEW: Execute workflow steps deterministically
└── ... existing files unchanged ...

data/
├── workflows/           # NEW: Workflow JSON definitions
│   ├── deep_research.json
│   ├── status_briefing.json
│   └── ...
```

### Integration Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    orchestrator_v2.py                            │
│                    Orchestrator.process()                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   def process(self, transcript, ...):                           │
│       │                                                          │
│       ▼                                                          │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  1. Check for workflow match (NEW)                       │  │
│   │     workflow = self.workflow_loader.match(transcript)    │  │
│   └──────────────────────────────────────────────────────────┘  │
│       │                                                          │
│       ├── Match found ──────────────────────────────────────────│──► Pipeline Mode
│       │                                                          │
│       │   ┌──────────────────────────────────────────────────┐  │
│       │   │  return self.pipeline_executor.execute(          │  │
│       │   │      workflow, transcript, ...                   │  │
│       │   │  )                                               │  │
│       │   └──────────────────────────────────────────────────┘  │
│       │                                                          │
│       └── No match ─────────────────────────────────────────────│──► Freeform Mode
│                                                                  │
│           ┌──────────────────────────────────────────────────┐  │
│           │  # Existing multi-turn loop (unchanged)          │  │
│           │  for turn_num in range(max_turns):               │  │
│           │      route = self.router.route(...)              │  │
│           │      if route["intent"] == "tool":               │  │
│           │          result = self.executor.execute(...)     │  │
│           └──────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### File Responsibilities

#### `orchestrator/workflow_loader.py` (NEW)

```python
class WorkflowLoader:
    """Load and match workflow definitions."""

    def __init__(self, workflows_dir: str):
        self.workflows_dir = Path(workflows_dir)
        self.workflows = {}
        self._load_workflows()

    def _load_workflows(self):
        """Load all enabled workflow JSON files."""
        for path in self.workflows_dir.glob("*.json"):
            workflow = json.load(path.open())
            if workflow.get("enabled", True):  # Default enabled
                self.workflows[workflow["id"]] = workflow

    def match(self, query: str) -> Optional[Dict]:
        """Match query against workflow triggers."""
        query_lower = query.lower()
        for workflow in self.workflows.values():
            triggers = workflow.get("triggers", {})

            # Check explicit commands (e.g., "/research")
            for explicit in triggers.get("explicit", []):
                if query_lower.startswith(explicit):
                    return workflow

            # Check patterns (e.g., "research about")
            for pattern in triggers.get("patterns", []):
                if pattern.lower() in query_lower:
                    return workflow

            # Check keywords
            keywords = triggers.get("keywords", [])
            if keywords and all(kw.lower() in query_lower for kw in keywords[:2]):
                return workflow

        return None

    def reload(self):
        """Hot-reload workflows (for development)."""
        self.workflows = {}
        self._load_workflows()
```

#### `orchestrator/pipeline_executor.py` (NEW)

```python
class PipelineExecutor:
    """Execute workflow pipelines step-by-step."""

    def __init__(self, mode: str, executor: ToolExecutor, provider):
        self.mode = mode
        self.executor = executor  # Reuse existing ToolExecutor
        self.provider = provider  # LLM for parameter filling

    def execute(self, workflow: Dict, query: str,
                status_callback=None) -> Dict[str, Any]:
        """
        Execute a workflow pipeline.

        Returns same format as Orchestrator.process() for compatibility.
        """
        variables = {"query": query, "topic": self._extract_topic(query)}
        tool_defaults = workflow.get("tool_defaults", {})
        steps = workflow.get("steps", [])
        results = []
        tools_used = []

        for step in steps:
            step_num = step.get("step", len(results) + 1)
            tool_name = step["tool"]

            # Status update
            if status_callback:
                status_callback(f"Step {step_num}: {tool_name}")

            # Resolve parameters (layered: step > tool_defaults > llm)
            params = self._resolve_params(
                step, tool_defaults.get(tool_name, {}), variables
            )

            # Handle for_each loops
            if "for_each" in step:
                items = self._resolve_variable(step["for_each"], variables)
                step_results = []
                success_count = 0

                for item in items:
                    item_params = {**params, **self._item_to_params(item, step)}
                    result = self.executor.execute(tool_name, item_params)

                    # Validate result
                    if self._validate_result(result, step, variables):
                        step_results.append(result)
                        success_count += 1
                    elif step.get("retry"):
                        # Retry logic
                        pass

                # Check required_success_count
                required = step.get("required_success_count", 1)
                if success_count < required:
                    if step.get("on_all_fail") == "abort_with_message":
                        return self._abort_response(workflow, step, results)

                variables[step.get("output_var", f"step{step_num}")] = step_results
            else:
                # Single execution
                result = self.executor.execute(tool_name, params)

                if not result.get("ok") and step.get("required", True):
                    # Required step failed
                    if step.get("on_all_fail") == "abort_with_message":
                        return self._abort_response(workflow, step, results)

                # Store output
                if step.get("output_var"):
                    variables[step["output_var"]] = result.get("data", {})

            results.append({"step": step_num, "tool": tool_name, "result": result})
            tools_used.append(tool_name)

        # Build final response
        return {
            "ok": True,
            "speech": self._build_speech(workflow, results, variables),
            "data": {"workflow_id": workflow["id"], "results": results},
            "tools_used": tools_used
        }

    def _resolve_params(self, step, tool_defaults, variables) -> Dict:
        """Resolve parameters: step > tool_defaults > llm_fills."""
        params = {**tool_defaults}  # Start with defaults

        # Override with step params
        for key, value in step.get("params", {}).items():
            if isinstance(value, str) and value.startswith("${"):
                params[key] = self._resolve_variable(value, variables)
            else:
                params[key] = value

        # LLM fills remaining (if llm_hints provided)
        if step.get("llm_hints"):
            llm_params = self._llm_fill_params(step, variables)
            for key, value in llm_params.items():
                if key not in params:  # Don't override explicit params
                    params[key] = value

        return params

    def _validate_result(self, result, step, variables) -> bool:
        """Validate step result using configured validation."""
        if not step.get("validation"):
            return result.get("ok", False)

        validation = step["validation"]
        content = result.get("data", {}).get("content", "")

        # Heuristic checks
        if validation.get("type") in ["heuristic", "hybrid"]:
            heuristic = validation.get("heuristic", validation)

            if len(content) < heuristic.get("min_length", 0):
                return False

            for pattern in heuristic.get("reject_patterns", []):
                if pattern.lower() in content.lower():
                    return False

        # LLM validation
        if validation.get("type") in ["llm", "hybrid"] and validation.get("llm_prompt"):
            # Call LLM to validate
            pass

        return True
```

#### `orchestrator/orchestrator_v2.py` (MODIFIED)

```python
# Add imports at top
from workflow_loader import WorkflowLoader
from pipeline_executor import PipelineExecutor

class Orchestrator:
    def __init__(self, mode='cloud', ...):
        # ... existing init ...

        # NEW: Initialize workflow system
        workflows_dir = self.project_root / "data" / "workflows"
        if workflows_dir.exists():
            self.workflow_loader = WorkflowLoader(str(workflows_dir))
            self.pipeline_executor = PipelineExecutor(
                mode, self.executor, self.router.provider
            )
        else:
            self.workflow_loader = None
            self.pipeline_executor = None

    def process(self, transcript: str, ...) -> Dict[str, Any]:
        # ... existing setup code ...

        # NEW: Check for workflow match BEFORE freeform loop
        if self.workflow_loader:
            workflow = self.workflow_loader.match(transcript)
            if workflow:
                # Execute via pipeline (bypasses freeform routing)
                return self.pipeline_executor.execute(
                    workflow,
                    transcript,
                    status_callback=self.status_updater.update
                )

        # ... existing freeform loop (unchanged) ...
```

### Web UI Integration

The pipeline executor returns a response compatible with the WebUI:

```python
{
    "ok": True,
    "speech": "Research complete...",
    "data": {
        "workflow_id": "deep_research",
        "workflow_name": "Deep Research Workflow",
        "steps_completed": 4,
        "results": [
            {"step": 1, "tool": "stash", "ok": True, "data": {...}},
            {"step": 2, "tool": "brave_search", "ok": True, "data": {...}},
            ...
        ]
    },
    "tools_used": ["stash", "brave_search", "crawl_url", "canvas"],
    "usage": {"input_tokens": 500, "output_tokens": 200, ...},  # LLM usage for param filling
    "server_side_tools": {"SERVER_SIDE_TOOL_X_SEARCH": 2, "SERVER_SIDE_TOOL_WEB_SEARCH": 1}  # xAI/Anthropic native tools
}
```

**Server-Side Tools Tracking:**

Workflows track usage of LLM provider native tools (xAI `web_search`, `x_search`, Anthropic `web search`, etc.):
- Accumulated from LLM calls during parameter filling and validation
- Returned in response for WebUI toast notification ("🔍 Server-side: X Search, Web Search")
- Logged to `logs/server-side-tools/server-tools-YYYY-MM-DD.jsonl`
- View summary: `LLMLogger().get_server_side_tools_summary(days=7)`

**WebUI Changes Made:**

| Component | Change |
|-----------|--------|
| `jarvis-web/server/routes/api.py` | Added `/api/workflows` endpoint to list enabled workflows |
| `jarvis-web/client/js/chat.js` | Workflow autocomplete on `/` prefix, replaced old commands system |
| `jarvis-web/server/sockets/chat.py` | Detects workflow results, emits `tool:complete` for each step |
| `jarvis-web/client/js/logs.js` | Added workflow log source button |
| `jarvis-web/server/services/log_streamer.py` | Added workflow log parsing |

**How WebUI Displays Workflows:**

1. User types `/` → autocomplete shows enabled workflows
2. User selects workflow → sends to orchestrator
3. Backend detects workflow, runs pipeline executor
4. For each step, `tool:complete` event sent to frontend
5. Tool cards appear in correct execution order
6. Final response displayed with workflow speech

**Removed:** The old `/commands` system was removed. Commands were prompt hints that competed with tool RAG. Workflows are deterministic pipelines that replace them entirely. Prompts (`@` prefix) remain unchanged.

### Testing Strategy

```bash
# Test workflow loading
python -c "
from orchestrator.workflow_loader import WorkflowLoader
loader = WorkflowLoader('data/workflows')
print(f'Loaded {len(loader.workflows)} workflows')
print(loader.match('research about quantum computing'))
"

# Test pipeline execution
./orchestrator/orchestrator_v2.py cloud "research about quantum computing 2026"

# Compare with freeform (should match if no workflow defined)
./orchestrator/orchestrator_v2.py cloud "what time is it"
```

---

## Integration Points (Summary)

| Component | Change | Effort |
|-----------|--------|--------|
| `orchestrator/workflow_loader.py` | **NEW FILE** | Medium |
| `orchestrator/pipeline_executor.py` | **NEW FILE** | High |
| `orchestrator/orchestrator_v2.py` | Add workflow check at top of `process()` | Low |
| `data/workflows/*.json` | **NEW FOLDER** + JSON files | Low |
| `router_v2.py` | No changes | None |
| `executor.py` | No changes (reused by pipeline) | None |
| Web UI / Terminal | No changes (same response format) | None |

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
- [tools/phone/MULTI_TOOL_WORKFLOWS.md](tools/phone/MULTI_TOOL_WORKFLOWS.md) - Phone call workflow examples

---

## Next Steps

### Phase 1: Foundation ✅ COMPLETE
- [x] Create `data/workflows/` folder
- [x] Create `orchestrator/workflow_loader.py`
- [x] Create first workflow JSON: `deep_research.json`
- [x] Create second workflow JSON: `web_archive.json`
- [x] Create third workflow JSON: `quick_note.json`
- [x] Test workflow matching
- [x] **Safe by default**: Only explicit commands (`/research`, `/archive`) trigger workflows
  - Pattern/keyword matching disabled by default to prevent hijacking normal queries
  - Can be enabled with `explicit_only=False` if needed

### Phase 2: Pipeline Executor ✅ COMPLETE
- [x] Create `orchestrator/pipeline_executor.py`
- [x] Implement step execution loop
- [x] Implement variable substitution (including array slicing `${urls[:5]}`)
- [x] Implement parameter layering (step > defaults > LLM)
- [x] Handle for_each loops with validation
- [x] Extract URLs from MCP search results
- [x] LLM provider integration for parameter filling
- [x] Generic output extraction via `_apply_output_transforms()`
- [x] Step-defined `extract` rules support
- [x] Nested path resolution for variables (e.g., `${article.url}`)
- [x] URL extraction from query (handles bare domains like `bigsk1.com`)
- [x] **Variable transforms** - Derive variables from others (e.g., `domain` from URL)

### Phase 3: WebUI Integration ✅ COMPLETE
- [x] Import WorkflowLoader and PipelineExecutor in `orchestrator_v2.py`
- [x] Initialize workflow components in Orchestrator `__init__`
- [x] Add `_try_workflow()` method to check for explicit commands
- [x] Workflow check runs before normal LLM routing
- [x] Non-workflow queries pass through to normal flow unchanged
- [x] Status updates integrated via existing StatusUpdater
- [x] **Removed old `/commands` system** - Workflows replace commands
- [x] **WebUI API**: `/api/workflows` lists enabled workflows
- [x] **WebUI autocomplete**: Type `/` to see workflow suggestions
- [x] **WebUI tool cards**: Display workflow step results in order
- [x] **WebUI logs**: Workflow execution logs in server logs panel

### Phase 4: Validation & Retry (Partial)
- [x] Implement heuristic content validation (min_length, reject_patterns)
- [x] Basic retry counting in for_each loops
- [x] Required step failure aborts workflow by default
- [x] `on_fail: continue` option for non-critical steps
- [ ] Implement LLM content validation (llm_prompt for validation)
- [ ] Implement advanced retry strategies (next_url, alternative_tool, broaden_search)

### Phase 5: Polish
- [ ] Add more workflow recipes - ssh_tool have ideas for creating and fully controlling remote vps2, start to finish app on vps2.. x amount of steps stop summarize, continue X amount of steps stop summarize, need way to pause during workflow for summary and not rerun workflow from start. (15 tool calls limit via .env can increase or lower as needed)
- [ ] Add workflow execution logging to intelligence layer
- [ ] Document in main README
- [ ] Create a workflow builder (proposed command: `bin/workflow-builder`) similar to the existing tool builder

---

## Troubleshooting

### Common Issues

**Variables not resolving (showing `${var}` literally):**
- Check the `extract` rules match the actual field names from the tool
- Use CLI test to see what fields a tool returns: `python -c "from skills.stash import stash; print(stash('save', kind='text', text='test', name='test.txt'))"`
- Nested paths like `${article.url}` require the parent variable to be a dict

**Workflow completes instantly:**
- Check if a required step is failing silently
- Add `"required": true` to ensure failures abort the workflow
- Check logs for validation failures

**Tool cards show `{}`:**
- Ensure the tool returns data in `result.data`
- Check `extract` rules are capturing the right paths
- WebUI expects workflow results in `data.results[]` format

**URL not extracted from query:**
- `/archive bigsk1.com` extracts `https://bigsk1.com`
- Variables section needs `"url": {"from": "query", "extract": "url"}`
- URL extraction handles bare domains, adds `https://` automatically

### Testing Workflows

```bash
# Test workflow matching
python -c "
from orchestrator.workflow_loader import WorkflowLoader
loader = WorkflowLoader()
print(loader.match('/archive bigsk1.com'))
"

# Test full execution
source ~/jarvis-venv/bin/activate
./orchestrator/orchestrator_v2.py cloud "/archive https://example.com"

# Check extracted variables
python -c "
from orchestrator.pipeline_executor import PipelineExecutor
pe = PipelineExecutor.__new__(PipelineExecutor)
print(pe._extract_url_from_text('/archive bigsk1.com'))
"
```

---

## Implementation Files

| File | Purpose |
|------|---------|
| `orchestrator/workflow_loader.py` | Load/match workflow JSON files |
| `orchestrator/pipeline_executor.py` | Execute workflow steps |
| `orchestrator/orchestrator_v2.py` | Integration point (`_try_workflow()`) |
| `data/workflows/*.json` | Workflow definitions |
| `jarvis-web/server/routes/api.py` | `/api/workflows` endpoint |
| `jarvis-web/client/js/chat.js` | WebUI workflow autocomplete |
| `jarvis-web/server/sockets/chat.py` | WebSocket workflow result handling |

---

**Status**: Fully implemented and working. Add new workflows by creating JSON files in `data/workflows/`.
