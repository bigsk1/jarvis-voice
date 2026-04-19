#!/usr/bin/env python3
"""
Sync Tools to Vector Database
Iterates through all registered tools (Local + MCP) and updates their embeddings in MemoryDB.
Run this script when adding new tools or changing descriptions.

Handles:
- Adding new tools with embeddings
- Updating existing tool descriptions/schemas
- Disabling tools that are no longer in the registry (removed or set enabled=false)
- Skipping unchanged tools via embedding_input_hash (unless --force)

Usage:
    source "$HOME/jarvis-venv/bin/activate"

    ./bin/sync_tools.py cloud
        Update data/jarvis_memory.db tool_definitions (OpenAI-class embeddings for cloud mode).

    ./bin/sync_tools.py local
        Update data/jarvis_memory_local.db tool_definitions (Ollama embeddings for local mode).

    ./bin/sync_tools.py cloud --force
    ./bin/sync_tools.py local --force
        Regenerate embeddings for every tool (ignore content hash). Use after switching embedding
        model/dimensions or when debugging Tool RAG.

Profile note: tools excluded by JARVIS_TOOL_PROFILE are not in the registry, so they never
appear as "○ Unchanged" in the sync loop; they are disabled in the DB afterward if still enabled.

See also: docs/SYNC_ARCHITECTURE.md, docs/DUAL_DATABASE_SYSTEM.md (tools are not copied by sync-memory-db).
"""
import sys
import os
import json
from pathlib import Path

# Add lib to path early so the venv guard can use shared path helpers while
# still running before dependency-sensitive Tool RAG imports.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from paths import get_user_home


def _ensure_jarvis_venv() -> None:
    """
    Refuse to run outside the Jarvis virtual environment.

    Tool embeddings are dependency-sensitive: running this script with system
    Python can create hash-matched fallback embeddings that future syncs skip.
    Fail early so a bad interpreter cannot poison Tool RAG state.
    """
    expected_venv = Path(
        os.environ.get("JARVIS_VENV", str(get_user_home() / "jarvis-venv"))
    ).expanduser().resolve()

    active_venv = os.environ.get("VIRTUAL_ENV")
    executable_path = Path(sys.executable).expanduser().resolve()
    prefix_path = Path(sys.prefix).expanduser().resolve()

    in_expected_venv = prefix_path == expected_venv or executable_path.is_relative_to(expected_venv)

    if in_expected_venv:
        return

    print("❌ Refusing to sync Tool RAG outside the Jarvis virtual environment.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Why: running sync_tools.py with system Python can generate fallback", file=sys.stderr)
    print("embeddings, then embedding_input_hash can make later syncs skip the bad row.", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"Expected venv: {expected_venv}", file=sys.stderr)
    print(f"Active VIRTUAL_ENV: {active_venv or '(not set)'}", file=sys.stderr)
    print(f"Python executable: {sys.executable}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Run:", file=sys.stderr)
    print('  source "$HOME/jarvis-venv/bin/activate"', file=sys.stderr)
    print('  # or, if JARVIS_VENV is customized: source "$JARVIS_VENV/bin/activate"', file=sys.stderr)
    print("  ./bin/sync_tools.py cloud   # or local", file=sys.stderr)
    sys.exit(2)


_ensure_jarvis_venv()

from tool_schema import ToolRegistry
from memory_db import get_memory_db
from config_loader import load_config

