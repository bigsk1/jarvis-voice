#!/usr/bin/env python3
"""
Jarvis Proactive Assistant API Server
FastAPI server for webhooks, alerts, reminders, and proactive notifications
"""

from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import sys
import time
import json
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.routes import alerts_router, reminders_router, health_router, voice_router, memory_router, query_router, conversations_router, stash_router, canvas_router, prices_router, price_alerts_router, workflows_router, intel_router, images_router, generated_images_router, generated_music_router, generated_videos_router, docs_router, scheduled_tasks_router
from api.routes.intelligence import router as intelligence_router
from lib.rate_limiter import APIRateLimitMiddleware
from lib.config_loader import get_config_value, get_active_config_mode


# ============================================================================
# Request Logging Middleware
# ============================================================================

# ============================================================================
# API Authentication Middleware (Optional)
# ============================================================================

class APIAuthMiddleware(BaseHTTPMiddleware):
    """
    Optional Bearer token authentication middleware.
    
    Controlled by environment variables:
    - JARVIS_API_AUTH: true/false (default: false for backward compatibility)
    - JARVIS_API_KEY: The API key to validate against
    
    When enabled:
    - Localhost (127.0.0.1, ::1) requests are always allowed (internal calls)
    - External requests require: Authorization: Bearer <JARVIS_API_KEY>
    - Certain paths are always public: /api/health, /metrics, /docs, /
    """
    
    def __init__(self, app):
        super().__init__(app)
        # Load auth config
        self.auth_enabled = get_config_value("JARVIS_API_AUTH", "false").lower() == "true"
        self.api_key = get_config_value("JARVIS_API_KEY", "")
        
        # IPs that don't need auth (internal/localhost)
        self.trusted_ips = {"127.0.0.1", "::1", "localhost"}
        
        # Paths that are always public (no auth required)
        self.public_paths = {"/", "/api/health", "/api/status", "/metrics", "/docs", "/docs/dark", "/redoc", "/openapi.json"}
        
        if self.auth_enabled:
            if not self.api_key:
                print("⚠️  JARVIS_API_AUTH=true but JARVIS_API_KEY not set! Auth disabled.")
                self.auth_enabled = False
            else:
                print(f"🔐 API authentication enabled (localhost whitelisted)")
        else:
            print("🔓 API authentication disabled (set JARVIS_API_AUTH=true to enable)")
    
    async def dispatch(self, request: Request, call_next):
        # If auth is disabled, pass through
        if not self.auth_enabled:
            return await call_next(request)
        
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"
        
        # Public paths - no auth needed
        if path in self.public_paths or path.startswith("/docs"):
            return await call_next(request)
        
        # Localhost - trusted, no auth needed
        if client_ip in self.trusted_ips:
            return await call_next(request)
        
        # External request - check Bearer token
        auth_header = request.headers.get("Authorization", "")
        
        if not auth_header:
            return Response(
                content=json.dumps({"error": "Authorization header required", "detail": "Use: Authorization: Bearer <api_key>"}),
                status_code=401,
                media_type="application/json"
            )
        
        # Parse Bearer token
        if not auth_header.startswith("Bearer "):
            return Response(
                content=json.dumps({"error": "Invalid authorization format", "detail": "Use: Authorization: Bearer <api_key>"}),
                status_code=401,
                media_type="application/json"
            )
        
        token = auth_header[7:]  # Remove "Bearer " prefix
        
        if token != self.api_key:
            return Response(
                content=json.dumps({"error": "Invalid API key"}),
                status_code=403,
                media_type="application/json"
            )
        
        # Auth passed
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all API requests to logs/api/ directory.
    
    Logs:
    - access.log: All requests (JSONL format)  
    - errors.log: 4xx/5xx responses with details
    
    By default, skips logging loopback (127.0.0.1) access to reduce noise
    from internal daemon polling. Errors from loopback are still logged.
    """
    
    def __init__(self, app, logs_dir: Path = None, log_loopback: bool = False):
        super().__init__(app)
        self.logs_dir = logs_dir or Path(__file__).parent.parent / "logs" / "api"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_loopback = log_loopback
        
        # Paths to skip detailed logging (health checks, metrics)
        self.skip_paths = {"/api/health", "/metrics", "/api/status"}
        
        # IPs considered "internal" (loopback)
        self.internal_ips = {"127.0.0.1", "::1", "localhost"}
    
    def _get_log_file(self, log_type: str) -> Path:
        """Get log file path with date rotation."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self.logs_dir / f"{log_type}-{date_str}.jsonl"
    
    def _write_log(self, log_type: str, entry: dict):
        """Write log entry to file."""
        try:
            log_file = self._get_log_file(log_type)
            with open(log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"⚠️  Failed to write {log_type} log: {e}")
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Get request info
        method = request.method
        path = request.url.path
        query_string = str(request.url.query) if request.url.query else None
        client_ip = request.client.host if request.client else "unknown"
        
        # Try to get request body for POST/PUT (for error logging)
        body = None
        if method in ("POST", "PUT", "PATCH") and path not in self.skip_paths:
            try:
                body_bytes = await request.body()
                if body_bytes:
                    body = body_bytes.decode("utf-8")[:2000]  # Limit to 2KB
            except:
                pass
        
        # Process request
        response = None
        error_detail = None
        try:
            response = await call_next(request)
        except Exception as e:
            error_detail = str(e)
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            status_code = response.status_code if response else 500
            
            # Build log entry
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "method": method,
                "path": path,
                "query": query_string,
                "status": status_code,
                "duration_ms": round(duration_ms, 2),
                "client_ip": client_ip,
            }
            
            # Skip access log for health checks and internal traffic
            is_internal = client_ip in self.internal_ips
            skip_access = path in self.skip_paths or (is_internal and not self.log_loopback)
            
            if not skip_access:
                self._write_log("access", log_entry)
            
            # Log errors (4xx, 5xx) with more detail - ALWAYS log errors, even from loopback
            if status_code >= 400:
                error_entry = {
                    **log_entry,
                    "request_body": body[:500] if body else None,  # Truncate for errors
                    "error": error_detail,
                }
                self._write_log("errors", error_entry)
        
        return response

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

