#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Main Orchestrator
Coordinates routing, execution, and response formatting.

This is the "brain" that sits between STT and TTS.
"""
import os
import sys
import json
from typing import Any

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config

from router import IntentRouter
from executor import ToolExecutor


class Orchestrator:
    """Main orchestration logic."""
    
    def __init__(self, mode='cloud'):
        """Initialize orchestrator."""
        self.mode = mode
        load_config(mode)
        self.router = IntentRouter(mode)
        self.executor = ToolExecutor(mode)
        
        # Get script paths for Q&A fallback
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        if mode == 'cloud':
            self.qa_script = os.path.join(self.project_root, "bin", "question.sh")
        else:
            self.qa_script = os.path.join(self.project_root, "bin", "question-local.sh")
    
    def process(self, transcript: str) -> dict[str, Any]:
        """
        Process a user transcript and return speech response.
        
        Args:
            transcript: User's spoken input (from STT)
            
        Returns:
            dict: Response to speak
            {
                "text": "Speech text for TTS",
                "data": {...} (optional metadata)
            }
        """
        # Route to determine intent
        route = self.router.route(transcript)
        
        if route["intent"] == "tool":
            # Execute tool
            result = self.executor.execute(route["tool_name"], route["args"])
            return {
                "text": result.get("speech", "Tool executed"),
                "data": result.get("data", {}),
                "ok": result.get("ok", False)
            }
        
        elif route["intent"] == "qa":
            # Fall back to normal Q&A (call question script)
            import subprocess
            try:
                result = subprocess.run(
                    [self.qa_script, transcript],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                # The script handles TTS directly for now
                # In future, return text for orchestrator to handle TTS
                return {
                    "text": "(handled by Q&A script)",
                    "ok": True
                }
            except Exception as e:
                return {
                    "text": "Sorry, I had trouble processing that",
                    "error": str(e),
                    "ok": False
                }
        
        else:
            return {
                "text": "I'm not sure how to handle that",
                "ok": False
            }


def main():
    """CLI interface."""
    if len(sys.argv) < 2:
        print("Usage: orchestrator.py <mode> <transcript>", file=sys.stderr)
        print("  mode: 'cloud' or 'local'", file=sys.stderr)
        sys.exit(1)
    
    mode = sys.argv[1]
    transcript = " ".join(sys.argv[2:])
    
    orch = Orchestrator(mode)
    result = orch.process(transcript)
    
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

