#!/usr/bin/env python3
"""
Sync memory databases between cloud and local modes.
Each mode has its own database with mode-appropriate embeddings.

Usage:
    ./bin/sync-memory-db.py --from cloud --to local
        Sync cloud memory into the local DB.
        This is the command to run after a fresh local DB rebuild or sync.
        It will also backfill missing columns like conversations.metadata.

    ./bin/sync-memory-db.py --from local --to cloud
        Sync local memory into the cloud DB.

    ./bin/sync-memory-db.py --from cloud --to local --quiet
        Run the same repair/sync path with minimal output.
"""

import sys
import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from config_loader import load_config
from embeddings import get_embedding


def _table_columns(cursor, table_name):
    """Return column names for a SQLite table."""
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _table_exists(cursor, table_name):
    """Return True when a SQLite table exists."""
    return cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _ensure_column(cursor, table_name, column_name, definition):
    """Add a missing column to an existing SQLite table."""
    if column_name not in _table_columns(cursor, table_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _ensure_user_model_schema(cursor):
    """Create/repair the structured user_model table."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_model (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            value TEXT NOT NULL,
            value_type TEXT DEFAULT 'scalar',
            confidence REAL DEFAULT 0.5,
            evidence TEXT,
            source TEXT,
            metadata TEXT,
            last_reconciled_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    _ensure_column(cursor, "user_model", "value_type", "TEXT DEFAULT 'scalar'")
    _ensure_column(cursor, "user_model", "confidence", "REAL DEFAULT 0.5")
    _ensure_column(cursor, "user_model", "evidence", "TEXT")
    _ensure_column(cursor, "user_model", "source", "TEXT")
    _ensure_column(cursor, "user_model", "metadata", "TEXT")
    _ensure_column(cursor, "user_model", "last_reconciled_at", "TEXT")
    _ensure_column(cursor, "user_model", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "user_model", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_model_key ON user_model(key)")


def sync_databases(source_mode='cloud', target_mode='local', verbose=True, project_root: Path | None = None):
    """
    Sync knowledge_base, conversations, and user_model from source DB to target DB.
    Regenerates embeddings for target mode's embedding model.
    
    Future: Will also sync alerts, reminders, and tasks tables
    (see docs/PROACTIVE_ASSISTANT_SYSTEM.md)
    """
    
    project_root = project_root or Path(__file__).parent.parent
    
    # Database paths
    if source_mode == 'cloud':
        source_db = project_root / 'data' / 'jarvis_memory.db'
    else:
        source_db = project_root / 'data' / 'jarvis_memory_local.db'
    
    if target_mode == 'cloud':
        target_db = project_root / 'data' / 'jarvis_memory.db'
    else:
        target_db = project_root / 'data' / 'jarvis_memory_local.db'
    
    if not source_db.exists():
        print(f"❌ Source database not found: {source_db}")
        return False
    
    if verbose:
        print(f"╔════════════════════════════════════════════════════════════╗")
        print(f"║  Memory Database Sync: {source_mode} → {target_mode}")
        print(f"╚════════════════════════════════════════════════════════════╝")
        print()
        print(f"Source: {source_db}")
        print(f"Target: {target_db}")
        print()
    
    # Load target mode config (for embeddings) BEFORE importing embeddings
    # Temporarily set provider to ensure correct embedding model
    os.environ.get('LLM_PROVIDER')
    if target_mode == 'local':
        os.environ['LLM_PROVIDER'] = 'ollama'
    else:
        os.environ['LLM_PROVIDER'] = 'anthropic'
    
    load_config(target_mode)
    
    # Connect to both databases
    source_conn = sqlite3.connect(str(source_db))
    source_conn.row_factory = sqlite3.Row
    source_cursor = source_conn.cursor()
    
    target_conn = sqlite3.connect(str(target_db))
    target_cursor = target_conn.cursor()
    
    # Ensure target DB has schema
    target_cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT,
            metadata TEXT,
            embedding BLOB,
            long_form TEXT
        )
    """)
    
    target_cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_query TEXT,
            jarvis_response TEXT,
            tools_used TEXT,
            session_id TEXT,
            success BOOLEAN DEFAULT 1,
            metadata TEXT
        )
    """)
    _ensure_column(target_cursor, "conversations", "metadata", "TEXT")
    _ensure_user_model_schema(target_cursor)
    
    # Get all memories from source
    memories = source_cursor.execute("""
        SELECT id, category, key, value, importance, 
               created_at, updated_at, source, metadata, long_form
        FROM knowledge_base
    """).fetchall()
    
    if verbose:
        print(f"Found {len(memories)} memories in source database")
        print()
    
    synced = 0
    skipped = 0
    errors = 0
    
    for memory in memories:
        memory['id']
        category = memory['category']
        key = memory['key']
        value = memory['value']
        importance = memory['importance']
        created_at = memory['created_at']
        updated_at = memory['updated_at']
        source = memory['source']
        metadata = memory['metadata']
        long_form = memory['long_form']
        
        try:
            # Check if already exists in target
            existing = target_cursor.execute(
                "SELECT id, updated_at FROM knowledge_base WHERE key = ? AND category = ?",
                (key, category)
            ).fetchone()
            
            if existing:
                # Update if source is newer
                if updated_at > existing[1]:
                    if verbose:
                        print(f"⟳ Updating: {key[:40]}...")
                    
                    # Generate new embedding for target mode
                    text = f"{key}: {value}"
                    embedding = get_embedding(text)
                    embedding_blob = json.dumps(embedding).encode('utf-8')
                    
                    target_cursor.execute("""
                        UPDATE knowledge_base 
                        SET value = ?, importance = ?, updated_at = ?,
                            source = ?, metadata = ?, embedding = ?, long_form = ?
                        WHERE id = ?
                    """, (value, importance, updated_at, source, metadata, 
                          embedding_blob, long_form, existing[0]))
                    
                    synced += 1
                else:
                    if verbose:
                        print(f"⊝ Skipping: {key[:40]} (already up-to-date)")
                    skipped += 1
            else:
                # Insert new
                if verbose:
                    print(f"+ Inserting: {key[:40]}...")
                
                # Generate embedding for target mode
                text = f"{key}: {value}"
                embedding = get_embedding(text)
                embedding_blob = json.dumps(embedding).encode('utf-8')
                
                target_cursor.execute("""
                    INSERT INTO knowledge_base 
                    (category, key, value, importance, created_at, updated_at,
                     source, metadata, embedding, long_form)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (category, key, value, importance, created_at, updated_at,
                      source, metadata, embedding_blob, long_form))
                
                synced += 1
        
        except Exception as e:
            print(f"❌ Error syncing {key}: {e}")
            errors += 1
    
    # Also sync conversations (no embeddings needed)
    source_conversation_columns = _table_columns(source_cursor, "conversations")
    conversation_metadata_select = (
        "metadata" if "metadata" in source_conversation_columns else "NULL AS metadata"
    )
    conversations = source_cursor.execute(f"""
        SELECT timestamp, user_query, jarvis_response, tools_used, 
               session_id, success, {conversation_metadata_select}
        FROM conversations
        ORDER BY timestamp DESC
        LIMIT 100
    """).fetchall()
    
    if verbose:
        print()
        print(f"Syncing {len(conversations)} recent conversations...")
    
    for conv in conversations:
        try:
            # Check if exists
            existing = target_cursor.execute(
                "SELECT id FROM conversations WHERE timestamp = ? AND user_query = ?",
                (conv['timestamp'], conv['user_query'])
            ).fetchone()
            
            if not existing:
                target_cursor.execute("""
                    INSERT INTO conversations 
                    (timestamp, user_query, jarvis_response, tools_used, session_id, success, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (conv['timestamp'], conv['user_query'], conv['jarvis_response'],
                      conv['tools_used'], conv['session_id'], conv['success'], conv['metadata']))
        except Exception as e:
            if verbose:
                print(f"⚠️  Skipping conversation: {e}")

    # Sync structured user model traits (no embeddings needed)
    user_model_synced = 0
    user_model_skipped = 0
    if _table_exists(source_cursor, "user_model"):
        source_user_columns = _table_columns(source_cursor, "user_model")
        user_select_columns = [
            "key",
            "value",
            "value_type" if "value_type" in source_user_columns else "'scalar' AS value_type",
            "confidence" if "confidence" in source_user_columns else "0.5 AS confidence",
            "evidence" if "evidence" in source_user_columns else "NULL AS evidence",
            "source" if "source" in source_user_columns else "NULL AS source",
            "metadata" if "metadata" in source_user_columns else "NULL AS metadata",
            "last_reconciled_at" if "last_reconciled_at" in source_user_columns else "NULL AS last_reconciled_at",
            "created_at" if "created_at" in source_user_columns else "CURRENT_TIMESTAMP AS created_at",
            "updated_at" if "updated_at" in source_user_columns else "CURRENT_TIMESTAMP AS updated_at",
        ]
        user_traits = source_cursor.execute(f"""
            SELECT {', '.join(user_select_columns)}
            FROM user_model
        """).fetchall()

        if verbose and len(user_traits) > 0:
            print()
            print(f"Syncing {len(user_traits)} user model trait(s)...")

        for trait in user_traits:
            try:
                existing = target_cursor.execute(
                    "SELECT id, updated_at FROM user_model WHERE key = ?",
                    (trait["key"],),
                ).fetchone()

                if existing:
                    if trait["updated_at"] > existing[1]:
                        target_cursor.execute("""
                            UPDATE user_model
                            SET value = ?,
                                value_type = ?,
                                confidence = ?,
                                evidence = ?,
                                source = ?,
                                metadata = ?,
                                last_reconciled_at = ?,
                                created_at = ?,
                                updated_at = ?
                            WHERE id = ?
                        """, (
                            trait["value"],
                            trait["value_type"],
                            trait["confidence"],
                            trait["evidence"],
                            trait["source"],
                            trait["metadata"],
                            trait["last_reconciled_at"],
                            trait["created_at"],
                            trait["updated_at"],
                            existing[0],
                        ))
                        user_model_synced += 1
                    else:
                        user_model_skipped += 1
                else:
                    target_cursor.execute("""
                        INSERT INTO user_model (
                            key, value, value_type, confidence, evidence,
                            source, metadata, last_reconciled_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trait["key"],
                        trait["value"],
                        trait["value_type"],
                        trait["confidence"],
                        trait["evidence"],
                        trait["source"],
                        trait["metadata"],
                        trait["last_reconciled_at"],
                        trait["created_at"],
                        trait["updated_at"],
                    ))
                    user_model_synced += 1
            except Exception as e:
                if verbose:
                    print(f"⚠️  Skipping user_model trait {trait['key']}: {e}")
    
    # Sync alerts (if table exists)
    try:
        target_cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                severity TEXT CHECK(severity IN ('low', 'medium', 'high', 'critical')) DEFAULT 'medium',
                source TEXT NOT NULL,
                status TEXT CHECK(status IN ('pending', 'acknowledged', 'auto_resolved', 'canceled')) DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,
                acknowledged_at TEXT,
                resolved_at TEXT,
                spoken BOOLEAN DEFAULT 0,
                spoken_at TEXT,
                follow_up_count INTEGER DEFAULT 0,
                last_follow_up TEXT,
                auto_resolve_url TEXT,
                auto_resolve_check_interval INTEGER DEFAULT 300,
                last_check_at TEXT,
                metadata TEXT,
                related_intel_file TEXT,
                synced_to_other_db BOOLEAN DEFAULT 0,
                sync_timestamp TEXT
            )
        """)
        alerts = source_cursor.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 100").fetchall()
        if verbose and len(alerts) > 0:
            print()
            print(f"Syncing {len(alerts)} alerts...")
        
        for alert in alerts:
            try:
                existing = target_cursor.execute(
                    "SELECT id FROM alerts WHERE id = ?", (alert['id'],)
                ).fetchone()
                
                if not existing:
                    target_cursor.execute("""
                        INSERT INTO alerts 
                        (id, title, description, severity, source, status, created_at, updated_at,
                         acknowledged_at, resolved_at, spoken, spoken_at, follow_up_count, last_follow_up,
                         auto_resolve_url, auto_resolve_check_interval, last_check_at,
                         metadata, related_intel_file, synced_to_other_db, sync_timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """, (
                        alert['id'], alert['title'], alert['description'], alert['severity'],
                        alert['source'], alert['status'], alert['created_at'], alert['updated_at'],
                        alert['acknowledged_at'], alert['resolved_at'], alert['spoken'], alert['spoken_at'],
                        alert['follow_up_count'], alert['last_follow_up'], alert['auto_resolve_url'],
                        alert['auto_resolve_check_interval'], alert['last_check_at'],
                        alert['metadata'], alert['related_intel_file'],
                        datetime.now().isoformat()
                    ))
            except Exception as e:
                if verbose:
                    print(f"⚠️  Skipping alert: {e}")
    except Exception:
        # alerts table doesn't exist yet
        pass
    
    # Sync reminders (if table exists)
    try:
        target_cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                trigger_time TEXT NOT NULL,
                status TEXT CHECK(status IN ('scheduled', 'triggered', 'acknowledged', 'canceled', 'expired')) DEFAULT 'scheduled',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                triggered_at TEXT,
                acknowledged_at TEXT,
                spoken BOOLEAN DEFAULT 0,
                spoken_at TEXT,
                related_intel_file TEXT,
                callback_url TEXT,
                recurrence_rule TEXT,
                metadata TEXT,
                synced_to_other_db BOOLEAN DEFAULT 0,
                sync_timestamp TEXT
            )
        """)
        reminders = source_cursor.execute("SELECT * FROM reminders ORDER BY trigger_time ASC LIMIT 100").fetchall()
        if verbose and len(reminders) > 0:
            print()
            print(f"Syncing {len(reminders)} reminders...")
        
        for reminder in reminders:
            try:
                existing = target_cursor.execute(
                    "SELECT id FROM reminders WHERE id = ?", (reminder['id'],)
                ).fetchone()
                
                if not existing:
                    target_cursor.execute("""
                        INSERT INTO reminders
                        (id, title, description, trigger_time, status, created_at, triggered_at,
                         acknowledged_at, spoken, spoken_at, related_intel_file, callback_url,
                         recurrence_rule, metadata, synced_to_other_db, sync_timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """, (
                        reminder['id'], reminder['title'], reminder['description'],
                        reminder['trigger_time'], reminder['status'], reminder['created_at'],
                        reminder['triggered_at'], reminder['acknowledged_at'], reminder['spoken'],
                        reminder['spoken_at'], reminder['related_intel_file'], reminder['callback_url'],
                        reminder['recurrence_rule'], reminder['metadata'],
                        datetime.now().isoformat()
                    ))
            except Exception as e:
                if verbose:
                    print(f"⚠️  Skipping reminder: {e}")
    except Exception:
        # reminders table doesn't exist yet
        pass

    # Sync scheduled tasks (if table exists)
    try:
        target_cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                enabled BOOLEAN DEFAULT 1,
                task_type TEXT NOT NULL,
                task_target TEXT,
                task_payload TEXT,
                schedule_type TEXT NOT NULL,
                schedule_expr TEXT NOT NULL,
                timezone TEXT DEFAULT 'America/Los_Angeles',
                mode TEXT DEFAULT 'cloud',
                allow_overlap BOOLEAN DEFAULT 0,
                max_retries INTEGER DEFAULT 1,
                timeout_seconds INTEGER DEFAULT 300,
                last_run_at TEXT,
                next_run_at TEXT,
                last_status TEXT,
                last_error TEXT,
                last_duration_ms REAL,
                last_result_summary TEXT,
                lock_owner TEXT,
                lock_acquired_at TEXT,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        tasks = source_cursor.execute("SELECT * FROM scheduled_tasks ORDER BY created_at DESC LIMIT 200").fetchall()
        if verbose and len(tasks) > 0:
            print()
            print(f"Syncing {len(tasks)} scheduled tasks...")

        for task in tasks:
            existing = target_cursor.execute("SELECT id FROM scheduled_tasks WHERE id = ?", (task['id'],)).fetchone()
            if not existing:
                target_cursor.execute("""
                    INSERT INTO scheduled_tasks (
                        id, name, enabled, task_type, task_target, task_payload,
                        schedule_type, schedule_expr, timezone, mode,
                        allow_overlap, max_retries, timeout_seconds,
                        last_run_at, next_run_at, last_status, last_error,
                        last_duration_ms, last_result_summary,
                        lock_owner, lock_acquired_at, metadata, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, tuple(task))
    except Exception:
        pass

    # Sync scheduled task runs (if table exists)
    try:
        target_cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_task_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                mode TEXT,
                provider TEXT,
                model TEXT,
                workflow_id TEXT,
                tools_used TEXT,
                speech TEXT,
                raw_llm_response TEXT,
                result_data TEXT,
                error TEXT,
                duration_ms REAL,
                completion_guard_applied BOOLEAN DEFAULT 0,
                feedback_collected BOOLEAN DEFAULT 0,
                metadata TEXT
            )
        """)
        runs = source_cursor.execute("SELECT * FROM scheduled_task_runs ORDER BY started_at DESC LIMIT 500").fetchall()
        if verbose and len(runs) > 0:
            print(f"Syncing {len(runs)} scheduled task runs...")

        for run in runs:
            existing = target_cursor.execute("SELECT id FROM scheduled_task_runs WHERE id = ?", (run['id'],)).fetchone()
            if not existing:
                target_cursor.execute("""
                    INSERT INTO scheduled_task_runs (
                        id, task_id, started_at, finished_at, status,
                        mode, provider, model, workflow_id, tools_used,
                        speech, raw_llm_response, result_data, error,
                        duration_ms, completion_guard_applied, feedback_collected, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, tuple(run))
    except Exception:
        pass
    
    target_conn.commit()
    
    source_conn.close()
    target_conn.close()
    
    if verbose:
        print()
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"✅ Sync Complete!")
        print(f"   Synced: {synced}")
        print(f"   Skipped: {skipped} (already current)")
        print(f"   User model synced: {user_model_synced}")
        print(f"   User model skipped: {user_model_skipped} (already current)")
        print(f"   Errors: {errors}")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print()
    
    return True


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync memory databases between modes')
    parser.add_argument('--from', dest='source', choices=['cloud', 'local'], 
                       default='cloud', help='Source mode')
    parser.add_argument('--to', dest='target', choices=['cloud', 'local'],
                       default='local', help='Target mode')
    parser.add_argument('--quiet', action='store_true', 
                       help='Suppress verbose output')
    
    args = parser.parse_args()
    
    if args.source == args.target:
        print("❌ Source and target must be different!")
        sys.exit(1)
    
    success = sync_databases(
        source_mode=args.source,
        target_mode=args.target,
        verbose=not args.quiet
    )
    
    sys.exit(0 if success else 1)