# Swagger UI dark mode CSS
SWAGGER_DARK_CSS = """
/* Dark mode for Swagger UI */
body { background-color: #1a1a2e !important; }
.swagger-ui { background-color: #1a1a2e !important; color: #d0d0d0 !important; }
.swagger-ui .topbar { background-color: #16213e !important; }
.swagger-ui .info { margin: 20px 0; }
.swagger-ui .info .title { color: #e94560 !important; }
.swagger-ui .info .description { color: #c8c8c8 !important; }
.swagger-ui .info .description p { color: #c8c8c8 !important; }
.swagger-ui .scheme-container { background-color: #1a1a2e !important; box-shadow: none !important; }

/* Tag sections (alerts, reminders, etc.) */
.swagger-ui .opblock-tag { color: #e0e0e0 !important; border-bottom: 1px solid #333 !important; }
.swagger-ui .opblock-tag small { color: #c8c8c8 !important; }
.swagger-ui .opblock-tag-section .opblock-tag p { color: #c8c8c8 !important; }

/* Operation blocks */
.swagger-ui .opblock { background: #16213e !important; border: 1px solid #333 !important; }
.swagger-ui .opblock .opblock-summary { border: none !important; }
.swagger-ui .opblock .opblock-summary-method { background: #e94560 !important; }
.swagger-ui .opblock.opblock-get .opblock-summary-method { background: #61affe !important; }
.swagger-ui .opblock.opblock-post .opblock-summary-method { background: #49cc90 !important; }
.swagger-ui .opblock.opblock-put .opblock-summary-method { background: #fca130 !important; }
.swagger-ui .opblock.opblock-delete .opblock-summary-method { background: #f93e3e !important; }
.swagger-ui .opblock .opblock-summary-path { color: #e0e0e0 !important; }
.swagger-ui .opblock .opblock-summary-description { color: #c8c8c8 !important; }
.swagger-ui .opblock-body pre { background: #0f0f1a !important; color: #e0e0e0 !important; }

/* Descriptions and markdown content - LIGHT GREY */
.swagger-ui .opblock-description-wrapper { color: #d0d0d0 !important; }
.swagger-ui .opblock-description-wrapper p { color: #d0d0d0 !important; }
.swagger-ui .opblock-description { color: #d0d0d0 !important; }
.swagger-ui .renderedMarkdown { color: #d0d0d0 !important; }
.swagger-ui .renderedMarkdown p { color: #d0d0d0 !important; }
.swagger-ui .markdown p, .swagger-ui .markdown li { color: #d0d0d0 !important; }
.swagger-ui .markdown code { background: #0f0f1a !important; color: #e94560 !important; }

/* Labels - Parameters, Request body, etc. */
.swagger-ui .opblock-section-header { background: #0f0f1a !important; }
.swagger-ui .opblock-section-header h4 { color: #e0e0e0 !important; }
.swagger-ui .opblock-section-header label { color: #c8c8c8 !important; }
.swagger-ui .parameters-col_description { color: #d0d0d0 !important; }
.swagger-ui .parameter__name { color: #e0e0e0 !important; }
.swagger-ui .parameter__type { color: #c8c8c8 !important; }
.swagger-ui .parameter__in { color: #c8c8c8 !important; }

/* Tables */
.swagger-ui table thead tr th { color: #e0e0e0 !important; border-bottom: 1px solid #333 !important; }
.swagger-ui table tbody tr td { color: #d0d0d0 !important; border-bottom: 1px solid #222 !important; }
.swagger-ui table tbody tr td p { color: #d0d0d0 !important; }

/* Models and schemas */
.swagger-ui .model-box { background: #16213e !important; }
.swagger-ui .model { color: #e0e0e0 !important; }
.swagger-ui .model-title { color: #e0e0e0 !important; }
.swagger-ui .prop-type { color: #61affe !important; }
.swagger-ui .prop-format { color: #c8c8c8 !important; }

/* Responses */
.swagger-ui .response-col_status { color: #49cc90 !important; }
.swagger-ui .response-col_description { color: #d0d0d0 !important; }
.swagger-ui .responses-inner { background: #0f0f1a !important; }
.swagger-ui .response { color: #e0e0e0 !important; }

/* Buttons and inputs */
.swagger-ui .btn { background: #333 !important; color: #e0e0e0 !important; border: 1px solid #444 !important; }
.swagger-ui .btn:hover { background: #444 !important; }
.swagger-ui .btn.execute { background: #e94560 !important; border-color: #e94560 !important; }
.swagger-ui input[type=text], .swagger-ui textarea { background: #0f0f1a !important; color: #e0e0e0 !important; border: 1px solid #333 !important; }
.swagger-ui select { background: #16213e !important; color: #e0e0e0 !important; border: 1px solid #333 !important; }

/* Models section */
.swagger-ui section.models { border: 1px solid #333 !important; background: #16213e !important; }
.swagger-ui section.models h4 { color: #e0e0e0 !important; }
.swagger-ui section.models .model-container { background: #1a1a2e !important; }

/* Example values */
.swagger-ui .example { color: #d0d0d0 !important; }
.swagger-ui .microlight { background: #0f0f1a !important; color: #d0d0d0 !important; }
"""

