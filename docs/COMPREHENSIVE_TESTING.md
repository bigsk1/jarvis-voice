# Comprehensive Testing Guide

## Overview

The comprehensive test suite (`tests/comprehensive_test.py`) is a "burn test" that validates ALL Jarvis features in a logical order. It's designed to catch regressions early and verify the entire system is working correctly after code changes.

## Quick Start

```bash
# Test cloud mode
./tests/comprehensive_test.py cloud

# Test local mode  
./tests/comprehensive_test.py local

# Test both modes
./tests/comprehensive_test.py both

# Stop on first failure (for debugging)
./tests/comprehensive_test.py cloud --stop-on-fail

# JSON output (for automation)
./tests/comprehensive_test.py cloud --json
```

## What It Tests

### 1. Basic Tools (No Side Effects)
- `get_time` - Time retrieval
- `crypto_price` - API integration
- `api_call` - HTTP requests

### 2. Memory System
- `remember` - Create memories
- `search_memory` - FTS5 keyword search
- `semantic_recall` - AI-powered semantic search
- `update_memory` - Update existing memories
- **Database verification** - Confirms data in correct DB

### 3. FTS5 Search System
- FTS5 tables exist (5 tables expected)
- FTS5 triggers exist (3 triggers: insert/update/delete)
- Search performance (< 2 seconds)

### 4. Reminder System
- `create_reminder` - Create reminders
- `list_reminders` - List pending reminders
- `acknowledge_reminders` - Cancel reminders
- **Database verification** - Confirms reminders in correct DB

### 5. Time Parsing
- "noon" → 12:00 PM
- "midnight" → 12:00 AM
- Other natural language times

### 6. Conversation System
- `get_recent_conversations` - Recent history
- `search_conversations` - Search past conversations

### 7. MCP Tools
- `mcp_duckduckgo_search` - Credential-free web search
- `mcp_duckduckgo_fetch_content` - Public-page extraction with pagination
- `mcp_fetch_fetch` - HTTP fetch via MCP
- `mcp_brave_search_brave_web_search` - Brave web search (if configured)
- **Graceful skipping** - Disabled tools don't fail tests

### 8. Database Mode Isolation
- **Critical**: Verifies local mode uses `jarvis_memory_local.db`
- **Critical**: Verifies cloud mode uses `jarvis_memory.db`
- **Critical**: Confirms NO cross-contamination

## Test Architecture

### Modular Design
```python
class ComprehensiveTest:
    test_basic_tools()           # Basic functionality
    test_memory_system()          # Memory CRUD + verification
    test_fts5_system()            # FTS5 infrastructure
    test_reminder_system()        # Reminders + DB checks
    test_reminder_time_parsing()  # Time parsing edge cases
    test_conversation_system()    # Conversation history
    test_mcp_tools()              # MCP integration (skip if disabled)
    test_database_mode_isolation()  # CRITICAL: DB isolation
```

### Database Verification
Every test that modifies data verifies the database:
```python
# 1. Run orchestrator command
result = self.run_query("Set a reminder for test in 5 minutes")

# 2. Verify in database
db_check = self.check_db("SELECT * FROM reminders WHERE title='test'")

# 3. Confirm correct database was used
assert len(db_check) > 0  # Found in expected DB
```

### Graceful Degradation
- MCP servers not running → Tests marked as "skipped"
- Disabled tools → Tests skipped, not failed
- Unknown errors → Captured and reported, continue testing

## Adding New Tests

### 1. Add Test Method
```python
def test_new_feature(self):
    """Test description."""
    self.log("Testing New Feature", "HEADER")
    
    # Run test
    result = self.run_query("Test new feature")
    
    # Verify result
    self.add_result(TestResult(
        "new_feature",
        result.get("ok") and "expected" in str(result),
        "Should do expected thing"
    ))
    
    # Verify database (if applicable)
    db_check = self.check_db("SELECT * FROM new_table")
    self.add_result(TestResult(
        "new_feature_db_verification",
        len(db_check) > 0,
        "Should find data in database"
    ))
```

### 2. Call in `run_all_tests()`
```python
def run_all_tests(self):
    self.test_basic_tools()
    self.test_memory_system()
    # ... existing tests ...
    self.test_new_feature()  # Add here
    self.test_database_mode_isolation()  # Always last
```

### 3. Update This Documentation
Add your test to the "What It Tests" section above.

## Best Practices

### Test Order Matters
Tests run in logical order:
1. Basic tools (no side effects)
2. Memory system (creates test data)
3. FTS5 system (uses test data)
4. Reminders (creates & deletes)
5. Conversations (uses history)
6. MCP tools (external dependencies)
7. Database isolation (validates everything)

