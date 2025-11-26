#!/usr/bin/env python3
"""
Sync Tools to Vector Database
Iterates through all registered tools (Local + MCP) and updates their embeddings in MemoryDB.
Run this script when adding new tools or changing descriptions.

Handles:
- Adding new tools with embeddings
- Updating existing tool descriptions/schemas
- Disabling tools that are no longer in the registry (removed or set enabled=false)
"""
import sys
import os
import json
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from tool_schema import ToolRegistry
from memory_db import get_memory_db
from config_loader import load_config

def sync_tools(mode='cloud', verbose=True):
    """Sync all tools to the vector database."""
    load_config(mode)
    
    print(f"🔄 Syncing tools for mode: {mode}")
    
    # Initialize registry (discovers all tools)
    project_root = Path(__file__).parent.parent
    skills_dir = str(project_root / "skills")
    mcp_config = str(project_root / "config" / "mcp-servers.json")
    
    print("🔍 Discovering tools...")
    registry = ToolRegistry(skills_dir, mcp_config)
    
    # Get DB connection
    db = get_memory_db()
    
    # Get list of active tool names from registry
    active_tools = set(registry.tools.keys())
    
    count = 0
    total = len(registry.tools)
    
    print(f"📝 Found {total} active tools. Updating embeddings...")
    
    for tool_name, schema in registry.tools.items():
        try:
            # Serialize schema for storage
            # We store the OpenAI format as it's the most universal standard
            schema_json = json.dumps(schema.to_openai_format())
            
            # Check enabled status
            # Local tools have explicit enabled status in json
            # MCP tools are enabled if they were discovered
            enabled = True
            
            # Update DB (generates embedding automatically)
            db.upsert_tool(
                name=tool_name,
                description=schema.description,
                schema_json=schema_json,
                enabled=enabled
            )
            
            if verbose:
                print(f"  ✓ Synced: {tool_name}")
            count += 1
            
        except Exception as e:
            print(f"  ❌ Failed to sync {tool_name}: {e}")
    
    # Disable tools that are no longer in the registry
    # This handles tools that were removed or have enabled=false in their .tool.json
    disabled_count = _disable_stale_tools(db, active_tools, verbose)
    
    print(f"\n✅ Successfully synced {count}/{total} tools to vector DB.")
    if disabled_count > 0:
        print(f"   Disabled {disabled_count} stale/removed tools.")
    print("   Tools are now ready for dynamic retrieval.")


def _disable_stale_tools(db, active_tools: set, verbose: bool) -> int:
    """
    Disable tools in the database that are no longer in the active registry.
    
    This ensures tools with enabled=false in their .tool.json or
    tools that have been deleted don't show up in Tool RAG searches.
    
    Args:
        db: MemoryDB instance
        active_tools: Set of currently active tool names
        verbose: Print status messages
        
    Returns:
        Number of tools disabled
    """
    cursor = db.conn.cursor()
    
    # Get all currently enabled tools from DB
    db_tools = cursor.execute(
        "SELECT name FROM tool_definitions WHERE enabled = 1"
    ).fetchall()
    
    db_tool_names = {row['name'] for row in db_tools}
    
    # Find tools to disable (in DB but not in active registry)
    stale_tools = db_tool_names - active_tools
    
    disabled = 0
    for tool_name in stale_tools:
        cursor.execute(
            "UPDATE tool_definitions SET enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
            (tool_name,)
        )
        if verbose:
            print(f"  ⊝ Disabled stale tool: {tool_name}")
        disabled += 1
    
    db.conn.commit()
    return disabled

def main():
    if len(sys.argv) < 2:
        print("Usage: sync_tools.py <mode>")
        print("  mode: 'cloud' or 'local'")
        sys.exit(1)
        
    mode = sys.argv[1]
    sync_tools(mode)

if __name__ == "__main__":
    main()

