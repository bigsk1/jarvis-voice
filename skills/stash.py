#!/usr/bin/env python3
"""
Tool Name: Stash
Description: Generic artifact storage for multi-step tasks
Input: { "action": "open_space|info|save|list|read|update|cleanup", ... }
Output: { "ok": bool, "speech": str, "data": {...} }

Stash is the standard artifact layer for the Jarvis ecosystem.
It provides structured storage for files, images, and other artifacts
that need to persist across tool calls or sessions.
"""

import sys
import os
import json
import base64
import requests
import subprocess

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from stash_helper import (
    open_space, get_space, list_spaces, cleanup_expired,
    StashFile
)

# Tool locations for calling other tools
SKILLS_DIR = os.path.dirname(__file__)


def call_tool(tool_name: str, args: dict = None, timeout: int = 60) -> dict:
    """
    Call another Jarvis tool and return its result.
    Used for calling pdf_read to extract text from PDFs.
    """
    try:
        tool_path = os.path.join(SKILLS_DIR, f"{tool_name}.py")
        if not os.path.exists(tool_path):
            return {"ok": False, "error": f"Tool {tool_name} not found"}
        
        # Get project root for proper module resolution
        project_root = os.path.join(os.path.dirname(__file__), '..')
        
        input_data = json.dumps(args or {})
        cmd = ["python3", tool_path, input_data]
        
        # Run from project root so tools can find their lib imports
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=project_root)
        
        if result.returncode == 0 and result.stdout:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"ok": False, "error": f"Invalid JSON from {tool_name}"}
        return {"ok": False, "error": result.stderr or f"Tool {tool_name} failed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{tool_name} timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def extract_pdf_text(file_path: str) -> str | None:
    """
    Extract text from a PDF file using pdf_read tool.
    
    Returns:
        Extracted text, or None if extraction fails
    """
    result = call_tool('pdf_read', {
        'action': 'extract_text',
        'file_path': file_path
    })
    
    if result.get('ok') and result.get('data', {}).get('text'):
        return result['data']['text']
    return None


def summarize_content_with_llm(content: str, file_name: str, max_length: int = 500) -> str | None:
    """
    Summarize content using configured LLM provider.
    
    Makes a direct API call (not through orchestrator) to keep key facts
    for memory storage. Uses cheap/fast models when available.
    
    Args:
        content: Full text content to summarize
        file_name: For context in the prompt
        max_length: Target summary length
    
    Returns:
        Summary string, or None if LLM call fails (caller should fallback to truncation)
    """
    provider = get_config_value('LLM_PROVIDER', 'openai').lower()
    
    # System prompt for summarization
    system_prompt = """You are a precise summarizer. Extract and preserve ALL key facts, numbers, dates, names, and conclusions from the content. 
Output a dense summary that captures the essential information for future reference.
Do NOT add commentary or opinions - just the facts."""
    
    user_prompt = f"""Summarize this content from "{file_name}" in under {max_length} characters, preserving all key facts:

{content[:8000]}"""  # Cap input to avoid token limits
    
    try:
        if provider == 'openai':
            api_key = get_config_value('OPENAI_API_KEY')
            if not api_key:
                return None
            
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={
                    'model': get_config_value('STASH_SUMMARIZE_MODEL', 'gpt-4o-mini'),
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': user_prompt}
                    ],
                    'max_tokens': 400,
                    'temperature': 0.3
                },
                timeout=30
            )
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content'].strip()
        
        elif provider == 'anthropic':
            api_key = get_config_value('ANTHROPIC_API_KEY')
            if not api_key:
                return None
            
            response = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': api_key,
                    'Content-Type': 'application/json',
                    'anthropic-version': '2023-06-01'
                },
                json={
                    'model': get_config_value('STASH_SUMMARIZE_MODEL', 'claude-4-5-sonnet-20250929'),
                    'max_tokens': 400,
                    'system': system_prompt,
                    'messages': [{'role': 'user', 'content': user_prompt}]
                },
                timeout=30
            )
            response.raise_for_status()
            return response.json()['content'][0]['text'].strip()
        
        
        elif provider == 'ollama':
            base_url = get_config_value('OLLAMA_BASE_URL', 'http://localhost:11434')
            model = get_config_value('STASH_SUMMARIZE_MODEL', 'qwen3:14b')
            
            response = requests.post(
                f'{base_url}/api/chat',
                json={
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': user_prompt}
                    ],
                    'stream': False,
                    'options': {'num_predict': 300, 'temperature': 0.3}
                },
                timeout=60  # Ollama can be slower
            )
            response.raise_for_status()
            return response.json()['message']['content'].strip()
        
        elif provider == 'xai':
            api_key = get_config_value('XAI_API_KEY')
            if not api_key:
                return None
            
            response = requests.post(
                'https://api.x.ai/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={
                    'model': get_config_value('STASH_SUMMARIZE_MODEL', 'grok-4-1-fast-non-reasoning'),
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': user_prompt}
                    ],
                    'max_tokens': 400,
                    'temperature': 0.3
                },
                timeout=30
            )
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content'].strip()
        
        else:
            return None
            
    except Exception as e:
        # Silent fail - caller will fallback to truncation
        print(f"LLM summarize failed: {e}", file=sys.stderr)
        return None


