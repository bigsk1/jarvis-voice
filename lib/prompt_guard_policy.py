"""Readable, operator-owned selection and threshold policy for Prompt Guard.

Content never supplies its own policy selectors. Source identifiers come from
the reviewed caller; workflow identity is held in a mode-bound runtime scope.
Trusted policy assignments and JSON select tools; JSON also controls the
independent summarizer gate, named thresholds and source/workflow exceptions.
Invalid files select no tool
results, retain enabled summarizer checks and use the global threshold.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

try:
    from config_loader import get_active_config_mode, get_config_value
except ModuleNotFoundError as exc:
    if exc.name != "config_loader":
        raise
    from lib.config_loader import get_active_config_mode, get_config_value

from lib.paths import get_project_root
from lib.prompt_guard_tool_policy import (
    normalize_prompt_guard_policy_name,
    resolve_tool_policy_name,
)

MAX_POLICY_BYTES = 64 * 1024
MAX_POLICY_RULES = 128
MAX_SELECTED_TOOLS = 512
MAX_NAMED_POLICIES = 64
POLICY_ID = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_NAMED_POLICY = re.compile(r"[A-Za-z0-9_.:-]{1,93}\Z")
_TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SELECTORS = frozenset({"source_type", "source_name", "workflow_id", "profile"})
DEFAULT_POLICY_FILE = "config/prompt_guard_policy.json.example"
logger = logging.getLogger("prompt_guard")


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


@dataclass(frozen=True, slots=True)
class _Config:
    tools: frozenset[str]
    summarizers_enabled: bool
    policies: dict[str, float]
    rules: tuple[_Rule, ...]
    error_code: str | None = None


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


def export_prompt_guard_context() -> str | None:
    """Serialize only the parent's trusted, mode-matching workflow snapshot.

    The executor overwrites the dedicated internal child field with this value;
    neither tool arguments nor inherited ambient environment supply selectors.
    """
    context = _workflow_context.get()
    if (context is None or context.mode != get_active_config_mode()
            or context.workflow_id is None):
        return None
    return json.dumps({
        "v": 1, "mode": context.mode, "workflow_id": context.workflow_id,
        "profile": context.profile,
    }, separators=(",", ":"))


@contextmanager
def inherited_prompt_guard_scope(snapshot: str | None) -> Iterator[None]:
    """Restore the executor-owned child snapshot, clearing invalid inheritance.

    This parser is not a source of workflow authority. Only the executor may
    construct/overwrite the transported field; callers must not pass tool args,
    results, or document metadata here. Cross-mode snapshots cannot apply.
    """
    mode = get_active_config_mode()
    current = _workflow_context.get()
    if current is not None:
        # In-process workflow scopes remain authoritative, including deliberate
        # clearing by a nested/invalid workflow. An ambient child field cannot
        # replace those selectors or revive a different mode's scope.
        if current.mode == mode:
            yield
        else:
            with workflow_prompt_guard_scope(mode=mode, workflow_id=None):
                yield
        return
    workflow_id = None
    profile = None
    try:
        if not isinstance(snapshot, str) or len(snapshot.encode("utf-8")) > 1024:
            raise ValueError("invalid_context")
        value = json.loads(snapshot, object_pairs_hook=_strict_object)
        if (not isinstance(value, dict)
                or set(value) != {"v", "mode", "workflow_id", "profile"}
                or type(value["v"]) is not int or value["v"] != 1
                or value["mode"] != mode):
            raise ValueError("invalid_context")
        workflow_id = _identifier(value["workflow_id"])
        if value["profile"] is not None:
            if workflow_id != "rss_digest":
                raise ValueError("invalid_context")
            profile = _identifier(value["profile"], _PROFILE)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        workflow_id = None
        profile = None
    with workflow_prompt_guard_scope(mode=mode, workflow_id=workflow_id, profile=profile):
        yield


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


def _threshold(value: object) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0 <= value <= 1 or not math.isfinite(value)):
        raise ValueError("invalid_policy")
    return float(value)


def _parse_rules(rows: object, policies: dict[str, float]) -> tuple[_Rule, ...]:
    if not isinstance(rows, list) or len(rows) > MAX_POLICY_RULES:
        raise ValueError("invalid_policy")
    rules = []
    identifiers = {"configured_default"}
    selectors = set()
    for row in rows:
        if (not isinstance(row, dict)
                or set(row) - (_SELECTORS | {"id", "threshold", "policy"})
                or not {"id", "source_type", "source_name"} <= set(row)
                or ("threshold" in row) == ("policy" in row)):
            raise ValueError("invalid_policy")
        policy_id = _identifier(row["id"])
        if policy_id in identifiers:
            raise ValueError("invalid_policy")
        identifiers.add(policy_id)
        if "threshold" in row:
            threshold = _threshold(row["threshold"])
        else:
            policy_name = _identifier(row["policy"], _NAMED_POLICY)
            if policy_name not in policies:
                raise ValueError("invalid_policy")
            threshold = policies[policy_name]
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
    return tuple(rules)


def _parse_config(document: object) -> _Config:
    if (not isinstance(document, dict)
            or set(document) != {"v", "tools", "summarizers", "policies", "rules"}
            or type(document["v"]) is not int or document["v"] != 2):
        raise ValueError("invalid_policy")
    tools = document["tools"]
    if not isinstance(tools, list) or len(tools) > MAX_SELECTED_TOOLS:
        raise ValueError("invalid_policy")
    selected = frozenset(_identifier(tool, _TOOL_NAME) for tool in tools)
    if len(selected) != len(tools):
        raise ValueError("invalid_policy")
    summarizers = document["summarizers"]
    if (not isinstance(summarizers, dict) or set(summarizers) != {"enabled"}
            or type(summarizers["enabled"]) is not bool):
        raise ValueError("invalid_policy")
    policy_values = document["policies"]
    if not isinstance(policy_values, dict) or len(policy_values) > MAX_NAMED_POLICIES:
        raise ValueError("invalid_policy")
    policies = {
        _identifier(name, _NAMED_POLICY): _threshold(value) for name, value in policy_values.items()
    }
    if "configured_default" in policies:
        raise ValueError("invalid_policy")
    return _Config(
        selected, summarizers["enabled"], policies, _parse_rules(document["rules"], policies),
    )


def _load_config(policy_file: str | None = None) -> _Config:
    """Reload the selected mode's small JSON file without caching contents."""
    try:
        selected_file = policy_file
        if selected_file is None or selected_file == "":
            selected_file = get_config_value("PROMPT_GUARD_POLICY_FILE", "") or DEFAULT_POLICY_FILE
        if not isinstance(selected_file, str) or not selected_file.strip():
            raise ValueError("invalid_policy")
        path = Path(selected_file).expanduser()
        if not path.is_absolute():
            path = get_project_root() / path
        with path.open("rb") as stream:
            raw = stream.read(MAX_POLICY_BYTES + 1)
        if len(raw) > MAX_POLICY_BYTES:
            raise ValueError("invalid_policy")
        return _parse_config(json.loads(
            raw, object_pairs_hook=_strict_object, parse_constant=_invalid_constant,
        ))
    except (OSError, ValueError, TypeError, UnicodeError, RuntimeError, RecursionError):
        # Never log paths or parser exceptions: they can contain private data.
        logger.warning("Prompt Guard policy fallback reason=invalid_policy")
        return _Config(frozenset(), True, {}, (), "invalid_policy")


