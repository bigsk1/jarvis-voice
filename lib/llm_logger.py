#!/usr/bin/env python3
"""
LLM Call Logger
Tracks all LLM API calls for cost monitoring, debugging, and performance analysis.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any


class LLMLogger:
    """Logger for LLM API calls."""
    
    def __init__(self, log_dir: str = None):
        """
        Initialize LLM logger.
        
        Args:
            log_dir: Directory for log files (default: PROJECT_ROOT/logs)
        """
        if log_dir is None:
            # Default to project root logs directory
            project_root = Path(__file__).parent.parent.resolve()
            log_dir = project_root / "logs"
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Current log file (daily rotation)
        today = datetime.now().strftime("%Y-%m-%d")
        self.log_file = self.log_dir / f"llm-calls-{today}.jsonl"
    
    def log_llm_call(
        self,
        provider: str,
        model: str,
        prompt_type: str,  # "routing", "chat", "tool_selection", etc.
        messages: list[dict[str, str]],
        response_text: str | None,
        tool_call: dict[str, Any] | None,
        usage_info: dict[str, Any] | None,
        thinking: str | None,
        duration_ms: float,
        mode: str = "cloud",
        user_query: str | None = None,
        error: str | None = None
    ):
        """
        Log an LLM API call.
        
        Args:
            provider: LLM provider (openai, anthropic, xai, ollama)
            model: Model name (gpt-4, claude-sonnet-4-5, etc.)
            prompt_type: Type of prompt (routing, chat, tool_selection, etc.)
            messages: Messages sent to LLM
            response_text: Text response from LLM (if any)
            tool_call: Tool call from LLM (if any)
            usage_info: Token usage and cost info
            thinking: Extended thinking/reasoning (if available)
            duration_ms: Response time in milliseconds
            mode: cloud or local
            user_query: Original user query (if available)
            error: Error message (if call failed)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "provider": provider,
            "model": model,
            "prompt_type": prompt_type,
            "user_query": user_query,
            "messages_count": len(messages),
            
            # Flatten usage fields for easier Loki/Grafana querying
            "input_tokens": usage_info.get("input_tokens") if usage_info else None,
            "output_tokens": usage_info.get("output_tokens") if usage_info else None,
            "total_tokens": usage_info.get("total_tokens") if usage_info else None,
            "cost_usd": usage_info.get("cost_usd") if usage_info else None,
            
            # xAI native search usage (web_search, x_search)
            "xai_search_calls": sum(usage_info.get("server_side_tools", {}).values()) if usage_info else 0,
            "xai_search_tools": list(usage_info.get("server_side_tools", {}).keys()) if usage_info and usage_info.get("server_side_tools") else None,
            
            "response": {
                "type": "tool_call" if tool_call else ("text" if response_text else "error"),
                "text_preview": response_text[:200] if response_text else None,
                "tool_name": tool_call.get("name") if tool_call else None,
                "has_thinking": thinking is not None
            },
            "duration_ms": round(duration_ms, 2),
            "success": error is None,
            "error": error
        }
        
        # Write as JSON lines (one JSON object per line)
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def get_recent_logs(self, limit: int = 10) -> list:
        """Get recent LLM calls."""
        if not self.log_file.exists():
            return []
        
        logs = []
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))
        
        # Return most recent first
        return logs[-limit:][::-1]
    
    def get_logs_by_provider(self, provider: str, limit: int = 10) -> list:
        """Get recent calls to a specific provider."""
        if not self.log_file.exists():
            return []
        
        logs = []
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("provider") == provider:
                        logs.append(entry)
        
        return logs[-limit:][::-1]
    
    def get_logs_by_model(self, model: str, limit: int = 10) -> list:
        """Get recent calls to a specific model."""
        if not self.log_file.exists():
            return []
        
        logs = []
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("model") == model:
                        logs.append(entry)
        
        return logs[-limit:][::-1]
    
    def get_stats(self) -> dict[str, Any]:
        """Get statistics about LLM usage."""
        if not self.log_file.exists():
            return {
                "total_calls": 0,
                "providers": {},
                "models": {},
                "total_tokens": 0,
                "total_cost_usd": 0.0
            }
        
        stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "providers": {},
            "models": {},
            "prompt_types": {},
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_response_time_ms": 0
        }
        
        total_duration = 0
        
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    stats["total_calls"] += 1
                    
                    if entry.get("success", False):
                        stats["successful_calls"] += 1
                    else:
                        stats["failed_calls"] += 1
                    
                    # Provider stats
                    provider = entry.get("provider", "unknown")
                    if provider not in stats["providers"]:
                        stats["providers"][provider] = {
                            "count": 0,
                            "tokens": 0,
                            "cost_usd": 0.0
                        }
                    stats["providers"][provider]["count"] += 1
                    
                    # Model stats
                    model = entry.get("model", "unknown")
                    if model not in stats["models"]:
                        stats["models"][model] = {
                            "count": 0,
                            "tokens": 0,
                            "cost_usd": 0.0,
                            "avg_response_time_ms": 0
                        }
                    stats["models"][model]["count"] += 1
                    
                    # Prompt type stats
                    prompt_type = entry.get("prompt_type", "unknown")
                    if prompt_type not in stats["prompt_types"]:
                        stats["prompt_types"][prompt_type] = {"count": 0}
                    stats["prompt_types"][prompt_type]["count"] += 1
                    
                    # Token and cost tracking
                    usage = entry.get("usage", {})
                    if usage:
                        tokens = usage.get("total_tokens", 0)
                        cost = usage.get("cost_usd", 0.0)
                        
                        if tokens:
                            stats["total_tokens"] += tokens
                            stats["providers"][provider]["tokens"] += tokens
                            stats["models"][model]["tokens"] += tokens
                        
                        if cost:
                            stats["total_cost_usd"] += cost
                            stats["providers"][provider]["cost_usd"] += cost
                            stats["models"][model]["cost_usd"] += cost
                    
                    # Response time tracking
                    duration = entry.get("duration_ms", 0)
                    total_duration += duration
                    stats["models"][model]["avg_response_time_ms"] += duration
        
        # Calculate averages
        if stats["total_calls"] > 0:
            stats["avg_response_time_ms"] = round(total_duration / stats["total_calls"], 2)
        
        for model, model_stats in stats["models"].items():
            if model_stats["count"] > 0:
                model_stats["avg_response_time_ms"] = round(
                    model_stats["avg_response_time_ms"] / model_stats["count"], 2
                )
        
        # Round costs
        stats["total_cost_usd"] = round(stats["total_cost_usd"], 4)
        for provider in stats["providers"].values():
            provider["cost_usd"] = round(provider["cost_usd"], 4)
        for model in stats["models"].values():
            model["cost_usd"] = round(model["cost_usd"], 4)
        
        return stats


def get_logger(mode: str = "cloud") -> LLMLogger:
    """Get an LLM logger instance."""
    return LLMLogger()

