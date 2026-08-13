"""Intel API endpoints - CRUD for jarvis-intel/ knowledge base files"""

from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
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
sys.path.insert(0, str(SKILLS_DIR))
from config_loader import config_scope, get_active_config_mode
from intel_content import normalize_intel_content
from intel_filename import validate_create_filename
from manage_intel import auto_ingest, get_auto_ingest_plan, start_auto_ingest


def _resolve_ingest_mode(mode: str | None) -> str:
    """Resolve an explicit request mode or the FastAPI startup mode."""
    try:
        return get_active_config_mode(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_ingest_plan(mode: str | None) -> tuple[str, dict]:
    """Validate mode/config before a mutating route writes the Intel file."""
    resolved_mode = _resolve_ingest_mode(mode)
    plan = get_auto_ingest_plan(PROJECT_ROOT, resolved_mode)
    if not plan.get("ok"):
        raise HTTPException(status_code=400, detail=plan.get("error", "Ingest preflight failed"))
    return resolved_mode, plan


def _start_planned_ingest(mode: str) -> dict:
    """Launch detached multi-mode ingestion after the canonical file is saved."""
    result = start_auto_ingest(PROJECT_ROOT, mode)
    if not result.get("started"):
        raise HTTPException(status_code=500, detail=result.get("error", "Ingest could not start"))
    return result


def get_db():
    """Get memory database instance for checking ingestion status"""
    from memory_db import MemoryDB
    return MemoryDB()


def _memory_db_path(mode: str) -> Path:
    """Return the existing-mode DB path without initializing MemoryDB."""
    db_name = "jarvis_memory_local.db" if mode == "local" else "jarvis_memory.db"
    return PROJECT_ROOT / "data" / db_name


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
            "SELECT COUNT(*) FROM knowledge_base WHERE source = ?",
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
                "SELECT COUNT(*) FROM knowledge_base WHERE source = ?",
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
    async_mode: bool = Query(False, description="If true, start ingestion in background and return immediately"),
    mode: str | None = None,
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
        
        resolved_mode, plan = _require_ingest_plan(mode)

        if async_mode:
            started = _start_planned_ingest(resolved_mode)
            return IngestResult(
                ok=True,
                async_started=True,
                modes=started.get("modes", []),
                skipped_modes=started.get("skipped_modes", []),
                partial=bool(started.get("warning")),
                warning=started.get("warning"),
            )
        else:
            result = auto_ingest(PROJECT_ROOT, resolved_mode)
            if not result.get("ingested"):
                error = result.get("error", "Ingestion failed")
                status = 504 if "timeout" in error.lower() else 500
                raise HTTPException(status_code=status, detail=error)
            mode_results = result.get("results", [])
            return IngestResult(
                ok=True,
                new_files=result.get("new_files", 0),
                skipped_files=sum(
                    int(entry.get("skipped_files", 0) or 0)
                    for entry in mode_results
                    if isinstance(entry, dict)
                ),
                total_facts=result.get("total_facts", 0),
                processed_files=[
                    str(filename)
                    for entry in mode_results
                    if isinstance(entry, dict)
                    for filename in (entry.get("processed_files") or [])
                ],
                modes=result.get("modes", plan.get("modes", [])),
                skipped_modes=result.get("skipped_modes", []),
                partial=bool(result.get("partial")),
                warning=result.get("warning"),
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# CRUD Operations
# ============================================

@router.post("", response_model=IntelResponse)
@router.post("/", response_model=IntelResponse, include_in_schema=False)
async def create_intel_file(data: IntelCreate, mode: str | None = None):
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
        try:
            validate_create_filename(filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filepath = INTEL_DIR / filename
        
        if filepath.exists():
            raise HTTPException(
                status_code=409,
                detail=f"File '{filename}' already exists. Use PUT to update."
            )

        resolved_mode = None
        ingest_plan = None
        if data.auto_ingest:
            resolved_mode, ingest_plan = _require_ingest_plan(mode)
        
        # Normalize escaped multiline text from LLM/tool output before writing.
        content, _ = normalize_intel_content(data.content)
        filepath.write_text(content, encoding='utf-8')
        
        ingest_start = None
        if data.auto_ingest:
            ingest_start = _start_planned_ingest(resolved_mode)
        
        return IntelResponse(
            ok=True,
            message=f"Created {filename}" + (" (ingestion started)" if data.auto_ingest else ""),
            file=get_file_info(filepath),
            ingestion_started=bool(ingest_start),
            ingest_modes=(ingest_start or ingest_plan or {}).get("modes"),
            ingest_warning=(ingest_start or ingest_plan or {}).get("warning"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{filename}", response_model=IntelResponse)
async def get_intel_file(filename: str, mode: str | None = None):
    """
    Get an intel file's content and metadata.
    """
    try:
        filename = validate_filename(filename)
        filepath = INTEL_DIR / filename
        
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"File '{filename}' not found")
        
        content = filepath.read_text(encoding='utf-8')
        resolved_mode = _resolve_ingest_mode(mode)
        file_info = get_file_info(filepath)
        if _memory_db_path(resolved_mode).is_file():
            with config_scope(resolved_mode):
                db = get_db()
                try:
                    file_info = get_file_info(filepath, db)
                finally:
                    db.close()

        return IntelResponse(ok=True, file=file_info, content=content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{filename}", response_model=IntelResponse)
async def update_intel_file(filename: str, data: IntelUpdate, mode: str | None = None):
    """
    Update an existing intel file.
    
    Replaces file content. If auto_ingest=true, re-ingests to update memory.
    """
    try:
        filename = validate_filename(filename)
        filepath = INTEL_DIR / filename
        
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"File '{filename}' not found")

        resolved_mode = None
        ingest_plan = None
        if data.auto_ingest:
            resolved_mode, ingest_plan = _require_ingest_plan(mode)
        
        # Normalize escaped multiline text from LLM/tool output before writing.
        content, _ = normalize_intel_content(data.content)
        filepath.write_text(content, encoding='utf-8')
        
        # Optionally re-ingest
        ingest_start = None
        if data.auto_ingest:
            # First, delete old memories from this file
            with config_scope(resolved_mode):
                db = get_db()
                cursor = db.conn.cursor()
                cursor.execute(
                    "DELETE FROM knowledge_base WHERE source = ?",
                    (f"intel/{filename}",)
                )
                # Delete hash tracking
                cursor.execute(
                    "DELETE FROM knowledge_base WHERE category = 'system' AND key = ?",
                    (f"intel_hash_{filename}",)
                )
                db.conn.commit()
            ingest_start = _start_planned_ingest(resolved_mode)
        
        return IntelResponse(
            ok=True,
            message=f"Updated {filename}" + (" (re-ingestion started)" if data.auto_ingest else ""),
            file=get_file_info(filepath),
            ingestion_started=bool(ingest_start),
            ingest_modes=(ingest_start or ingest_plan or {}).get("modes"),
            ingest_warning=(ingest_start or ingest_plan or {}).get("warning"),
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
            "SELECT COUNT(*) FROM knowledge_base WHERE source = ?",
            (f"intel/{filename}",)
        ).fetchone()[0]
        
        # Delete facts
        cursor.execute(
            "DELETE FROM knowledge_base WHERE source = ?",
            (f"intel/{filename}",)
        )
        
        # Delete hash tracking
        cursor.execute(
            "DELETE FROM knowledge_base WHERE category = 'system' AND key = ?",
            (f"intel_hash_{filename}",)
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
