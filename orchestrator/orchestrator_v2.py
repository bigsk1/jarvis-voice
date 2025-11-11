#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Main Orchestrator (v2)
Enhanced with LLM-based routing and confirmation flow.
"""
import os
import sys
import json
from typing import Dict, Any

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config

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
                # Success - speak the result
                speech = result.get("speech", f"Completed {tool_name}")
                if sys.stdout.isatty():
                    print(f"✅ Tool succeeded: {speech}")
                
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
                return {
                    "speech": f"{speech}. Error: {error}. I tried {retry_count + 1} time(s) but couldn't complete the task.",
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
            
            return {
                "speech": speech,
                "ok": False,
                "error": error
            }


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

