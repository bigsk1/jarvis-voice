#!/bin/bash
# Migration: Remove unused database tables (tool_patterns, preferences)
#
# WHAT THIS DOES:
# - Drops 'tool_patterns' table (never used, 0 rows after 300+ conversations)
# - Drops 'preferences' table (superseded by knowledge_base.category='preference')
# - Creates backup before migration
#
# WHY:
# - These tables were part of original design but never implemented
# - Removing them simplifies schema and reduces confusion
# - knowledge_base table handles all memory needs
#
# SAFETY:
# - Creates backup of database before making changes
# - Can be rolled back by restoring from backup
# - No data loss (tables are empty anyway)

set -e

cd "$(dirname "$0")/.."

DB_PATH="data/jarvis_memory.db"
BACKUP_PATH="data/jarvis_memory.backup-$(date +%Y%m%d-%H%M%S).db"

echo "🗄️  Jarvis Database Migration: Remove Zombie Tables"
echo ""
echo "This will remove unused tables:"
echo "  - tool_patterns (learning system never implemented)"
echo "  - preferences (superseded by knowledge_base)"
echo ""

# Check if database exists
if [ ! -f "$DB_PATH" ]; then
    echo "❌ Database not found at: $DB_PATH"
    exit 1
fi

# Show current table status
echo "📊 Current table status:"
echo ""
echo "tool_patterns rows:"
sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM tool_patterns;"
echo ""
echo "preferences rows:"
sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM preferences;"
echo ""

# Confirm
read -p "⚠️  Create backup and proceed with migration? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "❌ Migration cancelled"
    exit 0
fi

# Create backup
echo ""
echo "💾 Creating backup..."
cp "$DB_PATH" "$BACKUP_PATH"
echo "✅ Backup created: $BACKUP_PATH"

# Drop tables
echo ""
echo "🗑️  Dropping unused tables..."

sqlite3 "$DB_PATH" <<EOF
DROP TABLE IF EXISTS tool_patterns;
DROP TABLE IF EXISTS preferences;
VACUUM;
EOF

echo "✅ Tables removed and database vacuumed"

# Show new schema
echo ""
echo "📋 Remaining tables:"
sqlite3 "$DB_PATH" ".tables"

echo ""
echo "✅ Migration complete!"
echo ""
echo "To rollback:"
echo "  cp $BACKUP_PATH $DB_PATH"

