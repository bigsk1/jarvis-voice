"""Authenticated, bounded REST access to local watch state; no deliveries."""

from __future__ import annotations

import secrets
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from lib.config_loader import config_scope, get_active_config_mode, get_config_value
from lib.paths import get_project_root
from lib.watch_state.service import MAX_REQUEST_BYTES, dispatch

Mode = Literal["cloud", "local"]
Action = Literal[
    "register",
    "compare",
    "commit",
    "discard",
    "claim",
    "ack",
    "pending",
    "history",
    "list",
    "inspect",
    "reset",
    "mute",
    "delete",
    "health",
    "handled",
    "record_delivery",
    "cleanup",
    "record_error",
    "retry",
]


class ActionBody(BaseModel):
    """Typed action values; the service enforces each action's exact allowed set."""

    model_config = ConfigDict(extra="forbid", strict=True)
    definition: dict[str, Any] | None = None
    owner: str | None = Field(default=None, min_length=1, max_length=200)
    records: list[dict[str, Any]] | None = Field(default=None, max_length=1000)
    complete: bool | None = None
    dry_run: bool | None = None
    request_id: str | None = Field(default=None, min_length=1, max_length=200)
    run_id: str | None = Field(default=None, min_length=1, max_length=200)
    event_id: str | None = Field(default=None, min_length=1, max_length=200)
    channel: str | None = Field(default=None, min_length=1, max_length=40)
    destination: str | None = Field(default=None, min_length=1, max_length=1024)
    lease_seconds: int | None = Field(default=None, ge=1, le=3600)
    claim_token: str | None = Field(default=None, min_length=1, max_length=200)
    success: bool | None = None
    receipt: dict[str, Any] | None = Field(
        default=None,
        description="Actual delivery result. record_delivery requires a standard {ok:true,...} success envelope.",
    )
    error: str | None = Field(default=None, max_length=1000)
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    limit: int | None = Field(default=None, ge=1, le=1000)
    offset: int | None = Field(default=None, ge=0, le=1_000_000_000)
    include_parked: bool | None = None
    until: int | float | None = Field(default=None, ge=0)
    seconds: int | float | None = Field(default=None, gt=0, le=31_536_000)
    delete_handled: bool | None = None
    record: dict[str, Any] | None = Field(
        default=None,
        description="record_delivery only: per-record ever-handled ledger; use claim/ack for repeated change events.",
    )


def _require_access(request: Request) -> None:
    expected = get_config_value("JARVIS_API_KEY", "")
    if not isinstance(expected, str) or not expected:
        raise HTTPException(503, "Watch API authentication is not configured.")
    parts = request.headers.get("authorization", "").split()
    if (
        len(parts) != 2
        or parts[0].casefold() != "bearer"
        or len(parts[1]) > 4096
        or not secrets.compare_digest(parts[1].encode("utf-8"), expected.encode("utf-8"))
    ):
        raise HTTPException(
            401, "A valid Bearer token is required.", headers={"WWW-Authenticate": "Bearer"}
        )


class WatchRoute(APIRoute):
    """Authenticate and cap the stream before FastAPI decodes the JSON body."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            mode = request.query_params.get("mode")
            if mode is not None and mode not in {"cloud", "local"}:
                raise HTTPException(422, "Mode must be cloud or local.")
            with config_scope(mode or get_active_config_mode()):
                _require_access(request)
                length = request.headers.get("content-length")
                if length is not None:
                    try:
                        count = int(length)
                    except ValueError:
                        raise HTTPException(400, "Invalid request length.") from None
                    if count < 0 or count > MAX_REQUEST_BYTES:
                        raise HTTPException(413, "Watch request exceeds the 256 KiB limit.")
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    body = bytearray()
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                            raise HTTPException(413, "Watch request exceeds the 256 KiB limit.")
                        body.extend(chunk)
                    # Starlette's body cache lets the normal typed decoder reuse
                    # the bounded bytes after the stream has been consumed.
                    request._body = bytes(body)
                try:
                    return await original(request)
                except RecursionError:
                    raise HTTPException(400, "Watch request JSON nesting is excessive.") from None

        return bounded


router = APIRouter(prefix="/api/watch", tags=["watch state"], route_class=WatchRoute)


def _execute(action: str, parameters: dict[str, Any], mode: Mode | None) -> dict[str, Any]:
    from lib.watch_state import (
        Authority,
        AuthorityError,
        ConflictError,
        NotFoundError,
        StorageError,
    )

    try:
        return dispatch(
            {"action": action, **parameters},
            project_root=get_project_root(),
            mode=mode or get_active_config_mode(),
            authority=Authority("api", True),
        )
    except AuthorityError as exc:
        raise HTTPException(403, str(exc)) from None
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from None
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    except (StorageError, OSError, sqlite3.Error):
        raise HTTPException(503, "Watch state storage is unavailable.") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("")
@router.get("/", include_in_schema=False)
def list_watches(
    mode: Mode | None = None,
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=1_000_000_000),
) -> dict[str, Any]:
    return _execute("list", {"limit": limit, "offset": offset}, mode)


@router.get("/health")
def watch_health(
    mode: Mode | None = None, key: str | None = Query(None, max_length=160)
) -> dict[str, Any]:
    return _execute("health", {"key": key} if key is not None else {}, mode)


@router.post("/{key:path}/{action}")
def watch_action(
    key: str,
    action: Action,
    body: ActionBody = Body(default=ActionBody()),
    mode: Mode | None = None,
) -> dict[str, Any]:
    return _execute(action, {"key": key, **body.model_dump(exclude_none=True)}, mode)


@router.put("/{key:path}")
def register_watch(key: str, body: ActionBody, mode: Mode | None = None) -> dict[str, Any]:
    return _execute("register", {"key": key, **body.model_dump(exclude_none=True)}, mode)


@router.delete("/{key:path}")
def delete_watch(
    key: str,
    body: ActionBody = Body(default=ActionBody()),
    mode: Mode | None = None,
) -> dict[str, Any]:
    return _execute("delete", {"key": key, **body.model_dump(exclude_none=True)}, mode)


@router.get("/{key:path}")
def inspect_watch(key: str, mode: Mode | None = None) -> dict[str, Any]:
    return _execute("inspect", {"key": key}, mode)
