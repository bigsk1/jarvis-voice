#!/usr/bin/env python3
"""
Intelligence Layer Sandbox - Test Harness for Self-Learning System

Validates theories about:
1. Insight matching (relevance thresholds)
2. Confidence updates (helpful vs unhelpful tracking)
3. Self-correction when tools are enhanced
4. Decay and pruning behavior

Usage:
    # Run all tests
    python3 tests/integration/test_intelligence_sandbox.py
    
    # Run specific test
    python3 tests/integration/test_intelligence_sandbox.py --test matching
    
    # Show verbose output
    python3 tests/integration/test_intelligence_sandbox.py --verbose
"""

import os
import sys
import json
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))

from config_loader import load_config
from intelligence_hooks import (
    get_routing_insights,
    _evaluate_insight_helpfulness,
    format_insights_for_prompt
)

# ============================================
# TEST SCENARIOS
# ============================================

@dataclass
class TestScenario:
    """A test scenario for the intelligence layer."""
    name: str
    description: str
    query: str
    expected_insights: List[str]  # Insight IDs or descriptions we expect to match
    expected_biases: Dict[str, str]  # tool -> "prefer" or "avoid"
    tools_to_use: List[str]  # Simulate these tools being used
    outcome_success: bool
    expected_helpful: Dict[str, bool]  # insight_id -> expected helpful value


# Test scenarios to validate theories
SCENARIOS = [
    # ============================================
    # THEORY 1: Time queries should match time insights
    # ============================================
    TestScenario(
        name="local_time_query",
        description="Simple local time query should match get_time insights",
        query="What time is it?",
        expected_insights=["get_time"],
        expected_biases={"get_time": "prefer"},
        tools_to_use=["get_time"],
        outcome_success=True,
        expected_helpful={}
    ),
    TestScenario(
        name="city_time_query",
        description="City time query should match get_time (after enhancement)",
        query="What time is it in Tokyo?",
        expected_insights=["get_time"],
        expected_biases={"get_time": "prefer"},
        tools_to_use=["get_time"],
        outcome_success=True,
        expected_helpful={}
    ),
    
    # ============================================
    # THEORY 2: Crypto queries should match crypto insights
    # ============================================
    TestScenario(
        name="bitcoin_price",
        description="Bitcoin price query should match crypto_price insights",
        query="What is the current price of Bitcoin?",
        expected_insights=["crypto_price"],
        expected_biases={"crypto_price": "prefer", "search_memory": "avoid"},
        tools_to_use=["crypto_price"],
        outcome_success=True,
        expected_helpful={}
    ),
    
    # ============================================
    # THEORY 3: Weather queries should match weather insights
    # ============================================
    TestScenario(
        name="weather_query",
        description="Weather query should match weather tool insights",
        query="What's the weather in Seattle?",
        expected_insights=["weather"],
        expected_biases={"weather": "prefer"},
        tools_to_use=["weather"],
        outcome_success=True,
        expected_helpful={}
    ),
    
    # ============================================
    # THEORY 4: Server status should check memory first
    # ============================================
    TestScenario(
        name="server_status",
        description="Server status should prefer memory check first",
        query="Is my Ollama server running?",
        expected_insights=["memory", "fetch"],
        expected_biases={},  # Complex - could go either way
        tools_to_use=["semantic_recall", "mcp_fetch_fetch"],
        outcome_success=True,
        expected_helpful={}
    ),
    
    # ============================================
    # THEORY 5: Negative constraint contradicted = NOT helpful
    # ============================================
    TestScenario(
        name="negative_contradicted_success",
        description="When 'avoid X' is contradicted and X succeeds, insight should be NOT helpful",
        query="Test query",
        expected_insights=[],
        expected_biases={},
        tools_to_use=["avoided_tool"],
        outcome_success=True,
        expected_helpful={"negative_insight": False}  # KEY TEST
    ),
]


# ============================================
# TEST RUNNER
# ============================================

