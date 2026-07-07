#!/usr/bin/env python3
"""
Embedding Health Check - Validates that embeddings in the database
match the expected dimensions for the current mode.

This prevents silent failures in semantic search caused by:
- Wrong embedding model used during ingestion
- Database synced without regenerating embeddings
- Config changes that affect embedding provider

Expected dimensions:
- Cloud mode (OpenAI): 1536 dimensions
- Local mode (nomic-embed-text): 768 dimensions
"""

import sys
import json
import pickle
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from config_loader import config_scope, get_config_value
from memory_db import MemoryDB
from embeddings import get_effective_embedding_provider, get_persistable_embedding

# ANSI color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
BOLD = '\033[1m'
NC = '\033[0m'  # No Color


def _effective_embedding_backend() -> str:
    """Match the runtime embedding resolver exactly."""
    resolved = get_effective_embedding_provider()
    return "ollama" if resolved == "ollama" else "openai"


def check_embedding_dimensions(mode='cloud', _scoped=False):
    """
    Check if embeddings in the database match expected dimensions for the mode.
    
    Args:
        mode: 'cloud' or 'local'
        
    Returns:
        dict with health status
    """
    if not _scoped:
        with config_scope(mode):
            return check_embedding_dimensions(mode, _scoped=True)
    
    # Determine expected dimensions
    if mode == 'local':
        expected_dim = 768  # nomic-embed-text
        db_path = 'data/jarvis_memory_local.db'
    else:
        expected_dim = 1536  # OpenAI text-embedding-3-small
        db_path = 'data/jarvis_memory.db'
    
    project_root = Path(__file__).parent.parent
    db_file = project_root / db_path
    
    if not db_file.exists():
        return {
            'ok': True,
            'warning': f'Database not found: {db_path} (will be created on first use)',
            'mode': mode
        }
    
    # Connect to database
    db = MemoryDB(str(db_file))
    cursor = db.conn.cursor()
    
    # Check knowledge_base embeddings
    memories_with_embeddings = cursor.execute(
        "SELECT id, key, embedding FROM knowledge_base WHERE embedding IS NOT NULL LIMIT 100"
    ).fetchall()
    
    # Check tool_definitions embeddings
    tools_with_embeddings = cursor.execute(
        "SELECT name, embedding FROM tool_definitions WHERE embedding IS NOT NULL LIMIT 50"
    ).fetchall()
    
    db.close()
    
    # Analyze dimensions
    memory_issues = []
    for mem_id, key, embedding_blob in memories_with_embeddings:
        try:
            # Try to deserialize
            try:
                embedding = json.loads(embedding_blob.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                embedding = pickle.loads(embedding_blob)
            
            actual_dim = len(embedding)
            if actual_dim != expected_dim:
                memory_issues.append({
                    'id': mem_id,
                    'key': key[:50],
                    'expected': expected_dim,
                    'actual': actual_dim
                })
        except Exception as e:
            memory_issues.append({
                'id': mem_id,
                'key': key[:50],
                'error': str(e)
            })
    
    tool_issues = []
    for tool_name, embedding_blob in tools_with_embeddings:
        try:
            # Try to deserialize
            try:
                embedding = json.loads(embedding_blob.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                embedding = pickle.loads(embedding_blob)
            
            actual_dim = len(embedding)
            if actual_dim != expected_dim:
                tool_issues.append({
                    'name': tool_name,
                    'expected': expected_dim,
                    'actual': actual_dim
                })
        except Exception as e:
            tool_issues.append({
                'name': tool_name,
                'error': str(e)
            })
    
    # Generate a real provider embedding to verify current config. A same-size
    # hash fallback must not make a disconnected provider look healthy.
    provider_error = None
    try:
        test_embedding = get_persistable_embedding("test query")
        current_dim = len(test_embedding)
    except Exception as exc:
        current_dim = None
        provider_error = str(exc)
    
    llm_provider = get_config_value("LLM_PROVIDER", "openai")
    effective = _effective_embedding_backend()
    if mode == "local":
        embedding_model = get_config_value("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    else:
        embedding_model = (
            get_config_value("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
            if effective == "ollama"
            else "text-embedding-3-small"
        )
    
    return {
        'ok': (
            provider_error is None
            and len(memory_issues) == 0
            and len(tool_issues) == 0
            and current_dim == expected_dim
        ),
        'mode': mode,
        'expected_dimensions': expected_dim,
        'current_embedding_dimensions': current_dim,
        'memories_checked': len(memories_with_embeddings),
        'memory_issues': memory_issues,
        'tools_checked': len(tools_with_embeddings),
        'tool_issues': tool_issues,
        # What actually runs vectors (openai vs ollama), not the chat LLM (xai/anthropic/…)
        'embedding_provider': effective,
        'llm_provider': llm_provider,
        'embedding_model': embedding_model,
        'provider_error': provider_error,
    }


def print_health_report(health):
    """Print a formatted health report."""
    mode = health['mode']
    ok = health['ok']
    
    print(f"{BOLD}╔════════════════════════════════════════════════════════════╗{NC}")
    print(f"{BOLD}║  Embedding Health Check - {mode.upper()} Mode{' ' * (30 - len(mode))}║{NC}")
    print(f"{BOLD}╚════════════════════════════════════════════════════════════╝{NC}")
    print()
    
    # Overall status
    if ok:
        print(f"{GREEN}✅ All embeddings are healthy!{NC}")
    elif health.get('provider_error'):
        print(f"{RED}❌ Embedding provider unavailable!{NC}")
    else:
        print(f"{RED}❌ Embedding dimension mismatch detected!{NC}")
    
    print()
    print(f"{BLUE}Expected Dimensions:{NC} {health['expected_dimensions']}")
    print(f"{BLUE}Current Config Generates:{NC} {health['current_embedding_dimensions']}")
    print(f"{BLUE}Embedding Provider:{NC} {health['embedding_provider']}")
    if health.get("llm_provider") and health["llm_provider"] != health["embedding_provider"]:
        print(f"{BLUE}LLM Provider (chat):{NC} {health['llm_provider']}")
    print(f"{BLUE}Embedding Model:{NC} {health['embedding_model']}")
    if health.get('provider_error'):
        print(f"{RED}Provider Error:{NC} {health['provider_error']}")
    print()
    
    # Memory embeddings
    print(f"{BOLD}Knowledge Base:{NC}")
    print(f"  Checked: {health['memories_checked']} memories")
    if health['memory_issues']:
        print(f"  {RED}Issues: {len(health['memory_issues'])}{NC}")
        print()
        for issue in health['memory_issues'][:5]:  # Show first 5
            if 'error' in issue:
                print(f"    {RED}✗{NC} Memory #{issue['id']} ({issue['key']}...): {issue['error']}")
            else:
                print(f"    {RED}✗{NC} Memory #{issue['id']} ({issue['key']}...): {issue['actual']}D (expected {issue['expected']}D)")
        if len(health['memory_issues']) > 5:
            print(f"    ... and {len(health['memory_issues']) - 5} more")
    else:
        print(f"  {GREEN}✓ All OK{NC}")
    
    print()
    
    # Tool embeddings
    print(f"{BOLD}Tool Definitions:{NC}")
    print(f"  Checked: {health['tools_checked']} tools")
    if health['tool_issues']:
        print(f"  {RED}Issues: {len(health['tool_issues'])}{NC}")
        print()
        for issue in health['tool_issues'][:5]:  # Show first 5
            if 'error' in issue:
                print(f"    {RED}✗{NC} Tool {issue['name']}: {issue['error']}")
            else:
                print(f"    {RED}✗{NC} Tool {issue['name']}: {issue['actual']}D (expected {issue['expected']}D)")
        if len(health['tool_issues']) > 5:
            print(f"    ... and {len(health['tool_issues']) - 5} more")
    else:
        print(f"  {GREEN}✓ All OK{NC}")
    
    print()
    
    # Recommendations
    if not ok:
        print(f"{BOLD}{YELLOW}🔧 Recommended Actions:{NC}")
        
        if health.get('provider_error'):
            print(f"{YELLOW}  1. Restore the configured embedding provider, then rerun the failed sync{NC}")
        elif health['current_embedding_dimensions'] != health['expected_dimensions']:
            print(f"{YELLOW}  1. Config issue: Current embedding model generates wrong dimensions{NC}")
            print(f"     Check config/{mode}.env for correct LLM_PROVIDER and embedding model")
        
        if health['memory_issues']:
            print(f"{YELLOW}  2. Memory embeddings are wrong - regenerate them:{NC}")
            if mode == 'local':
                print(f"     ./bin/sync-memory-db.py --from cloud --to local")
            else:
                print(f"     ./bin/sync-memory-db.py --from local --to cloud")
        
        if health['tool_issues']:
            print(f"{YELLOW}  3. Tool embeddings are wrong - regenerate them:{NC}")
            print(f"     ./bin/sync-tools.py {mode}")
        
        print()
        print(f"{RED}⚠️  Semantic search will fail until embeddings are fixed!{NC}")
    
    print()
    print("━" * 62)


def main():
    """Run health check for specified mode."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Check embedding health for Jarvis databases')
    parser.add_argument('mode', nargs='?', default='cloud', choices=['cloud', 'local'],
                        help='Mode to check (cloud or local)')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of formatted text')
    parser.add_argument('--both', action='store_true', help='Check both cloud and local modes')
    
    args = parser.parse_args()
    
    if args.both:
        # Check both modes
        cloud_health = check_embedding_dimensions('cloud')
        local_health = check_embedding_dimensions('local')
        
        if args.json:
            print(json.dumps({
                'cloud': cloud_health,
                'local': local_health
            }, indent=2))
        else:
            print_health_report(cloud_health)
            print()
            print_health_report(local_health)
        
        # Exit with error if either mode has issues
        if not cloud_health['ok'] or not local_health['ok']:
            sys.exit(1)
    else:
        # Check single mode
        health = check_embedding_dimensions(args.mode)
        
        if args.json:
            print(json.dumps(health, indent=2))
        else:
            print_health_report(health)
        
        # Exit with error code if issues found
        if not health['ok']:
            sys.exit(1)


if __name__ == '__main__':
    main()
