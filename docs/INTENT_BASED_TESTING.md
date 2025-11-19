# Intent-Based Testing Strategy

> **Philosophy**: Test like a human would speak, not like a keyword matcher would parse.

---

## Table of Contents

1. [The Problem with Current Testing](#the-problem-with-current-testing)
2. [Intent-Based Testing Approach](#intent-based-testing-approach)
3. [Natural Language Test Cases](#natural-language-test-cases)
4. [Temperature Settings Strategy](#temperature-settings-strategy)
5. [Test Suite Structure](#test-suite-structure)
6. [Regression Detection](#regression-detection)
7. [Implementation](#implementation)

---

## The Problem with Current Testing

### Current Test Pattern (Keyword Matching)

```bash
# Purpose-built queries that match tool descriptions exactly
./orchestrator_v2.py cloud "List my reminders"        # ✅ Works
./orchestrator_v2.py cloud "What time is it?"         # ✅ Works
./orchestrator_v2.py cloud "Get recent conversations" # ✅ Works
```

**Why This Fails:**
- These are **not natural human speech**
- They're optimized to match tool descriptions
- Real users say: "What was my last question?" not "Get recent conversations"
- Regressions like the conversation tool bug go undetected

---

### Real-World User Queries (Intent-Based)

```bash
# How humans actually talk
"What was the last thing I asked you?"           # Should → get_recent_conversations
"When is my next reminder?"                      # Should → list_reminders
"Did I miss any reminders?"                      # Should → list_reminders
"What's broken?"                                 # Should → list_alerts
"Show me what we talked about earlier"           # Should → get_recent_conversations
"Remind me in an hour to check the mail"         # Should → create_reminder
```

**These test INTENT, not KEYWORDS.**

---

## Intent-Based Testing Approach

### Principle: Test Multiple Phrasings for Same Intent

For each tool, create 5-10 natural variations:

```python
# Testing list_reminders tool
test_cases = [
    # Formal (keyword match)
    "List my reminders",
    "Show reminders",
    
    # Natural variations (intent match)
    "What reminders do I have?",
    "When is my next reminder?",
    "Do I have any reminders?",
    "Did I set any reminders?",
    "What's on my reminder list?",
    "Any upcoming reminders?",
    "What am I supposed to remember?",
    
    # Temporal queries
    "What was I supposed to do?",
    "What's coming up?",
]

expected_tool = "list_reminders"
```

### Principle: Test Edge Cases and Ambiguity

```python
# Ambiguous queries that humans understand
ambiguous_tests = [
    {
        "query": "What's the status?",
        "acceptable_tools": ["list_alerts", "query_service_logs"],
        "context": "User recently set up Docker monitoring → prefer list_alerts"
    },
    {
        "query": "What did I just do?",
        "acceptable_tools": ["get_recent_conversations", "search_conversations"],
        "prefer": "get_recent_conversations",  # Temporal, not topic search
    }
]
```

---

## Natural Language Test Cases

### Category 1: Conversation History (The Regression We Just Fixed)

**Intent**: User wants to see recent conversation history

```python
conversation_temporal_tests = {
    "expected_tool": "get_recent_conversations",
    "queries": [
        # Formal
        "Show recent conversations",
        "Get conversation history",
        
        # Natural (these should ALL work)
        "What was my last question?",
        "What did I just ask?",
        "What was the last thing I said?",
        "What did we just talk about?",
        "What was our last conversation?",
        "Show me what I asked earlier",
        "What was my previous request?",
        "Remind me what I just asked about",
        
        # Edge cases
        "What was that thing I just asked?",
        "Go back - what did I say?",
    ]
}

conversation_topic_tests = {
    "expected_tool": "search_conversations",
    "queries": [
        # Topic search (requires query parameter)
        "Did I ask about Bitcoin?",
        "When did I mention Flask?",
        "Show conversations about reminders",
        "Find where I talked about webhooks",
        "Have I asked about crypto before?",
        
        # Should NOT use get_recent_conversations
        # (These need topic filtering, not just chronological)
    ]
}
```

**Test Validation**:
```python
# This would have caught the regression!
def test_conversation_temporal():
    query = "What was my last question?"
    result = orchestrator.route_query(query)
    
    # Assert correct tool
    assert result.tool == "get_recent_conversations", \
        f"Expected get_recent_conversations, got {result.tool}"
    
    # Assert no required parameters (should work without query param)
    assert "query" not in result.tool_args or result.tool_args["query"] is None, \
        "get_recent_conversations should not require query parameter"
```

---

### Category 2: Reminders (Temporal State)

**Intent**: User wants to know about current/upcoming reminders

```python
reminder_tests = {
    "expected_tool": "list_reminders",
    "queries": [
        # Formal
        "List reminders",
        "Show reminders",
        
        # Natural variations
        "When is my next reminder?",           # ← We just fixed this!
        "What reminders do I have?",
        "Do I have any reminders?",
        "Did I set any reminders?",
        "Any upcoming reminders?",
        "What's on my reminder list?",
        "Did I miss any reminders?",
        "What am I supposed to remember?",
        "What's coming up?",
        "What did I tell you to remind me about?",
        
        # Temporal edge cases
        "When is the next thing I need to do?",
        "What's next on my list?",
        "Any pending reminders?",
    ]
}

# Anti-patterns (should NOT use list_reminders)
reminder_anti_tests = {
    "should_NOT_use": "list_reminders",
    "queries": [
        "Did I mention reminders before?",      # → search_conversations
        "What's a reminder?",                   # → Q&A (no tool)
        "How do reminders work?",               # → Q&A (no tool)
    ]
}
```

---

### Category 3: Alerts (System State)

**Intent**: User wants to know about pending alerts/issues

```python
alert_tests = {
    "expected_tool": "list_alerts",
    "queries": [
        # Formal
        "List alerts",
        "Show alerts",
        
        # Natural variations
        "Any alerts?",
        "What alerts do I have?",
        "What's broken?",                      # ← Human-speak!
        "Is anything down?",
        "Any problems?",
        "What's wrong?",
        "Any issues?",
        "What needs attention?",
        "Any notifications?",
        "What's happening?",                   # ← Ambiguous but often alerts
        
        # Urgent/casual
        "Everything okay?",
        "Status?",
        "What's up?",                          # ← Very casual, context-dependent
    ]
}
```

---

### Category 4: Time Queries (Simple, Fast Path)

**Intent**: User wants current time

```python
time_tests = {
    "expected_tool": "get_time",
    "queries": [
        # Formal
        "What time is it?",
        "Get time",
        
        # Natural variations
        "What's the time?",
        "Time?",
        "What time is it right now?",
        "Tell me the time",
        "Current time?",
        
        # With context
        "What day is it?",
        "What's today's date?",
        "What's the date?",
    ],
    "fast_path_candidate": True,  # Should skip thinking, direct execute
}
```

---

### Category 5: Crypto Prices (Fast Path)

**Intent**: User wants cryptocurrency price

```python
crypto_tests = {
    "expected_tool": "crypto_price",
    "queries": [
        # Formal
        "Bitcoin price",
        "Get crypto price bitcoin",
        
        # Natural variations
        "How much is Bitcoin?",
        "What's Bitcoin at?",
        "Bitcoin?",                           # ← Single word
        "BTC price",
        "What's BTC trading at?",
        "How much is a Bitcoin worth?",
        "Bitcoin value",
        
        # Multiple coins
        "Ethereum price",
        "How much is ETH?",
    ],
    "fast_path_candidate": True,
}
```

---

### Category 6: Bash Commands (Dangerous)

**Intent**: User wants to execute system command

```python
bash_tests = {
    "expected_tool": "execute_bash",
    "queries": [
        # Direct commands
        "Run ls -la",
        "Execute uptime",
        
        # Natural variations
        "Check disk space",                   # → Should infer "df -h"
        "Show running processes",             # → Should infer "ps aux"
        "What's the system uptime?",          # → Should infer "uptime"
        
        # Ambiguous (may need clarification)
        "Restart the server",                 # ⚠️ Dangerous - needs confirmation
        "Kill that process",                  # ⚠️ Needs PID or name
    ],
    "requires_confirmation": True,
}
```

---

### Category 7: Memory Queries (Keyword vs Semantic)

**Intent**: User wants to recall stored information

```python
memory_keyword_tests = {
    "expected_tool": "search_memory",
    "queries": [
        # 1-3 words (keyword search is faster)
        "Flask",
        "Webhook URL",
        "Tetris location",
        "Pizza place",
        "Doctor appointment",
    ]
}

memory_semantic_tests = {
    "expected_tool": "semantic_recall",
    "queries": [
        # Natural language questions (4+ words)
        "Where is my Flask application?",
        "What's my favorite pizza place?",
        "When is my doctor appointment?",
        "Who is my dentist?",
        "What time does the gym close?",
        
        # Should use AI understanding, not keyword match
        "Where did I deploy that web app?",   # "deploy" → might mean project location
        "What's that Italian restaurant I like?",  # "Italian restaurant" → pizza place
    ]
}
```

---

### Category 8: Complex Multi-Turn

**Intent**: User wants multiple operations in sequence

```python
multi_turn_tests = {
    "expected_sequence": ["opencode", "api_call", "create_reminder"],
    "queries": [
        "Build a Flask API, test it, and remind me to deploy tomorrow",
        "Create a website and set a reminder to check it in an hour",
        "Start the tetris server and remind me to check it in 10 minutes",
    ],
    "requires_thinking": True,
    "complexity": "high"
}
```

---

## Temperature Settings Strategy

### The Temperature Problem

**Issue**: Using the same temperature for all LLM tasks leads to:
- Tool selection being too creative (hallucinates tools)
- Q&A responses being too rigid (sounds robotic)
- Thinking steps lacking depth (doesn't explore alternatives)

**Solution**: **Dynamic temperature** based on task type.

---

### Temperature Recommendations

| Task Type | Temperature | Rationale | Example |
|-----------|-------------|-----------|---------|
| **Tool Selection** | 0.0 - 0.2 | Needs to be EXACT. No hallucination. Pick from available tools only. | Routing user query to tool |
| **Tool Arguments** | 0.1 - 0.3 | Slightly more flexible for natural language → structured args | Parsing "in one hour" → datetime |
| **Thinking Step** | 0.5 - 0.7 | Needs creativity to explore alternatives and reasoning | "Why did this fail? What else could work?" |
| **Q&A Response** | 0.3 - 0.5 | Balanced: accurate but conversational | Final response to user |
| **Creative Tasks** | 0.7 - 0.9 | High creativity for content generation | Writing emails, stories, code comments |

---

### Implementation in Code

```python
class DynamicTemperatureLLM:
    """LLM provider with task-specific temperature settings."""
    
    TEMPERATURES = {
        'tool_selection': 0.1,      # Strict
        'tool_arguments': 0.2,      # Slightly flexible
        'thinking': 0.6,            # Creative reasoning
        'qa_response': 0.4,         # Conversational
        'creative': 0.8,            # High creativity
    }
    
    def route_query(self, query: str, task_type: str = 'tool_selection'):
        """Route query with task-specific temperature."""
        temp = self.TEMPERATURES.get(task_type, 0.3)
        
        return self.llm_provider.complete(
            prompt=query,
            temperature=temp,
            max_tokens=500
        )
    
    def think(self, query: str, context: str):
        """Thinking step with higher temperature for exploration."""
        temp = self.TEMPERATURES['thinking']
        
        prompt = f"""
        Think carefully about this problem:
        {query}
        
        Context:
        {context}
        
        Explore multiple possibilities and reason through them.
        """
        
        return self.llm_provider.complete(
            prompt=prompt,
            temperature=temp,  # 0.6 - allows exploration
            max_tokens=1000
        )
    
    def generate_response(self, result: dict):
        """Generate user-facing response with conversational temperature."""
        temp = self.TEMPERATURES['qa_response']
        
        return self.llm_provider.complete(
            prompt=f"Summarize this result conversationally: {result}",
            temperature=temp,  # 0.4 - friendly but accurate
            max_tokens=200
        )
```

---

### Temperature Tuning Examples

#### Example 1: Tool Selection (Low Temperature)

```python
# Temperature: 0.1 (strict)
query = "What was my last question?"

# With low temp:
selected_tool = "get_recent_conversations"  # ✅ Correct, deterministic

# With high temp (0.7):
selected_tool = "search_conversations"      # ❌ Wrong, too creative
# or worse:
selected_tool = "get_last_query_history"    # ❌ Hallucinated tool!
```

#### Example 2: Thinking Step (High Temperature)

```python
# Temperature: 0.6 (exploratory)
query = "Why did search_conversations fail?"

# With high temp (good for thinking):
reasoning = """
Possible reasons:
1. Missing query parameter - tool requires it
2. User asked temporal question, not topic search
3. Should use get_recent_conversations instead
4. Tool description may be ambiguous
Let me analyze: User said "last question" which is TEMPORAL...
→ Recommendation: Use get_recent_conversations
"""

# With low temp (0.1):
reasoning = """
Tool failed due to missing parameter.
"""  # ← Too brief, doesn't explore alternatives
```

#### Example 3: Q&A Response (Medium Temperature)

```python
# Temperature: 0.4 (conversational but accurate)
result = {"reminder": "Check truck registration", "time": "in 30 minutes"}

# With medium temp (good):
response = "You have one reminder in 30 minutes to check truck registration"

# With low temp (0.1):
response = "Reminder: Check truck registration. Time: 30 minutes."  # ← Robotic

# With high temp (0.8):
response = "Oh! Let me tell you about this super important reminder..."  # ← Too creative
```

---

### Temperature in Sequential Thinking Architecture

**Integration with Thinking Modes:**

```python
def execute_with_adaptive_temperature(query, mode='cloud'):
    """Execute with temperature optimized for each step."""
    
    # Step 1: Tool selection (strict)
    tool = route_query(query, temperature=0.1)
    
    # Step 2: Execute tool
    result = execute_tool(tool)
    
    # Step 3: If failed, think with higher temp
    if not result.ok:
        thinking = analyze_failure(
            query=query,
            failure=result,
            temperature=0.6  # Higher for exploration
        )
        
        # Step 4: Re-route with strict temp
        corrected_tool = route_query(
            query,
            context=thinking,
            temperature=0.1  # Back to strict
        )
        
        result = execute_tool(corrected_tool)
    
    # Step 5: Generate response (conversational)
    response = generate_response(
        result,
        temperature=0.4  # Friendly but accurate
    )
    
    return response
```

---

## Test Suite Structure

### Directory Layout

```
tests/
├── intent/
│   ├── test_conversation_queries.py
│   ├── test_reminder_queries.py
│   ├── test_alert_queries.py
│   ├── test_time_queries.py
│   ├── test_memory_queries.py
│   └── test_multi_turn.py
├── regression/
│   ├── test_conversation_tool_regression.py
│   ├── test_reminder_parsing.py
│   └── test_<date>_<issue>.py
├── temperature/
│   ├── test_tool_selection_temp.py
│   ├── test_thinking_temp.py
│   └── test_response_temp.py
└── performance/
    ├── test_fast_path_latency.py
    └── test_thinking_overhead.py
```

---

### Test Format: Intent-Based

```python
# tests/intent/test_conversation_queries.py

import pytest
from orchestrator.orchestrator_v2 import Orchestrator

class TestConversationIntentRouting:
    """Test natural language conversation queries route correctly."""
    
    @pytest.fixture
    def orchestrator(self):
        return Orchestrator(mode='cloud')
    
    @pytest.mark.parametrize("query", [
        "What was my last question?",
        "What did I just ask?",
        "What was the last thing I said?",
        "What did we just talk about?",
        "What was our last conversation?",
        "Show me what I asked earlier",
        "What was my previous request?",
        "Remind me what I just asked about",
    ])
    def test_temporal_conversation_queries(self, orchestrator, query):
        """Test temporal conversation queries use get_recent_conversations."""
        
        # Route the query
        result = orchestrator.route_query(query)
        
        # Assert correct tool
        assert result.tool_name == "get_recent_conversations", \
            f"Query '{query}' should use get_recent_conversations, got {result.tool_name}"
        
        # Assert no query parameter required
        assert "query" not in result.tool_args or result.tool_args.get("query") is None, \
            f"get_recent_conversations should not require query parameter for '{query}'"
    
    @pytest.mark.parametrize("query,expected_query_param", [
        ("Did I ask about Bitcoin?", "Bitcoin"),
        ("When did I mention Flask?", "Flask"),
        ("Show conversations about reminders", "reminders"),
        ("Find where I talked about webhooks", "webhooks"),
    ])
    def test_topic_conversation_queries(self, orchestrator, query, expected_query_param):
        """Test topic search queries use search_conversations with query param."""
        
        result = orchestrator.route_query(query)
        
        # Assert correct tool
        assert result.tool_name == "search_conversations", \
            f"Query '{query}' should use search_conversations, got {result.tool_name}"
        
        # Assert query parameter is present
        assert "query" in result.tool_args, \
            f"search_conversations requires query parameter for '{query}'"
        
        # Optionally assert query param contains expected keyword
        actual_query = result.tool_args["query"].lower()
        assert expected_query_param.lower() in actual_query, \
            f"Query param should contain '{expected_query_param}', got '{actual_query}'"
```

---

### Test Format: Regression Detection

```python
# tests/regression/test_conversation_tool_regression.py

import pytest
from datetime import datetime

class TestConversationToolRegression:
    """
    Regression test for the bug discovered on 2025-11-18:
    User asked "What was the last conversation?" and router
    incorrectly chose search_conversations instead of get_recent_conversations.
    """
    
    def test_last_conversation_query_regression(self, orchestrator):
        """
        Regression: "What was the last conversation?" should not fail
        with "Missing query parameter" error.
        """
        query = "What was the last conversation we had?"
        
        # This should NOT fail
        result = orchestrator.execute_query(query)
        
        # Assert success
        assert result.ok, f"Query '{query}' failed: {result.error}"
        
        # Assert used correct tool
        assert result.tool_name == "get_recent_conversations", \
            f"Should use get_recent_conversations, got {result.tool_name}"
        
        # Assert no "Missing query parameter" error
        assert "Missing query parameter" not in str(result.error), \
            "Should not require query parameter for temporal query"
    
    def test_variations_of_last_conversation(self, orchestrator):
        """Test all variations that failed before the fix."""
        
        queries = [
            "What was my last question?",
            "What did I just ask?",
            "What was the last thing I asked you?",
        ]
        
        for query in queries:
            result = orchestrator.execute_query(query)
            
            # None of these should fail with parameter error
            assert result.ok or "Missing query parameter" not in str(result.error), \
                f"Query '{query}' failed with parameter error (regression!)"
```

---

### Test Format: Temperature Validation

```python
# tests/temperature/test_tool_selection_temp.py

import pytest

class TestToolSelectionTemperature:
    """Test that tool selection uses low temperature for determinism."""
    
    def test_tool_selection_is_deterministic(self, orchestrator):
        """Tool selection should be deterministic (low temp)."""
        
        query = "What was my last question?"
        
        # Run 10 times - should always pick same tool
        results = [
            orchestrator.route_query(query).tool_name
            for _ in range(10)
        ]
        
        # Assert all identical
        assert len(set(results)) == 1, \
            f"Tool selection not deterministic: got {set(results)}"
        
        # Assert correct tool
        assert results[0] == "get_recent_conversations"
    
    def test_no_hallucinated_tools(self, orchestrator):
        """Low temperature should prevent tool hallucination."""
        
        query = "Show me the flux capacitor status"
        
        result = orchestrator.route_query(query)
        
        # Should either pick a real tool or return Q&A
        available_tools = orchestrator.registry.list_tools()
        
        if result.tool_name:
            assert result.tool_name in available_tools, \
                f"Hallucinated tool: {result.tool_name}"
```

---

## Regression Detection

### Automated Regression Testing

```python
# tests/regression/auto_detect.py

class RegressionDetector:
    """Automatically detect routing regressions."""
    
    def __init__(self, test_db_path):
        self.db = sqlite3.connect(test_db_path)
        self._create_baseline()
    
    def _create_baseline(self):
        """Create baseline of expected query → tool mappings."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS query_baseline (
                query TEXT PRIMARY KEY,
                expected_tool TEXT,
                expected_success BOOLEAN,
                category TEXT,
                last_verified TIMESTAMP
            )
        """)
    
    def add_baseline(self, query, tool, category):
        """Add a verified query → tool mapping."""
        self.db.execute("""
            INSERT OR REPLACE INTO query_baseline
            (query, expected_tool, expected_success, category, last_verified)
            VALUES (?, ?, 1, ?, ?)
        """, (query, tool, category, datetime.now()))
        self.db.commit()
    
    def detect_regressions(self, orchestrator):
        """Test all baseline queries and detect regressions."""
        
        baselines = self.db.execute("""
            SELECT query, expected_tool, category
            FROM query_baseline
        """).fetchall()
        
        regressions = []
        
        for query, expected_tool, category in baselines:
            result = orchestrator.route_query(query)
            
            if result.tool_name != expected_tool:
                regressions.append({
                    'query': query,
                    'category': category,
                    'expected': expected_tool,
                    'actual': result.tool_name,
                    'severity': 'high'
                })
        
        return regressions
    
    def report(self, regressions):
        """Generate regression report."""
        if not regressions:
            print("✅ No regressions detected!")
            return
        
        print(f"❌ Detected {len(regressions)} regressions:\n")
        
        for reg in regressions:
            print(f"Query: '{reg['query']}'")
            print(f"  Expected: {reg['expected']}")
            print(f"  Actual: {reg['actual']}")
            print(f"  Category: {reg['category']}")
            print()

# Usage:
detector = RegressionDetector('tests/regression_baseline.db')

# Add baselines (run once, then version control)
detector.add_baseline("What was my last question?", "get_recent_conversations", "conversation_temporal")
detector.add_baseline("When is my next reminder?", "list_reminders", "reminder_temporal")
detector.add_baseline("Any alerts?", "list_alerts", "alert_query")

# Run regression detection (in CI/CD)
regressions = detector.detect_regressions(orchestrator)
detector.report(regressions)
```

---

## Implementation

### Phase 1: Intent Test Suite (Week 1)

**Goal**: Create comprehensive intent-based test suite

**Tasks**:
1. Create `tests/intent/` directory structure
2. Write natural language test cases for each tool category
3. Parametrize tests for all query variations
4. Run tests, establish baseline success rate

**Success Criteria**:
- 100+ natural language test cases
- Covers all major tools
- Baseline: >85% pass rate

---

### Phase 2: Temperature Implementation (Week 2)

**Goal**: Implement dynamic temperature settings

**Tasks**:
1. Modify `llm_provider.py` to support task-specific temperatures
2. Update router to use low temp (0.1) for tool selection
3. Update thinking steps to use high temp (0.6)
4. Update Q&A generation to use medium temp (0.4)
5. Measure impact on success rate and response quality

**Success Criteria**:
- Tool selection determinism: >95%
- No hallucinated tools
- Conversational responses: user satisfaction survey

---

### Phase 3: Regression Detection (Week 3)

**Goal**: Automated regression detection

**Tasks**:
1. Create `RegressionDetector` class
2. Populate baseline database with verified queries
3. Integrate into CI/CD pipeline
4. Run on every commit to catch regressions early

**Success Criteria**:
- Baseline database with 200+ verified queries
- Automated detection in GitHub Actions
- <5% false positive rate

---

### Phase 4: Continuous Improvement (Ongoing)

**Goal**: Learn from production and add tests

**Workflow**:
1. User reports issue (e.g., "What was my last question?" failed)
2. Add failing test case to `tests/intent/`
3. Fix the bug (update tool descriptions, router prompt)
4. Verify test now passes
5. Add to regression baseline
6. Deploy fix

**This creates a virtuous cycle**: Every bug becomes a test, preventing future regressions.

---

## Quick Start

### Run Intent Tests

```bash
# Run all intent tests
pytest tests/intent/ -v

# Run specific category
pytest tests/intent/test_conversation_queries.py -v

# Run with coverage
pytest tests/intent/ --cov=orchestrator --cov-report=html
```

### Detect Regressions

```bash
# Run regression detector
python tests/regression/auto_detect.py

# Output:
# ✅ No regressions detected!
# or
# ❌ Detected 1 regression:
# Query: 'What was my last question?'
#   Expected: get_recent_conversations
#   Actual: search_conversations
#   Category: conversation_temporal
```

### Test Temperature Settings

```bash
# Test tool selection determinism
pytest tests/temperature/test_tool_selection_temp.py::test_tool_selection_is_deterministic -v

# Test thinking creativity
pytest tests/temperature/test_thinking_temp.py -v
```

---

## Example: Adding a New Tool

**When you create a new tool**, add intent tests immediately:

```python
# skills/new_tool.tool.json created

# Immediately add tests in tests/intent/test_new_tool.py
class TestNewToolIntent:
    @pytest.mark.parametrize("query", [
        "Formal keyword query",
        "Natural variation 1",
        "Natural variation 2",
        "Edge case query",
        "Ambiguous but should work",
    ])
    def test_new_tool_routing(self, query):
        result = orchestrator.route_query(query)
        assert result.tool_name == "new_tool"
```

**This prevents regressions from day one.**

---

## Summary

### Key Principles

1. ✅ **Test intent, not keywords**
2. ✅ **Use natural human language**
3. ✅ **Temperature matters** - strict for tools, creative for thinking
4. ✅ **Automate regression detection**
5. ✅ **Every bug becomes a test**

### Expected Impact

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Intent routing success** | 85% | 95% | +10% |
| **Regression detection** | Manual | Automated | 100% |
| **Test coverage** | Keywords only | Natural language | 200% |
| **Temperature optimization** | Static 0.7 | Dynamic 0.1-0.7 | Better quality |
| **Development speed** | Slow (manual testing) | Fast (automated CI) | 3x faster |

### Timeline

- **Week 1**: Intent test suite (100+ tests)
- **Week 2**: Temperature implementation
- **Week 3**: Regression detection
- **Ongoing**: Continuous improvement

**This is how we build a robust, human-friendly AI assistant.** 🎯