# Create FastAPI app
app = FastAPI(
    title="Jarvis Proactive Assistant API",
    description="REST API for alerts, reminders, intelligence, and proactive notifications",
    version=__import__('lib.version', fromlist=['JARVIS_VERSION']).JARVIS_VERSION,
    docs_url=None,  # Disable default, we'll add custom
    redoc_url="/redoc",
    swagger_ui_oauth2_redirect_url=None
)

# Custom Swagger UI with dark mode
from fastapi.openapi.docs import get_swagger_ui_html

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Docs",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
        swagger_ui_parameters={"syntaxHighlight.theme": "monokai", "docExpansion": "none"},
    )

# Inject dark mode CSS
from fastapi.responses import HTMLResponse

@app.get("/docs/dark", include_in_schema=False)
async def swagger_ui_dark():
    """Swagger UI with dark mode"""
    html = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Docs (Dark)",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
        swagger_ui_parameters={"syntaxHighlight.theme": "monokai", "docExpansion": "none"},
    )
    # Inject dark CSS
    dark_html = html.body.decode().replace(
        "</head>",
        f"<style>{SWAGGER_DARK_CSS}</style></head>"
    )
    return HTMLResponse(content=dark_html)

# Per-IP rate limits for /api/* (buckets in lib/rate_limiter.py); skips /api/health, OPTIONS, etc.
# Added first so it runs innermost (just before route handlers): Logging → Auth → CORS → RateLimit → app
app.add_middleware(APIRateLimitMiddleware)

