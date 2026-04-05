#!/usr/bin/env python3
"""
Sync Intelligence Database - Full sync between cloud and local modes.

Syncs ALL intelligence data:
- experiences (raw interaction data)
- insights (learned patterns)
- reflection_queue (pending reflections)

IMPORTANT: Cloud and local use DIFFERENT embedding dimensions (1536 vs 768).
This script copies the TEXT content and REGENERATES embeddings for the target mode.

The learned insights are provider-agnostic - "use crypto_price for price queries" 
applies whether you're using xAI, Anthropic, OpenAI, or Ollama. Only the vector
embeddings need to be regenerated for dimension compatibility.

Usage:
    ./bin/sync-intelligence-db.py cloud     # Sync from local → cloud (regenerate 1536-dim embeddings)
    ./bin/sync-intelligence-db.py local     # Sync from cloud → local (regenerate 768-dim embeddings)
    ./bin/sync-intelligence-db.py --dry-run local  # Preview what would sync
    ./bin/sync-intelligence-db.py --reset cloud    # Reset cloud intelligence DB
"""

import sys
import os
import sqlite3
import pickle
import shutil
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from config_loader import load_config
from embeddings import get_embedding

# ANSI colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
BOLD = '\033[1m'
NC = '\033[0m'


def get_db_paths():
    """Get paths for cloud and local intelligence databases."""
    project_root = Path(__file__).parent.parent
    return {
        'cloud': project_root / 'data' / 'jarvis_intelligence.db',
        'local': project_root / 'data' / 'jarvis_intelligence_local.db'
    }


def backup_db(db_path: Path) -> Path:
    """Create a backup of the database."""
    if not db_path.exists():
        return None
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = db_path.with_suffix(f'.db.backup_{timestamp}')
    shutil.copy2(db_path, backup_path)
    return backup_path


def reset_db(mode: str):
    """Reset (delete) the intelligence database for a mode."""
    paths = get_db_paths()
    db_path = paths[mode]
    
    if db_path.exists():
        # Create backup first
        backup = backup_db(db_path)
        print(f"{YELLOW}Created backup: {backup}{NC}")
        
        # Delete the database
        db_path.unlink()
        print(f"{GREEN}✅ Deleted {db_path}{NC}")
        print(f"   Database will be recreated on next use.")
    else:
        print(f"{YELLOW}Database doesn't exist: {db_path}{NC}")


