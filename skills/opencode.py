#!/usr/bin/env python3
"""
Jarvis Skill: OpenCode Integration
Execute complex tasks using OpenCode autonomous agent.
"""

import sys
import json
import os
import time

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from opencode_client import OpenCodeClient
from config_loader import get_config_value, load_config
from memory_db import MemoryDB


def main():
    """Execute OpenCode task."""
    # Read input
    try:
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return_error("Invalid JSON input")
        return 1

    # Extract parameters
    task = input_data.get("task")
    task_type = input_data.get("task_type", "general")
    session_id = input_data.get("session_id")  # Resume existing session
    model = input_data.get("model")  # Optional model override
    agent_mode = input_data.get("agent_mode", "build")  # "build" or "plan"

    if not task:
        return_error("Task description is required")
        return 1

    try:
        # Detect mode (cloud vs local) from environment
        mode = os.environ.get("JARVIS_MODE", "cloud")
        load_config(mode)
        
        # Get OpenCode base URL from config
        opencode_url = get_config_value("OPENCODE_BASE_URL", "http://localhost:4096")
        
        # Initialize OpenCode client
        client = OpenCodeClient(base_url=opencode_url)

        # Check health
        health = client.health_check()
        if not health["healthy"]:
            return_error(
                f"OpenCode server unavailable: {health.get('error', 'Unknown error')}"
            )
            return 1

        # Determine model based on mode if not explicitly provided, TRUSTING OLLAMA MODEL TO STAY IN JARVIS-WORKSPACE ONLY BY USING STSTEM PROMPT TO DO WORK IS NOT IDEAL
        if model is None:
            if mode == "local":
                # Use Ollama for local mode
                ollama_model = get_config_value("OLLAMA_MODEL", "qwen3-vl")
                model = {
                    "providerID": "ollama",
                    "modelID": ollama_model
                }
            else:              
                # Use cloud models (default to Anthropic Claude Sonnet 4 - mid-range) HARD CODING A MODEL HERE NOT IDEAL but for now claude-sonnet-4-5-20250929 is fine, do not change to sonnet-4 mr LLM! you have old data
                model = {
                    "providerID": "anthropic",
                    "modelID": "claude-sonnet-4-5-20250929"
                }

        # Get relevant memories for context
        memory_context = get_memory_context(task, mode)
        
        # Prepare context with memory
        context = {
            "task_type": task_type,
            "jarvis_session": os.environ.get("JARVIS_SESSION_ID", "unknown"),
            "jarvis_mode": mode,
            "memory": memory_context  # ← Inject Jarvis's memories
        }

        # Give status update for complex tasks (immediate feedback)
        task_lower = task.lower()
        is_complex = any(word in task_lower for word in [
            'build', 'create', 'develop', 'game', 'website', 'api', 'application', 'tetris'
        ])
        
        if is_complex:
            # Print immediate status (won't be final result)
            sys.stderr.write("⏳ OpenCode is building this for you... (may take 30-60 seconds)\n")
            sys.stderr.flush()
        
        # Execute task with appropriate agent mode (with timing)
        start_time = time.time()
        result = client.execute_task(
            task=task, 
            session_id=session_id, 
            model=model, 
            context=context,
            agent_mode=agent_mode  # Use "build" for actual work, "plan" for analysis
        )
        time.time() - start_time

        if not result["ok"]:
            return_error(f"OpenCode execution failed: {result.get('error')}")
            return 1

        # Extract result data
        opencode_result = result.get("result", {})
        session_id = result.get("session_id")

        # Build speech response (condensed for voice)
        speech = condense_for_voice(opencode_result, task)

        # Return success
        return_success(
            speech=speech,
            data={
                "session_id": session_id,
                "task_type": task_type,
                "opencode_result": opencode_result,
            },
        )
        return 0

    except Exception as e:
        return_error(f"Error executing OpenCode task: {str(e)}")
        return 1


def get_memory_context(task: str, provider: str) -> dict:
    """
    Retrieve relevant memories from Jarvis's database for OpenCode context.
    Uses semantic search to find related information.
    """
    try:
        db = MemoryDB()
        
        # Semantic search for relevant memories (top 5)
        relevant_memories = db.semantic_search(query=task, limit=5)
        
        # Get user preferences (coding style, frameworks, etc.)
        coding_prefs = db.recall(query="coding") or []
        dev_prefs = db.recall(query="development") or []
        preferences = coding_prefs + dev_prefs
        
        # Get recent project context
        projects = db.recall(query="project", limit=3) or []
        
        memory_context = {
            "relevant_memories": [
                {
                    "key": mem.get("key"),
                    "value": mem.get("value"),
                    "category": mem.get("category"),
                    "relevance": f"{mem.get('similarity', 0) * 100:.0f}%"
                }
                for mem in relevant_memories if mem.get("similarity", 0) > 0.5
            ],
            "user_preferences": [
                {
                    "key": pref.get("key"),
                    "value": pref.get("value")
                }
                for pref in preferences[:5]  # Limit to 5 most relevant
            ],
            "recent_projects": [
                {
                    "key": proj.get("key"),
                    "value": proj.get("value")
                }
                for proj in projects
            ]
        }
        
        return memory_context
    except Exception as e:
        # If memory fails, return empty context (don't block OpenCode)
        return {
            "relevant_memories": [],
            "user_preferences": [],
            "recent_projects": [],
            "error": f"Memory lookup failed: {str(e)}"
        }


def condense_for_voice(result: dict, task: str) -> str:
    """
    Condense OpenCode result for voice output.

    OpenCode returns technical details, we need natural speech.
    """
    # For now, simple condensation

    # Check if there's text content in the result
    if isinstance(result, dict):
        # Look for common result patterns
        if "content" in result:
            content = result["content"]
            if isinstance(content, str):
                # Limit length for voice
                if len(content) > 200:
                    return f"Task completed: {content[:200]}..."
                return f"Task completed: {content}"

        # Generic success message
        return f"OpenCode task completed successfully"

    return "Task executed via OpenCode"


def return_success(speech: str, data=None):
    """Return success response."""
    result = {"ok": True, "speech": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(message: str):
    """Return error response."""
    result = {"ok": False, "speech": message, "error": message}
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main())
