"""Intel API endpoints - CRUD for jarvis-intel/ knowledge base files"""

from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import json
import subprocess
import sys
from datetime import datetime

from api.models.intel import (
    IntelFile, IntelCreate, IntelUpdate, 
    IntelResponse, IntelStats, IngestResult
)

router = APIRouter(prefix="/api/intel", tags=["intel"])

# Intel directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
INTEL_DIR = PROJECT_ROOT / "jarvis-intel"
SKILLS_DIR = PROJECT_ROOT / "skills"

sys.path.insert(0, str(PROJECT_ROOT / "lib"))
from intel_content import normalize_intel_content


def get_db():
    """Get memory database instance for checking ingestion status"""
    from memory_db import MemoryDB
    return MemoryDB()


def human_size(size_bytes: int) -> str:
    """Convert bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def get_file_info(filepath: Path, db=None) -> IntelFile:
    """Get info about an intel file"""
    stat = filepath.stat()
    
    # Check if ingested
    ingested = False
    fact_count = None
    
    if db:
        cursor = db.conn.cursor()
        # Check for facts from this file
        count = cursor.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE source LIKE ?",
            (f"intel/{filepath.name}",)
        ).fetchone()[0]
        if count > 0:
            ingested = True
            fact_count = count
    
    return IntelFile(
        filename=filepath.name,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        ingested=ingested,
        fact_count=fact_count
    )


def validate_filename(filename: str) -> str:
    """Validate and sanitize filename"""
    # Remove path components
    filename = Path(filename).name
    
    # Check extension
    if not filename.endswith(('.md', '.txt')):
        raise HTTPException(
            status_code=400, 
            detail="Filename must end in .md or .txt"
        )
    
    # Don't allow README.md
    if filename == 'README.md':
        raise HTTPException(
            status_code=400,
            detail="Cannot modify README.md"
        )
    
    # Sanitize: only allow safe characters
    safe_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.')
    if not all(c in safe_chars for c in filename):
        raise HTTPException(
            status_code=400,
            detail="Filename contains invalid characters. Use only letters, numbers, hyphens, underscores, and dots."
        )
    
    return filename


# ============================================
# Stats & List
# ============================================

@router.get("/stats", response_model=IntelStats)
async def get_intel_stats():
    """
    Get intel folder statistics.
    
    Returns file counts, total size, and ingestion status.
    """
    try:
        db = get_db()
        
        files = list(INTEL_DIR.glob("*.md")) + list(INTEL_DIR.glob("*.txt"))
        files = [f for f in files if f.name != "README.md"]
        
        total_size = sum(f.stat().st_size for f in files)
        
        # Count total facts from intel files
        cursor = db.conn.cursor()
        total_facts = cursor.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE source LIKE 'intel/%'"
        ).fetchone()[0]
        
        # Count files pending ingest (modified after last ingest or no facts)
        pending = 0
        for f in files:
            count = cursor.execute(
                "SELECT COUNT(*) FROM knowledge_base WHERE source LIKE ?",
                (f"intel/{f.name}",)
            ).fetchone()[0]
            if count == 0:
                pending += 1
        
        newest = max(files, key=lambda f: f.stat().st_mtime) if files else None
        oldest = min(files, key=lambda f: f.stat().st_mtime) if files else None
        
        return IntelStats(
            total_files=len(files),
            total_size_bytes=total_size,
            total_size_human=human_size(total_size),
            total_facts_ingested=total_facts,
            files_pending_ingest=pending,
            newest_file=newest.name if newest else None,
            oldest_file=oldest.name if oldest else None
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=IntelResponse)
@router.get("/", response_model=IntelResponse, include_in_schema=False)
async def list_intel_files(
    include_stats: bool = Query(False, description="Include ingestion stats per file")
):
    """
    List all intel files.
    
    Returns all .md and .txt files in jarvis-intel/ folder.
    """
    try:
        db = get_db() if include_stats else None
        
        files = list(INTEL_DIR.glob("*.md")) + list(INTEL_DIR.glob("*.txt"))
        files = [f for f in files if f.name != "README.md"]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        
        intel_files = [get_file_info(f, db) for f in files]
        
        return IntelResponse(
            ok=True,
            count=len(intel_files),
            files=intel_files
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Ingest Operation
# ============================================

@router.post("/ingest", response_model=IngestResult)
async def ingest_intel_files(
    async_mode: bool = Query(False, description="If true, start ingestion in background and return immediately")
):
    """
    Trigger ingestion of all intel files to memory.
    
    Reads all files in jarvis-intel/, extracts facts, and saves to memory database.
    Use async_mode=true for large files to avoid timeout.
    """
    try:
        ingest_script = SKILLS_DIR / "ingest_intel.py"
        
        if not ingest_script.exists():
            raise HTTPException(status_code=500, detail="ingest_intel.py not found")
        
        if async_mode:
            # Start in background
            subprocess.Popen(
                ['python3', str(ingest_script), '--sync'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            return IngestResult(
                ok=True,
                async_started=True
            )
        else:
            # Run synchronously
            result = subprocess.run(
                ['python3', str(ingest_script)],
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes max
            )
            
            if result.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Ingestion failed: {result.stderr or result.stdout}"
                )
            
            try:
                output = json.loads(result.stdout)
                data = output.get('data', {})
                return IngestResult(
                    ok=True,
                    new_files=data.get('new_files', 0),
                    skipped_files=data.get('skipped_files', 0),
                    total_facts=data.get('total_facts', 0),
                    processed_files=data.get('processed_files', [])
                )
            except json.JSONDecodeError:
                return IngestResult(ok=True)
                
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Ingestion timed out (5 minutes)")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# CRUD Operations
# ============================================

@router.post("", response_model=IntelResponse)
@router.post("/", response_model=IntelResponse, include_in_schema=False)
async def create_intel_file(data: IntelCreate):
    """
    Create a new intel file.
    
    Creates a file in jarvis-intel/ folder. Optionally triggers ingestion.
    
    **Format tips for best ingestion:**
    - Use `# Header` for sections
    - Use `Key: Value` format for facts
    - Use `- bullet points` for lists
    """
    try:
        filename = validate_filename(data.filename)
        filepath = INTEL_DIR / filename
        
        if filepath.exists():
            raise HTTPException(
                status_code=409,
                detail=f"File '{filename}' already exists. Use PUT to update."
            )
        
        # Normalize escaped multiline text from LLM/tool output before writing.
        content, _ = normalize_intel_content(data.content)
        filepath.write_text(content, encoding='utf-8')
        
        # Optionally ingest
        if data.auto_ingest:
            subprocess.Popen(
                ['python3', str(SKILLS_DIR / "ingest_intel.py"), '--sync'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        
        return IntelResponse(
            ok=True,
            message=f"Created {filename}" + (" (ingestion started)" if data.auto_ingest else ""),
            file=get_file_info(filepath)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{filename}", response_model=IntelResponse)
async def get_intel_file(filename: str):
    """
    Get an intel file's content and metadata.
    """
    try:
        filename = validate_filename(filename)
        filepath = INTEL_DIR / filename
        
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"File '{filename}' not found")
        
        content = filepath.read_text(encoding='utf-8')
        db = get_db()
        
        return IntelResponse(
            ok=True,
            file=get_file_info(filepath, db),
            content=content
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{filename}", response_model=IntelResponse)
async def update_intel_file(filename: str, data: IntelUpdate):
    """
    Update an existing intel file.
    
    Replaces file content. If auto_ingest=true, re-ingests to update memory.
    """
    try:
        filename = validate_filename(filename)
        filepath = INTEL_DIR / filename
        
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"File '{filename}' not found")
        
        # Normalize escaped multiline text from LLM/tool output before writing.
        content, _ = normalize_intel_content(data.content)
        filepath.write_text(content, encoding='utf-8')
        
        # Optionally re-ingest
        if data.auto_ingest:
            # First, delete old memories from this file
            db = get_db()
            cursor = db.conn.cursor()
            cursor.execute(
                "DELETE FROM knowledge_base WHERE source LIKE ?",
                (f"intel/{filename}",)
            )
            # Delete hash tracking
            cursor.execute(
                "DELETE FROM knowledge_base WHERE category = 'system' AND key = 'intel_files_ingested' AND value LIKE ?",
                (f"%|{filename}",)
            )
            db.conn.commit()
            
            # Then trigger re-ingest
            subprocess.Popen(
                ['python3', str(SKILLS_DIR / "ingest_intel.py"), '--sync'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        
        return IntelResponse(
            ok=True,
            message=f"Updated {filename}" + (" (re-ingestion started)" if data.auto_ingest else ""),
            file=get_file_info(filepath)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{filename}", response_model=IntelResponse)
async def delete_intel_file(filename: str):
    """
    Delete an intel file and its associated memories.
    
    Removes the file and all facts ingested from it.
    """
    try:
        filename = validate_filename(filename)
        filepath = INTEL_DIR / filename
        
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"File '{filename}' not found")
        
        # Delete memories first
        db = get_db()
        cursor = db.conn.cursor()
        
        # Count facts to be deleted
        deleted_facts = cursor.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE source LIKE ?",
            (f"intel/{filename}",)
        ).fetchone()[0]
        
        # Delete facts
        cursor.execute(
            "DELETE FROM knowledge_base WHERE source LIKE ?",
            (f"intel/{filename}",)
        )
        
        # Delete hash tracking
        cursor.execute(
            "DELETE FROM knowledge_base WHERE category = 'system' AND key = 'intel_files_ingested' AND value LIKE ?",
            (f"%|{filename}",)
        )
        db.conn.commit()
        
        # Delete file
        filepath.unlink()
        
        return IntelResponse(
            ok=True,
            message=f"Deleted {filename} and {deleted_facts} associated facts"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
