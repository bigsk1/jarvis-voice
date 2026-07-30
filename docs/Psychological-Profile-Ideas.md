# Phase 2: Psychological Profile & Behavioral Intelligence

> **Status**: Future Feature (Documented for Implementation)  
> **Last Updated**: Nov 27, 2025  
> **Priority**: Medium (after core intelligence layer stabilizes)

---

## Overview

We've successfully moved from a "Tool Logger" to a **Procedural Memory System**. By separating Facts (Memory DB) from Skills (Intelligence DB), we have solved the context pollution problem that plagues most RAG agents.

**Current State (Phase 1)**: Intelligence layer asks *"What is the best **function** to call?"*  
**Next Evolution (Phase 2)**: Intelligence layer asks *"What is the best **way to behave** for this user?"*

This document outlines the strategic roadmap to bridge the gap from "Smart Tool User" to "Fully Aware Assistant."

---

## Implementation Considerations

### Complexity Factors
- **OpenCode ↔ Jarvis**: Always verbose (2 LLMs talking to each other)
- **CLI mode**: Typically lengthy responses
- **Voice/Speech mode**: Needs concise responses
- **Current `JARVIS_RESPONSE_STYLE`**: Set to `auto` - already handles some of this

### Where to Store User Model
**Recommended**: `jarvis_memory.db` (not intelligence.db)
- User preferences are **facts about the user** (like memories)
- Intelligence.db is for **procedural knowledge** (how to do things)
- Keeps separation of concerns clean

### Current Intel Discovery Pattern
Jarvis currently uses a 2-step pattern for user intel:
1. **Semantic search** → Finds snippet in memory with file location
2. **Read file directly** → Gets full context from `jarvis-intel/` directory

This works but could be improved with auto-loading critical user preferences.

---

### 1. The Dynamic User Model (Beyond `jarvis-intel`)

You mentioned `jarvis-intel` (vector search). That is **Passive Memory**. It requires the user to manually write a file or the agent to "search" for it.
You need **Active State Tracking**. This is a persistent "Psychological Profile" that loads into *every* context window, not just when searched.

**The Fix:** Create a `user_model` table in your SQLite DB.
Instead of vectors, use **Scalars (0.0 - 1.0)** for global traits.

**Schema:**
```sql
CREATE TABLE user_model (
    trait_key TEXT PRIMARY KEY, -- e.g., 'verbosity', 'technical_depth', 'humor'
    value REAL,                 -- 0.0 to 1.0
    confidence REAL,            -- How sure are we?
    last_updated DATETIME
);
```

**How it works:**
1.  **Initialize:** `verbosity: 0.5`, `technical_depth: 0.5`.
2.  **Observe:** User says "Just give me the code, no yapping."
3.  **Update:** Reflection layer detects this and updates `verbosity` to `0.2`.
4.  **Inject:** Every system prompt gets a header:
    > *User Profile: Prefers concise responses (Level 2/10). High technical proficiency (Level 8/10).*

**Why this is "Awareness":** The agent adapts its *personality* instantly, without needing to perform a semantic search for "user preferences."

### 2. Q&A Intelligence (Non-Tool Reflection)

Your current logic triggers reflection on `tools_used`. You need to trigger reflection on **Conversation Flow**.

**The Fix:** Detect "Correction Patterns" in Q&A.
If the user's *next* message contains phrases like:
*   "No, I meant..."
*   "You forgot..."
*   "Too long."
*   "Rewrite this."

**Action:**
1.  Flag the *previous* response as a "Style Failure."
2.  The Reflection Prompt changes from "Did the tool work?" to **"Why did the user correct me?"**
3.  **Learned Insight:** *"When user asks about 'React Components', do not explain what React is. Just show the code."*
4.  Store this as a **Negative Constraint** for *Content Generation* rather than Tool Selection.

### 3. "Dreaming" (Offline Sandbox Simulation)

You asked about a "sandboxed environment to run scenarios." This is the holy grail of self-improvement.

**The Concept:**
When Jarvis is idle (e.g., 3 AM), it should process the `failed_interactions` queue.

