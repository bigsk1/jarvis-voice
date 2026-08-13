#!/usr/bin/env python3
"""
Tool Name: manage_intel
Sandboxed CRUD operations for jarvis-intel/ directory.
Allows Jarvis to programmatically create, read, search, update, replace, and delete intel files.

Input: {
    "action": "create|read|search|update|replace|append|delete|list",
    "path": "flat filename in jarvis-intel/file.md",
    "content": "file content",
    "auto_ingest": true  # Auto-run ingest_intel after changes
}
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json
import hashlib
from pathlib import Path
from typing import Any
import subprocess

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from intel_content import normalize_intel_content
from config_loader import export_config_environment
from intel_filename import (
    filename_from_markdown_title,
    validate_create_filename,
)
from memory_db import MemoryDB
from time_utils import now_local


def _mode_for_db_path(db_path: str) -> str:
    """Infer mode name from the active memory DB path."""
    name = Path(db_path).name
    if name == "jarvis_memory_local.db":
        return "local"
    return "cloud"


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


def get_auto_ingest_plan(project_root: Path, current_mode: str) -> dict[str, Any]:
    """Plan current-mode ingestion plus an already-configured sibling DB.

    The selected mode is always required and may create its own DB on first
    use. A sibling is included only when both its DB and config file already
    exist, so a single-mode install never grows an unused second database.
    """
    current_mode = str(current_mode or "").strip().lower()
    if current_mode not in {"cloud", "local"}:
        return {"ok": False, "error": f"Invalid ingest mode: {current_mode or 'missing'}"}

    config_dir = project_root / "config"
    current_config = config_dir / f"{current_mode}.env"
    if not current_config.is_file():
        return {
            "ok": False,
            "error": f"config/{current_mode}.env not found; {current_mode} ingest was not started",
        }

    data_dir = project_root / "data"
    sibling_mode = "local" if current_mode == "cloud" else "cloud"
    sibling_db = data_dir / (
        "jarvis_memory_local.db" if sibling_mode == "local" else "jarvis_memory.db"
    )
    sibling_config = config_dir / f"{sibling_mode}.env"

    modes = [current_mode]
    skipped_modes = []
    warnings = []
    if sibling_db.is_file():
        if sibling_config.is_file():
            modes.append(sibling_mode)
        else:
            skipped_modes.append(sibling_mode)
            warnings.append(
                f"{sibling_mode} DB exists but config/{sibling_mode}.env is missing; "
                f"skipped {sibling_mode} ingest"
            )

    plan = {
        "ok": True,
        "modes": modes,
        "skipped_modes": skipped_modes,
    }
    if warnings:
        plan["warning"] = " ".join(warnings)
    return plan


def start_auto_ingest(project_root: Path, current_mode: str) -> dict[str, Any]:
    """Start detached mode-aware ingestion and return its preflight plan."""
    plan = get_auto_ingest_plan(project_root, current_mode)
    if not plan.get("ok"):
        return {"started": False, **plan}

    try:
        subprocess.Popen(
            [
                sys.executable,
                str(project_root / "skills" / "manage_intel.py"),
                "--auto-ingest",
                current_mode,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(project_root),
        )
    except OSError as exc:
        return {
            "started": False,
            "ok": False,
            "error": f"Could not start Intel ingestion: {exc}",
            "modes": plan.get("modes", []),
            "skipped_modes": plan.get("skipped_modes", []),
        }

    return {"started": True, **plan}


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


def create_intel_file(
    intel_dir: Path,
    path: str,
    content: str,
    on_conflict: str = "error",
) -> dict[str, Any]:
    """Create a new intel file."""
    file_path = validate_path(path, intel_dir)
    content, content_normalized = normalize_intel_content(content)

    # Add .md extension if missing
    if not file_path.suffix:
        file_path = file_path.with_suffix('.md')
    validate_create_filename(file_path.name)
    requested_file_path = file_path

    if on_conflict not in {"error", "version"}:
        raise ValueError("'on_conflict' must be 'error' or 'version'")

    # Check if file already exists
    if file_path.exists():
        if on_conflict == "error":
            raise ValueError(f"File already exists: {path}. Use 'update' action instead.")
        base_path = file_path
        version = 2
        while file_path.exists():
            file_path = base_path.with_name(
                f"{base_path.stem}-{version}{base_path.suffix}"
            )
            version += 1
    
    # Create parent directories if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write content
    file_path.write_text(content, encoding='utf-8')
    
    return {
        "file": str(file_path.relative_to(intel_dir)),
        "content": content,
        "size_bytes": len(content),
        "created": True,
        "versioned": file_path != requested_file_path,
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


def search_intel_file(
    intel_dir: Path,
    path: str,
    query: str,
    context_lines: int = 5,
    max_matches: int = 20,
) -> dict[str, Any]:
    """Find literal text and return bounded, line-numbered surrounding context."""
    file_path = validate_path(path, intel_dir)
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    if not query:
        raise ValueError("'query' must be non-empty for search")

    context_lines = max(0, min(int(context_lines), 100))
    max_matches = max(1, min(int(max_matches), 100))
    content = file_path.read_text(encoding='utf-8')
    lines = content.splitlines()
    matches = []
    cursor = 0
    total_matches = 0

    while True:
        offset = content.find(query, cursor)
        if offset < 0:
            break
        total_matches += 1
        if len(matches) < max_matches:
            match_start_line = content.count('\n', 0, offset) + 1
            match_end_line = content.count('\n', 0, offset + len(query)) + 1
            start_line = max(1, match_start_line - context_lines)
            end_line = min(len(lines), match_end_line + context_lines)
            excerpt_lines = lines[start_line - 1:end_line]
            matches.append({
                "match_start_line": match_start_line,
                "match_end_line": match_end_line,
                "context_start_line": start_line,
                "context_end_line": end_line,
                "content": "\n".join(excerpt_lines),
                "line_numbered_content": "\n".join(
                    f"{line_no}: {line}"
                    for line_no, line in enumerate(excerpt_lines, start=start_line)
                ),
            })
        cursor = offset + max(1, len(query))

    return {
        "file": str(file_path.relative_to(intel_dir)),
        "query": query,
        "matches": matches,
        "match_count": total_matches,
        "matches_returned": len(matches),
        "matches_truncated": total_matches > len(matches),
        "size_bytes": len(content),
        "line_count": len(lines),
        "file_sha256": hashlib.sha256(content.encode('utf-8')).hexdigest(),
    }


def replace_intel_content(
    intel_dir: Path,
    path: str,
    old_content: str,
    new_content: str = "",
    expected_replacements: int = 1,
    expected_file_sha256: str | None = None,
) -> dict[str, Any]:
    """Replace exact literal content, refusing ambiguous or stale edits."""
    file_path = validate_path(path, intel_dir)
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    if not old_content:
        raise ValueError("'old_content' must be non-empty for replace")

    expected_replacements = int(expected_replacements)
    if expected_replacements < 1:
        raise ValueError("'expected_replacements' must be at least 1")

    existing = file_path.read_text(encoding='utf-8')
    before_sha256 = hashlib.sha256(existing.encode('utf-8')).hexdigest()
    if expected_file_sha256 and expected_file_sha256 != before_sha256:
        raise ValueError(
            "File changed after it was inspected; search/read again before replacing content"
        )

    actual_replacements = existing.count(old_content)
    if actual_replacements != expected_replacements:
        raise ValueError(
            f"Expected {expected_replacements} exact match(es), found {actual_replacements}; "
            "no changes were made"
        )

    updated = existing.replace(old_content, new_content)
    file_path.write_text(updated, encoding='utf-8')
    after_sha256 = hashlib.sha256(updated.encode('utf-8')).hexdigest()
    return {
        "file": str(file_path.relative_to(intel_dir)),
        "updated": True,
        "replacements": actual_replacements,
        "removed": new_content == "",
        "size_bytes_before": len(existing),
        "size_bytes_after": len(updated),
        "bytes_changed": len(updated) - len(existing),
        "file_sha256_before": before_sha256,
        "file_sha256_after": after_sha256,
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
        "content": content,
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
    updated = existing + separator + dated_content + "\n"
    file_path.write_text(updated, encoding='utf-8')
    
    new_size = file_path.stat().st_size
    
    return {
        "file": str(file_path.relative_to(intel_dir)),
        "content": updated,
        "appended_content": dated_content,
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
    cursor.execute("DELETE FROM knowledge_base WHERE source = ?", (f"intel/{filename}",))
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

    plan = get_auto_ingest_plan(project_root, current_mode)
    if not plan.get("ok"):
        return {"ingested": False, "error": plan.get("error", "Ingest preflight failed")}
    modes_to_ingest = plan["modes"]

    mode_results = []
    total_new_files = 0
    total_facts = 0
    warnings = [plan["warning"]] if plan.get("warning") else []

    for index, mode in enumerate(modes_to_ingest):
        try:
            env = export_config_environment(mode)
            result = subprocess.run(
                [sys.executable, str(ingest_script)],
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
                skipped_files = output.get('data', {}).get('skipped_files', 0)
                processed_files = output.get('data', {}).get('processed_files', [])
                total_new_files += new_files
                total_facts += facts
                mode_results.append({
                    "mode": mode,
                    "ok": True,
                    "new_files": new_files,
                    "total_facts": facts,
                    "deleted_files": deleted_files,
                    "deleted_facts": deleted_facts,
                    "skipped_files": skipped_files,
                    "processed_files": processed_files,
                })
            except json.JSONDecodeError:
                mode_results.append({
                    "mode": mode,
                    "ok": True,
                    "raw_output": result.stdout,
                })
        except subprocess.TimeoutExpired:
            error_text = f"{mode} ingest timeout ({per_mode_timeout}s)"
            if index == 0:
                return {"ingested": False, "error": error_text}
            warnings.append(error_text)
            mode_results.append({"mode": mode, "ok": False, "error": error_text})
        except Exception as exc:
            error_text = f"{mode} ingest failed: {str(exc)[:500]}"
            if index == 0:
                return {"ingested": False, "error": error_text}
            warnings.append(error_text)
            mode_results.append({"mode": mode, "ok": False, "error": error_text})

    response = {
        "ingested": True,
        "new_files": total_new_files,
        "total_facts": total_facts,
        "modes": [entry["mode"] for entry in mode_results if entry.get("ok")],
        "results": mode_results,
        "skipped_modes": plan.get("skipped_modes", []),
    }
    if warnings:
        response["warning"] = " ".join(warnings)
        response["failed_modes"] = [entry["mode"] for entry in mode_results if entry.get("ok") is False]
        response["partial"] = True
    return response


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
        
        if action not in ['create', 'read', 'search', 'update', 'replace', 'append', 'delete', 'list']:
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
            if not content:
                raise ValueError("'content' required for create")
            if args.get('filename_from_title'):
                path = filename_from_markdown_title(
                    content,
                    prefix=args.get('filename_prefix', 'intel'),
                )
            if not path:
                raise ValueError(
                    "'path' required for create unless filename_from_title=true"
                )

            result_data = create_intel_file(
                intel_dir,
                path,
                content,
                on_conflict=args.get('on_conflict', 'error'),
            )
            speech = f"Created intel file: {result_data['file']}"
        
        elif action == 'read':
            path = args.get('path')
            if not path:
                raise ValueError("'path' required for read")
            
            result_data = read_intel_file(intel_dir, path)
            speech = f"Read {result_data['size_bytes']} bytes from {result_data['file']}"

        elif action == 'search':
            path = args.get('path')
            query = args.get('query')
            if not path or not query:
                raise ValueError("'path' and non-empty 'query' required for search")

            result_data = search_intel_file(
                intel_dir,
                path,
                query,
                context_lines=args.get('context_lines', 5),
                max_matches=args.get('max_matches', 20),
            )
            speech = (
                f"Found {result_data['match_count']} exact match"
                f"{'es' if result_data['match_count'] != 1 else ''} in {result_data['file']}"
            )
        
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

        elif action == 'replace':
            path = args.get('path')
            old_content = args.get('old_content')
            if not path or not old_content:
                raise ValueError("'path' and non-empty 'old_content' required for replace")

            result_data = replace_intel_content(
                intel_dir,
                path,
                old_content,
                args.get('new_content', ''),
                expected_replacements=args.get('expected_replacements', 1),
                expected_file_sha256=args.get('expected_file_sha256'),
            )
            verb = "Removed" if result_data['removed'] else "Replaced"
            speech = (
                f"{verb} {result_data['replacements']} exact content block"
                f"{'s' if result_data['replacements'] != 1 else ''} in {result_data['file']}"
            )
        
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
        if args.get('auto_ingest', False) and action in ['create', 'update', 'replace', 'append', 'delete']:
            current_mode = _mode_for_db_path(getattr(db, "db_path", ""))
            ingest_result = auto_ingest(project_root, current_mode)
            result_data['ingest'] = ingest_result
            
            if ingest_result.get('ingested'):
                speech += f". {format_ingest_summary(ingest_result)}"
            else:
                speech += f". Warning: Ingest failed - {ingest_result.get('error', 'unknown error')}"

        result_data.setdefault('action', action)
        
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
    if len(sys.argv) == 3 and sys.argv[1] == "--auto-ingest":
        internal_result = auto_ingest(Path(__file__).parent.parent.resolve(), sys.argv[2])
        print(json.dumps(internal_result))
        sys.exit(0 if internal_result.get("ingested") else 1)
    main()
