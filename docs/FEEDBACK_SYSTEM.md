# Jarvis Feedback System - LLM-as-QA

> **Purpose**: Allow Jarvis to critique its own experience after completing tasks, identifying issues with system prompts, tool descriptions, and suggesting improvements.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [Usage Methods](#usage-methods)
4. [Commands Reference](#commands-reference)
5. [What the LLM Sees](#what-the-llm-sees)
6. [Output Format](#output-format)
7. [Log Files](#log-files)
8. [Use Cases](#use-cases)
9. [Configuration](#configuration)

---

## Overview

The Feedback System is a **self-improvement mechanism** where the LLM acts as a QA analyst reviewing its own performance. After completing a task, it's asked to:

1. **Rate** the experience (1-5)
2. **Identify issues** with system prompt, tool descriptions, or missing info
3. **Suggest improvements** for next time

This creates a feedback loop for continuous improvement without manual debugging.

### Why This Matters

- **The LLM has full context** - It sees everything you give it (system prompt, tools, instructions)
- **Catches issues humans miss** - Like the truncated insight we found ("co" cutoff)
- **Self-documenting** - Issues are logged with timestamps for later review
- **Actionable feedback** - Specific suggestions, not vague complaints

---

## How It Works

### Flow Diagram

```
┌─────────────────┐
│  User Query     │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Orchestrator   │  ← Normal task processing
│  (process)      │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Task Result    │  ← speech, ok, tools_used, etc.
└────────┬────────┘
         ▼
┌─────────────────────────────────────────┐
│  FeedbackCollector.collect()            │
│                                         │
│  1. Build feedback prompt with:         │
│     - Original query                    │
│     - Task result (success/failure)     │
│     - Tools used                        │
│     - Summary of what was available     │
│                                         │
│  2. Ask LLM: "Rate and critique this"   │
│                                         │
│  3. Parse JSON response                 │
│                                         │
│  4. Log to feedback-YYYY-MM-DD.jsonl    │
│     (only if rating < 5 or always_log)  │
└─────────────────────────────────────────┘
```

### Key Points

1. **Separate LLM Call**: Feedback collection is a NEW LLM call after the task completes
2. **FULL System Prompt**: The feedback LLM sees the actual system prompt text
3. **Tool Descriptions**: Includes descriptions for used tools AND likely relevant tools
4. **Separate Provider**: Can use a DIFFERENT LLM for feedback (avoid self-grading bias)
5. **Logs stored separately**: In `logs/feedback/`, not mixed with other logs

---

## Usage Methods

### Method 1: `--feedback` Flag (Quick Debugging)

Add `--feedback` to any orchestrator command:

```bash
# Basic usage
./orchestrator/orchestrator_v2.py cloud "What time is it?" --feedback

# With other flags
./orchestrator/orchestrator_v2.py cloud "Search memory" --feedback --json
./orchestrator/orchestrator_v2.py cloud "Complex task" --feedback --debug-thinking
```

**When to use**: 
- Debugging a specific query
- Spot-checking after changes
- One-off testing

### Method 2: `bin/jarvis-feedback` (Dedicated Tool)

Standalone tool with multiple commands:

```bash
./bin/jarvis-feedback run "Query here"      # Single query with feedback
./bin/jarvis-feedback batch file.txt        # Batch testing
./bin/jarvis-feedback summary               # Summarize recent feedback
./bin/jarvis-feedback recent                # Show recent feedback entries
./bin/jarvis-feedback issues                # Show only issues (rating < 5)
```

**When to use**:
- Batch testing multiple queries
- Reviewing historical feedback
- Analyzing patterns in issues

---

## Commands Reference

### `--feedback` Flag

| Flag | Description |
|------|-------------|
| `--feedback` | Collect LLM feedback after task completion |

Example:
```bash
./orchestrator/orchestrator_v2.py cloud "What's the weather?" --feedback
```

### `bin/jarvis-feedback` Commands

#### `run` - Single Query

```bash
./bin/jarvis-feedback run "Your query here" [--mode cloud|local]
```

Runs a single query through the orchestrator and collects feedback.

#### `batch` - Batch Testing

```bash
./bin/jarvis-feedback batch queries.txt [--mode cloud|local]
```

Runs multiple queries from a file (one per line, `#` for comments).

Example file (`tests/feedback-queries.txt`):
```
# Memory tests
Search my memory for flask
What do you remember about my server?

# Tool tests
What time is it?
What's the Bitcoin price?
```

#### `summary` - Feedback Summary

```bash
./bin/jarvis-feedback summary [--days 7] [--mode cloud|local]
```

Shows aggregated statistics from feedback logs:
- Total feedback entries
- Average rating
- Issues grouped by category
- Low-rated tasks

**`--days` explained**: Looks back N days in the `logs/feedback/` directory. It reads `feedback-YYYY-MM-DD.jsonl` files from the past N days and aggregates them.

#### `recent` - Recent Feedback

```bash
./bin/jarvis-feedback recent [--days 7] [--mode cloud|local]
```

Shows individual feedback entries from recent days.

#### `issues` - Issues Only

```bash
./bin/jarvis-feedback issues [--days 7] [--mode cloud|local]
```

Shows only feedback with rating < 5 (tasks that had problems).

---

## What the LLM Sees

During feedback collection, the LLM receives **FULL CONTEXT** to enable specific, actionable feedback:

### Provided Information

| Info | Source | Purpose |
|------|--------|---------|
| Original query | User input | What was asked |
| Success/failure | Task result | Did it work |
| Response text | Task result | What was returned |
| Tools used | Task result | What tools ran |
| **FULL System Prompt** | Router | Critique rules, constraints, instructions |
| **Tool Descriptions** | Registry | For tools used + likely relevant tools |
| **Intelligence Insights** | Context | Learned strategies, known failures |
| **Config Context** | Config | Auto-context, response style, mode |

### Why Full Context Matters

The LLM needs to SEE the actual text to provide specific feedback like:
- "The system prompt says X but this conflicts with Y"
- "Tool description for `get_time` says 'returns current time' but doesn't mention timezone"
- "Intelligence insight #24 was misleading because..."

### Tool Description Detection

The system automatically includes descriptions for:
1. Tools that were actually used
2. Tools that SHOULD have been used (based on query keywords)

For example, a query with "time" will include the `get_time` description even if it wasn't used, so the LLM can say "This tool should have been used because..."

### The Feedback Prompt

```
You just completed a task as a voice assistant. Now provide HONEST FEEDBACK...

=== YOUR TASK WAS ===
User Query: What time is it?

=== RESULT ===
Success: Yes
Response: It's 2:15 PM on Sunday
Tools Used: get_time

=== WHAT YOU WERE GIVEN ===
System Prompt Summary:
- Memory-first rules requiring semantic_recall before external tools
- 25-word voice output limit
- Tool descriptions for 50 tools
- Intelligence insights (learned patterns, known failures)
- Auto-context with recent conversation history

Tools Available: 50
Intelligence Insights: Enabled
Auto-Context: Enabled (window=3, minutes=10)
Response Style: auto

=== PROVIDE FEEDBACK ===
Rate your experience (1-5)...
```

---

## Output Format

### JSON Structure

```json
{
    "rating": 4,
    "summary": "Task completed but tool description could be clearer",
    "issues": [
        {
            "category": "tool_description",
            "description": "get_time description doesn't mention timezone handling",
            "suggestion": "Add 'Returns time in user's local timezone' to description"
        }
    ],
    "positive": "Memory-first rule correctly skipped for time query",
    "timestamp": "2025-11-30T09:45:00.000000",
    "session_id": "20251130_094500",
    "query": "What time is it?",
    "result_ok": true,
    "result_speech": "It's 2:15 PM on Sunday",
    "tools_used": ["get_time"],
    "mode": "cloud"
}
```

### Issue Categories

| Category | Description |
|----------|-------------|
| `system_prompt` | Issues with instructions, rules, constraints |
| `tool_description` | Tool descriptions don't match behavior |
| `intelligence_insights` | Issues with learned strategies or known failures |
| `config` | Configuration issues (auto-context, response style) |
| `missing_info` | Information that would have helped |
| `other` | Anything else |

### Issue Structure

Each issue now includes:
```json
{
    "category": "tool_description",
    "description": "What's wrong",
    "current_text": "The actual text that's problematic (quoted)",
    "suggestion": "How to fix it with specific improved text"
}
```

This allows you to see exactly WHAT text needs changing and HOW to change it.

### Rating Scale

| Rating | Meaning |
|--------|---------|
| 5 | Perfect - no issues |
| 4 | Minor improvements possible |
| 3 | Some issues but workable |
| 2 | Significant issues |
| 1 | Major problems |

---

## Log Files

### Location

```
logs/feedback/
├── feedback-2025-11-30.jsonl
├── feedback-2025-11-29.jsonl
└── ...
```

### Format

One JSON object per line (JSONL):
```jsonl
{"rating": 5, "summary": "No issues", "timestamp": "...", ...}
{"rating": 3, "summary": "Tool description misleading", "issues": [...], ...}
```

### When Logs Are Written

- **Default**: Only when rating < 5 (has issues)
- **Always log**: Set `JARVIS_FEEDBACK_ALWAYS_LOG=1` environment variable

---

## Use Cases

### 1. After Making Changes

```bash
# Test that your changes didn't break anything
./bin/jarvis-feedback batch tests/feedback-queries.txt
```

### 2. Debugging Specific Issues

```bash
# Something seems off with memory search
./orchestrator/orchestrator_v2.py cloud "Search my memory for flask" --feedback
```

### 3. Weekly Review

```bash
# What issues came up this week?
./bin/jarvis-feedback issues --days 7
./bin/jarvis-feedback summary --days 7
```

### 4. Tool Description QA

Run queries that use each tool and check if descriptions are accurate:
```bash
./bin/jarvis-feedback run "What's the Bitcoin price?"
# → Feedback might say: "Description says 'current price' but also returns 24h change"
```

### 5. System Prompt Validation

Ask meta-questions:
```bash
./bin/jarvis-feedback run "What tools do you have available?"
# → Feedback might say: "20-word limit too restrictive for this question"
```

---

## Configuration

### Dedicated Feedback Provider (Recommended)

**Problem**: Using the same LLM to grade itself creates bias - it won't catch its own mistakes.

**Solution**: Use a DIFFERENT LLM for feedback analysis.

```bash
# In config/cloud.env or config/local.env

# Use Claude to grade xAI's work
FEEDBACK_PROVIDER=anthropic
FEEDBACK_MODEL=claude-sonnet-4-5-20250929

# Or use GPT-4o to grade anyone's work
FEEDBACK_PROVIDER=openai
FEEDBACK_MODEL=gpt-4o

# Or use a larger Ollama model to grade a smaller one
FEEDBACK_PROVIDER=ollama
FEEDBACK_MODEL=qwen3:32b
```

### Recommended Setups

| Task Provider | Feedback Provider | Why |
|---------------|-------------------|-----|
| xAI (cheap, fast) | Anthropic Claude | Claude's analysis is thorough |
| Ollama (local) | Anthropic or OpenAI | Cloud model catches local model mistakes |
| Anthropic | OpenAI | Different training, different blind spots |
| OpenAI | Anthropic | Same logic |

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FEEDBACK_PROVIDER` | LLM provider for feedback | Same as task |
| `FEEDBACK_MODEL` | Model for feedback | Provider's default |
| `JARVIS_FEEDBACK_ALWAYS_LOG` | Log even if rating = 5 | Not set (false) |

### Supported Providers

- `anthropic` - Claude models (claude-sonnet-4-5-20250929, etc.)
- `openai` - GPT models (gpt-4o, gpt-4-turbo, etc.)
- `xai` - Grok models (grok-4-1-fast-non-reasoning-latest, etc.)
- `ollama` - Local models (qwen3:14b, llama3:70b, etc.)

### From Dashboard

The Jarvis Dashboard (Testing tab) includes:
- **Feedback Summary** - `./bin/jarvis-feedback summary --days 7`
- **Feedback Issues** - `./bin/jarvis-feedback issues --days 7`
- **Feedback Test** - `./bin/jarvis-feedback run "What time is it?"`

---

## Example Session

```bash
$ ./orchestrator/orchestrator_v2.py cloud "What's the current price of Bitcoin?" --feedback

🎯 Processing: 'What's the current price of Bitcoin?'
📡 Mode: cloud
🤖 Model: grok-4-1-fast-reasoning-latest
============================================================

... normal task output ...

============================================================
🔍 COLLECTING FEEDBACK (LLM-as-QA Mode)
============================================================

📊 Feedback Rating: 5/5
📝 Summary: Task completed efficiently - crypto_price tool worked as expected

✅ What Worked: Intelligence insights correctly suggested crypto_price as preferred tool

📁 Feedback logged to: logs/feedback/feedback-2025-11-30.jsonl
```

---

## Future Enhancements

1. **Aggregate analysis** - Pattern detection across many feedback entries
2. **Auto-fix suggestions** - Generate patches for tool descriptions
3. **Integration with intelligence layer** - Feed insights back into learning
4. **Slack/Discord alerts** - Notify on low ratings

---

## Related Documentation

- [Intelligence Layer](./INTELLIGENCE_LAYER.md) - Learning from success/failure patterns
- [Tool Calling System](./TOOL_CALLING_SYSTEM.md) - How tools work
- [Memory System](./MEMORY_SYSTEM.md) - Memory-first rules

