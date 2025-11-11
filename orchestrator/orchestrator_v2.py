#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Main Orchestrator (v2)
Enhanced with LLM-based routing and confirmation flow.
"""
import os
import sys
import json
from typing import Dict, Any
from datetime import datetime

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config
from memory_db import get_memory_db

from router_v2 import LLMRouter
from executor import ToolExecutor


class Orchestrator:
    """Main orchestration with LLM-based routing, error recovery, and retry logic."""
    
    def __init__(self, mode='cloud'):
        """Initialize orchestrator."""
        self.mode = mode
        load_config(mode)
        self.router = LLMRouter(mode)
        self.executor = ToolExecutor(mode)
        self.max_retries = 1  # Maximum retry attempts
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")  # Unique session ID
    
    def process(self, transcript: str, retry_count: int = 0, error_context: str = None) -> Dict[str, Any]:
        """
        Process user transcript and execute tools or respond.
        
        Args:
            transcript: User's spoken input (from STT)
            retry_count: Current retry attempt (for error recovery)
            error_context: Previous error information (for retry)
            
        Returns:
            dict: Response for TTS
            {
                "speech": "Text to speak",
                "ok": bool,
                "data": {...} (optional),
                "error": str (optional)
            }
        """
        # If retrying, augment transcript with error context
        if error_context and retry_count > 0:
            enhanced_transcript = f"{transcript}\n\nPrevious attempt failed with error: {error_context}\nPlease try again with corrected parameters or check logs if needed."
        else:
            enhanced_transcript = transcript
        
        # Route using LLM
        route = self.router.route(enhanced_transcript)
        
        # Handle tool execution
        if route["intent"] == "tool":
            tool_name = route["tool_name"]
            arguments = route["arguments"]
            
            # Only print if in interactive mode
            if sys.stdout.isatty():
                print(f"🔧 Executing tool: {tool_name}")
                print(f"📝 Arguments: {json.dumps(arguments, indent=2)}")
            
            # Execute the tool
            result = self.executor.execute(tool_name, arguments)
            
            if result["ok"]:
                # Success - let LLM format natural response based on tool result
                if sys.stdout.isatty():
                    print(f"✅ Tool succeeded")
                    print(f"📊 Tool result: {json.dumps(result.get('data', {}), indent=2)[:200]}...")
                
                # For memory tools, get natural response from LLM
                if tool_name in ['remember', 'recall', 'search_memory', 'semantic_recall', 'update_memory', 'forget']:
                    speech = self._format_natural_response(transcript, tool_name, result)
                else:
                    # For other tools, use their built-in speech
                    speech = result.get("speech", f"Completed {tool_name}")
                
                if sys.stdout.isatty():
                    print(f"💬 Natural response: {speech}")
                
                # Auto-log conversation
                self._log_conversation(transcript, speech, [tool_name], success=True)
                
                return {
                    "speech": speech,
                    "ok": True,
                    "data": result.get("data", {}),
                    "tool_used": tool_name
                }
            else:
                # Failure - check if we should retry
                error = result.get("error", "Unknown error")
                speech = result.get("speech", f"Failed to execute {tool_name}")
                if sys.stdout.isatty():
                    print(f"❌ Tool failed: {error}")
                
                # Retry if we haven't exceeded max retries
                if retry_count < self.max_retries:
                    if sys.stdout.isatty():
                        print(f"🔄 Attempting retry {retry_count + 1}/{self.max_retries}...")
                    
                    # Build error context for retry
                    error_context = f"Tool '{tool_name}' failed with: {error}. Arguments used: {json.dumps(arguments)}"
                    
                    # Recursive retry with error context
                    return self.process(transcript, retry_count + 1, error_context)
                
                # Max retries exceeded
                final_speech = f"{speech}. Error: {error}. I tried {retry_count + 1} time(s) but couldn't complete the task."
                
                # Auto-log failed conversation
                self._log_conversation(transcript, final_speech, [tool_name], success=False)
                
                return {
                    "speech": final_speech,
                    "ok": False,
                    "error": error,
                    "tool_used": tool_name,
                    "retries": retry_count
                }
        
        # Handle Q&A (direct response)
        elif route["intent"] == "qa":
            speech = route.get("text_response", "I'm not sure how to respond.")
            if sys.stdout.isatty():
                print(f"💬 Q&A response: {speech}")
            
            # Auto-log Q&A conversation
            self._log_conversation(transcript, speech, [], success=True)
            
            return {
                "speech": speech,
                "ok": True
            }
        
        # Handle errors
        else:
            error = route.get("error", "Unknown routing error")
            speech = route.get("text_response", "Sorry, I had trouble understanding that.")
            if sys.stdout.isatty():
                print(f"❌ Routing error: {error}")
            
            # Auto-log error
            self._log_conversation(transcript, speech, [], success=False)
            
            return {
                "speech": speech,
                "ok": False,
                "error": error
            }
    
    def _format_natural_response(self, user_query: str, tool_name: str, tool_result: Dict[str, Any]) -> str:
        """
        Use LLM to format tool results into natural conversational speech.
        
        Args:
            user_query: Original user question
            tool_name: Name of the tool that was executed
            tool_result: The tool's result dict
            
        Returns:
            Natural language response
        """
        try:
            # Extract relevant data
            data = tool_result.get("data", {})
            
            # Build context for LLM
            context = f"""User asked: "{user_query}"