class SandboxRunner:
    """Runs sandbox tests and reports results."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results = []
        
    def run_all(self) -> Dict[str, Any]:
        """Run all test scenarios."""
        print("\n" + "="*60)
        print("🧪 INTELLIGENCE LAYER SANDBOX")
        print("="*60 + "\n")
        
        # Load config
        load_config('cloud')
        
        for scenario in SCENARIOS:
            result = self.run_scenario(scenario)
            self.results.append(result)
        
        return self.summarize()
    
    def run_scenario(self, scenario: TestScenario) -> Dict[str, Any]:
        """Run a single test scenario."""
        print(f"📋 Test: {scenario.name}")
        print(f"   {scenario.description}")
        print(f"   Query: \"{scenario.query}\"")
        
        result = {
            "name": scenario.name,
            "passed": True,
            "failures": [],
            "insights_found": [],
            "biases": {}
        }
        
        # Get routing insights for query
        try:
            insights = get_routing_insights(scenario.query)
            result["insights_found"] = [i.get('description', '')[:50] for i in insights.get('insights', [])]
            result["biases"] = insights.get('tool_biases', {})
            
            if self.verbose:
                print(f"   Found {len(insights.get('insights', []))} insights")
                for i in insights.get('insights', [])[:3]:
                    print(f"      - {i.get('description', '')[:60]}...")
                print(f"   Biases: {dict(list(result['biases'].items())[:5])}")
            
            # Check expected insights matched
            for expected in scenario.expected_insights:
                found = any(
                    expected.lower() in str(i.get('description', '')).lower() or
                    expected.lower() in str(result['biases'].keys()).lower()
                    for i in insights.get('insights', [])
                ) or expected.lower() in str(result['biases'].keys()).lower()
                
                if not found:
                    result["failures"].append(f"Expected insight about '{expected}' not found")
                    result["passed"] = False
            
            # Check expected biases
            for tool, expected_direction in scenario.expected_biases.items():
                actual_bias = result['biases'].get(tool, 0)
                if expected_direction == "prefer" and actual_bias <= 0:
                    result["failures"].append(f"Expected PREFER {tool}, got bias={actual_bias:.2f}")
                    result["passed"] = False
                elif expected_direction == "avoid" and actual_bias >= 0:
                    result["failures"].append(f"Expected AVOID {tool}, got bias={actual_bias:.2f}")
                    result["passed"] = False
                    
        except Exception as e:
            result["failures"].append(f"Exception: {e}")
            result["passed"] = False
        
        # Report
        if result["passed"]:
            print(f"   ✅ PASSED\n")
        else:
            print(f"   ❌ FAILED")
            for f in result["failures"]:
                print(f"      - {f}")
            print()
        
        return result
    
    def test_helpfulness_tracking(self) -> Dict[str, Any]:
        """Test the _evaluate_insight_helpfulness function."""
        print("\n" + "="*60)
        print("🧪 HELPFULNESS TRACKING TESTS")
        print("="*60 + "\n")
        
        test_cases = [
            # (insight_dict, tools_used, outcome_success, expected_helpful, description)
            (
                {"constraint_type": "negative", "avoided_tools": ["get_time"]},
                ["mcp_fetch_fetch"],
                True,
                True,
                "Followed 'avoid get_time' + SUCCESS → helpful"
            ),
            (
                {"constraint_type": "negative", "avoided_tools": ["get_time"]},
                ["get_time"],
                True,
                False,
                "VIOLATED 'avoid get_time' + SUCCESS → NOT helpful (THE FIX)"
            ),
            (
                {"constraint_type": "negative", "avoided_tools": ["get_time"]},
                ["get_time"],
                False,
                True,
                "Violated 'avoid get_time' + FAILURE → helpful (advice was correct)"
            ),
            (
                {"constraint_type": "positive", "avoided_tools": []},
                ["any_tool"],
                True,
                True,
                "Positive insight + SUCCESS → helpful"
            ),
            (
                {"constraint_type": "positive", "avoided_tools": []},
                ["any_tool"],
                False,
                False,
                "Positive insight + FAILURE → NOT helpful"
            ),
        ]
        
        all_passed = True
        for insight, tools, success, expected, desc in test_cases:
            actual = _evaluate_insight_helpfulness(insight, tools, success)
            passed = actual == expected
            
            icon = "✅" if passed else "❌"
            print(f"{icon} {desc}")
            print(f"   Expected: {expected}, Got: {actual}")
            
            if not passed:
                all_passed = False
        
        print(f"\n{'✅ All helpfulness tests PASSED' if all_passed else '❌ Some tests FAILED'}\n")
        return {"passed": all_passed}
    
    def summarize(self) -> Dict[str, Any]:
        """Summarize all test results."""
        passed = sum(1 for r in self.results if r["passed"])
        failed = len(self.results) - passed
        
        print("="*60)
        print("📊 SUMMARY")
        print("="*60)
        print(f"   Total: {len(self.results)}")
        print(f"   Passed: {passed}")
        print(f"   Failed: {failed}")
        print()
        
        if failed > 0:
            print("❌ Failed tests:")
            for r in self.results:
                if not r["passed"]:
                    print(f"   - {r['name']}: {', '.join(r['failures'])}")
            print()
        
        return {
            "total": len(self.results),
            "passed": passed,
            "failed": failed,
            "success_rate": passed / len(self.results) if self.results else 0
        }


# ============================================
# INSIGHT ANALYSIS
# ============================================

def analyze_insight_coverage():
    """Analyze why some insights are never applied."""
    print("\n" + "="*60)
    print("📊 INSIGHT COVERAGE ANALYSIS")
    print("="*60 + "\n")
    
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'jarvis_intelligence.db')
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Get stats
    cursor = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN times_applied > 0 THEN 1 ELSE 0 END) as applied,
            SUM(CASE WHEN times_applied = 0 THEN 1 ELSE 0 END) as never_applied,
            ROUND(AVG(times_applied), 2) as avg_applied,
            ROUND(AVG(confidence), 2) as avg_confidence
        FROM insights
    """)
    stats = dict(cursor.fetchone())
    
    print(f"Total insights: {stats['total']}")
    print(f"Applied at least once: {stats['applied']} ({100*stats['applied']/stats['total']:.0f}%)")
    print(f"Never applied: {stats['never_applied']} ({100*stats['never_applied']/stats['total']:.0f}%)")
    print(f"Average applications: {stats['avg_applied']}")
    print(f"Average confidence: {stats['avg_confidence']}")
    
    # Sample of never-applied insights
    print("\n📋 Sample of never-applied insights:")
    cursor = conn.execute("""
        SELECT id, substr(description, 1, 70) as desc, constraint_type
        FROM insights 
        WHERE times_applied = 0 
        ORDER BY RANDOM() 
        LIMIT 5
    """)
    for row in cursor:
        print(f"   [{row['constraint_type']}] {row['desc']}...")
    
    # Most applied insights
    print("\n⭐ Most applied insights:")
    cursor = conn.execute("""
        SELECT id, substr(description, 1, 50) as desc, times_applied, times_helpful
        FROM insights 
        WHERE times_applied > 0 
        ORDER BY times_applied DESC 
        LIMIT 5
    """)
    for row in cursor:
        print(f"   {row['times_applied']}x applied, {row['times_helpful']}x helpful: {row['desc']}...")
    
    conn.close()
    
    print("\n💡 ANALYSIS:")
    if stats['never_applied'] / stats['total'] > 0.5:
        print("   - High % of never-applied insights suggests:")
        print("     1. Query diversity is low (same questions repeated)")
        print("     2. Some insights are very specific (niche scenarios)")
        print("     3. This may be NORMAL for a new system")
    
    return stats


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Intelligence Layer Sandbox")
    parser.add_argument("--test", choices=["matching", "helpfulness", "analysis", "all"], 
                        default="all", help="Which tests to run")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()
    
    runner = SandboxRunner(verbose=args.verbose)
    
    if args.test in ["matching", "all"]:
        runner.run_all()
    
    if args.test in ["helpfulness", "all"]:
        runner.test_helpfulness_tracking()
    
    if args.test in ["analysis", "all"]:
        analyze_insight_coverage()
    
    print("\n✅ Sandbox complete!")

