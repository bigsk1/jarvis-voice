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
        search_query = args.get('search_query')
        category = args.get('category')
        importance = args.get('importance')
        
        if not new_value:
            result = {
                "ok": False,
                "speech": "I need a new value to update the memory",
                "error": "Missing new_value parameter"
            }
            print(json.dumps(result))
            return result
        
        # Get database connection
        db = get_memory_db()
        
        # If no memory_id provided, search for it
        if not memory_id:
            if not search_query:
                result = {
                    "ok": False,
                    "speech": "I need either a memory ID or a search query to find the memory to update",
                    "error": "Missing memory_id or search_query"
                }
                print(json.dumps(result))
                db.close()
                return result
            
            # Search for the memory (try recall first, then semantic search)
            memories = db.recall(query=search_query, category=category, limit=1)
            
            if not memories:
                # Fallback to semantic search (no category filter available)
                all_memories = db.semantic_search(query=search_query, limit=5)
                # Filter by category if specified
                if category:
                    memories = [m for m in all_memories if m.get('category') == category][:1]
                else:
                    memories = all_memories[:1]
            
            if not memories:
                result = {
                    "ok": False,
                    "speech": f"I couldn't find any memories matching '{search_query}'",
                    "error": "No matching memories found"
                }
                print(json.dumps(result))
                db.close()
                return result
            
            # Use the first matching memory
            memory_id = memories[0]['id']
            old_value = memories[0].get('value', '')
        else:
            old_value = None
        
        # Update memory
        success = db.update_memory(
            memory_id=memory_id,
            value=new_value,
            importance=importance
        )
        db.close()
        
        if success:
            if old_value:
                speech = f"I've updated that memory from '{old_value}' to '{new_value}'"
            else:
                speech = f"I've updated that memory to: {new_value}"
            
            result = {
                "ok": True,
                "speech": speech,
                "data": {
                    "memory_id": memory_id,
                    "old_value": old_value,
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

