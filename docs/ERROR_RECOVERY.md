# Error Recovery & Self-Correction System

## Overview

Jarvis now has the ability to self-diagnose errors, check logs, and retry failed operations with corrected parameters ( depending on the tool ). This makes the system more robust and able to recover from common failures automatically.

## Relationship to Completion Guard

These mechanisms solve **different layers** of failure and do **not** replace each other:

| Mechanism | When it runs | What it fixes |
|-----------|----------------|----------------|
| **Tool / routing error recovery** (this doc) | During the orchestrator turn, after a tool fails | Bad parameters, transient tool errors, “try again with fixes” inside the same run |
| **[Completion Guard](./COMPLETION_GUARD.md)** | After the assistant has produced an answer | “Sounds done but isn’t”: missed tools, weak answers, user-driven or auto repair, tickets |

So: a tool can succeed and still leave the task incomplete—that is where Completion Guard helps. Conversely, Completion Guard does not remove the need for **in-turn retries** when the tool returns a hard error.

## How It Works

### 1. Automatic Retry on Failure

When a tool fails, the orchestrator automatically:
1. Captures the error message and parameters used
2. Provides this context to Claude for the retry
3. Claude can decide to:
   - Retry with corrected parameters
   - Check logs to understand the error
   - Try a different approach
   - Give up and report the error

**Max retries**: 1 (configurable in `orchestrator_v2.py`)

### 2. Tool Log Access

Jarvis has access to the `check_tool_logs` tool which allows it to:
- See recent tool executions
- Understand what went wrong
- Learn from errors
- Make informed decisions about retries

## Flow Diagrams

### Normal Execution (No Errors)

```
User: "What's the bitcoin price?"
  ↓
Claude: Routes to crypto_price tool
  ↓
Tool executes successfully ✅
  ↓
Jarvis: "Bitcoin is currently $105,109..."
  ↓
Logged to: logs/tools/tool-calls-YYYY-MM-DD.jsonl
```

### Automatic Error Recovery

```
User: "Call the API at invalid-url"
  ↓
Claude: Routes to api_call tool with URL
  ↓
Tool fails ❌ (invalid URL format)
  ↓
Error logged with details
  ↓
Orchestrator: Retry attempt 1/1
  ↓
Claude receives error context:
  "Tool 'api_call' failed with: Invalid URL format
   Arguments used: {'url': 'invalid-url', 'method': 'GET'}"
  ↓
Claude: Corrects URL format, retries
  ↓
Tool executes successfully ✅
  ↓
Jarvis: "API call succeeded..."
```

### Self-Diagnosis with Logs

```
User: "Why did that fail?"
  ↓
Claude: Routes to check_tool_logs tool
  ↓
Tool returns recent failures with errors
  ↓
Claude analyzes logs
  ↓
Jarvis: "The send_webhook tool failed because 
         the URL was malformed. It expected 
         https:// format."
```

## Configuration

### Max Retries

Edit `orchestrator/orchestrator_v2.py`:

```python
class Orchestrator:
    def __init__(self, mode='cloud'):
        ...
        self.max_retries = 1  # Change this value
```

**Recommended values**:
- `0`: No retries (fail fast)
- `1`: One retry (balance of recovery vs. latency)
- `2+`: Multiple retries (higher success rate but slower)

## Log Files

### Location
```
logs/tools/tool-calls-YYYY-MM-DD.jsonl
```

### Format (JSON Lines)
```json
{
  "timestamp": "2025-11-11T02:18:27.733804",
  "mode": "cloud",
  "tool": "crypto_price",
  "arguments": {"coin": "bitcoin"},
  "result": {
    "ok": true,
    "speech": "Bitcoin is currently $105,109...",
    "has_data": true,
    "error": null
  },
  "duration_ms": 140.48,
  "user_query": null
}
```

## Viewing Logs

### Recent Tool Calls
```bash
./bin/tool-logs recent
```

### Recent with Details
```bash
./bin/tool-logs recent --verbose
```

### Specific Tool
```bash
./bin/tool-logs tool --tool crypto_price
```

### Statistics
```bash
./bin/tool-logs stats
```

## Example Scenarios

### Scenario 1: Invalid Parameter Correction

**User**: "Send webhook to httpbin with message test"

