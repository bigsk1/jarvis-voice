#!/usr/bin/env python3
"""
Forget Tool - Delete memories by ID or search query
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db


def main():
    """Delete a memory from database by ID or search query."""
    try:
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        memory_id = args.get('memory_id')
        search_query = args.get('search_query')
        
        db = get_memory_db()
        
        # If no memory_id, try to find by search_query
        if not memory_id and search_query:
            # Search for matching memories
            memories = db.search_memory(query=search_query, limit=5)
            
            if not memories:
                result = {
                    "ok": False,
                    "speech": f"I couldn't find any memories matching '{search_query}'",
                    "error": "No matching memories found"
                }
                print(json.dumps(result))
                db.close()
                return result
            
            # Take the best match (first result)
            memory_id = memories[0].get('id')
            memories[0].get('key', 'unknown')
            memories[0].get('value', '')[:50]
        
        if not memory_id:
            result = {
                "ok": False,
                "speech": "I need either a memory ID or search keywords to forget something",
                "error": "Missing memory_id or search_query parameter"
            }
            print(json.dumps(result))
            db.close()
            return result
        
        # Get memory info before deleting (for confirmation message)
        memory_info = None
        try:
            memories = db.search_memory(query="", limit=1000)  # Get all to find by ID
            for m in memories:
                if m.get('id') == memory_id:
                    memory_info = m
                    break
        except:
            pass
        
        # Delete memory
        success = db.forget(memory_id=memory_id)
        db.close()
        
        if success:
            if memory_info:
                key = memory_info.get('key', 'that memory')
                result = {
                    "ok": True,
                    "speech": f"I've forgotten about {key}",
                    "data": {"deleted_id": memory_id, "deleted_key": key}
                }
            else:
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

