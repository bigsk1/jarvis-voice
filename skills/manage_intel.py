#!/usr/bin/env python3
"""
Tool Name: manage_intel
Sandboxed CRUD operations for jarvis-intel/ directory.
Allows Jarvis to programmatically create, read, update, and delete intel files.

Input: {
    "action": "create|read|update|delete|list",
    "path": "flat filename in jarvis-intel/file.md",
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
from intel_content import normalize_intel_content
from memory_db import MemoryDB
from time_utils import now_local


def _mode_for_db_path(db_path: str) -> str:
    """Infer mode name from the active memory DB path."""
    name = Path(db_path).name
    if name == "jarvis_memory_local.db":
        return "local"
    return "cloud"


def _llm_provider_for_mode(mode: str) -> str:
    """Map memory mode to the embedding provider selection used by MemoryDB."""
    return "ollama" if mode == "local" else "anthropic"


def _format_mode_list(modes: list[str]) -> str:
    """Render mode names naturally for status messages."""
    if not modes:
        return "no modes"
    if len(modes) == 1:
        return modes[0]
    if len(modes) == 2:
        return f"{modes[0]} and {modes[1]}"
    return f"{', '.join(modes[:-1])}, and {modes[-1]}"


def format_ingest_summary(ingest_result: dict[str, Any]) -> str:
    """Build a user-facing ingest summary that explains cross-DB totals."""
    modes = ingest_result.get("modes", [])
    total_new_files = ingest_result.get("new_files", 0)
    total_facts = ingest_result.get("total_facts", 0)
    mode_label = _format_mode_list(modes)

    summary = (
        f"Intel ingest complete for {mode_label}. "
        f"Processed {total_new_files} changed file update"
    )
    if total_new_files != 1:
        summary += "s"
    summary += f" and {total_facts} total fact"
    if total_facts != 1:
        summary += "s"
    if len(modes) > 1:
        summary += " across both DBs."
    else:
        summary += "."

    if ingest_result.get("warning"):
        summary += f" Warning: {ingest_result['warning']}"

    return summary


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
    content, content_normalized = normalize_intel_content(content)
    
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
        "created": True,
        "content_normalized": content_normalized
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
    content, content_normalized = normalize_intel_content(content)
    
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
        "updated": True,
        "content_normalized": content_normalized
    }


def append_intel_file(intel_dir: Path, path: str, content: str) -> dict[str, Any]:
    """Append content to an existing intel file. Safe — can only add, never overwrite."""
    file_path = validate_path(path, intel_dir)
    content, content_normalized = normalize_intel_content(content)
    
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
    
    # Preserve markdown structure for append-heavy intel files.
    # Inline timestamp prefixes break headings like "## Section" and make
    # seasonal logs / inventories harder to ingest cleanly later.
    date_stamp = now_local().strftime("%Y-%m-%d %H:%M %Z")
    if _should_preserve_block_structure(content):
        dated_content = f"[{date_stamp}]\n{content}"
    else:
        dated_content = f"[{date_stamp}] {content}"
    
    # Append new content
    file_path.write_text(existing + separator + dated_content + "\n", encoding='utf-8')
    
    new_size = file_path.stat().st_size
    
    return {
        "file": str(file_path.relative_to(intel_dir)),
        "size_bytes": new_size,
        "appended_bytes": len(content),
        "appended": True,
        "content_normalized": content_normalized
    }


def _should_preserve_block_structure(content: str) -> bool:
    """
    Decide whether appended content should keep its own line structure.

    Structured markdown blocks like headings, bullets, numbered items, and
    multiline notes should not be forced onto the same line as the timestamp.
    """
    stripped = content.lstrip()
    if not stripped:
        return False

    if "\n" in stripped:
        return True

    if stripped.startswith(("#", "-", "*", ">")):
        return True

    if len(stripped) >= 3 and stripped[0].isdigit() and ". " in stripped[:4]:
        return True

    return False


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


def auto_ingest(project_root: Path, current_mode: str) -> dict[str, Any]:
    """Run ingest_intel sequentially for current mode and existing sibling DB."""
    per_mode_timeout = 300
    ingest_script = project_root / 'skills' / 'ingest_intel.py'
    
    if not ingest_script.exists():
        return {"ingested": False, "error": "ingest_intel.py not found"}

    data_dir = project_root / 'data'
    db_paths = {
        "cloud": data_dir / "jarvis_memory.db",
        "local": data_dir / "jarvis_memory_local.db",
    }
    sibling_mode = "local" if current_mode == "cloud" else "cloud"

    modes_to_ingest = [current_mode]
    if db_paths[sibling_mode].exists():
        modes_to_ingest.append(sibling_mode)

    mode_results = []
    total_new_files = 0
    total_facts = 0
    warnings = []
    
    try:
        for index, mode in enumerate(modes_to_ingest):
            env = os.environ.copy()
            env["LLM_PROVIDER"] = _llm_provider_for_mode(mode)
            result = subprocess.run(
                ['python3', str(ingest_script)],
                capture_output=True,
                text=True,
                timeout=per_mode_timeout,
                env=env,
            )

            if result.returncode != 0:
                error_text = result.stderr or result.stdout
                if index == 0:
                    return {
                        "ingested": False,
                        "error": f"{mode} ingest failed: {error_text}"
                    }

                warnings.append(f"{mode} ingest failed: {error_text}")
                mode_results.append({
                    "mode": mode,
                    "ok": False,
                    "error": error_text,
                })
                continue

            try:
                output = json.loads(result.stdout)
                new_files = output.get('data', {}).get('new_files', 0)
                facts = output.get('data', {}).get('total_facts', 0)
                deleted_files = output.get('data', {}).get('deleted_files', 0)
                deleted_facts = output.get('data', {}).get('deleted_facts', 0)
                total_new_files += new_files
                total_facts += facts
                mode_results.append({
                    "mode": mode,
                    "ok": True,
                    "new_files": new_files,
                    "total_facts": facts,
                    "deleted_files": deleted_files,
                    "deleted_facts": deleted_facts,
                })
            except json.JSONDecodeError:
                mode_results.append({
                    "mode": mode,
                    "ok": True,
                    "raw_output": result.stdout,
                })

        response = {
            "ingested": True,
            "new_files": total_new_files,
            "total_facts": total_facts,
            "modes": [entry["mode"] for entry in mode_results if entry.get("ok")],
            "results": mode_results,
        }
        if warnings:
            response["warning"] = " ".join(warnings)
            response["failed_modes"] = [entry["mode"] for entry in mode_results if entry.get("ok") is False]
            response["partial"] = True
        return response
    except subprocess.TimeoutExpired:
        return {"ingested": False, "error": f"Ingest timeout ({per_mode_timeout}s per mode)"}
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
            current_mode = _mode_for_db_path(getattr(db, "db_path", ""))
            ingest_result = auto_ingest(project_root, current_mode)
            result_data['ingest'] = ingest_result
            
            if ingest_result.get('ingested'):
                speech += f". {format_ingest_summary(ingest_result)}"
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
