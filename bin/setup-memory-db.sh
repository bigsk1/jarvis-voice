#!/bin/bash
# Setup/Update Jarvis Memory Database Schema
# This script is idempotent - safe to run multiple times
# Run this after updates or if you delete the database

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DB_PATH="$PROJECT_ROOT/data/jarvis_memory.db"

echo "🗄️  Jarvis Memory Database Setup"
echo "======================================"
echo "Database: $DB_PATH"
echo ""

# Ensure data directory exists
mkdir -p "$PROJECT_ROOT/data"

# Run Python setup script
cd "$PROJECT_ROOT" || exit 1
python3 - <<'PYTHON_SCRIPT'
import sqlite3
import sys
import os

# Add lib to path
sys.path.insert(0, 'lib')

# Use current working directory (PROJECT_ROOT set by shell)
project_root = os.getcwd()
db_path = os.path.join(project_root, 'data', 'jarvis_memory.db')

print(f"📍 Database location: {db_path}")

# Connect to database (creates if doesn't exist)
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check if database is new or existing
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = [row[0] for row in cursor.fetchall()]
    
    if not existing_tables:
        print("✨ Creating new database...")
        
        # Import and initialize through MemoryDB to ensure all tables are created
        from memory_db import MemoryDB
        db = MemoryDB(db_path)
        db.close()
        
        print("✅ Database initialized successfully!")
    else:
        print(f"📊 Found existing database with {len(existing_tables)} tables")
        
        # Run migrations
        migrations_applied = 0
        
        # Migration 1: Add embedding column if missing
        cursor.execute('PRAGMA table_info(knowledge_base)')
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'embedding' not in columns:
            print("🔄 Migration: Adding embedding column...")
            cursor.execute('ALTER TABLE knowledge_base ADD COLUMN embedding BLOB')
            conn.commit()
            migrations_applied += 1
            print("   ✅ Added embedding column")
        
        # Future migrations go here
        # if 'new_column' not in columns:
        #     cursor.execute('ALTER TABLE ... ADD COLUMN ...')
        #     migrations_applied += 1
        
        if migrations_applied > 0:
            print(f"✅ Applied {migrations_applied} migration(s)")
        else:
            print("✅ Database schema is up to date")
    
    # Show database stats
    cursor.execute('SELECT COUNT(*) FROM knowledge_base')
    memory_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM conversations')
    conversation_count = cursor.fetchone()[0]
    
    print("")
    print("📊 Database Statistics:")
    print(f"   Memories: {memory_count}")
    print(f"   Conversations: {conversation_count}")
    
    # Check for memories with embeddings
    cursor.execute('SELECT COUNT(*) FROM knowledge_base WHERE embedding IS NOT NULL')
    embedded_count = cursor.fetchone()[0]
    print(f"   With embeddings: {embedded_count}/{memory_count}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
finally:
    conn.close()

print("")
print("✨ Setup complete!")
PYTHON_SCRIPT

echo ""
echo "🎯 You can now use Jarvis memory system:"
echo "   - Start Jarvis: jarvis or jarvis-local"
echo "   - View memories: ./bin/memory list"
echo "   - Database will auto-create on first use if deleted"

