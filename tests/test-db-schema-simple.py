#!/usr/bin/env python3
"""
Simple database schema tests for MemoryDB: knowledge_base.long_form and
tool_definitions.embedding_input_hash on fresh init (cloud + local).
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

def print_header(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")

def _tool_definitions_column_names(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(tool_definitions)").fetchall()]
    finally:
        conn.close()


def _table_names(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


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

    print_header("Database Schema Test - MemoryDB (long_form + tool_definitions)")
    from memory_db import MemoryDB

    all_passed = True
    with tempfile.TemporaryDirectory(prefix="jarvis-schema-test-") as tmp:
        temp_root = Path(tmp)
        cloud_db = temp_root / 'jarvis_memory.db'
        local_db = temp_root / 'jarvis_memory_local.db'

        # Both mode databases now share one schema and embedding contract. Use
        # explicit isolated paths instead of deleting/restoring operator data.
        print_header("Test 1: Fresh Cloud Database (MemoryDB init)")
        db = MemoryDB(str(cloud_db))
        db.close()
        assert "embedding_input_hash" in _tool_definitions_column_names(cloud_db)
        assert "user_model" in _table_names(cloud_db)
        assert "tool_definitions_fts" in _table_names(cloud_db)
        if not check_long_form_column(cloud_db, "Cloud DB"):
            all_passed = False

        print_header("Test 2: Fresh Local Database (MemoryDB init)")
        db2 = MemoryDB(str(local_db))
        db2.close()
        assert "embedding_input_hash" in _tool_definitions_column_names(local_db)
        assert "user_model" in _table_names(local_db)
        assert "tool_definitions_fts" in _table_names(local_db)
        if not check_long_form_column(local_db, "Local DB"):
            all_passed = False

        print_header("Test 3: Insert and Sync long_form Data")
        conn = sqlite3.connect(str(cloud_db))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO knowledge_base (category, key, value, importance, long_form)
            VALUES (?, ?, ?, ?, ?)
        """, ('test', 'schema_test', 'test value', 5, 'This is long form test data'))
        conn.commit()
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
        if 'long_form' in content and 'user_model' in content:
            print("✅ sync-memory-db.py includes long_form column and user_model table")
        else:
            print("❌ sync-memory-db.py missing long_form column or user_model table")
            all_passed = False
    else:
        print("⚠️  sync-memory-db.py not found")
    
    # Summary
    print_header("Test Results")
    
    if all_passed:
        print("✅ ALL TESTS PASSED\n")
        print("Summary:")
        print("  ✅ long_form column in memory_db.py schema")
        print("  ✅ long_form column created on fresh init")
        print("  ✅ tool_definitions.embedding_input_hash on fresh cloud/local init")
        print("  ✅ tool_definitions_fts on fresh cloud/local init")
        print("  ✅ user_model table on fresh cloud/local init")
        print("  ✅ long_form data can be inserted and retrieved")
        print("  ✅ sync-memory-db.py updated for long_form and user_model")
        print()
        return 0
    else:
        print("❌ SOME TESTS FAILED\n")
        return 1

if __name__ == '__main__':
    sys.exit(main())
