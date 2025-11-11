#!/usr/bin/env python3
"""
Jarvis Voice Assistant - LLM-Based Router (v2)
Uses native tool calling from OpenAI/Anthropic/Ollama to intelligently route requests.
"""
import os
import sys
from typing import Dict, Any, Optional
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from tool_schema import ToolRegistry
from llm_provider import create_provider


class LLMRouter:
    """Intelligent router using LLM tool calling."""
    
    def __init__(self, mode='cloud'):
        """Initialize router with LLM provider."""
        self.mode = mode
        load_config(mode)
        
        # Load tool registry
        project_root = Path(__file__).parent.parent.resolve()
        mcp_config = str(project_root / "config" / "mcp-servers.json")
        self.registry = ToolRegistry(str(project_root / "skills"), mcp_config)
        
        # Initialize LLM provider
        self.provider = self._create_provider()
        
        # System prompt for routing
        self.system_prompt = """You are Jarvis, a voice-controlled AI assistant with access to tools AND persistent memory.

MEMORY MANAGEMENT (CRITICAL):
You have persistent memory across conversations. ALWAYS check your memory first before responding!

When to use memory tools:
1. **ALWAYS use 'recall', 'search_memory', or 'semantic_recall' FIRST** when the user asks "what", "when", "who", "where" questions about personal information
   - Use 'semantic_recall' when the question uses different words than what might be stored (e.g., "spouse" vs "wife", "born" vs "birthday")
   - Use 'recall' or 'search_memory' for exact keyword matches
2. **PROACTIVELY use 'remember'** when the user shares important information:
   - Personal information (family, birthdays, relationships)
   - Preferences (favorite places, settings, habits)
   - Important contacts (doctor, dentist, etc.)
   - Locations (home, work, frequent places)
3. Use 'update_memory' to correct outdated information
4. Use 'forget' to remove incorrect or obsolete data

CRITICAL EXAMPLES:
❌ BAD: User asks "When is my wife's birthday?" → You respond "I don't know"
✅ GOOD: User asks "When is my wife's birthday?" → You call 'recall' with query "wife birthday" → Respond with the stored date

❌ BAD: User says "My wife's birthday is March 15" → You just acknowledge
✅ GOOD: User says "My wife's birthday is March 15" → You call 'remember' → Respond "I'll remember that"

ACTION TOOLS - When the user asks you to perform an ACTION or get REAL-TIME data:
- Use the appropriate tool based on user request
- Tools are dynamically loaded including local tools and MCP servers
- Common actions: send_webhook, api_call, get_time, crypto_price, execute_bash
- Web access: mcp.duckduckgo.search, mcp.fetch.fetch (if available)

ERROR RECOVERY: If a tool fails, you can:
1. Use check_tool_logs to see what went wrong
2. Retry with corrected parameters based on the error
3. Try a different approach

Only respond conversationally for general knowledge questions, jokes, explanations, or conversation.

Be decisive and proactive - remember what's important, use tools when needed."""
    
    def _create_provider(self):
        """Create appropriate LLM provider based on config."""
        provider_type = get_config_value("LLM_PROVIDER", "openai" if self.mode == "cloud" else "ollama")
        
        if provider_type == "openai":
            return create_provider(
                "openai",
                api_key=get_config_value("OPENAI_API_KEY"),
                model=get_config_value("CHAT_MODEL", "gpt-4o-mini")
            )
        elif provider_type == "anthropic":
            return create_provider(
                "anthropic",
                api_key=get_config_value("ANTHROPIC_API_KEY"),
                model=get_config_value("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
            )
        elif provider_type == "ollama":
            return create_provider(
                "ollama",
                base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434"),
                model=get_config_value("OLLAMA_MODEL", "llama3.1:latest")
            )
        else:
            raise ValueError(f"Unknown LLM provider: {provider_type}")
    
    def route(self, transcript: str) -> Dict[str, Any]:
        """
        Use LLM to determine intent and route appropriately.
        
        Args:
            transcript: User's transcribed speech
            
        Returns:
            dict: Routing decision
            {
                "intent": "tool" | "qa",
                "tool_name": str (if tool),
                "arguments": dict (if tool),
                "text_response": str (if qa),
                "confidence": float
            }
        """
        # Only print if in interactive mode
        if sys.stdout.isatty():
            print(f"🧠 Routing with LLM: '{transcript}'")
        
        # Get tools in appropriate format for provider
        if hasattr(self.provider, '__class__') and 'Anthropic' in self.provider.__class__.__name__:
            tools = self.registry.to_anthropic_format()
        else:
            # OpenAI format also works for Ollama (we convert internally)
            tools = self.registry.to_openai_format()
        
        # For Ollama, convert to Anthropic-like format (simpler)
        if hasattr(self.provider, '__class__') and 'Ollama' in self.provider.__class__.__name__:
            tools = self.registry.to_anthropic_format()
        
        # Send to LLM
        messages = [{"role": "user", "content": transcript}]
        
        try:
            text_response, tool_call = self.provider.chat_with_tools(
                messages=messages,
                tools=tools,
                system_prompt=self.system_prompt
            )
            
            # Tool was called
            if tool_call:
                return {
                    "intent": "tool",
                    "tool_name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                    "confidence": 1.0
                }
            
            # Direct text response (Q&A)
            else:
                return {
                    "intent": "qa",
                    "text_response": text_response or "I'm not sure how to respond to that.",
                    "confidence": 1.0
                }
        
        except Exception as e:
            print(f"❌ Router error: {e}")
            return {
                "intent": "error",
                "error": str(e),
                "text_response": "Sorry, I had trouble processing your request.",
                "confidence": 0.0
            }


def main():
    """CLI interface for testing."""
    import json
    
    if len(sys.argv) < 2:
        print("Usage: router_v2.py <mode> <transcript>", file=sys.stderr)
        print("  mode: 'cloud' or 'local'", file=sys.stderr)
        sys.exit(1)
    
    mode = sys.argv[1]
    transcript = " ".join(sys.argv[2:])
    
    router = LLMRouter(mode)
    result = router.route(transcript)
    
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

