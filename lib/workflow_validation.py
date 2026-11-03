"""Pure diagnostics for workflow JSON; validation never resolves config or runs tools."""

from __future__ import annotations

import json
import re
from typing import Any

ID_RE = re.compile(r"^[a-z0-9_]+$")
CONDITION_OPS = frozenset({"truthy", "exists", "not_exists", "eq", "ne", "lt", "lte", "gt", "gte", "contains", "contains_any"})

def _has_validated_content_prefix(steps: list, target: dict, content: str) -> bool:
    """Recognize a full-page brief validated before deterministic publication."""
    saved_ids = {}
    content_vars = set()
    for producer in steps:
        if producer is target:
            break
        if (
            not isinstance(producer, dict)
            or producer.get("required", True) is not True
            or producer.get("on_fail") == "continue"
            or producer.get("condition") not in (None, target.get("condition"))
        ):
            continue
        if producer.get("tool") != "stash":
            continue
        params = producer.get("params", {})
        extracts = producer.get("extract", {})
        validation = producer.get("llm_output_validation", {})
        if not all(isinstance(value, dict) for value in (params, extracts, validation)):
            continue
        action = producer.get("action", params.get("action"))
        patterns = validation.get("required_patterns", [])
        if (
            action == "save"
            and params.get("kind") == "text"
            and validation.get("param") == "text"
            and isinstance(patterns, list)
            and len(patterns) >= 3
            and any(isinstance(pattern, str) and pattern.startswith("# ") for pattern in patterns)
        ):
            for name, path in extracts.items():
                if path == "file_id":
                    saved_ids[f"${{{name}}}"] = params.get("space_id")
        elif (
            action == "read"
            and params.get("mode") == "text"
            and params.get("file_id") in saved_ids
            and params.get("space_id") == saved_ids[params["file_id"]]
        ):
            content_vars.update(name for name, path in extracts.items() if path == "content")
    return any(content.lstrip().startswith(f"${{{name}}}") for name in content_vars)


