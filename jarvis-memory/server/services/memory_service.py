"""
Memory Service - Database operations for memory management
Handles both cloud and local databases
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
DATA_PATH = JARVIS_ROOT / 'data'

# Database paths
DB_PATHS = {
    'cloud': DATA_PATH / 'jarvis_memory.db',
    'local': DATA_PATH / 'jarvis_memory_local.db'
}


def get_db_path(mode: str) -> Path:
    """Get database path for mode"""
    return DB_PATHS.get(mode, DB_PATHS['cloud'])


def get_connection(mode: str) -> sqlite3.Connection:
    """Get database connection for mode"""
    db_path = get_db_path(mode)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class MemoryService:
    """Service for memory database operations"""
    
    def __init__(self, mode: str = 'cloud'):
        self.mode = mode
        self.db_path = get_db_path(mode)
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get a new connection"""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    # =========================================================================
    # Knowledge Base Operations
    # =========================================================================
    
    def list_memories(self, category: str = None, limit: int = 100, 
                      offset: int = 0, sort_by: str = 'updated_at',
                      sort_order: str = 'DESC') -> List[Dict]:
        """List all memories with optional filtering"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Validate sort column
        valid_sorts = ['id', 'category', 'key', 'importance', 'created_at', 'updated_at']
        if sort_by not in valid_sorts:
            sort_by = 'updated_at'
        
        sort_order = 'DESC' if sort_order.upper() == 'DESC' else 'ASC'
        
        try:
            if category:
                results = cursor.execute(f"""
                    SELECT id, category, key, value, importance, created_at, updated_at, 
                           source, metadata, long_form,
                           CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                    FROM knowledge_base
                    WHERE category = ?
                    ORDER BY {sort_by} {sort_order}
                    LIMIT ? OFFSET ?
                """, (category, limit, offset)).fetchall()
            else:
                results = cursor.execute(f"""
                    SELECT id, category, key, value, importance, created_at, updated_at,
                           source, metadata, long_form,
                           CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                    FROM knowledge_base
                    ORDER BY {sort_by} {sort_order}
                    LIMIT ? OFFSET ?
                """, (limit, offset)).fetchall()
            
            memories = []
            for row in results:
                memory = dict(row)
                # Parse metadata JSON if present
                if memory.get('metadata'):
                    try:
                        memory['metadata'] = json.loads(memory['metadata'])
                    except:
                        pass
                memories.append(memory)
            
            return memories
        finally:
            conn.close()
    
    def get_memory(self, memory_id: int) -> Optional[Dict]:
        """Get a single memory by ID"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            result = cursor.execute("""
                SELECT id, category, key, value, importance, created_at, updated_at,
                       source, metadata, long_form,
                       CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM knowledge_base
                WHERE id = ?
            """, (memory_id,)).fetchone()
            
            if result:
                memory = dict(result)
                if memory.get('metadata'):
                    try:
                        memory['metadata'] = json.loads(memory['metadata'])
                    except:
                        pass
                return memory
            return None
        finally:
            conn.close()
    
    def search_memories(self, query: str, limit: int = 50) -> List[Dict]:
        """
        Search memories using FTS5 (full-text search with BM25 ranking)
        Falls back to LIKE search if FTS5 fails
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            # Try FTS5 search first
            try:
                results = cursor.execute("""
                    SELECT kb.id, kb.category, kb.key, kb.value, kb.importance, 
                           kb.created_at, kb.updated_at, kb.source, kb.metadata, kb.long_form,
                           bm25(knowledge_base_fts) as relevance_score,
                           CASE WHEN kb.embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                    FROM knowledge_base kb
                    JOIN knowledge_base_fts ON kb.id = knowledge_base_fts.rowid
                    WHERE knowledge_base_fts MATCH ?
                    ORDER BY relevance_score ASC, kb.importance DESC
                    LIMIT ?
                """, (query, limit)).fetchall()
                
                memories = []
                for row in results:
                    memory = dict(row)
                    # Convert BM25 to 0-1 score
                    memory['relevance'] = 1 / (1 + abs(memory.get('relevance_score', 0)))
                    if 'relevance_score' in memory:
                        del memory['relevance_score']
                    if memory.get('metadata'):
                        try:
                            memory['metadata'] = json.loads(memory['metadata'])
                        except:
                            pass
                    memories.append(memory)
                
                if memories:
                    return memories
                    
            except sqlite3.OperationalError:
                pass  # FTS5 not available or query syntax error
            
            # Fallback to LIKE search
            results = cursor.execute("""
                SELECT id, category, key, value, importance, created_at, updated_at,
                       source, metadata, long_form,
                       CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM knowledge_base
                WHERE key LIKE ? OR value LIKE ? OR category LIKE ?
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
            
            return [dict(row) for row in results]
            
        finally:
            conn.close()
    
    def create_memory(self, category: str, key: str, value: str, 
                      importance: int = 5, source: str = None,
                      metadata: dict = None) -> int:
        """Create a new memory"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        metadata_json = json.dumps(metadata) if metadata else None
        
        try:
            cursor.execute("""
                INSERT INTO knowledge_base (category, key, value, importance, source, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (category, key, value, importance, source or 'memory_browser', metadata_json))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()
    
    def update_memory(self, memory_id: int, category: str = None, key: str = None,
                      value: str = None, importance: int = None, 
                      metadata: dict = None) -> bool:
        """Update an existing memory"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if category is not None:
            updates.append("category = ?")
            params.append(category)
        if key is not None:
            updates.append("key = ?")
            params.append(key)
        if value is not None:
            updates.append("value = ?")
            params.append(value)
        if importance is not None:
            updates.append("importance = ?")
            params.append(importance)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))
        
        if not updates:
            return False
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(memory_id)
        
        try:
            query = f"UPDATE knowledge_base SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def delete_memory(self, memory_id: int) -> bool:
        """Delete a memory"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM knowledge_base WHERE id = ?", (memory_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def get_categories(self) -> List[Dict]:
        """Get list of categories with counts"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            results = cursor.execute("""
                SELECT category, COUNT(*) as count
                FROM knowledge_base
                GROUP BY category
                ORDER BY count DESC
            """).fetchall()
            
            return [{'name': row['category'], 'count': row['count']} for row in results]
        finally:
            conn.close()
    
    def get_stats(self) -> Dict:
        """Get memory database statistics"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
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
            """).fetchall()
            
            # By importance
            importance_dist = cursor.execute("""
                SELECT importance, COUNT(*) as count
                FROM knowledge_base
                GROUP BY importance
                ORDER BY importance DESC
            """).fetchall()
            
            # Recent activity
            recent = cursor.execute("""
                SELECT COUNT(*) FROM knowledge_base
                WHERE updated_at > datetime('now', '-7 days')
            """).fetchone()[0]
            
            # Database file size
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
            
            return {
                'total_memories': total,
                'with_embeddings': with_embeddings,
                'without_embeddings': total - with_embeddings,
                'categories': [{'name': r['category'], 'count': r['count']} for r in categories],
                'importance_distribution': [{'level': r['importance'], 'count': r['count']} for r in importance_dist],
                'recent_7_days': recent,
                'db_size_bytes': db_size,
                'db_size_mb': round(db_size / (1024 * 1024), 2),
                'mode': self.mode
            }
        finally:
            conn.close()
    
    # =========================================================================
    # Conversation Operations
    # =========================================================================
    
    def list_conversations(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """List conversations from database"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            results = cursor.execute("""
                SELECT id, timestamp, session_id, user_query, jarvis_response,
                       tools_used, success, metadata
                FROM conversations
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
            
            conversations = []
            for row in results:
                conv = dict(row)
                # Parse JSON fields
                if conv.get('tools_used'):
                    try:
                        conv['tools_used'] = json.loads(conv['tools_used'])
                    except:
                        pass
                if conv.get('metadata'):
                    try:
                        conv['metadata'] = json.loads(conv['metadata'])
                    except:
                        pass
                conversations.append(conv)
            
            return conversations
        finally:
            conn.close()
    
    def search_conversations(self, query: str, limit: int = 50) -> List[Dict]:
        """Search conversations"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            results = cursor.execute("""
                SELECT id, timestamp, session_id, user_query, jarvis_response,
                       tools_used, success, metadata
                FROM conversations
                WHERE user_query LIKE ? OR jarvis_response LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit)).fetchall()
            
            conversations = []
            for row in results:
                conv = dict(row)
                if conv.get('tools_used'):
                    try:
                        conv['tools_used'] = json.loads(conv['tools_used'])
                    except:
                        pass
                if conv.get('metadata'):
                    try:
                        conv['metadata'] = json.loads(conv['metadata'])
                    except:
                        pass
                conversations.append(conv)
            
            return conversations
        finally:
            conn.close()
    
    def get_conversation_stats(self) -> Dict:
        """Get conversation statistics"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            total = cursor.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            
            success_count = cursor.execute(
                "SELECT COUNT(*) FROM conversations WHERE success = 1"
            ).fetchone()[0]
            
            recent = cursor.execute("""
                SELECT COUNT(*) FROM conversations
                WHERE timestamp > datetime('now', '-7 days')
            """).fetchone()[0]
            
            # Most used tools
            tool_usage = {}
            results = cursor.execute("SELECT tools_used FROM conversations WHERE tools_used IS NOT NULL").fetchall()
            for row in results:
                try:
                    tools = json.loads(row['tools_used'])
                    if isinstance(tools, list):
                        for tool in tools:
                            tool_usage[tool] = tool_usage.get(tool, 0) + 1
                except:
                    pass
            
            top_tools = sorted(tool_usage.items(), key=lambda x: x[1], reverse=True)[:10]
            
            return {
                'total_conversations': total,
                'success_rate': round(success_count / total * 100, 1) if total > 0 else 0,
                'recent_7_days': recent,
                'top_tools': [{'name': t[0], 'count': t[1]} for t in top_tools]
            }
        finally:
            conn.close()

