#!/usr/bin/env python3
"""
Jarvis Skill: OpenCode Integration
Execute complex tasks using OpenCode autonomous agent.
"""

import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from opencode_client import OpenCodeClient


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

    if not task:
        return_error("Task description is required")
        return 1

    try:
        # Initialize OpenCode client
        client = OpenCodeClient()

        # Check health
        health = client.health_check()
        if not health["healthy"]:
            return_error(
                f"OpenCode server unavailable: {health.get('error', 'Unknown error')}"
            )
            return 1

        # Prepare context
        context = {
            "task_type": task_type,
            "jarvis_session": os.environ.get("JARVIS_SESSION_ID", "unknown"),
        }

        # Execute task
        result = client.execute_task(
            task=task, session_id=session_id, model=model, context=context
        )

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


def condense_for_voice(result: dict, task: str) -> str:
    """
    Condense OpenCode result for voice output.

    OpenCode returns technical details, we need natural speech.
    """
    # For now, simple condensation
    # TODO: Use LLM to intelligently condense in Phase 2

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