def _authoring_checks(
    workflow: dict[str, Any], *, is_personal: bool = False
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    workflow_id = workflow.get("id")
    if not isinstance(workflow_id, str) or not workflow_id.strip():
        errors.append("Missing string field: id")
    elif not ID_RE.fullmatch(workflow_id):
        errors.append("id should use lowercase letters, digits, and underscores")

    steps = workflow.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps must be a non-empty list")
        steps = []

    triggers = workflow.get("triggers", {})
    explicit = triggers.get("explicit", []) if isinstance(triggers, dict) else []
    if not isinstance(explicit, list) or not explicit:
        warnings.append("Add triggers.explicit so the workflow can be invoked predictably")
    else:
        for trigger in explicit:
            if not isinstance(trigger, str) or not trigger.strip():
                errors.append(f"Invalid explicit trigger: {trigger!r}")
        if len(explicit) > 1 and not is_personal:
            warnings.append(
                "Shared workflows should define one canonical triggers.explicit command; "
                "additional entries are only for temporary rename compatibility"
            )

    seen_step_numbers: set[int] = set()
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            errors.append(f"Step {index} must be an object")
            continue

        step_num = step.get("step", index)
        if isinstance(step_num, int):
            if step_num in seen_step_numbers:
                errors.append(f"Duplicate step number: {step_num}")
            seen_step_numbers.add(step_num)
        else:
            errors.append(f"Step {index} has non-integer step value")

        tool = step.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            errors.append(f"Step {step_num}: missing tool")

        action = step.get("action")
        validation = step.get("llm_output_validation")
        if step.get("llm_prompt") and not isinstance(validation, dict):
            warnings.append(
                f"Step {step_num}: llm_prompt should usually define llm_output_validation"
            )

        if tool == "canvas" and action in {"create", "update"} and step.get("llm_prompt"):
            if not isinstance(validation, dict):
                errors.append(f"Step {step_num}: Canvas {action} with llm_prompt needs validation")
            else:
                rejects = {str(item).lower() for item in validation.get("reject_patterns", [])}
                for pattern in ("```", "<html", "<pre", "https://..."):
                    if pattern not in rejects:
                        warnings.append(
                            f"Step {step_num}: consider rejecting {pattern!r} in Canvas output"
                        )

        params = step.get("params", {})
        if (
            tool == "canvas"
            and action == "update"
            and isinstance(params, dict)
            and params.get("allow_content_shrink") is True
        ):
            required = (
                validation.get("required_patterns", []) if isinstance(validation, dict) else []
            )
            content = str(params.get("content") or "")
            required_headings_in_content = [
                heading
                for heading in ("# ", "## Current Status", "## Run Log")
                if heading in content
            ]
            if (
                len(required) < 3
                and len(required_headings_in_content) < 3
                and not _has_validated_content_prefix(steps, step, content)
            ):
                errors.append(
                    f"Step {step_num}: allow_content_shrink=true requires strong required_patterns or deterministic full-page content"
                )

    if workflow.get("disable_server_side_tools") is True:
        llm_steps = [step for step in steps if isinstance(step, dict) and step.get("llm_prompt")]
        if not llm_steps:
            warnings.append("disable_server_side_tools=true has no llm_prompt steps to protect")

    return errors, warnings



def _condition_errors(condition: Any, path: str) -> list[dict[str, str]]:
    errors = []
    if isinstance(condition, list):
        for index, item in enumerate(condition):
            errors.extend(_condition_errors(item, f"{path}[{index}]"))
    elif isinstance(condition, dict):
        groups = [key for key in ("all", "any") if key in condition]
        if groups:
            if len(groups) != 1 or len(condition) != 1:
                errors.append({"path": path, "message": "Use exactly one all/any condition group"})
            for group in groups:
                if not isinstance(condition[group], list):
                    errors.append({"path": f"{path}.{group}", "message": "Condition group must be an array"})
                else:
                    errors.extend(_condition_errors(condition[group], f"{path}.{group}"))
        elif not isinstance(condition.get("op", "truthy"), str) or condition.get("op", "truthy") not in CONDITION_OPS:
            errors.append({"path": f"{path}.op", "message": "Unsupported condition operator"})
        elif "left" not in condition:
            errors.append({"path": f"{path}.left", "message": "Condition requires a left value"})
        elif condition.get("op", "truthy") not in {"truthy", "exists", "not_exists"} and "right" not in condition:
            errors.append({"path": f"{path}.right", "message": "Comparison requires a right value"})
    elif condition is not None and not isinstance(condition, (str, bool, int, float)):
        errors.append({"path": path, "message": "Invalid condition value"})
    return errors


_INITIAL_BINDINGS = frozenset({"query", "topic", "content", "workflow_id", "timestamp", "filename_timestamp"})
_TEMPLATE_REFERENCE = re.compile(r"\$\{([^}]+)\}")


def _template_references(value: Any, path: str):
    if isinstance(value, str):
        for match in _TEMPLATE_REFERENCE.finditer(value):
            expression = match.group(1)
            root = re.split(r"[.\[]", expression, maxsplit=1)[0]
            if root and root != "llm_decides":
                yield root, expression, path
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _template_references(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _template_references(child, f"{path}[{index}]")


def _step_bindings(step: dict, index: int) -> tuple[set[str], set[str]]:
    """Return explicit bindings and runtime compatibility aliases separately."""
    explicit = {name for name in step.get("extract", {}) if isinstance(name, str)}
    for field in ("output_var", "search_output_var", "validated_output_var"):
        if isinstance(step.get(field), str) and step[field]:
            explicit.add(step[field])
    implicit: set[str] = set()
    name = str(step.get("tool", "")).lower()
    params = step.get("params", {})
    action = step.get("action") or params.get("action")
    if "for_each" in step:
        if not step.get("output_var"):
            implicit.add(f"step{step.get('step', index + 1)}_results")
        if name == "crawl_url" and not step.get("validated_output_var"):
            implicit.add("validated_articles")
        return explicit, implicit
    if name == "crawl_url":
        implicit.add(step.get("output_var") or "article")
    if name not in {"serpapi_google_trends", "serpapi_google_trending_now"} and any(
        indicator in name for indicator in ("search", "brave", "serp", "google", "bing", "duckduckgo")
    ):
        implicit.add(step.get("search_output_var") or "search_results")
    aliases = {"remember": "memory_id", "canvas": "canvas_id", "list_reminders": "reminders_markdown",
               "ssh_remote": "ssh_output", "generate_image": "image_path"}
    if name in aliases:
        implicit.add(aliases[name])
    if name == "stash" and action == "open_space":
        implicit.add("space_id")
    return explicit, implicit


def _binding_warnings(workflow: dict) -> list[dict[str, str]]:
    """Diagnose missing/forward roots without guessing tools' output field shapes."""
    warnings: list[dict[str, str]] = []
    raw_steps = workflow.get("steps")
    steps = [step for step in raw_steps if isinstance(step, dict)] if isinstance(raw_steps, list) else []
    declarations = workflow.get("variables", {})
    known = set(_INITIAL_BINDINGS) | set(declarations)
    defaults = set(_INITIAL_BINDINGS) | {
        name for name, value in declarations.items()
        if not isinstance(value, dict) or value.get("from") == "static" or "default" in value
    }
    uncertain: set[str] = set()
    all_bindings = [_step_bindings(step, index) for index, step in enumerate(steps)]
    emitted: set[tuple[str, str]] = set()

    def warn_refs(value: Any, path: str, available: set[str], future: set[str]):
        for root, expression, reference_path in _template_references(value, path):
            if root not in available:
                qualifier = "Forward reference to an output not yet produced" if root in future else "Undefined workflow variable"
                message = f"{qualifier}: {expression}"
            elif root in uncertain and root not in defaults:
                message = f"Output {root} may be absent after an optional or conditional producer; provide a default or skip assignment"
            else:
                continue
            if (reference_path, message) not in emitted:
                warnings.append({"path": reference_path, "message": message})
                emitted.add((reference_path, message))

    for name, definition in declarations.items():
        if isinstance(definition, dict) and definition.get("transform"):
            source = definition.get("from")
            if isinstance(source, str) and source not in known:
                warnings.append({"path": f"variables.{name}.from", "message": f"Undefined transform source: {source}"})
    for index, step in enumerate(steps):
        explicit, implicit = all_bindings[index]
        future = set().union(*(first | second for first, second in all_bindings[index:]))
        path = f"steps[{index}]"
        # Conditions and the iteration source run before a loop index exists.
        for field in ("condition", "for_each", "set_variables_on_skip"):
            warn_refs(step.get(field), f"{path}.{field}", known, future)
        available = known | ({"_loop_index"} if "for_each" in step else set())
        for field in ("params", "llm_prompt", "validation", "llm_output_validation"):
            warn_refs(step.get(field), f"{path}.{field}", available, future)
        for name in explicit & known:
            warnings.append({"path": path, "message": f"Output binding {name} reuses an earlier variable; verify the intended source"})
        assignments = step.get("set_variables_on_success", {})
        warn_refs(assignments, f"{path}.set_variables_on_success", available | explicit | implicit, future)
        produced = explicit | implicit | set(assignments)
        known |= produced | set(step.get("set_variables_on_skip", {}))
        if step.get("required", True) is False or step.get("condition") is not None or step.get("on_fail") == "continue":
            uncertain |= produced
        # Defaults and explicit skip assignments keep downstream references usable.
        defaults |= set(step.get("set_variables_on_skip", {}))
    for field in ("success_speech", "success_speech_llm_prompt"):
        warn_refs(workflow.get(field), field, known | {"article_count"}, set())
    return warnings


def _prefix_warnings(explicit: list[str], workflow: dict, workflows) -> list[dict[str, str]]:
    warnings = []
    candidates = list(explicit)
    for other in workflows:
        if isinstance(other, dict) and other.get("id") != workflow.get("id"):
            triggers = other.get("triggers", {})
            if isinstance(triggers, dict) and isinstance(triggers.get("explicit", []), list):
                candidates.extend(value for value in triggers.get("explicit", []) if isinstance(value, str))
    for trigger in explicit:
        for other in candidates:
            first, second = trigger.lower(), other.lower()
            if first != second and (first.startswith(second) or second.startswith(first)):
                warnings.append({"path": "triggers.explicit", "message": "Explicit trigger prefixes overlap; runtime selects the longest matching prefix"})
                return warnings
    return warnings


def validate_workflow_document(workflow: Any, *, builder: bool = False, workflows=()) -> dict[str, list[dict[str, str]]]:
    """Return structured errors/warnings without executing tools or resolving env values.

    Legacy callers keep the author's existing rules; builder mode adds strict
    shape, condition, source and trigger collision checks. Unknown fields survive.
    """
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(workflow, dict):
        return {"errors": [{"path": "$", "message": "Workflow root must be a JSON object"}], "warnings": []}
    try:
        json.dumps(workflow, allow_nan=False)
    except (TypeError, ValueError):
        return {"errors": [{"path": "$", "message": "Workflow must contain only finite JSON values"}], "warnings": []}
    workflows = tuple(workflows)
    # Shape guards keep the authoring rules safe for arbitrary submitted JSON.
    for key in ("triggers", "variables", "tool_defaults", "validation_policy", "workflow_llm_options"):
        if key in workflow and not isinstance(workflow[key], dict):
            errors.append({"path": key, "message": f"{key} must be an object"})
    steps = workflow.get("steps")
    if isinstance(steps, list):
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append({"path": f"steps[{index}]", "message": "Step must be an object"})
                continue
            if builder:
                for key in ("output_var", "search_output_var", "validated_output_var"):
                    if key in step and (not isinstance(step[key], str) or not step[key].strip()):
                        errors.append({"path": f"steps[{index}].{key}", "message": f"{key} must be a nonempty binding name"})
            for key in ("params", "extract", "retry", "validation", "llm_output_validation", "set_variables_on_success", "set_variables_on_skip"):
                if key in step and not isinstance(step[key], dict):
                    errors.append({"path": f"steps[{index}].{key}", "message": f"{key} must be an object"})
    triggers = workflow.get("triggers", {})
    if isinstance(triggers, dict):
        for key in ("explicit", "patterns", "keywords"):
            if key in triggers and (not isinstance(triggers[key], list) or any(not isinstance(item, str) for item in triggers[key])):
                errors.append({"path": f"triggers.{key}", "message": "Trigger values must be strings in an array"})
    if errors:
        return {"errors": errors, "warnings": warnings}
    try:
        old_errors, old_warnings = _authoring_checks(workflow, is_personal=True if builder else False)
        errors.extend({"path": "$", "message": message} for message in old_errors)
        warnings.extend({"path": "$", "message": message} for message in old_warnings)
    except (TypeError, ValueError, AttributeError):
        errors.append({"path": "$", "message": "Malformed workflow validation settings"})
    if builder:
        try:
            from .workflow_policy import (
                BUILDER_EXCLUDED_TOOLS,
                BUILDER_POLICY_VERSION,
                get_workflow_allowed_env_keys,
            )
        except ImportError:
            from workflow_policy import (
                BUILDER_EXCLUDED_TOOLS,
                BUILDER_POLICY_VERSION,
                get_workflow_allowed_env_keys,
            )
        try:
            allowed_env = get_workflow_allowed_env_keys()
        except ValueError:
            errors.append({"path": "$policy", "message": "Trusted workflow environment allowlist configuration is invalid"})
            return {"errors": errors, "warnings": warnings}
        if "builder_policy_version" in workflow and (type(workflow["builder_policy_version"]) is not int or workflow["builder_policy_version"] != BUILDER_POLICY_VERSION):
            errors.append({"path": "builder_policy_version", "message": "Unsupported builder policy version"})
        for name, definition in workflow.get("variables", {}).items():
            if isinstance(definition, dict) and definition.get("from") == "env":
                key = definition.get("key", name)
                if not isinstance(key, str) or key not in allowed_env:
                    errors.append({"path": f"variables.{name}", "message": "Environment source is not in the reviewed workflow allowlist"})
        for index, step in enumerate(steps if isinstance(steps, list) else []):
            if isinstance(step, dict):
                if isinstance(step.get("tool"), str) and step["tool"] in BUILDER_EXCLUDED_TOOLS:
                    errors.append({"path": f"steps[{index}].tool", "message": "Tool is excluded from managed workflows"})
                errors.extend(_condition_errors(step.get("condition"), f"steps[{index}].condition"))
                for key in ("required", "process_all"):
                    if key in step and type(step[key]) is not bool:
                        errors.append({"path": f"steps[{index}].{key}", "message": f"{key} must be a boolean"})
                if "step" in step and type(step["step"]) is not int:
                    errors.append({"path": f"steps[{index}].step", "message": "Step number must be an integer"})
        warnings.extend(_binding_warnings(workflow))
        explicit = triggers.get("explicit", [])
        warnings.extend(_prefix_warnings(explicit, workflow, workflows))
        explicit_folded = {item.lower() for item in explicit}
        if len(explicit_folded) != len(explicit):
            errors.append({"path": "triggers.explicit", "message": "Duplicate explicit trigger"})
        if not explicit:
            errors.append({"path": "triggers.explicit", "message": "Provide a canonical explicit trigger"})
        for other in workflows:
            if not isinstance(other, dict) or other.get("id") == workflow.get("id"):
                continue
            other_triggers = other.get("triggers", {})
            if not isinstance(other_triggers, dict):
                continue
            other_explicit = other_triggers.get("explicit", [])
            if not isinstance(other_explicit, list):
                continue
            if explicit_folded.intersection(item.lower() for item in other_explicit if isinstance(item, str)):
                errors.append({"path": "triggers.explicit", "message": "Explicit trigger is already used by another workflow"})
                break
    return {"errors": errors, "warnings": warnings}
