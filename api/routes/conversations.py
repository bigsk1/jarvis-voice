"""Conversations API endpoints - Read-only access to conversation history"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))

from api.models.conversation import (
    Conversation, ConversationResponse, ConversationStats
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def get_db():
    """Get memory database instance (mode-specific)"""
    from memory_db import MemoryDB
    return MemoryDB()


def row_to_conversation(row) -> Conversation:
    """Convert database row to Conversation model"""
    tools_used = None
    if row['tools_used']:
        try:
            tools_used = json.loads(row['tools_used'])
        except:
            tools_used = [row['tools_used']]
    
    metadata = None
    if row['metadata']:
        try:
            metadata = json.loads(row['metadata'])
        except:
            pass
    
    return Conversation(
        id=row['id'],
        timestamp=row['timestamp'],
        session_id=row['session_id'],
        user_query=row['user_query'],
        jarvis_response=row['jarvis_response'],
        tools_used=tools_used,
        success=bool(row['success']),
        metadata=metadata
    )


# ============================================
# List & Pagination
# ============================================

@router.get("", response_model=ConversationResponse)
@router.get("/", response_model=ConversationResponse, include_in_schema=False)
async def list_conversations(
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    success: Optional[bool] = Query(None, description="Filter by success status"),
    tool: Optional[str] = Query(None, description="Filter by tool used")
):
    """
    List recent conversations with pagination.
    
    Returns conversations from the current mode's database (cloud or local).
    
    **Filters:**
    - `session_id`: Get all conversations from a specific session
    - `success`: Filter by outcome (true/false)
    - `tool`: Filter by tool used (e.g., "weather", "crypto_price")
    
    **Pagination:**
    - `limit`: Results per page (default 50, max 500)
    - `offset`: Skip N results
    """
    try:
        db = get_db()
        cursor = db.conn.cursor()
        
        # Build query
        conditions = []
        params = []
        
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        
        if success is not None:
            conditions.append("success = ?")
            params.append(1 if success else 0)
        
        if tool:
            conditions.append("tools_used LIKE ?")
            params.append(f'%"{tool}"%')
        
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        
        # Get total count
        total = cursor.execute(
            f"SELECT COUNT(*) FROM conversations{where_clause}",
            params
        ).fetchone()[0]
        
        # Get paginated results
        rows = cursor.execute(
            f"""SELECT * FROM conversations{where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset]
        ).fetchall()
        
        conversations = [row_to_conversation(row) for row in rows]
        
        return ConversationResponse(
            ok=True,
            count=len(conversations),
            total=total,
            page=(offset // limit) + 1,
            pages=(total + limit - 1) // limit,
            conversations=conversations
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Get Single Conversation
# ============================================

@router.get("/stats", response_model=ConversationStats)
async def get_conversation_stats():
    """
    Get conversation statistics.
    
    Returns counts, success rates, and top tools used.
    """
    try:
        db = get_db()
        cursor = db.conn.cursor()
        
        # Total
        total = cursor.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        
        # Today
        today = cursor.execute("""
            SELECT COUNT(*) FROM conversations 
            WHERE date(timestamp) = date('now')
        """).fetchone()[0]
        
        # This week
        this_week = cursor.execute("""
            SELECT COUNT(*) FROM conversations 
            WHERE timestamp > datetime('now', '-7 days')
        """).fetchone()[0]
        
        # Success rate
        successful = cursor.execute(
            "SELECT COUNT(*) FROM conversations WHERE success = 1"
        ).fetchone()[0]
        success_rate = (successful / max(total, 1)) * 100
        
        # Top tools
        rows = cursor.execute("""
            SELECT tools_used, COUNT(*) as count 
            FROM conversations 
            WHERE tools_used IS NOT NULL AND tools_used != '[]'
            GROUP BY tools_used 
            ORDER BY count DESC 
            LIMIT 10
        """).fetchall()
        
        # Parse and aggregate tools
        tool_counts = {}
        for row in rows:
            try:
                tools = json.loads(row['tools_used'])
                for tool in tools:
                    tool_counts[tool] = tool_counts.get(tool, 0) + row['count']
            except:
                pass
        
        # Sort by count
        top_tools = dict(sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:10])
        
        return ConversationStats(
            total_conversations=total,
            total_today=today,
            total_this_week=this_week,
            success_rate=round(success_rate, 1),
            top_tools=top_tools,
            database=db.db_path
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recent", response_model=ConversationResponse)
async def get_recent_conversations(
    minutes: int = Query(30, ge=1, le=1440, description="Look back N minutes"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results")
):
    """
    Get recent conversations within a time window.
    
    Useful for getting context of recent interactions.
    """
    try:
        db = get_db()
        cursor = db.conn.cursor()
        
        rows = cursor.execute("""
            SELECT * FROM conversations 
            WHERE timestamp > datetime('now', ? || ' minutes')
            ORDER BY timestamp DESC
            LIMIT ?
        """, (f'-{minutes}', limit)).fetchall()
        
        conversations = [row_to_conversation(row) for row in rows]
        
        return ConversationResponse(
            ok=True,
            message=f"Conversations from last {minutes} minutes",
            count=len(conversations),
            conversations=conversations
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", response_model=ConversationResponse)
async def search_conversations(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results")
):
    """
    Search conversations by query text or response.
    
    Searches in both user queries and Jarvis responses.
    """
    try:
        db = get_db()
        cursor = db.conn.cursor()
        
        rows = cursor.execute("""
            SELECT * FROM conversations 
            WHERE user_query LIKE ? OR jarvis_response LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (f'%{q}%', f'%{q}%', limit)).fetchall()
        
        conversations = [row_to_conversation(row) for row in rows]
        
        return ConversationResponse(
            ok=True,
            message=f"Found {len(conversations)} conversations matching '{q}'",
            count=len(conversations),
            conversations=conversations
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(20, ge=1, le=100, description="Maximum sessions")
):
    """
    List unique session IDs with conversation counts.
    
    Useful for understanding conversation groupings.
    """
    try:
        db = get_db()
        cursor = db.conn.cursor()
        
        rows = cursor.execute("""
            SELECT session_id, 
                   COUNT(*) as count,
                   MIN(timestamp) as first_msg,
                   MAX(timestamp) as last_msg
            FROM conversations 
            WHERE session_id IS NOT NULL
            GROUP BY session_id 
            ORDER BY last_msg DESC
            LIMIT ?
        """, (limit,)).fetchall()
        
        sessions = [
            {
                "session_id": row['session_id'],
                "message_count": row['count'],
                "first_message": row['first_msg'],
                "last_message": row['last_msg']
            }
            for row in rows
        ]
        
        return {
            "ok": True,
            "count": len(sessions),
            "sessions": sessions
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: int):
    """
    Get a specific conversation by ID.
    """
    try:
        db = get_db()
        cursor = db.conn.cursor()
        
        row = cursor.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,)
        ).fetchone()
        
        if not row:
            raise HTTPException(
                status_code=404, 
                detail=f"Conversation {conversation_id} not found"
            )
        
        return ConversationResponse(
            ok=True,
            conversation=row_to_conversation(row)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
