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
        system_prompt: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Send chat request with tool calling capability.
        
        Args:
            messages: Conversation history [{"role": "user", "content": "..."}]
            tools: List of tool definitions (format depends on provider)
            system_prompt: System prompt for the conversation
            
        Returns:
            Tuple of (text_response, tool_call)
            - text_response: Direct text response from LLM (if not calling tool)
            - tool_call: {"name": "tool_name", "arguments": {...}} if tool called
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
    
    def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Send chat with OpenAI function calling."""
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
            
            # Check if tool was called
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                return None, {
                    "name": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments)
                }
            
            # Otherwise return text response
            return message.content, None
            
        except Exception as e:
            print(f"OpenAI API error: {e}")
            return f"Error: {str(e)}", None


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
    
    def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Send chat with Anthropic tool calling."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt or "You are a helpful AI assistant.",
                messages=messages,
                tools=tools
            )
            
            # Check response type
            for block in response.content:
                # Tool use block
                if block.type == "tool_use":
                    return None, {
                        "name": block.name,
                        "arguments": block.input
                    }
                # Text block
                elif block.type == "text":
                    return block.text, None
            
            return "No response from Claude", None
            
        except Exception as e:
            print(f"Anthropic API error: {e}")
            return f"Error: {str(e)}", None


class OllamaProvider(LLMProvider):
    """Ollama provider using structured prompting (no native tool calling)."""
    
    def __init__(self, base_url: str, model: str):
        """Initialize Ollama provider."""
        self.base_url = base_url.rstrip('/')
        self.model = model
    
    def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Send chat with Ollama using structured prompting.
        Since Ollama doesn't have native tool calling, we use a structured prompt.
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

IMPORTANT: 
- If using a tool, ONLY respond with the JSON tool call, nothing else.
- If not using a tool, respond normally without JSON.
"""
        
        # Build full messages
        full_messages = [{"role": "system", "content": enhanced_system}]
        full_messages.extend(messages)
        
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": full_messages,
                    "stream": False
                },
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            content = result["message"]["content"]
            
            # Try to parse as tool call
            try:
                if content.strip().startswith("{") and "tool" in content:
                    tool_call = json.loads(content.strip())
                    if "tool" in tool_call and "arguments" in tool_call:
                        return None, {
                            "name": tool_call["tool"],
                            "arguments": tool_call["arguments"]
                        }
            except json.JSONDecodeError:
                pass
            
            # Otherwise return as text
            return content, None
            
        except Exception as e:
            print(f"Ollama API error: {e}")
            return f"Error: {str(e)}", None
    
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

