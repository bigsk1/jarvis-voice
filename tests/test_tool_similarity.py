#!/usr/bin/env python3
"""
Tool Similarity Ranking Test

Tests how well the Tool RAG system matches queries to expected tools.
Useful for tuning SEMANTIC_SIMILARITY_THRESHOLD.

Usage:
    ./tests/test_tool_similarity.py                    # Run default test queries
    ./tests/test_tool_similarity.py "play some music"  # Test a single query
    ./tests/test_tool_similarity.py --threshold 0.30   # Test with specific threshold
    ./tests/test_tool_similarity.py --all              # Show all tools for each query
"""

import sys
import os
import argparse

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from memory_db import MemoryDB
from config_loader import load_config, get_float

# Default test queries that REQUIRE tools (not answerable from system prompt)
DEFAULT_TEST_QUERIES = [
    ('Play my chill vibes playlist', 'spotify'),
    ('Call boss and ask about dinner', 'phone_call'),
    ('What is bitcoin price right now?', 'crypto_price'),
    ('Remember my wifi password is abc123', 'remember'),
    ('Show my reminders', 'list_reminders'),
    ('What did I ask you yesterday?', 'search_conversations'),
    ('Set speaker volume to 50 percent', 'speaker_volume'),
    ('Print this document', 'printer'),
    ('Create a PDF with this text', 'pdf_create'),
    ('Check the weather in Portland', 'weather'),
    ('Ping google.com', 'network_tools'),
    ('How much CPU am I using?', 'system_monitor'),
    ('Save this URL for later', 'stash'),
    ('Build me a flask app', 'opencode'),
    ('Send an email to Andrew', 'send_email'),
    ("What's my VPN network?", 'semantic_recall'),
    ('Search my memories for flask', 'search_memory'),
]


def test_single_query(db: MemoryDB, query: str, show_all: bool = False, limit: int = 10):
    """Test a single query and show tool rankings."""
    print(f'\n🔍 Query: "{query}"')
    print('-' * 50)
    
    # Get all tools with scores (no threshold filtering)
    results = db.search_tools(query, limit=limit, threshold=0.0)
    
    if not results:
        print("  ❌ No tools found!")
        return None
    
    # Show results
    count = len(results) if show_all else min(10, len(results))
    for i, tool in enumerate(results[:count]):
        score = tool.get('similarity', 0)
        name = tool.get('name', 'unknown')
        
        # Color coding based on score
        if score >= 0.40:
            marker = '✅'
        elif score >= 0.30:
            marker = '🟡'
        else:
            marker = '🔴'
        
        print(f'  {marker} {i+1:2d}. {name:30s} {score:.3f}')
    
    if not show_all and len(results) > 10:
        print(f'  ... and {len(results) - 10} more tools')
    
    return results


def test_expected_queries(db: MemoryDB, queries: list, current_threshold: float):
    """Test queries with expected tools and analyze threshold impact."""
    print('\n' + '=' * 60)
    print('=== TOOL RAG SIMILARITY ANALYSIS ===')
    print('=' * 60)
    
    all_expected_scores = []
    missed_tools = []
    
    for query, expected_tool in queries:
        # Get all tools with scores (no threshold filtering)
        results = db.search_tools(query, limit=20, threshold=0.0)
        
        # Find expected tool's rank and score
        expected_rank = None
        expected_score = None
        for i, tool in enumerate(results):
            if expected_tool.lower() in tool.get('name', '').lower():
                expected_rank = i + 1
                expected_score = tool.get('similarity', 0)
                break
        
        if expected_score:
            all_expected_scores.append((expected_tool, expected_score, expected_rank, query[:40]))
        else:
            missed_tools.append((expected_tool, query[:40]))
        
        # Show details for low-scoring or missed tools
        if not expected_score or expected_score < current_threshold:
            status = '⚠️  LOW SCORE' if expected_score else '❌ NOT FOUND'
            print(f'\n{status}: "{query}"')
            print(f'   Expected: {expected_tool}')
            if expected_score:
                print(f'   Score: {expected_score:.3f} (rank #{expected_rank})')
            else:
                print(f'   Not in top 20 results!')
            top3 = [f"{t['name']}:{t['similarity']:.2f}" for t in results[:3]]
            print(f'   Top 3: {top3}')
    
    # Summary
    print('\n' + '=' * 60)
    print('=== EXPECTED TOOL SCORES (sorted low → high) ===')
    print('=' * 60 + '\n')
    
    for tool, score, rank, query in sorted(all_expected_scores, key=lambda x: x[1]):
        status = '⚠️' if score < current_threshold else '✅'
        print(f'{status} {score:.3f} #{rank:2d} {tool:25s} "{query}..."')
    
    if missed_tools:
        print('\n❌ COMPLETELY MISSED:')
        for tool, query in missed_tools:
            print(f'   {tool}: "{query}..."')
    
    # Statistics
    if all_expected_scores:
        scores_only = [s[1] for s in all_expected_scores]
        print(f'\n📊 Statistics:')
        print(f'   Lowest:  {min(scores_only):.3f}')
        print(f'   Highest: {max(scores_only):.3f}')
        print(f'   Average: {sum(scores_only)/len(scores_only):.3f}')
        print(f'   Current threshold: {current_threshold}')
        
        # Threshold impact analysis
        print(f'\n🎯 Threshold Impact (expected tools missed):')
        for thresh in [0.20, 0.25, 0.28, 0.30, 0.32, 0.35, 0.38, 0.40, 0.45]:
            missed = sum(1 for s in scores_only if s < thresh)
            missed += len(missed_tools)  # Add completely missed tools
            total = len(scores_only) + len(missed_tools)
            pct = missed / total * 100 if total > 0 else 0
            marker = ' ← CURRENT' if abs(thresh - current_threshold) < 0.01 else ''
            status = '❌' if missed > 0 else '✅'
            print(f'   {thresh:.2f}: {status} {missed:2d}/{total} missed ({pct:.0f}%){marker}')
        
        # Recommendation
        safe_threshold = min(scores_only) - 0.02 if scores_only else 0.25
        print(f'\n💡 Recommendation:')
        print(f'   Safe threshold (catches all): {max(0.20, safe_threshold):.2f}')
        
    return all_expected_scores


def main():
    parser = argparse.ArgumentParser(description='Test Tool RAG similarity rankings')
    parser.add_argument('query', nargs='?', help='Single query to test (optional)')
    parser.add_argument('--threshold', '-t', type=float, help='Override threshold for analysis')
    parser.add_argument('--all', '-a', action='store_true', help='Show all tools, not just top 10')
    parser.add_argument('--mode', '-m', default='cloud', choices=['cloud', 'local'], 
                        help='Mode to use (default: cloud)')
    parser.add_argument('--limit', '-l', type=int, default=15, help='Number of tools to retrieve')
    
    args = parser.parse_args()
    
    # Load config
    load_config(args.mode)
    
    # Get current threshold
    current_threshold = args.threshold or get_float('SEMANTIC_SIMILARITY_THRESHOLD', 0.35)
    
    print(f'🔧 Mode: {args.mode}')
    print(f'📏 Current threshold: {current_threshold}')
    
    # Initialize DB
    db = MemoryDB()
    
    if args.query:
        # Single query mode
        test_single_query(db, args.query, show_all=args.all, limit=args.limit)
    else:
        # Run all test queries
        test_expected_queries(db, DEFAULT_TEST_QUERIES, current_threshold)
    
    print('\n✅ Done!')


if __name__ == '__main__':
    main()

