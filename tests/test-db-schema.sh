#!/bin/bash
# Test database schema initialization in various scenarios
# Ensures long_form column is always created properly

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Database Schema Test - long_form Column                  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Backup existing databases
echo "📦 Backing up existing databases..."
if [ -f "data/jarvis_memory.db" ]; then
    cp "data/jarvis_memory.db" "data/jarvis_memory.db.backup-test"
    echo "  ✅ Backed up cloud DB"
fi

if [ -f "data/jarvis_memory_local.db" ]; then
    cp "data/jarvis_memory_local.db" "data/jarvis_memory_local.db.backup-test"
    echo "  ✅ Backed up local DB"
fi

echo ""

# Test 1: Fresh database via orchestrator
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 1: Fresh cloud DB via orchestrator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

rm -f "data/jarvis_memory.db"
rm -f "data/jarvis_memory_local.db"

echo "Running: ./orchestrator/orchestrator_v2.py cloud 'hello'"
./orchestrator/orchestrator_v2.py cloud "hello" > /dev/null 2>&1

# Sync tool definitions for Tool RAG
./bin/sync_tools.py cloud > /dev/null 2>&1

echo "Checking schema..."
COLUMNS=$(sqlite3 data/jarvis_memory.db "PRAGMA table_info(knowledge_base);" | cut -d'|' -f2)

if echo "$COLUMNS" | grep -q "long_form"; then
    echo "✅ PASS: long_form column exists in cloud DB after orchestrator init"
else
    echo "❌ FAIL: long_form column missing in cloud DB after orchestrator init"
    echo "Columns found: $COLUMNS"
    exit 1
fi

echo ""

# Test 2: Fresh database via API server
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 2: Fresh local DB via API server"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

rm -f "data/jarvis_memory_local.db"

# Import MemoryDB in local mode
python3 << 'EOF'
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / 'lib'))

# Set to local mode
os.environ['LLM_PROVIDER'] = 'ollama'

from memory_db import MemoryDB

# Initialize DB
db = MemoryDB()
db.close()

print("✅ MemoryDB initialized in local mode")
EOF

echo "Checking schema..."
COLUMNS=$(sqlite3 data/jarvis_memory_local.db "PRAGMA table_info(knowledge_base);" | cut -d'|' -f2)

if echo "$COLUMNS" | grep -q "long_form"; then
    echo "✅ PASS: long_form column exists in local DB after MemoryDB init"
else
    echo "❌ FAIL: long_form column missing in local DB after MemoryDB init"
    echo "Columns found: $COLUMNS"
    exit 1
fi

echo ""

# Test 3: Sync between databases
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 3: Sync long_form column between databases"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Add a memory with long_form to cloud DB
sqlite3 data/jarvis_memory.db << 'EOF'
INSERT INTO knowledge_base (category, key, value, importance, long_form)
VALUES ('test', 'test_key', 'test_value', 5, 'This is a long form explanation of the test data.');
EOF

echo "✅ Added test memory with long_form to cloud DB"

# Sync to local DB
echo "Running sync: cloud → local"
./bin/sync-memory-db.py --from cloud --to local --quiet

# Check if long_form was synced
LONG_FORM=$(sqlite3 data/jarvis_memory_local.db "SELECT long_form FROM knowledge_base WHERE key='test_key';" 2>&1)

if echo "$LONG_FORM" | grep -q "long form explanation"; then
    echo "✅ PASS: long_form data synced successfully"
else
    echo "❌ FAIL: long_form data not synced"
    echo "Found: $LONG_FORM"
    exit 1
fi

echo ""

# Test 4: Check both databases have same schema
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 4: Schema consistency check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

CLOUD_COLS=$(sqlite3 data/jarvis_memory.db "PRAGMA table_info(knowledge_base);" | wc -l)
LOCAL_COLS=$(sqlite3 data/jarvis_memory_local.db "PRAGMA table_info(knowledge_base);" | wc -l)

if [ "$CLOUD_COLS" -eq "$LOCAL_COLS" ]; then
    echo "✅ PASS: Both databases have same number of columns ($CLOUD_COLS)"
else
    echo "❌ FAIL: Column count mismatch (cloud: $CLOUD_COLS, local: $LOCAL_COLS)"
    exit 1
fi

# Cleanup test data
sqlite3 data/jarvis_memory.db "DELETE FROM knowledge_base WHERE key='test_key';"
sqlite3 data/jarvis_memory_local.db "DELETE FROM knowledge_base WHERE key='test_key';"

echo ""

# Restore original databases
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔄 Restoring original databases..."

rm -f "data/jarvis_memory.db"
rm -f "data/jarvis_memory_local.db"

if [ -f "data/jarvis_memory.db.backup-test" ]; then
    mv "data/jarvis_memory.db.backup-test" "data/jarvis_memory.db"
    echo "  ✅ Restored cloud DB"
fi

if [ -f "data/jarvis_memory_local.db.backup-test" ]; then
    mv "data/jarvis_memory_local.db.backup-test" "data/jarvis_memory_local.db"
    echo "  ✅ Restored local DB"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  ✅ ALL TESTS PASSED                                       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Summary:"
echo "  ✅ long_form column created on fresh init (orchestrator)"
echo "  ✅ long_form column created on fresh init (API/MemoryDB)"
echo "  ✅ long_form column synced between databases"
echo "  ✅ Schema consistency maintained"
echo ""