Tool executed: {tool_name}
Tool result: {json.dumps(data, indent=2)}

Respond naturally and conversationally to the user's question based on this tool result. Be concise, helpful, and speak in first person as Jarvis."""
            
            # Get natural response from LLM (without tools)
            text_response, _ = self.router.provider.chat_with_tools(
                messages=[{"role": "user", "content": context}],
                tools=[],  # No tools for response formatting
                system_prompt="You are Jarvis, a helpful AI assistant. Format the tool result into natural speech."
            )
            
            if text_response:
                return text_response
            else:
                return tool_result.get("speech", "Done")
            
        except Exception as e:
            # Fallback to tool's built-in speech
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format natural response: {e}", file=sys.stderr)
            return tool_result.get("speech", "Completed")
    
    def _log_conversation(self, user_query: str, response: str, tools_used: list, success: bool = True):
        """Auto-log conversation to memory database."""
        try:
            db = get_memory_db()
            db.log_conversation(
                user_query=user_query,
                jarvis_response=response,
                tools_used=tools_used,
                session_id=self.session_id,
                success=success
            )
            db.close()
        except Exception as e:
            # Silently fail - don't break the main flow
            if sys.stdout.isatty():
                print(f"⚠️ Failed to log conversation: {e}", file=sys.stderr)


def main():
    """CLI interface."""
    if len(sys.argv) < 2:
        print("Usage: orchestrator_v2.py <mode> <transcript> [--json]", file=sys.stderr)
        print("  mode: 'cloud' or 'local'", file=sys.stderr)
        print("  --json: Output only JSON (for scripting)", file=sys.stderr)
        print("\nExample:")
        print("  ./orchestrator_v2.py cloud 'Send a webhook to my server'")
        sys.exit(1)
    
    mode = sys.argv[1]
    
    # Check for --json flag
    json_only = "--json" in sys.argv
    if json_only:
        sys.argv.remove("--json")
        # Set env var to suppress verbose MCP output
        os.environ['JARVIS_JSON_MODE'] = '1'
    
    transcript = " ".join(sys.argv[2:])
    
    if not json_only:
        print(f"🎯 Processing: '{transcript}'")
        print(f"📡 Mode: {mode}")
        print("=" * 60)
    
    orch = Orchestrator(mode)
    result = orch.process(transcript)
    
    if json_only:
        # Output only JSON for scripting
        print(json.dumps(result))
    else:
        # Pretty output for human viewing
        print("=" * 60)
        print(f"🗣️  Speech Output: {result['speech']}")
        print(f"✓  Status: {'✅ OK' if result['ok'] else '❌ Failed'}")
        
        if result.get("data"):
            print(f"📊 Data: {json.dumps(result['data'], indent=2)}")
        
        print("\n📄 Full Response:")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

