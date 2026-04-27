#!/usr/bin/env python3
"""
Sync prompt evolution data between cloud and local databases.

This allows you to:
1. Use stronger cloud models to evolve prompts
2. Sync those improvements to local mode
3. Keep both databases in sync

Usage:
    ./bin/sync-evolution-db.py cloud   # Sync from local → cloud
    ./bin/sync-evolution-db.py local   # Sync from cloud → local
    ./bin/sync-evolution-db.py local --dry-run
    ./bin/sync-evolution-db.py local --update-files
"""

import os
import sys
import sqlite3
import json
from datetime import datetime

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

def get_db_path(mode: str) -> str:
    """Get database path for a mode."""
    base_path = os.path.join(os.path.dirname(__file__), '..', 'data')
    if mode == 'local':
        return os.path.join(base_path, 'jarvis_memory_local.db')
    return os.path.join(base_path, 'jarvis_memory.db')


def _table_exists(cursor, table_name: str) -> bool:
    """Return True when a SQLite table exists."""
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def ensure_prompt_evolution_schema(cursor):
    """Create prompt evolution tables if they do not exist."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompt_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component TEXT NOT NULL,
            component_type TEXT NOT NULL,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            parent_version_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT 'human',
            times_used INTEGER DEFAULT 0,
            total_rating_sum REAL DEFAULT 0,
            is_active BOOLEAN DEFAULT FALSE,
            is_archived BOOLEAN DEFAULT FALSE,
            trigger_feedback_ids TEXT,
            change_summary TEXT,
            FOREIGN KEY (parent_version_id) REFERENCES prompt_versions(id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_prompt_active
        ON prompt_versions(component, is_active)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_prompt_component
        ON prompt_versions(component, version DESC)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompt_evolution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            action TEXT NOT NULL,
            component TEXT NOT NULL,
            from_version_id INTEGER,
            to_version_id INTEGER,
            trigger_type TEXT,
            trigger_details TEXT,
            status TEXT,
            notes TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompt_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            component TEXT NOT NULL,
            version_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            reason TEXT,
            FOREIGN KEY (version_id) REFERENCES prompt_versions(id)
        )
    """)


def sync_prompt_versions(source_db: str, target_db: str, dry_run: bool = False, force: bool = False):
    """Sync prompt_versions table from source to target."""
    source_conn = sqlite3.connect(source_db)
    source_conn.row_factory = sqlite3.Row
    target_conn = sqlite3.connect(target_db)
    target_conn.row_factory = sqlite3.Row
    
    source_cursor = source_conn.cursor()
    target_cursor = target_conn.cursor()

    ensure_prompt_evolution_schema(target_cursor)

    if not _table_exists(source_cursor, "prompt_versions"):
        if not dry_run:
            target_conn.commit()
        source_conn.close()
        target_conn.close()
        print("⚠️  Source database has no prompt_versions table yet. Nothing to sync.")
        return 0, 0, 0
    
    # Get all components and their active versions from source
    source_cursor.execute("""
        SELECT component, content, version, created_by, change_summary, created_at
        FROM prompt_versions 
        WHERE is_active = TRUE
    """)
    source_versions = source_cursor.fetchall()
    
    synced = 0
    skipped = 0
    conflicts = 0
    
    for row in source_versions:
        component = row['component']
        content = row['content']
        version = row['version']
        source_time = row['created_at'] or ''
        
        # Check if target has this component
        target_cursor.execute("""
            SELECT version, content, created_by, created_at FROM prompt_versions 
            WHERE component = ? AND is_active = TRUE
        """, (component,))
        target_row = target_cursor.fetchone()
        
        if target_row:
            target_version = target_row['version']
            target_content = target_row['content']
            target_created_by = target_row['created_by'] or ''
            target_time = target_row['created_at'] or ''
            
            # Check for conflict: both evolved independently
            is_conflict = (
                target_version >= version and 
                target_content != content and
                'sync' not in target_created_by.lower()  # Not from a previous sync
            )
            
            if is_conflict and not force:
                print(f"  ⚠️  CONFLICT {component}:")
                print(f"      Source: v{version} ({source_time})")
                print(f"      Target: v{target_version} ({target_time}, by {target_created_by})")
                print(f"      Use --force to override target")
                conflicts += 1
                continue
            
            # Only sync if source is newer or content different
            if version > target_version or content != target_content or force:
                if dry_run:
                    print(f"  🔍 Would sync {component}: v{target_version} → v{version}")
                    synced += 1
                else:
                    # Deactivate current version
                    target_cursor.execute("""
                        UPDATE prompt_versions SET is_active = FALSE 
                        WHERE component = ? AND is_active = TRUE
                    """, (component,))
                    
                    # Insert new version
                    target_cursor.execute("""
                        INSERT INTO prompt_versions 
                        (component, component_type, version, content, created_by, 
                         change_summary, is_active, created_at)
                        VALUES (?, 'tool_description', ?, ?, 'sync_from_cloud', ?, TRUE, ?)
                    """, (component, version, content, row['change_summary'], datetime.now().isoformat()))
                    
                    print(f"  ✅ Synced {component}: v{target_version} → v{version}")
                    synced += 1
            else:
                print(f"  ⏭️  Skipped {component}: already at v{version}")
                skipped += 1
        else:
            # New component - insert
            if dry_run:
                print(f"  🔍 Would add {component}: v{version}")
                synced += 1
            else:
                target_cursor.execute("""
                    INSERT INTO prompt_versions 
                    (component, component_type, version, content, created_by, 
                     change_summary, is_active, created_at)
                    VALUES (?, 'tool_description', ?, ?, 'sync_from_cloud', ?, TRUE, ?)
                """, (component, version, content, row['change_summary'], datetime.now().isoformat()))
                
                print(f"  ➕ Added {component}: v{version}")
                synced += 1
    
    if not dry_run:
        target_conn.commit()
    source_conn.close()
    target_conn.close()
    
    return synced, skipped, conflicts


