"""Exact, operator-owned threshold rules for Prompt Guard observations.

Content never supplies its own policy selectors. Source identifiers come from
the reviewed caller; workflow identity is held in a mode-bound runtime scope.
The optional JSON file changes thresholds only, never tool selection or whether
a result is scanned. Invalid policy files leave the configured default active.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

try:
    from config_loader import get_active_config_mode
except ModuleNotFoundError as exc:
    if exc.name != "config_loader":
        raise
    from lib.config_loader import get_active_config_mode

from lib.paths import get_project_root

MAX_POLICY_BYTES = 64 * 1024
MAX_POLICY_RULES = 128
POLICY_ID = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SELECTORS = frozenset({"source_type", "source_name", "workflow_id", "profile"})


@dataclass(frozen=True, slots=True)
class PromptGuardPolicyDecision:
    """Safe policy metadata; no paths, external text, or exception messages."""

    threshold: float
    policy_id: str = "configured_default"
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class _WorkflowContext:
    mode: str
    workflow_id: str | None
    profile: str | None


@dataclass(frozen=True, slots=True)
class _Rule:
    policy_id: str
    threshold: float
    source_type: str
    source_name: str
    workflow_id: str | None
    profile: str | None

    @property
    def specificity(self) -> int:
        return int(self.workflow_id is not None) + int(self.profile is not None)


_workflow_context: ContextVar[_WorkflowContext | None] = ContextVar(
    "prompt_guard_workflow_context", default=None,
)


@contextmanager
def workflow_prompt_guard_scope(
    *, mode: str, workflow_id: object, profile: object = None,
) -> Iterator[None]:
    """Bind a trusted snapshot; reset on returns, failures, and nested workflows.

    Only PipelineExecutor should supply workflow/profile values. Do not call
    this with labels found in tool output, a document, or model-filled params.
    An invalid identity clears inherited context rather than borrowing a parent
    workflow's more permissive exception.
    """
    valid_workflow = (
        workflow_id if isinstance(workflow_id, str) and POLICY_ID.fullmatch(workflow_id) else None
    )
    valid_profile = (
        profile if valid_workflow == "rss_digest" and isinstance(profile, str)
        and _PROFILE.fullmatch(profile) else None
    )
    context = _WorkflowContext(mode, valid_workflow, valid_profile)
    token = _workflow_context.set(context)
    try:
        yield
    finally:
        _workflow_context.reset(token)


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_policy")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ValueError("invalid_policy")


def _identifier(value: object, pattern: re.Pattern[str] = POLICY_ID) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError("invalid_policy")
    return value


def _parse_rules(document: object) -> list[_Rule]:
    if (not isinstance(document, dict) or set(document) != {"v", "rules"}
            or type(document["v"]) is not int or document["v"] != 1
            or not isinstance(document["rules"], list)
            or len(document["rules"]) > MAX_POLICY_RULES):
        raise ValueError("invalid_policy")
    rules = []
    identifiers = {"configured_default"}
    selectors = set()
    for row in document["rules"]:
        if (not isinstance(row, dict) or set(row) - (_SELECTORS | {"id", "threshold"})
                or not {"id", "threshold", "source_type", "source_name"} <= set(row)):
            raise ValueError("invalid_policy")
        policy_id = _identifier(row["id"])
        if policy_id in identifiers:
            raise ValueError("invalid_policy")
        identifiers.add(policy_id)
        threshold = row["threshold"]
        if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                or not 0 <= threshold <= 1 or not math.isfinite(threshold)):
            raise ValueError("invalid_policy")
        source_type = _identifier(row["source_type"])
        source_name = _identifier(row["source_name"])
        workflow_id = _identifier(row["workflow_id"]) if "workflow_id" in row else None
        profile = _identifier(row["profile"], _PROFILE) if "profile" in row else None
        if profile is not None and workflow_id != "rss_digest":
            raise ValueError("invalid_policy")
        selector = (source_type, source_name, workflow_id, profile)
        if selector in selectors:
            raise ValueError("invalid_policy")
        selectors.add(selector)
        rules.append(_Rule(policy_id, float(threshold), *selector))
    return rules


def resolve_prompt_guard_policy(
    default_threshold: float, *, source_type: str, source_name: str,
    policy_file: str | None = None,
) -> PromptGuardPolicyDecision:
    """Resolve the most specific exact rule, or retain the configured default.

    Source type/name are mandatory exact selectors; workflow and RSS profile
    refine them. Declaration order breaks a specificity tie. Every rule is
    validated before any is used, so a typo cannot partially activate a file.
    The file is small and reloaded on use; editing it needs no global cache or
    process-environment mutation. Relative paths resolve against the project.
    """
    fallback = PromptGuardPolicyDecision(default_threshold)
    if policy_file is None or policy_file == "":
        return fallback
    try:
        if not isinstance(policy_file, str) or not policy_file.strip():
            raise ValueError("invalid_policy")
        path = Path(policy_file).expanduser()
        if not path.is_absolute():
            path = get_project_root() / path
        with path.open("rb") as stream:
            raw = stream.read(MAX_POLICY_BYTES + 1)
        if len(raw) > MAX_POLICY_BYTES:
            raise ValueError("invalid_policy")
        rules = _parse_rules(json.loads(
            raw, object_pairs_hook=_strict_object, parse_constant=_invalid_constant,
        ))
    except (OSError, ValueError, TypeError, UnicodeError, RuntimeError):
        return PromptGuardPolicyDecision(default_threshold, error_code="invalid_policy")
    context = _workflow_context.get()
    if context is not None and context.mode != get_active_config_mode():
        context = None
    best = None
    for rule in rules:
        if rule.source_type != source_type or rule.source_name != source_name:
            continue
        if rule.workflow_id is not None and (
            context is None or context.workflow_id != rule.workflow_id
        ):
            continue
        if rule.profile is not None and (context is None or context.profile != rule.profile):
            continue
        if best is None or rule.specificity > best.specificity:
            best = rule
    return PromptGuardPolicyDecision(best.threshold, best.policy_id) if best else fallback
