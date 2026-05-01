#!/usr/bin/env python3
"""
Jarvis Skill: Ingest Intel Files
Processes files from jarvis-intel/ and saves to memory.
"""

import sys
import json
import os
from pathlib import Path
from typing import Any
import hashlib

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from intel_content import normalize_intel_content
from memory_db import MemoryDB
from time_utils import format_utc_z, now_utc


def return_success(speech: str, data: dict[str, Any] = None):
    """Return success response."""
    print(json.dumps({
        "ok": True,
        "speech": speech,
        "data": data or {}
    }))


def return_error(error: str):
    """Return error response."""
    print(json.dumps({
        "ok": False,
        "error": error,
        "speech": f"Error ingesting intel: {error}"
    }))


def get_file_hash(filepath: Path) -> str:
    """Generate hash of file content for deduplication."""
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def extract_facts_from_content(content: str, filename: str) -> list[dict[str, str]]:
    """
    Extract structured facts from file content.
    Uses simple heuristics to identify key information.
    
    Returns list of facts: [{"key": "...", "value": "...", "category": "..."}]
    """
    content, _ = normalize_intel_content(content)
    facts = []
    lines = content.split('\n')
    
    current_section = filename.replace('.txt', '').replace('.md', '').replace('_', ' ').title()
    
    for line in lines:
        line = line.strip()
        
        # Update section from headers (but also save header as fact if it has info)
        if line.startswith('#'):
            header_text = line.lstrip('#').strip()
            
            # If header has substantial content (not just a title), save it as a fact
            if len(header_text) > 10 and not header_text.endswith(':'):
                # Determine category
                category = "technical"
                if any(keyword in header_text.lower() for keyword in ['ip', 'host', 'server', 'network', 'vlan', 'vram', 'gpu', 'rtx']):
                    category = "network"
                elif any(keyword in header_text.lower() for keyword in ['password', 'key', 'secret', 'token']):
                    category = "credentials"
                elif any(keyword in header_text.lower() for keyword in ['project', 'repo', 'code']):
                    category = "project"
                
                facts.append({
                    "key": f"{current_section} info",
                    "value": header_text,
                    "category": category,
                    "source": f"intel/{filename}"
                })
            
            # Update current section for subsequent lines
            current_section = header_text
            continue
        
        if not line:
            continue
        
        # Detect key-value patterns
        if ':' in line or '=' in line:
            separator = ':' if ':' in line else '='
            parts = line.split(separator, 1)
            if len(parts) == 2:
                key = parts[0].strip().strip('-*•')
                value = parts[1].strip()
                
                if value:  # Skip empty values
                    # Determine category from content
                    category = "technical"
                    if any(keyword in key.lower() or keyword in value.lower() for keyword in ['ip', 'host', 'server', 'network', 'vlan', 'vram', 'gpu', 'rtx']):
                        category = "network"
                    elif any(keyword in key.lower() for keyword in ['password', 'key', 'secret', 'token']):
                        category = "credentials"
                    elif any(keyword in key.lower() for keyword in ['project', 'repo', 'code']):
                        category = "project"
                    
                    facts.append({
                        "key": f"{current_section} - {key}",
                        "value": value,
                        "category": category,
                        "source": f"intel/{filename}"
                    })
        
        # Detect bullet points with information
        elif line.startswith(('-', '*', '•')) or (line and line[0].isdigit() and '. ' in line):
            content_part = line.lstrip('-*•0123456789. ').strip()
            if content_part and len(content_part) > 5:  # Skip very short lines
                # Determine category
                category = "technical"
                if any(keyword in content_part.lower() for keyword in ['ip', 'host', 'server', 'network', 'vlan', 'vram', 'gpu', 'rtx']):
                    category = "network"
                
                facts.append({
                    "key": f"{current_section} note",
                    "value": content_part,
                    "category": category,
                    "source": f"intel/{filename}"
                })
    
    return facts