def update_tool_files_from_db(mode: str):
    """Update tool JSON files with active versions from DB."""
    db_path = get_db_path(mode)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if not _table_exists(cursor, "prompt_versions"):
        conn.close()
        print("  ⚠️  No prompt_versions table found, skipping tool file updates")
        return 0
    
    skills_dir = os.path.join(os.path.dirname(__file__), '..', 'skills')
    
    cursor.execute("""
        SELECT component, content FROM prompt_versions 
        WHERE is_active = TRUE AND component LIKE 'tool:%'
    """)
    
    updated = 0
    for row in cursor.fetchall():
        tool_name = row['component'].replace('tool:', '')
        content = row['content']
        
        # Check for tool in skills/ or skills/auto-tools/
        for subdir in ['', 'auto-tools']:
            tool_path = os.path.join(skills_dir, subdir, f'{tool_name}.tool.json')
            if os.path.exists(tool_path):
                try:
                    with open(tool_path, 'r') as f:
                        data = json.load(f)
                    
                    if data.get('description') != content:
                        data['description'] = content
                        with open(tool_path, 'w') as f:
                            json.dump(data, f, indent=2)
                        print(f"  📝 Updated {tool_name}.tool.json")
                        updated += 1
                except Exception as e:
                    print(f"  ⚠️  Error updating {tool_name}: {e}")
                break
    
    conn.close()
    return updated


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Sync evolution data between databases')
    parser.add_argument('target', choices=['cloud', 'local'],
                       help='Target database to sync TO (syncs FROM the other)')
    parser.add_argument('--update-files', action='store_true',
                       help='Also update tool JSON files after sync')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview changes without applying them')
    parser.add_argument('--force', action='store_true',
                       help='Force sync even when conflicts detected')
    args = parser.parse_args()
    
    if args.target == 'cloud':
        source_mode = 'local'
        source_db = get_db_path('local')
        target_db = get_db_path('cloud')
    else:
        source_mode = 'cloud'
        source_db = get_db_path('cloud')
        target_db = get_db_path('local')
    
    print(f"\n{'='*60}")
    if args.dry_run:
        print(f"🔍 DRY RUN - Syncing prompt_versions: {source_mode} → {args.target}")
    else:
        print(f"Syncing prompt_versions: {source_mode} → {args.target}")
    print(f"{'='*60}\n")
    
    print(f"Source: {source_db}")
    print(f"Target: {target_db}\n")
    
    synced, skipped, conflicts = sync_prompt_versions(
        source_db, target_db, 
        dry_run=args.dry_run,
        force=args.force
    )
    
    print(f"\n📊 Summary: {synced} synced, {skipped} skipped, {conflicts} conflicts")
    
    if conflicts > 0 and not args.force:
        print(f"\n⚠️  {conflicts} conflict(s) detected!")
        print(f"   Run with --force to override, or resolve manually")
    
    if args.update_files and not args.dry_run:
        print(f"\n📝 Updating tool files for {args.target} mode...")
        updated = update_tool_files_from_db(args.target)
        print(f"   Updated {updated} tool files")
    
    if args.dry_run:
        print(f"\n🔍 Dry run complete - no changes made")
    else:
        print(f"\n✅ Sync complete!")
        print(f"\n💡 Tip: Run ./bin/sync-tools.py {args.target} to update embeddings")


if __name__ == "__main__":
    main()
