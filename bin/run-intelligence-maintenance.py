#!/usr/bin/env python3
"""
Intelligence Maintenance Runner

Manually trigger maintenance jobs:
- Decay: Reduce confidence of stale/unused insights
- Anomaly: Detect unusual experiences
- Meta-cognition: Analyze learning process health

Usage:
    ./bin/run-intelligence-maintenance.py              # Run all jobs
    ./bin/run-intelligence-maintenance.py --decay      # Run decay only
    ./bin/run-intelligence-maintenance.py --anomaly    # Run anomaly detection only
    ./bin/run-intelligence-maintenance.py --meta       # Run meta-cognition only
    ./bin/run-intelligence-maintenance.py --watch      # Run all and show logs
"""

import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config

def main():
    parser = argparse.ArgumentParser(description='Run intelligence maintenance jobs')
    parser.add_argument('--decay', action='store_true', help='Run decay job only')
    parser.add_argument('--anomaly', action='store_true', help='Run anomaly detection only')
    parser.add_argument('--meta', action='store_true', help='Run meta-cognition only')
    parser.add_argument('--force', action='store_true', help='Force run even if within minimum interval (use with caution!)')
    parser.add_argument('--watch', action='store_true', help='Show recent log entries after running')
    parser.add_argument('--mode', choices=['cloud', 'local'], default='cloud', help='Mode to run in')
    args = parser.parse_args()
    
    # Load config
    load_config(args.mode)
    
    # Import hooks after config loaded
    from intelligence_hooks import (
        run_decay_job, run_anomaly_detection, 
        run_meta_cognition, run_all_maintenance
    )
    
    print("=" * 60)
    print("🧠 INTELLIGENCE MAINTENANCE")
    print("=" * 60)
    print(f"Mode: {args.mode}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    results = {}
    
    if args.force:
        print("⚠️  FORCE MODE: Bypassing minimum interval checks!")
        print()
    
    if args.decay:
        print("Running decay job...")
        results['decay'] = run_decay_job(force=args.force)
    elif args.anomaly:
        print("Running anomaly detection...")
        results['anomaly'] = run_anomaly_detection()
    elif args.meta:
        print("Running meta-cognition...")
        results['meta_cognition'] = run_meta_cognition()
    else:
        print("Running ALL maintenance jobs...")
        results = run_all_maintenance(force=args.force)
    
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    # Pretty print results
    if 'decay' in results:
        decay = results['decay']
        if isinstance(decay, dict):
            if decay.get('status') == 'skipped':
                print("\n📉 DECAY JOB: ⏭️  SKIPPED")
                print(f"   Reason: {decay.get('reason', 'Unknown')}")
                print(f"   Last run: {decay.get('last_run', 'Unknown')}")
                print(f"   Next eligible: {decay.get('next_eligible', 'Unknown')}")
                print("   (Use --force to bypass)")
            elif decay.get('status') != 'error':
                print("\n📉 DECAY JOB:")
                print(f"   Insights checked: {decay.get('total_checked', 0)}")
                print(f"   Decayed: {decay.get('decayed', 0)}")
                print(f"   Boosted: {decay.get('boosted', 0)}")
                print(f"   Pruned: {decay.get('pruned', 0)}")
                print(f"   Unchanged: {decay.get('unchanged', 0)}")
            else:
                print(f"\n📉 DECAY JOB: {decay}")
        else:
            print(f"\n📉 DECAY JOB: {decay}")
    
    if 'anomalies' in results:
        anomalies = results['anomalies']
        if isinstance(anomalies, dict) and anomalies.get('status') != 'error':
            print("\n🔍 ANOMALY DETECTION:")
            print(f"   Baseline avg turns: {anomalies.get('baseline_avg_turns', 'N/A')}")
            print(f"   Baseline std dev: {anomalies.get('baseline_std_dev', 'N/A')}")
            print(f"   Anomalies found: {anomalies.get('anomalies_found', 0)}")
            if anomalies.get('anomalies'):
                for a in anomalies['anomalies'][:3]:
                    print(f"      ⚠️  Exp #{a['experience_id']}: {a['reasons'][0]['type']}")
        else:
            print(f"\n🔍 ANOMALY DETECTION: {anomalies}")
    
    if 'meta_cognition' in results:
        meta = results['meta_cognition']
        if isinstance(meta, dict) and meta.get('status') != 'error':
            print("\n🧠 META-COGNITION:")
            print(f"   Findings: {meta.get('findings_count', 0)}")
            if meta.get('quality_stats'):
                qs = meta['quality_stats']
                print(f"   Total insights: {qs.get('total_insights', 0)}")
                print(f"   Avg confidence: {qs.get('avg_confidence', 0):.1%}")
                print(f"   Insights used: {qs.get('insights_used', 0)}")
            if meta.get('findings'):
                for f in meta['findings'][:3]:
                    emoji = '🔴' if f['meta_type'] == 'blind_spot' else '🟡' if f['meta_type'] == 'over_generalization' else '🟢'
                    print(f"      {emoji} {f['meta_type']}: {f['observation'][:60]}...")
        else:
            print(f"\n🧠 META-COGNITION: {meta}")
    
    print()
    
    # Show recent logs if requested
    if args.watch:
        print("=" * 60)
        print("RECENT LOG ENTRIES")
        print("=" * 60)
        
        log_file = Path(__file__).parent.parent / "logs" / "intelligence" / f"intelligence-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        
        if log_file.exists():
            with open(log_file, 'r') as f:
                lines = f.readlines()
                # Show last 20 lines
                for line in lines[-20:]:
                    try:
                        entry = json.loads(line)
                        event = entry.get('event', 'unknown')
                        timestamp = entry.get('timestamp', '')[:19]
                        
                        # Color code by event type
                        if 'decay' in event:
                            prefix = '📉'
                        elif 'anomaly' in event:
                            prefix = '🔍'
                        elif 'meta' in event:
                            prefix = '🧠'
                        elif 'maintenance' in event:
                            prefix = '🔧'
                        else:
                            prefix = '📝'
                        
                        print(f"{prefix} [{timestamp}] {event}")
                        
                        # Show key details
                        if event == 'decay_applied':
                            print(f"      Insight #{entry.get('insight_id')}: {entry.get('old_confidence'):.2f} → {entry.get('new_confidence'):.2f}")
                        elif event == 'anomaly_detected':
                            print(f"      Exp #{entry.get('experience_id')}: {entry.get('anomaly_type')}")
                        elif event == 'meta_cognition':
                            print(f"      {entry.get('meta_type')}: {entry.get('observation', '')[:50]}")
                        elif event == 'maintenance_run':
                            print(f"      Job: {entry.get('job_type')}")
                            
                    except json.JSONDecodeError:
                        continue
        else:
            print(f"No log file found: {log_file}")
    
    print()
    print("✅ Maintenance complete!")
    print()
    print("Logs written to: logs/intelligence/intelligence-YYYY-MM-DD.jsonl")
    print("View in Grafana: http://192.168.70.228:3000 → Intelligence Dashboard")


if __name__ == "__main__":
    main()

