#!/usr/bin/env python3
"""
Optimize Grafana dashboard queries for better performance.

Changes:
1. Replace [24h] with [1h] for instant queries (24x faster!)
2. Remove | json from count_over_time (no parsing needed)
3. Add longer refresh intervals (reduce query load)
"""

import json
from pathlib import Path

def optimize_query(expr, query_type):
    """Optimize a single LogQL query."""
    if not expr:
        return expr
    
    # For instant queries, reduce time range
    if query_type == "instant":
        # Replace [24h] with [1h]
        expr = expr.replace("[24h]", "[1h]")
        expr = expr.replace("[$__range]", "[1h]")
    
    # Remove | json from count_over_time (counting lines doesn't need parsing)
    if "count_over_time" in expr and "| json" in expr:
        expr = expr.replace(" | json", "")
    
    return expr

def optimize_dashboard(dashboard_path):
    """Optimize a single dashboard file."""
    print(f"\n🔧 Optimizing: {dashboard_path.name}")
    
    with open(dashboard_path, 'r') as f:
        dashboard = json.load(f)
    
    changes_made = 0
    
    # Optimize panel queries
    if "panels" in dashboard:
        for panel in dashboard["panels"]:
            if "targets" in panel:
                for target in panel["targets"]:
                    if "expr" in target:
                        old_expr = target["expr"]
                        query_type = target.get("queryType", "range")
                        new_expr = optimize_query(old_expr, query_type)
                        
                        if old_expr != new_expr:
                            target["expr"] = new_expr
                            changes_made += 1
                            print(f"  ✅ Optimized query in panel: {panel.get('title', 'Unknown')}")
                            print(f"     Old: {old_expr[:80]}...")
                            print(f"     New: {new_expr[:80]}...")
    
    # Set longer refresh interval (if not already set)
    if dashboard.get("refresh", "") not in ["1m", "5m", "10m"]:
        dashboard["refresh"] = "1m"
        print(f"  ✅ Set refresh interval to 1 minute")
        changes_made += 1
    
    if changes_made > 0:
        # Write optimized dashboard
        with open(dashboard_path, 'w') as f:
            json.dump(dashboard, f, indent=2)
        print(f"  ✅ Saved {changes_made} optimization(s)")
    else:
        print(f"  ℹ️  No optimizations needed")
    
    return changes_made

def main():
    dashboards_dir = Path(__file__).parent / "grafana" / "dashboards"
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  📊 OPTIMIZING GRAFANA DASHBOARDS")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("\nOptimizations:")
    print("  • [24h] → [1h] for instant queries (24x faster!)")
    print("  • Remove | json from count queries (no parsing)")
    print("  • Set refresh interval to 1 minute")
    
    total_changes = 0
    
    for dashboard_file in dashboards_dir.glob("jarvis-*.json"):
        try:
            changes = optimize_dashboard(dashboard_file)
            total_changes += changes
        except Exception as e:
            print(f"  ❌ Error optimizing {dashboard_file.name}: {e}")
    
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if total_changes > 0:
        print(f"  ✅ Made {total_changes} optimization(s) across all dashboards")
        print("\n🔄 Restart Grafana to apply changes:")
        print("   cd ~/jarvis-voice/monitoring")
        print("   docker compose restart grafana")
    else:
        print("  ℹ️  All dashboards already optimized!")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

if __name__ == "__main__":
    main()