def format_size(bytes_size: int) -> str:
    """Format bytes to human-readable size."""
    if bytes_size < 1024:
        return f"{bytes_size}B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f}KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.1f}MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.1f}GB"


def action_open_space(args: dict) -> dict:
    """Create or resume a stash space."""
    space_id = args.get('space_id')
    labels = args.get('labels', [])
    scope = args.get('scope', 'session')
    ttl_days = args.get('ttl_days')
    
    space, is_new = open_space(
        space_id=space_id,
        labels=labels,
        scope=scope,
        ttl_days=ttl_days
    )
    
    if is_new:
        speech = f"Created new stash space"
    else:
        speech = f"Resumed existing stash space"
    
    return {
        "ok": True,
        "speech": speech,
        "data": {
            "space_id": space.space_id,
            "path": str(space.space_path),
            "scope": scope,
            "is_new": is_new
        }
    }


def action_info(args: dict) -> dict:
    """Get space metadata summary."""
    space_id = args.get('space_id')
    if not space_id:
        raise ValueError("space_id is required")
    
    space = get_space(space_id)
    info = space.info()
    
    size_str = format_size(info['total_size_bytes'])
    speech = f"Space has {info['file_count']} files, {size_str} total"
    if info.get('pinned'):
        speech += " (pinned)"
    
    return {
        "ok": True,
        "speech": speech,
        "data": info
    }


def action_save(args: dict) -> dict:
    """Save content to stash."""
    space_id = args.get('space_id')
    name = args.get('name')
    kind = args.get('kind', 'text')
    on_conflict = args.get('on_conflict', 'error')
    tags = args.get('tags', [])
    tool_origin = args.get('tool_origin', 'stash')  # Default to 'stash' when called directly
    
    if not name:
        raise ValueError("name is required")
    
    # Get or create space
    if space_id:
        space = get_space(space_id)
    else:
        space, _ = open_space(scope='session')
    
    stash_file = StashFile(space)
    
    if kind == 'text':
        text = args.get('text')
        if not text:
            raise ValueError("text is required for kind='text'")
        result = stash_file.save_text(text, name, on_conflict, tags, tool_origin)
        
    elif kind == 'json':
        json_data = args.get('json')
        if json_data is None:
            raise ValueError("json is required for kind='json'")
        result = stash_file.save_json(json_data, name, on_conflict, tags, tool_origin)
        
    elif kind == 'base64':
        data_b64 = args.get('data')
        if not data_b64:
            raise ValueError("data is required for kind='base64'")
        data = base64.b64decode(data_b64)
        result = stash_file.save_binary(data, name, args.get('mime_type'), 
                                        on_conflict, tags, tool_origin)
        
    elif kind == 'url':
        url = args.get('url')
        if not url:
            raise ValueError("url is required for kind='url'")
        result = stash_file.save_from_url(url, name, on_conflict, tags, tool_origin)
    
    elif kind == 'file':
        file_path = args.get('file_path')
        if not file_path:
            raise ValueError("file_path is required for kind='file'")
        
        from pathlib import Path
        src_path = Path(file_path)
        
        if not src_path.exists():
            raise ValueError(f"File not found: {file_path}")
        
        # Security: only allow files from /tmp or project directories
        allowed_prefixes = ['/tmp', str(Path(__file__).parent.parent)]
        if not any(str(src_path).startswith(prefix) for prefix in allowed_prefixes):
            raise ValueError(f"File path not allowed: {file_path}")
        
        # Read file and save as binary
        with open(src_path, 'rb') as f:
            data = f.read()
        
        # Use original filename if no name provided
        if not name:
            name = src_path.name
        
        result = stash_file.save_binary(data, name, args.get('mime_type'), 
                                        on_conflict, tags, tool_origin)
        
    else:
        raise ValueError(f"Unknown kind: {kind}. Use: text, json, base64, url, file")
    
    size_str = format_size(result['size_bytes'])
    
    return {
        "ok": True,
        "speech": f"Saved {name} to stash ({size_str})",
        "data": {
            "space_id": space.space_id,
            **result
        }
    }


