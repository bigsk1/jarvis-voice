#!/usr/bin/env python3
"""
Search Conversations Tool - Search previous conversation history
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db


def main():
    """Search conversation history."""
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
        
        # Search conversations
        db = get_memory_db()
        conversations = db.search_conversations(query=query, limit=limit)
        db.close()
        
        if not conversations:
            result = {
                "ok": True,
                "speech": f"I found no previous conversations about '{query}'",
                "data": {"conversations": [], "count": 0}
            }
        else:
            # Format speech output
            speech = f"I found {len(conversations)} previous conversation(s) about '{query}': "
            
            # Summarize tools used across conversations
            all_tools = []
            for conv in conversations:
                if conv.get('tools_used'):
                    tools_list = json.loads(conv['tools_used'])
                    all_tools.extend(tools_list)
            
            unique_tools = list(set(all_tools))
            
            if unique_tools:
                speech += f"Tools used: {', '.join(unique_tools)}. "
            
            # Add metadata if available
            for conv in conversations:
                if conv.get('metadata'):
                    try:
                        metadata = json.loads(conv['metadata'])
                        conv['metadata_parsed'] = metadata
                    except:
                        pass
            
            result = {
                "ok": True,
                "speech": speech,
                "data": {
                    "conversations": conversations,
                    "count": len(conversations),
                    "tools_used": unique_tools
                }
            }
        
        print(json.dumps(result))
        return result
        
    except Exception as e:
        error_result = {
            "ok": False,
            "speech": f"Failed to search conversations: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()

