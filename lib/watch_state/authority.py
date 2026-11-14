"""Trusted caller identity for watch mutations; never sourced from tool arguments."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .normalization import AuthorityError

WRITER_ENV = "JARVIS_INTERNAL_WATCH_WRITER"
_WRITER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")
_writer: ContextVar[str] = ContextVar("watch_writer", default="interactive")


@dataclass(frozen=True, slots=True)
class Authority:
    writer: str
    admin: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.writer, str) or not _WRITER_RE.fullmatch(self.writer) or type(self.admin) is not bool:
            raise AuthorityError("A valid trusted watch writer is required.")


@contextmanager
def watch_writer_scope(workflow_id: str | None) -> Iterator[None]:
    if workflow_id is None or workflow_id == "":
        writer = "interactive"
    elif isinstance(workflow_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", workflow_id):
        writer = f"workflow:{workflow_id}"
    else:
        # An unrelated old workflow can still run, but cannot borrow its caller's identity.
        writer = "workflow:unidentified"
    token = _writer.set(writer)
    try:
        yield
    finally:
        _writer.reset(token)


def export_writer_context() -> str:
    return _writer.get()


def authority_from_environment(environment: Mapping[str, str] | None = None) -> Authority:
    values = os.environ if environment is None else environment
    return Authority(values.get(WRITER_ENV, "interactive"))
