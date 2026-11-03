"""The CLI and builder share pure workflow diagnostics."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from config_loader import config_scope
from workflow_validation import validate_workflow_document

ROOT = Path(__file__).resolve().parents[1]


def document(**fields):
    return {"id": "test_recipe", "triggers": {"explicit": ["/test_recipe"]},
            "steps": [{"step": 1, "tool": "get_time", "params": {}}], **fields}


def test_existing_shared_definitions_validate_without_runtime_dependencies():
    with config_scope("cloud", overrides={"WORKFLOW_BUILDER_ALLOWED_ENV_KEYS": ""}):
        for path in (ROOT / "data/workflows").glob("*.json"):
            diagnostics = validate_workflow_document(json.loads(path.read_text()), builder=True)
            legacy = validate_workflow_document(json.loads(path.read_text()))
            assert diagnostics["errors"] == legacy["errors"], (path.name, diagnostics["errors"])


@pytest.mark.parametrize("value", [None, [], "object", {"steps": [None]}, document(variables=[]), document(triggers={"explicit": [None]})])
def test_malformed_documents_produce_diagnostics_instead_of_exceptions(value):
    assert validate_workflow_document(value, builder=True)["errors"]


@pytest.mark.parametrize("condition", [{"op": "execute_python", "left": True}, {"op": []}, {"all": True}, {"all": [], "any": []}, {"op": "eq", "left": "one"}])
def test_builder_rejects_conditions_that_runtime_would_fail_open(condition):
    data = document(steps=[{"step": 1, "tool": "get_time", "condition": condition}])
    errors = validate_workflow_document(data, builder=True)["errors"]
    assert any(item["path"].startswith("steps[0].condition") for item in errors)


def test_env_key_allowlist_never_resolves_or_echoes_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-that-must-never-be-resolved")
    data = document(variables={"summary": {"from": "env", "key": "OPENAI_API_KEY"}})
    diagnostics = validate_workflow_document(data, builder=True)
    assert diagnostics["errors"]
    assert "secret-that-must-never-be-resolved" not in json.dumps(diagnostics)
    with config_scope("cloud", overrides={"WORKFLOW_BUILDER_ALLOWED_ENV_KEYS": "REVIEWED_REPORT_LANGUAGE"}):
        allowed = document(variables={"language": {"from": "env", "key": "REVIEWED_REPORT_LANGUAGE"}})
        assert not validate_workflow_document(allowed, builder=True)["errors"]


def test_trigger_collisions_match_runtime_case_insensitivity():
    existing = document(id="other", triggers={"explicit": ["/Test_Recipe"]})
    diagnostics = validate_workflow_document(document(), builder=True, workflows=[existing])
    assert any("already used" in error["message"] for error in diagnostics["errors"])
    assert not validate_workflow_document(document(), builder=True, workflows=[document()])["errors"]


def test_unknown_fields_roundtrip_unchanged_and_cli_shares_canvas_rules():
    data = document(unknown_feature={"nested": [1, False]}, steps=[{
        "step": 1, "tool": "canvas", "action": "create", "llm_prompt": "Create content", "params": {},
    }])
    snapshot = json.loads(json.dumps(data))
    spec = importlib.util.spec_from_file_location("workflow_authoring_contract", ROOT / "data/workflows/skill/skill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    errors, _ = module._check_workflow(data)
    diagnostics = validate_workflow_document(data)
    assert errors == [item["message"] for item in diagnostics["errors"]]
    assert any("needs validation" in error for error in errors)
    assert data == snapshot


@pytest.mark.parametrize("trigger", ["!daily", "*", "run daily brief", "/ordinary"])
def test_runtime_non_slash_prefixes_remain_valid_explicit_triggers(trigger):
    assert not validate_workflow_document(document(triggers={"explicit": [trigger]}), builder=True)["errors"]


def test_overlapping_prefixes_warn_without_blocking_longest_match_behavior():
    diagnostics = validate_workflow_document(
        document(triggers={"explicit": ["!Daily"]}), builder=True,
        workflows=[document(id="longer", triggers={"explicit": ["!daily brief"]})],
    )
    assert diagnostics["errors"] == []
    assert any("prefixes overlap" in item["message"] for item in diagnostics["warnings"])
    same = validate_workflow_document(document(triggers={"explicit": ["!Daily", "!daily"]}), builder=True)
    assert any("Duplicate" in item["message"] for item in same["errors"])


@pytest.mark.parametrize("key", ["OPENAI_API_KEY", "SESSION_TOKEN", "APP_SECRET", "DATABASE_PASSWORD", "PASSWORD", "TOKEN"])
def test_secret_looking_operator_additions_cannot_enable_environment_reads(key):
    with config_scope("cloud", overrides={"WORKFLOW_BUILDER_ALLOWED_ENV_KEYS": key}):
        value = document(variables={"innocent": {"from": "env", "key": key}})
        assert validate_workflow_document(value, builder=True)["errors"]


def test_binding_diagnostics_cover_forward_missing_and_reused_outputs_without_hard_errors():
    value = document(steps=[
        {"step": 1, "tool": "get_time", "params": {"text": "${later.value} ${missing}"}, "output_var": "first"},
        {"step": 2, "tool": "get_time", "params": {}, "output_var": "later"},
        {"step": 3, "tool": "get_time", "params": {}, "output_var": "first"},
    ])
    diagnostics = validate_workflow_document(value, builder=True)
    assert diagnostics["errors"] == []
    messages = [item["message"] for item in diagnostics["warnings"]]
    assert any("Forward reference" in message and "later.value" in message for message in messages)
    assert any("Undefined workflow variable: missing" in message for message in messages)
    assert any("reuses an earlier variable" in message for message in messages)


def test_binding_analysis_knows_runtime_aliases_and_loop_index_scope():
    value = document(steps=[
        {"step": 1, "tool": "mcp_brave_search_brave_web_search", "params": {}},
        {"step": 2, "tool": "crawl_url", "for_each": "${search_results.urls[:3]}", "params": {"label": "${_loop_index}"}},
        {"step": 3, "tool": "canvas", "params": {"content": "${validated_articles}"}},
    ])
    assert not validate_workflow_document(value, builder=True)["warnings"]
    value["steps"][2]["params"]["content"] = "${_loop_index}"
    warnings = validate_workflow_document(value, builder=True)["warnings"]
    assert any("Undefined workflow variable: _loop_index" in item["message"] for item in warnings)


def test_optional_output_default_avoids_missing_value_warning():
    value = document(steps=[
        {"step": 1, "tool": "get_time", "params": {}, "required": False, "output_var": "optional_output"},
        {"step": 2, "tool": "get_time", "params": {"text": "${optional_output}"}},
    ])
    assert any("may be absent" in item["message"] for item in validate_workflow_document(value, builder=True)["warnings"])
    value["variables"] = {"optional_output": {"from": "static", "value": {}}}
    assert not any("may be absent" in item["message"] for item in validate_workflow_document(value, builder=True)["warnings"])


@pytest.mark.parametrize("steps", [None, "steps", {}])
def test_malformed_steps_never_crash_binding_analysis(steps):
    assert validate_workflow_document(document(steps=steps), builder=True)["errors"]


def test_non_json_numbers_reject_with_diagnostic():
    assert validate_workflow_document(document(variables={"bad": float("nan")}), builder=True)["errors"]


def test_trigger_collision_case_normalization_matches_runtime_lower_not_casefold():
    existing = document(id="different", triggers={"explicit": ["/STRASSE"]})
    diagnostics = validate_workflow_document(document(triggers={"explicit": ["/straße"]}), builder=True, workflows=[existing])
    assert not diagnostics["errors"]


@pytest.mark.parametrize("tool", ["opencode", "workflow", "browser_use", "browser_use_cloud"])
def test_hard_excluded_tools_cannot_publish_even_when_optional(tool):
    value = document(steps=[{"step": 1, "tool": tool, "required": False, "params": {}}])
    assert validate_workflow_document(value)["errors"] == []
    assert any("excluded" in error["message"] for error in validate_workflow_document(value, builder=True)["errors"])


def test_builder_ids_match_approved_lowercase_digit_underscore_policy():
    assert not validate_workflow_document(document(id="_personal_recipe"), builder=True)["errors"]
    assert validate_workflow_document(document(id="invalid\n"), builder=True)["errors"]


@pytest.mark.parametrize("other", [None, [], "invalid", {"triggers": []}, {"triggers": {"explicit": None}}, {"triggers": {"explicit": [None, {}]}}])
def test_invalid_other_inventory_records_do_not_break_validation(other):
    assert isinstance(validate_workflow_document(document(), builder=True, workflows=[other]), dict)
