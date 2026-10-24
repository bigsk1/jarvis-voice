"""Workspace feature discovery and v2.2.0 argument contracts without Google calls."""

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
        "to": _nullable("string"),
        "subject": _nullable("string"),
        "body": _nullable("string"),
        "thread_id": _nullable("string"),
        "reply_all": {"type": "boolean", "default": False},
        "from_email": _nullable("string"),
        "direction": {"type": "string", "enum": ["auto", "ltr", "rtl"], "default": "auto"},
        "quote_original": {"type": "boolean", "default": False},
    },
    "draft_gmail_message": {
        "to": _nullable("string"),
        "subject": _nullable("string"),
        "body": _nullable("string"),
        "thread_id": _nullable("string"),
        "reply_all": {"type": "boolean", "default": False},
        "direction": {"type": "string", "enum": ["auto", "ltr", "rtl"], "default": "auto"},
    },
    "modify_doc_text": {
        "document_id": {"type": "string"},
        "start_index": _nullable("integer"),
        "end_index": _nullable("integer"),
        "text": _nullable("string"),
        "heading": _nullable("string"),
        "heading_level": _nullable("integer"),
        "tab_id": _nullable("string"),
        "end_of_segment": {"type": "boolean", "default": False},
    },
    "get_doc_as_markdown": {
        "document_id": {"type": "string"},
        "tab_id": _nullable("string"),
        "include_colors": {"type": "boolean", "default": False},
        "suggestions_view_mode": {"type": "string", "default": "DEFAULT_FOR_CURRENT_ACCESS"},
    },
    "list_contacts": {
        "page_size": {"type": "integer", "default": 100},
        "page_token": _nullable("string"),
        "sort_order": _nullable("string"),
        "request_sync_token": {"type": "boolean", "default": False},
        "sync_token": _nullable("string"),
    },
    "manage_event": {
        "action": {"type": "string"},
        **{name: _nullable("string") for name in (
            "color_id", "timezone", "start_timezone", "end_timezone", "start_time", "end_time",
        )},
    },
    "render_page_to_image": {
        "presentation_id": {"type": "string"},
        "page_object_id": {"type": "string"},
        "size": {"type": "string", "default": "MEDIUM"},
    },
    "get_drive_file_content": {"file_id": {"type": "string"}},
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
    ("send_gmail_message", {
        "thread_id": "thread-123", "body": "Reply with inherited subject", "reply_all": True,
    }),
    ("draft_gmail_message", {
        "thread_id": "thread-123", "body": "Unsent reply with inherited subject", "reply_all": True,
    }),
    ("modify_doc_text", {
        "document_id": "doc-123", "heading": "Results", "heading_level": 2,
        "tab_id": "t.1", "text": "**Additional result**", "end_of_segment": True,
    }),
    ("get_doc_as_markdown", {
        "document_id": "doc-123", "tab_id": "t.1", "include_colors": True,
        "suggestions_view_mode": "PREVIEW_WITHOUT_SUGGESTIONS",
    }),
    ("list_contacts", {"request_sync_token": True, "page_size": 50, "page_token": "next-page"}),
    ("list_contacts", {"sync_token": "sync-token", "page_size": 50}),
    ("manage_event", {
        "action": "create", "color_id": "tomato", "start_timezone": "Asia/Jerusalem",
        "end_timezone": "Europe/Amsterdam", "start_time": "2027-01-15T13:45:00",
        "end_time": "2027-01-15T17:50:00",
    }),
    ("render_page_to_image", {
        "presentation_id": "slides-123", "page_object_id": "page-123", "size": "LARGE",
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


def test_v220_guidance_explains_new_modes_without_implying_extra_authority():
    metadata = _config()["tool_metadata"]
    heading = metadata["modify_doc_text"]["description_prefix"]
    assert "matches exactly one heading case-insensitively" in heading
    assert "replaces the body below that heading" in heading
    assert "end_of_segment=true appends" in heading
    assert "Multi-tab documents require tab_id" in heading
    assert "Do not combine heading with start_index, end_index or segment_id" in heading
    assert "theme colors are not shown" in metadata["get_doc_as_markdown"]["description_prefix"]
    contacts = metadata["list_contacts"]["description_prefix"]
    assert "Keep all other arguments unchanged" in contacts
    assert "sort_order is not allowed while syncing" in contacts
    assert "expire after seven days" in contacts and "requires a new full sync" in contacts
    assert "does not synchronize or edit config/contacts.json" in contacts
    calendar = metadata["manage_event"]["description_prefix"]
    assert "tomato or numeric IDs 1-11" in calendar
    assert "Explicit RFC3339 offsets preserve the exact instant" in calendar
    assert "All-day end dates are exclusive" in calendar
    for tool_name in ("send_gmail_message", "draft_gmail_message"):
        assert "inherit the parent message's subject" in metadata[tool_name]["description_prefix"]
        assert "explicit to/cc win" in metadata[tool_name]["description_prefix"]


def test_image_guidance_uses_stash_analysis_instead_of_claiming_automatic_vision():
    metadata = _config()["tool_metadata"]
    for tool_name in ("render_page_to_image", "get_drive_file_content"):
        text = metadata[tool_name]["description_prefix"]
        assert "Stash" in text and "analyze_image" in text
        assert "not automatically" in text
    assert "size=MEDIUM" in metadata["render_page_to_image"]["description_prefix"]
    assert "do not share" in metadata["render_page_to_image"]["description_prefix"]


def test_v220_catalog_replaces_slide_thumbnail_without_growing_the_tool_set():
    fixture = json.loads((ROOT / "tests/fixtures/google_workspace_tool_names.json").read_text())
    assert fixture['image'].endswith(':2.2.0')
    assert fixture['upstream_commit'] == 'b5cf07e6078ae10a596710d77569e9430e01ebd4'
    assert len(fixture['tools']) == len(set(fixture['tools'])) == 111
    assert 'render_page_to_image' in fixture['tools']
    assert 'get_page_thumbnail' not in fixture['tools']