**The Workflow (The "Dream"):**
1.  **Pick a Failure:** Select a query where the user said "That didn't work" or an error occurred.
2.  **Sandbox:** Spin up a restricted context (or Docker container for OpenCode).
3.  **Simulate:** The LLM acts as both **User** and **Agent**.
    *   *Simulated User:* Re-asks the question.
    *   *Agent:* Tries a **different** tool path or parameter set.
4.  **Verify:** Did the new path succeed?
5.  **Synthesize:** If yes, write a **Synthetic Insight** to the Intelligence DB.
    > *"I learned this while dreaming: For 'Deploy to Vercel', use the CLI tool, not the API."*

### 4. Semantic Intent Classification (The "Gut Feeling")

Before routing to tools, the intelligence layer should classify the **User's State of Mind**.

**Implementation:**
Add a lightweight classification step (or use a small local model like `qwen3.5:latest`) before the main router.

**Output:**
```json
{
  "urgency": "high",
  "emotional_state": "frustrated",
  "task_type": "exploratory" // vs "execution"
}
```

**How this changes behavior:**
*   If `urgency: high`, skip "Thinking Mode" and ghost tools.
*   If `emotional_state: frustrated`, apologize before answering and lower `verbosity`.
*   If `task_type: execution`, do not offer advice, just run the command.

### 5. Implementation Plan: Phase 2

Here is how to modify your `INTELLIGENCE_LAYER.md` and code to support this.

#### A. Modify `lib/intelligence.py` (Schema Update)
Add support for "Style Constraints" separate from "Tool Constraints."

```python
# In your reflection logic
def categorize_insight(text):
    if "use tool" in text or "call function" in text:
        return "tool_routing"
    elif "speak" in text or "explain" in text or "tone" in text:
        return "communication_style" # <--- NEW
    else:
        return "general_knowledge"
```

#### B. The "Dreaming" Script (`bin/dream_cycle.py`)
Create a script that runs via cron at night.

```python
# Pseudocode for Dream Cycle
def dream():
    failures = db.query("SELECT * FROM experiences WHERE success = 0 AND dreamt_about = 0")
    for fail in failures:
        print(f"Dreaming about correction for: {fail.query}")
        
        # Ask LLM to propose 3 alternative strategies
        alternatives = llm.generate_alternatives(fail.query, fail.tools_used)
        
        # Test strategies (Dry run or harmless tools only)
        best_strat = evaluate_strategies(alternatives)
        
        if best_strat:
            db.insert_insight(best_strat)
            print("I taught myself a new strategy overnight.")
```

#### C. User Model Injection
In `orchestrator/orchestrator_v2.py`, inside `_construct_system_prompt`:

```python
# Load active user state
user_state = self.db.get_user_model() 
# e.g., {'verbosity': 0.2, 'expert_mode': True}

style_instructions = ""
if user_state['verbosity'] < 0.3:
    style_instructions += "Response Style: Extremely concise. No fluff.\n"
if user_state['expert_mode']:
    style_instructions += "Technical Level: Expert. Do not explain basic concepts.\n"

system_prompt = f"{base_prompt}\n\n{style_instructions}"
```

### Summary of the Upgrade

| Feature | Current Phase 1 | Proposed Phase 2 |
| :--- | :--- | :--- |
| **Scope** | Tool Routing | Total Behavior (Routing + Style + Persona) |
| **User Profile** | Static Files (`jarvis-intel`) | Dynamic State (`user_model` DB) |
| **Correction** | Failed Tool Execution | Failed Conversation (Rewords/Corrections) |
| **Learning** | Reactive (After query) | Proactive ("Dreaming" / Simulation) |
| **Feedback** | Implicit (Crash) | Explicit (Urgency/Emotion detection) |

This moves you from a **"Tool-Use Agent"** to a **"Personal Companion."** The "Awareness" comes from the fact that it remembers *how you like to be treated*, not just *what commands to run*.

---

## Practical Implementation Phases

### Phase 2A: User Model Table (Future - Low Complexity)

**Location**: `jarvis_memory.db`

