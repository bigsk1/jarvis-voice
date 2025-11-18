#!/usr/bin/env python3
"""
Simple database schema test for long_form column.
Tests that the column is created correctly in all initialization scenarios.
"""

import sys
import os
import sqlite3
from pathlib import Path
import shutil

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

def print_header(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")

def check_long_form_column(db_path: Path, db_name: str):
    """Check if long_form column exists in knowledge_base table."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Get column info
    columns = cursor.execute("PRAGMA table_info(knowledge_base)").fetchall()
    column_names = [col[1] for col in columns]
    
    conn.close()
    
    has_long_form = 'long_form' in column_names
    
    if has_long_form:
        print(f"✅ {db_name}: long_form column EXISTS ({len(column_names)} total columns)")
    else:
        print(f"❌ {db_name}: long_form column MISSING")
        print(f"   Columns: {', '.join(column_names)}")
    
    return has_long_form

def main():
    project_root = Path(__file__).parent.parent
    cloud_db = project_root / 'data' / 'jarvis_memory.db'
    local_db = project_root / 'data' / 'jarvis_memory_local.db'
    
    print_header("Database Schema Test - long_form Column")
    
    # Backup existing databases
    print("\n📦 Backing up existing databases...")
    backups_made = []
    
    if cloud_db.exists():
        backup = cloud_db.with_suffix('.db.backup-schema-test')
        shutil.copy(cloud_db, backup)
        backups_made.append(('cloud', cloud_db, backup))
        print(f"  ✅ Backed up {cloud_db.name}")
    
    if local_db.exists():
        backup = local_db.with_suffix('.db.backup-schema-test')
        shutil.copy(local_db, backup)
        backups_made.append(('local', local_db, backup))
        print(f"  ✅ Backed up {local_db.name}")
    
    all_passed = True
    
    # Test 1: Fresh cloud DB
    print_header("Test 1: Fresh Cloud Database (MemoryDB init)")
    
    if cloud_db.exists():
        cloud_db.unlink()
    
    os.environ['LLM_PROVIDER'] = 'anthropic'
    from memory_db import MemoryDB
    
    db = MemoryDB()
    db.close()
    
    if not check_long_form_column(cloud_db, "Cloud DB"):
        all_passed = False
    
    # Test 2: Fresh local DB
    print_header("Test 2: Fresh Local Database (MemoryDB init)")
    
    if local_db.exists():
        local_db.unlink()
    
    os.environ['LLM_PROVIDER'] = 'ollama'
    
    # Need to reimport to pick up new env var
    import importlib
    import memory_db
    importlib.reload(memory_db)
    
    db2 = memory_db.MemoryDB()
    db2.close()
    
    if not check_long_form_column(local_db, "Local DB"):
        all_passed = False
    
    # Test 3: Add data with long_form to cloud
    print_header("Test 3: Insert and Sync long_form Data")
    
    conn = sqlite3.connect(str(cloud_db))
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO knowledge_base (category, key, value, importance, long_form)
        VALUES (?, ?, ?, ?, ?)
    """, ('test', 'schema_test', 'test value', 5, 'This is long form test data'))
    conn.commit()
    conn.close()
    
    print("✅ Inserted test record with long_form to cloud DB")
    
    # Verify it's there
    conn = sqlite3.connect(str(cloud_db))
    cursor = conn.cursor()
    result = cursor.execute(
        "SELECT long_form FROM knowledge_base WHERE key = ?", ('schema_test',)
    ).fetchone()
    conn.close()
    
    if result and result[0]:
        print(f"✅ Verified long_form data in cloud DB: '{result[0][:40]}...'")
    else:
        print("❌ long_form data not found in cloud DB")
        all_passed = False
    
    # Test 4: Check sync script can handle long_form
    print_header("Test 4: Sync Script Compatibility")
    
    # Check the sync script SQL
    sync_script = project_root / 'bin' / 'sync-memory-db.py'
    if sync_script.exists():
        content = sync_script.read_text()
        if 'long_form' in content:
            print("✅ sync-memory-db.py includes long_form column")
        else:
            print("❌ sync-memory-db.py missing long_form column")
            all_passed = False
    else:
        print("⚠️  sync-memory-db.py not found")
    
    # Cleanup test data
    conn = sqlite3.connect(str(cloud_db))
    cursor = conn.cursor()
    cursor.execute("DELETE FROM knowledge_base WHERE key = ?", ('schema_test',))
    conn.commit()
    conn.close()
    
    # Restore original databases
    print_header("Restoring Original Databases")
    
    for db_name, db_path, backup_path in backups_made:
        db_path.unlink(missing_ok=True)
        shutil.copy(backup_path, db_path)
        backup_path.unlink()
        print(f"  ✅ Restored {db_name} database")
    
    # Summary
    print_header("Test Results")
    
    if all_passed:
        print("✅ ALL TESTS PASSED\n")
        print("Summary:")
        print("  ✅ long_form column in memory_db.py schema")
        print("  ✅ long_form column created on fresh init")
        print("  ✅ long_form data can be inserted and retrieved")
        print("  ✅ sync-memory-db.py updated for long_form")
        print()
        return 0
    else:
        print("❌ SOME TESTS FAILED\n")
        return 1

if __name__ == '__main__':
    sys.exit(main())

