#!/usr/bin/env python3
"""
Forget Tool - Delete memories
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db


def main():
    """Delete a memory from database."""
    try:
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        memory_id = args.get('memory_id')
        
        if not memory_id:
            result = {
                "ok": False,
                "speech": "I need a memory ID to forget",
                "error": "Missing memory_id parameter"
            }
            print(json.dumps(result))
            return result
        
        # Delete memory
        db = get_memory_db()
        success = db.forget(memory_id=memory_id)
        db.close()
        
        if success:
            result = {
                "ok": True,
                "speech": f"I've forgotten that memory",
                "data": {"deleted_id": memory_id}
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
            "speech": f"Failed to forget memory: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()

