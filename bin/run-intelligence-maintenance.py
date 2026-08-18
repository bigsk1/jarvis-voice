#!/usr/bin/env python3
"""
Intelligence Maintenance Runner

Manually trigger maintenance jobs:
- Decay: Protect proven insights and retire weak/unsafe guidance
- Anomaly: Detect unusual experiences
- Meta-cognition: Analyze learning process health

Usage:
    ./bin/run-intelligence-maintenance.py              # Run all jobs
    ./bin/run-intelligence-maintenance.py --decay      # Run decay only
    ./bin/run-intelligence-maintenance.py --decay --dry-run  # Preview decay only
    ./bin/run-intelligence-maintenance.py --anomaly    # Run anomaly detection only
    ./bin/run-intelligence-maintenance.py --meta       # Run meta-cognition only
    ./bin/run-intelligence-maintenance.py --watch      # Run all and show logs
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _ensure_project_python() -> None:
    """Re-exec with a Jarvis environment before importing Intelligence."""
    candidates = [PROJECT_ROOT / ".venv"]
    configured_venv = os.environ.get("JARVIS_VENV")
    if configured_venv:
        candidates.append(Path(configured_venv).expanduser())
    candidates.append(Path.home() / "jarvis-venv")

    active_prefix = Path(sys.prefix).expanduser().resolve()
    for candidate in candidates:
        resolved = candidate.resolve()
        if active_prefix == resolved:
            return

    for candidate in candidates:
        expected_python = candidate.expanduser().resolve() / "bin" / "python"
        if expected_python.is_file():
            os.execv(
                str(expected_python),
                [str(expected_python), str(Path(__file__).resolve()), *sys.argv[1:]],
            )

    print(
        "ERROR: No Jarvis Python environment was found. Run 'uv sync --dev' "
        "or set JARVIS_VENV.",
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    _ensure_project_python()

# Add lib to path
sys.path.insert(0, str(PROJECT_ROOT / "lib"))


def _failed_jobs(results: dict) -> list[str]:
    """Return maintenance result keys that report an unavailable/error state."""
    failures = []
    top_status = str(results.get("status") or "").lower()
    if top_status in {"error", "unavailable"} or results.get("error"):
        failures.append("maintenance")
    for name, result in results.items():
        if not isinstance(result, dict):
            continue
        status = str(result.get("status") or "").lower()
        if status in {"error", "unavailable"} or result.get("error"):
            failures.append(name)
    return failures


def main():
    parser = argparse.ArgumentParser(description='Run intelligence maintenance jobs')
    parser.add_argument('--decay', action='store_true', help='Run decay job only')
    parser.add_argument('--anomaly', action='store_true', help='Run anomaly detection only')
    parser.add_argument('--meta', action='store_true', help='Run meta-cognition only')
    parser.add_argument('--force', action='store_true', help='Force run even if within minimum interval (use with caution!)')
    parser.add_argument('--dry-run', action='store_true', help='Preview decay changes without writing decay updates')
    parser.add_argument('--watch', action='store_true', help='Show recent log entries after running')
    parser.add_argument('--mode', choices=['cloud', 'local'], default='cloud', help='Mode to run in')
    args = parser.parse_args()
    
    # Hooks install an isolated mode-specific config scope for each job.
    from intelligence_hooks import (
        run_all_maintenance,
        run_anomaly_detection,
        run_decay_job,
        run_meta_cognition,
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

    if args.dry_run:
        print("DRY RUN: Decay changes will be calculated without writing updates.")
        if args.anomaly or args.meta:
            print("Note: --dry-run only applies to decay; anomaly/meta jobs will still write maintenance findings.")
        elif not args.decay:
            print("Note: --dry-run with all maintenance skips anomaly/meta write jobs.")
        print()
    
    if args.decay:
        print("Running decay job...")
        results['decay'] = run_decay_job(
            force=args.force,
            dry_run=args.dry_run,
            mode=args.mode,
        )
    elif args.anomaly:
        print("Running anomaly detection...")
        results['anomalies'] = run_anomaly_detection(mode=args.mode)
    elif args.meta:
        print("Running meta-cognition...")
        results['meta_cognition'] = run_meta_cognition(mode=args.mode)
    else:
        print("Running ALL maintenance jobs...")
        results = run_all_maintenance(
            force=args.force,
            dry_run=args.dry_run,
            mode=args.mode,
        )
    
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
            elif decay.get('status') in {'ok', 'dry_run'}:
                dry_label = " (DRY RUN)" if decay.get('dry_run') else ""
                print(f"\n📉 DECAY JOB:{dry_label}")
                print(f"   Insights checked: {decay.get('total_checked', 0)}")
                print(f"   Protected/recent: {decay.get('protected', 0)}")
                print(f"   Decayed: {decay.get('decayed', 0)}")
                print(f"   Pruned: {decay.get('pruned', 0)}")
                print(f"   Unchanged: {decay.get('unchanged', 0)}")
                print(f"   Average before: {decay.get('avg_confidence_before', 0):.1%}")
                print(
                    "   Average after (survivors): "
                    f"{decay.get('avg_confidence_after_survivors', 0):.1%}"
                )
                if decay.get('policy_counts'):
                    policies = ', '.join(
                        f"{name}={count}"
                        for name, count in sorted(decay['policy_counts'].items())
                    )
                    print(f"   Policies: {policies}")
                if decay.get('backup_path'):
                    print(f"   Backup: {decay['backup_path']}")
            else:
                print(f"\n📉 DECAY JOB: {decay}")
        else:
            print(f"\n📉 DECAY JOB: {decay}")
    
    if 'anomalies' in results:
        anomalies = results['anomalies']
        if isinstance(anomalies, dict) and anomalies.get('status') == 'skipped_dry_run':
            print("\n🔍 ANOMALY DETECTION: ⏭️  SKIPPED (dry run)")
        elif isinstance(anomalies, dict) and anomalies.get('status') != 'error':
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
        if isinstance(meta, dict) and meta.get('status') == 'skipped_dry_run':
            print("\n🧠 META-COGNITION: ⏭️  SKIPPED (dry run)")
        elif isinstance(meta, dict) and meta.get('status') != 'error':
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

    if results.get('backup_path'):
        print(f"\n📦 Maintenance backup: {results['backup_path']}")
    
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
    
    failures = _failed_jobs(results)
    print()
    if failures:
        print(f"❌ Maintenance failed: {', '.join(failures)}")
        raise SystemExit(2)

    print("✅ Maintenance complete!")
    print()
    print("Logs written to: logs/intelligence/intelligence-YYYY-MM-DD.jsonl")
    print("View in Grafana: http://localhost:3000 → Intelligence Dashboard")


if __name__ == "__main__":
    main()
