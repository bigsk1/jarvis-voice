# Orchestrator

The orchestrator is the "brain" between STT and TTS that:
1. **Routes** transcripts to appropriate handlers
2. **Executes** tools/skills
3. **Formats** responses for TTS

## Architecture

```
Transcription → Router → Executor → Response
                   ↓
              (determines intent)
                   ↓
         ┌─────────┴─────────┐
         ↓                   ↓
      [Tool]              [Q&A]
    (skills/)         (question.sh)
```

## Components

### `router.py`
- Determines user intent from transcript
- Returns: `{intent, tool_name, args, confidence}`
- Currently rule-based; future: LLM-based classification

### `executor.py`
- Executes tools/skills in `skills/` directory
- Manages timeouts, errors, JSON I/O
- Returns: `{ok, speech, data}`

### `orchestrator.py`
- Main coordinator
- Combines routing + execution
- Falls back to Q&A for general questions

## Usage

### Test Router
```bash
cd /home/boss/jarvis-voice
./orchestrator/router.py cloud "What's the weather like?"
```

### Test Executor
```bash
./orchestrator/executor.py cloud weather '{"location":"Portland"}'
```

### Test Full Orchestrator
```bash
./orchestrator/orchestrator.py cloud "What's the weather in Seattle?"
```

## Creating Tools

Tools live in `skills/` and follow this contract:

**Input**: JSON via stdin
```json
{
  "location": "Portland, OR"
}
```

**Output**: JSON via stdout
```json
{
  "ok": true,
  "speech": "It's 72 degrees and sunny",
  "data": {
    "temp": 72,
    "condition": "sunny"
  }
}
```

**Exit Code**: 0 for success, non-zero for error

### Example Tool

```bash
#!/bin/bash
# skills/time.sh
NOW=$(date "+%I:%M %p")
jq -n --arg speech "It's $NOW" '{ok:true, speech:$speech}'
```

## Integration

To integrate the orchestrator into the wake loop:

1. Modify `question-mic.sh` to call orchestrator instead of direct Q&A
2. Orchestrator returns speech text
3. Pass to TTS scripts (`say.sh` or `say-local.sh`)

This keeps the wake loop clean and extensible.

## Future Enhancements

- [ ] LLM-based intent classification
- [ ] Multi-step workflows
- [ ] Context/session management
- [ ] MCP (Model Context Protocol) integration
- [ ] Tool marketplace/discovery
- [ ] Async tool execution
- [ ] Retry logic with backoff

