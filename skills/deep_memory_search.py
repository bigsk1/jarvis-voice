#!/usr/bin/env python3
"""
Deep Memory Search Tool - Comprehensive search across ALL Jarvis data sources.

Searches:
- Memory database (knowledge_base with FTS5 and semantic)
- Terminal conversations (conversations table)
- Web UI conversations (data/web_conversations/*.json)
- Intel folder (jarvis-intel/*.md)
- Canvas pages (data/canvas/*.json)
- Stash spaces (data/stash/*/meta.json)

Uses ripgrep (rg) for fast file-based searches with --json output.
"""

import sys
import os
import json
import subprocess
import re
from datetime import datetime, timedelta
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db
from config_loader import load_config

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def parse_date_filter(date_filter: str) -> datetime | None:
    """Convert date filter string to datetime object."""
    if not date_filter:
        return None
    
    now = datetime.now()
    
    if date_filter == 'today':
        return datetime(now.year, now.month, now.day)
    elif date_filter == 'week':
        return now - timedelta(days=7)
    elif date_filter == 'month':
        return now - timedelta(days=30)
    elif date_filter == 'year':
        return now - timedelta(days=365)
    else:
        # Try parsing as ISO date
        try:
            return datetime.fromisoformat(date_filter.replace('Z', '+00:00'))
        except ValueError:
            return None


def memory_retrieval_label(memory: dict) -> tuple[str, str]:
    """Return truthful source labels for a MemoryDB semantic_search row."""
    channels = set(memory.get('retrieval_channels') or [])
    similarity = memory.get('similarity')

    if 'dense' in channels:
        try:
            similarity_text = f", {float(similarity) * 100:.0f}% semantic match"
        except (TypeError, ValueError):
            similarity_text = ""
        if 'keyword' in channels:
            return 'memory_hybrid', f"Memory (hybrid{similarity_text})"
        return 'memory_semantic', f"Memory (semantic{similarity_text})"

    if 'keyword' in channels:
        if memory.get('keyword_match_mode') == 'fallback':
            return 'memory_keyword', 'Memory (keyword fallback; embeddings unavailable)'
        return 'memory_keyword', 'Memory (exact keyword match)'

    # Compatibility for older/custom MemoryDB implementations that return a
    # cosine but do not annotate retrieval channels.
    if isinstance(similarity, (int, float)):
        return 'memory_semantic', f"Memory (semantic, {similarity * 100:.0f}% match)"
    return 'memory_retrieval', 'Memory (retrieval match)'


def ripgrep_search(query: str, paths: list[str], file_globs: list[str] = None, 
                   case_sensitive: bool = False, no_ignore: bool = False) -> list[dict]:
    """
    Search files using ripgrep with JSON output.
    
    Args:
        query: Search pattern
        paths: List of paths to search
        file_globs: Optional glob patterns like ['*.md', '*.json']
        case_sensitive: Whether to be case sensitive
        no_ignore: Skip .gitignore (needed for stash which is gitignored)
        
    Returns:
        List of match dicts with file, line_number, line_content, match_text
    """
    results = []
    
    # Filter to existing paths
    existing_paths = [p for p in paths if Path(p).exists()]
    if not existing_paths:
        return results
    
    # Build ripgrep command
    cmd = ['rg', '--json', '--smart-case', '--multiline', '--max-count', '10']
    
    if no_ignore:
        cmd.append('--no-ignore')
    
    if case_sensitive:
        cmd.remove('--smart-case')
        cmd.append('--case-sensitive')
    
    # Add glob filters
    if file_globs:
        for glob in file_globs:
            cmd.extend(['--glob', glob])
    
    # Add query and paths
    cmd.append(query)
    cmd.extend(existing_paths)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        # Parse JSON lines output
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get('type') == 'match':
                    match_data = data.get('data', {})
                    path_data = match_data.get('path', {})
                    lines_data = match_data.get('lines', {})
                    submatches = match_data.get('submatches', [])
                    
                    # Extract match text
                    match_text = ''
                    if submatches:
                        match_text = submatches[0].get('match', {}).get('text', '')
                    
                    results.append({
                        'file': path_data.get('text', ''),
                        'line_number': match_data.get('line_number', 0),
                        'line_content': lines_data.get('text', '').strip()[:500],  # Limit content
                        'match_text': match_text
                    })
            except json.JSONDecodeError:
                continue
                
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        # ripgrep not installed - fall back to basic grep
        pass
    
    return results


