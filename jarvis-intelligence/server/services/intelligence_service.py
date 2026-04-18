"""
Intelligence Service - Database operations for intelligence layer management
Handles both cloud and local databases
"""
import sqlite3
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
DATA_PATH = JARVIS_ROOT / 'data'
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from time_utils import utc_string_display_fields

# Database paths
DB_PATHS = {
    'cloud': DATA_PATH / 'jarvis_intelligence.db',
    'local': DATA_PATH / 'jarvis_intelligence_local.db'
}


def get_db_path(mode: str) -> Path:
    """Get database path for mode"""
    return DB_PATHS.get(mode, DB_PATHS['cloud'])


def get_connection(mode: str) -> sqlite3.Connection:
    """Get database connection for mode"""
    db_path = get_db_path(mode)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # SECURITY: Ensure DB file is owner-only (600) on every connect,
    # since sqlite3.connect() creates files with umask defaults (644).
    try:
        os.chmod(str(db_path), 0o600)
    except OSError:
        pass
    return conn


class IntelligenceService:
    """Service for intelligence database operations"""
    
    def __init__(self, mode: str = 'cloud'):
        self.mode = mode
        self.db_path = get_db_path(mode)
        self._ensure_insight_usage_columns()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get a new connection"""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_insight_usage_columns(self) -> None:
        """Keep UI reads compatible with DBs created before reflection usage tracking."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            cursor = conn.cursor()
            table_exists = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'insights'"
            ).fetchone()
            if not table_exists:
                return

            cursor.execute("PRAGMA table_info(insights)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            new_columns = [
                ("reflection_provider", "TEXT"),
                ("reflection_model", "TEXT"),
                ("reflection_input_tokens", "INTEGER DEFAULT 0"),
                ("reflection_output_tokens", "INTEGER DEFAULT 0"),
                ("reflection_total_tokens", "INTEGER DEFAULT 0"),
                ("reflection_cost_usd", "REAL DEFAULT 0"),
            ]
            for col_name, col_def in new_columns:
                if col_name not in existing_columns:
                    cursor.execute(f"ALTER TABLE insights ADD COLUMN {col_name} {col_def}")
            conn.commit()
        finally:
            conn.close()

    def _add_time_display(self, item: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
        """Attach configured-local and UTC display fields for stored UTC strings."""
        for field in fields:
            value = item.get(field)
            if not value:
                continue
            try:
                display = utc_string_display_fields(str(value))
            except Exception:
                continue
            item[f'{field}_utc'] = display['utc']
            item[f'{field}_utc_display'] = display['utc_display']
            item[f'{field}_local'] = display['local']
            item[f'{field}_local_display'] = display['local_display']
            item[f'{field}_timezone'] = display['timezone']
        return item

    @staticmethod
    def _parse_json_value(value: Any, default: Any = None) -> Any:
        """Parse a JSON DB field without failing the whole response."""
        if value in (None, ''):
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return default if default is not None else value

    def _hydrate_experience(self, row: sqlite3.Row, include_raw: bool = False) -> Dict[str, Any]:
        """Convert an experience row into API shape."""
        exp = dict(row)
        exp['tools_used'] = self._parse_json_value(exp.get('tools_used'), exp.get('tools_used'))
        exp['tool_sequence'] = self._parse_json_value(exp.get('tool_sequence'), exp.get('tool_sequence'))

        raw_data = self._parse_json_value(exp.get('raw_data'), {})
        if isinstance(raw_data, dict):
            exp['completion_guard'] = raw_data.get('completion_guard')
            if include_raw:
                exp['raw_data'] = raw_data
            else:
                exp.pop('raw_data', None)
        elif include_raw:
            exp['raw_data'] = raw_data
        else:
            exp.pop('raw_data', None)

        return self._add_time_display(exp, ['timestamp'])

    def _hydrate_insight(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert an insight row into API shape."""
        insight = dict(row)
        return self._add_time_display(insight, ['created_at', 'updated_at', 'last_applied'])
    
    # =========================================================================
    # Experiences Operations
    # =========================================================================
    
    def list_experiences(self, limit: int = 100, offset: int = 0,
                        success_only: bool = None) -> List[Dict]:
        """List experiences with optional filtering"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            where_clause = ""
            params = []
            
            if success_only is True:
                where_clause = "WHERE outcome_success = 1"
            elif success_only is False:
                where_clause = "WHERE outcome_success = 0"
            
            results = cursor.execute(f"""
                SELECT id, timestamp, query, context_summary, tools_used, 
                       tool_sequence, turns_taken, final_tool,
                       outcome_success, user_satisfied, error_occurred,
                       raw_data,
                       CASE WHEN query_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM experiences
                {where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """, (*params, limit, offset)).fetchall()

            return [self._hydrate_experience(row, include_raw=False) for row in results]
        finally:
            conn.close()
    
    def get_experience(self, experience_id: int) -> Optional[Dict]:
        """Get a single experience by ID"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            result = cursor.execute("""
                SELECT id, timestamp, query, context_summary, tools_used, 
                       tool_sequence, turns_taken, final_tool,
                       outcome_success, user_satisfied, error_occurred,
                       had_to_retry, had_to_clarify, raw_data,
                       CASE WHEN query_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM experiences
                WHERE id = ?
            """, (experience_id,)).fetchone()
            
            if result:
                return self._hydrate_experience(result, include_raw=True)
            return None
        finally:
            conn.close()
    
    def search_experiences(self, query: str, limit: int = 50) -> List[Dict]:
        """Search experiences by query text"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            results = cursor.execute("""
                SELECT id, timestamp, query, context_summary, tools_used, 
                       tool_sequence, turns_taken, final_tool,
                       outcome_success, user_satisfied, error_occurred,
                       raw_data,
                       CASE WHEN query_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM experiences
                WHERE query LIKE ? OR context_summary LIKE ? OR tools_used LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()

            return [self._hydrate_experience(row, include_raw=False) for row in results]
        finally:
            conn.close()
    
    def update_experience(self, experience_id: int, query: str = None,
                         context_summary: str = None,
                         outcome_success: bool = None) -> bool:
        """Update an experience"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if query is not None:
            updates.append("query = ?")
            params.append(query)
        if context_summary is not None:
            updates.append("context_summary = ?")
            params.append(context_summary)
        if outcome_success is not None:
            updates.append("outcome_success = ?")
            params.append(1 if outcome_success else 0)
        
        if not updates:
            return False
        
        params.append(experience_id)
        
        try:
            query_str = f"UPDATE experiences SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query_str, params)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def delete_experience(self, experience_id: int) -> bool:
        """Delete an experience"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            # Also remove from reflection queue
            cursor.execute("DELETE FROM reflection_queue WHERE experience_id = ?", (experience_id,))
            cursor.execute("DELETE FROM experiences WHERE id = ?", (experience_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    # =========================================================================
    # Insights Operations
    # =========================================================================
    
    def list_insights(self, limit: int = 100, offset: int = 0,
                     constraint_type: str = None, min_confidence: float = None) -> List[Dict]:
        """List insights with optional filtering"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            where_clauses = []
            params = []
            
            if constraint_type:
                where_clauses.append("(constraint_type = ? OR (constraint_type IS NULL AND ? = 'positive'))")
                params.extend([constraint_type, constraint_type])
            
            if min_confidence is not None:
                where_clauses.append("confidence >= ?")
                params.append(min_confidence)
            
            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            
            results = cursor.execute(f"""
                SELECT id, created_at, updated_at, insight_type, description,
                       constraint_type, applies_to_pattern, confidence, evidence_count,
                       times_applied, times_helpful, times_failed, consecutive_failures,
                       last_applied, last_outcome,
                       preferred_tools, avoided_tools, generalizability,
                       reflection_provider, reflection_model,
                       reflection_input_tokens, reflection_output_tokens,
                       reflection_total_tokens, reflection_cost_usd,
                       CASE WHEN insight_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM insights
                {where_sql}
                ORDER BY confidence DESC, times_applied DESC
                LIMIT ? OFFSET ?
            """, (*params, limit, offset)).fetchall()
            
            return [self._hydrate_insight(row) for row in results]
        finally:
            conn.close()
    
    def get_insight(self, insight_id: int) -> Optional[Dict]:
        """Get a single insight by ID"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            result = cursor.execute("""
                SELECT id, created_at, updated_at, insight_type, description,
                       constraint_type, applies_to_pattern, confidence, evidence_count,
                       times_applied, times_helpful, times_failed, consecutive_failures,
                       last_applied, last_outcome, preferred_tools, avoided_tools,
                       generalizability,
                       reflection_provider, reflection_model,
                       reflection_input_tokens, reflection_output_tokens,
                       reflection_total_tokens, reflection_cost_usd,
                       CASE WHEN insight_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM insights
                WHERE id = ?
            """, (insight_id,)).fetchone()
            
            return self._hydrate_insight(result) if result else None
        finally:
            conn.close()
    
    def search_insights(self, query: str, limit: int = 50) -> List[Dict]:
        """Search insights by description or pattern"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            results = cursor.execute("""
                SELECT id, created_at, updated_at, insight_type, description,
                       constraint_type, applies_to_pattern, confidence, evidence_count,
                       times_applied, times_helpful, times_failed,
                       preferred_tools, avoided_tools,
                       reflection_provider, reflection_model,
                       reflection_input_tokens, reflection_output_tokens,
                       reflection_total_tokens, reflection_cost_usd,
                       CASE WHEN insight_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM insights
                WHERE description LIKE ? OR applies_to_pattern LIKE ? 
                      OR preferred_tools LIKE ? OR avoided_tools LIKE ?
                ORDER BY confidence DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
            
            return [self._hydrate_insight(row) for row in results]
        finally:
            conn.close()
    
    def update_insight(self, insight_id: int, description: str = None,
                      applies_to_pattern: str = None, confidence: float = None,
                      constraint_type: str = None) -> bool:
        """Update an insight"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if applies_to_pattern is not None:
            updates.append("applies_to_pattern = ?")
            params.append(applies_to_pattern)
        if confidence is not None:
            updates.append("confidence = ?")
            params.append(confidence)
        if constraint_type is not None:
            updates.append("constraint_type = ?")
            params.append(constraint_type)
        
        if not updates:
            return False
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(insight_id)
        
        try:
            query = f"UPDATE insights SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def delete_insight(self, insight_id: int) -> bool:
        """Delete an insight"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM insights WHERE id = ?", (insight_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    # =========================================================================
    # Meta Knowledge Operations
    # =========================================================================
    
    def list_meta_knowledge(self, limit: int = 50, meta_type: str = None) -> List[Dict]:
        """List meta-knowledge entries"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            if meta_type:
                results = cursor.execute("""
                    SELECT id, timestamp, meta_type, description, observation,
                           conclusion, action_taken, confidence, validated
                    FROM meta_knowledge
                    WHERE meta_type = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (meta_type, limit)).fetchall()
            else:
                results = cursor.execute("""
                    SELECT id, timestamp, meta_type, description, observation,
                           conclusion, action_taken, confidence, validated
                    FROM meta_knowledge
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,)).fetchall()
            
            return [dict(row) for row in results]
        finally:
            conn.close()
    
    # =========================================================================
    # Reflection Queue Operations
    # =========================================================================
    
    def get_reflection_queue(self, limit: int = 50) -> List[Dict]:
        """Get pending reflections"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            results = cursor.execute("""
                SELECT rq.id, rq.experience_id, rq.priority, rq.queued_at, rq.processed,
                       e.query, e.tools_used, e.outcome_success
                FROM reflection_queue rq
                LEFT JOIN experiences e ON rq.experience_id = e.id
                WHERE rq.processed = 0
                ORDER BY rq.priority DESC, rq.queued_at ASC
                LIMIT ?
            """, (limit,)).fetchall()
            
            queue = []
            for row in results:
                item = dict(row)
                if item.get('tools_used'):
                    try:
                        item['tools_used'] = json.loads(item['tools_used'])
                    except:
                        pass
                queue.append(item)
            
            return queue
        finally:
            conn.close()
    
    def delete_reflection(self, reflection_id: int) -> bool:
        """Delete a pending reflection from the queue (cancel it without processing)"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            # Only delete if not yet processed
            cursor.execute("""
                DELETE FROM reflection_queue 
                WHERE id = ? AND processed = 0
            """, (reflection_id,))
            
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
        finally:
            conn.close()
    
    def delete_all_pending_reflections(self) -> int:
        """Delete all pending reflections from the queue"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM reflection_queue WHERE processed = 0")
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
        finally:
            conn.close()
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict:
        """Get comprehensive intelligence statistics"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            # Experiences stats
            total_experiences = cursor.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
            successful_experiences = cursor.execute(
                "SELECT COUNT(*) FROM experiences WHERE outcome_success = 1"
            ).fetchone()[0]
            
            # Insights stats
            total_insights = cursor.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
            positive_constraints = cursor.execute(
                "SELECT COUNT(*) FROM insights WHERE constraint_type = 'positive' OR constraint_type IS NULL"
            ).fetchone()[0]
            negative_constraints = cursor.execute(
                "SELECT COUNT(*) FROM insights WHERE constraint_type = 'negative'"
            ).fetchone()[0]
            
            # Confidence stats
            avg_confidence = cursor.execute("SELECT AVG(confidence) FROM insights").fetchone()[0] or 0
            high_confidence = cursor.execute(
                "SELECT COUNT(*) FROM insights WHERE confidence >= 0.7"
            ).fetchone()[0]
            low_confidence = cursor.execute(
                "SELECT COUNT(*) FROM insights WHERE confidence < 0.3"
            ).fetchone()[0]
            
            # Pending reflections
            pending_reflections = cursor.execute(
                "SELECT COUNT(*) FROM reflection_queue WHERE processed = 0"
            ).fetchone()[0]
            
            # Recent activity (24h)
            recent_experiences = cursor.execute("""
                SELECT COUNT(*) FROM experiences 
                WHERE timestamp > datetime('now', '-24 hours')
            """).fetchone()[0]
            
            recent_insights = cursor.execute("""
                SELECT COUNT(*) FROM insights 
                WHERE created_at > datetime('now', '-24 hours')
            """).fetchone()[0]
            
            # Application stats
            total_applied = cursor.execute("SELECT SUM(times_applied) FROM insights").fetchone()[0] or 0
            total_helpful = cursor.execute("SELECT SUM(times_helpful) FROM insights").fetchone()[0] or 0
            total_failed = cursor.execute("SELECT SUM(times_failed) FROM insights").fetchone()[0] or 0
            
            # Meta-knowledge
            meta_count = cursor.execute("SELECT COUNT(*) FROM meta_knowledge").fetchone()[0]
            blind_spots = cursor.execute(
                "SELECT COUNT(*) FROM meta_knowledge WHERE meta_type = 'blind_spot'"
            ).fetchone()[0]
            
            # Most used tools in experiences
            tool_usage = {}
            tool_results = cursor.execute("SELECT tools_used FROM experiences WHERE tools_used IS NOT NULL").fetchall()
            for row in tool_results:
                try:
                    tools = json.loads(row['tools_used'])
                    if isinstance(tools, list):
                        for tool in tools:
                            tool_usage[tool] = tool_usage.get(tool, 0) + 1
                except:
                    pass
            top_tools = sorted(tool_usage.items(), key=lambda x: x[1], reverse=True)[:10]

            # Completion Guard lifetime stats
            completion_guard_counts: dict[str, int] = {}
            completion_guard_rows = cursor.execute("""
                SELECT raw_data
                FROM experiences
                WHERE raw_data IS NOT NULL
            """).fetchall()
            for row in completion_guard_rows:
                try:
                    raw_data = json.loads(row['raw_data'])
                    status = ((raw_data.get('completion_guard') or {}).get('status'))
                    if status:
                        completion_guard_counts[status] = completion_guard_counts.get(status, 0) + 1
                except Exception:
                    pass
            completion_guard_total = sum(completion_guard_counts.values())
            
            # Database size
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
            
            return {
                'experiences': {
                    'total': total_experiences,
                    'successful': successful_experiences,
                    'failed': total_experiences - successful_experiences,
                    'success_rate': round(successful_experiences / total_experiences * 100, 1) if total_experiences > 0 else 0,
                    'recent_24h': recent_experiences
                },
                'insights': {
                    'total': total_insights,
                    'positive': positive_constraints,
                    'negative': negative_constraints,
                    'high_confidence': high_confidence,
                    'low_confidence': low_confidence,
                    'avg_confidence': round(avg_confidence, 3),
                    'recent_24h': recent_insights
                },
                'application': {
                    'total_applied': total_applied,
                    'total_helpful': total_helpful,
                    'total_failed': total_failed,
                    'helpfulness_rate': round(total_helpful / total_applied * 100, 1) if total_applied > 0 else 0
                },
                'reflection': {
                    'pending': pending_reflections
                },
                'meta_knowledge': {
                    'total': meta_count,
                    'blind_spots': blind_spots
                },
                'completion_guard': {
                    'total': completion_guard_total,
                    'repaired': completion_guard_counts.get('repaired', 0),
                    'ticket_created': completion_guard_counts.get('ticket_created', 0),
                    'expired': completion_guard_counts.get('expired', 0),
                    'superseded': completion_guard_counts.get('superseded', 0),
                    'by_status': dict(sorted(completion_guard_counts.items(), key=lambda item: item[0]))
                },
                'top_tools': [{'name': t[0], 'count': t[1]} for t in top_tools],
                'db_size_bytes': db_size,
                'db_size_mb': round(db_size / (1024 * 1024), 2),
                'mode': self.mode
            }
        finally:
            conn.close()
    
    def get_tool_performance(self) -> List[Dict]:
        """Get performance metrics per tool from insights.
        
        Note: preferred_tools and avoided_tools are JSON fields that can be:
        - Dict format: {"tool_name": score} (older format)
        - List format: ["tool_name"] (newer format)
        We parse both to extract tool names and aggregate.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            # Get all insights with tool preferences
            rows = cursor.execute("""
                SELECT preferred_tools, avoided_tools, confidence
                FROM insights 
                WHERE preferred_tools IS NOT NULL OR avoided_tools IS NOT NULL
            """).fetchall()
            
            # Build tool performance map
            tools = {}
            
            def extract_tool_names(json_str):
                """Extract tool names from either dict or list JSON format"""
                if not json_str:
                    return []
                try:
                    parsed = json.loads(json_str)
                    if isinstance(parsed, dict):
                        # Dict format: {"tool_name": score}
                        return list(parsed.keys())
                    elif isinstance(parsed, list):
                        # List format: ["tool_name"]
                        return [t for t in parsed if isinstance(t, str) and t]
                    return []
                except (json.JSONDecodeError, TypeError):
                    return []
            
            for row in rows:
                confidence = row['confidence'] or 0.5
                
                # Parse preferred_tools (can be dict or list)
                pref_tools = extract_tool_names(row['preferred_tools'])
                for tool_name in pref_tools:
                    if tool_name not in tools:
                        tools[tool_name] = {'name': tool_name, 'prefer_count': 0, 'avoid_count': 0, 'conf_sum': 0}
                    tools[tool_name]['prefer_count'] += 1
                    tools[tool_name]['conf_sum'] += confidence
                
                # Parse avoided_tools (can be dict or list)
                avoid_tools = extract_tool_names(row['avoided_tools'])
                for tool_name in avoid_tools:
                    if tool_name not in tools:
                        tools[tool_name] = {'name': tool_name, 'prefer_count': 0, 'avoid_count': 0, 'conf_sum': 0}
                    tools[tool_name]['avoid_count'] += 1
            
            # Calculate net score and avg confidence
            result = []
            for tool in tools.values():
                total_refs = tool['prefer_count'] + tool['avoid_count']
                tool['net_score'] = tool['prefer_count'] - tool['avoid_count']
                tool['avg_confidence'] = round(tool['conf_sum'] / total_refs, 2) if total_refs > 0 else 0
                del tool['conf_sum']
                result.append(tool)
            
            return sorted(result, key=lambda x: x['net_score'], reverse=True)
        finally:
            conn.close()
