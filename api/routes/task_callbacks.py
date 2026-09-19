"""Mandatory source authentication; this router never exposes operator controls."""
import sqlite3

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from lib.background_tasks import TaskError
from lib.webhook_integrations.contracts import CallbackError
from lib.webhook_integrations.service import IntegrationService

router = APIRouter(tags=['task-callbacks'])


@router.post(
    '/api/task-callbacks/{source_id}/events',
    summary='Receive an authenticated background task event',
    description='See `docs/TASK-CALLBACKS.md` for setup and the callback event contract.',
)
async def task_event(source_id: str, request: Request):
    service = getattr(request.app.state, 'task_integrations', None) or IntegrationService()
    try:
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise CallbackError('Use application/json', 415)
        # Raw bytes survive the outer size limiter and are verified before JSON parsing.
        result = await run_in_threadpool(service.accept, source_id, await request.body(), dict(request.headers))
        return JSONResponse(result, status_code=200 if result['duplicate'] else 202)
    except CallbackError as exc:
        service.store.events.emit('callback_rejected', component='callback', level='WARNING',
                                   source_id=source_id, error_type=type(exc).__name__)
        return JSONResponse({'error': str(exc)}, status_code=exc.status,
                            headers={'Retry-After': '60'} if exc.status == 429 else None)
    except (OSError, sqlite3.Error, TaskError):
        service.store.events.emit('callback_unavailable', component='callback', level='ERROR', source_id=source_id)
        return JSONResponse({'error': 'Task callback storage or credentials are unavailable; retry later'},
                            status_code=503, headers={'Retry-After': '5'})