def search_memory_db(query: str, limit: int, mode: str, date_filter: datetime = None) -> tuple[list[dict], dict]:
    """Search memory database using existing methods."""
    results = []
    semantic_meta = {
        "retrieval_mode": "hybrid",
        "semantic_disabled_reason": None,
    }
    
    try:
        db = get_memory_db()
        
        if mode in ['comprehensive', 'keyword']:
            # FTS5 keyword search
            keyword_results = db.search_memory(query=query, limit=limit)
            for mem in keyword_results:
                # Remove embedding blob
                if 'embedding' in mem:
                    del mem['embedding']
                
                # Date filtering
                if date_filter and mem.get('created_at'):
                    try:
                        mem_date = datetime.fromisoformat(mem['created_at'].replace('Z', '+00:00'))
                        if mem_date < date_filter:
                            continue
                    except:
                        pass
                
                mem['_source'] = 'memory_keyword'
                mem['_source_display'] = 'Memory (keyword match)'
                results.append(mem)
        
        if mode in ['comprehensive', 'semantic']:
            # Semantic search
            semantic_results = db.semantic_search(query=query, limit=limit)
            semantic_meta = getattr(
                db,
                'last_semantic_search_meta',
                {"retrieval_mode": "hybrid", "semantic_disabled_reason": None},
            )
            for mem in semantic_results:
                # Avoid duplicates from keyword search
                existing_keys = [r.get('key') for r in results]
                if mem.get('key') in existing_keys:
                    continue
                
                if date_filter and mem.get('created_at'):
                    try:
                        mem_date = datetime.fromisoformat(mem['created_at'].replace('Z', '+00:00'))
                        if mem_date < date_filter:
                            continue
                    except:
                        pass
                
                mem['_source'], mem['_source_display'] = memory_retrieval_label(mem)
                results.append(mem)
        
        db.close()
    except Exception:
        pass
    
    return results[:limit], semantic_meta


def search_terminal_conversations(query: str, limit: int, date_filter: datetime = None) -> list[dict]:
    """Search terminal/voice conversation history from database."""
    results = []
    
    try:
        db = get_memory_db()
        conversations = db.search_conversations(query=query, limit=limit)
        db.close()
        
        for conv in conversations:
            if date_filter and conv.get('timestamp'):
                try:
                    conv_date = datetime.fromisoformat(conv['timestamp'].replace('Z', '+00:00'))
                    if conv_date < date_filter:
                        continue
                except:
                    pass
            
            conv['_source'] = 'terminal_conversation'
            conv['_source_display'] = 'Terminal/Voice Conversation'
            results.append(conv)
            
    except Exception:
        pass
    
    return results[:limit]


def search_web_conversations(query: str, limit: int, date_filter: datetime = None) -> list[dict]:
    """Search web UI conversation JSON files using ripgrep."""
    results = []
    web_conv_dir = PROJECT_ROOT / 'data' / 'web_conversations'
    
    if not web_conv_dir.exists():
        return results
    
    # Use ripgrep on JSON files
    rg_results = ripgrep_search(
        query, 
        [str(web_conv_dir)], 
        file_globs=['*.json', '!index.json']
    )
    
    # Parse matched files for context
    seen_files = set()
    for match in rg_results:
        file_path = match.get('file', '')
        if file_path in seen_files or file_path.endswith('index.json'):
            continue
        seen_files.add(file_path)
        
        try:
            with open(file_path, 'r') as f:
                conv_data = json.load(f)
            
            # Date filtering
            if date_filter and conv_data.get('created_at'):
                try:
                    conv_date = datetime.fromisoformat(conv_data['created_at'].replace('Z', '+00:00'))
                    if conv_date < date_filter:
                        continue
                except:
                    pass
            
            # Extract relevant messages
            matching_messages = []
            for msg in conv_data.get('messages', []):
                content = msg.get('content', '')
                if query.lower() in content.lower():
                    matching_messages.append({
                        'role': msg.get('role'),
                        'content': content[:300],
                        'tools_used': msg.get('tools_used', [])
                    })
            
            results.append({
                'conversation_id': conv_data.get('id'),
                'title': conv_data.get('title', '')[:100],
                'created_at': conv_data.get('created_at'),
                'message_count': len(conv_data.get('messages', [])),
                'matching_messages': matching_messages[:3],
                'matched_line': match.get('line_content', '')[:200],
                '_source': 'web_conversation',
                '_source_display': 'Web UI Conversation'
            })
            
            if len(results) >= limit:
                break
                
        except Exception:
            continue
    
    return results[:limit]


