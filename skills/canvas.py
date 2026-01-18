#!/usr/bin/env python3
"""
Canvas Tool - Create and manage pages in Jarvis Canvas viewer.

Input: { 
    "action": "create|update|delete|list|open",
    "title": "Page Title",
    "content": "Markdown content",
    "tags": ["tag1", "tag2"],
    "page_id": "page_20241201_143022"  # for update/delete
}
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json
import subprocess
import webbrowser
from typing import Dict, Any, Optional, List
from datetime import datetime

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value

# Constants
CANVAS_URL = "http://localhost:8890"
CANVAS_API = f"{CANVAS_URL}/api"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANVAS_DIR = os.path.join(PROJECT_ROOT, "data", "canvas")


def check_canvas_health() -> bool:
    """Check if canvas server is running."""
    try:
        import urllib.request
        req = urllib.request.Request(f"{CANVAS_API}/health", method='GET')
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def api_request(method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
    """Make API request to canvas server."""
    import urllib.request
    import urllib.error
    
    url = f"{CANVAS_API}{endpoint}"
    
    req = urllib.request.Request(url, method=method)
    req.add_header('Content-Type', 'application/json')
    
    body = None
    if data:
        body = json.dumps(data).encode('utf-8')
    
    try:
        with urllib.request.urlopen(req, body, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        try:
            return json.loads(error_body)
        except:
            return {"error": f"HTTP {e.code}: {error_body}"}
    except urllib.error.URLError as e:
        return {"error": f"Connection failed: {e.reason}"}


def save_to_memory(page: Dict[str, Any]) -> None:
    """Save page reference to Jarvis memory."""
    try:
        from memory_db import MemoryDB
        db = MemoryDB()
        
        # Create a memory entry for this canvas page
        key = f"canvas_page_{page['id']}"
        tags = page.get('tags', [])
        value = f"Canvas page '{page['title']}' - {', '.join(tags)}. View at {CANVAS_URL}"
        
        # Build metadata
        metadata = {
            "page_id": page['id'],
            "tags": tags,
            "url": CANVAS_URL,
            "created": page.get('created'),
            "source_query": page.get('source_query')
        }
        
        db.remember(
            key=key,
            value=value,
            category="canvas",
            importance=6,
            source="user_conversation",
            metadata=metadata
        )
    except Exception as e:
        # Non-fatal - just log
        print(f"Warning: Could not save to memory: {e}", file=sys.stderr)


def remove_from_memory(page_id: str) -> None:
    """Remove page reference from Jarvis memory."""
    try:
        from memory_db import MemoryDB
        db = MemoryDB()
        
        key = f"canvas_page_{page_id}"
        db.forget(key)
    except Exception:
        pass  # Non-fatal


def create_page(title: str, content: str, tags: List[str] = None, 
                source_query: str = None, pinned: bool = False) -> Dict[str, Any]:
    """Create a new canvas page."""
    
    # Check if server is running
    if not check_canvas_health():
        return {
            "ok": False,
            "error": "Canvas server not running",
            "speech": "Canvas isn't running right now. Start it with jarvis-canvas command."
        }
    
    # Fix LLM escape sequences - convert literal \n to actual newlines
    if content:
        content = content.replace('\\n', '\n')
    
    data = {
        "title": title,
        "content": content,
        "tags": tags or [],
        "source_query": source_query,
        "pinned": pinned
    }
    
    result = api_request('POST', '/pages', data)
    
    if 'error' in result:
        return {
            "ok": False,
            "error": result['error'],
            "speech": f"Couldn't create page: {result['error']}"
        }
    
    # Save to memory
    save_to_memory(result)
    
    return {
        "ok": True,
        "speech": f"I've saved '{title}' to your canvas. Take a look when you're ready.",
        "data": {
            "page_id": result['id'],
            "title": result['title'],
            "url": CANVAS_URL,
            "tags": result.get('tags', [])
        }
    }


def update_page(page_id: str, title: str = None, content: str = None, 
                tags: List[str] = None, pinned: bool = None) -> Dict[str, Any]:
    """Update an existing canvas page."""
    
    if not check_canvas_health():
        return {
            "ok": False,
            "error": "Canvas server not running",
            "speech": "Canvas isn't running right now."
        }
    
    data = {}
    if title is not None:
        data['title'] = title
    if content is not None:
        data['content'] = content
    if tags is not None:
        data['tags'] = tags
    if pinned is not None:
        data['pinned'] = pinned
    
    result = api_request('PUT', f'/pages/{page_id}', data)
    
    if 'error' in result:
        return {
            "ok": False,
            "error": result['error'],
            "speech": f"Couldn't update page: {result['error']}"
        }
    
    # Update memory
    save_to_memory(result)
    
    return {
        "ok": True,
        "speech": f"Updated '{result['title']}' in your canvas.",
        "data": result
    }


def delete_page(page_id: str) -> Dict[str, Any]:
    """Delete a canvas page."""
    
    if not check_canvas_health():
        return {
            "ok": False,
            "error": "Canvas server not running",
            "speech": "Canvas isn't running right now."
        }
    
    result = api_request('DELETE', f'/pages/{page_id}')
    
    if 'error' in result:
        return {
            "ok": False,
            "error": result['error'],
            "speech": f"Couldn't delete page: {result['error']}"
        }
    
    # Remove from memory
    remove_from_memory(page_id)
    
    return {
        "ok": True,
        "speech": "Page deleted from canvas.",
        "data": {"deleted": page_id}
    }


def list_pages(limit: int = 10) -> Dict[str, Any]:
    """List all canvas pages."""
    
    if not check_canvas_health():
        return {
            "ok": False,
            "error": "Canvas server not running",
            "speech": "Canvas isn't running right now."
        }
    
    pages = api_request('GET', '/pages')
    
    if isinstance(pages, dict) and 'error' in pages:
        return {
            "ok": False,
            "error": pages['error'],
            "speech": f"Couldn't list pages: {pages['error']}"
        }
    
    if not pages:
        return {
            "ok": True,
            "speech": "Your canvas is empty. Ask me to save something there!",
            "data": {"pages": [], "count": 0}
        }
    
    # Summarize pages
    page_list = pages[:limit]
    summary = [f"'{p['title']}'" for p in page_list]
    
    speech = f"You have {len(pages)} page{'s' if len(pages) != 1 else ''} in your canvas"
    if len(pages) <= 3:
        speech += f": {', '.join(summary)}."
    else:
        speech += f". Recent ones: {', '.join(summary[:3])}."
    
    return {
        "ok": True,
        "speech": speech,
        "data": {
            "pages": page_list,
            "count": len(pages),
            "url": CANVAS_URL
        }
    }


def open_canvas() -> Dict[str, Any]:
    """Return the canvas URL (user opens browser manually)."""
    
    health = check_canvas_health()
    
    if not health:
        return {
            "ok": False,
            "error": "Canvas server not running",
            "speech": "Canvas isn't running. Start it with the jarvis-canvas command, then visit localhost 8890."
        }
    
    return {
        "ok": True,
        "speech": f"Canvas is running at localhost 8890.",
        "data": {
            "url": CANVAS_URL,
            "status": "running"
        }
    }


def read_page(page_id: str = None, search: str = None) -> Dict[str, Any]:
    """Read a canvas page content. Can find by ID or search by title/content.
    
    Useful for:
    - Verifying a page was created correctly
    - Reading back content for troubleshooting
    - Finding pages by keyword
    """
    
    # Try Canvas server API first
    if check_canvas_health():
        if page_id:
            result = api_request('GET', f'/pages/{page_id}')
            if 'error' not in result:
                return {
                    "ok": True,
                    "speech": f"Here's the canvas page '{result.get('title', 'Untitled')}'.",
                    "data": {
                        "page_id": result.get('id'),
                        "title": result.get('title'),
                        "content": result.get('content', ''),
                        "tags": result.get('tags', []),
                        "created": result.get('created'),
                        "content_length": len(result.get('content', ''))
                    }
                }
    
    # Fallback to direct file access
    if not os.path.exists(CANVAS_DIR):
        return {
            "ok": False,
            "error": "Canvas directory not found",
            "speech": "Couldn't find any canvas pages."
        }
    
    # If page_id provided, try direct file read
    if page_id:
        # Handle various ID formats
        if not page_id.startswith("page_"):
            page_id = f"page_{page_id}"
        filename = f"{page_id}.json" if not page_id.endswith(".json") else page_id
        filepath = os.path.join(CANVAS_DIR, filename)
        
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                return {
                    "ok": True,
                    "speech": f"Here's the canvas page '{data.get('title', 'Untitled')}'.",
                    "data": {
                        "page_id": data.get('id'),
                        "title": data.get('title'),
                        "content": data.get('content', ''),
                        "tags": data.get('tags', []),
                        "created": data.get('created'),
                        "content_length": len(data.get('content', ''))
                    }
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": f"Failed to read page: {e}",
                    "speech": f"Couldn't read that page: {e}"
                }
        else:
            return {
                "ok": False,
                "error": f"Page not found: {page_id}",
                "speech": f"I couldn't find a page with ID {page_id}."
            }
    
    # Search by keyword if no page_id
    if search:
        search_lower = search.lower()
        matches = []
        
        for filename in os.listdir(CANVAS_DIR):
            if filename.startswith("page_") and filename.endswith(".json"):
                filepath = os.path.join(CANVAS_DIR, filename)
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    title = data.get('title', '').lower()
                    content = data.get('content', '').lower()
                    
                    if search_lower in title or search_lower in content:
                        matches.append({
                            "page_id": data.get('id'),
                            "title": data.get('title'),
                            "content": data.get('content', ''),
                            "tags": data.get('tags', []),
                            "created": data.get('created'),
                            "content_length": len(data.get('content', ''))
                        })
                except:
                    continue
        
        if not matches:
            return {
                "ok": True,
                "speech": f"No canvas pages found matching '{search}'.",
                "data": {"matches": [], "count": 0}
            }
        
        # Sort by created date, newest first
        matches.sort(key=lambda x: x.get('created', ''), reverse=True)
        
        if len(matches) == 1:
            return {
                "ok": True,
                "speech": f"Found one page: '{matches[0]['title']}'.",
                "data": matches[0]
            }
        else:
            return {
                "ok": True,
                "speech": f"Found {len(matches)} pages matching '{search}'. Most recent: '{matches[0]['title']}'.",
                "data": {
                    "matches": matches[:5],  # Return top 5
                    "count": len(matches),
                    "most_recent": matches[0]
                }
            }
    
    # No page_id or search - get most recent page
    pages = []
    for filename in os.listdir(CANVAS_DIR):
        if filename.startswith("page_") and filename.endswith(".json"):
            filepath = os.path.join(CANVAS_DIR, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                pages.append(data)
            except:
                continue
    
    if not pages:
        return {
            "ok": True,
            "speech": "Your canvas is empty.",
            "data": {"pages": [], "count": 0}
        }
    
    # Sort and return most recent
    pages.sort(key=lambda x: x.get('created', ''), reverse=True)
    latest = pages[0]
    
    return {
        "ok": True,
        "speech": f"Your most recent canvas page is '{latest.get('title')}'.",
        "data": {
            "page_id": latest.get('id'),
            "title": latest.get('title'),
            "content": latest.get('content', ''),
            "tags": latest.get('tags', []),
            "created": latest.get('created'),
            "content_length": len(latest.get('content', ''))
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
        
        action = args.get('action', 'create')
        
        if action == 'create':
            title = args.get('title')
            content = args.get('content', '')
            tags = args.get('tags', [])
            source_query = args.get('source_query')
            pinned = args.get('pinned', False)
            
            if not title:
                raise ValueError("title is required for create action")
            
            result = create_page(title, content, tags, source_query, pinned)
        
        elif action == 'update':
            page_id = args.get('page_id')
            if not page_id:
                raise ValueError("page_id is required for update action")
            
            result = update_page(
                page_id,
                title=args.get('title'),
                content=args.get('content'),
                tags=args.get('tags'),
                pinned=args.get('pinned')
            )
        
        elif action == 'delete':
            page_id = args.get('page_id')
            if not page_id:
                raise ValueError("page_id is required for delete action")
            
            result = delete_page(page_id)
        
        elif action == 'list':
            limit = args.get('limit', 10)
            result = list_pages(limit)
        
        elif action == 'open':
            result = open_canvas()
        
        elif action == 'read':
            page_id = args.get('page_id')
            search = args.get('search')
            result = read_page(page_id=page_id, search=search)
        
        else:
            raise ValueError(f"Unknown action: {action}. Use: create, update, delete, list, open, read")
        
        print(json.dumps(result))
        
        if not result.get('ok'):
            sys.exit(1)
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Canvas error: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

