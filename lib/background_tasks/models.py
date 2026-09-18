"""Internal value contracts, not HTTP or model-controlled authorization schemas."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any

MAX_ARGUMENT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 1024 * 1024
MAX_PROGRESS_BYTES = 4096
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class TaskError(ValueError):
    """A task operation could not satisfy its contract."""


class AdmissionDenied(TaskError):
    """No new background work was admitted."""


class Conflict(TaskError):
    """An existing identity was reused for different content/state."""


class LostLease(TaskError):
    """The execution owner is no longer permitted to write."""


def identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise TaskError(f"Invalid {name}")
    return value


def canonical_json(value: Any, limit: int) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise TaskError("Payload must be finite JSON") from exc
    if len(encoded.encode("utf-8")) > limit:
        raise TaskError("Payload exceeds its storage limit")
    return encoded


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Admission:
    """Trusted caller context; no socket, ENV value, or MemoryDB session can replace it.

    The future Web admission service must validate authorization_id and adapter
    readiness before calling the store. Merely constructing this object is not
    proof of user authorization. There is no public admission endpoint in phase 1a.
    """

    conversation_id: str
    generation: int
    request_id: str
    invocation_id: str
    tool: str
    adapter: str
    mode: str
    arguments: dict
    authorization_id: str
    source: str
    timeout_seconds: float = 900

    def serialize(self) -> str:
        if self.source != "web":
            raise AdmissionDenied("Background admission requires an explicit Web destination")
        for name in (
            "conversation_id",
            "request_id",
            "invocation_id",
            "tool",
            "adapter",
            "authorization_id",
        ):
            identifier(getattr(self, name), name)
        if type(self.generation) is not int or self.generation < 0:
            raise TaskError("Invalid conversation generation")
        if self.mode not in {"cloud", "local"}:
            raise TaskError("Mode must be cloud or local")
        if not isinstance(self.arguments, dict):
            raise TaskError("Arguments must be an object")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 86400
        ):
            raise TaskError("Timeout must be between zero and 86400 seconds")
        return canonical_json(asdict(self), MAX_ARGUMENT_BYTES)

    @property
    def invocation_key(self) -> str:
        return digest(
            canonical_json(
                [self.conversation_id, self.generation, self.request_id, self.invocation_id], 1024
            )
        )


@dataclass(frozen=True)
class ReceiptEvidence:
    """Supplied only after Web durably saves its receipt and releases its run lease.

    Phase 1b must derive this from saved source-request history, not the current
    conversation run (which might already be a successor). The phase 1a fixture
    harness supplies it explicitly; the store cannot inspect Web's JSON itself.
    """

    conversation_id: str
    generation: int
    request_id: str
    receipt_message_id: str
    run_status: str
    lease_released: bool

    def serialize(self) -> str:
        for name in ("conversation_id", "request_id", "receipt_message_id"):
            identifier(getattr(self, name), name)
        if type(self.generation) is not int or self.generation < 0:
            raise TaskError("Invalid receipt generation")
        if self.run_status != "completed" or self.lease_released is not True:
            raise AdmissionDenied("The receipt turn has not durably settled and released its lease")
        return canonical_json(asdict(self), 4096)


@dataclass(frozen=True)
class Claim:
    job_id: str
    attempt_id: str
    owner: str
    fence: int
    job: dict