def is_valid_tool_name(tool_name: object) -> bool:
    """Accept bounded exact local/MCP names, including MCP's literal hyphens."""
    return isinstance(tool_name, str) and _TOOL_NAME.fullmatch(tool_name) is not None


def is_tool_selected(tool_name: str, *, policy_name: str | None = None) -> bool:
    """Select exact listed tools or tools with a trusted named-policy assignment.

    A manifest/MCP binding opts in without a duplicate tools-list entry. The
    list remains useful for tools that should use the global threshold. An
    invalid config still selects nothing; an unknown assigned policy keeps the
    normal global-threshold fallback. Callers separately check the master flag.
    """
    if not is_valid_tool_name(tool_name):
        return False
    config = _load_config()
    if config.error_code:
        return False
    if tool_name in config.tools:
        return True
    assigned = normalize_prompt_guard_policy_name(policy_name)
    if assigned is None:
        assigned = resolve_tool_policy_name(tool_name)
    return assigned is not None


def summarizers_enabled() -> bool:
    """Return the independent input-screening gate, defaulting to true.

    Callers must also check Prompt Guard's mode-scoped master enable flag. This
    gate controls source screening before summarizer models, not output checks.
    """
    return _load_config().summarizers_enabled


def resolve_prompt_guard_policy(
    default_threshold: float, *, source_type: str, source_name: str,
    policy_file: str | None = None, policy_name: str | None = None,
) -> PromptGuardPolicyDecision:
    """Resolve the most specific exact rule, or retain the configured default.

    Exact rules override caller-owned named policy metadata, then the global
    threshold applies. Workflow and RSS profile refine an exact source rule;
    declaration order breaks specificity ties. Returned text and model-filled
    arguments must never supply policy_name. Empty/unset paths use the active
    configured path or shipped default. Every field is validated before use.
    """
    fallback = PromptGuardPolicyDecision(default_threshold)
    config = _load_config(policy_file)
    if config.error_code:
        return PromptGuardPolicyDecision(default_threshold, error_code=config.error_code)
    context = _workflow_context.get()
    if context is not None and context.mode != get_active_config_mode():
        context = None
    best = None
    for rule in config.rules:
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
    if best:
        return PromptGuardPolicyDecision(best.threshold, best.policy_id)
    if policy_name is not None:
        if isinstance(policy_name, str) and policy_name in config.policies:
            return PromptGuardPolicyDecision(config.policies[policy_name], f"policy:{policy_name}")
        return PromptGuardPolicyDecision(default_threshold, error_code="unknown_policy")
    return fallback
