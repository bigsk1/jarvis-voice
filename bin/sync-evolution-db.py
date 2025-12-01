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


def sync_prompt_versions(source_db: str, target_db: str):
    """Sync prompt_versions table from source to target."""
    source_conn = sqlite3.connect(source_db)
    source_conn.row_factory = sqlite3.Row
    target_conn = sqlite3.connect(target_db)
    
    source_cursor = source_conn.cursor()
    target_cursor = target_conn.cursor()
    
    # Get all components and their active versions from source
    source_cursor.execute("""
        SELECT component, content, version, created_by, change_summary
        FROM prompt_versions 
        WHERE is_active = TRUE
    """)
    source_versions = source_cursor.fetchall()
    
    synced = 0
    skipped = 0
    
    for row in source_versions:
        component = row['component']
        content = row['content']
        version = row['version']
        
        # Check if target has this component
        target_cursor.execute("""
            SELECT version, content FROM prompt_versions 
            WHERE component = ? AND is_active = TRUE
        """, (component,))
        target_row = target_cursor.fetchone()
        
        if target_row:
            target_version = target_row[0]
            target_content = target_row[1]
            
            # Only sync if source is newer or content different
            if version > target_version or content != target_content:
                # Deactivate current version
                target_cursor.execute("""
                    UPDATE prompt_versions SET is_active = FALSE 
                    WHERE component = ? AND is_active = TRUE
                """, (component,))
                
                # Insert new version
                target_cursor.execute("""
                    INSERT INTO prompt_versions 
                    (component, component_type, version, content, created_by, 
                     change_summary, is_active)
                    VALUES (?, 'tool_description', ?, ?, 'sync_from_cloud', ?, TRUE)
                """, (component, version, content, row['change_summary']))
                
                print(f"  ✅ Synced {component}: v{target_version} → v{version}")
                synced += 1
            else:
                print(f"  ⏭️  Skipped {component}: already at v{version}")
                skipped += 1
        else:
            # New component - insert
            target_cursor.execute("""
                INSERT INTO prompt_versions 
                (component, component_type, version, content, created_by, 
                 change_summary, is_active)
                VALUES (?, 'tool_description', ?, ?, 'sync_from_cloud', ?, TRUE)
            """, (component, version, content, row['change_summary']))
            
            print(f"  ➕ Added {component}: v{version}")
            synced += 1
    
    target_conn.commit()
    source_conn.close()
    target_conn.close()
    
    return synced, skipped


def update_tool_files_from_db(mode: str):
    """Update tool JSON files with active versions from DB."""
    db_path = get_db_path(mode)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
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
    print(f"Syncing prompt_versions: {source_mode} → {args.target}")
    print(f"{'='*60}\n")
    
    print(f"Source: {source_db}")
    print(f"Target: {target_db}\n")
    
    synced, skipped = sync_prompt_versions(source_db, target_db)
    
    print(f"\n📊 Summary: {synced} synced, {skipped} skipped")
    
    if args.update_files:
        print(f"\n📝 Updating tool files for {args.target} mode...")
        updated = update_tool_files_from_db(args.target)
        print(f"   Updated {updated} tool files")
    
    print(f"\n✅ Sync complete!")
    print(f"\n💡 Tip: Run ./bin/sync_tools.py {args.target} to update embeddings")


if __name__ == "__main__":
    main()

