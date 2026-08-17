"""Memory API endpoints - CRUD and search for Jarvis memories."""

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))

from api.models.memory import (
    Memory,
    MemoryCategoriesResponse,
    MemoryCreate,
    MemoryResponse,
    MemorySearchResponse,
    MemoryUpdate,
    SemanticSearchRequest,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])


def get_db():
    """Get memory database instance"""
    from memory_db import MemoryDB
    return MemoryDB()


def memory_to_dict(row) -> dict:
    """Convert database row to clean dict (remove embedding blob)"""
    if row is None:
        return None
    
    memory = dict(row) if hasattr(row, 'keys') else row
    
    # Remove embedding blob (not JSON serializable)
    if 'embedding' in memory:
        del memory['embedding']
    
    # Parse metadata if it's a string
    if memory.get('metadata') and isinstance(memory['metadata'], str):
        import json
        try:
            memory['metadata'] = json.loads(memory['metadata'])
        except (json.JSONDecodeError, TypeError):
            pass
    
    return memory


# ============================================
# Utility Operations (MUST be before /{memory_id} routes)
# ============================================

@router.get("/stats")
async def get_memory_stats():
    """
    Get memory database statistics.
    
    Returns counts, top categories, and storage info.
    """
    try:
        db = get_db()
        cursor = db.conn.cursor()
        
        # Total memories
        total = cursor.execute("SELECT COUNT(*) FROM knowledge_base").fetchone()[0]
        
        # With embeddings
        with_embeddings = cursor.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE embedding IS NOT NULL"
        ).fetchone()[0]
        
        # By category
        categories = cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM knowledge_base
            GROUP BY category
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()
        
        # Recent
        recent = cursor.execute("""
            SELECT COUNT(*) FROM knowledge_base
            WHERE updated_at > datetime('now', '-7 days')
        """).fetchone()[0]
        
        # High importance
        high_importance = cursor.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE importance >= 8"
        ).fetchone()[0]
        
        return {
            "status": "ok",
            "total_memories": total,
            "with_embeddings": with_embeddings,
            "embedding_coverage": f"{(with_embeddings/max(total,1))*100:.1f}%",
            "updated_last_7_days": recent,
            "high_importance": high_importance,
            "top_categories": {row['category']: row['count'] for row in categories},
            "database": db.db_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories", response_model=MemoryCategoriesResponse)
async def list_categories():
    """
    List all memory categories with counts.
    
    Useful for understanding what's stored and filtering.
    """
    try:
        db = get_db()
        cursor = db.conn.cursor()
        
        rows = cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM knowledge_base
            GROUP BY category
            ORDER BY count DESC
        """).fetchall()
        
        categories = {row['category']: row['count'] for row in rows}
        
        return MemoryCategoriesResponse(
            ok=True,
            message=f"Found {len(categories)} categories",
            categories=categories,
            count=sum(categories.values())
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebuild-fts")
async def rebuild_fts_index():
    """
    Rebuild the FTS5 full-text search index.
    
    Use this if keyword search seems broken or incomplete.
    """
    try:
        db = get_db()
        count = db.rebuild_fts_index()
        
        return {
            "status": "ok",
            "indexed": count,
            "message": f"Rebuilt FTS index with {count} memories"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Search Operations (MUST be before /{memory_id} routes)
# ============================================

@router.get("/search/keyword", response_model=MemoryResponse)
async def search_memories_keyword(
    q: str = Query(..., description="Search query"),
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(10, ge=1, le=100, description="Maximum results")
):
    """
    Keyword search using FTS5 full-text search (fast, BM25 ranking).
    
    Good for: Simple keyword lookups, 1-3 word searches like "flask", "project location"
    
    For natural language questions, use `/search/semantic` instead.
    """
    try:
        db = get_db()
        memories = db.fts_search(query=q, limit=limit)
        
        # Apply category filter if specified
        if category:
            memories = [m for m in memories if m.get('category') == category]
        
        return MemoryResponse(
            ok=True,
            count=len(memories),
            memories=[Memory(**memory_to_dict(m)) for m in memories]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search/semantic", response_model=MemorySearchResponse)
async def search_memories_semantic(
    q: str = Query(..., description="Natural language question or concept"),
    limit: int = Query(5, ge=1, le=50, description="Maximum results"),
    threshold: float | None = Query(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum dense similarity (0-1); omit to use the active mode's "
            "SEMANTIC_SIMILARITY_THRESHOLD"
        ),
    ),
):
    """
    Hybrid search using dense embeddings and FTS5/BM25 keyword evidence.
    
    Good for: Natural language questions like "Where is my Flask project?", 
    "What's John's email?", "How do I configure the API?"
    
    Broad keyword hits reinforce dense matches, while keyword-only results must
    match every meaningful query term when embeddings are healthy. If semantic
    retrieval is unavailable, the endpoint continues with keyword fallback and
    reports the reason in retrieval metadata.
    """
    try:
        db = get_db()
        memories = db.semantic_search(
            query=q,
            limit=limit,
            similarity_threshold=threshold
        )
        
        return MemorySearchResponse(
            ok=True,
            count=len(memories),
            memories=[Memory(**memory_to_dict(m)) for m in memories],
            retrieval=db.last_semantic_search_meta,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/semantic", response_model=MemorySearchResponse)
async def search_memories_semantic_post(request: SemanticSearchRequest):
    """
    Hybrid memory search (POST version for complex queries).
    
    Same as GET /search/semantic but accepts JSON body for longer queries.
    """
    try:
        db = get_db()
        memories = db.semantic_search(
            query=request.query,
            limit=request.limit,
            similarity_threshold=request.similarity_threshold
        )
        
        return MemorySearchResponse(
            ok=True,
            count=len(memories),
            memories=[Memory(**memory_to_dict(m)) for m in memories],
            retrieval=db.last_semantic_search_meta,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# CRUD Operations
# ============================================

@router.post("", response_model=MemoryResponse)
@router.post("/", response_model=MemoryResponse, include_in_schema=False)
async def create_memory(memory: MemoryCreate):
    """
    Create or update a memory.
    
    If a memory with the same category+key exists, it will be updated.
    Generates vector embedding for semantic search by default.
    
    **Categories**: personal, technical, contact, preference, project, fact, location, other
    
    **Example use cases**:
    - Store project locations
    - Remember user preferences
    - Save API keys/configs (use importance=10)
    - Track contacts and relationships
    """
    try:
        db = get_db()
        memory_id = db.remember(
            category=memory.category,
            key=memory.key,
            value=memory.value,
            importance=memory.importance,
            source=memory.source,
            generate_embedding=memory.generate_embedding,
            metadata=memory.metadata
        )
        
        return MemoryResponse(
            ok=True,
            memory_id=memory_id,
            message=f"Memory saved (ID: {memory_id})"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=MemoryResponse)
@router.get("/", response_model=MemoryResponse, include_in_schema=False)
async def list_memories(
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results")
):
    """
    List all memories with optional category filter.
    
    Returns memories sorted by importance (descending), then by updated_at.
    """
    try:
        db = get_db()
        memories = db.get_all_memories(category=category)
        
        # Limit results
        memories = memories[:limit]
        
        return MemoryResponse(
            ok=True,
            count=len(memories),
            memories=[Memory(**memory_to_dict(m)) for m in memories]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Parameterized routes (MUST be LAST to avoid catching /stats, /categories, etc.)
# ============================================

@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(memory_id: int):
    """Get a specific memory by ID"""
    try:
        db = get_db()
        cursor = db.conn.cursor()
        
        row = cursor.execute(
            "SELECT * FROM knowledge_base WHERE id = ?", 
            (memory_id,)
        ).fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
        
        return MemoryResponse(
            ok=True,
            memory=Memory(**memory_to_dict(row))
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{memory_id}", response_model=MemoryResponse)
async def update_memory(memory_id: int, update: MemoryUpdate):
    """
    Update an existing memory.
    
    Only updates provided fields (value, importance).
    Does NOT regenerate embeddings - use POST to fully replace.
    """
    try:
        db = get_db()
        success = db.update_memory(
            memory_id=memory_id,
            value=update.value,
            importance=update.importance
        )
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
        
        return MemoryResponse(
            ok=True,
            message=f"Memory {memory_id} updated"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{memory_id}", response_model=MemoryResponse)
async def delete_memory(memory_id: int):
    """Delete a memory (forget it)"""
    try:
        db = get_db()
        success = db.forget(memory_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")

        return MemoryResponse(
            ok=True,
            message=f"Memory {memory_id} deleted"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
