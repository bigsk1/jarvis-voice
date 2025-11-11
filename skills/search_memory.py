#!/usr/bin/env python3
"""
Search Memory Tool - Search all stored knowledge
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db


def main():
    """Search memories."""
    try:
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        query = args.get('query')
        limit = args.get('limit', 10)
        
        if not query:
            result = {
                "ok": False,
                "speech": "I need a search query",
                "error": "Missing query parameter"
            }
            print(json.dumps(result))
            return result
        
        # Search memory
        db = get_memory_db()
        memories = db.search_memory(query=query, limit=limit)
        db.close()
        
        # Remove embedding blobs (not JSON serializable)
        for mem in memories:
            if 'embedding' in mem:
                del mem['embedding']
        
        if not memories:
            result = {
                "ok": True,
                "speech": f"I found no memories matching '{query}'",
                "data": {"memories": [], "count": 0}
            }
        else:
            # Group by category
            by_category = {}
            for mem in memories:
                cat = mem['category']
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(mem)
            
            speech = f"I found {len(memories)} memories about '{query}': "
            details = []
            for cat, mems in by_category.items():
                details.append(f"{len(mems)} {cat}")
            speech += ", ".join(details)
            
            result = {
                "ok": True,
                "speech": speech,
                "data": {
                    "memories": memories,
                    "count": len(memories),
                    "by_category": {cat: len(mems) for cat, mems in by_category.items()}
                }
            }
        
        print(json.dumps(result))
        return result
        
    except Exception as e:
        error_result = {
            "ok": False,
            "speech": f"Failed to search memories: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()

