"""Workspace feature discovery and v2.1.2 argument contracts without Google calls."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))

import test_mcp_discovery_graceful as discovery_helpers
from mcp_client import MCPRemoteClient
from router_v2 import expand_prerequisite_tool_names

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "mcp_google_workspace_"


def _nullable(kind: str) -> dict:
    return {"anyOf": [{"type": kind}, {"type": "null"}], "default": None}


# Representative added fields from the tagged upstream schemas. The local
# metadata must supplement discovery without replacing those schemas.
FEATURE_PARAMETERS = {
    "send_gmail_message": {
        "to": {"type": "string"},
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "from_email": _nullable("string"),
        "direction": {"type": "string", "enum": ["auto", "ltr", "rtl"], "default": "auto"},
        "quote_original": {"type": "boolean", "default": False},
    },
    "draft_gmail_message": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "direction": {"type": "string", "enum": ["auto", "ltr", "rtl"], "default": "auto"},
    },
    "batch_modify_gmail_message_labels": {
        name: {"type": "array", "items": {"type": "string"}, "default": None}
        for name in ("message_ids", "thread_ids", "add_label_ids", "remove_label_ids")
    },
    "format_sheet_range": {
        "spreadsheet_id": {"type": "string"},
        "range_name": {"type": "string"},
        **{name: _nullable("boolean") for name in (
            "merge_cells", "dropdown_strict", "clear_dropdown",
        )},
        **{name: _nullable("string") for name in (
            "merge_type", "borders", "border_style", "border_color",
        )},
        "dropdown_values": {
            "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}],
            "default": None,
        },
    },
    "manage_sheet_tab": {
        "spreadsheet_id": {"type": "string"},
        "sheet_name": {"type": "string"},
        "action": {"type": "string"},
        "tab_color": _nullable("string"),
        "show_gridlines": _nullable("boolean"),
    },
    "manage_doc_tab": {
        "document_id": {"type": "string"},
        "tab_id": _nullable("string"),
        "action": {"type": "string", "enum": [
            "create", "rename", "delete", "populate_from_markdown",
        ]},
        "markdown_text": _nullable("string"),
        "replace_existing": {"type": "boolean", "default": True},
    },
    "debug_table_structure": {
        "document_id": {"type": "string"},
        "tab_id": _nullable("string"),
    },
    "copy_drive_file": {
        "file_id": {"type": "string"},
        "parent_folder_id": {"type": "string", "default": "root"},
        "copy_comments": {"type": "boolean", "default": False},
    },
    "import_to_google_doc": {
        "file_name": {"type": "string"},
        "content": _nullable("string"),
        "source_format": _nullable("string"),
    },
}


def _config() -> dict:
    return json.loads((ROOT / "config/mcp-servers.json").read_text())["mcpServers"][
        "google_workspace"
    ]


def _tools() -> list[dict]:
    names = json.loads((ROOT / "tests/fixtures/google_workspace_tool_names.json").read_text())[
        "tools"
    ]
    return [{
        "name": name,
        "description": f"Upstream {name} contract.",
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_google_email": {"type": "string"},
                **deepcopy(FEATURE_PARAMETERS.get(name, {})),
            },
            "required": ["user_google_email"],
        },
    } for name in names]


class _FeatureClient(discovery_helpers.FakeRemoteClient):
    def __init__(self):
        super().__init__()
        self.name = "google_workspace"
        self.tool_defaults = {"user_google_email": "dedicated@example.test"}

    def list_tools(self):
        return _tools()


def _registry(profile_overrides: dict | None = None):
    return discovery_helpers.TestMCPDiscoveryGraceful()._build_registry(
        _FeatureClient(), tool_metadata=_config()["tool_metadata"],
        profile_overrides=profile_overrides,
    )


@pytest.mark.parametrize("tool_name", FEATURE_PARAMETERS)
def test_feature_metadata_preserves_provider_schemas_and_account_binding(tool_name):
    registry = _registry()
    schema = registry.get_tool(PREFIX + tool_name)
    assert schema is not None
    assert schema.description.endswith(f"Upstream {tool_name} contract.")
    expected = FEATURE_PARAMETERS[tool_name]
    properties = schema.parameters["properties"]
    assert properties.keys() == expected.keys()
    for name, contract in expected.items():
        assert {key: properties[name][key] for key in contract} == contract
    projections = [
        schema.to_openai_format()["function"]["parameters"],
        schema.to_anthropic_format()["input_schema"],
    ]
    for parameters in projections:
        assert expected.keys() <= parameters["properties"].keys()
        assert "user_google_email" not in parameters["properties"]
    if "direction" in expected:
        assert projections[0]["properties"]["direction"]["enum"] == ["auto", "ltr", "rtl"]
    assert schema.permissions["dangerous"] is True
    assert schema.permissions["auto_approve"] is True


@pytest.mark.parametrize(("tool_name", "argument"), [
    ("manage_doc_tab", {
        "document_id": "doc-123", "tab_id": "t.1", "action": "populate_from_markdown",
        "markdown_text": "| Name | Status |\n| --- | --- |\n| Test | Open |",
        "replace_existing": False,
    }),
    ("format_sheet_range", {
        "spreadsheet_id": "sheet-123", "range_name": "Report!A1:C1",
        "merge_cells": True, "merge_type": "MERGE_ALL", "borders": "outer",
        "border_style": "SOLID", "border_color": "#000000",
        "dropdown_values": ["Open", "Done"], "dropdown_strict": False,
        "clear_dropdown": False,
    }),
    ("manage_sheet_tab", {
        "spreadsheet_id": "sheet-123", "sheet_name": "Report", "action": "style",
        "tab_color": "#FF0000", "show_gridlines": False,
    }),
    ("copy_drive_file", {
        "file_id": "doc-123", "parent_folder_id": "folder-123", "copy_comments": True,
    }),
    ("batch_modify_gmail_message_labels", {
        "thread_ids": ["1abc", "2def"], "remove_label_ids": ["INBOX"],
    }),
    ("send_gmail_message", {
        "to": "recipient@example.test", "subject": "Test", "body": "Hello",
        "direction": "rtl", "include_signature": False,
    }),
    ("draft_gmail_message", {
        "to": "recipient@example.test", "subject": "Test", "body": "Hello",
        "direction": "ltr",
    }),
    ("debug_table_structure", {"document_id": "doc-123", "tab_id": "t.1"}),
    ("import_to_google_doc", {
        "file_name": "Report.md", "source_format": "md", "content": "# Report",
    }),
])
def test_feature_arguments_reach_mcp_unchanged(monkeypatch, tool_name, argument):
    client = MCPRemoteClient("google_workspace", "http://localhost/mcp", "http")
    client.tool_defaults = {"user_google_email": "dedicated@example.test"}
    client._tools_cache = _tools()
    sent = []

    def send(method, parameters):
        sent.append((method, deepcopy(parameters)))
        return {"content": [{"type": "text", "text": "ID: receipt-123"}]}

    monkeypatch.setattr(client, "_send_request", send)
    client.call_tool(tool_name, argument)
    assert sent == [("tools/call", {
        "name": tool_name,
        "arguments": {**argument, "user_google_email": "dedicated@example.test"},
    })]


def test_inspection_prerequisites_stay_bounded_and_respect_exclusions():
    registry = _registry()
    dependents = [PREFIX + name for name in (
        "format_sheet_range", "manage_doc_tab", "copy_drive_file",
    )]
    blocked = PREFIX + "read_sheet_values"
    names, added = expand_prerequisite_tool_names(
        dependents, registry, registry.list_tools(), excluded_tools={blocked}, max_added=3,
    )
    assert len(added) == 3
    assert blocked not in names
    assert set(dependents) <= set(names)
    assert names.index(PREFIX + "inspect_doc_structure") < names.index(PREFIX + "manage_doc_tab")
    hidden_registry = _registry({PREFIX + "inspect_doc_structure": False})
    names, _ = expand_prerequisite_tool_names(
        [PREFIX + "manage_doc_tab"], hidden_registry, hidden_registry.list_tools(),
    )
    assert names == [PREFIX + "manage_doc_tab"]


def test_guidance_keeps_gmail_routing_and_destructive_boundaries_explicit():
    metadata = _config()["tool_metadata"]
    assert "prefer the native send_email" in metadata["send_gmail_message"]["description_prefix"]
    assert "Draft ID, not a Gmail Message ID" in metadata["draft_gmail_message"]["description_prefix"]
    assert "replace_existing=false to append" in metadata["manage_doc_tab"]["description_prefix"]
    assert "top-left value" in metadata["format_sheet_range"]["description_prefix"]
    assert "including checkboxes" in metadata["format_sheet_range"]["description_prefix"]
    assert "partial receipt" in metadata["batch_modify_gmail_message_labels"]["description_prefix"]
    assert "not a named revision or automatic undo" in metadata["copy_drive_file"]["description_prefix"]