def action_list(args: dict) -> dict:
    """List files in a space."""
    space_id = args.get('space_id')
    
    if space_id:
        space = get_space(space_id)
        files = space.meta.get('files', [])
        
        # Simplify file info for response
        file_list = []
        for f in files:
            file_list.append({
                'file_id': f.get('file_id'),
                'name': f.get('name'),
                'mime_type': f.get('mime_type'),
                'size_bytes': f.get('size_bytes'),
                'created_at': f.get('created_at')
            })
        
        speech = f"Space has {len(file_list)} file(s)"
        return {
            "ok": True,
            "speech": speech,
            "data": {
                "space_id": space_id,
                "files": file_list
            }
        }
    else:
        # List all spaces
        spaces = list_spaces()
        speech = f"Found {len(spaces)} stash space(s)"
        return {
            "ok": True,
            "speech": speech,
            "data": {
                "spaces": spaces
            }
        }


def action_read(args: dict) -> dict:
    """Read file content or get path."""
    space_id = args.get('space_id')
    file_id = args.get('file_id')
    mode = args.get('mode', 'auto')
    
    if not space_id:
        raise ValueError("space_id is required")
    if not file_id:
        raise ValueError("file_id is required")
    
    space = get_space(space_id)
    
    # Try to find by file_id first, then by name
    stash_file = StashFile(space, file_id=file_id)
    if not stash_file.exists:
        stash_file = StashFile(space, name=file_id)
    
    if not stash_file.exists:
        raise ValueError(f"File '{file_id}' not found in space")
    
    result = stash_file.read(mode=mode)
    
    if 'content' in result:
        speech = f"Read {result['name']}"
    else:
        speech = f"Retrieved path for {result['name']}"
    
    return {
        "ok": True,
        "speech": speech,
        "data": result
    }


def action_update(args: dict) -> dict:
    """Update space metadata (TTL, pinned, labels)."""
    space_id = args.get('space_id')
    if not space_id:
        raise ValueError("space_id is required")
    
    space = get_space(space_id)
    
    ttl_days = args.get('ttl_days')
    pinned = args.get('pinned')
    labels = args.get('labels')
    
    space.update(ttl_days=ttl_days, pinned=pinned, labels=labels)
    
    parts = []
    if pinned is not None:
        parts.append("pinned" if pinned else "unpinned")
    if ttl_days is not None:
        parts.append(f"TTL set to {ttl_days} days")
    if labels is not None:
        parts.append(f"labels updated")
    
    speech = "Space " + ", ".join(parts) if parts else "Space updated"
    
    return {
        "ok": True,
        "speech": speech,
        "data": space.info()
    }


