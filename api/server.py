#!/usr/bin/env python3
"""
Jarvis Proactive Assistant API Server
FastAPI server for webhooks, alerts, reminders, and proactive notifications
"""

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.routes import alerts_router, reminders_router, health_router, voice_router
from api.routes.intelligence import router as intelligence_router

# Prometheus metrics
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest, REGISTRY
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    print("⚠️  prometheus-fastapi-instrumentator not installed. Metrics disabled.")
    print("   To enable: pip install prometheus-fastapi-instrumentator")

# Intelligence metrics
try:
    from api.metrics import update_intelligence_metrics, PROMETHEUS_AVAILABLE as INTEL_METRICS_AVAILABLE
    print("✅ Intelligence metrics module loaded")
except ImportError as e:
    INTEL_METRICS_AVAILABLE = False
    print(f"⚠️  Intelligence metrics not available: {e}")

# Create FastAPI app
app = FastAPI(
    title="Jarvis Proactive Assistant API",
    description="REST API for alerts, reminders, and proactive notifications",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware (for web UIs in the future)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Localhost only in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Prometheus metrics FIRST (before routes)
if PROMETHEUS_AVAILABLE:
    # Create instrumentator
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=False,  # Don't respect env var, always enable
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics", "/docs", "/redoc", "/openapi.json"],
        inprogress_name="jarvis_api_requests_inprogress",
        inprogress_labels=True,
    )
    
    # Instrument the app (must happen before routes are added for proper wrapping)
    instrumentator.instrument(app)
    
    print("✅ Prometheus instrumentator initialized")
else:
    print("⚠️  Prometheus metrics disabled (library not installed)")

# Register routers AFTER instrumentator is initialized
app.include_router(health_router)
app.include_router(alerts_router)
app.include_router(reminders_router)
app.include_router(voice_router)
app.include_router(intelligence_router)

# Add /metrics endpoint LAST
if PROMETHEUS_AVAILABLE:
    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        """Expose Prometheus metrics including intelligence layer stats"""
        # Update intelligence metrics before generating response
        try:
            if INTEL_METRICS_AVAILABLE:
                import os
                mode = 'local' if os.environ.get('LLM_PROVIDER') == 'ollama' else 'cloud'
                update_intelligence_metrics(mode=mode)
        except Exception as e:
            print(f"⚠️  Failed to update intelligence metrics: {e}")
        
        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
    
    print("✅ Prometheus metrics endpoint exposed at /metrics")

@app.get("/")
async def root():
    """Root endpoint"""
    endpoints = {
        "health": "/api/health",
        "status": "/api/status",
        "alerts": "/api/alerts",
        "reminders": "/api/reminders",
        "speak": "/api/voice/speak",
        "intelligence": {
            "stats": "/api/intelligence/stats",
            "health": "/api/intelligence/health",
            "metrics": "/api/intelligence/metrics",
            "insights": "/api/intelligence/insights",
            "experiences": "/api/intelligence/experiences",
            "logs": "/api/intelligence/logs/recent"
        }
    }
    
    if PROMETHEUS_AVAILABLE:
        endpoints["metrics"] = "/metrics"
    
    return {
        "service": "Jarvis Proactive Assistant API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": endpoints,
        "metrics_enabled": PROMETHEUS_AVAILABLE
    }

if __name__ == "__main__":
    import uvicorn
    
    # Run server
    # Pass app directly (not string) to avoid double-import
    uvicorn.run(
        app,  # Pass the app object directly
        host="0.0.0.0",
        port=8880,
        log_level="info"
    )

