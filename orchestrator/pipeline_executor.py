#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Pipeline Executor

Executes workflow pipelines step-by-step, bypassing the normal LLM routing.
The LLM is only used for parameter filling and content validation, not tool selection.

This provides deterministic multi-tool execution while still leveraging LLM intelligence
for flexible parameter resolution.
"""
import os
import sys
import json
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from collections.abc import Callable
from datetime import datetime

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from llm_provider import create_configured_provider
from tool_logger import ToolLogger
from llm_logger import LLMLogger
from workflow_availability import (
    check_workflow_registry_availability,
    workflow_unavailable_message,
)


class PipelineExecutor:
    """Execute workflow pipelines step-by-step."""
    
    def __init__(self, mode: str, executor, provider=None):
        """
        Initialize pipeline executor.
        
        Args:
            mode: 'cloud' or 'local'
            executor: ToolExecutor instance (reused for individual tool calls)
            provider: Optional LLM provider for parameter filling and validation
        """
        self.mode = mode
        self.executor = executor
        load_config(mode)
        self.provider = provider or self._create_provider()
        self.logger = ToolLogger()
        self.llm_logger = LLMLogger()
        self._disable_server_side_tools = False
        self._server_side_tools = {}
        
        # Track cumulative token usage for this workflow execution
        self._total_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "model_calls": 0,
            "peak_context_tokens": 0,
            "cost_usd": 0.0,
            "has_unknown_cost": False,
            "cost_known": True,
            "billing_mode": None,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_cost_usd": 0.0,
            "cache_read_cost_usd": 0.0,
            "cache_cost_usd": 0.0,
            "cache_savings_usd": 0.0,
        }
    
    @contextmanager
    def _workflow_llm_tool_scope(self):
        """Temporarily suppress provider-native tools for workflow LLM helper calls."""
        if not self._disable_server_side_tools:
            yield
            return

        env_overrides = {
            "XAI_DISABLE_SERVER_SIDE_TOOLS": "true",
            "OPENAI_RESPONSES_DISABLE_SERVER_SIDE_TOOLS": "true",
            "JARVIS_OVERRIDE_XAI_SEARCH": "false",
            "JARVIS_OVERRIDE_ANTHROPIC_SEARCH": "false",
        }
        previous_env = {key: os.environ.get(key) for key in env_overrides}
        previous_enable_search = None
        provider = self.provider

        if provider is not None and hasattr(provider, "enable_search"):
            previous_enable_search = getattr(provider, "enable_search")
            setattr(provider, "enable_search", False)

        try:
            for key, value in env_overrides.items():
                os.environ[key] = value
            yield
        finally:
            if provider is not None and previous_enable_search is not None:
                setattr(provider, "enable_search", previous_enable_search)
            for key, previous in previous_env.items():
                if previous is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = previous

    def _chat_with_usage(self, message: str, system_prompt: str = None, max_tokens: int = 1024) -> str:
        """
        Chat with the LLM and track token usage.
        Uses chat_with_tools() with empty tools to get usage data.
        """
        if not self.provider:
            return ""
        
        try:
            # Use chat_with_tools with empty tool list to get usage info
            messages = [{"role": "user", "content": message}]
            with self._workflow_llm_tool_scope():
                text, _, usage_info, _ = self.provider.chat_with_tools(
                    messages=messages,
                    tools=[],  # No Jarvis tools; workflow may also disable provider-native tools.
                    system_prompt=system_prompt
                )
            
            # Accumulate usage
            if usage_info:
                call_tokens = usage_info.get("total_tokens")
                if not isinstance(call_tokens, (int, float)):
                    call_tokens = (
                        (usage_info.get("input_tokens") or 0)
                        + (usage_info.get("output_tokens") or 0)
                    )
                self._total_usage["model_calls"] += 1
                self._total_usage["peak_context_tokens"] = max(
                    self._total_usage["peak_context_tokens"], call_tokens
                )
                self._total_usage["input_tokens"] += usage_info.get("input_tokens", 0)
                self._total_usage["output_tokens"] += usage_info.get("output_tokens", 0)
                self._total_usage["total_tokens"] += usage_info.get("total_tokens", 0)
                cost = usage_info.get("cost_usd")
                if isinstance(cost, (int, float)):
                    self._total_usage["cost_usd"] += cost
                if (
                    usage_info.get("cost_known") is False
                    or usage_info.get("billing_mode") in {
                        "ollama_cloud_subscription",
                        "xai_oauth_subscription",
                    }
                    or cost is None
                ):
                    self._total_usage["has_unknown_cost"] = True
                    self._total_usage["cost_known"] = False
                if usage_info.get("billing_mode"):
                    self._total_usage["billing_mode"] = usage_info["billing_mode"]
                for key in (
                    "cache_creation_tokens",
                    "cache_read_tokens",
                    "cache_write_cost_usd",
                    "cache_read_cost_usd",
                    "cache_cost_usd",
                    "cache_savings_usd",
                ):
                    value = usage_info.get(key)
                    if isinstance(value, (int, float)):
                        self._total_usage[key] += value
                
                # Track provider-native/server-side tools.
                if usage_info.get("server_side_tools"):
                    for tool_name, count in usage_info["server_side_tools"].items():
                        self._server_side_tools[tool_name] = self._server_side_tools.get(tool_name, 0) + count
            
            return text or ""
        except Exception as e:
            # Fallback to regular chat if chat_with_tools fails
            print(f"Warning: chat_with_usage failed, falling back: {e}", file=sys.stderr)
            if not self.provider:
                return ""
            with self._workflow_llm_tool_scope():
                return self.provider.chat(message, system_prompt, max_tokens)
    
    def _generate_short_title(self, query: str) -> str | None:
        """
        Use LLM to generate a concise title (5-8 words) from a raw user query.
        Falls back to None if the LLM call fails so the caller can use a fallback.
        """
        system_prompt = (
            "Generate a brief title (5-8 words max) for this research query. "
            "Reply with ONLY the title text, no quotes, no punctuation at the end, no explanation."
        )
        try:
            result = self._chat_with_usage(query, system_prompt=system_prompt, max_tokens=60)
            if result and result.strip():
                # Strip surrounding quotes and trailing punctuation
                title = result.strip().strip('"\'').rstrip('.')
                # Sanity check: if the LLM returned something too long or empty, reject it
                if 2 < len(title) < 120:
                    return title
            return None
        except Exception as e:
            print(f"Warning: short title generation failed: {e}", file=sys.stderr)
            return None
    
    def _create_provider(self):
        """Create LLM provider for parameter filling and validation."""
        try:
            _, _, provider = create_configured_provider(
                default_provider="openai" if self.mode == "cloud" else "ollama",
                mode=self.mode,
            )
            return provider
        except Exception as e:
            print(f"Warning: Could not create LLM provider: {e}", file=sys.stderr)
            return None
    
    def execute(self, workflow: dict, query: str, 
                status_callback: Callable[[str], None] = None) -> dict[str, Any]:
        """
        Execute a workflow pipeline.
        
        Args:
            workflow: Workflow definition dict
            query: Original user query
            status_callback: Optional callback for status updates (e.g., "Step 2: crawl_url")
        
        Note: Token usage is tracked across all LLM calls (parameter filling, validation)
              and returned in the response['usage'] field.
        
        Returns:
            Same format as Orchestrator.process() for compatibility:
            {
                "ok": True/False,
                "speech": "Text to speak",
                "data": {...},
                "tools_used": [...]
            }
        """
        registry = getattr(self.executor, "registry", None)
        if registry is not None:
            availability = check_workflow_registry_availability(
                workflow,
                registry,
                excluded_tools=getattr(self.executor, "excluded_tools", set()),
            )
            if not availability["available"]:
                message = workflow_unavailable_message(workflow, availability)
                return {
                    "ok": False,
                    "speech": message,
                    "error": message,
                    "data": {
                        "workflow_id": workflow.get("id"),
                        "availability": availability,
                        "results": [],
                    },
                    "tools_used": [],
                    "steps_completed": 0,
                }

        # Reset usage tracking for this workflow
        self._total_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "model_calls": 0,
            "peak_context_tokens": 0,
            "cost_usd": 0.0,
            "has_unknown_cost": False,
            "cost_known": True,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_cost_usd": 0.0,
            "cache_read_cost_usd": 0.0,
            "cache_cost_usd": 0.0,
            "cache_savings_usd": 0.0,
        }
        
        # Track server-side tool usage from LLM providers (xAI web_search, x_search, etc.)
        self._server_side_tools = {}
        
        workflow_id = workflow.get("id", "unknown")
        workflow_name = workflow.get("name", workflow_id)
        steps = workflow.get("steps", [])
        tool_defaults = workflow.get("tool_defaults", {})
        validation_policy = workflow.get("validation_policy", {})
        self._disable_server_side_tools = bool(workflow.get("disable_server_side_tools", False))
        
        # Track execution time
        start_time = time.time()
        
        # Initialize execution state
        topic = self._extract_topic(query, workflow)
        variables = self._extract_workflow_variables(query, workflow, topic)
        
        # Store workflow context for logging
        self._current_workflow_id = workflow_id
        
        results = []
        tools_used = []
        total_retries = 0
        max_total_retries = validation_policy.get("max_total_retries", 10)
        
        if status_callback:
            status_callback(f"Starting workflow: {workflow_name}")
        
        # Execute each step
        for step in steps:
            step_num = step.get("step", len(results) + 1)
            tool_name = step["tool"]
            action = step.get("action")
            description = step.get("description", f"{tool_name}")
            step_start_time = time.time()
            
            if status_callback:
                status_callback(f"Step {step_num}: {description}")
            
            # Check condition (if specified)
            should_execute, skip_reason = self._should_execute_step(step, variables)
            if not should_execute:
                self._apply_variable_assignments(step.get("set_variables_on_skip"), variables)
                results.append({
                    "step": step_num,
                    "tool": tool_name,
                    "skipped": True,
                    "reason": skip_reason or "Condition evaluated to false"
                })
                continue
            
            # Handle for_each loops
            if "for_each" in step:
                step_result = self._execute_for_each(
                    step, tool_name, action, tool_defaults, 
                    variables, validation_policy, total_retries, max_total_retries
                )
                step_duration_ms = int((time.time() - step_start_time) * 1000)
                
                if step_result.get("abort"):
                    # Workflow abort requested
                    return self._build_abort_response(workflow, step, results, variables,
                                                      start_time=start_time, query=query)
                
                total_retries += step_result.get("retries", 0)
                variables[step.get("output_var", f"step{step_num}_results")] = step_result.get("outputs", [])
                
                # Store validated outputs only when the workflow explicitly names
                # their semantic variable. Keep a crawl-only fallback for older
                # custom workflows, but never let later stash/save loops overwrite
                # the source articles used by synthesis steps.
                self._store_validated_outputs(step, tool_name, step_result, variables)
                
                results.append({
                    "step": step_num,
                    "tool": tool_name,
                    "items_processed": step_result.get("items_processed", 0),
                    "items_succeeded": step_result.get("items_succeeded", 0),
                    "outputs": step_result.get("outputs", []),
                    "duration_ms": step_duration_ms
                })
                tools_used.append(tool_name)
            else:
                # Single execution
                step_result = self._execute_single(
                    step, tool_name, action, tool_defaults,
                    variables, validation_policy
                )
                step_duration_ms = int((time.time() - step_start_time) * 1000)
                
                if not step_result.get("ok") and step.get("required", True):
                    # Required step failed - abort by default unless explicitly told to continue
                    if step.get("on_fail") != "continue":
                        # Include the failed step in results before aborting
                        results.append({
                            "step": step_num,
                            "tool": tool_name,
                            "ok": False,
                            "data": step_result.get("data"),
                            "error": step_result.get("error") or step_result.get("speech"),
                            "duration_ms": step_duration_ms
                        })
                        return self._build_abort_response(workflow, step, results, variables,
                                                          start_time=start_time, query=query,
                                                          step_error=step_result.get("error") or step_result.get("speech"))
                
                # Apply output transformations defined in the step
                self._apply_output_transforms(step, step_result, variables, tool_name, action)

                # Store output after transforms because search recovery can flip
                # ok=True when a failed tool response still contains usable URLs.
                output_var = step.get("output_var")
                if output_var and step_result.get("ok"):
                    # Built-in transforms may populate output_var with a
                    # workflow-friendly shape, e.g. search_results.urls or
                    # article.content. Preserve that instead of replacing it
                    # with the raw tool payload.
                    if output_var not in variables:
                        variables[output_var] = step_result.get("data", {})
                    self._apply_variable_assignments(step.get("set_variables_on_success"), variables)
                
                results.append({
                    "step": step_num,
                    "tool": tool_name,
                    "ok": step_result.get("ok", False),
                    "data": step_result.get("data"),
                    "error": step_result.get("error"),
                    "speech": step_result.get("speech"),
                    "duration_ms": step_duration_ms
                })
                tools_used.append(tool_name)
        
        # Build final response and log workflow execution
        return self._build_success_response(workflow, results, variables, tools_used, 
                                            start_time=start_time, query=query)
    
    def _execute_single(self, step: dict, tool_name: str, action: str,
                        tool_defaults: dict, variables: dict,
                        validation_policy: dict) -> dict[str, Any]:
        """Execute a single step (not for_each)."""
        
        # Resolve parameters
        params = self._resolve_params(step, tool_defaults.get(tool_name, {}), variables)
        
        # Add action if specified
        if action:
            params["action"] = action
        
        # LLM parameter filling if needed
        if step.get("llm_prompt") and self.provider:
            llm_params = self._llm_fill_params(step, variables)
            llm_output_error = self._validate_llm_filled_params(step, llm_params)
            if llm_output_error:
                return {
                    "ok": False,
                    "error": llm_output_error,
                    "speech": llm_output_error,
                }
            params.update(llm_params)
        
        # Execute tool
        result = self.executor.execute(tool_name, params)
        
        # Validate if needed
        if step.get("validation") and result.get("ok"):
            if not self._validate_result(result, step, variables):
                result["ok"] = False
                result["validation_failed"] = True
        
        return result

    def _validate_llm_filled_params(self, step: dict, llm_params: dict) -> str | None:
        """Validate generated tool parameters when a workflow explicitly opts in."""
        validation = step.get("llm_output_validation")
        if not validation:
            return None

        param_name = validation.get("param", "content")
        content = str(llm_params.get(param_name, "") or "").strip()
        min_length = int(validation.get("min_length", 0) or 0)
        if len(content) < min_length:
            return f"LLM-generated {param_name} was empty or too short"

        content_lower = content.lower()
        for pattern in validation.get("reject_patterns", []):
            if str(pattern).lower() in content_lower:
                return f"LLM-generated {param_name} contained refusal or placeholder content"
        for pattern in validation.get("required_patterns", []):
            if str(pattern).lower() not in content_lower:
                return f"LLM-generated {param_name} was missing required structure"
        return None

    def _store_validated_outputs(
        self,
        step: dict,
        tool_name: str,
        step_result: dict,
        variables: dict,
    ) -> None:
        """Store validated loop outputs without allowing later save steps to replace sources."""
        validated_outputs = step_result.get("validated_outputs")

        validated_output_var = step.get("validated_output_var")
        if validated_output_var:
            variables[validated_output_var] = validated_outputs or []
            return

        if not validated_outputs:
            return

        if tool_name == "crawl_url":
            # Backward compatibility for custom crawl workflows created before
            # validated_output_var became explicit.
            variables["validated_articles"] = validated_outputs
    
    def _execute_for_each(self, step: dict, tool_name: str, action: str,
                          tool_defaults: dict, variables: dict,
                          validation_policy: dict,
                          current_retries: int, max_retries: int) -> dict[str, Any]:
        """Execute a for_each step with retry logic."""
        
        # Get items to iterate
        for_each_expr = step["for_each"]
        items = self._resolve_variable(for_each_expr, variables)
        if items is None:
            items = []
        
        if not items:
            required_success = (
                len(items)
                if step.get("process_all", False)
                else step.get("required_success_count", 1)
            )
            validated_outputs = []
            abort = (
                len(validated_outputs) < required_success
                and step.get("on_all_fail") == "abort_with_message"
            )
            return {
                "items_processed": 0,
                "items_succeeded": 0,
                "outputs": [],
                "validated_outputs": validated_outputs,
                "retries": 0,
                "abort": abort,
            }
        
        outputs = []
        validated_outputs = []
        retries = 0
        required_success = (
            len(items)
            if step.get("process_all", False)
            else step.get("required_success_count", 1)
        )
        configured_max_attempts = step.get("retry", {}).get("max_attempts")
        step_max_attempts = (
            max(1, int(configured_max_attempts))
            if configured_max_attempts is not None
            else len(items)
        )
        
        item_index = 0
        while (
            item_index < len(items)
            and item_index < step_max_attempts
            and len(validated_outputs) < required_success
        ):
            if current_retries + retries >= max_retries:
                break
            
            item = items[item_index]
            
            # Store loop index for LLM param generation
            variables["_loop_index"] = item_index
            
            # Resolve parameters for this item
            params = self._resolve_params(step, tool_defaults.get(tool_name, {}), variables)
            
            # Add action if specified
            if action:
                params["action"] = action
            
            # Add item-specific params based on tool type
            if isinstance(item, str):
                # Assume it's a URL for crawl_url
                params["url"] = item
            elif isinstance(item, dict):
                # Smart item handling based on tool
                if tool_name == "stash" and action == "save":
                    # For stash save from crawl results, extract the actual content
                    # Crawl results have: {ok, data: {results: [{url, markdown, ...}]}, ...}
                    content = None
                    source_url = None
                    if "data" in item and "results" in item.get("data", {}):
                        results = item["data"]["results"]
                        if results and len(results) > 0:
                            content = results[0].get("markdown") or results[0].get("text", "")
                            source_url = results[0].get("url", "")
                    elif "markdown" in item:
                        content = item.get("markdown") or item.get("text", "")
                        source_url = item.get("url", "")
                    
                    if content:
                        params["text"] = content
                        # Generate name from URL if not provided
                        if "name" not in params and source_url:
                            from urllib.parse import urlparse
                            domain = urlparse(source_url).netloc.replace("www.", "").split(".")[0]
                            params["name"] = f"{domain}_article_{item_index + 1}.md"
                        elif "name" not in params:
                            topic = variables.get("topic", "source")
                            params["name"] = f"{topic[:20].replace(' ', '_')}_source_{item_index + 1}.md"
                else:
                    # Default: merge item dict into params
                    params.update(item)
            
            # Execute tool
            item_start_time = time.time()
            result = self.executor.execute(tool_name, params)
            item_duration_ms = int((time.time() - item_start_time) * 1000)
            if isinstance(result, dict):
                result["duration_ms"] = item_duration_ms
            
            # Validate result
            if result.get("ok") and step.get("validation"):
                if self._validate_result(result, step, variables):
                    validated_outputs.append(result)
                    outputs.append(result)
                else:
                    # Validation failed - count as retry
                    retries += 1
                    result["validation_failed"] = True
                    outputs.append(result)
            elif result.get("ok"):
                validated_outputs.append(result)
                outputs.append(result)
            else:
                retries += 1
                outputs.append(result)
            
            item_index += 1
        
        # Clean up loop variable
        variables.pop("_loop_index", None)
        
        # Check if we met required success count
        abort = False
        if len(validated_outputs) < required_success:
            if step.get("on_all_fail") == "abort_with_message":
                abort = True
        
        return {
            "items_processed": len(outputs),
            "items_succeeded": len(validated_outputs),
            "outputs": outputs,
            "validated_outputs": validated_outputs,
            "retries": retries,
            "abort": abort
        }
    
    def _resolve_params(self, step: dict, tool_defaults: dict, variables: dict) -> dict:
        """
        Resolve parameters with layering: step > tool_defaults > variables.
        """
        params = {}
        
        # Start with tool defaults
        params.update(tool_defaults)
        
        # Override with step params
        for key, value in step.get("params", {}).items():
            resolved = self._resolve_variable(value, variables)
            if resolved is not None:
                params[key] = resolved
        
        return params
    
    def _resolve_variable(self, expr: Any, variables: dict) -> Any:
        """
        Resolve a variable expression like ${topic} or ${search_results.urls[:5]}.
        Also handles embedded variables in strings and arrays.
        """
        # Handle arrays - recursively resolve each element
        if isinstance(expr, list):
            return [self._resolve_variable(item, variables) for item in expr]
        
        # Handle dicts - recursively resolve each value
        if isinstance(expr, dict):
            return {k: self._resolve_variable(v, variables) for k, v in expr.items()}
        
        if not isinstance(expr, str):
            return expr
        
        full_placeholder = re.fullmatch(r'\$\{([^}]+)\}', expr)

        # Handle embedded variables like "Research: ${topic}" or mixed templates.
        if "${" in expr and not full_placeholder:
            return self._resolve_template_string(expr, variables)
        
        if not full_placeholder:
            return expr
        
        # Extract variable path
        path = full_placeholder.group(1)
        
        # Handle array slicing like urls[:5]
        slice_match = re.match(r'^(.+)\[(\d*):(\d*)\]$', path)
        if slice_match:
            base_path = slice_match.group(1)
            start = int(slice_match.group(2)) if slice_match.group(2) else None
            end = int(slice_match.group(3)) if slice_match.group(3) else None
            
            value = self._get_nested_value(variables, base_path)
            if isinstance(value, list):
                return value[start:end]
            return value
        
        # Handle array indexing like urls[0]
        index_match = re.match(r'^(.+)\[(\d+)\]$', path)
        if index_match:
            base_path = index_match.group(1)
            index = int(index_match.group(2))
            
            value = self._get_nested_value(variables, base_path)
            if isinstance(value, list) and index < len(value):
                return value[index]
            return None
        
        # Simple path like "topic" or "search_results.urls"
        return self._get_nested_value(variables, path)

    def _resolve_template_string(self, template: str, variables: dict) -> str:
        """Resolve all ${...} placeholders inside a larger template string."""
        result = template
        for match in re.finditer(r'\$\{([^}]+)\}', template):
            full_match = match.group(0)
            value = self._resolve_variable(full_match, variables)
            if value is None:
                continue
            replacement = self._format_template_value(value)
            result = result.replace(full_match, replacement)
        return result

    def _format_template_value(self, value: Any) -> str:
        """Format structured values for LLM prompts in a readable way."""
        if isinstance(value, list):
            formatted_list = self._format_reminders_for_prompt(value)
            if formatted_list is not None:
                return formatted_list
            return json.dumps(value, default=str)
        if isinstance(value, dict):
            return json.dumps(value, default=str)
        return str(value)

    def _format_reminders_for_prompt(self, reminders: list[Any]) -> str | None:
        """Convert reminder objects into deterministic markdown for workflow prompts."""
        if not reminders or not all(isinstance(item, dict) for item in reminders):
            return None

        reminder_like = [
            item for item in reminders
            if {"title", "status", "trigger_time"}.issubset(item.keys())
        ]
        if len(reminder_like) != len(reminders):
            return None

        triggered = [r for r in reminders if r.get("status") == "triggered"]
        scheduled = [r for r in reminders if r.get("status") == "scheduled"]
        historical = [r for r in reminders if r.get("status") not in {"triggered", "scheduled"}]

        lines: list[str] = []
        if triggered:
            lines.append("Triggered (need attention, unacknowledged)")
            lines.append("")
            for reminder in triggered:
                lines.extend(self._format_single_reminder_lines(reminder))
                lines.append("")
        if scheduled:
            lines.append("Scheduled (upcoming)")
            lines.append("")
            for reminder in scheduled:
                lines.extend(self._format_single_reminder_lines(reminder))
                lines.append("")
        if historical:
            lines.append("History")
            lines.append("")
            for reminder in historical:
                lines.extend(self._format_single_reminder_lines(reminder))
                lines.append("")

        return "\n".join(lines).strip() if lines else "No reminders"

    def _format_single_reminder_lines(self, reminder: dict[str, Any]) -> list[str]:
        """Format one reminder for workflow prompt consumption."""
        reminder_id = reminder.get("id")
        title = reminder.get("title") or reminder.get("message") or "Reminder"
        status = reminder.get("status", "unknown")
        spoken = reminder.get("spoken")
        trigger_local = reminder.get("trigger_time_local") or reminder.get("trigger_time", "")
        relative_time = reminder.get("relative_time", "")
        recurrence = reminder.get("recurrence_rule")
        acknowledged = "Yes" if reminder.get("acknowledged_at") else "No"

        if spoken in (0, 1, True, False):
            spoken_text = "spoken 1 time" if bool(spoken) else "not spoken"
        else:
            spoken_text = "spoken state unknown"

        first_line = f"- ID {reminder_id}: {title}" if reminder_id is not None else f"- {title}"
        trigger_line = f"  Trigger: {trigger_local}"
        if relative_time:
            trigger_line += f" ({relative_time})"

        lines = [
            first_line,
            f"  Status: {status} ({spoken_text})",
            trigger_line,
        ]

        if status == "triggered":
            lines.append(f"  Acknowledged: {acknowledged}")
        if recurrence:
            lines.append(f"  Recurrence: {recurrence}")

        return lines
    
    def _get_nested_value(self, data: dict, path: str) -> Any:
        """Get a nested value using dot notation with optional list indexes."""
        parts = path.split(".")
        current = data
        
        for part in parts:
            current = self._get_path_part(current, part)
            if current is None:
                return None

        return current

    def _get_path_part(self, current: Any, part: str) -> Any:
        """Resolve one dotted path segment, including forms like results[0]."""
        match = re.fullmatch(r"([^\[\]]+)((?:\[\d+\])*)", part)
        if not match:
            if isinstance(current, dict):
                return current.get(part)
            return None

        key, indexes = match.groups()
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None

        for raw_index in re.findall(r"\[(\d+)\]", indexes):
            index = int(raw_index)
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
            if current is None:
                return None

        return current

    def _apply_variable_assignments(self, assignments: dict | None, variables: dict) -> None:
        """Apply workflow-defined variable assignments with template resolution."""
        if not isinstance(assignments, dict):
            return
        for key, value in assignments.items():
            variables[key] = self._resolve_variable(value, variables)
    
    def _apply_output_transforms(self, step: dict, result: dict, variables: dict, 
                                    tool_name: str, action: str) -> None:
        """
        Apply output transformations to extract useful data from step results.
        Uses step-defined 'extract' rules or falls back to built-in patterns.
        """
        data = result.get("data", {})
        
        # Check for step-defined extraction rules first
        extract_rules = step.get("extract", {})
        if extract_rules:
            for var_name, path in extract_rules.items():
                value = self._extract_by_path(data, path)
                if value is not None:
                    variables[var_name] = value
        
        # Built-in patterns (fallback for common tools)
        
        # Stash open_space - extract space_id
        if tool_name == "stash" and action == "open_space":
            if data.get("space_id"):
                variables["space_id"] = data["space_id"]
        
        # Crawl URL - extract content and title from results
        if tool_name == "crawl_url":
            results = data.get("results", [])
            if results:
                first_result = results[0] if isinstance(results, list) else results
                output_var = step.get("output_var", "article")
                # Flatten for easier access: ${article.title}, ${article.content}
                variables[output_var] = {
                    "title": first_result.get("title", "Untitled"),
                    "content": first_result.get("markdown", ""),
                    "url": first_result.get("url", ""),
                    "results": results  # Keep full results too
                }
        
        # Search tools - extract URLs
        if self._is_search_tool(tool_name):
            urls = self._extract_urls_from_search(data)
            if urls:
                variables["search_results"] = {"urls": urls, "data": data}
                # Mark as successful if we got URLs even if tool reported failure
                if not result.get("ok"):
                    result["ok"] = True
                    result["recovered"] = True
        
        # Remember tool - extract memory_id
        if tool_name == "remember":
            if data.get("memory_id"):
                variables["memory_id"] = data["memory_id"]
            elif data.get("id"):
                variables["memory_id"] = data["id"]
        
        # Canvas tool - extract page_id
        if tool_name == "canvas":
            if data.get("page_id"):
                variables["canvas_id"] = data["page_id"]
            elif data.get("id"):
                variables["canvas_id"] = data["id"]

        # Reminder tool - provide deterministic markdown for workflow prompts/canvas reports
        if tool_name == "list_reminders":
            reminders = data.get("reminders", [])
            if isinstance(reminders, list):
                formatted = self._format_reminders_for_prompt(reminders)
                if formatted:
                    variables["reminders_markdown"] = formatted
        
        # SSH tool - extract output
        if tool_name == "ssh_remote":
            if data.get("output"):
                variables["ssh_output"] = data["output"]
        
        # Generate image - extract path
        if tool_name == "generate_image":
            if data.get("path"):
                variables["image_path"] = data["path"]
    
    def _is_search_tool(self, tool_name: str) -> bool:
        """Check if a tool is a search tool."""
        search_indicators = ["search", "brave", "serp", "google", "bing", "duckduckgo"]
        tool_lower = tool_name.lower()
        return any(ind in tool_lower for ind in search_indicators)
    
    def _extract_by_path(self, data: dict, path: str) -> Any:
        """
        Extract a value from nested data using dot notation or special syntax.
        
        Examples:
            "space_id" -> data["space_id"]
            "results[0].url" -> data["results"][0]["url"]
            "results[*].url" -> [r["url"] for r in data["results"]]
        """
        if not path or not data:
            return None
        
        # Handle array wildcard like "results[*].url"
        if "[*]" in path:
            parts = path.split("[*]")
            if len(parts) == 2:
                array_path = parts[0].strip(".")
                item_path = parts[1].strip(".")
                
                array_data = self._get_nested_value(data, array_path) if array_path else data
                if isinstance(array_data, list):
                    return [self._get_nested_value(item, item_path) for item in array_data 
                            if self._get_nested_value(item, item_path) is not None]
            return None
        
        # Handle indexed access like "results[0].url"
        # Convert to nested format for _get_nested_value
        return self._get_nested_value(data, path)
    
    def _format_articles_for_llm(self, articles: list[dict]) -> str:
        """Format validated articles for LLM consumption."""
        if not articles:
            return "[No articles gathered]"
        
        formatted = []
        for i, article in enumerate(articles, 1):
            # Extract content from various possible structures
            data = article.get("data", {})
            content = ""
            url = ""
            
            # Handle crawl_url format: data.results[0].markdown
            if "results" in data and data["results"]:
                result = data["results"][0]
                content = result.get("markdown", result.get("content", ""))
                url = result.get("url", "")
            else:
                content = data.get("markdown", data.get("content", data.get("text", "")))
                url = data.get("url", "")
            
            # Truncate content to reasonable size (keep first ~3000 chars per article)
            if len(content) > 3000:
                content = content[:3000] + "\n\n[... content truncated ...]"
            
            formatted.append(f"### Article {i}\n**URL**: {url}\n\n{content}")
        
        return "\n\n---\n\n".join(formatted)
    
    def _extract_urls_from_search(self, search_data: dict) -> list[str]:
        """
        Extract URLs from search results (handles MCP and native formats).
        """
        urls = []
        
        # Handle MCP brave_search format (full_text contains JSON strings)
        full_text = search_data.get("full_text", "")
        if full_text:
            # Parse JSON objects from full_text
            import re
            json_pattern = r'\{[^{}]+\}'
            matches = re.findall(json_pattern, full_text)
            for match in matches:
                try:
                    obj = json.loads(match)
                    if obj.get("url"):
                        urls.append(obj["url"])
                except json.JSONDecodeError:
                    continue
        
        # Handle standard results array format
        if not urls:
            results = search_data.get("results", [])
            for result in results:
                if result.get("url"):
                    urls.append(result["url"])
        
        # Handle web.results format (Brave API direct)
        if not urls:
            web = search_data.get("web", {})
            for result in web.get("results", []):
                if result.get("url"):
                    urls.append(result["url"])
        
        return urls
    
    def _extract_topic(self, query: str, workflow: dict) -> str:
        """Extract the main topic from the query."""
        # Remove explicit command prefix
        for explicit in workflow.get("triggers", {}).get("explicit", []):
            if query.lower().startswith(explicit.lower()):
                topic = query[len(explicit):].strip()
                return topic
        
        # Remove common patterns
        patterns = workflow.get("triggers", {}).get("patterns", [])
        query_lower = query.lower()
        for pattern in patterns:
            if pattern.lower() in query_lower:
                # Remove the pattern and return the rest
                idx = query_lower.find(pattern.lower())
                topic = query[idx + len(pattern):].strip()
                if topic:
                    return topic
        
        # Return the whole query as topic
        return query
    
    def _extract_workflow_variables(self, query: str, workflow: dict, topic: str) -> dict[str, Any]:
        """
        Extract workflow-defined variables from the query.
        
        Handles variable definitions like:
        - {"from": "query", "extract": "url"}
        - {"from": "query", "extract": "main_subject"}
        - {"from": "query", "extract": "main_subject", "default": "vps2"}
        - {"from": "static", "value": "some fixed value"}
        - {"from": "env", "key": "JARVIS_DEFAULT_LOCATION", "default": "Hillsboro, Oregon"}
        - {"from": "url", "transform": "domain"}  # Derive from another variable
        """
        variables = {
            "query": query,
            "topic": topic,
            "content": topic,  # Alias for workflows that expect 'content'
            "workflow_id": workflow.get("id", "unknown"),
            "timestamp": datetime.now().isoformat()
        }
        
        var_defs = workflow.get("variables", {})
        
        # First pass: extract variables from query/static
        for var_name, var_def in var_defs.items():
            # Handle simple values (string, int, float, bool) as static variables
            if isinstance(var_def, (str, int, float, bool)):
                variables[var_name] = var_def
                continue
            
            if not isinstance(var_def, dict):
                continue
            
            source = var_def.get("from", "query")
            extract_type = var_def.get("extract", "main_subject")
            default_value = var_def.get("default")
            
            extracted_value = None
            
            if source == "static":
                # Static value - use directly
                extracted_value = var_def.get("value")
            elif source == "env":
                env_key = var_def.get("key", var_name)
                extracted_value = os.environ.get(env_key)
            elif source == "query":
                if extract_type == "url":
                    # Extract URL from query
                    extracted_value = self._extract_url_from_text(topic)
                elif extract_type == "main_subject":
                    extracted_value = topic if topic and topic.strip() else None
                elif extract_type == "short_title":
                    # Use LLM to generate a concise title from the query
                    if topic and topic.strip():
                        extracted_value = self._generate_short_title(topic.strip())
                    if not extracted_value:
                        # Fallback: first 8 words joined by spaces
                        words = topic.strip().split()[:8] if topic and topic.strip() else []
                        extracted_value = " ".join(words) if words else None
                elif extract_type == "first_words":
                    # Extract first N words from topic for use in titles/keys
                    max_words = var_def.get("max_words", 4)
                    if topic and topic.strip():
                        # Strip leading slash/command prefix if present
                        clean_topic = topic.strip().lstrip('/')
                        words = clean_topic.split()
                        # Filter out empty words and join with underscore
                        extracted_value = "_".join(w for w in words[:max_words] if w)
                    else:
                        extracted_value = None
                else:
                    extracted_value = topic if topic and topic.strip() else None
            
            # Use extracted value or fall back to default
            if extracted_value and str(extracted_value).strip():
                variables[var_name] = extracted_value
            elif default_value is not None:
                variables[var_name] = default_value
        
        # Second pass: apply transforms that reference other variables
        for var_name, var_def in var_defs.items():
            # Skip simple values (already handled in first pass)
            if not isinstance(var_def, dict):
                continue
            
            transform = var_def.get("transform")
            source = var_def.get("from", "query")
            default_value = var_def.get("default")
            
            if transform and source in variables:
                source_value = variables.get(source, "")
                transformed = self._apply_transform(source_value, transform)
                if transformed:
                    variables[var_name] = transformed
                elif default_value is not None:
                    variables[var_name] = default_value
        
        return variables
    
    def _apply_transform(self, value: str, transform: str) -> str | None:
        """Apply a transformation to a value."""
        if not value:
            return None
        
        if transform == "domain":
            # Extract domain from URL
            return self._extract_domain_from_url(value)
        elif transform == "lowercase":
            return value.lower()
        elif transform == "uppercase":
            return value.upper()
        elif transform == "strip":
            return value.strip()
        
        return value
    
    def _extract_domain_from_url(self, url: str) -> str | None:
        """Extract domain from a URL (e.g., 'https://www.bigsk1.com/page' -> 'bigsk1.com')."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path.split('/')[0]
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain if domain else None
        except Exception:
            return None
    
    def _extract_url_from_text(self, text: str) -> str | None:
        """Extract a URL from text, adding https:// if needed."""
        # Try to find a URL with protocol
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        match = re.search(url_pattern, text)
        if match:
            return match.group(0)
        
        # Try to find a domain-like pattern (e.g., "bigsk1.com" or "www.example.com")
        domain_pattern = r'(?:www\.)?([a-zA-Z0-9][-a-zA-Z0-9]*\.)+[a-zA-Z]{2,}(?:/[^\s]*)?'
        match = re.search(domain_pattern, text)
        if match:
            domain = match.group(0)
            # Add https:// if not present
            if not domain.startswith(('http://', 'https://')):
                domain = 'https://' + domain
            return domain
        
        return None
    
    def _validate_result(self, result: dict, step: dict, variables: dict) -> bool:
        """Validate step result using configured validation."""
        validation = step.get("validation", {})
        
        # Get content to validate (handle various result formats)
        content = ""
        data = result.get("data", {})
        if isinstance(data, dict):
            # Try direct content fields first
            content = data.get("content", data.get("markdown", data.get("text", "")))
            
            # Handle crawl_url format: data.results[0].markdown
            if not content and "results" in data:
                results = data.get("results", [])
                if results and isinstance(results[0], dict):
                    content = results[0].get("markdown", results[0].get("content", ""))
        elif isinstance(data, str):
            content = data
        
        # Heuristic validation
        if validation.get("type") in ["heuristic", "hybrid"]:
            heuristic = validation.get("heuristic", validation)
            
            # Check minimum length
            min_length = heuristic.get("min_length", 0)
            if len(content) < min_length:
                return False
            
            # Check reject patterns
            content_lower = content.lower()
            for pattern in heuristic.get("reject_patterns", []):
                if pattern.lower() in content_lower:
                    return False
            
            # Check minimum results (for search)
            min_results = heuristic.get("min_results", 0)
            if min_results > 0:
                # Check various result formats: results, raw, urls
                results_list = data.get("results", data.get("raw", []))
                if len(results_list) < min_results:
                    return False
        
        # LLM validation (if hybrid or llm type)
        if validation.get("type") in ["llm", "hybrid"] and validation.get("llm_prompt"):
            if self.provider:
                return self._llm_validate(content, validation["llm_prompt"], variables)
        
        return True
    
    def _llm_validate(self, content: str, prompt_template: str, variables: dict) -> bool:
        """Use LLM to validate content."""
        if not self.provider:
            return True  # Skip LLM validation if no provider
        
        # Resolve variables in prompt
        prompt = self._resolve_template_string(prompt_template, variables)
        
        # Truncate content for validation
        content_preview = content[:2000] if len(content) > 2000 else content
        
        try:
            user_message = f"{prompt}\n\nContent to validate:\n{content_preview}"
            system_prompt = "You are validating content quality. Respond with only 'YES' or 'NO'."
            
            # Use _chat_with_usage to track token usage
            response = self._chat_with_usage(user_message, system_prompt=system_prompt)
            answer = response.strip().upper() if isinstance(response, str) else ""
            
            return answer.startswith("YES")
        except Exception as e:
            print(f"LLM validation error: {e}", file=sys.stderr)
            return True  # Default to valid on error
    
    def _llm_should_execute(self, step: dict, variables: dict) -> bool:
        """Use LLM to decide if a step should execute."""
        if not self.provider:
            return True
        
        prompt = self._resolve_template_string(
            step.get("llm_prompt", "Should this step be executed?"),
            variables
        )
        
        try:
            system_prompt = "Decide if this action should be taken. Respond with only 'YES' or 'NO'."
            
            # Use _chat_with_usage to track token usage
            response = self._chat_with_usage(prompt, system_prompt=system_prompt)
            answer = response.strip().upper() if isinstance(response, str) else ""
            
            return answer.startswith("YES")
        except Exception:
            return True

    def _should_execute_step(self, step: dict, variables: dict) -> tuple[bool, str | None]:
        """Evaluate whether a workflow step should execute."""
        condition = step.get("condition")
        if condition is None:
            return True, None

        if condition == "${llm_decides}":
            return (
                self._llm_should_execute(step, variables),
                "LLM decided to skip"
            )

        try:
            should_execute = self._evaluate_condition(condition, variables)
            return should_execute, "Condition evaluated to false"
        except Exception as e:
            print(f"Warning: condition evaluation failed for step {step.get('step')}: {e}", file=sys.stderr)
            # Fail open so a bad condition does not silently suppress important work.
            return True, None

    def _evaluate_condition(self, condition: Any, variables: dict) -> bool:
        """Evaluate a deterministic workflow condition."""
        if isinstance(condition, list):
            return all(self._evaluate_condition(item, variables) for item in condition)

        if isinstance(condition, dict):
            if "any" in condition:
                return any(self._evaluate_condition(item, variables) for item in condition["any"])
            if "all" in condition:
                return all(self._evaluate_condition(item, variables) for item in condition["all"])

            op = str(condition.get("op", "truthy")).strip().lower()
            left = self._resolve_variable(condition.get("left"), variables)
            right = self._resolve_variable(condition.get("right"), variables)

            if op in {"truthy", "exists"}:
                return self._is_truthy(left)
            if op == "not_exists":
                return not self._is_truthy(left)
            if op == "eq":
                return self._normalize_condition_value(left) == self._normalize_condition_value(right)
            if op == "ne":
                return self._normalize_condition_value(left) != self._normalize_condition_value(right)
            if op == "lt":
                try:
                    return self._compare_condition_values(left, right) < 0
                except ValueError:
                    return False
            if op == "lte":
                try:
                    return self._compare_condition_values(left, right) <= 0
                except ValueError:
                    return False
            if op == "gt":
                try:
                    return self._compare_condition_values(left, right) > 0
                except ValueError:
                    return False
            if op == "gte":
                try:
                    return self._compare_condition_values(left, right) >= 0
                except ValueError:
                    return False
            if op == "contains":
                return str(right or "").lower() in str(left or "").lower()
            if op == "contains_any":
                haystack = str(left or "").lower()
                if isinstance(right, str):
                    needles = [item.strip() for item in right.split(",")]
                elif isinstance(right, list):
                    needles = right
                else:
                    needles = [right]
                return any(str(needle).strip().lower() in haystack for needle in needles if str(needle).strip())

            raise ValueError(f"Unsupported condition op: {op}")

        if isinstance(condition, str):
            resolved = self._resolve_variable(condition, variables)
            return self._is_truthy(resolved)

        return self._is_truthy(condition)

    def _normalize_condition_value(self, value: Any) -> Any:
        """Normalize workflow condition values for comparisons."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return ""
            if stripped.lower() in {"true", "false"}:
                return stripped.lower() == "true"
            if re.fullmatch(r"-?\d+", stripped):
                try:
                    return int(stripped)
                except ValueError:
                    pass
            if re.fullmatch(r"-?\d+\.\d+", stripped):
                try:
                    return float(stripped)
                except ValueError:
                    pass
            return stripped
        return value

    def _compare_condition_values(self, left: Any, right: Any) -> int:
        """Compare two values for workflow conditions."""
        norm_left = self._normalize_condition_value(left)
        norm_right = self._normalize_condition_value(right)

        if norm_left is None or norm_right is None:
            raise ValueError("Cannot compare None values")

        if isinstance(norm_left, (int, float)) and isinstance(norm_right, (int, float)):
            return (norm_left > norm_right) - (norm_left < norm_right)

        if isinstance(norm_left, (int, float)) != isinstance(norm_right, (int, float)):
            raise ValueError("Cannot compare numeric and non-numeric values")

        left_str = str(norm_left)
        right_str = str(norm_right)
        return (left_str > right_str) - (left_str < right_str)

    def _is_truthy(self, value: Any) -> bool:
        """Truthiness helper for workflow conditions."""
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip().lower() not in {"", "0", "false", "none", "null"}
        if isinstance(value, (list, dict, tuple, set)):
            return len(value) > 0
        return bool(value)
    
    def _llm_fill_params(self, step: dict, variables: dict) -> dict:
        """Use LLM to fill in parameters based on llm_prompt.
        
        TODO: Support llm_hints - additional guidance for parameter generation.
        When implemented, hints would be appended to the prompt like:
            hints = step.get("llm_hints", {})
            if hints:
                prompt += "\\n\\nParameter hints:\\n"
                for param, hint in hints.items():
                    prompt += f"- {param}: {hint}\\n"
        """
        if not self.provider:
            return {}
        
        prompt = step.get("llm_prompt", "")
        tool_name = step.get("tool", "")
        
        # Find all ${...} patterns in the prompt and resolve them
        import re
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, prompt)
        
        for var_path in matches:
            placeholder = f"${{{var_path}}}"
            
            # Get value using nested path resolution
            value = self._resolve_variable(placeholder, variables)
            
            if value is None:
                continue
            
            if isinstance(value, str):
                prompt = prompt.replace(placeholder, value)
            elif var_path == "validated_articles" and isinstance(value, list):
                # Special handling for articles - extract actual content
                articles_text = self._format_articles_for_llm(value)
                prompt = prompt.replace(placeholder, articles_text)
            else:
                prompt = prompt.replace(placeholder, self._format_template_value(value)[:3000])
        
        try:
            # Use appropriate system prompt based on tool type
            if tool_name == "crypto_price":
                system_prompt = "Extract the requested value. Respond with ONLY the value, no extra text."
            elif tool_name == "generate_image":
                system_prompt = "Generate a detailed image prompt description. Focus on visual elements, colors, composition, and style. Do NOT use ASCII art or code blocks. Output only the text description for an AI image generator."
            else:
                system_prompt = "Generate content based on the instruction. Be comprehensive and well-structured."
            
            # Use _chat_with_usage to track token usage
            response = self._chat_with_usage(prompt, system_prompt=system_prompt)
            content = response.strip() if isinstance(response, str) else ""
            
            # Return appropriate parameter names based on tool
            if tool_name == "crypto_price":
                # For crypto_price, the LLM should return just the coin name
                return {"coin": content.lower().strip()}
            elif tool_name == "send_email":
                return {"body": content}
            elif tool_name == "stash":
                # stash save needs 'text' for content AND 'name' for filename
                # Generate name from step context if not provided
                action = step.get("params", {}).get("action", step.get("action", ""))
                if action == "save":
                    # Try to generate a sensible filename
                    topic = variables.get("topic", "research")
                    index = variables.get("_loop_index", 0)
                    name = f"{topic.replace(' ', '_')[:30]}_source_{index + 1}.txt"
                    return {"text": content, "name": name}
                return {"text": content}
            elif tool_name == "canvas":
                return {"content": content}
            elif tool_name == "generate_image":
                return {"prompt": content}
            elif tool_name == "remember":
                # remember requires 'key' and 'value', NOT content/text/body
                # Try to extract key from content or generate one
                topic = variables.get("topic", "fact")
                key = f"{topic.replace(' ', '_')[:40]}_{hash(content) % 10000}"
                return {"key": key, "value": content}
            else:
                # Generic fallback - return all common parameter names
                return {"content": content, "text": content, "body": content}
        except Exception as e:
            print(f"LLM param fill error: {e}", file=sys.stderr)
            return {}
    
    def _build_success_response(self, workflow: dict, results: list[dict],
                                 variables: dict, tools_used: list[str],
                                 start_time: float = None, query: str = None) -> dict[str, Any]:
        """Build success response and log workflow execution."""
        # Count successful articles
        article_count = len(variables.get("validated_articles", []))
        variables["article_count"] = article_count  # Make available for speech
        
        # Build speech from template - resolve all ${variables}
        speech_prompt = workflow.get("success_speech_llm_prompt")
        if speech_prompt and self.provider:
            resolved_prompt = self._resolve_variable(speech_prompt, variables)
            system_prompt = (
                "Write a short voice-friendly workflow completion message. "
                "Be direct and actionable. Keep it under 45 words."
            )
            speech = self._chat_with_usage(str(resolved_prompt), system_prompt=system_prompt, max_tokens=120).strip()
            if not speech:
                speech_template = workflow.get("success_speech", "Workflow complete.")
                speech = self._resolve_variable(speech_template, variables)
        else:
            speech_template = workflow.get("success_speech", "Workflow complete.")
            speech = self._resolve_variable(speech_template, variables)
        
        # If still has unresolved vars, they stay as-is (shouldn't happen normally)
        if not isinstance(speech, str):
            speech = str(speech)
        
        response = {
            "ok": True,
            "speech": speech,
            "data": {
                "workflow_id": workflow.get("id"),
                "workflow_name": workflow.get("name"),
                "steps_completed": len(results),
                "results": results,
                "variables": {k: v for k, v in variables.items() if not k.startswith("_")}
            },
            "tools_used": list(dict.fromkeys(tools_used)),  # Preserve order, remove duplicates
            "usage": self._total_usage if self._total_usage.get("total_tokens", 0) > 0 else None,
            "server_side_tools": self._server_side_tools if self._server_side_tools else None
        }
        
        # Log workflow execution
        if start_time:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.log_workflow_execution(
                workflow_id=workflow.get("id", "unknown"),
                workflow_name=workflow.get("name", ""),
                user_query=query or variables.get("query", ""),
                result=response,
                duration_ms=duration_ms,
                steps_completed=len(results),
                tools_used=list(set(tools_used)),
                mode=self.mode
            )
        
        # Log server-side tools to dedicated log file
        if self._server_side_tools:
            provider_type = get_config_value("LLM_PROVIDER", "unknown")
            model = get_config_value(f"{provider_type.upper()}_MODEL", "unknown")
            self.llm_logger.log_server_side_tools(
                provider=provider_type,
                model=model,
                tools=self._server_side_tools,
                context=f"workflow:{workflow.get('id', 'unknown')}",
                user_query=query,
                mode=self.mode
            )
        
        return response
    
    def _build_abort_response(self, workflow: dict, failed_step: dict,
                               results: list[dict], variables: dict,
                               start_time: float = None, query: str = None,
                               step_error: str = None) -> dict[str, Any]:
        """Build abort response and log workflow abortion."""
        speech_template = failed_step.get("abort_speech") or workflow.get("abort_speech", "Workflow aborted.")
        speech = speech_template
        speech = speech.replace("${topic}", variables.get("topic", ""))
        
        tools_used = [r.get("tool") for r in results if r.get("tool")]
        
        # Build detailed reason with error message
        reason = f"Step {failed_step.get('step')} ({failed_step.get('tool')}) failed"
        if step_error:
            reason = f"{reason}: {step_error}"
        
        response = {
            "ok": False,
            "speech": speech,
            "error": step_error,  # Surface the actual error at top level
            "data": {
                "workflow_id": workflow.get("id"),
                "aborted_at_step": failed_step.get("step"),
                "failed_tool": failed_step.get("tool"),
                "reason": reason,
                "results": results
            },
            "tools_used": tools_used,
            "usage": self._total_usage if self._total_usage.get("total_tokens", 0) > 0 else None
        }
        
        # Log aborted workflow execution
        if start_time:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.log_workflow_execution(
                workflow_id=workflow.get("id", "unknown"),
                workflow_name=workflow.get("name", ""),
                user_query=query or variables.get("query", ""),
                result=response,
                duration_ms=duration_ms,
                steps_completed=len(results),
                tools_used=tools_used,
                mode=self.mode
            )
        
        return response


def main():
    """CLI for testing pipeline executor."""
    import argparse
    from executor import ToolExecutor
    from workflow_loader import WorkflowLoader
    
    parser = argparse.ArgumentParser(description="Pipeline Executor CLI")
    parser.add_argument("mode", choices=["cloud", "local"], help="Execution mode")
    parser.add_argument("query", help="Query to execute")
    parser.add_argument("--workflow", "-w", help="Workflow ID (optional, auto-matches if not provided)")
    
    args = parser.parse_args()
    
    # Load config
    load_config(args.mode)
    
    # Initialize components
    loader = WorkflowLoader()
    
    # Match or get workflow
    if args.workflow:
        workflow = loader.get_workflow(args.workflow)
        if not workflow:
            print(f"Workflow '{args.workflow}' not found")
            sys.exit(1)
    else:
        workflow = loader.match(args.query)
        if not workflow:
            print("No workflow matched. Use --workflow to specify.")
            sys.exit(1)
    
    print(f"Executing workflow: {workflow['id']}")
    print(f"Steps: {len(workflow.get('steps', []))}")
    print("-" * 40)
    
    # Initialize executor
    from tool_schema import get_tool_registry

    registry = get_tool_registry(mode=args.mode)
    tool_executor = ToolExecutor(args.mode, registry=registry)
    
    # Execute pipeline
    pipeline = PipelineExecutor(args.mode, tool_executor)
    
    def status_callback(msg):
        print(f"[STATUS] {msg}")
    
    result = pipeline.execute(workflow, args.query, status_callback=status_callback)
    
    print("-" * 40)
    print(f"Result: {'SUCCESS' if result.get('ok') else 'FAILED'}")
    print(f"Speech: {result.get('speech')}")
    print(f"Tools used: {result.get('tools_used')}")
    
    if os.environ.get("JARVIS_DEBUG"):
        print("\nFull result:")
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
