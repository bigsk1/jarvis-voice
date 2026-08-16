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

    ./bin/sync-tools.py cloud
        Update data/jarvis_memory.db tool_definitions (Jarvis Embedding, 768D).

    ./bin/sync-tools.py local
        Update data/jarvis_memory_local.db tool_definitions (Jarvis Embedding, 768D).

    ./bin/sync-tools.py cloud --force
    ./bin/sync-tools.py local --force
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

    Tool discovery depends on the full Jarvis runtime environment. Fail early
    so a partial interpreter cannot silently omit registry or MCP integrations.
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
    print("Why: a partial interpreter can omit tool or MCP integrations and leave", file=sys.stderr)
    print("the Tool RAG index incomplete.", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"Expected venv: {expected_venv}", file=sys.stderr)
    print(f"Active VIRTUAL_ENV: {active_venv or '(not set)'}", file=sys.stderr)
    print(f"Python executable: {sys.executable}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Run:", file=sys.stderr)
    print('  source "$HOME/jarvis-venv/bin/activate"', file=sys.stderr)
    print('  # or, if JARVIS_VENV is customized: source "$JARVIS_VENV/bin/activate"', file=sys.stderr)
    print("  ./bin/sync-tools.py cloud   # or local", file=sys.stderr)
    sys.exit(2)


_ensure_jarvis_venv()

from tool_schema import ToolRegistry
from memory_db import get_memory_db
from config_loader import get_float, get_int, load_config
from embeddings import PersistentEmbeddingError
from tool_sync_status import (
    count_usable_tool_embeddings,
    record_tool_sync_failure,
    record_tool_sync_success,
)

MCP_UNAVAILABLE_EXIT_CODE = 3
EMBEDDING_UNAVAILABLE_EXIT_CODE = 4
TOOL_SYNC_INCOMPLETE_EXIT_CODE = 5


class ToolSyncEmbeddingError(RuntimeError):
    """Raised when Tool RAG cannot safely persist a provider embedding."""


class ToolSyncIncompleteError(RuntimeError):
    """Raised when one or more tool definitions could not be synchronized."""


def _record_sync_outcome(mode: str, *, exit_code: int = 0, reason: str = "") -> None:
    """Persist startup-visible sync state without masking the sync result."""
    try:
        usable_count = count_usable_tool_embeddings(mode)
        if exit_code:
            record_tool_sync_failure(
                mode,
                exit_code=exit_code,
                reason=reason,
                usable_tool_count=usable_count,
            )
        else:
            record_tool_sync_success(mode, usable_tool_count=usable_count)
    except Exception as exc:
        print(f"⚠️ Failed to persist Tool RAG sync status: {exc}", file=sys.stderr)


