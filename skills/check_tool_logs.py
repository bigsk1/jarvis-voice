#!/usr/bin/env python3
"""
Jarvis Skill: Check Tool Logs
Allows the LLM to check recent tool execution logs and workflow execution logs.
"""
import sys
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from tool_logger import ToolLogger


def get_workflow_logs(limit: int = 10, workflow_id: str = None, days: int = 7) -> list:
    """Get recent workflow execution logs from JSONL files."""
    logs_dir = Path(__file__).parent.parent / "logs"
    workflow_logs = []
    
    # Get workflow log files from last N days
    cutoff_date = datetime.now() - timedelta(days=days)
    
    for log_file in sorted(logs_dir.glob("workflows-*.jsonl"), reverse=True):
        # Parse date from filename (workflows-2026-01-22.jsonl)
        try:
            date_str = log_file.stem.replace("workflows-", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff_date:
                continue
        except ValueError:
            continue
        
        # Read log entries
        try:
            with open(log_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            entry = json.loads(line)
                            # Filter by workflow_id if specified
                            if workflow_id and entry.get('workflow_id') != workflow_id:
                                continue
                            workflow_logs.append(entry)
                        except json.JSONDecodeError:
                            continue
        except IOError:
            continue
    
    # Sort by timestamp descending and limit
    workflow_logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return workflow_logs[:limit]


def main():
    """Check tool logs."""
    # Read input from command line argument
    try:
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        input_data = {}
    
    # Extract parameters
    tool_name = input_data.get("tool_name", None)
    limit = input_data.get("limit", 3)
    log_type = input_data.get("log_type", "tools")  # "tools", "workflows", or "all"
    workflow_id = input_data.get("workflow_id", None)
    
    logs = []
    workflow_logs = []
    speech_parts = []
    
    # Get workflow logs if requested
    if log_type in ["workflows", "all"]:
        workflow_logs = get_workflow_logs(limit=limit, workflow_id=workflow_id)
        if workflow_logs:
            success_count = sum(1 for w in workflow_logs if w.get('result', {}).get('ok', False))
            fail_count = len(workflow_logs) - success_count
            speech_parts.append(f"{len(workflow_logs)} workflow executions ({success_count} ok, {fail_count} failed)")
    
    # Get tool logs if requested
    if log_type in ["tools", "all"]:
        logger = ToolLogger()
        if tool_name:
            logs = logger.get_logs_by_tool(tool_name, limit)
            speech_parts.append(f"{len(logs)} calls to {tool_name}")
        else:
            logs = logger.get_recent_logs(limit)
            speech_parts.append(f"{len(logs)} tool calls")
    
    # Handle case where no logs found
    if not logs and not workflow_logs:
        return_success(
            speech="No logs found.",
            data={"logs": [], "workflow_logs": []}
        )
        return 0
    
    # Build speech summary for tool logs
    log_summaries = []
    for log in logs:
        status = "succeeded" if log["result"]["ok"] else "failed"
        tool = log["tool"]
        duration = log["duration_ms"]
        
        summary = f"{tool} {status} in {duration:.0f}ms"
        if log.get("fallback_embeddings"):
            summary += " - fallback embeddings used"
        proxy = log.get("proxy")
        if isinstance(proxy, dict):
            if proxy.get("used") is True:
                summary += f" - proxy {proxy.get('slot', 'configured')}"
            elif proxy.get("used") is False:
                reason = proxy.get("direct_reason")
                summary += f" - no proxy{f' ({reason})' if reason else ''}"
            else:
                summary += " - proxy use unknown"
        
        if not log["result"]["ok"]:
            error = log["result"].get("error", "unknown error")
            summary += f" - Error: {error}"
        
        log_summaries.append(summary)
    
    # Build speech summary for workflow logs
    workflow_summaries = []
    for wf in workflow_logs:
        result = wf.get('result', {})
        status = "succeeded" if result.get('ok', False) else "failed"
        wf_id = wf.get('workflow_id', 'unknown')
        duration = wf.get('duration_ms', 0)
        steps = result.get('steps_completed', 0)
        
        summary = f"{wf_id} {status} ({steps} steps, {duration:.0f}ms)"
        workflow_summaries.append(summary)
    
    # Build final speech
    speech = f"Found: {', '.join(speech_parts)}. "
    if log_summaries:
        speech += "Tools: " + "; ".join(log_summaries[:3]) + ". "
    if workflow_summaries:
        speech += "Workflows: " + "; ".join(workflow_summaries[:3]) + "."
    
    # Return detailed logs in data
    simplified_logs = []
    for log in logs:
        simplified_logs.append({
            "timestamp": log["timestamp"],
            "tool": log["tool"],
            "arguments": log["arguments"],
            "fallback_embeddings": log.get("fallback_embeddings"),
            "proxy": log.get("proxy"),
            "ok": log["result"]["ok"],
            "speech": log["result"]["speech"],
            "error": log["result"].get("error"),
            "duration_ms": log["duration_ms"]
        })
    
    # Simplified workflow logs
    simplified_workflows = []
    for wf in workflow_logs:
        result = wf.get('result', {})
        simplified_workflows.append({
            "timestamp": wf.get("timestamp"),
            "workflow_id": wf.get("workflow_id"),
            "workflow_name": wf.get("workflow_name"),
            "user_query": wf.get("user_query"),
            "ok": result.get("ok", False),
            "speech": result.get("speech", ""),
            "steps_completed": result.get("steps_completed", 0),
            "tools_used": result.get("tools_used", []),
            "duration_ms": wf.get("duration_ms", 0)
        })
    
    return_success(
        speech=speech,
        data={
            "logs": simplified_logs,
            "workflow_logs": simplified_workflows
        }
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
