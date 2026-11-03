"""Reviewed policy for workflows published or executed by the visual builder."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from config_loader import config_scope, get_config_value

BUILDER_POLICY_VERSION = 1
BUILDER_ALLOWED_ENV_KEYS = frozenset({
    "JARVIS_DEFAULT_LOCATION", "JARVIS_DEFAULT_POSTAL_CODE", "JARVIS_MODE",
    "UPCOMING_MOVIE_RADAR_EMAIL_TO", "UPCOMING_TV_RADAR_EMAIL_TO",
})
BUILDER_EXCLUDED_TOOLS = frozenset({"workflow", "opencode", "browser_use", "browser_use_cloud"})
WEB_CONFIG_PATH = Path(__file__).resolve().parent.parent / "jarvis-web" / "config" / "web_config.json"


class WorkflowPolicyError(ValueError):
    """A managed recipe cannot safely execute under the current saved policy."""


def workflow_approval_hash(workflow: dict[str, Any]) -> str:
    """Hash the exact recipe independently of its server-owned approval grant."""
    document = {key: value for key, value in workflow.items() if key != "builder_unattended_approval"}
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validated_workflow_approval_tools(workflow: dict[str, Any]) -> set[str]:
    """Return exact-revision grants; malformed or stale grants never grant authority."""
    if "builder_unattended_approval" not in workflow:
        return set()
    grant = workflow["builder_unattended_approval"]
    if not isinstance(grant, dict) or type(grant.get("version")) is not int or grant["version"] != 1:
        raise WorkflowPolicyError("Recipe unattended approval is malformed or unsupported")
    tools = grant.get("tools")
    if not isinstance(tools, list) or any(not isinstance(name, str) or not name for name in tools):
        raise WorkflowPolicyError("Recipe unattended approval must list exact tool names")
    if not isinstance(workflow.get("steps"), list):
        raise WorkflowPolicyError("Recipe unattended approval requires a valid step array")
    declared = {step.get("tool") for step in workflow["steps"]
                if isinstance(step, dict) and isinstance(step.get("tool"), str)}
    if len(set(tools)) != len(tools) or not set(tools).issubset(declared):
        raise WorkflowPolicyError("Recipe unattended approval contains duplicate or undeclared tools")
    try:
        expected = workflow_approval_hash(workflow)
    except (TypeError, ValueError) as exc:
        raise WorkflowPolicyError("Recipe unattended approval cannot validate this definition") from exc
    if grant.get("recipe_hash") != expected:
        raise WorkflowPolicyError("Recipe changed after unattended approval; publish and explicitly approve this revision")
    return set(tools)


def get_workflow_allowed_env_keys() -> frozenset[str]:
    """Read trusted operator additions; browser requests cannot supply this list."""
    raw = get_config_value("WORKFLOW_BUILDER_ALLOWED_ENV_KEYS", "")
    if not isinstance(raw, str):
        raise WorkflowPolicyError("Workflow environment allowlist configuration must be text")
    names = [name.strip() for name in raw.split(",") if name.strip()]
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in names):
        raise WorkflowPolicyError("Invalid workflow environment allowlist configuration")
    # A mistaken operator addition must not turn workflow bindings into a
    # credential-reading interface. Tools obtain secrets through their own env.
    safe = {name for name in names if not re.search(r"(?:(?:^|_)(?:KEY|TOKEN|SECRET)$|PASSWORD)", name, re.IGNORECASE)}
    return BUILDER_ALLOWED_ENV_KEYS | frozenset(safe)


def get_workflow_excluded_tools(mode: str) -> set[str]:
    """Read saved Web blocks fresh, plus the selected mode's scoped blocks.

    A missing optional settings file means no saved blocks. Malformed policy
    fails closed rather than silently allowing an operation.
    """
    with config_scope(mode):
        raw = get_config_value("BLOCKED_TOOLS", "")
    if not isinstance(raw, str):
        raise WorkflowPolicyError("BLOCKED_TOOLS must be comma-separated text")
    blocked = {name.strip() for name in raw.split(",") if name.strip()}
    try:
        document = json.loads(WEB_CONFIG_PATH.read_text())
    except FileNotFoundError:
        return blocked
    except (OSError, ValueError) as exc:
        raise WorkflowPolicyError("Saved workflow tool policy could not be read") from exc
    if not isinstance(document, dict) or not isinstance(document.get("tools", {}), dict):
        raise WorkflowPolicyError("Saved workflow tool policy is malformed")
    saved = document.get("tools", {}).get("blocked", [])
    if not isinstance(saved, list) or any(not isinstance(name, str) for name in saved):
        raise WorkflowPolicyError("Saved blocked tools must be an array of names")
    return blocked | {name.strip() for name in saved if name.strip()}


def requires_workflow_confirmation(schema: Any) -> bool:
    """Managed runs require approval unless trusted metadata explicitly allows it."""
    permissions = getattr(schema, "permissions", {})
    if not isinstance(permissions, dict) or permissions.get("auto_approve") is not True:
        return True
    check = getattr(schema, "requires_confirmation", None)
    return bool(check()) if callable(check) else True


def validate_managed_workflow(workflow: dict[str, Any], mode: str, registry: Any, *, interactive: bool = False) -> dict[str, list[dict[str, str]]]:
    """Preflight the whole managed recipe before any helper/tool can run."""
    try:
        from .workflow_validation import validate_workflow_document
    except ImportError:
        from workflow_validation import validate_workflow_document
    with config_scope(mode):
        diagnostics = validate_workflow_document(workflow, builder=True)
        get_workflow_excluded_tools(mode)  # Validate saved policy before helpers/effects.
        excluded = set(BUILDER_EXCLUDED_TOOLS)
    errors = diagnostics["errors"]
    try:
        approved_tools = validated_workflow_approval_tools(workflow)
    except WorkflowPolicyError as exc:
        errors.append({"path": "builder_unattended_approval", "message": str(exc)})
        return diagnostics
    if registry is None:
        errors.append({"path": "steps", "message": "Managed workflows require an effective tool registry"})
        return diagnostics
    for index, step in enumerate(workflow.get("steps", [])):
        if not isinstance(step, dict):
            continue
        name = step.get("tool")
        schema = registry.get_tool(name)
        if name in excluded or (schema is not None and getattr(schema, "background_required", False)):
            errors.append({"path": f"steps[{index}].tool", "message": "Tool is excluded from managed workflows"})
        if schema is not None and name not in approved_tools and not interactive and requires_workflow_confirmation(schema):
            errors.append({"path": f"steps[{index}].tool", "message": "This managed workflow requires interactive per-call approval in the workflow builder"})
    return diagnostics
