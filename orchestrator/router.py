#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Orchestrator Router
Determines intent and routes to appropriate handler (QA, tool, skill, etc.)
"""
import os
import sys
import json
from typing import Dict, Any, Optional

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value


class IntentRouter:
    """Routes transcribed text to appropriate handler."""
    
    def __init__(self, mode='cloud'):
        """Initialize router with configuration."""
        self.mode = mode
        load_config(mode)
        self.chat_model = get_config_value("CHAT_MODEL", "gpt-4o-mini")
        self.api_key = get_config_value("OPENAI_API_KEY", "")
        
    def route(self, transcript: str) -> Dict[str, Any]:
        """
        Determine intent from transcript.
        
        Args:
            transcript: The transcribed user speech
            
        Returns:
            dict: Routing decision
            {
                "intent": "qa" | "tool" | "skill",
                "tool_name": "weather" (if intent=tool),
                "args": {...} (if intent=tool),
                "confidence": 0.0-1.0
            }
        """
        # For now, simple rule-based routing
        # TODO: Replace with LLM-based intent classification
        
        transcript_lower = transcript.lower()
        
        # Check for tool keywords
        if any(word in transcript_lower for word in ["weather", "temperature", "forecast"]):
            return {
                "intent": "tool",
                "tool_name": "weather",
                "args": {"location": self._extract_location(transcript)},
                "confidence": 0.8
            }
        
        if any(word in transcript_lower for word in ["time", "clock", "what time"]):
            return {
                "intent": "tool",
                "tool_name": "time",
                "args": {},
                "confidence": 0.9
            }
        
        # Default to Q&A
        return {
            "intent": "qa",
            "tool_name": None,
            "args": {},
            "confidence": 1.0
        }
    
    def _extract_location(self, text: str) -> str:
        """Extract location from text (simple regex for now)."""
        # TODO: Improve location extraction
        words = text.split()
        for i, word in enumerate(words):
            if word.lower() in ["in", "at", "for"] and i + 1 < len(words):
                return " ".join(words[i+1:])
        return "here"


def main():
    """CLI interface for testing."""
    if len(sys.argv) < 2:
        print("Usage: router.py <mode> <transcript>", file=sys.stderr)
        print("  mode: 'cloud' or 'local'", file=sys.stderr)
        sys.exit(1)
    
    mode = sys.argv[1]
    transcript = " ".join(sys.argv[2:])
    
    router = IntentRouter(mode)
    result = router.route(transcript)
    
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