### Clean Up After Tests
```python
# Create test data with unique identifiers
test_id = f"test_{self.mode}_{int(time.time())}"

# Use in tests
self.run_query(f"Create reminder {test_id}")

# Clean up
self.run_query(f"Cancel {test_id}")
```

### Database Verification
**Always verify database state** for tests that modify data:
- Confirms orchestrator worked correctly
- Catches bugs in tool → DB pipeline
- Validates correct database was used (cloud vs local)

## Integration with CI/CD

### Exit Codes
- `0` - All tests passed
- `1` - One or more tests failed

### JSON Output
```bash
./tests/comprehensive_test.py cloud --json > results.json
```

Output format:
```json
{
  "mode": "cloud",
  "database": "/path/to/jarvis_memory.db",
  "timestamp": "2025-11-21T...",
  "total": 25,
  "passed": 25,
  "failed": 0,
  "results": [
    {
      "name": "get_time",
      "passed": true,
      "message": "Should return current time",
      "timestamp": "..."
    }
  ]
}
```

## AI Agent Usage

### Running Tests
AI agents (like me) can run tests and analyze results:

```python
# Run test
result = subprocess.run(
    ["./tests/comprehensive_test.py", "cloud", "--json"],
    capture_output=True
)

# Parse results
data = json.loads(result.stdout)

# Report
if data["failed"] > 0:
    print(f"⚠️ {data['failed']} tests failed!")
    for test in data["results"]:
        if not test["passed"]:
            print(f"  - {test['name']}: {test['message']}")
```

### Instructions for AI
1. Run comprehensive test after major code changes
2. Check for failures in output
3. If failures occur:
   - Read test name and message
   - Investigate relevant code
   - Propose fix
   - Re-run test to verify

### Auto-Fix Capability
AI can automatically fix common issues:
- Database path problems → Check `MemoryDB()` initialization
- Tool not found → Check `enabled: true` in tool.json
- MCP failures → Verify MCP server running
- Time parsing → Check `parse_time_expression()` logic

## Common Failure Modes

### "Database mode isolation" fails
**Cause**: Local mode is using cloud database (or vice versa)

**Fix**:
1. Check `load_config()` auto-detection
2. Verify `LLM_PROVIDER` environment variable
3. Check `MemoryDB()` initialization
4. Verify `executor.py` passes environment to tools

### "FTS5 tables exist" fails
**Cause**: Database doesn't have FTS5 tables

**Fix**:
1. Run `./bin/rebuild-fts-index` 
2. Or delete DB and let it recreate
3. Verify `memory_db.py` creates FTS5 on init

### "MCP tools" fail
**Cause**: MCP server not running

**Fix**:
- This is expected if servers aren't running
- Tests should show "skipped", not "failed"
- If showing "failed", improve graceful degradation

### Time parsing fails
**Cause**: Reminder time parsing regression

**Fix**:
1. Check `parse_time_expression()` in `create_reminder.py`
2. Verify "noon" → 12:00, "midnight" → 00:00
3. Add test case for new time format

## Comparison with Other Tests

| Test Suite | Purpose | When to Use |
|------------|---------|-------------|
| Focused pytest modules | Deterministic regression coverage | During development |
| Full pytest suite | Cross-feature regression coverage | Before merge |
| Maintained integration wrappers | Explicit provider/service verification | When that path changed |
| **`comprehensive_test.py`** | **Full system validation** | **Before merge, after major changes** |

## Running After Merge

```bash
# After merging to main
git checkout main
git pull

# Run comprehensive test
./tests/comprehensive_test.py both

# If all pass ✅
# System is stable!

# If failures ❌  
# Investigate and fix before next merge
```

## Future Enhancements

### Planned Features
- [ ] Performance benchmarking (track test duration trends)
- [ ] HTML report generation
- [ ] Parallel test execution
- [ ] Docker integration tests
- [ ] API endpoint tests (when API mode is enabled)
- [ ] Alert system tests
- [ ] Service manager tests

### LLM-Powered Testing
- [ ] LLM reads test specs and generates new tests
- [ ] LLM analyzes failures and suggests fixes
- [ ] LLM validates tool outputs for correctness
- [ ] Self-healing tests that adapt to changes

## Summary

**Use `comprehensive_test.py` as your "one test to rule them all":**

✅ Fast (completes in < 2 minutes)  
✅ Comprehensive (tests ALL features)  
✅ Database verification (catches DB bugs)  
✅ Modular (easy to extend)  
✅ AI-friendly (can be run and analyzed by agents)  
✅ CI/CD ready (JSON output, exit codes)  

**Run before every merge. Sleep well knowing nothing broke.** 🎯
