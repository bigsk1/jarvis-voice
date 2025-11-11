#!/usr/bin/env python3
"""
Recall Tool - Retrieve stored memories
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db


def main():
    """Retrieve memories from database."""
    try:
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        query = args.get('query')
        category = args.get('category')
        limit = args.get('limit', 5)
        
        if not query:
            result = {
                "ok": False,
                "speech": "I need a search query to recall memories",
                "error": "Missing query parameter"
            }
            print(json.dumps(result))
            return result
        
        # Search memory
        db = get_memory_db()
        memories = db.recall(query=query, category=category, limit=limit)
        db.close()
        
        if not memories:
            result = {
                "ok": True,
                "speech": f"I don't have any memories about '{query}'",
                "data": {"memories": []}
            }
        else:
            # Format memories for speech
            if len(memories) == 1:
                mem = memories[0]
                speech = f"{mem['key']}: {mem['value']}"
            else:
                speech = f"I found {len(memories)} memories about '{query}': " + \
                         ", ".join([f"{m['key']}: {m['value']}" for m in memories[:3]])
            
            result = {
                "ok": True,
                "speech": speech,
                "data": {"memories": memories}
            }
        
        print(json.dumps(result))
        return result
        
    except Exception as e:
        error_result = {
            "ok": False,
            "speech": f"Failed to recall memories: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()

