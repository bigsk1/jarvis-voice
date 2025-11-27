"""
Prometheus metrics for Jarvis Intelligence Layer
These metrics are exposed at /metrics via prometheus_client
"""

import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))

try:
    from prometheus_client import Gauge, Counter, Info
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    print("⚠️  prometheus_client not installed. Intelligence metrics disabled.")

# ============================================
# Define Prometheus Metrics
# ============================================

if PROMETHEUS_AVAILABLE:
    # Counters (always increasing)
    INTELLIGENCE_EXPERIENCES_TOTAL = Gauge(
        'jarvis_intelligence_experiences_total',
        'Total number of experiences recorded',
        ['mode']  # cloud or local
    )
    
    INTELLIGENCE_INSIGHTS_TOTAL = Gauge(
        'jarvis_intelligence_insights_total',
        'Total number of insights learned',
        ['mode', 'constraint_type']  # positive or negative
    )
    
    INTELLIGENCE_REFLECTIONS_PROCESSED = Counter(
        'jarvis_intelligence_reflections_processed_total',
        'Total reflections processed',
        ['mode']
    )
    
    INTELLIGENCE_INSIGHTS_APPLIED = Counter(
        'jarvis_intelligence_insights_applied_total',
        'Total times insights were applied to routing',
        ['mode']
    )
    
    # Gauges (can go up and down)
    INTELLIGENCE_PENDING_REFLECTIONS = Gauge(
        'jarvis_intelligence_pending_reflections',
        'Number of pending reflections in queue',
        ['mode']
    )
    
    INTELLIGENCE_AVG_CONFIDENCE = Gauge(
        'jarvis_intelligence_avg_confidence',
        'Average confidence across all insights',
        ['mode']
    )
    
    INTELLIGENCE_HELPFUL_RATIO = Gauge(
        'jarvis_intelligence_helpful_ratio',
        'Ratio of helpful vs total applied (times_helpful / times_applied)',
        ['mode']
    )
    
    INTELLIGENCE_ENABLED = Gauge(
        'jarvis_intelligence_enabled',
        'Whether intelligence layer is enabled (1=yes, 0=no)',
        ['mode']
    )
    
    # Info metric
    INTELLIGENCE_INFO = Info(
        'jarvis_intelligence',
        'Intelligence layer information'
    )


def update_intelligence_metrics(mode: str = 'cloud'):
    """
    Update all intelligence metrics from the database.
    Called periodically or on demand.
    
    Args:
        mode: 'cloud' or 'local'
    """
    if not PROMETHEUS_AVAILABLE:
        return
    
    try:
        from config_loader import load_config, get_config_value
        from intelligence import get_intelligence_layer
        
        load_config(mode=mode)
        
        # Check if enabled
        enabled = get_config_value('JARVIS_INTELLIGENCE', 'true').lower() == 'true'
        INTELLIGENCE_ENABLED.labels(mode=mode).set(1 if enabled else 0)
        
        if not enabled:
            return
        
        intel = get_intelligence_layer()
        cursor = intel.conn.cursor()
        
        # Experiences count
        experiences = cursor.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
        INTELLIGENCE_EXPERIENCES_TOTAL.labels(mode=mode).set(experiences)
        
        # Insights by type
        positive = cursor.execute(
            "SELECT COUNT(*) FROM insights WHERE constraint_type = 'positive' OR constraint_type IS NULL"
        ).fetchone()[0]
        negative = cursor.execute(
            "SELECT COUNT(*) FROM insights WHERE constraint_type = 'negative'"
        ).fetchone()[0]
        
        INTELLIGENCE_INSIGHTS_TOTAL.labels(mode=mode, constraint_type='positive').set(positive)
        INTELLIGENCE_INSIGHTS_TOTAL.labels(mode=mode, constraint_type='negative').set(negative)
        
        # Pending reflections
        pending = cursor.execute(
            "SELECT COUNT(*) FROM reflection_queue WHERE processed = 0"
        ).fetchone()[0]
        INTELLIGENCE_PENDING_REFLECTIONS.labels(mode=mode).set(pending)
        
        # Average confidence
        avg_conf = cursor.execute("SELECT AVG(confidence) FROM insights").fetchone()[0] or 0
        INTELLIGENCE_AVG_CONFIDENCE.labels(mode=mode).set(round(avg_conf, 3))
        
        # Helpful ratio
        total_applied = cursor.execute("SELECT SUM(times_applied) FROM insights").fetchone()[0] or 0
        total_helpful = cursor.execute("SELECT SUM(times_helpful) FROM insights").fetchone()[0] or 0
        
        if total_applied > 0:
            ratio = total_helpful / total_applied
        else:
            ratio = 0
        INTELLIGENCE_HELPFUL_RATIO.labels(mode=mode).set(round(ratio, 3))
        
        # Info
        INTELLIGENCE_INFO.info({
            'mode': mode,
            'db_path': str(intel.db_path),
            'experiences': str(experiences),
            'insights': str(positive + negative)
        })
        
    except Exception as e:
        print(f"⚠️  Failed to update intelligence metrics: {e}")


def increment_reflections_processed(mode: str = 'cloud'):
    """Increment the reflections processed counter."""
    if PROMETHEUS_AVAILABLE:
        INTELLIGENCE_REFLECTIONS_PROCESSED.labels(mode=mode).inc()


def increment_insights_applied(mode: str = 'cloud'):
    """Increment the insights applied counter."""
    if PROMETHEUS_AVAILABLE:
        INTELLIGENCE_INSIGHTS_APPLIED.labels(mode=mode).inc()

