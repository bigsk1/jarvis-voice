#!/usr/bin/env python3
"""
LLM Provider Abstraction Layer
Supports OpenAI, Anthropic, xAI (Grok), and Ollama with unified interface.
"""
import os
import sys
import json
from typing import Any
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """
        Send chat request with tool calling capability.
        
        Args:
            messages: Conversation history [{"role": "user", "content": "..."}]
            tools: List of tool definitions (format depends on provider)
            system_prompt: System prompt for the conversation
            enable_thinking: Enable extended thinking mode (if supported by model)
            
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
    
    def chat(self, message: str, system_prompt: str | None = None, max_tokens: int = None) -> str:
        """Simple chat without tools."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})
        
        try:
            params = {"model": self.model, "messages": messages}
            if max_tokens:
                # Newer OpenAI models (gpt-5.x, o1, o3, etc.) use max_completion_tokens
                if self.model.startswith(('gpt-5', 'o1', 'o3')):
                    params["max_completion_tokens"] = max_tokens
                else:
                    params["max_tokens"] = max_tokens
            response = self.client.chat.completions.create(**params)
            return response.choices[0].message.content or ""
        except Exception as e:
            import sys
            print(f"OpenAI API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"
    
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                tools=tools,
                tool_choice="auto"
            )
            
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
            import sys
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
            
            # Extract text from response
            for block in response.content:
                if block.type == "text":
                    return block.text
            
            return "No response from Claude"
        except Exception as e:
            import sys
            print(f"Anthropic API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"
    
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False
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
            # Cache everything in the system prompt (saves 90% on cache hits)
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
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5  # Limit searches per request
                }
                tools_with_cache.insert(0, web_search_tool)
                # Required beta header for web search
                extra_headers["anthropic-beta"] = "web-search-2025-03-05"
                
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
                "tools": tools_with_cache
            }
            
            # Add extra headers if any (e.g., web search beta)
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
                            import sys
                            print(f"DEBUG: Thinking enabled! Config: {thinking_config}", file=sys.stderr)
                            print(f"DEBUG: max_tokens set to: {api_params['max_tokens']}", file=sys.stderr)
            
            response = self.client.messages.create(**api_params)
            
            # Debug: Show what we got back
            if os.environ.get('JARVIS_DEBUG'):
                import sys
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
                    import sys
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
            
            # Check response type
            # Anthropic may return BOTH text AND tool_use blocks
            # Prioritize tool_use if present
            tool_use_block = None
            text_block = None
            
            for block in response.content:
                if block.type == "tool_use":
                    tool_use_block = block
                elif block.type == "text":
                    text_block = block
            
            # Return tool use if found (text is just explanatory)
            if tool_use_block:
                return None, {
                    "name": tool_use_block.name,
                    "arguments": tool_use_block.input
                }, usage_info, thinking_text
            
            # Otherwise return text response
            if text_block:
                return text_block.text, None, usage_info, thinking_text
            
            return "No response from Claude", None, usage_info, thinking_text
            
        except Exception as e:
            import sys
            print(f"Anthropic API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}", None, None, None


class XAIProvider(LLMProvider):
    """
    xAI (Grok) provider with hybrid SDK support.
    
    Features:
    - 2M context window for grok-4-fast and grok-4-1-fast models
    - 256k context for grok-4 and grok-code-fast models
    - Extremely competitive pricing ($0.20 input / $0.50 output per 1M tokens)
    - Native function calling (OpenAI-compatible)
    - Reasoning mode support (grok-*-reasoning-* models)
    - Structured outputs
    - Live Search: When XAI_SEARCH=true, uses xAI SDK Agent Tools API
      for real-time web/X search (server-side tools)
    """
    
    def __init__(self, api_key: str, model: str = "grok-4-1-fast-non-reasoning-latest"):
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
        self.model = model
        self.is_reasoning_model = "reasoning" in model.lower()
        
        # Check if live search is enabled (XAI_SEARCH=true in cloud.env)
        # When enabled, uses xAI SDK with Agent Tools API for web/X search
        from config_loader import get_config_value
        self.enable_search = get_config_value("XAI_SEARCH", "false").lower() == "true"
        
        # Initialize xAI SDK client if search is enabled
        self.xai_client = None
        if self.enable_search:
            try:
                from xai_sdk import Client as XAIClient
                self.xai_client = XAIClient(api_key=api_key)
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
            if max_tokens:
                params["max_tokens"] = max_tokens
            
            response = self.client.chat.completions.create(**params)
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"xAI API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"
    
    def _build_xai_server_tools(self):
        """Build list of xAI server-side tools based on config."""
        from xai_sdk.tools import web_search, x_search, code_execution
        
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
    
    def _chat_with_xai_sdk(self, message: str, system_prompt: str | None = None, max_tokens: int = None) -> str:
        """Simple chat using xAI SDK with server-side tools."""
        try:
            from xai_sdk.chat import user, system as sys_msg
            
            # Create chat with xAI server-side tools (configurable)
            chat = self.xai_client.chat.create(
                model=self.model,
                tools=self._build_xai_server_tools(),
            )
            
            # Add system prompt if provided
            if system_prompt:
                chat.append(sys_msg(system_prompt))
            
            # Add user message
            chat.append(user(message))
            
            # Get response (non-streaming for simple chat)
            response = chat.sample()
            
            return response.content or ""
        except Exception as e:
            print(f"xAI SDK error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"
    
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False
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
            return self._chat_with_tools_xai_sdk(messages, tools, system_prompt, enable_thinking)
        
        # Standard OpenAI SDK path (no search)
        return self._chat_with_tools_openai_sdk(messages, tools, system_prompt, enable_thinking)
    
    def _chat_with_tools_openai_sdk(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False
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
                "max_tokens": 1024  # Ensure adequate response length
            }
            
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
        """Convert OpenAI-format tool to xAI SDK Protocol Buffer format."""
        from xai_sdk.tools import chat_pb2
        
        xai_tool = chat_pb2.Tool()
        
        # Handle OpenAI format: {"type": "function", "function": {...}}
        if tool.get("type") == "function":
            func_def = tool.get("function", {})
        else:
            # Handle Anthropic format: {"name": "...", "description": "...", "input_schema": {...}}
            func_def = tool
        
        xai_tool.function.name = func_def.get("name", "")
        xai_tool.function.description = func_def.get("description", "")
        
        # Parameters can be in "parameters" (OpenAI) or "input_schema" (Anthropic)
        params = func_def.get("parameters") or func_def.get("input_schema", {})
        if params:
            xai_tool.function.parameters = json.dumps(params)
        
        return xai_tool
    
    def _chat_with_tools_xai_sdk(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """
        Chat with tools using xAI SDK Agent Tools API.
        
        Combines server-side search tools (web_search, x_search) with our client-side tools.
        The model decides when to use search vs our tools.
        Server-side tools are executed automatically by xAI.
        Client-side tools are returned for us to execute.
        
        Note: xAI SDK doesn't support client-side tool results in multi-turn conversations.
        If messages contain tool results, we fall back to OpenAI SDK for full tool support.
        """
        # Check if messages contain tool results (xAI SDK doesn't support this)
        has_tool_results = any(msg.get("role") == "tool" for msg in messages)
        if has_tool_results:
            # Fall back to OpenAI SDK for multi-turn tool conversations
            return self._chat_with_tools_openai_sdk(messages, tools, system_prompt, enable_thinking)
        
        try:
            from xai_sdk.chat import user, system as sys_msg, assistant
            from xai_sdk.tools import get_tool_call_type
            
            # Build xAI SDK tools list: server-side tools (configurable) + client-side custom tools
            xai_tools = self._build_xai_server_tools()
            
            # Convert our custom tools to xAI SDK Protocol Buffer format
            for tool in tools:
                xai_tool = self._convert_tool_to_xai_sdk(tool)
                xai_tools.append(xai_tool)
            
            # Create chat with mixed tools
            chat = self.xai_client.chat.create(
                model=self.model,
                tools=xai_tools,
            )
            
            # Add system prompt if provided
            if system_prompt:
                chat.append(sys_msg(system_prompt))
            
            # Add conversation history (only user/assistant, tool results handled by fallback)
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                
                if role == "user":
                    chat.append(user(content))
                elif role == "assistant":
                    # Simple assistant message (no tool_calls since we'd have fallen back)
                    chat.append(assistant(content))
            
            # Get response (non-streaming for now)
            response = chat.sample()
            
            # Extract usage info
            usage_info = None
            if hasattr(response, 'usage') and response.usage:
                from cost_estimator import estimate_cost
                input_tokens = getattr(response.usage, 'prompt_tokens', 0) or getattr(response.usage, 'prompt_text_tokens', 0) or 0
                output_tokens = getattr(response.usage, 'completion_tokens', 0) or 0
                
                usage_info = estimate_cost(
                    provider="xai",
                    model=self.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens
                )
                
                # Add search tool usage info if available
                if hasattr(response, 'server_side_tool_usage'):
                    usage_info['server_side_tools'] = response.server_side_tool_usage
            
            # Check for client-side tool calls (our custom tools)
            # Server-side tools (web_search, x_search) are handled automatically by xAI
            if hasattr(response, 'tool_calls') and response.tool_calls:
                for tc in response.tool_calls:
                    tool_type = get_tool_call_type(tc)
                    
                    # Only return client-side tool calls for us to execute
                    if tool_type == "client_side_tool":
                        return None, {
                            "name": tc.function.name,
                            "arguments": json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                        }, usage_info, None
            
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
            # Fallback to OpenAI SDK without search
            print("Falling back to OpenAI SDK without search", file=sys.stderr)
            return self._chat_with_tools_openai_sdk(messages, tools, system_prompt, enable_thinking)


class OllamaProvider(LLMProvider):
    """Ollama provider using native tool calling API (Ollama 0.3.0+)."""
    
    def __init__(self, base_url: str, model: str):
        """Initialize Ollama provider."""
        self.base_url = base_url.rstrip('/')
        self.model = model
    
    def chat(self, message: str, system_prompt: str | None = None, max_tokens: int = None) -> str:
        """Simple chat without tools."""
        import requests
        
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
            
            # Extended context for capable models
            options = self._get_context_options()
            
            # Allow longer output for code generation
            if max_tokens:
                options["num_predict"] = max_tokens
            
            if options:
                request_data["options"] = options
            
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=request_data,
                timeout=180  # 3 minutes for local models (qwen3-vl is heavy)
            )
            response.raise_for_status()
            
            result = response.json()
            return result["message"]["content"]
        except Exception as e:
            import sys
            print(f"Ollama API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"
    
    def _get_context_options(self) -> dict[str, Any]:
        """Get context window options for the current model."""
        options = {}
        # Extended context for models that support it
        # Configurable via OLLAMA_CONTEXT_WINDOW in local.env
        # Models known to support large context: qwen3, ministral, mistral-nemo
        model_lower = self.model.lower()
        if any(m in model_lower for m in ['qwen3', 'ministral', 'mistral-nemo', 'llama3']):
            from config_loader import get_int
            context_window = get_int('OLLAMA_CONTEXT_WINDOW', 32000)
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
    
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        enable_thinking: bool = False
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
            - thinking is available for reasoning models (qwen3:14b, etc.)
        """
        import requests
        import os
        
        # Convert tools to Ollama/OpenAI format
        ollama_tools = self._convert_to_ollama_tools(tools) if tools else []
        
        # Build full messages with system prompt
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        
        try:
            # Build request
            request_data = {
                "model": self.model,
                "messages": full_messages,
                "stream": False
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
                print(f"DEBUG: Ollama request - model={self.model}, tools={len(ollama_tools)}, messages={len(full_messages)}", file=sys.stderr)
            
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=request_data,
                timeout=180  # 3 minutes for local models
            )
            
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
            
            # Extract thinking if present (qwen3:14b and other reasoning models)
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
        enhanced_system = f"""{system_prompt or 'You are a helpful AI assistant.'}

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
- If not using a tool, respond in plain conversational text without any JSON.
"""
        
        # Build full messages
        full_messages = [{"role": "system", "content": enhanced_system}]
        full_messages.extend(messages)
        
        try:
            request_data = {
                "model": self.model,
                "messages": full_messages,
                "stream": False
            }
            
            # Set context window options
            options = self._get_context_options()
            if options:
                request_data["options"] = options
            
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Ollama structured prompting fallback - model={self.model}", file=sys.stderr)
            
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=request_data,
                timeout=180
            )
            response.raise_for_status()
            
            result = response.json()
            content = result.get("message", {}).get("content", "")
            
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
                stripped = content.strip()
                
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
            model=config.get("model", "gpt-4o-mini")
        )
    elif provider_type == "anthropic":
        return AnthropicProvider(
            api_key=config["api_key"],
            model=config.get("model", "claude-sonnet-4-20250514")
        )
    elif provider_type == "xai":
        return XAIProvider(
            api_key=config["api_key"],
            model=config.get("model", "grok-4-1-fast-non-reasoning-latest")
        )
    elif provider_type == "ollama":
        return OllamaProvider(
            base_url=config["base_url"],
            model=config["model"]
        )
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")

