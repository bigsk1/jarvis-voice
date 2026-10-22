"""Quiet notifications through the standard Jarvis API authentication boundary."""

import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from api.models.notification import NotificationCreate
from lib.config_loader import get_active_config_mode, get_project_root
from lib.notifications import NotificationStore

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.post("")
@router.post("/", include_in_schema=False)
def create_notification(body: NotificationCreate) -> dict:
    """Record a notice without an LLM call, speech, or an alert lifecycle.

    A successful response confirms local storage. Inspect channel states for
    queued or unavailable delivery; it does not confirm phone arrival.
    """
    mode = body.mode or get_active_config_mode()
    try:
        data = NotificationStore(get_project_root(), mode).create(
            **body.model_dump(exclude={"mode"})
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except (OSError, sqlite3.Error):
        raise HTTPException(
            status_code=503, detail="Notification storage is unavailable."
        ) from None
    return {"ok": True, "data": data}


@router.get("")
@router.get("/", include_in_schema=False)
def list_notifications(
    mode: Literal["cloud", "local"] | None = None,
    source_type: Literal["notifications", "alerts", "reminders", "background_tasks"] | None = None,
    source: str | None = Query(None, max_length=80),
    channel: str | None = Query(None, max_length=40),
    state: str | None = Query(None, max_length=30),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    """Read mode-scoped notification and delivery history without publishing."""
    try:
        data = NotificationStore(get_project_root(), mode or get_active_config_mode()).list_history(
            source_type=source_type,
            source=source,
            channel=channel,
            state=state,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except (OSError, sqlite3.Error):
        raise HTTPException(
            status_code=503, detail="Notification history is unavailable."
        ) from None
    return {"ok": True, **data}
