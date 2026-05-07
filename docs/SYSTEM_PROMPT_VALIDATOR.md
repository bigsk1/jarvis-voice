# System Prompt Validator

A debugging and analysis tool for Jarvis's system prompt. Uses an LLM to review the complete prompt configuration and identify issues, contradictions, or ambiguities.

## Why This Tool Exists

When Jarvis behaves unexpectedly (wrong tool order, infinite loops, missing responses), the cause is often in the system prompt. This tool helps:

1. **Debug specific issues** - "Why did Jarvis call canvas before search?"
2. **Find contradictions** - Rules that conflict with each other
3. **Identify gaps** - Missing guidance for edge cases
4. **Validate changes** - Check if prompt edits introduced new problems

## Quick Start

```bash
# Basic validation
./bin/validate-system-prompt

# Include all tool definitions (recommended for thorough analysis)
./bin/validate-system-prompt --tools

# Debug a specific observed issue
./bin/validate-system-prompt --tools --issue "Jarvis called search 3 times then stopped without answering"
```

## Command Reference

### Basic Options

| Flag | Short | Description |
|------|-------|-------------|
| `--tools` | `-t` | Include all tool definitions in analysis |
| `--provider` | `-p` | LLM to use: `anthropic`, `xai`, `openai` (default: anthropic) |
| `--mode` | `-m` | Config mode: `cloud`, `local` (default: cloud) |
| `--dry-run` | `-d` | Show what LLM receives without making API call |
| `--no-log` | | Skip saving results to logs/ |

### Analysis Options

| Flag | Short | Description |
|------|-------|-------------|
| `--focus` | `-f` | Focus on specific area (e.g., "canvas", "memory", "research") |
| `--simulate` | `-s` | Simulate how a specific task would be interpreted |
| `--compare` | `-c` | Compare results to previous validation |
| `--issue` | `-i` | Debug a specific observed behavior |
| `--full-prompt` | | Save complete prompt in log (not truncated) |

## Usage Examples

### General Validation

Find all potential issues in the system prompt:

```bash
./bin/validate-system-prompt --tools --provider xai
```

Output categorizes findings by severity:
- **CRITICAL** - Will cause failures or wrong behavior
- **WARNING** - May cause suboptimal behavior  
- **INFO** - Minor improvements

### Debug Specific Behavior

When Jarvis does something weird, describe what happened:

```bash
./bin/validate-system-prompt --tools --issue "Jarvis used canvas first, then mcp brave search twice, then canvas again - only last canvas had data"
```

This triggers **root cause analysis** mode:
1. Most likely cause - which rule(s) triggered the behavior
2. Tool selection trace - why tools were called in that order
3. Contributing factors - other rules that added confusion
4. Recommended fix - specific diff to prevent it
5. Test case - scenario to verify the fix

### Focus on Specific Area

Narrow analysis to one subsystem:

```bash
./bin/validate-system-prompt --tools --focus "memory"
./bin/validate-system-prompt --tools --focus "canvas workflow"
./bin/validate-system-prompt --tools --focus "reminder handling"
```

### Simulate a Task

See how Jarvis would interpret a specific request:

```bash
./bin/validate-system-prompt --tools --simulate "research best cameras and save to canvas"
```

The LLM walks through:
1. What intent would be detected
2. Which tools would be considered
3. What order they'd be called
4. What could go wrong

### Compare to Previous

Check if issues from last validation are resolved:

```bash
./bin/validate-system-prompt --tools --compare
```

### Dry Run

See what the validator LLM receives without making an API call:

```bash
./bin/validate-system-prompt --tools --dry-run
```

## What Gets Analyzed

The validator sends the reviewing LLM:

1. **Full System Prompt** - The complete dynamic prompt including:
   - Stable base Jarvis prompt with all rules
   - Runtime context (current date/time)
   - Style notes (voice output rules)
   - Native search indicators (XAI/Anthropic search enabled)

2. **Tool Definitions** - All 40+ tools from ToolRegistry:
   - Skill tools (local Python scripts)
   - MCP tools (external servers)
   - Parameters and descriptions

3. **Ghost Tools** - Tools always available regardless of query

4. **Intelligence Context** - Example of learned insights injection

5. **Known Patterns** - Intentional designs that shouldn't be flagged:
   - Memory tool fallback (MAX 2 attempts)
   - Canvas update exception
   - stash vs canvas distinction
   - deep_memory_search purpose
   - Native search behavior
   - Ghost tools concept
   - Research workflow flexibility

## Log Files

Results are saved to `logs/validate-system-prompt/`:

```
logs/validate-system-prompt/
├── validation-20260124_142912.md
├── validation-20260124_145118.md
└── validation-20260124_145305.md
```

Each log contains:
- Metadata (mode, provider, focus, tools count)
- Issue being debugged (if `--issue` used)
- Full analysis result
- System prompt reference (truncated by default)
- Known patterns reference

## Workflow: Debugging an Issue

1. **Observe the problem** in Jarvis web UI or logs
2. **Describe it** clearly (what tools were called, what order, what was missing)
3. **Run validator** with `--issue` flag
4. **Review analysis** for root cause
5. **Apply fix** to `orchestrator/router_v2.py`
6. **Validate fix** with `--simulate` on a similar task
7. **Test in production**

Example workflow:

```bash
# Step 1: Debug the issue
./bin/validate-system-prompt --tools --provider xai \
  --issue "Jarvis called search_memory 3 times for 'Flask project' instead of trying semantic_recall"

# Step 2: After fixing, simulate similar task
./bin/validate-system-prompt --tools --simulate "what do you know about my Flask project"

# Step 3: Run general validation to check for side effects
./bin/validate-system-prompt --tools --compare
```

## Provider Comparison

Different LLMs may catch different issues:

```bash
# Run with multiple providers for thorough coverage
./bin/validate-system-prompt --tools --provider anthropic
./bin/validate-system-prompt --tools --provider xai
./bin/validate-system-prompt --tools --provider openai
```

| Provider | Strengths |
|----------|-----------|
| Anthropic | Precise rule analysis, good at finding contradictions |
| xAI | Fast, good at tool selection logic |
| OpenAI | Broad coverage, detailed suggestions |

## Common Issues Found

The validator typically catches:

1. **Contradictory rules** - "always do X" vs "never do X in case Y"
2. **Ambiguous tool selection** - Multiple tools could match
3. **Missing stop conditions** - Loops without exit criteria
4. **Workflow gaps** - "after tool A, do..." but no guidance for failures
5. **Outdated guidance** - Rules that don't match current tool capabilities

## Related Files

- `orchestrator/router_v2.py` - System prompt definition
- `lib/tool_registry.py` - Tool loading and definitions
- `config/cloud.env` - Ghost tools configuration
- `logs/validate-system-prompt/` - Validation history