def sync_tools(mode='cloud', verbose=True, force_reembed: bool = False):
    """Sync all tools to the vector database."""
    load_config(mode)
    
    print(f"🔄 Syncing tools for mode: {mode}" + (" (force re-embed all)" if force_reembed else ""))
    
    # Initialize registry (discovers all tools)
    project_root = Path(__file__).parent.parent
    skills_dir = str(project_root / "skills")
    mcp_config = str(project_root / "config" / "mcp-servers.json")
    
    print("🔍 Discovering tools...")
    registry = ToolRegistry(skills_dir, mcp_config)
    
    # Get DB connection
    db = get_memory_db()
    
    # Load blocked tools from config (comma-separated list)
    # Example: BLOCKED_TOOLS="mcp_blinko_webSearch,mcp_blinko_webExtra"
    from config_loader import get_config_value
    blocked_tools_str = get_config_value('BLOCKED_TOOLS', '')
    blocked_tools = set(t.strip() for t in blocked_tools_str.split(',') if t.strip())
    
    if blocked_tools:
        print(f"🚫 Blocked tools (from BLOCKED_TOOLS config): {len(blocked_tools)}")
        if verbose:
            for t in sorted(blocked_tools):
                print(f"     - {t}")
    
    # Get list of active tool names from registry (excluding blocked)
    active_tools = set(registry.tools.keys()) - blocked_tools
    
    count = 0
    skipped = 0
    skipped_hash = 0
    total = len(registry.tools)
    syncing = total - len(blocked_tools)
    
    print(f"📝 Found {total} tools, syncing {syncing} (blocked: {len(blocked_tools)})...")
    if verbose:
        print(
            "   ℹ️  '○ Unchanged' / '✓ Synced' apply only to tools in the registry above. "
            "Tools skipped by JARVIS_TOOL_PROFILE or disabled in *.tool.json are not listed here; "
            "their DB rows are turned off in the step after this loop if they were still enabled."
        )

    for tool_name, schema in registry.tools.items():
        # Skip blocked tools
        if tool_name in blocked_tools:
            if verbose:
                print(f"  ⊘ Skipped (blocked): {tool_name}")
            skipped += 1
            continue
            
        try:
            # Serialize schema for storage
            # We store the OpenAI format as it's the most universal standard
            schema_json = json.dumps(schema.to_openai_format())
            
            # Check enabled status
            # Local tools have explicit enabled status in json
            # MCP tools are enabled if they were discovered
            enabled = True
            
            # Update DB (embedding skipped when content hash unchanged)
            result = db.upsert_tool(
                name=tool_name,
                description=schema.description,
                schema_json=schema_json,
                enabled=enabled,
                force_reembed=force_reembed,
            )
            if result == "skipped":
                skipped_hash += 1
                if verbose:
                    print(f"  ○ Unchanged: {tool_name}")
            elif verbose:
                print(f"  ✓ Synced: {tool_name}")
            count += 1
            
        except Exception as e:
            print(f"  ❌ Failed to sync {tool_name}: {e}")

    # Preview DB rows that will be disabled (explains why profile-disabled tools never show as "Unchanged")
    if verbose:
        cur = db.conn.cursor()
        db_enabled_rows = cur.execute(
            "SELECT name FROM tool_definitions WHERE enabled = 1"
        ).fetchall()
        db_enabled_names = {row["name"] for row in db_enabled_rows}
        stale_preview = sorted(db_enabled_names - active_tools)
        if stale_preview:
            print(
                f"\n📌 Disabling {len(stale_preview)} tool(s) in DB (were enabled, not in current registry): "
                f"{', '.join(stale_preview)}"
            )
        else:
            print(
                "\n📌 No DB rows to disable (no enabled tools in DB are missing from the current registry)."
            )

    # Disable tools that are no longer in the registry
    # This handles tools that were removed or have enabled=false in their .tool.json
    disabled_count = _disable_stale_tools(db, active_tools, verbose)

    print(f"\n✅ Processed {count}/{syncing} tools to vector DB.")
    if skipped_hash > 0 and not force_reembed:
        print(f"   Skipped embedding (unchanged hash): {skipped_hash}")
    if skipped > 0:
        print(f"   Skipped {skipped} blocked tools (configure via BLOCKED_TOOLS in .env).")
    if disabled_count > 0:
        print(f"   Disabled {disabled_count} stale/removed tools in DB.")
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
        print("Usage: sync_tools.py <mode> [--force]")
        print("  mode: 'cloud' or 'local'")
        print("  --force: regenerate embeddings for every tool (ignore content hash)")
        sys.exit(1)

    args = [a for a in sys.argv[1:] if a != "--force"]
    force_reembed = "--force" in sys.argv[1:]
    if not args:
        print("Usage: sync_tools.py <mode> [--force]")
        sys.exit(1)
    mode = args[0]
    if mode not in ("cloud", "local"):
        print("mode must be 'cloud' or 'local'")
        sys.exit(1)
    sync_tools(mode, force_reembed=force_reembed)

if __name__ == "__main__":
    main()