def search_intel_folder(query: str, limit: int, date_filter: datetime = None) -> list[dict]:
    """Search intel folder markdown files using ripgrep."""
    results = []
    intel_dir = PROJECT_ROOT / 'jarvis-intel'
    
    if not intel_dir.exists():
        return results
    
    rg_results = ripgrep_search(
        query,
        [str(intel_dir)],
        file_globs=['*.md', '*.txt']
    )
    
    # Group by file
    files_matches = {}
    for match in rg_results:
        file_path = match.get('file', '')
        if file_path not in files_matches:
            files_matches[file_path] = []
        files_matches[file_path].append(match)
    
    for file_path, matches in files_matches.items():
        try:
            if date_filter:
                file_mtime = datetime.fromtimestamp(Path(file_path).stat().st_mtime)
                if file_mtime < date_filter:
                    continue

            file_name = Path(file_path).name
            
            # Get file content preview
            with open(file_path, 'r') as f:
                content = f.read()
            
            results.append({
                'file': file_name,
                'file_path': file_path,
                'match_count': len(matches),
                'matched_lines': [m.get('line_content', '')[:200] for m in matches[:3]],
                'content_preview': content[:500] if len(content) < 500 else content[:500] + '...',
                '_source': 'intel',
                '_source_display': f'Intel File: {file_name}'
            })

            if len(results) >= limit:
                break
        except Exception:
            continue
    
    return results


def search_canvas_pages(query: str, limit: int, date_filter: datetime = None) -> list[dict]:
    """Search canvas page content and tags using ripgrep."""
    results = []
    canvas_dir = PROJECT_ROOT / 'data' / 'canvas'
    
    if not canvas_dir.exists():
        return results
    
    rg_results = ripgrep_search(
        query,
        [str(canvas_dir)],
        file_globs=['*.json']
    )
    
    seen_files = set()
    for match in rg_results:
        file_path = match.get('file', '')
        if file_path in seen_files:
            continue
        seen_files.add(file_path)
        
        try:
            with open(file_path, 'r') as f:
                page_data = json.load(f)
            
            # Date filtering
            if date_filter and page_data.get('created'):
                try:
                    page_date = datetime.fromisoformat(page_data['created'].replace('Z', '+00:00'))
                    if page_date < date_filter:
                        continue
                except:
                    pass
            
            results.append({
                'page_id': page_data.get('id'),
                'title': page_data.get('title', ''),
                'tags': page_data.get('tags', []),
                'source_query': page_data.get('source_query', ''),
                'created': page_data.get('created'),
                'content_preview': page_data.get('content', '')[:500],
                'matched_line': match.get('line_content', '')[:200],
                '_source': 'canvas',
                '_source_display': f"Canvas: {page_data.get('title', 'Untitled')[:50]}"
            })
            
            if len(results) >= limit:
                break
                
        except Exception:
            continue
    
    return results[:limit]


def search_stash_spaces(query: str, limit: int, date_filter: datetime = None) -> list[dict]:
    """Search stash space metadata AND file contents."""
    results = []
    stash_dir = PROJECT_ROOT / 'data' / 'stash'
    
    if not stash_dir.exists():
        return results
    
    # Search both meta.json AND content files (.md, .txt, .json but not meta.json)
    # Use no_ignore=True because stash is in .gitignore
    rg_results = ripgrep_search(
        query,
        [str(stash_dir)],
        file_globs=['*.md', '*.txt', '*.json'],
        no_ignore=True
    )
    
    seen_spaces = set()
    for match in rg_results:
        file_path = match.get('file', '')
        space_dir = Path(file_path).parent.name
        matched_file = Path(file_path).name
        
        if space_dir in seen_spaces:
            continue
        seen_spaces.add(space_dir)
        
        # Get meta.json for this space
        meta_path = PROJECT_ROOT / 'data' / 'stash' / space_dir / 'meta.json'
        try:
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            
            # Date filtering
            if date_filter and meta.get('created_at'):
                try:
                    space_date = datetime.fromisoformat(meta['created_at'].replace('Z', '+00:00'))
                    if space_date < date_filter:
                        continue
                except:
                    pass
            
            # Get file info
            files = meta.get('files', [])
            file_names = [f.get('name', '') for f in files]
            tool_origins = list(set(f.get('tool_origin', '') for f in files if f.get('tool_origin')))
            
            # Get content preview from matched file (if not meta.json)
            content_preview = ""
            if matched_file != 'meta.json':
                try:
                    with open(file_path, 'r') as f:
                        content_preview = f.read()[:500]
                except:
                    pass
            
            results.append({
                'space_id': meta.get('space_id'),
                'labels': meta.get('labels', []),
                'created_at': meta.get('created_at'),
                'file_count': len(files),
                'file_names': file_names[:5],
                'tool_origins': tool_origins,
                'pinned': meta.get('pinned', False),
                'matched_file': matched_file if matched_file != 'meta.json' else None,
                'matched_line': match.get('line_content', '')[:200],
                'content_preview': content_preview[:300] if content_preview else None,
                '_source': 'stash',
                '_source_display': f"Stash: {', '.join(meta.get('labels', []))[:50] or space_dir}"
            })
            
            if len(results) >= limit:
                break
                
        except Exception:
            continue
    
    return results[:limit]


