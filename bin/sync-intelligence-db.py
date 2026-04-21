#!/usr/bin/env python3
"""
Sync Intelligence Database - merge or replace between cloud and local modes.

Syncs ALL intelligence data:
- experiences (raw interaction data)
- insights (learned patterns)
- insight_evidence (audit trail for insights)
- reflection_queue (pending reflections)

IMPORTANT: Cloud and local use DIFFERENT embedding dimensions (1536 vs 768).
This script copies the TEXT content and REGENERATES embeddings for the target mode.

The learned insights are provider-agnostic - "use crypto_price for price queries" 
applies whether you're using xAI, Anthropic, OpenAI, or Ollama. Only the vector
embeddings need to be regenerated for dimension compatibility.

Usage:
    ./bin/sync-intelligence-db.py cloud     # Merge local → cloud (regenerate 1536-dim embeddings)
    ./bin/sync-intelligence-db.py local     # Merge cloud → local (regenerate 768-dim embeddings)
    ./bin/sync-intelligence-db.py --dry-run local  # Preview what would sync
    ./bin/sync-intelligence-db.py --replace local  # Replace local with cloud mirror
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


def table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    """Return True when a table exists in the connected SQLite DB."""
    return cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    """Return existing column names for a table."""
    if not table_exists(cursor, table_name):
        return set()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def select_with_optional_columns(
    cursor: sqlite3.Cursor,
    table_name: str,
    columns: list[str],
    where_sql: str = "",
) -> list[sqlite3.Row]:
    """
    Select a stable set of columns from old/new DBs.

    Missing columns are returned as NULL aliases so the sync script can move data
    across schema versions without hand-editing the user's DB first.
    """
    existing = table_columns(cursor, table_name)
    select_parts = [
        col if col in existing else f"NULL AS {col}"
        for col in columns
    ]
    cursor.execute(f"SELECT {', '.join(select_parts)} FROM {table_name} {where_sql}")
    return cursor.fetchall()


def find_existing_experience(cursor: sqlite3.Cursor, row: sqlite3.Row) -> int | None:
    """Find an already-synced experience by stable content fields."""
    existing = cursor.execute("""
        SELECT id FROM experiences
        WHERE timestamp = ?
          AND query = ?
          AND COALESCE(tool_sequence, '') = COALESCE(?, '')
          AND COALESCE(tools_used, '') = COALESCE(?, '')
          AND COALESCE(final_tool, '') = COALESCE(?, '')
        LIMIT 1
    """, (
        row['timestamp'],
        row['query'],
        row['tool_sequence'],
        row['tools_used'],
        row['final_tool'],
    )).fetchone()
    return existing['id'] if existing else None


def find_existing_insight(cursor: sqlite3.Cursor, row: sqlite3.Row) -> int | None:
    """Find an already-synced insight by its learned rule identity."""
    existing = cursor.execute("""
        SELECT id FROM insights
        WHERE description = ?
          AND COALESCE(applies_to_pattern, '') = COALESCE(?, '')
          AND COALESCE(constraint_type, '') = COALESCE(?, '')
          AND COALESCE(preferred_tools, '') = COALESCE(?, '')
          AND COALESCE(avoided_tools, '') = COALESCE(?, '')
          AND COALESCE(preferred_tool_sequence, '') = COALESCE(?, '')
        LIMIT 1
    """, (
        row['description'],
        row['applies_to_pattern'],
        row['constraint_type'],
        row['preferred_tools'],
        row['avoided_tools'],
        row['preferred_tool_sequence'],
    )).fetchone()
    return existing['id'] if existing else None


def find_existing_evidence(
    cursor: sqlite3.Cursor,
    row: sqlite3.Row,
    insight_id: int,
    experience_id: int | None,
) -> int | None:
    """Find an already-synced insight evidence row."""
    existing = cursor.execute("""
        SELECT id FROM insight_evidence
        WHERE insight_id = ?
          AND COALESCE(experience_id, -1) = COALESCE(?, -1)
          AND COALESCE(web_conversation_id, '') = COALESCE(?, '')
          AND COALESCE(query, '') = COALESCE(?, '')
          AND COALESCE(tool_sequence, '') = COALESCE(?, '')
          AND COALESCE(preferred_tool, '') = COALESCE(?, '')
          AND COALESCE(avoided_tool, '') = COALESCE(?, '')
          AND COALESCE(action, '') = COALESCE(?, '')
          AND COALESCE(created_at, '') = COALESCE(?, '')
        LIMIT 1
    """, (
        insight_id,
        experience_id,
        row['web_conversation_id'],
        row['query'],
        row['tool_sequence'],
        row['preferred_tool'],
        row['avoided_tool'],
        row['action'],
        row['created_at'],
    )).fetchone()
    return existing['id'] if existing else None


def sync_intelligence(target_mode: str, dry_run: bool = False, replace: bool = False):
    """
    Sync intelligence data from source mode to target mode.

    Syncs:
    - experiences (with regenerated embeddings)
    - insights (with regenerated embeddings)
    - insight_evidence (with remapped experience/insight IDs)
    - reflection_queue

    Default behavior is additive merge: copy missing source rows while preserving
    target-only learning. Use replace=True for the old full-mirror behavior.

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

    sync_mode = "replace mirror" if replace else "additive merge"
    print(f"{BOLD}Syncing Intelligence: {source_mode} → {target_mode} ({sync_mode}){NC}")
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

    if table_exists(source_cursor, "insight_evidence"):
        source_cursor.execute("SELECT COUNT(*) FROM insight_evidence")
        evidence_count = source_cursor.fetchone()[0]
    else:
        evidence_count = 0

    source_cursor.execute("SELECT COUNT(*) FROM reflection_queue WHERE processed = 0")
    pending_count = source_cursor.fetchone()[0]

    print(f"Source database contains:")
    print(f"  - {exp_count} experiences")
    print(f"  - {insight_count} insights")
    print(f"  - {evidence_count} insight evidence rows")
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

    target_intel = IntelligenceLayer(str(target_path))
    target_conn = target_intel.conn
    target_cursor = target_conn.cursor()

    # ============================================
    # SYNC EXPERIENCES
    # ============================================
    print(f"{BLUE}Syncing experiences...{NC}")
    if replace:
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
    exp_reused = 0
    exp_errors = 0

    # Map old IDs to new IDs for reflection_queue
    exp_id_map = {}

    for row in source_experiences:
        try:
            if not replace:
                existing_id = find_existing_experience(target_cursor, row)
                if existing_id:
                    exp_id_map[row['id']] = existing_id
                    exp_reused += 1
                    continue

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
    print(
        f"  ✅ Copied {exp_success} experiences"
        + (f", reused {exp_reused}" if exp_reused else "")
        + (f" ({exp_errors} errors)" if exp_errors else "")
    )

    # ============================================
    # SYNC INSIGHTS
    # ============================================
    print(f"{BLUE}Syncing insights...{NC}")
    if replace:
        if table_exists(target_cursor, "insight_evidence"):
            target_cursor.execute("DELETE FROM insight_evidence")
        target_cursor.execute("DELETE FROM insights")
        target_conn.commit()

    insight_columns = [
        "id",
        "created_at",
        "updated_at",
        "insight_type",
        "description",
        "constraint_type",
        "trigger_concept",
        "trigger_signals",
        "primary_intent",
        "applies_to_pattern",
        "preferred_tools",
        "preferred_tool_sequence",
        "supporting_tools",
        "sequence_required",
        "avoided_tools",
        "avoided_patterns",
        "generalizability",
        "reasoning",
        "reflection_provider",
        "reflection_model",
        "reflection_input_tokens",
        "reflection_output_tokens",
        "reflection_total_tokens",
        "reflection_cost_usd",
        "confidence",
        "strength",
        "evidence_count",
        "times_applied",
        "times_helpful",
        "times_failed",
        "consecutive_failures",
        "last_outcome",
        "last_applied",
        "source_experience_id",
        "source_web_conversation_id",
        "source_query",
        "source_tool_sequence",
        "source_reflection_json",
    ]
    source_insights = select_with_optional_columns(source_cursor, "insights", insight_columns)

    insight_success = 0
    insight_reused = 0
    insight_errors = 0
    insight_id_map = {}

    for row in source_insights:
        try:
            if not replace:
                existing_id = find_existing_insight(target_cursor, row)
                if existing_id:
                    insight_id_map[row['id']] = existing_id
                    insight_reused += 1
                    continue

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
                    trigger_signals, primary_intent,
                    applies_to_pattern, pattern_embedding,
                    preferred_tools, preferred_tool_sequence, supporting_tools, sequence_required,
                    avoided_tools, avoided_patterns,
                    generalizability, reasoning,
                    reflection_provider, reflection_model,
                    reflection_input_tokens, reflection_output_tokens,
                    reflection_total_tokens, reflection_cost_usd,
                    confidence, strength, evidence_count,
                    times_applied, times_helpful, times_failed, consecutive_failures, last_outcome,
                    last_applied,
                    source_experience_id, source_web_conversation_id,
                    source_query, source_tool_sequence, source_reflection_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['created_at'],
                row['updated_at'],
                row['insight_type'],
                description,
                insight_embedding,
                row['constraint_type'],
                row['trigger_concept'],
                row['trigger_signals'],
                row['primary_intent'],
                pattern,
                pattern_embedding,
                row['preferred_tools'],
                row['preferred_tool_sequence'],
                row['supporting_tools'],
                row['sequence_required'],
                row['avoided_tools'],
                row['avoided_patterns'],
                row['generalizability'],
                row['reasoning'],
                row['reflection_provider'],
                row['reflection_model'],
                row['reflection_input_tokens'],
                row['reflection_output_tokens'],
                row['reflection_total_tokens'],
                row['reflection_cost_usd'],
                row['confidence'],
                row['strength'],
                row['evidence_count'],
                row['times_applied'],
                row['times_helpful'],
                row['times_failed'],
                row['consecutive_failures'],
                row['last_outcome'],
                row['last_applied'],
                exp_id_map.get(row['source_experience_id']) if row['source_experience_id'] else None,
                row['source_web_conversation_id'],
                row['source_query'],
                row['source_tool_sequence'],
                row['source_reflection_json'],
            ))
            insight_id_map[row['id']] = target_cursor.lastrowid
            insight_success += 1

        except Exception as e:
            print(f"{RED}  Error copying insight #{row['id']}: {e}{NC}")
            insight_errors += 1

    target_conn.commit()
    print(
        f"  ✅ Copied {insight_success} insights"
        + (f", reused {insight_reused}" if insight_reused else "")
        + (f" ({insight_errors} errors)" if insight_errors else "")
    )

    # ============================================
    # SYNC INSIGHT EVIDENCE
    # ============================================
    print(f"{BLUE}Syncing insight evidence...{NC}")
    evidence_success = 0
    evidence_skipped = 0
    evidence_errors = 0

    if table_exists(source_cursor, "insight_evidence") and table_exists(target_cursor, "insight_evidence"):
        evidence_columns = [
            "id",
            "insight_id",
            "experience_id",
            "web_conversation_id",
            "query",
            "tool_sequence",
            "preferred_tool",
            "avoided_tool",
            "preferred_tool_sequence",
            "supporting_tools",
            "reflection_json",
            "confidence",
            "confidence_delta",
            "action",
            "created_at",
        ]
        source_evidence = select_with_optional_columns(
            source_cursor,
            "insight_evidence",
            evidence_columns,
        )

        for row in source_evidence:
            old_insight_id = row['insight_id']
            if old_insight_id not in insight_id_map:
                evidence_skipped += 1
                continue

            old_exp_id = row['experience_id']
            new_exp_id = exp_id_map.get(old_exp_id) if old_exp_id else None
            try:
                if not replace and find_existing_evidence(
                    target_cursor,
                    row,
                    insight_id_map[old_insight_id],
                    new_exp_id,
                ):
                    evidence_skipped += 1
                    continue

                target_cursor.execute("""
                    INSERT INTO insight_evidence (
                        insight_id, experience_id, web_conversation_id, query,
                        tool_sequence, preferred_tool, avoided_tool,
                        preferred_tool_sequence, supporting_tools, reflection_json,
                        confidence, confidence_delta, action, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    insight_id_map[old_insight_id],
                    new_exp_id,
                    row['web_conversation_id'],
                    row['query'],
                    row['tool_sequence'],
                    row['preferred_tool'],
                    row['avoided_tool'],
                    row['preferred_tool_sequence'],
                    row['supporting_tools'],
                    row['reflection_json'],
                    row['confidence'],
                    row['confidence_delta'],
                    row['action'],
                    row['created_at'],
                ))
                evidence_success += 1
            except Exception as e:
                print(f"{RED}  Error copying insight evidence #{row['id']}: {e}{NC}")
                evidence_errors += 1

        target_conn.commit()
        print(
            f"  ✅ Copied {evidence_success} insight evidence rows"
            + (f" ({evidence_skipped} skipped)" if evidence_skipped else "")
            + (f" ({evidence_errors} errors)" if evidence_errors else "")
        )
    else:
        print(f"  {YELLOW}No insight_evidence table found to sync{NC}")

    # ============================================
    # SYNC REFLECTION QUEUE
    # ============================================
    print(f"{BLUE}Syncing reflection queue...{NC}")
    if replace:
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
            if not replace:
                existing_queue = target_cursor.execute("""
                    SELECT 1 FROM reflection_queue
                    WHERE experience_id = ?
                      AND processed = ?
                    LIMIT 1
                """, (new_exp_id, row['processed'])).fetchone()
                if existing_queue:
                    queue_skipped += 1
                    continue
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
    print(f"{GREEN}✅ Sync complete:{NC}")
    print(f"   Experiences: {exp_success}" + (f" copied, {exp_reused} reused" if exp_reused else "") + (f" ({exp_errors} errors)" if exp_errors else ""))
    print(f"   Insights:    {insight_success}" + (f" copied, {insight_reused} reused" if insight_reused else "") + (f" ({insight_errors} errors)" if insight_errors else ""))
    print(f"   Insight evidence: {evidence_success}" + (f" ({evidence_skipped} skipped)" if evidence_skipped else "") + (f" ({evidence_errors} errors)" if evidence_errors else ""))
    print(f"   Pending reflections: {queue_success}" + (f" ({queue_skipped} skipped)" if queue_skipped else ""))

    total_errors = exp_errors + insight_errors + evidence_errors
    return total_errors == 0


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Sync intelligence databases between cloud and local modes')
    parser.add_argument('mode', choices=['cloud', 'local'],
                        help='Target mode to sync TO (source is the other mode)')
    parser.add_argument('--reset', action='store_true',
                        help='Reset (delete) the target database instead of syncing')
    parser.add_argument('--replace', action='store_true',
                        help='Replace target with a source mirror instead of additive merge')
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
        success = sync_intelligence(args.mode, dry_run=args.dry_run, replace=args.replace)
        if not success:
            sys.exit(1)


if __name__ == '__main__':
    main()