def sync_tools(mode='cloud', verbose=True, force_reembed: bool = False) -> dict[str, str]:
    """Sync all tools to the vector database."""
    load_config(mode)
    
    print(f"🔄 Syncing tools for mode: {mode}" + (" (force re-embed all)" if force_reembed else ""))
    
    # Initialize registry (discovers all tools)
    project_root = Path(__file__).parent.parent
    skills_dir = str(project_root / "skills")
    mcp_config = str(project_root / "config" / "mcp-servers.json")
    
    print("🔍 Discovering tools...")
    registry = ToolRegistry(skills_dir, mcp_config)

    if registry.mcp_unavailable and verbose:
        print(
            f"⚠️ MCP servers skipped ({len(registry.mcp_unavailable)}): "
            + ", ".join(sorted(registry.mcp_unavailable.keys()))
        )
        print("   Pull missing Docker images or set enabled=false in config/mcp-servers.json.")

    # Tools excluded because required configuration is missing in this mode.
    # Their DB rows are disabled by the stale-tools pass below; adding the
    # missing key(s) and re-running sync re-enables them automatically.
    if registry.unavailable_tools:
        from tool_availability import describe_missing
        print(
            f"🔒 Unavailable tools ({len(registry.unavailable_tools)}) — "
            f"missing configuration in {mode} mode:"
        )
        for name in sorted(registry.unavailable_tools):
            print(f"     - {name}: {describe_missing(registry.unavailable_tools[name])}")
    
    # Get DB connection
    db = get_memory_db()
    
    # Load blocked tools from config (comma-separated list)
    # Example: BLOCKED_TOOLS="mcp_playwright_browser_navigate,mcp_playwright_browser_snapshot"
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
    embedding_max_attempts = max(1, get_int("PERSISTENT_EMBEDDING_MAX_ATTEMPTS", 3))
    embedding_retry_delay = max(0.0, get_float("PERSISTENT_EMBEDDING_RETRY_DELAY_SECONDS", 1.0))
    sync_errors = []
    
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
                embedding_max_attempts=embedding_max_attempts,
                embedding_retry_delay_seconds=embedding_retry_delay,
            )
            if result == "skipped":
                skipped_hash += 1
                if verbose:
                    print(f"  ○ Unchanged: {tool_name}")
            elif verbose:
                print(f"  ✓ Synced: {tool_name}")
            count += 1
            
        except PersistentEmbeddingError as e:
            registry.cleanup()
            raise ToolSyncEmbeddingError(
                f"Tool embedding sync stopped at '{tool_name}'; existing vectors and hashes were preserved: {e}"
            ) from e
        except Exception as e:
            print(f"  ❌ Failed to sync {tool_name}: {e}")
            sync_errors.append((tool_name, str(e)))

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

    if sync_errors:
        registry.cleanup()
        failed_names = ", ".join(name for name, _error in sync_errors)
        raise ToolSyncIncompleteError(
            f"Tool sync was incomplete for {len(sync_errors)} tool(s): {failed_names}"
        )

    print(f"\n✅ Processed {count}/{syncing} tools to vector DB.")
    if skipped_hash > 0 and not force_reembed:
        print(f"   Skipped embedding (unchanged hash): {skipped_hash}")
    if skipped > 0:
        print(f"   Skipped {skipped} blocked tools (configure via BLOCKED_TOOLS in .env).")
    if disabled_count > 0:
        print(f"   Disabled {disabled_count} stale/removed tools in DB.")
    print("   Tools are now ready for dynamic retrieval.")

    unavailable_mcp = dict(registry.mcp_unavailable)
    registry.cleanup()
    return unavailable_mcp


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
        print("Usage: sync-tools.py <mode> [--force]")
        print("  mode: 'cloud' or 'local'")
        print("  --force: regenerate embeddings for every tool (ignore content hash)")
        sys.exit(1)

    args = [a for a in sys.argv[1:] if a != "--force"]
    force_reembed = "--force" in sys.argv[1:]
    if not args:
        print("Usage: sync-tools.py <mode> [--force]")
        sys.exit(1)
    mode = args[0]
    if mode not in ("cloud", "local"):
        print("mode must be 'cloud' or 'local'")
        sys.exit(1)
    try:
        unavailable_mcp = sync_tools(mode, force_reembed=force_reembed)
    except ToolSyncEmbeddingError as exc:
        _record_sync_outcome(
            mode,
            exit_code=EMBEDDING_UNAVAILABLE_EXIT_CODE,
            reason=str(exc),
        )
        print(f"❌ {exc}", file=sys.stderr)
        print(
            "Tool RAG sync is incomplete. No fallback embedding was stored; retry after the embedding provider recovers.",
            file=sys.stderr,
        )
        sys.exit(EMBEDDING_UNAVAILABLE_EXIT_CODE)
    except ToolSyncIncompleteError as exc:
        _record_sync_outcome(
            mode,
            exit_code=TOOL_SYNC_INCOMPLETE_EXIT_CODE,
            reason=str(exc),
        )
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(TOOL_SYNC_INCOMPLETE_EXIT_CODE)
    except Exception as exc:
        _record_sync_outcome(mode, exit_code=1, reason=f"Unexpected Tool RAG sync failure: {exc}")
        raise
    if unavailable_mcp and os.environ.get("JARVIS_MCP_SYNC_STRICT", "0") == "1":
        _record_sync_outcome(
            mode,
            exit_code=MCP_UNAVAILABLE_EXIT_CODE,
            reason="MCP tool discovery was incomplete",
        )
        print(
            "⚠️ MCP tool sync was incomplete; Docker init will retry on the next start.",
            file=sys.stderr,
        )
        sys.exit(MCP_UNAVAILABLE_EXIT_CODE)
    _record_sync_outcome(mode)

if __name__ == "__main__":
    main()
