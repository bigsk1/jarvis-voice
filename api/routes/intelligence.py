"""Intelligence Layer API endpoints for monitoring and metrics"""

from fastapi import APIRouter
import sys
from pathlib import Path
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


@router.get("/stats")
async def get_intelligence_stats():
    """Get current intelligence layer statistics."""
    try:
        from intelligence_hooks import get_learning_stats
        stats = get_learning_stats()
        return {
            "status": "ok",
            **stats
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/health")
async def get_intelligence_health():
    """Get intelligence layer health status."""
    try:
        from intelligence import get_intelligence_layer
        from config_loader import load_config, get_config_value
        
        load_config()
        
        intel = get_intelligence_layer()
        stats = intel.get_stats()
        
        # Check for issues
        issues = []
        
        if stats['insights'] == 0:
            issues.append("No insights learned yet")
        
        if stats['pending_reflections'] > 10:
            issues.append(f"Many pending reflections: {stats['pending_reflections']}")
        
        if stats['avg_insight_confidence'] < 0.3 and stats['insights'] > 0:
            issues.append(f"Low average confidence: {stats['avg_insight_confidence']:.2f}")
        
        return {
            "status": "healthy" if not issues else "degraded",
            "enabled": get_config_value('JARVIS_INTELLIGENCE', 'true').lower() == 'true',
            "experiences": stats['experiences'],
            "insights": stats['insights'],
            "pending_reflections": stats['pending_reflections'],
            "avg_confidence": stats['avg_insight_confidence'],
            "db_path": stats['db_path'],
            "issues": issues
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/insights")
async def get_recent_insights():
    """Get recent insights for inspection."""
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        cursor = intel.conn.cursor()
        
        cursor.execute("""
            SELECT id, insight_type, description, constraint_type, 
                   applies_to_pattern, confidence, evidence_count,
                   times_applied, times_helpful, times_failed,
                   created_at
            FROM insights
            ORDER BY created_at DESC
            LIMIT 20
        """)
        
        insights = []
        for row in cursor.fetchall():
            insights.append({
                "id": row['id'],
                "type": row['insight_type'],
                "description": row['description'],
                "constraint": row['constraint_type'] or 'positive',
                "applies_to": row['applies_to_pattern'],
                "confidence": row['confidence'],
                "evidence_count": row['evidence_count'],
                "times_applied": row['times_applied'],
                "times_helpful": row['times_helpful'],
                "times_failed": row['times_failed'],
                "created_at": row['created_at']
            })
        
        return {
            "status": "ok",
            "count": len(insights),
            "insights": insights
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/experiences")
async def get_recent_experiences():
    """Get recent experiences for inspection."""
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        cursor = intel.conn.cursor()
        
        cursor.execute("""
            SELECT id, query, tools_used, turns_taken, 
                   outcome_success, user_satisfied, timestamp
            FROM experiences
            ORDER BY timestamp DESC
            LIMIT 20
        """)
        
        experiences = []
        for row in cursor.fetchall():
            tools = json.loads(row['tools_used']) if row['tools_used'] else []
            experiences.append({
                "id": row['id'],
                "query": row['query'][:100],
                "tools_used": tools,
                "turns": row['turns_taken'],
                "success": row['outcome_success'],
                "satisfied": row['user_satisfied'],
                "timestamp": row['timestamp']
            })
        
        return {
            "status": "ok",
            "count": len(experiences),
            "experiences": experiences
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/metrics")
async def get_intelligence_metrics():
    """
    Get Prometheus-style metrics for Grafana.
    Returns metrics in a format easy to parse.
    """
    try:
        from intelligence import get_intelligence_layer
        from config_loader import load_config, get_config_value
        
        load_config()
        
        intel = get_intelligence_layer()
        cursor = intel.conn.cursor()
        
        # Basic counts
        experiences = cursor.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
        insights = cursor.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
        pending = cursor.execute("SELECT COUNT(*) FROM reflection_queue WHERE processed = 0").fetchone()[0]
        
        # Constraint types
        positive = cursor.execute("SELECT COUNT(*) FROM insights WHERE constraint_type = 'positive' OR constraint_type IS NULL").fetchone()[0]
        negative = cursor.execute("SELECT COUNT(*) FROM insights WHERE constraint_type = 'negative'").fetchone()[0]
        
        # Confidence stats
        avg_confidence = cursor.execute("SELECT AVG(confidence) FROM insights").fetchone()[0] or 0
        low_confidence = cursor.execute("SELECT COUNT(*) FROM insights WHERE confidence < 0.3").fetchone()[0]
        high_confidence = cursor.execute("SELECT COUNT(*) FROM insights WHERE confidence >= 0.7").fetchone()[0]
        
        # Application stats
        total_applied = cursor.execute("SELECT SUM(times_applied) FROM insights").fetchone()[0] or 0
        total_helpful = cursor.execute("SELECT SUM(times_helpful) FROM insights").fetchone()[0] or 0
        total_failed = cursor.execute("SELECT SUM(times_failed) FROM insights").fetchone()[0] or 0
        
        # Recent activity (last 24h)
        recent_experiences = cursor.execute("""
            SELECT COUNT(*) FROM experiences 
            WHERE timestamp > datetime('now', '-24 hours')
        """).fetchone()[0]
        
        recent_insights = cursor.execute("""
            SELECT COUNT(*) FROM insights 
            WHERE created_at > datetime('now', '-24 hours')
        """).fetchone()[0]
        
        return {
            "status": "ok",
            "metrics": {
                # Counts
                "jarvis_intelligence_experiences_total": experiences,
                "jarvis_intelligence_insights_total": insights,
                "jarvis_intelligence_pending_reflections": pending,
                
                # Constraint breakdown
                "jarvis_intelligence_positive_constraints": positive,
                "jarvis_intelligence_negative_constraints": negative,
                
                # Confidence
                "jarvis_intelligence_avg_confidence": round(avg_confidence, 3),
                "jarvis_intelligence_low_confidence_count": low_confidence,
                "jarvis_intelligence_high_confidence_count": high_confidence,
                
                # Application stats
                "jarvis_intelligence_total_applied": total_applied,
                "jarvis_intelligence_total_helpful": total_helpful,
                "jarvis_intelligence_total_failed": total_failed,
                "jarvis_intelligence_helpfulness_ratio": round(total_helpful / max(total_applied, 1), 3),
                
                # Recent activity
                "jarvis_intelligence_experiences_24h": recent_experiences,
                "jarvis_intelligence_insights_24h": recent_insights,
                
                # Config
                "jarvis_intelligence_enabled": 1 if get_config_value('JARVIS_INTELLIGENCE', 'true').lower() == 'true' else 0
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/logs/recent")
async def get_recent_logs():
    """Get recent intelligence log entries."""
    try:
        log_dir = Path(__file__).parent.parent.parent / "logs" / "intelligence"
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"intelligence-{today}.jsonl"
        
        if not log_file.exists():
            return {
                "status": "ok",
                "count": 0,
                "logs": [],
                "message": "No logs for today yet"
            }
        
        logs = []
        with open(log_file, 'r') as f:
            for line in f.readlines()[-50:]:  # Last 50 entries
                try:
                    entry = json.loads(line)
                    logs.append(entry)
                except json.JSONDecodeError:
                    continue
        
        return {
            "status": "ok",
            "count": len(logs),
            "log_file": str(log_file),
            "logs": logs
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/reflections")
async def get_pending_reflections(limit: int = 50):
    """Get pending reflections in the queue.
    
    Returns experiences waiting to be processed for insight generation.
    Use DELETE to cancel reflections you don't want processed.
    """
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        if not intel:
            return {"status": "error", "error": "Intelligence layer not available"}
        
        cursor = intel.conn.cursor()
        cursor.execute("""
            SELECT rq.id, rq.experience_id, rq.priority, rq.queued_at, rq.processed,
                   e.query, e.tools_used, e.outcome_success
            FROM reflection_queue rq
            LEFT JOIN experiences e ON rq.experience_id = e.id
            WHERE rq.processed = 0
            ORDER BY rq.priority DESC, rq.queued_at ASC
            LIMIT ?
        """, (limit,))
        
        reflections = []
        for row in cursor.fetchall():
            tools = json.loads(row['tools_used']) if row['tools_used'] else []
            reflections.append({
                "id": row['id'],
                "experience_id": row['experience_id'],
                "query": row['query'][:100] if row['query'] else None,
                "tools_used": tools,
                "success": bool(row['outcome_success']),
                "priority": row['priority'],
                "queued_at": row['queued_at']
            })
        
        return {
            "status": "ok",
            "count": len(reflections),
            "reflections": reflections
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.delete("/reflections/{reflection_id}")
async def delete_reflection(reflection_id: int):
    """Cancel a pending reflection (don't process it for insights).
    
    Use this when you don't want to generate insights from an experience,
    e.g., during testing/development or for known bad data.
    """
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        if not intel:
            return {"status": "error", "error": "Intelligence layer not available"}
        
        cursor = intel.conn.cursor()
        cursor.execute("""
            DELETE FROM reflection_queue 
            WHERE id = ? AND processed = 0
        """, (reflection_id,))
        
        deleted = cursor.rowcount > 0
        intel.conn.commit()
        
        if deleted:
            return {
                "status": "ok",
                "message": f"Reflection {reflection_id} cancelled"
            }
        else:
            return {
                "status": "error",
                "error": f"Reflection {reflection_id} not found or already processed"
            }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.delete("/reflections")
async def delete_all_reflections():
    """Cancel ALL pending reflections.
    
    Use with caution - clears the entire reflection queue.
    Useful after testing sessions or to reset the queue.
    """
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        if not intel:
            return {"status": "error", "error": "Intelligence layer not available"}
        
        cursor = intel.conn.cursor()
        cursor.execute("DELETE FROM reflection_queue WHERE processed = 0")
        deleted_count = cursor.rowcount
        intel.conn.commit()
        
        return {
            "status": "ok",
            "deleted": deleted_count,
            "message": f"Cancelled {deleted_count} pending reflections"
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/reflect")
async def trigger_reflection_endpoint(batch_size: int = 5):
    """Manually trigger reflection processing."""
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        if not intel:
            return {
                "status": "error",
                "error": "Intelligence layer not available"
            }
        
        # Directly await the async method (we're already in async context)
        processed = await intel.process_reflection_queue(batch_size=batch_size)
        
        return {
            "status": "ok",
            "processed": processed,
            "message": f"Processed {processed} pending reflections"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/evaluate")
async def evaluate_learning_endpoint():
    """Run meta-cognition evaluation on learning quality."""
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        if not intel:
            return {
                "status": "error",
                "error": "Intelligence layer not available"
            }
        
        # Directly await the async method
        evaluation = await intel.evaluate_learning_quality()
        
        return {
            "status": "ok",
            **evaluation
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


# ============================================
# MAINTENANCE JOBS
# ============================================

@router.post("/maintenance/decay")
async def run_decay_job_endpoint(force: bool = False, dry_run: bool = False):
    """Run the confidence decay job.
    
    Reduces confidence of stale/unused insights.
    Uses INTELLIGENCE_DECAY_RATE from config.
    """
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        if not intel:
            return {"status": "error", "error": "Intelligence layer not available"}
        
        result = await intel.run_decay_job(force=force, dry_run=dry_run)
        
        return {
            "status": "ok",
            "job": "decay",
            **result
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/maintenance/anomaly")
async def run_anomaly_detection_endpoint():
    """Run anomaly detection on recent experiences.
    
    Flags experiences that deviate significantly from norms.
    Uses INTELLIGENCE_ANOMALY_THRESHOLD from config.
    """
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        if not intel:
            return {"status": "error", "error": "Intelligence layer not available"}
        
        result = await intel.run_anomaly_detection()
        
        return {
            "status": "ok",
            "job": "anomaly",
            **result
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/maintenance/meta-cognition")
async def run_meta_cognition_endpoint():
    """Run meta-cognition analysis.
    
    Higher-level reflection on the learning process:
    - Detects blind spots (repeated failures)
    - Detects over-generalization
    - Assesses learning quality
    
    Populates meta_knowledge table with findings.
    """
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        if not intel:
            return {"status": "error", "error": "Intelligence layer not available"}
        
        result = await intel.run_meta_cognition()
        
        return {
            "status": "ok",
            "job": "meta_cognition",
            **result
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/maintenance/all")
async def run_all_maintenance_endpoint(force: bool = False, dry_run: bool = False):
    """Run all maintenance jobs (decay, anomaly, meta-cognition)."""
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        if not intel:
            return {"status": "error", "error": "Intelligence layer not available"}
        
        result = await intel.run_all_maintenance(force=force, dry_run=dry_run)
        
        return {
            "status": "ok",
            "job": "all",
            **result
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/meta-knowledge")
async def get_meta_knowledge():
    """Get recent meta-knowledge findings (blind spots, over-generalizations, etc.)."""
    try:
        from intelligence import get_intelligence_layer
        
        intel = get_intelligence_layer()
        if not intel:
            return {"status": "error", "error": "Intelligence layer not available"}
        
        cursor = intel.conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, meta_type, description, observation, 
                   conclusion, action_taken, confidence, validated
            FROM meta_knowledge
            ORDER BY timestamp DESC
            LIMIT 20
        """)
        
        rows = cursor.fetchall()
        findings = []
        for row in rows:
            findings.append({
                'id': row['id'],
                'timestamp': row['timestamp'],
                'meta_type': row['meta_type'],
                'description': row['description'],
                'observation': row['observation'],
                'conclusion': row['conclusion'],
                'action_taken': row['action_taken'],
                'confidence': row['confidence'],
                'validated': bool(row['validated'])
            })
        
        return {
            "status": "ok",
            "count": len(findings),
            "findings": findings
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
