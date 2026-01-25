#!/usr/bin/env python3
"""
Intelligence Layer Health Check - Validates the self-learning system.

Checks:
- Database exists and is accessible
- Embeddings have correct dimensions for the mode
- Insights are valid and not corrupted
- Reflection queue is being processed
- Learning metrics are healthy

Usage:
    ./bin/check-intelligence-health.py [cloud|local]
    ./bin/check-intelligence-health.py --both
    ./bin/check-intelligence-health.py --json
"""

import sys
import json
import pickle
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from config_loader import load_config, get_config_value

# ANSI color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
BOLD = '\033[1m'
NC = '\033[0m'


def check_intelligence_health(mode='cloud'):
    """
    Check health of the intelligence layer for the given mode.
    
    Args:
        mode: 'cloud' or 'local'
        
    Returns:
        dict with health status and metrics
    """
    load_config(mode)
    
    # Determine expected dimensions and DB path
    if mode == 'local':
        expected_dim = 768  # nomic-embed-text
        db_path = 'data/jarvis_intelligence_local.db'
    else:
        expected_dim = 1536  # OpenAI text-embedding-3-small
        db_path = 'data/jarvis_intelligence.db'
    
    project_root = Path(__file__).parent.parent
    db_file = project_root / db_path
    
    result = {
        'ok': True,
        'mode': mode,
        'db_path': str(db_path),
        'expected_dimensions': expected_dim,
        'issues': [],
        'warnings': [],
        'stats': {}
    }
    
    # Check if database exists
    if not db_file.exists():
        result['warnings'].append(f"Database not found: {db_path} (will be created on first use)")
        result['stats'] = {
            'experiences': 0,
            'insights': 0,
            'pending_reflections': 0
        }
        return result
    
    # Connect to database
    import sqlite3
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get basic stats
    try:
        experiences = cursor.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
        insights = cursor.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
        pending = cursor.execute("SELECT COUNT(*) FROM reflection_queue WHERE processed = 0").fetchone()[0]
        
        result['stats'] = {
            'experiences': experiences,
            'insights': insights,
            'pending_reflections': pending
        }
    except Exception as e:
        result['issues'].append(f"Failed to read stats: {e}")
        result['ok'] = False
        conn.close()
        return result
    
    # Check insight embeddings
    embedding_issues = []
    try:
        cursor.execute("""
            SELECT id, description, insight_embedding, pattern_embedding, confidence
            FROM insights 
            WHERE insight_embedding IS NOT NULL
            LIMIT 50
        """)
        
        for row in cursor.fetchall():
            insight_id = row['id']
            
            # Check insight embedding
            if row['insight_embedding']:
                try:
                    emb = pickle.loads(row['insight_embedding'])
                    actual_dim = len(emb)
                    if actual_dim != expected_dim:
                        embedding_issues.append({
                            'insight_id': insight_id,
                            'field': 'insight_embedding',
                            'expected': expected_dim,
                            'actual': actual_dim
                        })
                except Exception as e:
                    embedding_issues.append({
                        'insight_id': insight_id,
                        'field': 'insight_embedding',
                        'error': str(e)
                    })
            
            # Check pattern embedding
            if row['pattern_embedding']:
                try:
                    emb = pickle.loads(row['pattern_embedding'])
                    actual_dim = len(emb)
                    if actual_dim != expected_dim:
                        embedding_issues.append({
                            'insight_id': insight_id,
                            'field': 'pattern_embedding',
                            'expected': expected_dim,
                            'actual': actual_dim
                        })
                except Exception as e:
                    embedding_issues.append({
                        'insight_id': insight_id,
                        'field': 'pattern_embedding',
                        'error': str(e)
                    })
    except Exception as e:
        result['issues'].append(f"Failed to check embeddings: {e}")
    
    if embedding_issues:
        for issue in embedding_issues[:5]:
            if 'error' in issue:
                msg = f"Embedding issue: #{issue['insight_id']} {issue.get('field', '')} - {issue['error']}"
            else:
                msg = f"Embedding issue: #{issue['insight_id']} {issue.get('field', '')} - {issue.get('actual')}D vs {issue.get('expected')}D"
            result['issues'].append(msg)
        result['ok'] = False
    
    result['embedding_issues_count'] = len(embedding_issues)
    
    # Check experience embeddings
    exp_embedding_issues = []
    try:
        cursor.execute("""
            SELECT id, query, query_embedding
            FROM experiences 
            WHERE query_embedding IS NOT NULL
            LIMIT 50
        """)
        
        for row in cursor.fetchall():
            if row['query_embedding']:
                try:
                    emb = pickle.loads(row['query_embedding'])
                    actual_dim = len(emb)
                    if actual_dim != expected_dim:
                        exp_embedding_issues.append({
                            'exp_id': row['id'],
                            'expected': expected_dim,
                            'actual': actual_dim
                        })
                except Exception as e:
                    exp_embedding_issues.append({
                        'exp_id': row['id'],
                        'error': str(e)
                    })
    except Exception as e:
        result['warnings'].append(f"Failed to check experience embeddings: {e}")
    
    if exp_embedding_issues:
        result['warnings'].append(f"{len(exp_embedding_issues)} experiences have wrong embedding dimensions")
    
    result['exp_embedding_issues_count'] = len(exp_embedding_issues)
    
    # Check for stale reflection queue
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM reflection_queue 
            WHERE processed = 0 
            AND queued_at < datetime('now', '-1 hour')
        """)
        stale_reflections = cursor.fetchone()[0]
        if stale_reflections > 0:
            result['warnings'].append(f"{stale_reflections} reflections pending for > 1 hour")
    except Exception:
        pass  # Ignore if column doesn't exist
    
    # Check insight quality
    try:
        cursor.execute("SELECT AVG(confidence) FROM insights")
        avg_confidence = cursor.fetchone()[0] or 0
        result['stats']['avg_confidence'] = round(avg_confidence, 3)
        
        if insights > 5 and avg_confidence < 0.3:
            result['warnings'].append(f"Low average insight confidence: {avg_confidence:.2f}")
        
        # Check for low-confidence insights that should be pruned
        cursor.execute("SELECT COUNT(*) FROM insights WHERE confidence < 0.2")
        low_conf = cursor.fetchone()[0]
        if low_conf > 0:
            result['warnings'].append(f"{low_conf} insights have very low confidence (<0.2) - consider pruning")
    except Exception:
        pass
    
    # Check constraint types
    try:
        cursor.execute("""
            SELECT 
                constraint_type,
                COUNT(*) as count
            FROM insights 
            GROUP BY constraint_type
        """)
        constraints = {row['constraint_type'] or 'positive': row['count'] for row in cursor.fetchall()}
        result['stats']['positive_constraints'] = constraints.get('positive', 0)
        result['stats']['negative_constraints'] = constraints.get('negative', 0)
    except Exception:
        pass
    
    # Check enabled status
    intelligence_enabled = get_config_value('JARVIS_INTELLIGENCE', 'true').lower() in ('true', '1', 'yes', 'on')
    result['enabled'] = intelligence_enabled
    if not intelligence_enabled:
        result['warnings'].append("Intelligence layer is DISABLED in config")
    
    conn.close()
    
    # Summarize
    if result['issues']:
        result['ok'] = False
    
    return result


def print_health_report(health):
    """Print a formatted health report."""
    mode = health['mode']
    ok = health['ok']
    
    print(f"{BOLD}╔════════════════════════════════════════════════════════════╗{NC}")
    print(f"{BOLD}║  Intelligence Health Check - {mode.upper()} Mode{' ' * (27 - len(mode))}║{NC}")
    print(f"{BOLD}╚════════════════════════════════════════════════════════════╝{NC}")
    print()
    
    # Overall status
    if ok:
        print(f"{GREEN}✅ Intelligence layer is healthy!{NC}")
    else:
        print(f"{RED}❌ Issues detected!{NC}")
    
    # Enabled status
    if health.get('enabled', True):
        print(f"{GREEN}🧠 Intelligence: ENABLED{NC}")
    else:
        print(f"{YELLOW}⚠️  Intelligence: DISABLED{NC}")
    
    print()
    print(f"{BLUE}Database:{NC} {health['db_path']}")
    print(f"{BLUE}Expected Dimensions:{NC} {health['expected_dimensions']}")
    print()
    
    # Stats
    stats = health.get('stats', {})
    print(f"{BOLD}Statistics:{NC}")
    print(f"  Experiences recorded: {stats.get('experiences', 0)}")
    print(f"  Insights learned: {stats.get('insights', 0)}")
    print(f"    ✅ Positive constraints: {stats.get('positive_constraints', 0)}")
    print(f"    ❌ Negative constraints: {stats.get('negative_constraints', 0)}")
    print(f"  Pending reflections: {stats.get('pending_reflections', 0)}")
    if 'avg_confidence' in stats:
        print(f"  Average confidence: {stats['avg_confidence']:.1%}")
    print()
    
    # Embedding health
    print(f"{BOLD}Embedding Health:{NC}")
    insight_issues = health.get('embedding_issues_count', 0)
    exp_issues = health.get('exp_embedding_issues_count', 0)
    
    if insight_issues == 0 and exp_issues == 0:
        print(f"  {GREEN}✓ All embeddings have correct dimensions{NC}")
    else:
        if insight_issues > 0:
            print(f"  {RED}✗ {insight_issues} insight embeddings have wrong dimensions{NC}")
        if exp_issues > 0:
            print(f"  {RED}✗ {exp_issues} experience embeddings have wrong dimensions{NC}")
    print()
    
    # Issues
    if health['issues']:
        print(f"{BOLD}{RED}Issues:{NC}")
        for issue in health['issues']:
            print(f"  {RED}✗{NC} {issue}")
        print()
    
    # Warnings
    if health['warnings']:
        print(f"{BOLD}{YELLOW}Warnings:{NC}")
        for warning in health['warnings']:
            print(f"  {YELLOW}⚠{NC} {warning}")
        print()
    
    # Recommendations
    if not ok or health['warnings']:
        print(f"{BOLD}🔧 Recommendations:{NC}")
        
        if health.get('embedding_issues_count', 0) > 0 or health.get('exp_embedding_issues_count', 0) > 0:
            print(f"  • Regenerate embeddings: ./bin/sync-intelligence-db.py {mode}")
        
        if not health.get('enabled', True):
            print(f"  • Enable intelligence in config/{mode}.env:")
            print(f"    JARVIS_INTELLIGENCE=true")
        
        if stats.get('pending_reflections', 0) > 5:
            print(f"  • Process pending reflections:")
            print(f"    python3 -c \"from lib.intelligence_hooks import trigger_reflection; trigger_reflection(10)\"")
        
        print()
    
    print("━" * 62)


def main():
    """Run health check for specified mode."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Check intelligence layer health')
    parser.add_argument('mode', nargs='?', default='cloud', choices=['cloud', 'local'],
                        help='Mode to check (cloud or local)')
    parser.add_argument('--json', action='store_true', help='Output JSON')
    parser.add_argument('--both', action='store_true', help='Check both modes')
    
    args = parser.parse_args()
    
    if args.both:
        cloud_health = check_intelligence_health('cloud')
        local_health = check_intelligence_health('local')
        
        if args.json:
            print(json.dumps({
                'cloud': cloud_health,
                'local': local_health
            }, indent=2))
        else:
            print_health_report(cloud_health)
            print()
            print_health_report(local_health)
        
        if not cloud_health['ok'] or not local_health['ok']:
            sys.exit(1)
    else:
        health = check_intelligence_health(args.mode)
        
        if args.json:
            print(json.dumps(health, indent=2))
        else:
            print_health_report(health)
        
        if not health['ok']:
            sys.exit(1)


if __name__ == '__main__':
    main()