def deduplicate_results(results: list[dict]) -> list[dict]:
    """
    Remove duplicates where same data appears in multiple sources.
    E.g., intel file content that's also in memory.
    """
    seen_content = set()
    deduped = []
    
    for r in results:
        # Create content fingerprint
        content = ''
        if r.get('value'):
            content = r['value'][:100].lower()
        elif r.get('content_preview'):
            content = r['content_preview'][:100].lower()
        elif r.get('matched_line'):
            content = r['matched_line'][:100].lower()
        elif r.get('title'):
            content = r['title'][:100].lower()
        
        # Skip if very similar content already seen
        fingerprint = re.sub(r'\s+', ' ', content.strip())
        if fingerprint and fingerprint in seen_content:
            r['_duplicate_of'] = 'Similar content found in another source'
            # Still include but mark as potential duplicate
        
        seen_content.add(fingerprint)
        deduped.append(r)
    
    return deduped


def main():
    """Main entry point for deep memory search."""
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config for embeddings
        load_config()
        
        # Extract parameters
        query = args.get('query')
        if not query:
            raise ValueError("query parameter is required")
        
        sources = args.get('sources', ['all'])
        if 'all' in sources:
            sources = ['memory', 'conversations', 'web_conversations', 'intel', 'canvas', 'stash']
        
        mode = args.get('mode', 'comprehensive')
        limit = args.get('limit_per_source', 5)
        date_filter = parse_date_filter(args.get('date_filter'))
        
        # Collect results from each source
        all_results = {}
        source_counts = {}
        
        if 'memory' in sources:
            memory_results, memory_semantic_meta = search_memory_db(query, limit, mode, date_filter)
            all_results['memory'] = memory_results
            source_counts['memory'] = len(memory_results)
        else:
            memory_semantic_meta = {
                "retrieval_mode": "hybrid",
                "semantic_disabled_reason": None,
            }
        
        if 'conversations' in sources:
            conv_results = search_terminal_conversations(query, limit, date_filter)
            all_results['terminal_conversations'] = conv_results
            source_counts['terminal_conversations'] = len(conv_results)
        
        if 'web_conversations' in sources:
            web_conv_results = search_web_conversations(query, limit, date_filter)
            all_results['web_conversations'] = web_conv_results
            source_counts['web_conversations'] = len(web_conv_results)
        
        if 'intel' in sources:
            intel_results = search_intel_folder(query, limit, date_filter)
            all_results['intel'] = intel_results
            source_counts['intel'] = len(intel_results)
        
        if 'canvas' in sources:
            canvas_results = search_canvas_pages(query, limit, date_filter)
            all_results['canvas'] = canvas_results
            source_counts['canvas'] = len(canvas_results)
        
        if 'stash' in sources:
            stash_results = search_stash_spaces(query, limit, date_filter)
            all_results['stash'] = stash_results
            source_counts['stash'] = len(stash_results)
        
        # Flatten and deduplicate
        flat_results = []
        for source, items in all_results.items():
            flat_results.extend(items)
        
        flat_results = deduplicate_results(flat_results)
        
        # Calculate totals
        total_found = sum(source_counts.values())
        sources_with_results = [s for s, c in source_counts.items() if c > 0]
        
        # Build speech response
        if total_found == 0:
            speech = f"No results found for '{query}' across any data source."
        else:
            source_summary = ', '.join([f"{c} in {s}" for s, c in source_counts.items() if c > 0])
            speech = f"Found {total_found} results for '{query}': {source_summary}"
        
        # Build structured output
        output = {
            "ok": True,
            "speech": speech,
            "data": {
                "query": query,
                "mode": mode,
                "sources_searched": sources,
                "date_filter": args.get('date_filter'),
                "embedding_diagnostics": {
                    "memory_semantic_search": memory_semantic_meta,
                },
                "summary": {
                    "total_results": total_found,
                    "by_source": source_counts,
                    "sources_with_matches": sources_with_results
                },
                "results": all_results,
                "flat_results": flat_results,
                "usage_note": "Results are grouped by source. 'flat_results' contains all results with '_source' labels. Check '_duplicate_of' field for potential duplicates across sources."
            }
        }
        
        print(json.dumps(output))
        
    except Exception as e:
        error_result = {
            "ok": False,
            "error": str(e),
            "speech": f"Deep memory search failed: {e}"
        }
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
