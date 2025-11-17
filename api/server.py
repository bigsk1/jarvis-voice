#!/usr/bin/env python3
"""
Jarvis Proactive Assistant API Server
FastAPI server for webhooks, alerts, reminders, and proactive notifications
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.routes import alerts_router, reminders_router, health_router, voice_router

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

# Register routers
app.include_router(health_router)
app.include_router(alerts_router)
app.include_router(reminders_router)
app.include_router(voice_router)

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Jarvis Proactive Assistant API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "health": "/api/health",
            "status": "/api/status",
            "alerts": "/api/alerts",
            "reminders": "/api/reminders",
            "speak": "/api/voice/speak"
        }
    }

if __name__ == "__main__":
    import uvicorn
    
    # Run server
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8880,
        reload=False,  # Disable in production
        log_level="info"
    )

