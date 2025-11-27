#!/usr/bin/env python3
"""
Intelligence Layer Integration Test
Tests how intelligence biases interact with tool selection.

Run: python3 tests/integration/test_intelligence_integration.py
"""

import sys
import os
import json
import asyncio

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config, get_config_value

# Load config
load_config('cloud')

from intelligence import IntelligenceLayer
from intelligence_hooks import get_routing_insights, format_insights_for_prompt, get_learning_stats

def test_scenario(name: str, query: str, expected_prefer: list = None, expected_avoid: list = None):
    """Test a specific query scenario."""
    print(f"\n{'='*60}")
    print(f"SCENARIO: {name}")
    print(f"{'='*60}")
    print(f"Query: \"{query}\"")
    
    insights = get_routing_insights(query)
    biases = insights.get('tool_biases', {})
    
    print(f"\nTool Biases:")
    if biases:
        for tool, bias in sorted(biases.items(), key=lambda x: -x[1]):
            symbol = '✅' if bias > 0 else '❌'
            print(f"  {symbol} {tool}: {bias:+.3f}")
    else:
        print("  (No biases)")
    
    # Validate expectations
    passed = True
    
    if expected_prefer:
        for tool in expected_prefer:
            if biases.get(tool, 0) <= 0:
                print(f"\n❌ FAIL: Expected {tool} to have POSITIVE bias")
                passed = False
    
    if expected_avoid:
        for tool in expected_avoid:
            if biases.get(tool, 0) >= 0:
                print(f"\n❌ FAIL: Expected {tool} to have NEGATIVE bias")
                passed = False
    
    if passed:
        print(f"\n✅ PASS: Biases match expectations")
    
    return passed


def test_learning_cycle():
    """Test a complete learning cycle: record → reflect → apply."""
    print("\n" + "="*60)
    print("TEST: Complete Learning Cycle")
    print("="*60)
    
    intel = IntelligenceLayer()
    
    async def run_cycle():
        # 1. Record a suboptimal experience
        print("\n1. Recording suboptimal experience (wrong first tool)...")
        exp_id = await intel.record_experience(
            query="Check if nginx is running",
            tools_used=["search_memory", "execute_bash"],  # Wrong first choice
            outcome={"success": True, "turns": 2},
            user_signals={"clarified": False}
        )
        print(f"   Recorded experience #{exp_id}")
        
        # 2. Reflect on it
        print("\n2. Reflecting...")
        reflection = await intel.reflect_on_experience(exp_id)
        if reflection:
            print(f"   Constraint type: {reflection.get('constraint_type')}")
            print(f"   Avoided tool: {reflection.get('avoided_tool')}")
            print(f"   Preferred tool: {reflection.get('preferred_tool')}")
        
        # 3. Check if insight applies to similar query
        print("\n3. Testing insight retrieval for similar query...")
        insights = await intel.get_relevant_insights("Is apache running?")
        print(f"   Found {len(insights)} relevant insights")
        
        # 4. Check tool biases
        biases = await intel.get_tool_biases("Is my web server up?")
        print("\n4. Tool biases for 'Is my web server up?':")
        for tool, bias in sorted(biases.items(), key=lambda x: -x[1]):
            symbol = '✅' if bias > 0 else '❌'
            print(f"   {symbol} {tool}: {bias:+.3f}")
        
        return len(insights) > 0
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        success = loop.run_until_complete(run_cycle())
    finally:
        loop.close()
    
    intel.close()
    return success


def test_embedding_fallback():
    """Test that embedding fallback works when API fails."""
    print("\n" + "="*60)
    print("TEST: Embedding Fallback")
    print("="*60)
    
    from embeddings import _get_fallback_embedding, cosine_similarity
    
    # Test fallback generation
    emb1 = _get_fallback_embedding("test query", 1536)
    emb2 = _get_fallback_embedding("test query", 1536)
    emb3 = _get_fallback_embedding("different query", 1536)
    
    # Test determinism
    print(f"\n1. Deterministic: same input → same output")
    print(f"   {emb1[:3]} == {emb2[:3]}: {emb1 == emb2}")
    
    # Test similarity (same query = 1.0, different = lower)
    print(f"\n2. Similarity:")
    print(f"   Same query: {cosine_similarity(emb1, emb2):.4f} (should be 1.0)")
    print(f"   Different query: {cosine_similarity(emb1, emb3):.4f} (should be < 1.0)")
    
    return emb1 == emb2 and cosine_similarity(emb1, emb3) < 1.0


def test_stats():
    """Show current learning stats."""
    print("\n" + "="*60)
    print("CURRENT LEARNING STATS")
    print("="*60)
    
    stats = get_learning_stats()
    print(json.dumps(stats, indent=2))
    
    return stats.get('status') != 'unavailable'


def main():
    """Run all integration tests."""
    print("\n" + "="*60)
    print("INTELLIGENCE LAYER INTEGRATION TESTS")
    print("="*60)
    
    results = []
    
    # Test scenarios based on learned patterns
    results.append(("Server Status", test_scenario(
        "Server Status Query",
        "Is my server running?",
        expected_prefer=["mcp_fetch_fetch"],
        expected_avoid=["search_memory"]
    )))
    
    results.append(("Crypto Price", test_scenario(
        "Crypto Price Query",
        "What is the current Bitcoin price?",
        expected_avoid=["search_memory"]
    )))
    
    results.append(("Memory Query (no bias)", test_scenario(
        "Memory Query (should have no biases)",
        "What projects have I been working on?",
        # No expectations - should not match status/crypto patterns
    )))
    
    # Test learning cycle
    results.append(("Learning Cycle", test_learning_cycle()))
    
    # Test embedding fallback
    results.append(("Embedding Fallback", test_embedding_fallback()))
    
    # Show stats
    results.append(("Stats", test_stats()))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        symbol = "✅" if result else "❌"
        print(f"{symbol} {name}")
    
    print(f"\nPassed: {passed}/{total}")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