def sync_intelligence(target_mode: str, dry_run: bool = False):
    """
    Sync ALL intelligence data from source mode to target mode.
    
    Syncs:
    - experiences (with regenerated embeddings)
    - insights (with regenerated embeddings)
    - reflection_queue
    
    Regenerates embeddings using the target mode's embedding model.
    """
    paths = get_db_paths()
    
    # Determine source and target
    if target_mode == 'cloud':
        source_mode = 'local'
        target_dim = 1536
    else:
        source_mode = 'cloud'
        target_dim = 768
    
    source_path = paths[source_mode]
    target_path = paths[target_mode]
    
    print(f"{BOLD}Syncing Intelligence: {source_mode} → {target_mode}{NC}")
    print(f"  Source: {source_path}")
    print(f"  Target: {target_path}")
    print(f"  Target embedding dimensions: {target_dim}")
    print()
    
    # Check source exists
    if not source_path.exists():
        print(f"{RED}❌ Source database doesn't exist: {source_path}{NC}")
        return False
    
    # Load target mode config for embeddings
    load_config(target_mode)
    
    # Connect to source
    source_conn = sqlite3.connect(str(source_path))
    source_conn.row_factory = sqlite3.Row
    source_cursor = source_conn.cursor()
    
    # Count source data
    source_cursor.execute("SELECT COUNT(*) FROM experiences")
    exp_count = source_cursor.fetchone()[0]
    
    source_cursor.execute("SELECT COUNT(*) FROM insights")
    insight_count = source_cursor.fetchone()[0]
    
    source_cursor.execute("SELECT COUNT(*) FROM reflection_queue WHERE processed = 0")
    pending_count = source_cursor.fetchone()[0]
    
    print(f"Source database contains:")
    print(f"  - {exp_count} experiences")
    print(f"  - {insight_count} insights")
    print(f"  - {pending_count} pending reflections")
    print()
    
    if dry_run:
        print(f"{YELLOW}DRY RUN - no changes will be made{NC}")
        source_conn.close()
        return True
    
    # Backup target if exists
    if target_path.exists():
        backup = backup_db(target_path)
        print(f"{YELLOW}Created target backup: {backup}{NC}")
    
    # Initialize target database (this creates tables if needed)
    from intelligence import IntelligenceLayer
    
    # Temporarily set LLM_PROVIDER for correct DB selection
    old_provider = os.environ.get('LLM_PROVIDER')
    os.environ['LLM_PROVIDER'] = 'ollama' if target_mode == 'local' else 'anthropic'
    
    target_intel = IntelligenceLayer()
    target_conn = target_intel.conn
    target_cursor = target_conn.cursor()
    
    # ============================================
    # SYNC EXPERIENCES
    # ============================================
    print(f"{BLUE}Syncing experiences...{NC}")
    target_cursor.execute("DELETE FROM experiences")
    target_conn.commit()
    
    source_cursor.execute("""
        SELECT id, query, context_summary, tools_used, tool_sequence, turns_taken,
               final_tool, outcome_success, user_satisfied, had_to_retry, had_to_clarify,
               error_occurred, raw_data, timestamp
        FROM experiences
    """)
    source_experiences = source_cursor.fetchall()
    
    exp_success = 0
    exp_errors = 0
    
    # Map old IDs to new IDs for reflection_queue
    exp_id_map = {}
    
    for row in source_experiences:
        try:
            query = row['query'] or ''
            context_summary = row['context_summary'] or ''
            
            # Regenerate embeddings
            query_embedding = None
            context_embedding = None
            outcome_embedding = None
            
            if query:
                try:
                    emb = get_embedding(query)
                    query_embedding = pickle.dumps(emb)
                except Exception as e:
                    print(f"{YELLOW}  Warning: Failed to generate query embedding: {e}{NC}")
            
            if context_summary:
                try:
                    emb = get_embedding(context_summary)
                    context_embedding = pickle.dumps(emb)
                except Exception as e:
                    print(f"{YELLOW}  Warning: Failed to generate context embedding: {e}{NC}")
            
            # Generate outcome embedding from a combination of signals
            outcome_text = f"success={row['outcome_success']} satisfied={row['user_satisfied']} tools={row['tools_used']}"
            try:
                emb = get_embedding(outcome_text)
                outcome_embedding = pickle.dumps(emb)
            except Exception as e:
                print(f"{YELLOW}  Warning: Failed to generate outcome embedding: {e}{NC}")
            
            target_cursor.execute("""
                INSERT INTO experiences (
                    query, query_embedding, context_summary, context_embedding,
                    tools_used, tool_sequence, turns_taken, final_tool,
                    outcome_success, user_satisfied, had_to_retry, had_to_clarify,
                    error_occurred, outcome_embedding, raw_data, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                query,
                query_embedding,
                context_summary,
                context_embedding,
                row['tools_used'],
                row['tool_sequence'],
                row['turns_taken'],
                row['final_tool'],
                row['outcome_success'],
                row['user_satisfied'],
                row['had_to_retry'],
                row['had_to_clarify'],
                row['error_occurred'],
                outcome_embedding,
                row['raw_data'],
                row['timestamp']
            ))
            
            new_id = target_cursor.lastrowid
            exp_id_map[row['id']] = new_id
            exp_success += 1
            
        except Exception as e:
            print(f"{RED}  Error copying experience #{row['id']}: {e}{NC}")
            exp_errors += 1
    
    target_conn.commit()
    print(f"  ✅ Copied {exp_success} experiences" + (f" ({exp_errors} errors)" if exp_errors else ""))
    
    # ============================================
    # SYNC INSIGHTS
    # ============================================
    print(f"{BLUE}Syncing insights...{NC}")
    target_cursor.execute("DELETE FROM insights")
    target_conn.commit()
    
    source_cursor.execute("""
        SELECT id, created_at, updated_at, insight_type, description, constraint_type, trigger_concept,
               applies_to_pattern, preferred_tools, avoided_tools, avoided_patterns,
               generalizability, reasoning, confidence, strength, evidence_count,
               times_applied, times_helpful, times_failed, consecutive_failures, last_outcome,
               last_applied
        FROM insights
    """)
    source_insights = source_cursor.fetchall()
    
    insight_success = 0
    insight_errors = 0
    
    for row in source_insights:
        try:
            description = row['description'] or ''
            pattern = row['applies_to_pattern'] or ''
            
            # Regenerate embeddings with target mode's model
            insight_embedding = None
            pattern_embedding = None
            
            if description:
                try:
                    emb = get_embedding(description)
                    insight_embedding = pickle.dumps(emb)
                except Exception as e:
                    print(f"{YELLOW}  Warning: Failed to generate insight embedding: {e}{NC}")
            
            if pattern:
                try:
                    emb = get_embedding(pattern)
                    pattern_embedding = pickle.dumps(emb)
                except Exception as e:
                    print(f"{YELLOW}  Warning: Failed to generate pattern embedding: {e}{NC}")
            
            # Insert into target
            target_cursor.execute("""
                INSERT INTO insights (
                    created_at, updated_at,
                    insight_type, description, insight_embedding, constraint_type, trigger_concept,
                    applies_to_pattern, pattern_embedding, preferred_tools, avoided_tools, avoided_patterns,
                    generalizability, reasoning, confidence, strength, evidence_count,
                    times_applied, times_helpful, times_failed, consecutive_failures, last_outcome,
                    last_applied
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['created_at'],
                row['updated_at'],
                row['insight_type'],
                description,
                insight_embedding,
                row['constraint_type'],
                row['trigger_concept'],
                pattern,
                pattern_embedding,
                row['preferred_tools'],
                row['avoided_tools'],
                row['avoided_patterns'],
                row['generalizability'],
                row['reasoning'],
                row['confidence'],
                row['strength'],
                row['evidence_count'],
                row['times_applied'],
                row['times_helpful'],
                row['times_failed'],
                row['consecutive_failures'],
                row['last_outcome'],
                row['last_applied']
            ))
            insight_success += 1
            
        except Exception as e:
            print(f"{RED}  Error copying insight #{row['id']}: {e}{NC}")
            insight_errors += 1
    
    target_conn.commit()
    print(f"  ✅ Copied {insight_success} insights" + (f" ({insight_errors} errors)" if insight_errors else ""))
    
    # ============================================
    # SYNC REFLECTION QUEUE
    # ============================================
    print(f"{BLUE}Syncing reflection queue...{NC}")
    target_cursor.execute("DELETE FROM reflection_queue")
    target_conn.commit()
    
    source_cursor.execute("""
        SELECT experience_id, priority, processed, queued_at
        FROM reflection_queue
        WHERE processed = 0
    """)
    source_queue = source_cursor.fetchall()
    
    queue_success = 0
    queue_skipped = 0
    
    for row in source_queue:
        old_exp_id = row['experience_id']
        
        # Map to new experience ID
        if old_exp_id in exp_id_map:
            new_exp_id = exp_id_map[old_exp_id]
            target_cursor.execute("""
                INSERT INTO reflection_queue (experience_id, priority, processed, queued_at)
                VALUES (?, ?, ?, ?)
            """, (new_exp_id, row['priority'], row['processed'], row['queued_at']))
            queue_success += 1
        else:
            queue_skipped += 1
    
    target_conn.commit()
    print(f"  ✅ Copied {queue_success} pending reflection entries" + (f" ({queue_skipped} skipped - missing experiences)" if queue_skipped else ""))
    
    # ============================================
    # CLEANUP
    # ============================================
    
    # Restore env
    if old_provider:
        os.environ['LLM_PROVIDER'] = old_provider
    elif 'LLM_PROVIDER' in os.environ:
        del os.environ['LLM_PROVIDER']
    
    source_conn.close()
    target_intel.close()
    
    print()
    print(f"{GREEN}✅ Full sync complete:{NC}")
    print(f"   Experiences: {exp_success}" + (f" ({exp_errors} errors)" if exp_errors else ""))
    print(f"   Insights:    {insight_success}" + (f" ({insight_errors} errors)" if insight_errors else ""))
    print(f"   Pending reflections: {queue_success}" + (f" ({queue_skipped} skipped)" if queue_skipped else ""))
    
    total_errors = exp_errors + insight_errors
    return total_errors == 0


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync intelligence databases between cloud and local modes')
    parser.add_argument('mode', choices=['cloud', 'local'],
                        help='Target mode to sync TO (source is the other mode)')
    parser.add_argument('--reset', action='store_true',
                        help='Reset (delete) the target database instead of syncing')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without making changes')
    
    args = parser.parse_args()
    
    print(f"{BOLD}╔════════════════════════════════════════════════════════════╗{NC}")
    print(f"{BOLD}║  Intelligence Database Sync                                ║{NC}")
    print(f"{BOLD}╚════════════════════════════════════════════════════════════╝{NC}")
    print()
    
    if args.reset:
        reset_db(args.mode)
    else:
        success = sync_intelligence(args.mode, dry_run=args.dry_run)
        if not success:
            sys.exit(1)


if __name__ == '__main__':
    main()
