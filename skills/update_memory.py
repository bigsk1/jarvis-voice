#!/usr/bin/env python3
"""
Update Memory Tool - Modify existing memories
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db


def main():
    """Update an existing memory."""
    try:
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        memory_id = args.get('memory_id')
        new_value = args.get('new_value')
        importance = args.get('importance')
        
        if not memory_id or not new_value:
            result = {
                "ok": False,
                "speech": "I need a memory ID and new value to update",
                "error": "Missing required parameters"
            }
            print(json.dumps(result))
            return result
        
        # Update memory
        db = get_memory_db()
        success = db.update_memory(
            memory_id=memory_id,
            value=new_value,
            importance=importance
        )
        db.close()
        
        if success:
            result = {
                "ok": True,
                "speech": f"I've updated that memory to: {new_value}",
                "data": {
                    "memory_id": memory_id,
                    "new_value": new_value
                }
            }
        else:
            result = {
                "ok": False,
                "speech": f"I couldn't find a memory with ID {memory_id}",
                "error": "Memory not found"
            }
        
        print(json.dumps(result))
        return result
        
    except Exception as e:
        error_result = {
            "ok": False,
            "speech": f"Failed to update memory: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()

