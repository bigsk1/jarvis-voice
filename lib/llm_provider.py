#!/usr/bin/env python3
"""
LLM Provider Abstraction Layer
Supports OpenAI, Anthropic, and Ollama with unified interface.
"""
import os
import json
from typing import Dict, Any, List, Optional, Tuple
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        enable_thinking: bool = False
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
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
    def chat(self, message: str, system_prompt: Optional[str] = None) -> str:
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
    
    def chat(self, message: str, system_prompt: Optional[str] = None) -> str:
        """Simple chat without tools."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            import sys
            print(f"OpenAI API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}"
    
    def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        enable_thinking: bool = False
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
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
    """Anthropic Claude provider using tool calling."""
    
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929"):
        """Initialize Anthropic provider."""
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")
        
        self.client = Anthropic(api_key=api_key)
        self.model = model
    
    def chat(self, message: str, system_prompt: Optional[str] = None) -> str:
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
                max_tokens=1024,
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
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        enable_thinking: bool = False
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
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


class OllamaProvider(LLMProvider):
    """Ollama provider using structured prompting (no native tool calling)."""
    
    def __init__(self, base_url: str, model: str):
        """Initialize Ollama provider."""
        self.base_url = base_url.rstrip('/')
        self.model = model
    
    def chat(self, message: str, system_prompt: Optional[str] = None) -> str:
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
            if any(m in self.model.lower() for m in ['qwen', 'mistral-nemo']):
                request_data["options"] = {"num_ctx": 8192}
            
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
    
    def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        enable_thinking: bool = False
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
        """
        Send chat with Ollama using structured prompting with smart corrections.
        Since Ollama doesn't have native tool calling, we use a structured prompt.
        
        Returns:
            Tuple of (text_response, tool_call, usage_info, thinking)
            - usage_info is None for Ollama (no cost tracking for local models)
            - thinking is None for most Ollama models (only certain models support it)
        """
        import requests
        
        # Build tool descriptions
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
            # Build request with extended context for capable models
            request_data = {
                "model": self.model,
                "messages": full_messages,
                "stream": False
            }
            
            # Extended context for models that support it
            # qwen3-vl VRAM usage on 16GB RTX 5060 Ti:
            #   4096 tokens  = 11GB (default, very safe)
            #   8192 tokens  = 12GB (current, 4GB headroom) ⭐
            #  16384 tokens  = 14GB (can increase if needed, 2GB headroom)
            #  32768 tokens  = 15GB (risky, causes timeouts)
            # To increase: change 8192 to 12288 or 16384 below
            if any(m in self.model.lower() for m in ['qwen', 'mistral-nemo']):
                request_data["options"] = {"num_ctx": 8192}  # 8k tokens = 12GB VRAM
            
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=request_data,
                timeout=180  # 3 minutes for local models (qwen3-vl vision model is heavy with full tool context)
            )
            response.raise_for_status()
            
            result = response.json()
            content = result["message"]["content"]
            
            # Try to parse as tool call
            # Handle both pure JSON and markdown-wrapped JSON
            try:
                # Strip whitespace and try direct JSON parse
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
                
                # Extract JSON if wrapped in markdown or text
                if "{" in stripped and "}" in stripped:
                    # Find the JSON object
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
                        
                        return None, corrected_call, None, None  # No usage info or thinking for Ollama
            except (json.JSONDecodeError, ValueError):
                pass
            
            # Otherwise return as text
            return content, None, None, None  # No tool call, usage, or thinking
            
        except Exception as e:
            import sys
            print(f"Ollama API error: {e}", file=sys.stderr)
            return f"Error: {str(e)}", None, None, None
    
    def _format_tools_for_prompt(self, tools: List[Dict[str, Any]]) -> str:
        """Format tools as text for Ollama prompt."""
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
        provider_type: "openai", "anthropic", or "ollama"
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
    elif provider_type == "ollama":
        return OllamaProvider(
            base_url=config["base_url"],
            model=config["model"]
        )
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")

