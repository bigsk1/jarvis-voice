#!/usr/bin/env python3
"""
Database migration: Add proactive assistant tables (alerts, reminders, tasks)
Run this once to upgrade existing databases.
"""

import sqlite3
import sys
from pathlib import Path

def migrate_database(db_path: Path):
    """Add proactive assistant tables to database."""
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return False
    
    print(f"📊 Migrating: {db_path.name}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if alerts table already exists
    existing_tables = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    existing_tables = [t[0] for t in existing_tables]
    
    migrations_applied = 0
    
    # Migration 1: alerts table
    if 'alerts' not in existing_tables:
        print("  ✅ Creating alerts table...")
        cursor.execute("""
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                
                -- Core fields
                title TEXT NOT NULL,
                description TEXT,
                severity TEXT CHECK(severity IN ('low', 'medium', 'high', 'critical')) DEFAULT 'medium',
                source TEXT NOT NULL,
                
                -- Status tracking
                status TEXT CHECK(status IN ('pending', 'acknowledged', 'auto_resolved', 'canceled')) DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,
                acknowledged_at TEXT,
                resolved_at TEXT,
                
                -- Notification tracking
                spoken BOOLEAN DEFAULT 0,
                spoken_at TEXT,
                follow_up_count INTEGER DEFAULT 0,
                last_follow_up TEXT,
                
                -- Self-healing
                auto_resolve_url TEXT,
                auto_resolve_check_interval INTEGER DEFAULT 300,
                last_check_at TEXT,
                
                -- Metadata
                metadata TEXT,
                related_intel_file TEXT,
                
                -- Sync tracking
                synced_to_other_db BOOLEAN DEFAULT 0,
                sync_timestamp TEXT
            )
        """)
        
        cursor.execute("CREATE INDEX idx_alerts_status ON alerts(status)")
        cursor.execute("CREATE INDEX idx_alerts_severity ON alerts(severity)")
        cursor.execute("CREATE INDEX idx_alerts_source ON alerts(source)")
        
        migrations_applied += 1
    else:
        print("  ⏭️  alerts table already exists")
    
    # Migration 2: reminders table (future)
    if 'reminders' not in existing_tables:
        print("  ✅ Creating reminders table...")
        cursor.execute("""
            CREATE TABLE reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                
                -- Core fields
                title TEXT NOT NULL,
                description TEXT,
                trigger_time TEXT NOT NULL,
                
                -- Status tracking
                status TEXT CHECK(status IN ('scheduled', 'triggered', 'acknowledged', 'canceled', 'expired')) DEFAULT 'scheduled',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                triggered_at TEXT,
                acknowledged_at TEXT,
                
                -- Notification tracking
                spoken BOOLEAN DEFAULT 0,
                spoken_at TEXT,
                
                -- Integration
                related_intel_file TEXT,
                callback_url TEXT,
                recurrence_rule TEXT,
                
                -- Metadata
                metadata TEXT,
                
                -- Sync tracking
                synced_to_other_db BOOLEAN DEFAULT 0,
                sync_timestamp TEXT
            )
        """)
        
        cursor.execute("CREATE INDEX idx_reminders_trigger ON reminders(trigger_time)")
        cursor.execute("CREATE INDEX idx_reminders_status ON reminders(status)")
        
        migrations_applied += 1
    else:
        print("  ⏭️  reminders table already exists")
    
    # Migration 3: long_form column for knowledge_base
    kb_columns = cursor.execute("PRAGMA table_info(knowledge_base)").fetchall()
    kb_column_names = [col[1] for col in kb_columns]
    
    if 'long_form' not in kb_column_names:
        print("  ✅ Adding long_form column to knowledge_base...")
        cursor.execute("ALTER TABLE knowledge_base ADD COLUMN long_form TEXT")
        migrations_applied += 1
    else:
        print("  ⏭️  long_form column already exists")
    
    conn.commit()
    conn.close()
    
    return migrations_applied

def main():
    project_root = Path(__file__).parent.parent
    
    cloud_db = project_root / 'data' / 'jarvis_memory.db'
    local_db = project_root / 'data' / 'jarvis_memory_local.db'
    
    print("╔════════════════════════════════════════════════════════════╗")
    print("║  Jarvis Proactive Assistant - Database Migration          ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print()
    
    total_migrations = 0
    
    # Migrate cloud DB
    if cloud_db.exists():
        migrations = migrate_database(cloud_db)
        if migrations:
            total_migrations += migrations
            print(f"  ✅ Applied {migrations} migration(s) to cloud DB")
        else:
            print(f"  ℹ️  Cloud DB already up to date")
    else:
        print(f"  ⚠️  Cloud DB not found (will be created on first use)")
    
    print()
    
    # Migrate local DB
    if local_db.exists():
        migrations = migrate_database(local_db)
        if migrations:
            total_migrations += migrations
            print(f"  ✅ Applied {migrations} migration(s) to local DB")
        else:
            print(f"  ℹ️  Local DB already up to date")
    else:
        print(f"  ⚠️  Local DB not found (will be created on first use)")
    
    print()
    print("=" * 60)
    if total_migrations > 0:
        print(f"✅ Migration complete! Applied {total_migrations} total changes.")
    else:
        print("✅ Databases are up to date!")
    print()
    print("New features enabled:")
    print("  • Alerts system (webhooks, health checks)")
    print("  • Reminders (time-based notifications)")
    print("  • Long-form memory (detailed context storage)")
    print()
    print("Next steps:")
    print("  1. Start API server: ./bin/jarvis-api")
    print("  2. See docs/PROACTIVE_ASSISTANT_SYSTEM.md for usage")

if __name__ == '__main__':
    main()

