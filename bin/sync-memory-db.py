#!/usr/bin/env python3
"""
Sync memory databases between cloud and local modes.
Each mode has its own database with mode-appropriate embeddings.
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

def sync_databases(source_mode='cloud', target_mode='local', verbose=True):
    """
    Sync knowledge_base and conversations from source DB to target DB.
    Regenerates embeddings for target mode's embedding model.
    
    Future: Will also sync alerts, reminders, and tasks tables
    (see docs/PROACTIVE_ASSISTANT_SYSTEM.md)
    """
    
    project_root = Path(__file__).parent.parent
    
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
            success BOOLEAN DEFAULT 1
        )
    """)
    
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
    conversations = source_cursor.execute("""
        SELECT timestamp, user_query, jarvis_response, tools_used, 
               session_id, success
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
                    (timestamp, user_query, jarvis_response, tools_used, session_id, success)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (conv['timestamp'], conv['user_query'], conv['jarvis_response'],
                      conv['tools_used'], conv['session_id'], conv['success']))
        except Exception as e:
            if verbose:
                print(f"⚠️  Skipping conversation: {e}")
    
    # Sync alerts (if table exists)
    try:
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
    
    target_conn.commit()
    
    source_conn.close()
    target_conn.close()
    
    if verbose:
        print()
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"✅ Sync Complete!")
        print(f"   Synced: {synced}")
        print(f"   Skipped: {skipped} (already current)")
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
