#!/usr/bin/env python3
"""
Remember Tool - Store information in persistent memory
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db


def main():
    """Store information in memory."""
    try:
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        category = args.get('category', 'fact')
        key = args.get('key')
        value = args.get('value')
        importance = args.get('importance', 5)
        
        if not key or not value:
            result = {
                "ok": False,
                "speech": "I need both a key and value to remember something",
                "error": "Missing required parameters"
            }
            print(json.dumps(result))
            return result
        
        # Store in memory
        db = get_memory_db()
        memory_id = db.remember(
            category=category,
            key=key,
            value=value,
            importance=importance,
            source="user_conversation"
        )
        db.close()
        
        result = {
            "ok": True,
            "speech": f"I'll remember that: {key} is {value}",
            "data": {
                "memory_id": memory_id,
                "category": category,
                "key": key,
                "value": value,
                "importance": importance
            }
        }
        
        print(json.dumps(result))
        return result
        
    except Exception as e:
        error_result = {
            "ok": False,
            "speech": f"Failed to store memory: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()

