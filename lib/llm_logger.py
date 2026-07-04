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
        routing_provenance: dict[str, Any] | None = None,
        error: str | None = None,
        call_metadata: dict[str, Any] | None = None,
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
        provider_route = (routing_provenance or {}).get("provider_route", {}) if routing_provenance else {}
        usage_info = usage_info or {}

        def usage_value(*keys: str) -> Any:
            for key in keys:
                value = usage_info.get(key)
                if value is not None:
                    return value
            return None

        cached_input_tokens = usage_value(
            "cached_input_tokens",
            "cached_prompt_text_tokens",
            "cache_read_tokens",
        )
        server_side_tools = usage_info.get("server_side_tools") or {}
        is_xai = provider == "xai"
        is_openai = provider == "openai"

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "provider": provider,
            "model": model,
            "prompt_type": prompt_type,
            "user_query": user_query,
            "messages_count": len(messages),
            "routing_provenance": routing_provenance,
            "call_metadata": call_metadata,
            
            # Flatten usage fields for easier Loki/Grafana querying
            "input_tokens": usage_value("input_tokens"),
            "output_tokens": usage_value("output_tokens"),
            "total_tokens": usage_value("total_tokens"),
            "cost_usd": usage_value("cost_usd"),
            "prompt_text_tokens": usage_value("prompt_text_tokens"),
            "cached_input_tokens": cached_input_tokens,
            "cached_prompt_text_tokens": usage_value("cached_prompt_text_tokens", "cached_input_tokens"),
            "cache_creation_tokens": usage_value("cache_creation_tokens"),
            "cache_creation_5m_tokens": usage_value("cache_creation_5m_tokens"),
            "cache_creation_1h_tokens": usage_value("cache_creation_1h_tokens"),
            "cache_read_tokens": usage_value("cache_read_tokens"),
            "cache_write_cost_usd": usage_value("cache_write_cost_usd"),
            "cache_read_cost_usd": usage_value("cache_read_cost_usd"),
            "cache_cost_usd": usage_value("cache_cost_usd"),
            "reasoning_tokens": usage_value("reasoning_tokens"),
            "provider_continuation_mode": provider_route.get("provider_continuation_mode"),
            "provider_continuation_fallback_reason": provider_route.get("provider_continuation_fallback_reason"),
            "provider_previous_response_id_present": provider_route.get("provider_previous_response_id_present"),
            "provider_previous_response_id_used": provider_route.get("provider_previous_response_id_used"),
            "provider_messages_shape": provider_route.get("provider_messages_shape"),
            
            "response": {
                "type": "tool_call" if tool_call else ("text" if response_text else "error"),
                "text_preview": response_text[:400] if response_text else None,
                "tool_name": tool_call.get("name") if tool_call else None,
                "has_thinking": thinking is not None
            },
            "duration_ms": round(duration_ms, 2),
            "success": error is None,
            "error": error
        }

        if is_xai:
            log_entry.update({
                "xai_prompt_text_tokens": usage_value("prompt_text_tokens"),
                "xai_cached_prompt_text_tokens": usage_value("cached_prompt_text_tokens"),
                "xai_reasoning_effort": usage_value("xai_reasoning_effort"),
                "xai_continuation_mode": provider_route.get("xai_continuation_mode"),
                "xai_continuation_fallback_reason": provider_route.get("xai_continuation_fallback_reason"),
                "xai_previous_response_id_present": provider_route.get("xai_previous_response_id_present"),
                "xai_previous_response_id_used": provider_route.get("xai_previous_response_id_used"),
                "xai_search_calls": sum(server_side_tools.values()),
                "xai_search_tools": list(server_side_tools.keys()) if server_side_tools else None,
            })

        if is_openai:
            log_entry.update({
                "openai_cached_input_tokens": cached_input_tokens,
                "openai_cache_read_tokens": usage_value("cache_read_tokens"),
                "openai_cache_hit": usage_value("cache_hit"),
                "openai_responses_continuation_payload_items": provider_route.get(
                    "openai_responses_continuation_payload_items",
                ),
                "openai_responses_continuation_mode": provider_route.get(
                    "openai_responses_continuation_mode",
                ),
                "openai_responses_continuation_fallback_reason": provider_route.get(
                    "openai_responses_continuation_fallback_reason",
                ),
                "openai_api_mode": provider_route.get("openai_api_mode"),
                "openai_responses_tools_enabled": provider_route.get("openai_responses_tools_enabled"),
                "openai_responses_previous_id_present": provider_route.get(
                    "openai_responses_previous_id_present",
                ),
                "openai_responses_previous_id_used": provider_route.get(
                    "openai_responses_previous_id_used",
                ),
                "openai_responses_continuation_input_items": provider_route.get(
                    "openai_responses_continuation_input_items",
                ),
                "openai_responses_output_items_by_type": provider_route.get(
                    "openai_responses_output_items_by_type",
                ),
                "openai_responses_fallback_reason": provider_route.get("openai_responses_fallback_reason"),
                "openai_prompt_cache_key_set": provider_route.get("openai_prompt_cache_key_set"),
                "openai_prompt_cache_retention": provider_route.get("openai_prompt_cache_retention"),
                "openai_server_side_tool_calls": sum(server_side_tools.values()),
                "openai_server_side_tools": list(server_side_tools.keys()) if server_side_tools else None,
            })

        if routing_provenance:
            auto_context = routing_provenance.get("auto_context", {})
            memory = routing_provenance.get("memory_injection", {})
            learning = routing_provenance.get("learning_insights", {})
            log_entry["auto_context_applied"] = bool(auto_context.get("applied"))
            log_entry["memory_injected"] = bool(memory.get("injected"))
            log_entry["memory_candidate_count"] = int(memory.get("candidate_count") or 0)
            log_entry["memory_injected_count"] = int(memory.get("injected_count") or 0)
            log_entry["learning_insights_injected"] = bool(learning.get("injected"))
            log_entry["learning_insight_count"] = int(learning.get("insight_count") or 0)
        
        # Write as JSON lines (one JSON object per line)
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        # Also log server-side tools to dedicated file if any were used
        if usage_info and usage_info.get("server_side_tools"):
            self._log_server_side_tools(
                provider=provider,
                model=model,
                tools=usage_info["server_side_tools"],
                context=prompt_type,
                user_query=user_query,
                mode=mode
            )
    
    def _log_server_side_tools(
        self,
        provider: str,
        model: str,
        tools: dict[str, int],
        context: str = None,
        user_query: str = None,
        mode: str = "cloud"
    ):
        """
        Log server-side tool usage to dedicated log file.
        
        This tracks xAI (web_search, x_search), Anthropic (web search, code execution), etc.
        Useful for cost monitoring since these often have additional charges.
        """
        # Use dedicated subfolder for server-side tools
        server_tools_dir = self.log_dir / "server-side-tools"
        server_tools_dir.mkdir(parents=True, exist_ok=True)
        
        today = datetime.now().strftime("%Y-%m-%d")
        server_tools_log = server_tools_dir / f"server-tools-{today}.jsonl"
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "provider": provider,
            "model": model,
            "context": context,  # e.g., "chat", "routing", "workflow_param_fill"
            "user_query_preview": user_query[:1000] if user_query else None,
            "user_query_chars": len(user_query) if user_query else 0,
            "tools": tools,  # e.g., {"SERVER_SIDE_TOOL_X_SEARCH": 2, "SERVER_SIDE_TOOL_WEB_SEARCH": 1}
            "total_calls": sum(tools.values())
        }
        
        with open(server_tools_log, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def log_server_side_tools(
        self,
        provider: str,
        model: str,
        tools: dict[str, int],
        context: str = None,
        user_query: str = None,
        mode: str = "cloud"
    ):
        """
        Public method to log server-side tool usage.
        
        Call this from orchestrator/pipeline_executor when tracking server-side tools
        that may not go through the normal LLM logging path.
        """
        if tools:
            self._log_server_side_tools(provider, model, tools, context, user_query, mode)
    
    def get_server_side_tools_summary(self, days: int = 1) -> dict:
        """
        Get summary of server-side tool usage.
        
        Returns:
            Dict with tool counts, total calls, and breakdown by provider.
        """
        from datetime import timedelta
        
        summary = {
            "total_calls": 0,
            "by_tool": {},
            "by_provider": {},
            "entries": []
        }
        
        # Check log files for the specified number of days
        server_tools_dir = self.log_dir / "server-side-tools"
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            log_file = server_tools_dir / f"server-tools-{date}.jsonl"
            
            if log_file.exists():
                with open(log_file, 'r') as f:
                    for line in f:
                        if line.strip():
                            entry = json.loads(line)
                            summary["entries"].append(entry)
                            
                            # Aggregate by tool
                            for tool, count in entry.get("tools", {}).items():
                                clean_name = tool.replace("SERVER_SIDE_TOOL_", "").lower()
                                summary["by_tool"][clean_name] = summary["by_tool"].get(clean_name, 0) + count
                                summary["total_calls"] += count
                            
                            # Aggregate by provider
                            provider = entry.get("provider", "unknown")
                            provider_count = sum(entry.get("tools", {}).values())
                            summary["by_provider"][provider] = summary["by_provider"].get(provider, 0) + provider_count
        
        return summary
    
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