```sql
CREATE TABLE user_model (
    trait_key TEXT PRIMARY KEY,
    value REAL DEFAULT 0.5,        -- 0.0 to 1.0
    confidence REAL DEFAULT 0.5,   -- How sure are we?
    evidence_count INTEGER DEFAULT 0,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Initial traits
INSERT INTO user_model (trait_key, value) VALUES
    ('verbosity', 0.5),            -- 0=concise, 1=detailed
    ('technical_depth', 0.7),      -- 0=beginner, 1=expert
    ('humor', 0.5),                -- 0=serious, 1=playful
    ('patience', 0.5),             -- 0=wants quick answers, 1=okay with exploration
    ('prefers_code_first', 0.5),   -- 0=explain first, 1=show code first
    ('formality', 0.3);            -- 0=casual, 1=formal
```

**Injection point** (orchestrator system prompt):
```python
def _get_user_style_header(self):
    traits = self.memory_db.get_user_model()
    
    header = "## User Preferences (Auto-learned)\n"
    if traits['verbosity'] < 0.3:
        header += "- Be EXTREMELY concise. No fluff.\n"
    elif traits['verbosity'] > 0.7:
        header += "- User appreciates detailed explanations.\n"
    
    if traits['technical_depth'] > 0.7:
        header += "- Expert user. Skip basic explanations.\n"
    
    if traits['prefers_code_first'] > 0.6:
        header += "- Show code first, explain after.\n"
    
    return header
```

**Challenge**: Must respect existing `JARVIS_RESPONSE_STYLE` setting and mode (voice vs CLI).

### Phase 2B: Style Reflection (Future - Medium Complexity)

Detect correction patterns in conversation flow:
- "No, I meant..." → Misunderstanding
- "Too long" / "TL;DR" → Lower verbosity  
- "You forgot..." → Incompleteness
- User immediately re-asks differently → Failure signal

**New constraint type**: `style` (vs current `positive`/`negative` for tools)

```python
# In reflection logic
def categorize_insight(reflection_output):
    if reflection_output.get('insight_type') in ['tool_preference', 'tool_avoidance']:
        return 'tool_routing'
    elif reflection_output.get('insight_type') in ['verbosity', 'tone', 'format']:
        return 'communication_style'
    else:
        return 'general_knowledge'
```

### Phase 2C: "Dreaming" / Offline Learning (Future - High Complexity)

**Start simple** with manual review:
```python
# bin/review-failures.py
def review_failures():
    failures = db.query("""
        SELECT * FROM experiences 
        WHERE outcome_success = 0 AND reviewed = 0
        LIMIT 5
    """)
    
    for fail in failures:
        analysis = llm.analyze(f"""
        This interaction failed. Query: {fail.query}
        Tools tried: {fail.tools_used}
        What could have worked better?
        """)
        
        print(f"Proposed insight: {analysis}")
        if input("Accept? (y/n)") == 'y':
            db.insert_insight(analysis)
```

**Full automation later** - requires sandboxed execution and validation.

### Phase 2D: Better Intel Auto-Discovery (Near-term Priority)

Current pattern works but could be improved:
```
Query: "What's my preferred tech stack?"
   ↓
1. semantic_recall → finds "user-profile.md" mention
   ↓
2. manage_intel/read_file → reads full file
```

**Improvement ideas**:
- Auto-load critical user profile data on startup
- Cache frequently-accessed intel in session context
- Detect when intel is outdated vs memory

---

## Summary: Evolution Roadmap

| Phase | Feature | Complexity | Priority | Status |
|-------|---------|------------|----------|--------|
| 1 ✅ | Tool Intelligence | High | Critical | **DONE** |
| 2A | User Model Table | Low | Medium | Future |
| 2B | Style Reflection | Medium | Medium | Future |
| 2C | Dreaming/Simulation | High | Low | Future |
| 2D | Better Intel Discovery | Low | High | **Next** |

---

## Key Insight

The goal is not just to know *what tools to use*, but to understand *how the user wants to interact*:

- **Facts** → Memory DB (what the user said, project locations, preferences)
- **Skills** → Intelligence DB (how to route, what tools work for what)
- **Personality** → User Model (how to communicate, tone, verbosity)

This three-layer system creates true "awareness" - the assistant adapts not just its actions, but its entire communication style to match the user.

---

## Related Documentation

- `docs/INTELLIGENCE_LAYER.md` - Current intelligence implementation
- `docs/JARVIS_INTEL_SYSTEM.md` - Intel file management
- `docs/MEMORY_SYSTEM.md` - Memory database architecture
- `config/cloud.env` - `JARVIS_RESPONSE_STYLE` setting
