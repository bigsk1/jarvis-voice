#!/usr/bin/env python3
"""
Tool Name: manage_intel
Sandboxed CRUD operations for jarvis-intel/ directory.
Allows Jarvis to programmatically create, read, update, and delete intel files.

Input: {
    "action": "create|read|update|delete|list",
    "path": "relative/path/in/jarvis-intel/file.md",
    "content": "file content",
    "auto_ingest": true  # Auto-run ingest_intel after changes
}
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json
from pathlib import Path
from typing import Any
import subprocess

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from memory_db import MemoryDB


def validate_path(path: str, intel_dir: Path) -> Path:
    """
    Validate and sanitize file path to ensure it's within jarvis-intel/.
    Prevents path traversal attacks and subdirectories.
    """
    # Normalize path
    path = path.strip().lstrip('/')
    
    # CRITICAL: Reject paths with subdirectories
    # jarvis-intel/ should be FLAT for simple ingestion
    if '/' in path or '\\' in path:
        raise ValueError(
            f"Subdirectories not allowed in jarvis-intel/. "
            f"Use flat filenames only (e.g., 'bitcoin-price-2025-11-19.md' not 'bitcoin/price-note.md')"
        )
    
    # Resolve full path
    full_path = (intel_dir / path).resolve()
    
    # Ensure it's within jarvis-intel/
    if not str(full_path).startswith(str(intel_dir.resolve())):
        raise ValueError(f"Path must be within jarvis-intel/ directory")
    
    # Only allow .md and .txt files
    if full_path.suffix not in ['.md', '.txt', '']:
        raise ValueError(f"Only .md and .txt files allowed")
    
    # Don't allow modifying README.md
    if full_path.name == 'README.md':
        raise ValueError("Cannot modify README.md")
    
    return full_path


def create_intel_file(intel_dir: Path, path: str, content: str) -> dict[str, Any]:
    """Create a new intel file."""
    file_path = validate_path(path, intel_dir)
    
    # Add .md extension if missing
    if not file_path.suffix:
        file_path = file_path.with_suffix('.md')
    
    # Check if file already exists
    if file_path.exists():
        raise ValueError(f"File already exists: {path}. Use 'update' action instead.")
    
    # Create parent directories if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write content
    file_path.write_text(content, encoding='utf-8')
    
    return {
        "file": str(file_path.relative_to(intel_dir)),
        "size_bytes": len(content),
        "created": True
    }


def read_intel_file(intel_dir: Path, path: str) -> dict[str, Any]:
    """Read an intel file."""
    file_path = validate_path(path, intel_dir)
    
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    
    content = file_path.read_text(encoding='utf-8')
    
    return {
        "file": str(file_path.relative_to(intel_dir)),
        "content": content,
        "size_bytes": len(content),
        "modified": file_path.stat().st_mtime
    }


def update_intel_file(intel_dir: Path, path: str, content: str) -> dict[str, Any]:
    """Update an existing intel file."""
    file_path = validate_path(path, intel_dir)
    
    # Add .md extension if missing
    if not file_path.suffix:
        file_path = file_path.with_suffix('.md')
    
    if not file_path.exists():
        raise ValueError(f"File not found: {path}. Use 'create' action instead.")
    
    # Write content
    file_path.write_text(content, encoding='utf-8')
    
    return {
        "file": str(file_path.relative_to(intel_dir)),
        "size_bytes": len(content),
        "updated": True
    }


def append_intel_file(intel_dir: Path, path: str, content: str) -> dict[str, Any]:
    """Append content to an existing intel file. Safe — can only add, never overwrite."""
    from datetime import datetime
    
    file_path = validate_path(path, intel_dir)
    
    # Add .md extension if missing
    if not file_path.suffix:
        file_path = file_path.with_suffix('.md')
    
    if not file_path.exists():
        raise ValueError(f"File not found: {path}. Use 'create' action instead.")
    
    # Read existing content
    existing = file_path.read_text(encoding='utf-8')
    
    # Ensure separation
    separator = "\n\n" if not existing.endswith("\n\n") else ""
    if existing.endswith("\n"):
        separator = "\n"
    
    # Prepend date stamp to the content
    date_stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    dated_content = f"[{date_stamp}] {content}"
    
    # Append new content
    file_path.write_text(existing + separator + dated_content + "\n", encoding='utf-8')
    
    new_size = file_path.stat().st_size
    
    return {
        "file": str(file_path.relative_to(intel_dir)),
        "size_bytes": new_size,
        "appended_bytes": len(content),
        "appended": True
    }


def delete_intel_file(intel_dir: Path, path: str, db: MemoryDB) -> dict[str, Any]:
    """
    Delete an intel file and remove its facts from memory.
    """
    file_path = validate_path(path, intel_dir)
    
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    
    filename = file_path.name
    
    # Remove associated memories from database
    cursor = db.conn.cursor()
    cursor.execute("DELETE FROM knowledge_base WHERE source LIKE ?", (f"intel/{filename}",))
    deleted_facts = cursor.rowcount
    db.conn.commit()
    
    # Also remove hash tracking for this file
    cursor.execute(
        "DELETE FROM knowledge_base WHERE category = 'system' AND key = ?",
        (f"intel_hash_{filename}",)
    )
    db.conn.commit()
    
    # Delete the file
    file_path.unlink()
    
    return {
        "file": str(file_path.relative_to(intel_dir)),
        "deleted": True,
        "facts_removed": deleted_facts
    }


def list_intel_files(intel_dir: Path, pattern: str = "*") -> dict[str, Any]:
    """List intel files (excluding README.md)."""
    md_files = list(intel_dir.glob(f"**/{pattern}.md"))
    txt_files = list(intel_dir.glob(f"**/{pattern}.txt"))
    
    files = md_files + txt_files
    files = [f for f in files if f.name != 'README.md']
    
    file_list = []
    for file_path in sorted(files):
        rel_path = file_path.relative_to(intel_dir)
        stat = file_path.stat()
        file_list.append({
            "path": str(rel_path),
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime
        })
    
    return {
        "files": file_list,
        "count": len(file_list)
    }


def auto_ingest(project_root: Path) -> dict[str, Any]:
    """Run ingest_intel tool to update memory."""
    ingest_script = project_root / 'skills' / 'ingest_intel.py'
    
    if not ingest_script.exists():
        return {"ingested": False, "error": "ingest_intel.py not found"}
    
    try:
        result = subprocess.run(
            ['python3', str(ingest_script)],
            capture_output=True,
            text=True,
            timeout=180
        )
        
        if result.returncode == 0:
            # Parse output
            try:
                output = json.loads(result.stdout)
                return {
                    "ingested": True,
                    "new_files": output.get('data', {}).get('new_files', 0),
                    "total_facts": output.get('data', {}).get('total_facts', 0)
                }
            except json.JSONDecodeError:
                return {"ingested": True, "raw_output": result.stdout}
        else:
            return {
                "ingested": False,
                "error": result.stderr or result.stdout
            }
    except subprocess.TimeoutExpired:
        return {"ingested": False, "error": "Ingest timeout (180s)"}
    except Exception as e:
        return {"ingested": False, "error": str(e)}


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Validate required parameters
        action = args.get('action')
        if not action:
            raise ValueError("'action' parameter required")
        
        if action not in ['create', 'read', 'update', 'append', 'delete', 'list']:
            raise ValueError(f"Invalid action: {action}")
        
        # Get project paths (resolve to handle symlinks and .. in path)
        project_root = Path(__file__).parent.parent.resolve()
        intel_dir = (project_root / 'jarvis-intel').resolve()
        
        if not intel_dir.exists():
            raise ValueError("jarvis-intel/ directory not found")
        
        # Initialize database
        db = MemoryDB()
        
        # Execute action
        result_data = {}
        
        if action == 'create':
            path = args.get('path')
            content = args.get('content')
            if not path or not content:
                raise ValueError("'path' and 'content' required for create")
            
            result_data = create_intel_file(intel_dir, path, content)
            speech = f"Created intel file: {result_data['file']}"
        
        elif action == 'read':
            path = args.get('path')
            if not path:
                raise ValueError("'path' required for read")
            
            result_data = read_intel_file(intel_dir, path)
            speech = f"Read {result_data['size_bytes']} bytes from {result_data['file']}"
        
        elif action == 'update':
            path = args.get('path')
            content = args.get('content')
            if not path or not content:
                raise ValueError("'path' and 'content' required for update")
            
            result_data = update_intel_file(intel_dir, path, content)
            speech = f"Updated intel file: {result_data['file']}"
        
        elif action == 'append':
            path = args.get('path')
            content = args.get('content')
            if not path or not content:
                raise ValueError("'path' and 'content' required for append")
            
            result_data = append_intel_file(intel_dir, path, content)
            speech = f"Appended to intel file: {result_data['file']}"
        
        elif action == 'delete':
            path = args.get('path')
            if not path:
                raise ValueError("'path' required for delete")
            
            result_data = delete_intel_file(intel_dir, path, db)
            speech = f"Deleted {result_data['file']}, removed {result_data['facts_removed']} facts from memory"
        
        elif action == 'list':
            pattern = args.get('pattern', '*')
            result_data = list_intel_files(intel_dir, pattern)
            if result_data['count'] == 0:
                speech = "No intel files found"
            else:
                speech = f"Found {result_data['count']} intel file"
                if result_data['count'] != 1:
                    speech += "s"
        
        # Auto-ingest if requested and action modifies files
        if args.get('auto_ingest', False) and action in ['create', 'update', 'append', 'delete']:
            ingest_result = auto_ingest(project_root)
            result_data['ingest'] = ingest_result
            
            if ingest_result.get('ingested'):
                speech += f". Ingested {ingest_result.get('new_files', 0)} file(s), {ingest_result.get('total_facts', 0)} facts."
            else:
                speech += f". Warning: Ingest failed - {ingest_result.get('error', 'unknown error')}"
        
        # Success response
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": result_data
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to manage intel: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