**First attempt**:
- Claude calls: `send_webhook(url="httpbin", data={"message": "test"})`
- Fails: "Invalid URL format"

**Retry**:
- Error context: "URL must start with http:// or https://"
- Claude corrects: `send_webhook(url="https://httpbin.org/post", data={"message": "test"})`
- Success ✅

### Scenario 2: Learning from Logs

**User**: "Get ethereum price"

**Execution**:
- Claude calls: `crypto_price(coin="ethereum")`
- Success, logged

**Later, User**: "What coins have I checked?"

**Claude's approach**:
- Calls: `check_tool_logs(tool_name="crypto_price")`
- Reads logs showing "bitcoin" and "ethereum"
- Responds: "You've checked bitcoin and ethereum prices today"

### Scenario 3: Multiple Failure Points

**User**: "Call the API at bad-url with invalid-method"

**First attempt**:
- Fails: Invalid URL format
- Logged

**Retry (automatic)**:
- Claude sees error, checks logs
- Calls: `check_tool_logs(tool_name="api_call", limit=2)`
- Sees pattern of URL errors
- Corrects URL format
- Retries with: `api_call(url="https://bad-url.com", method="GET")`
- Still fails (connection error), but different error

**Result**: 
- Max retries reached
- Jarvis: "I tried 2 times but couldn't complete the task. The URL appears to be unreachable."

## Benefits

### 1. Robustness
- Recovers from temporary failures
- Handles common user mistakes (malformed URLs, typos, etc.)
- Continues working even when one approach fails

### 2. Intelligence
- Learns from errors
- Adapts approach based on what worked/failed
- Can explain what went wrong

### 3. Transparency
- All tool calls logged
- Easy to audit and debug
- Users can ask "what happened?"

### 4. Performance Insights
- Track which tools are slow
- Identify failure patterns
- Optimize based on real usage

## Advanced Usage

### Custom Error Messages

Tools can provide helpful error messages that Claude can use:

```python
# In your tool script
if not valid_url(url):
    return {
        "ok": False,
        "speech": "Invalid URL format",
        "error": "URL must start with http:// or https:// and be properly formatted. Example: https://api.example.com"
    }
```

### Proactive Checks

Claude can proactively check logs before attempting risky operations:

**User**: "Try that webhook again"

**Claude**:
1. Checks logs to see what failed last time
2. Identifies the issue
3. Attempts with corrected parameters
4. Or asks for clarification if needed

### Log-Based Learning

Over time, Claude learns patterns:
- "This API often times out" → increase timeout
- "This URL format always fails" → correct it preemptively
- "This tool needs specific parameter format" → format correctly

## Monitoring & Debugging

### Daily Stats
```bash
# See what's been happening
./bin/tool-logs stats

# Check for failures
./bin/tool-logs recent -n 50 | grep "❌"
```

### Export Logs
```bash
# For analysis
cat logs/tools/tool-calls-2025-11-11.jsonl | jq '.' > formatted-logs.json
```

### Filter Failures
```bash
# See only failed calls
cat logs/tools/tool-calls-2025-11-11.jsonl | jq 'select(.result.ok == false)'
```

## Best Practices

### For Tool Development

1. **Provide detailed error messages**
   ```python
   error = "Invalid format. Expected: {'name': 'John', 'age': 25}"
   ```

2. **Return structured errors**
   ```python
   return {
       "ok": False,
       "speech": "User-friendly message",
       "error": "Technical error details",
       "data": {"expected_format": "...", "got": "..."}
   }
   ```

3. **Add parameter validation**
   ```python
   if not url.startswith("http"):
       return error("URL must start with http:// or https://")
   ```

### For Users

1. **Check logs after failures**
   ```
   "What went wrong?"
   "Check the tool logs"
   ```

2. **Be specific in retries**
   ```
   "Try again with the full URL"
   "Try the webhook with https"
   ```

3. **Review stats periodically**
   ```bash
   ./bin/tool-logs stats
   ```

## Future Enhancements

- [ ] Persistent learning across sessions
- [ ] Automatic error pattern detection
- [ ] Suggestions for fixing common issues
- [ ] Integration with external error tracking
- [ ] Automated testing based on logs
- [ ] Performance optimization recommendations

---

For post-answer quality control and bounded repair, see [Completion Guard](./COMPLETION_GUARD.md).

