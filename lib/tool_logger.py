#!/usr/bin/env python3
"""
Tool Call Logger
Tracks all tool executions for debugging and auditing.
"""
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class ToolLogger:
    """Logger for tool executions."""
    
    def __init__(self, log_dir: str = None):
        """
        Initialize tool logger.
        
        Args:
            log_dir: Directory for log files (default: PROJECT_ROOT/logs/tools)
        """
        if log_dir is None:
            # Default to project root logs/tools
            project_root = Path(__file__).parent.parent.resolve()
            log_dir = project_root / "logs" / "tools"
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Current log file (daily rotation)
        today = datetime.now().strftime("%Y-%m-%d")
        self.log_file = self.log_dir / f"tool-calls-{today}.jsonl"
    
    def log_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Dict[str, Any],
        duration_ms: float,
        user_query: Optional[str] = None,
        mode: str = "cloud"
    ):
        """
        Log a tool execution.
        
        Args:
            tool_name: Name of the tool executed
            arguments: Arguments passed to the tool
            result: Result returned by the tool
            duration_ms: Execution time in milliseconds
            user_query: Original user query (if available)
            mode: cloud or local
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "tool": tool_name,
            "arguments": arguments,
            "result": {
                "ok": result.get("ok", False),
                "speech": result.get("speech", ""),
                "has_data": "data" in result,
                "error": result.get("error", None)
            },
            "duration_ms": round(duration_ms, 2),
            "user_query": user_query
        }
        
        # Write as JSON lines (one JSON object per line)
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def get_recent_logs(self, limit: int = 10) -> list:
        """Get recent tool calls."""
        if not self.log_file.exists():
            return []
        
        logs = []
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))
        
        # Return most recent first
        return logs[-limit:][::-1]
    
    def get_logs_by_tool(self, tool_name: str, limit: int = 10) -> list:
        """Get recent calls to a specific tool."""
        if not self.log_file.exists():
            return []
        
        logs = []
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("tool") == tool_name:
                        logs.append(entry)
        
        return logs[-limit:][::-1]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about tool usage."""
        if not self.log_file.exists():
            return {"total_calls": 0, "tools": {}}
        
        stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "tools": {},
            "avg_duration_ms": 0
        }
        
        total_duration = 0
        
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    stats["total_calls"] += 1
                    
                    if entry["result"]["ok"]:
                        stats["successful_calls"] += 1
                    else:
                        stats["failed_calls"] += 1
                    
                    tool = entry["tool"]
                    if tool not in stats["tools"]:
                        stats["tools"][tool] = {
                            "count": 0,
                            "success": 0,
                            "failed": 0
                        }
                    
                    stats["tools"][tool]["count"] += 1
                    if entry["result"]["ok"]:
                        stats["tools"][tool]["success"] += 1
                    else:
                        stats["tools"][tool]["failed"] += 1
                    
                    total_duration += entry.get("duration_ms", 0)
        
        if stats["total_calls"] > 0:
            stats["avg_duration_ms"] = round(total_duration / stats["total_calls"], 2)
        
        return stats


def get_logger(mode: str = "cloud") -> ToolLogger:
    """Get a tool logger instance."""
    return ToolLogger()

