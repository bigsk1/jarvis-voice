#!/usr/bin/env python3
"""
LLM Provider Abstraction Layer
Supports OpenAI, Anthropic, xAI (Grok), and Ollama with unified interface.
"""
import os
import sys
import json
import time
import hashlib
from typing import Any
from abc import ABC, abstractmethod

# Prefer the system resolver over c-ares for xAI/gRPC DNS stability.
# environment already chose something else explicitly.
os.environ.setdefault("GRPC_DNS_RESOLVER", "native")

from model_catalog import get_provider_fallback_model
from ollama_utils import parse_ollama_base_urls, request_ollama


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False,
        previous_response_id: str | None = None,
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """
        Send chat request with tool calling capability.
        
        Args:
            messages: Conversation history [{"role": "user", "content": "..."}]
            tools: List of tool definitions (format depends on provider)
            system_prompt: System prompt for the conversation
            enable_thinking: Enable extended thinking mode (if supported by model)
            previous_response_id: Provider-specific continuation handle, if supported
            
        Returns:
            Tuple of (text_response, tool_call, usage_info, thinking)
            - text_response: Direct text response from LLM (if not calling tool)
            - tool_call: {"name": "tool_name", "arguments": {...}} if tool called
            - usage_info: Token counts and cost estimates (None for local models)
            - thinking: LLM reasoning/thinking text (None if not available)
        """
        pass
    
    @abstractmethod
    def chat(self, message: str, system_prompt: str | None = None, max_tokens: int = None) -> str:
        """
        Simple chat without tool calling.
        
        Args:
            message: User message
            system_prompt: Optional system prompt
            
        Returns:
            Text response from LLM
        """
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI provider using function calling."""
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        """Initialize OpenAI provider."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")
        
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def _openai_reasoning_effort(self, *, uses_tools: bool = False) -> str | None:
        """
        Optional reasoning-effort override for reasoning-capable OpenAI models.

        Chat Completions supports reasoning_effort on GPT-5/o-series models, but
        it should be omitted for older non-reasoning chat families.
        """
        if not self.model.startswith(("gpt-5", "o1", "o3", "o4")):
            return None

        from config_loader import get_config_value

        value = (get_config_value("OPENAI_REASONING_EFFORT", "") or "").strip().lower()
        if not value:
            return None

        allowed = {"none", "minimal", "low", "medium", "high", "xhigh"}
        if value not in allowed:
            print(
                f"WARNING: Ignoring invalid OPENAI_REASONING_EFFORT={value!r}",
                file=sys.stderr,
            )
            return None

        # OpenAI docs note models before GPT-5.1 do not support "none".
        if value == "none" and not self.model.startswith("gpt-5.1"):
            print(
                f"WARNING: {self.model} does not support reasoning_effort='none'; "
                "using 'minimal' instead",
                file=sys.stderr,
            )
            return "minimal"

        # Current OpenAI behavior: gpt-5.4-mini rejects the combination of
        # reasoning_effort + function tools on /v1/chat/completions and asks
        # callers to use /v1/responses instead. Jarvis still uses Chat
        # Completions for tool orchestration, so skip the env override here.
        if uses_tools and self.model.startswith("gpt-5.4-mini"):
            print(
                f"INFO: Skipping reasoning_effort for {self.model} tool calls on "
                "/v1/chat/completions (unsupported by OpenAI for this model)",
                file=sys.stderr,
            )
            return None

        return value
    
    def chat(self, message: str, system_prompt: str | None = None, max_tokens: int = None) -> str:
        """Simple chat without tools."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})
        
        try:
            params = {"model": self.model, "messages": messages}
            reasoning_effort = self._openai_reasoning_effort()
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort
            if max_tokens:
                # Newer OpenAI models (gpt-5.x, o1, o3, etc.) use max_completion_tokens
                if self.model.startswith(('gpt-5', 'o1', 'o3')):
                    params["max_completion_tokens"] = max_tokens
                else:
                    params["max_tokens"] = max_tokens
            response = self.client.chat.completions.create(**params)
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"OpenAI API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"
    
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False,
        previous_response_id: str | None = None,
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """
        Send chat with OpenAI function calling.
        
        Returns:
            Tuple of (text_response, tool_call, usage_info, thinking)
            - usage_info contains token counts and cost estimates
            - thinking is None for non-reasoning OpenAI models
        """
        # Add system message if provided
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        
        try:
            request_params = {
                "model": self.model,
                "messages": full_messages,
            }
            reasoning_effort = self._openai_reasoning_effort(uses_tools=bool(tools))
            if reasoning_effort:
                request_params["reasoning_effort"] = reasoning_effort
            if tools:
                request_params["tools"] = tools
                request_params["tool_choice"] = "auto"

            response = self.client.chat.completions.create(**request_params)

            message = response.choices[0].message
            
            # Extract usage info
            usage_info = None
            if hasattr(response, 'usage') and response.usage:
                from cost_estimator import estimate_cost
                usage_info = estimate_cost(
                    provider="openai",
                    model=self.model,
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens
                )
            
            # Check if tool was called
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                return None, {
                    "name": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments)
                }, usage_info, None  # No thinking for standard models
            
            # Otherwise return text response
            return message.content, None, usage_info, None  # No thinking for standard models
            
        except Exception as e:
            print(f"OpenAI API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}", None, None, None


class AnthropicProvider(LLMProvider):
    """
    Anthropic Claude provider using tool calling.
    
    Features:
    - Prompt caching (90% cost reduction on cache hits)
    - Extended thinking mode (Claude Sonnet 4+)
    - Web search tool when ANTHROPIC_SEARCH=true (requires beta header)
    """
    
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929"):
        """Initialize Anthropic provider."""
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")
        
        self.client = Anthropic(api_key=api_key)
        self.model = model
        
        # Check if web search is enabled (ANTHROPIC_SEARCH=true in cloud.env)
        # When enabled, Claude can search the web for real-time info
        from config_loader import get_config_value
        self.enable_search = get_config_value("ANTHROPIC_SEARCH", "false").lower() == "true"
        
        if self.enable_search and os.environ.get('JARVIS_DEBUG'):
            print(f"DEBUG: Anthropic Web Search enabled", file=sys.stderr)
    
    def chat(self, message: str, system_prompt: str | None = None, max_tokens: int = None) -> str:
        """
        Simple chat without tools.
        
        Uses prompt caching for system prompt (90% cost reduction on cache hits).
        """
        try:
            # Enable prompt caching for system prompt
            system_blocks = [
                {
                    "type": "text",
                    "text": system_prompt or "You are a helpful AI assistant.",
                    "cache_control": {"type": "ephemeral"}
                }
            ]
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens or 1024,
                system=system_blocks,
                messages=[{"role": "user", "content": message}]
            )
            
            text_content = self._collect_anthropic_text_blocks(response.content)
            if text_content:
                return text_content
            
            return "No response from Claude"
        except Exception as e:
            print(f"Anthropic API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"

    @staticmethod
    def _collect_anthropic_text_blocks(blocks: list[Any]) -> str:
        """Preserve all text blocks in order; Anthropic may split one answer across many."""
        parts: list[str] = []
        for block in blocks or []:
            if getattr(block, "type", None) != "text":
                continue
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)
    
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False,
        previous_response_id: str | None = None,
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """
        Send chat with Anthropic tool calling.
        
        Uses prompt caching to reduce costs by 90% on repeated system prompts/tools.
        Cache is valid for 5 minutes of inactivity.
        
        Supports extended thinking mode (Claude Sonnet 4+) for complex decisions.
        
        Returns:
            Tuple of (text_response, tool_call, usage_info, thinking)
            - usage_info contains token counts, cost estimates, and cache metrics
            - thinking contains LLM reasoning (if enable_thinking=True and supported)
        """
        try:
            # Enable prompt caching for system prompt
            # Cache everything in the system prompt (saves 90% on cache hits) the embedded date/time in system prompt can invalid cache fyi, look at later
            system_blocks = [
                {
                    "type": "text",
                    "text": system_prompt or "You are a helpful AI assistant.",
                    "cache_control": {"type": "ephemeral"}
                }
            ]
            
            # Enable prompt caching for tools
            # Mark the LAST tool for caching (Anthropic caches up to that point)
            tools_with_cache = []
            for i, tool in enumerate(tools):
                if i == len(tools) - 1:
                    # Last tool: add cache control
                    tools_with_cache.append({
                        **tool,
                        "cache_control": {"type": "ephemeral"}
                    })
                else:
                    tools_with_cache.append(tool)
            
            # Add web search tool if enabled (ANTHROPIC_SEARCH=true)
            # This is a server-side tool - Claude can search the web for real-time info
            extra_headers = {}
            if self.enable_search:
                # Add web search as first tool (server-side, special type)
                web_search_tool = {
                    "type": "web_search_20260209",
                    "name": "web_search",
                    "max_uses": 5  # Limit searches per request
                }
                tools_with_cache.insert(0, web_search_tool)
                # Required beta header for web search
                # extra_headers["anthropic-beta"] = "web-search-2025-03-05"
                
                if os.environ.get('JARVIS_DEBUG'):
                    print(f"DEBUG: Added Anthropic web search tool", file=sys.stderr)
            
            # Add thinking parameter if enabled and supported
            # Note: max_tokens must be > thinking.budget_tokens (Anthropic requirement)
            # Base: 1024 for normal responses, 8192 for thinking mode (generous for complex tasks)
            base_max_tokens = 1024
            
            api_params = {
                "model": self.model,
                "max_tokens": base_max_tokens,
                "system": system_blocks,
                "messages": messages,
            }
            if tools_with_cache:
                api_params["tools"] = tools_with_cache
            
            # Add extra headers if any (reserved for future provider requirements)
            if extra_headers:
                api_params["extra_headers"] = extra_headers
            
            # Enable extended thinking for supported models
            if enable_thinking:
                from thinking import is_thinking_supported, get_thinking_config
                if is_thinking_supported("anthropic", self.model):
                    thinking_config = get_thinking_config("anthropic", self.model)
                    if thinking_config:
                        api_params["thinking"] = thinking_config
                        # Increase max_tokens to accommodate thinking budget + comprehensive response
                        # max_tokens must be > budget_tokens (Anthropic API requirement)
                        # Formula: thinking_budget + generous_response_space
                        thinking_budget = thinking_config.get("budget_tokens", 2000)
                        api_params["max_tokens"] = thinking_budget + 6000  # 2000 thinking + 6000 response
                        
                        if os.environ.get('JARVIS_DEBUG'):
                            print(f"DEBUG: Thinking enabled! Config: {thinking_config}", file=sys.stderr)
                            print(f"DEBUG: max_tokens set to: {api_params['max_tokens']}", file=sys.stderr)
            
            response = self.client.messages.create(**api_params)
            
            # Debug: Show what we got back
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Response has thinking attr: {hasattr(response, 'thinking')}", file=sys.stderr)
                if hasattr(response, 'thinking'):
                    print(f"DEBUG: Thinking content: {response.thinking}", file=sys.stderr)
                print(f"DEBUG: Response type: {type(response)}", file=sys.stderr)
                print(f"DEBUG: Response dir: {[x for x in dir(response) if not x.startswith('_')]}", file=sys.stderr)
            
            # Extract thinking if present
            thinking_text = None
            if enable_thinking:
                from thinking import extract_thinking
                thinking_text = extract_thinking(response, "anthropic")
                if os.environ.get('JARVIS_DEBUG'):
                    print(f"DEBUG: Extracted thinking text: {thinking_text[:100] if thinking_text else 'None'}", file=sys.stderr)
            
            # Extract usage info with cache metrics
            usage_info = None
            if hasattr(response, 'usage') and response.usage:
                from cost_estimator import estimate_cost, estimate_cache_cost
                
                # Get token counts
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                
                # Get cache metrics (if available)
                cache_creation_tokens = getattr(response.usage, 'cache_creation_input_tokens', 0)
                cache_read_tokens = getattr(response.usage, 'cache_read_input_tokens', 0)
                
                # Calculate regular cost (input + output tokens)
                usage_info = estimate_cost(
                    provider="anthropic",
                    model=self.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens
                )
                
                # Calculate cache cost and savings using centralized pricing
                cache_info = estimate_cache_cost(
                    provider="anthropic",
                    model=self.model,
                    cache_creation_tokens=cache_creation_tokens,
                    cache_read_tokens=cache_read_tokens
                )
                
                # Merge cache info into usage_info
                usage_info.update(cache_info)

                # Anthropic reports cache tokens separately from input_tokens/output_tokens.
                # Include them in total_tokens so UI/log totals match provider dashboards.
                usage_info["total_tokens"] = (
                    input_tokens
                    + output_tokens
                    + cache_creation_tokens
                    + cache_read_tokens
                )

                server_tool_use = getattr(response.usage, 'server_tool_use', None)
                web_search_requests = getattr(server_tool_use, 'web_search_requests', 0) or 0
                if web_search_requests > 0:
                    usage_info["server_side_tools"] = {
                        "SERVER_SIDE_TOOL_WEB_SEARCH": web_search_requests
                    }
            
            # Check response type
            # Anthropic may return BOTH text AND tool_use blocks
            # Prioritize tool_use if present
            tool_use_block = None
            
            for block in response.content:
                if block.type == "tool_use":
                    tool_use_block = block
            
            # Return tool use if found (text is just explanatory)
            if tool_use_block:
                return None, {
                    "name": tool_use_block.name,
                    "arguments": tool_use_block.input
                }, usage_info, thinking_text
            
            # Otherwise return text response
            text_content = self._collect_anthropic_text_blocks(response.content)
            if text_content:
                return text_content, None, usage_info, thinking_text
            
            return "No response from Claude", None, usage_info, thinking_text
            
        except Exception as e:
            print(f"Anthropic API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}", None, None, None


class XAIProvider(LLMProvider):
    """
    xAI (Grok) provider with hybrid SDK support.
    
    Features:
    - Current Grok text models from the shared model catalog
    - Grok 4.3 configurable reasoning effort (low/medium/high)
    - Prompt-cache affinity via x-grok-conv-id / SDK metadata
    - Native function calling (OpenAI-compatible)
    - Structured outputs
    - Live Search: When XAI_SEARCH=true, uses xAI SDK Agent Tools API
      for real-time web/X search (server-side tools)
    """
    
    def __init__(self, api_key: str, model: str | None = None):
        """Initialize xAI provider with hybrid SDK support."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")
        
        # Store API key for xAI SDK usage
        self.api_key = api_key
        
        # xAI uses OpenAI-compatible API with custom base URL
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1"
        )
        self.model = model or get_provider_fallback_model("xai")
        self.is_reasoning_model = self._xai_model_is_reasoning(self.model)
        
        # Check if live search is enabled (XAI_SEARCH=true in cloud.env)
        # When enabled, uses xAI SDK with Agent Tools API for web/X search
        from config_loader import get_config_value
        self.enable_search = get_config_value("XAI_SEARCH", "false").lower() == "true"
        
        # Initialize xAI SDK client if search is enabled
        self.xai_client = None
        if self.enable_search:
            try:
                from xai_sdk import Client as XAIClient
                self.xai_client = XAIClient(
                    api_key=api_key,
                    metadata=self._xai_sdk_metadata(),
                )
                if os.environ.get('JARVIS_DEBUG'):
                    print(f"DEBUG: xAI Agent Tools API enabled (web_search + x_search)", file=sys.stderr)
            except ImportError:
                print("WARNING: xai-sdk not installed, falling back to OpenAI SDK without search", file=sys.stderr)
                self.enable_search = False
    
    def chat(self, message: str, system_prompt: str | None = None, max_tokens: int = None) -> str:
        """Simple chat without tools. Uses xAI SDK Agent Tools when XAI_SEARCH=true."""
        if self.enable_search and self.xai_client:
            return self._chat_with_xai_sdk(message, system_prompt, max_tokens)
        
        # Standard OpenAI SDK path (no search)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})
        
        try:
            params = {"model": self.model, "messages": messages}
            effective_max_tokens = max_tokens or self._xai_max_output_tokens()
            if effective_max_tokens:
                params["max_tokens"] = effective_max_tokens
            temperature = self._xai_temperature()
            if temperature is not None:
                params["temperature"] = temperature
            reasoning_effort = self._xai_reasoning_effort()
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort
            extra_headers = self._xai_chat_extra_headers()
            if extra_headers:
                params["extra_headers"] = extra_headers
            
            response = self.client.chat.completions.create(**params)
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"xAI API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"
    
    def _build_xai_server_tools(self):
        """Build list of xAI server-side tools based on config."""
        from xai_sdk.tools import web_search, x_search, code_execution

        if self._xai_env_bool("XAI_DISABLE_SERVER_SIDE_TOOLS", False):
            return []
        
        # Read config for fine-grained control
        enable_code = os.environ.get('XAI_CODE_EXECUTION', 'true').lower() == 'true'
        enable_image = os.environ.get('XAI_IMAGE_UNDERSTANDING', 'true').lower() == 'true'
        enable_video = os.environ.get('XAI_VIDEO_UNDERSTANDING', 'true').lower() == 'true'
        
        tools = [
            web_search(enable_image_understanding=enable_image),
            x_search(enable_image_understanding=enable_image, enable_video_understanding=enable_video),
        ]
        
        if enable_code:
            tools.append(code_execution())
        
        return tools

    @staticmethod
    def _is_retryable_xai_sdk_error(exc: Exception) -> bool:
        """Retry only for transient gRPC/xAI DNS resolver failures."""
        error_text = str(exc).lower()
        retryable_markers = (
            "dns resolution failed",
            "ares_success",
            "grpc_status:14",
            "statuscode.unavailable",
            "dns server returned answer with no data",
            "connection reset by peer",
        )
        return any(marker in error_text for marker in retryable_markers)

    @staticmethod
    def _xai_sdk_retry_delay(attempt: int) -> float:
        """Keep retries short so voice/chat latency stays reasonable."""
        return 0.35 * (2 ** (attempt - 1))

    @staticmethod
    def _xai_max_output_tokens() -> int | None:
        """
        Default output cap for xAI requests when callers do not provide one.

        This mainly protects the xAI SDK Agent Tools path, which otherwise can
        return very large outputs on heavy Grok models like grok-4.3.
        """
        raw = os.environ.get('XAI_MAX_OUTPUT_TOKENS', '4096').strip()
        if not raw:
            return None
        try:
            value = int(raw)
            return value if value > 0 else None
        except ValueError:
            return 4096

    @staticmethod
    def _xai_temperature() -> float | None:
        """
        Default temperature for xAI requests when configured.

        Lower values generally behave better for tool-heavy Jarvis flows by
        reducing exploratory branching and redundant search retries.
        """
        raw = os.environ.get('XAI_TEMPERATURE', '').strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            return 0.7
        return min(2.0, max(0.0, value))

    @staticmethod
    def _usage_field(obj: Any, key: str) -> Any:
        """Read usage fields from SDK objects or dict-like payloads."""
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    @staticmethod
    def _xai_model_supports_reasoning_effort(model: str) -> bool:
        """Only Grok 4.3 supports configurable reasoning effort today."""
        normalized = (model or "").strip().lower()
        return normalized == "grok-4.3" or normalized.startswith("grok-4.3-")

    @classmethod
    def _xai_model_is_reasoning(cls, model: str) -> bool:
        normalized = (model or "").strip().lower()
        if "non-reasoning" in normalized or "non_reasoning" in normalized:
            return False
        return cls._xai_model_supports_reasoning_effort(normalized) or "reasoning" in normalized

    def _xai_reasoning_effort(self) -> str | None:
        """
        Optional Grok 4.3 reasoning-effort override.

        xAI docs currently support low/medium/high only for grok-4.3. Other
        Grok reasoning models reason automatically and reject this parameter.
        """
        raw = os.environ.get("XAI_REASONING_EFFORT", "").strip().lower()
        if not raw:
            return None

        allowed = {"low", "medium", "high"}
        if raw not in allowed:
            print(
                f"WARNING: Ignoring invalid XAI_REASONING_EFFORT={raw!r}; "
                "expected low, medium, or high",
                file=sys.stderr,
            )
            return None

        if not self._xai_model_supports_reasoning_effort(self.model):
            if os.environ.get("JARVIS_DEBUG"):
                print(
                    f"DEBUG: {self.model} does not support XAI_REASONING_EFFORT; "
                    "omitting reasoning_effort",
                    file=sys.stderr,
                )
            return None

        return raw

    def _xai_prompt_cache_key(self) -> str | None:
        """Stable xAI cache-affinity key for Chat Completions and SDK/gRPC paths."""
        explicit = (
            os.environ.get("XAI_PROMPT_CACHE_KEY")
            or os.environ.get("XAI_GROK_CONV_ID")
            or os.environ.get("XAI_CONV_ID")
            or ""
        ).strip()
        if explicit:
            return explicit

        if not self._xai_env_bool("XAI_PROMPT_CACHE_ENABLED", True):
            return None

        namespace = (os.environ.get("XAI_PROMPT_CACHE_NAMESPACE") or "jarvis-voice").strip()
        seed = f"{namespace}|{self.api_key or ''}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
        return f"jarvis_{digest}"

    def _xai_chat_extra_headers(self) -> dict[str, str] | None:
        cache_key = self._xai_prompt_cache_key()
        if not cache_key:
            return None
        return {"x-grok-conv-id": cache_key}

    def _xai_sdk_metadata(self) -> tuple[tuple[str, str], ...] | None:
        cache_key = self._xai_prompt_cache_key()
        if not cache_key:
            return None
        return (("x-grok-conv-id", cache_key),)

    def _sample_xai_chat_with_retry(self, chat: Any):
        """Give transient xAI SDK DNS/gRPC failures one quick retry."""
        max_attempts = 2
        last_exception: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                return chat.sample()
            except Exception as exc:
                last_exception = exc
                if attempt >= max_attempts or not self._is_retryable_xai_sdk_error(exc):
                    raise

                delay = self._xai_sdk_retry_delay(attempt)
                print(
                    f"xAI SDK transient error on attempt {attempt}/{max_attempts}: {exc}. "
                    f"Retrying in {delay:.2f}s",
                    file=sys.stderr
                )
                time.sleep(delay)

        raise last_exception or RuntimeError("xAI SDK retry failed without an exception")
    
    def _chat_with_xai_sdk(self, message: str, system_prompt: str | None = None, max_tokens: int = None) -> str:
        """Simple chat using xAI SDK with server-side tools."""
        try:
            from xai_sdk.chat import user, system as sys_msg

            create_kwargs = self._xai_sdk_create_kwargs(
                tools=self._build_xai_server_tools(),
                max_tokens=max_tokens,
            )

            chat = self.xai_client.chat.create(**create_kwargs)
            
            # Add system prompt if provided
            if system_prompt:
                chat.append(sys_msg(system_prompt))
            
            # Add user message
            chat.append(user(message))
            
            # Get response (non-streaming for simple chat)
            response = self._sample_xai_chat_with_retry(chat)
            
            return response.content or ""
        except Exception as e:
            print(f"xAI SDK error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"

    @staticmethod
    def _xai_max_turns() -> int | None:
        """Optional cap on server-side tool iterations (web_search + x_search loops).

        Reads XAI_SERVER_SIDE_MAX_TOOL_TURNS from env. When unset or invalid,
        returns None and xAI uses its server-side default. Set this to bound
        cost/latency on very tool-heavy queries (e.g. ones that trigger many
        web_search calls). Narrowly scoped to xAI's server-side Agent Tools
        loop (web_search, x_search, code_execution); unrelated to the
        orchestrator's MAX_TOOL_TURNS which bounds client-side tool iteration.
        """
        raw = os.environ.get('XAI_SERVER_SIDE_MAX_TOOL_TURNS', '').strip()
        if not raw:
            return None
        try:
            value = int(raw)
            return value if value > 0 else None
        except ValueError:
            return None
    
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False,
        previous_response_id: str | None = None,
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """
        Send chat with xAI function calling and optional reasoning mode.
        
        When XAI_SEARCH=true, uses xAI SDK Agent Tools API which combines:
        - Server-side tools: web_search, x_search (executed by xAI automatically)
        - Client-side tools: Our custom tools (returned as tool_calls for us to execute)
        
        Returns:
            Tuple of (text_response, tool_call, usage_info, thinking)
            - usage_info contains token counts and cost estimates
            - thinking contains reasoning text for reasoning models
        """
        if self.enable_search and self.xai_client:
            return self._chat_with_tools_xai_sdk(
                messages,
                tools,
                system_prompt,
                enable_thinking,
                previous_response_id=previous_response_id,
            )
        
        # Standard OpenAI SDK path (no search)
        return self._chat_with_tools_openai_sdk(messages, tools, system_prompt, enable_thinking)
    
    def _chat_with_tools_openai_sdk(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False,
        previous_response_id: str | None = None,
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """Standard chat with tools using OpenAI SDK (no search)."""
        # Add system message if provided
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        
        try:
            # xAI uses OpenAI-compatible tool format
            request_params = {
                "model": self.model,
                "messages": full_messages,
                "max_tokens": max(1024, self._xai_max_output_tokens() or 1024)
            }
            temperature = self._xai_temperature()
            if temperature is not None:
                request_params["temperature"] = temperature
            reasoning_effort = self._xai_reasoning_effort()
            if reasoning_effort:
                request_params["reasoning_effort"] = reasoning_effort
            extra_headers = self._xai_chat_extra_headers()
            if extra_headers:
                request_params["extra_headers"] = extra_headers
            
            # Only add tools if provided
            if tools:
                request_params["tools"] = tools
                request_params["tool_choice"] = "auto"
            
            response = self.client.chat.completions.create(**request_params)
            
            message = response.choices[0].message
            
            # Extract reasoning/thinking for reasoning models
            thinking_text = None
            if self.is_reasoning_model and enable_thinking:
                if hasattr(message, 'reasoning_content'):
                    thinking_text = message.reasoning_content
                elif hasattr(response, 'reasoning'):
                    thinking_text = response.reasoning
            
            # Extract usage info
            usage_info = None
            if hasattr(response, 'usage') and response.usage:
                from cost_estimator import estimate_cost
                usage_info = estimate_cost(
                    provider="xai",
                    model=self.model,
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens
                )
                prompt_details = getattr(response.usage, "prompt_tokens_details", None)
                prompt_text_tokens = self._usage_field(prompt_details, "text_tokens")
                cached_tokens = self._usage_field(prompt_details, "cached_tokens")
                if prompt_text_tokens is not None:
                    usage_info["prompt_text_tokens"] = prompt_text_tokens
                if cached_tokens is not None:
                    usage_info["cached_prompt_text_tokens"] = cached_tokens
                    usage_info["cache_read_tokens"] = cached_tokens
                if reasoning_effort:
                    usage_info["xai_reasoning_effort"] = reasoning_effort
            
            # Check if tool was called
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                return None, {
                    "name": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments)
                }, usage_info, thinking_text
            
            # Otherwise return text response
            return message.content, None, usage_info, thinking_text
            
        except Exception as e:
            print(f"xAI API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}", None, None, None
    
    def _convert_tool_to_xai_sdk(self, tool: dict[str, Any]):
        """Convert a client-side tool definition using xAI SDK's public helper."""
        from xai_sdk.chat import tool as xai_tool

        # Handle OpenAI format: {"type": "function", "function": {...}}
        if tool.get("type") == "function":
            func_def = tool.get("function", {})
        else:
            # Handle Anthropic format: {"name": "...", "description": "...", "input_schema": {...}}
            func_def = tool

        # Parameters can be in "parameters" (OpenAI) or "input_schema" (Anthropic)
        params = func_def.get("parameters") or func_def.get("input_schema") or {
            "type": "object",
            "properties": {},
        }

        return xai_tool(
            name=func_def.get("name", ""),
            description=func_def.get("description", ""),
            parameters=params,
        )

    @staticmethod
    def _xai_env_bool(name: str, default: bool = False) -> bool:
        """Read an xAI boolean env knob without pulling config at call time."""
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def _xai_sdk_create_kwargs(
        self,
        *,
        tools: list[Any],
        max_tokens: int | None = None,
        force_serial_tool_calls: bool = False,
        previous_response_id: str | None = None,
    ) -> dict[str, Any]:
        """Build common xAI SDK chat.create kwargs for simple and tool chats."""
        create_kwargs: dict[str, Any] = {
            "model": self.model,
            "tools": tools,
        }
        effective_max_tokens = max_tokens or self._xai_max_output_tokens()
        if effective_max_tokens:
            create_kwargs["max_tokens"] = effective_max_tokens
        temperature = self._xai_temperature()
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        reasoning_effort = self._xai_reasoning_effort()
        if reasoning_effort:
            create_kwargs["reasoning_effort"] = reasoning_effort
        max_turns = self._xai_max_turns()
        if max_turns:
            create_kwargs["max_turns"] = max_turns

        # The provider currently returns one client-side tool call at a time.
        # Keep xAI aligned with that contract on tool-routing calls unless
        # explicitly overridden.
        if "XAI_PARALLEL_TOOL_CALLS" in os.environ:
            create_kwargs["parallel_tool_calls"] = self._xai_env_bool("XAI_PARALLEL_TOOL_CALLS", False)
        elif force_serial_tool_calls:
            create_kwargs["parallel_tool_calls"] = False

        use_stored_continuation = (
            bool(previous_response_id)
            and self._xai_env_bool("XAI_STORE_MESSAGES", False)
        )

        if self._xai_env_bool("XAI_STORE_MESSAGES", False):
            create_kwargs["store_messages"] = True
        if self._xai_env_bool("XAI_USE_ENCRYPTED_CONTENT", False):
            create_kwargs["use_encrypted_content"] = True
        if use_stored_continuation:
            create_kwargs["previous_response_id"] = previous_response_id

        return create_kwargs

    @staticmethod
    def _stringify_xai_content(content: Any) -> str:
        """Render message/tool content to a string for xAI SDK helpers."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        try:
            return json.dumps(content)
        except TypeError:
            return str(content)

    @staticmethod
    def _build_xai_assistant_message_from_openai(msg: dict[str, Any]):
        """Preserve assistant tool_call history when callers pass OpenAI-style messages."""
        from xai_sdk.chat import chat_pb2, text

        message = chat_pb2.Message(role=chat_pb2.MessageRole.ROLE_ASSISTANT)
        content = XAIProvider._stringify_xai_content(msg.get("content"))
        if content:
            message.content.append(text(content))

        for raw_tool_call in msg.get("tool_calls") or []:
            tool_call = chat_pb2.ToolCall(
                id=raw_tool_call.get("id", ""),
                type=chat_pb2.ToolCallType.TOOL_CALL_TYPE_CLIENT_SIDE_TOOL,
                status=chat_pb2.ToolCallStatus.TOOL_CALL_STATUS_COMPLETED,
            )
            function_data = raw_tool_call.get("function") or {}
            tool_call.function.name = function_data.get("name", "")
            raw_arguments = function_data.get("arguments", "{}")
            tool_call.function.arguments = (
                raw_arguments if isinstance(raw_arguments, str) else json.dumps(raw_arguments)
            )
            message.tool_calls.append(tool_call)

        return message

    @staticmethod
    def _xai_tool_call_payload(tool_call: Any) -> dict[str, Any]:
        """Return the Jarvis tool-call shape while preserving xAI IDs for continuation."""
        raw_arguments = tool_call.function.arguments
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        payload = {
            "name": tool_call.function.name,
            "arguments": arguments or {},
        }
        tool_call_id = getattr(tool_call, "id", None)
        if tool_call_id:
            payload["id"] = tool_call_id
            payload["tool_call_id"] = tool_call_id
        return payload

    @staticmethod
    def _is_xai_previous_response_error(exc: Exception) -> bool:
        """Detect stored-state misses so Jarvis can retry with local text context."""
        text = str(exc).lower()
        markers = (
            "previous_response_not_found",
            "previous response not found",
            "previous_response_id",
            "response id not found",
            "stored conversation",
        )
        return any(marker in text for marker in markers)

    def _extract_xai_sdk_usage(self, response: Any) -> dict[str, Any] | None:
        """Extract xAI SDK usage, preferring server-reported cost when available."""
        usage = getattr(response, "usage", None)
        if not usage:
            return None

        from cost_estimator import estimate_cost

        input_tokens = (
            getattr(usage, "prompt_tokens", 0)
            or getattr(usage, "prompt_text_tokens", 0)
            or 0
        )
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        usage_info = estimate_cost(
            provider="xai",
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        exact_cost = getattr(response, "cost_usd", None)
        if exact_cost is not None:
            usage_info["cost_usd"] = exact_cost

        for key in (
            "reasoning_tokens",
            "prompt_text_tokens",
            "cached_prompt_text_tokens",
            "prompt_image_tokens",
            "num_sources_used",
        ):
            value = getattr(usage, key, None)
            if value is not None:
                usage_info[key] = value
                if key == "cached_prompt_text_tokens":
                    usage_info["cache_read_tokens"] = value

        reasoning_effort = self._xai_reasoning_effort()
        if reasoning_effort:
            usage_info["xai_reasoning_effort"] = reasoning_effort

        server_tool_usage = getattr(response, "server_side_tool_usage", None)
        if server_tool_usage:
            usage_info["server_side_tools"] = server_tool_usage

        return usage_info
    
    def _chat_with_tools_xai_sdk(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False,
        previous_response_id: str | None = None,
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """
        Chat with tools using xAI SDK Agent Tools API.
        
        Combines server-side search tools (web_search, x_search) with our client-side tools.
        The model decides when to use search vs our tools.
        Server-side tools are executed automatically by xAI.
        Client-side tools are returned for us to execute.
        
        Supports OpenAI-style assistant tool-call history and role="tool" results
        via xai_sdk.chat.tool_result. Jarvis' main orchestrator still usually
        feeds previous tool results as plain text, but direct callers can now
        keep the native xAI SDK path for hybrid multi-turn conversations.
        """
        use_continuation = False
        try:
            from xai_sdk.chat import user, system as sys_msg, assistant, tool_result
            from xai_sdk.tools import get_tool_call_type
            use_continuation = (
                bool(previous_response_id)
                and self._xai_env_bool("XAI_STORE_MESSAGES", False)
            )
            
            # Build xAI SDK tools list: server-side tools (configurable) + client-side custom tools
            xai_tools = self._build_xai_server_tools()
            
            # Convert our custom tools through the SDK helper to avoid protobuf drift.
            for tool in tools:
                xai_tool = self._convert_tool_to_xai_sdk(tool)
                xai_tools.append(xai_tool)
            
            create_kwargs = self._xai_sdk_create_kwargs(
                tools=xai_tools,
                force_serial_tool_calls=True,
                previous_response_id=previous_response_id,
            )
            if os.environ.get('JARVIS_DEBUG') and use_continuation:
                print(
                    "DEBUG: xAI using stored continuation with "
                    f"previous_response_id={previous_response_id[:16]}...",
                    file=sys.stderr,
                )

            chat = self.xai_client.chat.create(**create_kwargs)
            
            # previous_response_id prepends the stored conversation, including
            # its original system message, on the xAI side.
            if system_prompt and not use_continuation:
                chat.append(sys_msg(system_prompt))
            
            # Add conversation history. OpenAI-style assistant tool_calls are
            # preserved so role="tool" messages can stay on the xAI SDK path.
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                
                if role == "user":
                    chat.append(user(self._stringify_xai_content(content)))
                elif role == "system":
                    chat.append(sys_msg(self._stringify_xai_content(content)))
                elif role == "assistant":
                    if msg.get("tool_calls"):
                        chat.append(self._build_xai_assistant_message_from_openai(msg))
                    else:
                        chat.append(assistant(self._stringify_xai_content(content)))
                elif role == "tool":
                    chat.append(tool_result(
                        self._stringify_xai_content(content),
                        tool_call_id=msg.get("tool_call_id") or msg.get("id"),
                    ))
            
            # Get response (non-streaming for now)
            response = self._sample_xai_chat_with_retry(chat)
            
            usage_info = self._extract_xai_sdk_usage(response)
            
            # Check for client-side tool calls (our custom tools)
            # Server-side tools (web_search, x_search) are handled automatically by xAI
            if hasattr(response, 'tool_calls') and response.tool_calls:
                client_side_tool_calls = [
                    tc for tc in response.tool_calls
                    if get_tool_call_type(tc) == "client_side_tool"
                ]
                if len(client_side_tool_calls) > 1:
                    names = [
                        getattr(getattr(tc, "function", None), "name", "unknown")
                        for tc in client_side_tool_calls
                    ]
                    print(
                        "WARNING: xAI returned multiple client-side tool calls; "
                        f"Jarvis executes one per router turn, taking first deterministically: {names}",
                        file=sys.stderr,
                    )
                if client_side_tool_calls:
                    tc = client_side_tool_calls[0]
                    payload = self._xai_tool_call_payload(tc)
                    response_id = getattr(response, "id", None)
                    if response_id:
                        payload["response_id"] = response_id
                    if len(client_side_tool_calls) > 1:
                        payload["additional_tool_call_count"] = len(client_side_tool_calls) - 1
                    return None, payload, usage_info, None
            
            # No client-side tool calls - return the response
            # (may include results from server-side search tools)
            content = response.content or ""
            
            # Include citations if available
            if hasattr(response, 'citations') and response.citations:
                # Append citations to response for transparency
                citations_text = "\n\nSources:\n" + "\n".join(f"- {url}" for url in response.citations[:5])
                content += citations_text
            
            return content, None, usage_info, None
            
        except Exception as e:
            import traceback
            print(f"xAI SDK error: {e}", file=sys.stderr)
            if os.environ.get('JARVIS_DEBUG'):
                traceback.print_exc()
            if use_continuation:
                if self._is_xai_previous_response_error(e):
                    print(
                        "xAI stored continuation expired/not found; retrying with text context",
                        file=sys.stderr,
                    )
                    return "Error: previous_response_not_found", None, None, None
                return f"Error: xAI stored continuation failed: {str(e)}", None, None, None
            # Fallback to OpenAI SDK without search
            print("Falling back to OpenAI SDK without search", file=sys.stderr)
            return self._chat_with_tools_openai_sdk(messages, tools, system_prompt, enable_thinking)


class OllamaProvider(LLMProvider):
    """Ollama provider using native tool calling API (Ollama 0.3.0+)."""
    
    def __init__(self, base_url: str, model: str):
        """Initialize Ollama provider."""
        self.base_urls = parse_ollama_base_urls(base_url)
        self.base_url = self.base_urls[0]
        self.model = model

    @staticmethod
    def _strip_reasoning_content(text: str) -> str:
        """Remove inline reasoning wrappers from providers that mix them into content."""
        import re

        if not text:
            return text

        cleaned = text

        # Closed XML-style think / reasoning tags.
        cleaned = re.sub(r'<think>.*?</think>\s*', '', cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r'<reasoning>.*?</reasoning>\s*', '', cleaned, flags=re.IGNORECASE | re.DOTALL)

        # Unclosed <think>/<reasoning> — cloud models sometimes omit the
        # closing tag.  Strip from the opening tag up to (not including) the
        # first '{' so any trailing JSON is preserved.
        cleaned = re.sub(r'<think>[^{]*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'<reasoning>[^{]*', '', cleaned, flags=re.IGNORECASE)

        # Ollama CLI-style wrappers occasionally leak into content on some hosted models.
        cleaned = re.sub(
            r'^\s*Thinking\.\.\..*?\.\.\.done thinking\.\s*',
            '',
            cleaned,
            flags=re.IGNORECASE | re.DOTALL
        )

        return cleaned.strip()
    
    def chat(self, message: str, system_prompt: str | None = None, max_tokens: int = None) -> str:
        """Simple chat without tools."""
        import requests
        import sys
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})
        
        try:
            request_data = {
                "model": self.model,
                "messages": messages,
                "stream": False
            }

            # Some evaluator-style prompts require strict JSON. Ollama models are
            # more reliable when we explicitly request JSON mode at the API layer.
            prompt_text = f"{system_prompt or ''}\n{message}".lower()
            json_mode = (
                'return json only' in prompt_text
                or 'return valid json only' in prompt_text
                or '"recommended_action"' in prompt_text
            )
            # Cloud-tagged models (e.g. minimax-m2.5:cloud) proxy to a remote
            # backend that doesn't support Ollama's grammar-level structured
            # format schema.  Use simple "json" format instead.
            is_cloud = ':cloud' in self.model.lower()

            if json_mode:
                request_data["think"] = False
                if '"recommended_action"' in prompt_text and not is_cloud:
                    request_data["format"] = {
                        "type": "object",
                        "properties": {
                            "recommended_action": {
                                "type": "string",
                                "enum": ["accept", "tighten_only", "repair_required"]
                            },
                            "task_status": {
                                "type": "string",
                                "enum": ["complete", "partial", "unsupported", "failed"]
                            },
                            "risk_level": {
                                "type": "string",
                                "enum": ["low", "medium", "high", "critical"]
                            },
                            "repair_worthwhile": {"type": "boolean"},
                            "failure_types": {"type": "array", "items": {"type": "string"}},
                            "missing_requirements": {"type": "array", "items": {"type": "string"}},
                            "unsupported_claims": {"type": "array", "items": {"type": "string"}},
                            "contradictions": {"type": "array", "items": {"type": "string"}},
                            "evidence_gaps": {"type": "array", "items": {"type": "string"}},
                            "reason": {"type": "string"},
                            "suggested_note": {"type": "string"}
                        },
                        "required": [
                            "recommended_action",
                            "task_status",
                            "risk_level",
                            "repair_worthwhile",
                            "failure_types",
                            "missing_requirements",
                            "unsupported_claims",
                            "contradictions",
                            "evidence_gaps",
                            "reason",
                            "suggested_note"
                        ]
                    }
                else:
                    request_data["format"] = "json"
            
            # Extended context for capable models
            options = self._get_context_options()
            if json_mode:
                options["temperature"] = 0
            
            if max_tokens:
                # Cloud-tagged models count thinking tokens against
                # num_predict (think:false is ignored by remote backends).
                # Multiply budget so the model has room for both reasoning
                # and the actual JSON content.
                options["num_predict"] = max_tokens * 4 if is_cloud else max_tokens
            
            if options:
                request_data["options"] = options
            
            response, used_base_url = request_ollama(
                "post",
                "/api/chat",
                base_urls=self.base_urls,
                json=request_data,
                timeout=180  # 3 minutes for local models (qwen3-vl is heavy)
            )
            self.base_url = used_base_url
            response.raise_for_status()
            
            result = response.json()
            msg = result.get("message", {})
            content = msg.get("content", "")

            # Cloud models may exhaust the token budget on internal
            # reasoning, leaving content empty.  Fall back to the
            # separate thinking field which may contain extractable data.
            if json_mode and not (content or '').strip():
                thinking_fallback = msg.get("thinking", "") or result.get("thinking", "")
                if thinking_fallback:
                    content = thinking_fallback
                    if os.environ.get('JARVIS_DEBUG'):
                        print(
                            f"DEBUG: Ollama cloud empty content, using thinking fallback "
                            f"({len(thinking_fallback)} chars) - model={self.model}",
                            file=sys.stderr
                        )
                else:
                    preview = json.dumps(result, default=str)[:1200]
                    print(
                        f"DEBUG: Ollama JSON-mode empty content - model={self.model}, result={preview}",
                        file=sys.stderr
                    )
            return self._strip_reasoning_content(content) if json_mode else content
        except Exception as e:
            print(f"Ollama API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"
    
    def _get_context_options(self) -> dict[str, Any]:
        """Get context window options for the current model."""
        options = {}
        # For Ollama-backed requests, always honor the configured context window.
        # Whether the model/runtime can fully use that budget is up to Ollama/model support,
        # but the app should consistently request the configured window instead of using a
        # hardcoded allowlist of model names.
        from config_loader import get_int
        context_window = get_int('OLLAMA_CONTEXT_WINDOW', 32000)
        if context_window and context_window > 0:
            options["num_ctx"] = context_window
        return options
    
    def _convert_to_ollama_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Convert tools from Anthropic format to Ollama/OpenAI native format.
        
        Anthropic format (input):
        {"name": "...", "description": "...", "input_schema": {...}}
        
        Ollama format (output):
        {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
        """
        ollama_tools = []
        for tool in tools:
            # Handle both Anthropic format (input_schema) and OpenAI format (parameters)
            parameters = tool.get("input_schema") or tool.get("parameters", {})
            
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", "unknown"),
                    "description": tool.get("description", ""),
                    "parameters": parameters
                }
            })
        return ollama_tools

    def _build_tool_contract_prompt(self, tools: list[dict[str, Any]]) -> str:
        """Build a strict tool-calling contract for local models."""
        if not tools:
            return ""

        tool_lines = []
        for tool in tools:
            name = tool.get("name", "unknown")
            schema = tool.get("input_schema") or tool.get("parameters") or {}
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            required = set(schema.get("required", [])) if isinstance(schema, dict) else set()
            if properties:
                params = ", ".join(
                    f"{param}{'*' if param in required else ''}"
                    for param in properties.keys()
                )
            else:
                params = "no parameters"
            tool_lines.append(f"- {name}: {params}")

        return (
            "TOOL CALL CONTRACT:\n"
            "- Use ONLY the exact tool/function names listed below.\n"
            "- Tool names are snake_case; copy them exactly as shown.\n"
            "- Use ONLY argument keys defined for the selected tool.\n"
            "- Never invent aliases, wrappers, or API-style names such as get_*, *_api, or *_tool.\n"
            "- If you are unsure which tool fits and tool_search is listed, call tool_search first.\n"
            "- If none of these tools exactly fit and tool_search is not listed, do not call a tool.\n"
            "- Required parameters are marked with *.\n\n"
            "Exact tool names and parameters:\n"
            f"{chr(10).join(tool_lines)}"
        )
    
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False,
        previous_response_id: str | None = None,
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """
        Send chat with Ollama using native tool calling API with structured prompting fallback.
        
        This uses Ollama's native tool calling (available since v0.3.0) which is more
        reliable than structured prompting, especially for models like ministral-3.
        
        For models that don't support native tool calling (e.g., deepseek-r1), it falls
        back to structured prompting where tools are described in the system prompt.
        
        Returns:
            Tuple of (text_response, tool_call, usage_info, thinking)
            - usage_info contains token counts (cost is always 0 for local models)
            - thinking is available for reasoning models (qwen3.5:latest, etc.)
        """
        import requests
        import os
        
        # Convert tools to Ollama/OpenAI format
        ollama_tools = self._convert_to_ollama_tools(tools) if tools else []
        
        # Build full messages with system prompt
        full_messages = []
        effective_system_prompt = system_prompt or ""
        tool_contract_prompt = self._build_tool_contract_prompt(tools)
        if tool_contract_prompt:
            effective_system_prompt = (
                f"{effective_system_prompt}\n\n{tool_contract_prompt}".strip()
            )
        if effective_system_prompt:
            full_messages.append({"role": "system", "content": effective_system_prompt})
        full_messages.extend(messages)
        
        try:
            # Build request
            request_data = {
                "model": self.model,
                "messages": full_messages,
                "stream": False,
                "think": bool(enable_thinking),
            }
            
            # Add tools if provided (native tool calling)
            if ollama_tools:
                request_data["tools"] = ollama_tools
            
            # Set context window options
            options = self._get_context_options()
            if options:
                request_data["options"] = options
            
            # Debug logging
            if os.environ.get('JARVIS_DEBUG'):
                debug_options = request_data.get("options", {})
                print(
                    f"DEBUG: Ollama request - model={self.model}, tools={len(ollama_tools)}, "
                    f"messages={len(full_messages)}, think={request_data.get('think')}, "
                    f"num_ctx={debug_options.get('num_ctx')}",
                    file=sys.stderr
                )
            
            response, used_base_url = request_ollama(
                "post",
                "/api/chat",
                base_urls=self.base_urls,
                json=request_data,
                timeout=180  # 3 minutes for local models
            )
            self.base_url = used_base_url
            
            # Check for "does not support tools" error (HTTP 400) - fall back to structured prompting
            if response.status_code == 400:
                try:
                    error_data = response.json()
                    if "does not support tools" in error_data.get("error", ""):
                        if os.environ.get('JARVIS_DEBUG'):
                            print(f"DEBUG: Model {self.model} doesn't support native tools, falling back to structured prompting", file=sys.stderr)
                        return self._chat_with_tools_structured(messages, tools, system_prompt, enable_thinking)
                except json.JSONDecodeError:
                    pass
            
            response.raise_for_status()
            
            result = response.json()
            message = result.get("message", {})
            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])
            
            # Extract token counts from Ollama response
            usage_info = None
            eval_count = result.get("eval_count", 0)
            prompt_eval_count = result.get("prompt_eval_count", 0)
            if eval_count or prompt_eval_count:
                usage_info = {
                    "input_tokens": prompt_eval_count,
                    "output_tokens": eval_count,
                    "total_tokens": prompt_eval_count + eval_count,
                    "cost_usd": 0.0,  # Local models have no cost
                    "note": "local model - no cost"
                }
            
            # Extract thinking if present (qwen3.5:latest and other reasoning models)
            thinking = None
            if "thinking" in message:
                thinking = message["thinking"]
            elif "thinking" in result:
                thinking = result["thinking"]
            
            # Check if tool was called (native tool calling response)
            if tool_calls:
                # Take the first tool call
                tool_call = tool_calls[0]
                function_data = tool_call.get("function", {})
                
                # Parse arguments - can be dict or JSON string
                arguments = function_data.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                
                raw_call = {
                    "name": function_data.get("name", ""),
                    "arguments": arguments
                }
                
                # Apply smart corrections for local models
                from local_model_corrections import correct_tool_call
                corrected_call = correct_tool_call(raw_call)
                
                if os.environ.get('JARVIS_DEBUG'):
                    print(f"DEBUG: Ollama tool call - {corrected_call['name']} with {corrected_call['arguments']}", file=sys.stderr)
                
                return None, corrected_call, usage_info, thinking
            
            # No tool call - return text response (Q&A mode)
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Ollama Q&A response - {len(content)} chars", file=sys.stderr)
            
            return content, None, usage_info, thinking
            
        except requests.exceptions.Timeout:
            print(f"Ollama API timeout after 180s", file=sys.stderr)
            return "Error: Request timed out. The model may be overloaded.", None, None, None
        except Exception as e:
            print(f"Ollama API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}", None, None, None
    
    def _chat_with_tools_structured(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """
        Fallback: Send chat using structured prompting for models that don't support native tools.
        
        This is used for models like deepseek-r1 that don't have native tool calling support.
        Tools are described in the system prompt and the model is asked to output JSON.
        """
        import requests
        import os
        
        # Build tool descriptions for prompt
        tools_text = self._format_tools_for_prompt(tools)
        
        # Create enhanced system prompt with tool instructions
        tool_contract_prompt = self._build_tool_contract_prompt(tools)
        enhanced_system = f"""{system_prompt or 'You are a helpful AI assistant.'}

{tool_contract_prompt}

You have access to the following tools. When the user's request matches a tool's capability, respond with a JSON tool call in this EXACT format:
{{"tool": "tool_name", "arguments": {{"param": "value"}}}}

If the request doesn't match any tool, respond normally in plain text.

Available Tools:
{tools_text}

CRITICAL RULES: 
- If using a tool, output ONLY the JSON object on a single line, nothing else.
- NO markdown formatting like **bold** or code blocks
- NO explanatory text before or after the JSON
- NO newlines or extra whitespace
- JUST the JSON: {{"tool": "name", "arguments": {{}}}}
- The "tool" value must exactly match one of the listed tool names.
- Tool names are snake_case; copy them exactly as listed.
- Argument keys must exactly match that tool's schema.
- Do not invent aliases like "get_crypto_price" or "crypto_api".
- If you are unsure which tool fits and tool_search is listed, call tool_search first.
- If not using a tool, respond in plain conversational text without any JSON.
"""
        
        # Build full messages
        full_messages = [{"role": "system", "content": enhanced_system}]
        full_messages.extend(messages)
        
        try:
            request_data = {
                "model": self.model,
                "messages": full_messages,
                "stream": False,
                "think": bool(enable_thinking),
            }
            
            # Set context window options
            options = self._get_context_options()
            if options:
                request_data["options"] = options
            
            if os.environ.get('JARVIS_DEBUG'):
                debug_options = request_data.get("options", {})
                print(
                    f"DEBUG: Ollama structured prompting fallback - model={self.model}, "
                    f"think={request_data.get('think')}, num_ctx={debug_options.get('num_ctx')}",
                    file=sys.stderr
                )
            
            response, used_base_url = request_ollama(
                "post",
                "/api/chat",
                base_urls=self.base_urls,
                json=request_data,
                timeout=180
            )
            self.base_url = used_base_url
            response.raise_for_status()
            
            result = response.json()
            content = result.get("message", {}).get("content", "")
            parse_content = self._strip_reasoning_content(content)
            
            # Extract token counts
            usage_info = None
            eval_count = result.get("eval_count", 0)
            prompt_eval_count = result.get("prompt_eval_count", 0)
            if eval_count or prompt_eval_count:
                usage_info = {
                    "input_tokens": prompt_eval_count,
                    "output_tokens": eval_count,
                    "total_tokens": prompt_eval_count + eval_count,
                    "cost_usd": 0.0,
                    "note": "local model - no cost (structured prompting fallback)"
                }
            
            # Extract thinking if present
            thinking = None
            if "thinking" in result.get("message", {}):
                thinking = result["message"]["thinking"]
            elif "thinking" in result:
                thinking = result["thinking"]
            
            # Try to parse as tool call (handle markdown-wrapped JSON)
            try:
                stripped = parse_content.strip()
                
                # Remove markdown code blocks if present
                if stripped.startswith("```json"):
                    stripped = stripped[7:]
                    if stripped.endswith("```"):
                        stripped = stripped[:-3]
                elif stripped.startswith("```"):
                    stripped = stripped[3:]
                    if stripped.endswith("```"):
                        stripped = stripped[:-3]
                
                # Extract JSON if present
                if "{" in stripped and "}" in stripped:
                    start = stripped.index("{")
                    end = stripped.rindex("}") + 1
                    json_str = stripped[start:end]
                    
                    tool_call = json.loads(json_str)
                    if "tool" in tool_call:
                        raw_call = {
                            "name": tool_call["tool"],
                            "arguments": tool_call.get("arguments", {})
                        }
                        
                        # Apply smart corrections for local models
                        from local_model_corrections import correct_tool_call
                        corrected_call = correct_tool_call(raw_call)
                        
                        return None, corrected_call, usage_info, thinking
            except (json.JSONDecodeError, ValueError):
                pass
            
            # Otherwise return as text (Q&A mode)
            return content, None, usage_info, thinking
            
        except Exception as e:
            print(f"Ollama API error (structured fallback): {e}", file=sys.stderr)
            return f"Error: {str(e)}", None, None, None
    
    def _format_tools_for_prompt(self, tools: list[dict[str, Any]]) -> str:
        """Format tools as text for fallback structured prompting."""
        tool_descriptions = []
        for tool in tools:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            schema = tool.get("input_schema", {})
            
            params = []
            if "properties" in schema:
                for param_name, param_info in schema["properties"].items():
                    param_type = param_info.get("type", "string")
                    param_desc = param_info.get("description", "")
                    params.append(f"  - {param_name} ({param_type}): {param_desc}")
            
            params_str = "\n".join(params) if params else "  No parameters"
            tool_descriptions.append(f"- {name}: {desc}\nParameters:\n{params_str}")
        
        return "\n\n".join(tool_descriptions)


def create_configured_provider(
    provider_override: str | None = None,
    model_override: str | None = None,
    provider_config_keys: tuple[str, ...] = ("LLM_PROVIDER",),
    model_config_keys: tuple[str, ...] = (),
    default_provider: str = "openai",
    disable_server_side_tools: bool = False,
) -> tuple[str, str | None, LLMProvider]:
    """
    Create an LLM provider from Jarvis config with optional task-specific keys.

    Args:
        provider_override: Explicit provider name, if supplied by the caller.
        model_override: Explicit model name, if supplied by the caller.
        provider_config_keys: Config keys to try before falling back to default_provider.
        model_config_keys: Task-specific model config keys to try before provider defaults.
        default_provider: Provider to use when no configured provider is found.
        disable_server_side_tools: Temporarily disable provider-native tools
            during provider init for plain text processing tasks.

    Returns:
        Tuple of (provider_type, model_name, provider_instance)
    """
    from config_loader import get_config_value

    def first_config_value(keys: tuple[str, ...], default: str | None = None) -> str | None:
        for key in keys:
            value = get_config_value(key)
            if value not in (None, ""):
                return str(value).strip()
        return default

    provider_type = (
        str(provider_override).strip()
        if provider_override not in (None, "")
        else first_config_value(provider_config_keys, default_provider)
    )
    provider_type = (provider_type or default_provider).strip().lower()

    model = str(model_override).strip() if model_override not in (None, "") else None
    if not model:
        model = first_config_value(model_config_keys)

    if provider_type == "openai":
        model = model or get_config_value("OPENAI_MODEL", get_provider_fallback_model("openai"))
        return provider_type, model, create_provider(
            "openai",
            api_key=get_config_value("OPENAI_API_KEY"),
            model=model,
        )
    if provider_type == "anthropic":
        model = model or get_config_value("ANTHROPIC_MODEL", get_provider_fallback_model("anthropic"))
        previous = os.environ.get("JARVIS_OVERRIDE_ANTHROPIC_SEARCH")
        if disable_server_side_tools:
            os.environ["JARVIS_OVERRIDE_ANTHROPIC_SEARCH"] = "false"
        try:
            provider = create_provider(
                "anthropic",
                api_key=get_config_value("ANTHROPIC_API_KEY"),
                model=model,
            )
        finally:
            if disable_server_side_tools:
                if previous is None:
                    os.environ.pop("JARVIS_OVERRIDE_ANTHROPIC_SEARCH", None)
                else:
                    os.environ["JARVIS_OVERRIDE_ANTHROPIC_SEARCH"] = previous
        return provider_type, model, provider
    if provider_type == "xai":
        model = model or get_config_value("XAI_MODEL", get_provider_fallback_model("xai"))
        previous = os.environ.get("JARVIS_OVERRIDE_XAI_SEARCH")
        if disable_server_side_tools:
            os.environ["JARVIS_OVERRIDE_XAI_SEARCH"] = "false"
        try:
            provider = create_provider(
                "xai",
                api_key=get_config_value("XAI_API_KEY"),
                model=model,
            )
        finally:
            if disable_server_side_tools:
                if previous is None:
                    os.environ.pop("JARVIS_OVERRIDE_XAI_SEARCH", None)
                else:
                    os.environ["JARVIS_OVERRIDE_XAI_SEARCH"] = previous
        return provider_type, model, provider
    if provider_type == "ollama":
        model = model or get_config_value("OLLAMA_MODEL", get_provider_fallback_model("ollama"))
        return provider_type, model, create_provider(
            "ollama",
            base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=model,
        )

    raise ValueError(f"Unknown LLM provider: {provider_type}")


def create_provider(provider_type: str, **config) -> LLMProvider:
    """
    Factory function to create appropriate provider.
    
    Args:
        provider_type: "openai", "anthropic", "xai", or "ollama"
        **config: Provider-specific configuration
        
    Returns:
        LLMProvider instance
    """
    if provider_type == "openai":
        return OpenAIProvider(
            api_key=config["api_key"],
            model=config.get("model", get_provider_fallback_model("openai"))
        )
    elif provider_type == "anthropic":
        return AnthropicProvider(
            api_key=config["api_key"],
            model=config.get("model", get_provider_fallback_model("anthropic"))
        )
    elif provider_type == "xai":
        return XAIProvider(
            api_key=config["api_key"],
            model=config.get("model", get_provider_fallback_model("xai"))
        )
    elif provider_type == "ollama":
        return OllamaProvider(
            base_url=config["base_url"],
            model=config["model"]
        )
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")
