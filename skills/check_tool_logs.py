#!/usr/bin/env python3
"""
Jarvis Skill: Check Tool Logs
Allows the LLM to check recent tool execution logs to understand errors.
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from tool_logger import ToolLogger


def main():
    """Check tool logs."""
    # Read input from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        input_data = {}
    
    # Extract parameters
    tool_name = input_data.get("tool_name", None)
    limit = input_data.get("limit", 3)
    
    # Get logger
    logger = ToolLogger()
    
    # Get logs
    if tool_name:
        logs = logger.get_logs_by_tool(tool_name, limit)
        speech_prefix = f"Last {len(logs)} calls to {tool_name}:"
    else:
        logs = logger.get_recent_logs(limit)
        speech_prefix = f"Last {len(logs)} tool calls:"
    
    if not logs:
        return_success(
            speech="No tool execution logs found yet.",
            data={"logs": []}
        )
        return 0
    
    # Build speech summary
    log_summaries = []
    for log in logs:
        status = "succeeded" if log["result"]["ok"] else "failed"
        tool = log["tool"]
        duration = log["duration_ms"]
        
        summary = f"{tool} {status} in {duration:.0f}ms"
        
        if not log["result"]["ok"]:
            error = log["result"].get("error", "unknown error")
            summary += f" - Error: {error}"
        
        log_summaries.append(summary)
    
    speech = speech_prefix + " " + "; ".join(log_summaries)
    
    # Return detailed logs in data
    simplified_logs = []
    for log in logs:
        simplified_logs.append({
            "timestamp": log["timestamp"],
            "tool": log["tool"],
            "arguments": log["arguments"],
            "ok": log["result"]["ok"],
            "speech": log["result"]["speech"],
            "error": log["result"].get("error"),
            "duration_ms": log["duration_ms"]
        })
    
    return_success(
        speech=speech,
        data={"logs": simplified_logs}
    )
    return 0


def return_success(speech, data=None):
    """Return success response."""
    result = {
        "ok": True,
        "speech": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech, data=None):
    """Return error response."""
    result = {
        "ok": False,
        "speech": speech,
        "error": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main())

