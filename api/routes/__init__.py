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
from .prices import router as prices_router
from .config import router as config_router
from .workflows import router as workflows_router
from .intel import router as intel_router
from .images import router as images_router
from .generated_images import router as generated_images_router
from .generated_music import router as generated_music_router
from .generated_videos import router as generated_videos_router
from .docs import router as docs_router
from .scheduled_tasks import router as scheduled_tasks_router

__all__ = ['alerts_router', 'reminders_router', 'health_router', 'voice_router', 'memory_router', 'query_router', 'conversations_router', 'stash_router', 'canvas_router', 'prices_router', 'config_router', 'workflows_router', 'intel_router', 'images_router', 'generated_images_router', 'generated_music_router', 'generated_videos_router', 'docs_router', 'scheduled_tasks_router']
