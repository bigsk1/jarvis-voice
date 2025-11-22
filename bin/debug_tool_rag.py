#!/usr/bin/env python3
"""
Tool RAG Debugger
Shows exactly what tools are retrieved and their similarity scores for a given query.
Helps debug tool selection issues.

Usage:
    ./bin/debug_tool_rag.py cloud "What is the price of Bitcoin?"
    ./bin/debug_tool_rag.py local "Remind me to call mom"
"""

import sys
import os
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value, get_float
from memory_db import get_memory_db
from tool_schema import ToolRegistry

def debug_tool_rag(mode: str, query: str):
    """Debug tool retrieval for a query."""
    print(f"🔍 Tool RAG Debugger")
    print(f"=" * 80)
    print(f"Mode: {mode}")
    print(f"Query: {query}")
    print(f"=" * 80)
    print()
    
    # Load config
    load_config(mode)
    
    # Get configuration
    ghost_tools_str = get_config_value('GHOST_TOOLS', 'search_memory,semantic_recall,remember,check_tool_logs,get_recent_conversations,get_time')
    ghost_tools = [t.strip() for t in ghost_tools_str.split(',')]
    threshold = get_float('TOOL_SIMILARITY_THRESHOLD', 0.0)
    retrieval_limit = 5 if mode == 'local' else 15
    
    print(f"📋 Configuration:")
    print(f"   Ghost Tools: {', '.join(ghost_tools)}")
    print(f"   Similarity Threshold: {threshold}")
    print(f"   Retrieval Limit: {retrieval_limit}")
    print()
    
    # Get database tools
    db = get_memory_db()
    all_tools = db.search_tools(query, limit=100, threshold=0.0)  # Get all for comparison
    
    print(f"🔎 Vector Search Results (Top 20):")
    print(f"   {'Rank':<6} {'Score':<8} {'Tool Name':<40} {'Pass Threshold?':<15}")
    print(f"   {'-'*6} {'-'*8} {'-'*40} {'-'*15}")
    
    for i, tool in enumerate(all_tools[:20], 1):
        name = tool['name']
        score = tool['similarity']
        passed = "✅ YES" if score >= threshold else "❌ NO"
        ghost_marker = "👻" if name in ghost_tools else "  "
        print(f"   {i:<6} {score:<8.4f} {ghost_marker} {name:<38} {passed}")
    
    print()
    
    # Get what would actually be sent to LLM
    print(f"📚 Tools Sent to LLM:")
    retrieved_tools = db.search_tools(query, limit=retrieval_limit, threshold=threshold)
    retrieved_names = [t['name'] for t in retrieved_tools]
    
    # Add ghost tools
    final_names = list(retrieved_names)
    for ghost in ghost_tools:
        if ghost not in final_names:
            final_names.append(ghost)
    
    print(f"   Total: {len(final_names)} tools")
    print(f"   Retrieved: {len(retrieved_names)} tools")
    print(f"   Ghost: {len([g for g in ghost_tools if g not in retrieved_names])} tools")
    print()
    
    print(f"   Retrieved Tools:")
    for name in retrieved_names:
        score = next((t['similarity'] for t in retrieved_tools if t['name'] == name), 0)
        print(f"      • {name} (score: {score:.4f})")
    
    print()
    print(f"   👻 Ghost Tools (always included):")
    for ghost in ghost_tools:
        if ghost in retrieved_names:
            print(f"      • {ghost} (also retrieved)")
        else:
            print(f"      • {ghost}")
    
    print()
    
    # Show tools that DIDN'T make the cut
    missed = [t for t in all_tools if t['name'] not in final_names][:10]
    if missed:
        print(f"❌ Tools NOT Retrieved (Top 10 highest scoring):")
        for tool in missed:
            print(f"      • {tool['name']} (score: {tool['similarity']:.4f})")
        print()
    
    # Recommendations
    print(f"💡 Recommendations:")
    if len(retrieved_names) == 0:
        print(f"   ⚠️  NO tools retrieved! Consider:")
        print(f"      - Lowering TOOL_SIMILARITY_THRESHOLD (current: {threshold})")
        print(f"      - Re-running sync_tools.py to update embeddings")
        print(f"      - Checking if tool descriptions match user queries")
    elif len(retrieved_names) < 3:
        print(f"   ⚠️  Only {len(retrieved_names)} tools retrieved. Consider:")
        print(f"      - Lowering TOOL_SIMILARITY_THRESHOLD (current: {threshold})")
    elif len(retrieved_names) > retrieval_limit * 0.8:
        print(f"   ⚠️  Many tools retrieved ({len(retrieved_names)}). Consider:")
        print(f"      - Raising TOOL_SIMILARITY_THRESHOLD (current: {threshold})")
    else:
        print(f"   ✅ Retrieval looks good ({len(retrieved_names)} tools)")
    
    db.close()

def main():
    if len(sys.argv) < 3:
        print("Usage: debug_tool_rag.py <mode> <query>")
        print("  mode: 'cloud' or 'local'")
        print("  query: User's question/request")
        print()
        print("Example:")
        print("  ./bin/debug_tool_rag.py cloud 'What is the price of Bitcoin?'")
        sys.exit(1)
    
    mode = sys.argv[1]
    query = ' '.join(sys.argv[2:])
    
    debug_tool_rag(mode, query)

if __name__ == "__main__":
    main()

