#!/usr/bin/env python3
"""
Semantic Recall Tool - AI-powered memory search using embeddings
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db
from config_loader import load_config


def main():
    """Semantic search across memories."""
    try:
        # CRITICAL: Load config to set correct embedding provider (local vs cloud)
        load_config()  # Auto-detects mode from LLM_PROVIDER
        
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        query = args.get('query')
        limit = args.get('limit', 5)
        
        if not query:
            result = {
                "ok": False,
                "speech": "I need a search query for semantic recall",
                "error": "Missing query parameter"
            }
            print(json.dumps(result))
            return result
        
        # Semantic search
        db = get_memory_db()
        memories = db.semantic_search(query=query, limit=limit)
        semantic_meta = getattr(db, 'last_semantic_search_meta', {"fallback_embeddings": None})
        db.close()
        
        if not memories:
            result = {
                "ok": True,
                "speech": f"I couldn't find any memories related to '{query}'",
                "data": {"memories": []}
            }
        else:
            # Format speech with similarity scores
            top_result = memories[0]
            similarity = top_result.get('similarity', 0) * 100
            
            if len(memories) == 1:
                speech = f"{top_result['key']}: {top_result['value']} (relevance: {similarity:.0f}%)"
            else:
                speech = f"Found {len(memories)} related memories: " + \
                         ", ".join([f"{m['key']}: {m['value']}" for m in memories[:3]])
            
            result = {
                "ok": True,
                "speech": speech,
                "data": {
                    "memories": memories,
                    "count": len(memories),
                    "embedding_diagnostics": semantic_meta,
                },
                "fallback_embeddings": semantic_meta.get("fallback_embeddings"),
            }
        if "fallback_embeddings" not in result:
            result["fallback_embeddings"] = semantic_meta.get("fallback_embeddings")
            if "data" in result:
                result["data"]["embedding_diagnostics"] = semantic_meta
        
        print(json.dumps(result))
        return result
        
    except Exception as e:
        error_result = {
            "ok": False,
            "speech": f"Failed to perform semantic search: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()
