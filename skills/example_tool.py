#!/usr/bin/env python3
"""
Jarvis Skill: Example Python Tool
Demonstrates how to create a Python-based tool.
"""
import sys
import json


def main():
    """Main tool logic."""
    # Read input from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        input_data = {}
    
    # Extract parameters
    name = input_data.get("name", "friend")
    
    # Do some work...
    message = f"Hello {name}, this is an example Python tool!"
    
    # Return JSON response
    result = {
        "ok": True,
        "speech": message,
        "data": {
            "name": name,
            "tool": "example_tool"
        }
    }
    
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