def run_async_ingest():
    """Spawn ingestion as background process and return immediately."""
    import subprocess
    
    script_path = Path(__file__).resolve()
    
    # Start subprocess with --sync flag to run actual ingestion
    subprocess.Popen(
        ['python3', str(script_path), '--sync'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True  # Detach from parent process
    )
    
    return_success(
        "Intel ingestion started in background. Facts will be available shortly.",
        {"async": True, "status": "started"}
    )
    return 0


def main():
    """Ingest intel files from jarvis-intel/ folder."""
    try:
        # Parse arguments
        args = {}
        if len(sys.argv) > 1:
            if sys.argv[1] == '--sync':
                # Called by async subprocess - run synchronously
                pass
            else:
                try:
                    args = json.loads(sys.argv[1])
                except json.JSONDecodeError:
                    pass
        
        # Check for async mode
        if args.get('async', False):
            return run_async_ingest()
        
        # Get project root
        project_root = Path(__file__).parent.parent
        intel_dir = project_root / "jarvis-intel"
        
        if not intel_dir.exists():
            return_error("jarvis-intel folder not found")
            return 1
        
        # Find all .txt and .md files
        files = list(intel_dir.glob("*.txt")) + list(intel_dir.glob("*.md"))
        files = [f for f in files if f.name != "README.md"]  # Skip README
        
        if not files:
            return_success(
                "No intel files found. Add .txt or .md files to jarvis-intel folder.",
                {"files_found": 0}
            )
            return 0
        
        # Initialize memory DB
        db = MemoryDB()
        
        # Track what we've already ingested (use file hash)
        # Each file gets its own key: intel_hash_{filename}
        # This avoids the remember() overwrite issue where all files shared one key
        cursor = db.conn.cursor()
        existing_hashes = cursor.execute("""
            SELECT key, value FROM knowledge_base 
            WHERE category = 'system' AND key LIKE 'intel_hash_%'
        """).fetchall()
        # Build dict: filename -> hash
        existing_hash_map = {}
        for row in existing_hashes:
            # key format: intel_hash_filename.md, value format: hash
            filename = row['key'].replace('intel_hash_', '')
            existing_hash_map[filename] = row['value']
        
        # Clean up deleted files - remove facts for files that no longer exist
        current_filenames = {f.name for f in files}
        deleted_files = 0
        deleted_facts = 0
        
        # Method 1: Clean up files with hash entries that no longer exist
        for stored_filename in list(existing_hash_map.keys()):
            if stored_filename not in current_filenames:
                # File was deleted - remove its facts and hash
                cursor.execute("DELETE FROM knowledge_base WHERE source LIKE ?", (f"intel/{stored_filename}",))
                facts_removed = cursor.rowcount
                cursor.execute("DELETE FROM knowledge_base WHERE category = 'system' AND key = ?", 
                             (f"intel_hash_{stored_filename}",))
                db.conn.commit()
                deleted_files += 1
                deleted_facts += facts_removed
                del existing_hash_map[stored_filename]
        
        # Method 2: Clean up orphaned facts from files that were deleted before hash tracking
        # Find all unique intel sources in DB and remove those that don't exist on disk
        orphan_sources = cursor.execute("""
            SELECT DISTINCT source FROM knowledge_base 
            WHERE source LIKE 'intel/%' AND source NOT LIKE 'intel/README.md'
        """).fetchall()
        
        for row in orphan_sources:
            source = row['source']  # e.g., "intel/old-file.md"
            filename = source.replace('intel/', '')
            if filename not in current_filenames:
                cursor.execute("DELETE FROM knowledge_base WHERE source = ?", (source,))
                facts_removed = cursor.rowcount
                if facts_removed > 0:
                    deleted_files += 1
                    deleted_facts += facts_removed
        db.conn.commit()
        
        total_facts = 0
        new_files = 0
        skipped_files = 0
        processed_files = []
        
        for filepath in files:
            file_hash = get_file_hash(filepath)
            
            # Check if already ingested (same hash = unchanged file)
            stored_hash = existing_hash_map.get(filepath.name)
            if stored_hash == file_hash:
                skipped_files += 1
                continue
            
            # Read and extract facts
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            facts = extract_facts_from_content(content, filepath.name)
            
            # If no structured facts extracted, store full content as single fact
            # (handles plain text like "hello world" or unstructured notes)
            if not facts and content.strip():
                section = filepath.name.replace('.txt', '').replace('.md', '').replace('_', ' ').title()
                facts = [{
                    "key": f"{section} content",
                    "value": content.strip(),
                    "category": "fact",
                    "source": f"intel/{filepath.name}"
                }]
            elif not facts:
                continue
            
            # Before adding new facts, check if this file was previously ingested
            # If so, delete old facts from this source (file was modified)
            if stored_hash is not None and stored_hash != file_hash:
                # File was modified - delete old memories from this file
                cursor.execute("DELETE FROM knowledge_base WHERE source LIKE ?", (f"intel/{filepath.name}",))
                db.conn.commit()
            
            # Save each fact to memory with metadata
            for fact in facts:
                # Include source in the value for context
                enriched_value = f"{fact['value']} (source: {fact.get('source', 'intel')})"
                
                # Build metadata
                metadata = {
                    "source_file": filepath.name,
                    "ingested_at": format_utc_z(now_utc()),
                    "file_hash": file_hash,
                    "tool": "ingest_intel"
                }
                
                db.remember(
                    category=fact.get("category", "technical"),
                    key=fact["key"],
                    value=enriched_value,
                    importance=8,  # High importance for explicitly provided intel
                    source=fact.get("source", "intel"),  # Track source for future deletions
                    metadata=metadata
                )
                total_facts += 1
            
            # Mark file as ingested (unique key per file)
            db.remember(
                category="system",
                key=f"intel_hash_{filepath.name}",
                value=file_hash,
                importance=1,
                generate_embedding=False  # No need for semantic search on hashes
            )
            
            new_files += 1
            processed_files.append(filepath.name)
        
        # Build response
        speech_parts = []
        
        if new_files > 0:
            speech_parts.append(f"Ingested {new_files} intel file{'s' if new_files != 1 else ''}, extracted {total_facts} facts")
        
        if deleted_files > 0:
            speech_parts.append(f"Cleaned up {deleted_files} deleted file{'s' if deleted_files != 1 else ''} ({deleted_facts} facts removed)")
        
        if skipped_files > 0 and new_files == 0 and deleted_files == 0:
            speech_parts.append(f"All {len(files)} intel files already ingested. Nothing new to add")
        elif skipped_files > 0:
            speech_parts.append(f"Skipped {skipped_files} unchanged file{'s' if skipped_files != 1 else ''}")
        
        speech = ". ".join(speech_parts) + "." if speech_parts else "No intel files found."
        
        return_success(
            speech,
            {
                "new_files": new_files,
                "skipped_files": skipped_files,
                "deleted_files": deleted_files,
                "deleted_facts": deleted_facts,
                "total_facts": total_facts,
                "processed_files": processed_files
            }
        )
        return 0
        
    except Exception as e:
        return_error(f"Failed to ingest intel: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
