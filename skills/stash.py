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
from typing import Dict, Any

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config
from stash_helper import (
    open_space, get_space, list_spaces, cleanup_expired,
    StashFile, StashSpace, get_stash_dir
)


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


def action_open_space(args: Dict) -> Dict:
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


def action_info(args: Dict) -> Dict:
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


def action_save(args: Dict) -> Dict:
    """Save content to stash."""
    space_id = args.get('space_id')
    name = args.get('name')
    kind = args.get('kind', 'text')
    on_conflict = args.get('on_conflict', 'error')
    tags = args.get('tags', [])
    tool_origin = args.get('tool_origin')
    
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
        # URL downloads will be implemented in Phase 2
        raise ValueError("URL downloads not yet implemented. Use kind='text', 'json', or 'base64'")
        
    else:
        raise ValueError(f"Unknown kind: {kind}. Use: text, json, base64, url")
    
    size_str = format_size(result['size_bytes'])
    
    return {
        "ok": True,
        "speech": f"Saved {name} to stash ({size_str})",
        "data": {
            "space_id": space.space_id,
            **result
        }
    }


def action_list(args: Dict) -> Dict:
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


def action_read(args: Dict) -> Dict:
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


def action_update(args: Dict) -> Dict:
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


def action_cleanup(args: Dict) -> Dict:
    """Clean up spaces."""
    space_id = args.get('space_id')
    mode = args.get('mode', 'expired_only')
    
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