# CORS middleware (for web UIs in the future)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Localhost only in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API authentication middleware (optional, controlled by JARVIS_API_AUTH env var)
# Middleware is added in reverse order - auth runs FIRST (added last)
app.add_middleware(APIAuthMiddleware)

# Request logging middleware - logs to logs/api/
# Set log_loopback=True to include internal daemon traffic
app.add_middleware(RequestLoggingMiddleware, log_loopback=False)
print("✅ Request logging enabled → logs/api/ (external only, errors always logged)")

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
app.include_router(memory_router)
app.include_router(query_router)
app.include_router(conversations_router)
app.include_router(stash_router)
app.include_router(canvas_router)
app.include_router(prices_router)
app.include_router(price_alerts_router)
app.include_router(workflows_router)
app.include_router(intel_router)
app.include_router(intelligence_router)
app.include_router(images_router)
app.include_router(generated_images_router)
app.include_router(generated_music_router)
app.include_router(generated_videos_router)
app.include_router(docs_router)
app.include_router(scheduled_tasks_router)

# Add /metrics endpoint LAST
if PROMETHEUS_AVAILABLE:
    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        """Expose Prometheus metrics including intelligence layer stats"""
        # Update intelligence metrics before generating response
        try:
            if INTEL_METRICS_AVAILABLE:
                mode = get_active_config_mode()
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
        "query": {
            "post": "/api/query",
            "quick": "/api/query/quick"
        },
        "alerts": "/api/alerts",
        "reminders": "/api/reminders",
        "memory": {
            "list": "/api/memory",
            "search_keyword": "/api/memory/search/keyword",
            "search_semantic": "/api/memory/search/semantic",
            "stats": "/api/memory/stats",
            "categories": "/api/memory/categories"
        },
        "conversations": {
            "list": "/api/conversations",
            "recent": "/api/conversations/recent",
            "search": "/api/conversations/search",
            "stats": "/api/conversations/stats",
            "sessions": "/api/conversations/sessions"
        },
        "stash": {
            "list": "/api/stash",
            "recent": "/api/stash/recent",
            "search": "/api/stash/search",
            "stats": "/api/stash/stats",
            "labels": "/api/stash/labels",
            "space": "/api/stash/space/{space_id}",
            "download": "/api/stash/space/{space_id}/file/{file_id}/download"
        },
        "canvas": {
            "list": "/api/canvas",
            "recent": "/api/canvas/recent",
            "search": "/api/canvas/search",
            "stats": "/api/canvas/stats",
            "tags": "/api/canvas/tags",
            "tools": "/api/canvas/tools",
            "page": "/api/canvas/{page_id}"
        },
        "speak": "/api/voice/speak",
        "workflows": {
            "list": "/api/workflows",
            "history": "/api/workflows/history",
            "get": "/api/workflows/{workflow_id}",
            "execute": "/api/workflows/{workflow_id}/execute"
        },
        "intelligence": {
            "stats": "/api/intelligence/stats",
            "health": "/api/intelligence/health",
            "metrics": "/api/intelligence/metrics",
            "insights": "/api/intelligence/insights",
            "experiences": "/api/intelligence/experiences",
            "reflections": "/api/intelligence/reflections",
            "logs": "/api/intelligence/logs/recent"
        }
    }
    
    if PROMETHEUS_AVAILABLE:
        endpoints["metrics"] = "/metrics"
    
    return {
        "service": "Jarvis Proactive Assistant API",
        "version": __import__('lib.version', fromlist=['JARVIS_VERSION']).JARVIS_VERSION,
        "docs": {
            "swagger": "/docs",
            "swagger_dark": "/docs/dark",
            "redoc": "/redoc"
        },
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
