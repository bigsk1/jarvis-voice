#!/usr/bin/env python3
"""
Get Recent Conversations Tool - Retrieve recent conversation history
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db


def main():
    """Get recent conversations."""
    try:
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        limit = args.get('limit', 10)
        session_id = args.get('session_id')
        
        # Get conversations
        db = get_memory_db()
        conversations = db.get_recent_conversations(limit=limit, session_id=session_id)
        db.close()
        
        if not conversations:
            scope = "this session" if session_id else "overall"
            result = {
                "ok": True,
                "speech": f"No conversation history found for {scope}",
                "data": {"conversations": [], "count": 0}
            }
        else:
            # Summarize tools used
            all_tools = []
            for conv in conversations:
                if conv.get('tools_used'):
                    tools_list = json.loads(conv['tools_used'])
                    all_tools.extend(tools_list)
            
            unique_tools = list(set(all_tools))
            
            # Parse metadata for each conversation
            for conv in conversations:
                if conv.get('metadata'):
                    try:
                        metadata = json.loads(conv['metadata'])
                        conv['metadata_parsed'] = metadata
                    except:
                        pass
            
            scope = "this session" if session_id else "recent"
            speech = f"Found {len(conversations)} {scope} conversation(s). "
            if unique_tools:
                speech += f"Tools used: {', '.join(unique_tools)}."
            
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
            "speech": f"Failed to retrieve conversations: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()