def action_cleanup(args: dict) -> dict:
    """Clean up spaces."""
    space_id = args.get('space_id')
    args.get('mode', 'expired_only')
    
    if space_id:
        # Delete specific space
        space = get_space(space_id)
        freed = space.delete()
        
        return {
            "ok": True,
            "speech": f"Deleted space, freed {format_size(freed)}",
            "data": {
                "deleted_spaces": 1,
                "freed_bytes": freed
            }
        }
    else:
        # Clean up expired spaces
        result = cleanup_expired()
        
        speech = f"Cleaned up {result['deleted_spaces']} expired space(s)"
        if result['freed_bytes'] > 0:
            speech += f", freed {format_size(result['freed_bytes'])}"
        
        return {
            "ok": True,
            "speech": speech,
            "data": result
        }


def action_remember(args: dict) -> dict:
    """
    Save stash artifact to persistent memory.
    
    This bridges the gap between temporary stash storage and permanent memory.
    For text files: saves content with metadata
    For binary files: saves metadata only (description, tags, stash ref)
    
    Args:
        space_id: Stash space ID (required if not using search)
        file_id: File ID or filename (required if not using search)
        search: Search term to find stash file (alternative to space_id/file_id)
        key: Memory key (optional - auto-generated if not provided)
        category: Memory category (default: 'fact')
        importance: Importance 1-10 (default: 7)
        summary: Custom summary to save instead of full content
    """
    # Import memory_db here to avoid circular imports
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
    from memory_db import get_memory_db
    
    space_id = args.get('space_id')
    file_id = args.get('file_id')
    search = args.get('search')
    key = args.get('key')
    category = args.get('category', 'fact')
    importance = args.get('importance', 7)
    summary = args.get('summary')
    auto_summarize = args.get('summarize', False)  # Use LLM to summarize large content
    
    # Find the file - either by direct reference or search
    if search and not (space_id and file_id):
        # Search for the file in recent stash spaces
        all_spaces = list_spaces()
        found = None
        search_lower = search.lower()
        search_terms = search_lower.split()  # Split into words for better matching
        
        for space_info in all_spaces:
            try:
                space = get_space(space_info['space_id'])
                space_labels = [l.lower() for l in space.meta.get('labels', [])]
                
                for file_meta in space.meta.get('files', []):
                    file_name = file_meta.get('name', '').lower()
                    file_tags = [t.lower() for t in file_meta.get('tags', [])]
                    
                    # Match: all search terms found in filename, tags, or space labels
                    searchable = file_name + ' ' + ' '.join(file_tags) + ' ' + ' '.join(space_labels)
                    
                    # For single-word search, simple substring match
                    # For multi-word, check if all words are present
                    if len(search_terms) == 1:
                        matched = search_terms[0] in searchable
                    else:
                        matched = all(term in searchable for term in search_terms)
                    
                    if matched:
                        found = {
                            'space': space,
                            'file_meta': file_meta,
                            'space_id': space_info['space_id']
                        }
                        break
                if found:
                    break
            except Exception:
                continue
        
        if not found:
            return {
                "ok": False,
                "speech": f"Could not find stash file matching '{search}'",
                "error": "File not found"
            }
        
        space = found['space']
        file_meta = found['file_meta']
        space_id = found['space_id']
        file_id = file_meta.get('file_id')
    
    elif space_id and file_id:
        # Direct reference
        space = get_space(space_id)
        stash_file = StashFile(space, file_id=file_id)
        if not stash_file.exists:
            stash_file = StashFile(space, name=file_id)
        if not stash_file.exists:
            return {
                "ok": False,
                "speech": f"File '{file_id}' not found in space",
                "error": "File not found"
            }
        file_meta = stash_file.meta
    else:
        return {
            "ok": False,
            "speech": "Provide space_id+file_id or search term",
            "error": "Missing parameters"
        }
    
    # Build the memory entry
    file_name = file_meta.get('name', 'unknown')
    mime_type = file_meta.get('mime_type', '')
    stash_ref = f"stash://{space_id}/{file_meta.get('file_id')}"
    tags = file_meta.get('tags', [])
    tool_origin = file_meta.get('tool_origin', 'stash')
    
    # Auto-generate key if not provided
    if not key:
        # Create key from filename, removing extension and sanitizing
        base_name = os.path.splitext(file_name)[0]
        key = f"stash_{base_name.replace(' ', '_').replace('-', '_')[:50]}"
    
    # Build value based on file type
    is_text = mime_type.startswith('text/') or mime_type == 'application/json'
    is_pdf = mime_type == 'application/pdf'
    content_truncated = False
    llm_summarized = False
    pdf_extracted = False
    
    if summary:
        # Use provided summary
        value = summary
    elif is_pdf:
        # Extract text from PDF using pdf_read tool
        file_path = space.space_path / file_meta.get('stored_name')
        content = extract_pdf_text(str(file_path))
        
        if content:
            pdf_extracted = True
            # Handle long content (same logic as text)
            if len(content) > 2000:
                if auto_summarize:
                    llm_summary = summarize_content_with_llm(content, file_name)
                    if llm_summary:
                        value = llm_summary
                        llm_summarized = True
                    else:
                        value = f"{content[:2000]}... [truncated]"
                        content_truncated = True
                else:
                    value = f"{content[:2000]}... [truncated]"
                    content_truncated = True
            else:
                value = content
        else:
            # PDF extraction failed
            value = f"PDF file: {file_name} ({format_size(file_meta.get('size_bytes', 0))}) [text extraction failed]"
    elif is_text:
        # Read text content
        file_path = space.space_path / file_meta.get('stored_name')
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Handle long content
            if len(content) > 2000:
                if auto_summarize:
                    # Use LLM to create intelligent summary
                    llm_summary = summarize_content_with_llm(content, file_name)
                    if llm_summary:
                        value = llm_summary
                        llm_summarized = True
                    else:
                        # LLM failed, fallback to truncation
                        value = f"{content[:2000]}... [truncated]"
                        content_truncated = True
                else:
                    # Simple truncation (default)
                    value = f"{content[:2000]}... [truncated]"
                    content_truncated = True
            else:
                value = content
        except Exception as e:
            value = f"[Could not read content: {e}]"
    else:
        # Binary file - save metadata only
        value = f"Binary file: {file_name} ({mime_type}, {format_size(file_meta.get('size_bytes', 0))})"
    
    # Build structured metadata (for db.remember metadata field)
    memory_metadata = {
        "stash_ref": stash_ref,
        "space_id": space_id,
        "file_id": file_meta.get('file_id'),
        "file_name": file_name,
        "mime_type": mime_type,
        "size_bytes": file_meta.get('size_bytes', 0),
        "tags": tags,
        "tool_origin": tool_origin,
        "stash_created_at": file_meta.get('created_at'),
        "content_truncated": content_truncated,
        "llm_summarized": llm_summarized,
        "pdf_extracted": pdf_extracted,
        "is_text": is_text or pdf_extracted,  # True if text or successfully extracted PDF
        "hash_sha256": file_meta.get('hash_sha256')
    }
    
    # Save to memory with proper metadata
    try:
        db = get_memory_db()
        db.remember(
            key=key,
            value=value,
            category=category,
            importance=importance,
            source=f"stash:{space_id}",
            metadata=memory_metadata
        )
        db.close()
    except Exception as e:
        return {
            "ok": False,
            "speech": f"Failed to save to memory: {e}",
            "error": str(e)
        }
    
    return {
        "ok": True,
        "speech": f"Saved '{file_name}' to memory as '{key}'",
        "data": {
            "key": key,
            "category": category,
            "importance": importance,
            "metadata": memory_metadata
        }
    }


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()
        
        # Get action
        action = args.get('action', 'list').lower()
        
        # Dispatch to action handler
        handlers = {
            'open_space': action_open_space,
            'info': action_info,
            'save': action_save,
            'list': action_list,
            'read': action_read,
            'update': action_update,
            'cleanup': action_cleanup,
            'remember': action_remember,
        }
        
        if action not in handlers:
            raise ValueError(f"Unknown action: {action}. Use: {', '.join(handlers.keys())}")
        
        result = handlers[action](args)
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Stash error: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

