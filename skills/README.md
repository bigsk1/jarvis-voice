# Skills / Tools

This directory contains executable tools that Jarvis can invoke.

## Tool Contract

All tools must follow this interface:

### Input (stdin)
JSON object with parameters:
```json
{
  "param1": "value1",
  "param2": "value2"
}
```

### Output (stdout)
JSON object with result:
```json
{
  "ok": true,
  "speech": "Text to speak to user",
  "data": {
    "additional": "metadata"
  }
}
```

### Exit Code
- `0`: Success
- Non-zero: Error

## Example Tools

### `time.sh`
Returns current time.

**Usage:**
```bash
echo '{}' | ./time.sh
```

**Output:**
```json
{
  "ok": true,
  "speech": "It's 03:30 PM on Monday, November 11",
  "data": {
    "time": "15:30"
  }
}
```

### `weather.sh`
Returns weather information (currently mocked).

**Usage:**
```bash
echo '{"location":"Portland"}' | ./weather.sh
```

**Output:**
```json
{
  "ok": true,
  "speech": "It's 72 degrees and partly cloudy in Portland",
  "data": {
    "location": "Portland",
    "temp": 72,
    "condition": "partly cloudy"
  }
}
```

## Creating New Tools

### Bash Template
```bash
#!/bin/bash
set -euo pipefail

# Read input
INPUT=$(cat)
PARAM=$(echo "$INPUT" | jq -r '.param')

# Do work...
RESULT="some result"

# Return JSON
jq -n --arg speech "Result: $RESULT" '{ok:true, speech:$speech}'
```

### Python Template
```python
#!/usr/bin/env python3
import sys
import json

# Read input
input_data = json.load(sys.stdin)
param = input_data.get("param", "default")

# Do work...
result = f"Processed: {param}"

# Return JSON
output = {
    "ok": True,
    "speech": result,
    "data": {"param": param}
}
print(json.dumps(output))
```

## Testing Tools

```bash
# Direct test
echo '{"location":"Seattle"}' | ./weather.sh

# Via orchestrator
cd ..
./orchestrator/executor.py cloud weather '{"location":"Seattle"}'
```

## Tool Ideas

- 🌤️ Real weather API integration
- 🏠 Smart home control
- 📅 Calendar integration
- 📧 Email summaries
- 🖥️ System status (CPU, memory, disk)
- 🎵 Music control
- 📝 Note taking
- ⏰ Timer/reminder management
- 📊 Stock prices
- 📰 News headlines

## Integration

Tools are automatically discovered by the orchestrator when:
1. Placed in `skills/` directory
2. Named `<tool_name>.sh` or `<tool_name>.py`
3. Made executable: `chmod +x skills/mytool.sh`
4. Router maps intent to tool name

---

**Keep tools simple, fast, and focused on one task!**

