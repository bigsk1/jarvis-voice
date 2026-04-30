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
from security_utils import redact_sensitive_data, redact_sensitive_text

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
                ("trigger_signals", "TEXT"),
                ("primary_intent", "TEXT"),
                ("preferred_tool_sequence", "TEXT"),
                ("supporting_tools", "TEXT"),
                ("sequence_required", "BOOLEAN DEFAULT 0"),
                ("reflection_provider", "TEXT"),
                ("reflection_model", "TEXT"),
                ("reflection_input_tokens", "INTEGER DEFAULT 0"),
                ("reflection_output_tokens", "INTEGER DEFAULT 0"),
                ("reflection_total_tokens", "INTEGER DEFAULT 0"),
                ("reflection_cost_usd", "REAL DEFAULT 0"),
                ("source_experience_id", "INTEGER"),
                ("source_web_conversation_id", "TEXT"),
                ("source_query", "TEXT"),
                ("source_tool_sequence", "TEXT"),
                ("source_reflection_json", "TEXT"),
            ]
            for col_name, col_def in new_columns:
                if col_name not in existing_columns:
                    cursor.execute(f"ALTER TABLE insights ADD COLUMN {col_name} {col_def}")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS insight_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    insight_id INTEGER NOT NULL,
                    experience_id INTEGER,
                    web_conversation_id TEXT,
                    query TEXT,
                    tool_sequence TEXT,
                    preferred_tool TEXT,
                    avoided_tool TEXT,
                    preferred_tool_sequence TEXT,
                    supporting_tools TEXT,
                    reflection_json TEXT,
                    confidence REAL,
                    confidence_delta REAL,
                    action TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_insight_evidence_insight ON insight_evidence(insight_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_insight_evidence_experience ON insight_evidence(experience_id)")
            cursor.execute("""
                UPDATE insights
                SET source_experience_id = COALESCE(
                        source_experience_id,
                        (
                            SELECT e.experience_id
                            FROM insight_evidence e
                            WHERE e.insight_id = insights.id
                              AND e.experience_id IS NOT NULL
                            ORDER BY e.id DESC
                            LIMIT 1
                        )
                    ),
                    source_web_conversation_id = COALESCE(
                        NULLIF(source_web_conversation_id, ''),
                        (
                            SELECT e.web_conversation_id
                            FROM insight_evidence e
                            WHERE e.insight_id = insights.id
                              AND e.web_conversation_id IS NOT NULL
                              AND e.web_conversation_id != ''
                            ORDER BY e.id DESC
                            LIMIT 1
                        )
                    ),
                    source_query = COALESCE(
                        NULLIF(source_query, ''),
                        (
                            SELECT e.query
                            FROM insight_evidence e
                            WHERE e.insight_id = insights.id
                              AND e.query IS NOT NULL
                              AND e.query != ''
                            ORDER BY e.id DESC
                            LIMIT 1
                        )
                    ),
                    source_tool_sequence = COALESCE(
                        NULLIF(source_tool_sequence, ''),
                        (
                            SELECT e.tool_sequence
                            FROM insight_evidence e
                            WHERE e.insight_id = insights.id
                              AND e.tool_sequence IS NOT NULL
                              AND e.tool_sequence != ''
                            ORDER BY e.id DESC
                            LIMIT 1
                        )
                    ),
                    source_reflection_json = COALESCE(
                        NULLIF(source_reflection_json, ''),
                        (
                            SELECT e.reflection_json
                            FROM insight_evidence e
                            WHERE e.insight_id = insights.id
                              AND e.reflection_json IS NOT NULL
                              AND e.reflection_json != ''
                            ORDER BY e.id DESC
                            LIMIT 1
                        )
                    )
                WHERE EXISTS (
                    SELECT 1 FROM insight_evidence e WHERE e.insight_id = insights.id
                )
                  AND (
                    source_experience_id IS NULL
                    OR source_web_conversation_id IS NULL OR source_web_conversation_id = ''
                    OR source_query IS NULL OR source_query = ''
                    OR source_tool_sequence IS NULL OR source_tool_sequence = ''
                    OR source_reflection_json IS NULL OR source_reflection_json = ''
                  )
            """)
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
        if exp.get('query'):
            exp['query'] = redact_sensitive_text(str(exp['query']))
        if exp.get('context_summary'):
            exp['context_summary'] = redact_sensitive_text(str(exp['context_summary']))
        exp['tools_used'] = self._parse_json_value(exp.get('tools_used'), exp.get('tools_used'))
        exp['tool_sequence'] = self._parse_json_value(exp.get('tool_sequence'), exp.get('tool_sequence'))

        raw_data = redact_sensitive_data(self._parse_json_value(exp.get('raw_data'), {}))
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
        insight = redact_sensitive_data(dict(row))
        return self._add_time_display(insight, ['created_at', 'updated_at', 'last_applied'])

    def _hydrate_evidence(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert an insight evidence row into API shape."""
        evidence = redact_sensitive_data(dict(row))
        evidence['tool_sequence'] = self._parse_json_value(evidence.get('tool_sequence'), [])
        evidence['preferred_tool_sequence'] = self._parse_json_value(evidence.get('preferred_tool_sequence'), [])
        evidence['supporting_tools'] = self._parse_json_value(evidence.get('supporting_tools'), [])
        evidence['reflection_json'] = self._parse_json_value(evidence.get('reflection_json'), evidence.get('reflection_json'))
        return self._add_time_display(evidence, ['created_at'])

    @staticmethod
    def _safe_json_array_expr(column: str) -> str:
        return f"CASE WHEN {column} IS NOT NULL AND json_valid({column}) THEN {column} ELSE '[]' END"

    @staticmethod
    def _safe_json_object_expr(column: str) -> str:
        return f"CASE WHEN {column} IS NOT NULL AND json_valid({column}) THEN {column} ELSE '{{}}' END"

    @classmethod
    def _experience_tool_count_expr(cls, alias: str = "e") -> str:
        tools_json = cls._safe_json_array_expr(f"{alias}.tools_used")
        return f"COALESCE(json_array_length({tools_json}), 0)"

    @classmethod
    def _experience_completion_guard_status_expr(cls, alias: str = "e") -> str:
        raw_json = cls._safe_json_object_expr(f"{alias}.raw_data")
        return (
            "COALESCE(NULLIF("
            f"json_extract({raw_json}, '$.completion_guard.status')"
            ", ''), 'none')"
        )

    @classmethod
    def _experience_where_sql(
        cls,
        *,
        success_only: bool = None,
        tool_count: str = None,
        tool: str = None,
        completion_guard_status: str = None,
    ) -> tuple[str, list[Any]]:
        where_clauses = []
        params: list[Any] = []

        if success_only is True:
            where_clauses.append("e.outcome_success = 1")
        elif success_only is False:
            where_clauses.append("e.outcome_success = 0")

        tool_count_expr = cls._experience_tool_count_expr("e")
        if tool_count == "none":
            where_clauses.append(f"{tool_count_expr} = 0")
        elif tool_count == "single":
            where_clauses.append(f"{tool_count_expr} = 1")
        elif tool_count == "multi":
            where_clauses.append(f"{tool_count_expr} > 1")

        if tool:
            tools_json = cls._safe_json_array_expr("e.tools_used")
            where_clauses.append(f"EXISTS (SELECT 1 FROM json_each({tools_json}) WHERE value = ?)")
            params.append(tool)

        if completion_guard_status:
            status_expr = cls._experience_completion_guard_status_expr("e")
            where_clauses.append(f"{status_expr} = ?")
            params.append(completion_guard_status)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        return where_sql, params

    @classmethod
    def _experience_order_sql(cls, sort: str = "date") -> str:
        tool_count_expr = cls._experience_tool_count_expr("e")
        status_expr = cls._experience_completion_guard_status_expr("e")
        completion_guard_rank = (
            f"CASE {status_expr} "
            "WHEN 'repaired' THEN 0 "
            "WHEN 'ticket_created' THEN 1 "
            "WHEN 'tighten_only' THEN 2 "
            "WHEN 'cancelled' THEN 3 "
            "WHEN 'expired' THEN 4 "
            "WHEN 'superseded' THEN 5 "
            "WHEN 'accepted' THEN 6 "
            "WHEN 'auto_accepted' THEN 7 "
            "WHEN 'none' THEN 8 "
            "ELSE 9 END"
        )
        sort_map = {
            "turns": "COALESCE(e.turns_taken, 1) DESC, e.timestamp DESC, e.id DESC",
            "tools": f"{tool_count_expr} DESC, e.timestamp DESC, e.id DESC",
            "completion_guard": f"{completion_guard_rank} ASC, e.timestamp DESC, e.id DESC",
            "date": "e.timestamp DESC, e.id DESC",
        }
        return sort_map.get(sort, sort_map["date"])

    @staticmethod
    def _insight_confidence_bounds(tier: str | None) -> tuple[float | None, float | None]:
        tiers = {
            "elite": (0.96, None),
            "high": (0.85, 0.96),
            "good": (0.75, 0.85),
            "medium": (0.50, 0.75),
            "low": (None, 0.50),
        }
        return tiers.get(tier or "", (None, None))

    @staticmethod
    def _insight_order_sql(sort: str = "updated") -> str:
        has_preferred = "CASE WHEN preferred_tools IS NOT NULL AND preferred_tools NOT IN ('', '{}', '[]', 'null') THEN 0 ELSE 1 END"
        has_avoided = "CASE WHEN avoided_tools IS NOT NULL AND avoided_tools NOT IN ('', '{}', '[]', 'null') THEN 0 ELSE 1 END"
        sort_map = {
            "preferred": f"{has_preferred} ASC, confidence DESC, times_applied DESC, id DESC",
            "avoided": f"{has_avoided} ASC, confidence DESC, times_applied DESC, id DESC",
            "confidence": "confidence DESC, times_applied DESC, id DESC",
            "helpful": "times_helpful DESC, confidence DESC, id DESC",
            "applied": "times_applied DESC, confidence DESC, id DESC",
            "updated": "COALESCE(updated_at, created_at) DESC, id DESC",
        }
        return sort_map.get(sort, sort_map["updated"])
    
    # =========================================================================
    # Experiences Operations
    # =========================================================================
    
    def list_experiences(
        self,
        limit: int = 100,
        offset: int = 0,
        success_only: bool = None,
        sort: str = "date",
        tool_count: str = None,
        tool: str = None,
        completion_guard_status: str = None,
    ) -> tuple[List[Dict], int]:
        """List experiences with optional filtering"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            limit = max(1, min(int(limit), 200))
            offset = max(0, int(offset))
            where_sql, params = self._experience_where_sql(
                success_only=success_only,
                tool_count=tool_count,
                tool=tool,
                completion_guard_status=completion_guard_status,
            )
            order_sql = self._experience_order_sql(sort)
            total = cursor.execute(f"""
                SELECT COUNT(*)
                FROM experiences e
                {where_sql}
            """, params).fetchone()[0]
            
            results = cursor.execute(f"""
                SELECT id, timestamp, query, context_summary, tools_used, 
                       tool_sequence, turns_taken, final_tool,
                       outcome_success, user_satisfied, error_occurred,
                       raw_data,
                       CASE WHEN query_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM experiences e
                {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
            """, (*params, limit, offset)).fetchall()

            return [self._hydrate_experience(row, include_raw=False) for row in results], total
        finally:
            conn.close()

    def get_experience_summary(self) -> Dict[str, Any]:
        """Return lightweight counts/facets for the Experiences sidebar."""
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            tool_count_expr = self._experience_tool_count_expr("e")
            status_expr = self._experience_completion_guard_status_expr("e")
            tools_json = self._safe_json_array_expr("e.tools_used")

            total = cursor.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
            success = cursor.execute("SELECT COUNT(*) FROM experiences WHERE outcome_success = 1").fetchone()[0]
            no_tools = cursor.execute(f"SELECT COUNT(*) FROM experiences e WHERE {tool_count_expr} = 0").fetchone()[0]
            single_tool = cursor.execute(f"SELECT COUNT(*) FROM experiences e WHERE {tool_count_expr} = 1").fetchone()[0]
            multi_tool = cursor.execute(f"SELECT COUNT(*) FROM experiences e WHERE {tool_count_expr} > 1").fetchone()[0]

            tool_rows = cursor.execute(f"""
                SELECT value AS tool, COUNT(*) AS count
                FROM experiences e, json_each({tools_json})
                WHERE value IS NOT NULL AND value != ''
                GROUP BY value
                ORDER BY value ASC
            """).fetchall()

            completion_guard_rows = cursor.execute(f"""
                SELECT {status_expr} AS status, COUNT(*) AS count
                FROM experiences e
                GROUP BY status
                ORDER BY status ASC
            """).fetchall()

            return {
                "total": total,
                "success": success,
                "failed": total - success,
                "tool_count": {
                    "all": total,
                    "none": no_tools,
                    "single": single_tool,
                    "multi": multi_tool,
                },
                "tools": [{"name": row["tool"], "count": row["count"]} for row in tool_rows],
                "completion_guard": {
                    row["status"] or "none": row["count"]
                    for row in completion_guard_rows
                },
            }
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
    
    def search_experiences(self, query: str, limit: int = 50, sort: str = "date") -> List[Dict]:
        """Search experiences by query text"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            order_sql = self._experience_order_sql(sort)
            results = cursor.execute("""
                SELECT id, timestamp, query, context_summary, tools_used, 
                       tool_sequence, turns_taken, final_tool,
                       outcome_success, user_satisfied, error_occurred,
                       raw_data,
                       CASE WHEN query_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM experiences e
                WHERE e.query LIKE ? OR e.context_summary LIKE ? OR e.tools_used LIKE ?
                ORDER BY """ + order_sql + """
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
            # Also unlink related audit/queue rows so provenance does not point
            # at a deleted experience.
            cursor.execute("DELETE FROM reflection_queue WHERE experience_id = ?", (experience_id,))
            cursor.execute("UPDATE insight_evidence SET experience_id = NULL WHERE experience_id = ?", (experience_id,))
            cursor.execute("UPDATE insights SET source_experience_id = NULL WHERE source_experience_id = ?", (experience_id,))
            cursor.execute("DELETE FROM experiences WHERE id = ?", (experience_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    # =========================================================================
    # Insights Operations
    # =========================================================================
    
    def list_insights(
        self,
        limit: int = 100,
        offset: int = 0,
        constraint_type: str = None,
        min_confidence: float = None,
        confidence_tier: str = None,
        sort: str = "updated",
    ) -> tuple[List[Dict], int]:
        """List insights with optional filtering"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            limit = max(1, min(int(limit), 200))
            offset = max(0, int(offset))
            where_clauses = []
            params = []
            
            if constraint_type:
                where_clauses.append("(constraint_type = ? OR (constraint_type IS NULL AND ? = 'positive'))")
                params.extend([constraint_type, constraint_type])
            
            if min_confidence is not None:
                where_clauses.append("confidence >= ?")
                params.append(min_confidence)

            confidence_min, confidence_max = self._insight_confidence_bounds(confidence_tier)
            if confidence_min is not None:
                where_clauses.append("confidence >= ?")
                params.append(confidence_min)
            if confidence_max is not None:
                where_clauses.append("confidence < ?")
                params.append(confidence_max)
            
            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            order_sql = self._insight_order_sql(sort)
            total = cursor.execute(f"""
                SELECT COUNT(*)
                FROM insights
                {where_sql}
            """, params).fetchone()[0]
            
            results = cursor.execute(f"""
                SELECT id, created_at, updated_at, insight_type, description,
                       constraint_type, applies_to_pattern, confidence, evidence_count,
                       times_applied, times_helpful, times_failed, consecutive_failures,
                       last_applied, last_outcome,
                       preferred_tools, avoided_tools, generalizability,
                       preferred_tool_sequence, supporting_tools, sequence_required,
                       trigger_signals, primary_intent,
                       source_experience_id, source_web_conversation_id,
                       source_query, source_tool_sequence,
                       reflection_provider, reflection_model,
                       reflection_input_tokens, reflection_output_tokens,
                       reflection_total_tokens, reflection_cost_usd,
                       CASE WHEN insight_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM insights
                {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
            """, (*params, limit, offset)).fetchall()
            
            return [self._hydrate_insight(row) for row in results], total
        finally:
            conn.close()

    def get_insight_summary(self) -> Dict[str, Any]:
        """Return lightweight counts/facets for the Insights sidebar."""
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            total = cursor.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
            positive = cursor.execute("""
                SELECT COUNT(*)
                FROM insights
                WHERE constraint_type = 'positive' OR constraint_type IS NULL
            """).fetchone()[0]
            negative = cursor.execute("""
                SELECT COUNT(*)
                FROM insights
                WHERE constraint_type = 'negative'
            """).fetchone()[0]
            elite = cursor.execute("SELECT COUNT(*) FROM insights WHERE confidence >= 0.96").fetchone()[0]
            high = cursor.execute("SELECT COUNT(*) FROM insights WHERE confidence >= 0.85 AND confidence < 0.96").fetchone()[0]
            good = cursor.execute("SELECT COUNT(*) FROM insights WHERE confidence >= 0.75 AND confidence < 0.85").fetchone()[0]
            medium = cursor.execute("SELECT COUNT(*) FROM insights WHERE confidence >= 0.50 AND confidence < 0.75").fetchone()[0]
            low = cursor.execute("SELECT COUNT(*) FROM insights WHERE confidence < 0.50").fetchone()[0]

            return {
                "total": total,
                "positive": positive,
                "negative": negative,
                "confidence": {
                    "elite": elite,
                    "high": high,
                    "good": good,
                    "medium": medium,
                    "low": low,
                },
            }
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
                       preferred_tool_sequence, supporting_tools, sequence_required,
                       trigger_signals, primary_intent,
                       source_experience_id, source_web_conversation_id,
                       source_query, source_tool_sequence, source_reflection_json,
                       reflection_provider, reflection_model,
                       reflection_input_tokens, reflection_output_tokens,
                       reflection_total_tokens, reflection_cost_usd,
                       CASE WHEN insight_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM insights
                WHERE id = ?
            """, (insight_id,)).fetchone()
            
            if not result:
                return None
            insight = self._hydrate_insight(result)
            insight['evidence'] = self.get_insight_evidence(insight_id)
            return insight
        finally:
            conn.close()
    
    def search_insights(self, query: str, limit: int = 50, sort: str = "updated") -> List[Dict]:
        """Search insights by description or pattern"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            order_sql = self._insight_order_sql(sort)
            normalized_query = (query or "").strip()
            id_match = None
            if normalized_query:
                numeric_candidate = normalized_query[1:] if normalized_query.startswith("#") else normalized_query
                if numeric_candidate.isdigit():
                    id_match = int(numeric_candidate)

            search_params = [
                f"%{normalized_query}%",
                f"%{normalized_query}%",
                f"%{normalized_query}%",
                f"%{normalized_query}%",
                f"%{normalized_query}%",
                f"%{normalized_query}%",
            ]
            where_clauses = [
                "description LIKE ?",
                "applies_to_pattern LIKE ?",
                "preferred_tools LIKE ?",
                "avoided_tools LIKE ?",
                "source_web_conversation_id LIKE ?",
                "source_query LIKE ?",
            ]
            if id_match is not None:
                where_clauses.insert(0, "id = ?")
                search_params.insert(0, id_match)

            results = cursor.execute(f"""
                SELECT id, created_at, updated_at, insight_type, description,
                       constraint_type, applies_to_pattern, confidence, evidence_count,
                       times_applied, times_helpful, times_failed,
                       preferred_tools, avoided_tools,
                       preferred_tool_sequence, supporting_tools, sequence_required,
                       trigger_signals, primary_intent,
                       source_experience_id, source_web_conversation_id,
                       reflection_provider, reflection_model,
                       reflection_input_tokens, reflection_output_tokens,
                       reflection_total_tokens, reflection_cost_usd,
                       CASE WHEN insight_embedding IS NOT NULL THEN 1 ELSE 0 END as has_embedding
                FROM insights
                WHERE {" OR ".join(where_clauses)}
                ORDER BY """ + order_sql + """
                LIMIT ?
            """, (*search_params, limit)).fetchall()
            
            return [self._hydrate_insight(row) for row in results]
        finally:
            conn.close()

    def get_insight_evidence(self, insight_id: int, limit: int = 25) -> List[Dict]:
        """List source experiences/reflections that created or reinforced an insight."""
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            table_exists = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'insight_evidence'"
            ).fetchone()
            if not table_exists:
                return []

            rows = cursor.execute("""
                SELECT id, insight_id, experience_id, web_conversation_id, query,
                       tool_sequence, preferred_tool, avoided_tool,
                       preferred_tool_sequence, supporting_tools, reflection_json,
                       confidence, confidence_delta, action, created_at
                FROM insight_evidence
                WHERE insight_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
            """, (insight_id, limit)).fetchall()
            return [self._hydrate_evidence(row) for row in rows]
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
            cursor.execute("DELETE FROM insight_evidence WHERE insight_id = ?", (insight_id,))
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
