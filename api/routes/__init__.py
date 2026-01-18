"""API routes"""

from .alerts import router as alerts_router
from .reminders import router as reminders_router
from .health import router as health_router
from .voice import router as voice_router
from .memory import router as memory_router
from .query import router as query_router
from .conversations import router as conversations_router
from .stash import router as stash_router
from .canvas import router as canvas_router

__all__ = ['alerts_router', 'reminders_router', 'health_router', 'voice_router', 'memory_router', 'query_router', 'conversations_router', 'stash_router', 'canvas_router']

