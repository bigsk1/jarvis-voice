"""Calendar ACLs, section reads and copy/shortcut identity survive Jarvis handoffs."""

import json

import google_workspace as workspace
import pytest
from test_deepwiki_context import _assembler, followup
from test_google_workspace_feature_guidance import PREFIX, _config, _registry
from test_structured_results_adapters import _run_renderer_assertions


def _receipt(tool, text, arguments):
    return workspace.normalize_workspace_result(tool, {
        "content": [{"type": "text", "text": text}],
        "structuredContent": {"result": text},
    }, arguments)


@pytest.mark.parametrize(("tool", "arguments", "text"), [
    ("manage_calendar", {
        "action": "create", "summary": "Fixture calendar", "timezone": "America/Los_Angeles",
    }, "Created calendar 'Fixture calendar' (ID: fixture@group.calendar.google.com)"),
    ("manage_calendar", {
        "action": "update_sharing", "calendar_id": "fixture@group.calendar.google.com",
        "rule_id": "user:reader@example.test", "role": "writerWithoutPrivateAccess",
        "send_notifications": False,
    }, "Updated sharing on calendar 'fixture@group.calendar.google.com':\n"
       "- writerWithoutPrivateAccess: user reader@example.test (Rule ID: user:reader@example.test)"),
    ("manage_calendar", {
        "action": "share", "calendar_id": "fixture@group.calendar.google.com",
        "role": "reader", "scope_type": "group", "scope_value": "team@example.test",
        "send_notifications": False,
    }, "Shared calendar 'fixture@group.calendar.google.com':\n"
       "- reader: group team@example.test (Rule ID: group:team@example.test)"),
    ("create_sheet", {
        "spreadsheet_id": "source-123", "source_sheet_name": "Budget",
        "destination_spreadsheet_id": "destination-456", "sheet_name": "Budget copy",
        "insert_sheet_index": 0,
    }, "Successfully duplicated 'Budget' to 'Budget copy' (ID: 42) in spreadsheet "
       "destination-456 for dedicated@example.test."),
    ("create_drive_file", {
        "file_name": "Report shortcut", "folder_id": "folder-123", "shortcut_target_id": "report-456",
    }, "Successfully created shortcut 'Report shortcut' (ID: shortcut-789)."),
    ("get_doc_content", {
        "document_id": "document-123", "tab_id": "t.1", "heading": "Results", "heading_level": 2,
        "preserve_context": True,
    }, "Showing only the section under heading 'Results', starting at document index 97.\nResults\nPassed."),
])
def test_v240_request_identity_survives_provider_context_and_saved_followup(tool, arguments, text):
    result = _receipt(tool, text, arguments)
    tool_name = PREFIX + tool
    assert result["ok"] is True
    assert result["data"]["request"] == arguments
    projected = workspace.project_workspace_data(result)
    assert projected["request"] == arguments
    assert projected["response_excerpt"] == text
    assert projected["context_truncated"] is False

    assembler = _assembler()
    preview, _, _, truncated = assembler.build_llm_result_context_preview(tool_name, result)
    assert json.loads(preview)["data"]["request"] == arguments
    assert not truncated
    saved = followup.extract_followup_data({tool_name: result["data"]})[tool_name]
    assert saved["request"] == arguments
    assert saved["response_excerpt"] == text


def test_calendar_acl_rule_ids_and_page_tokens_keep_their_distinct_labels():
    text = ("Found 2 sharing rules for calendar 'fixture@group.calendar.google.com':\n"
            "- owner: user dedicated@example.test (Rule ID: user:dedicated@example.test)\n"
            "- reader: user reader@example.test (Rule ID: user:reader@example.test)\n"
            "\nNext page token: next.page==")
    result = _receipt("manage_calendar", text, {
        "action": "list_sharing", "calendar_id": "fixture@group.calendar.google.com",
    })
    references = workspace.project_workspace_data(result)["references"]
    assert references == [
        {"label": "Rule ID", "id": "user:dedicated@example.test"},
        {"label": "Rule ID", "id": "user:reader@example.test"},
        {"label": "Next page token", "id": "next.page=="},
    ]
    assert result["data"]["links"] == []
    assert result["data"]["content_links_untrusted"] is True


def test_calendar_acl_recovery_does_not_reenable_a_profile_disabled_calendar_tool():
    registry = _registry({PREFIX + "manage_calendar": False})
    assert registry.get_tool(PREFIX + "manage_calendar") is None
    assert registry.get_tool(PREFIX + "list_calendars") is not None
    assert registry.get_tool(PREFIX + "create_calendar") is None


def test_section_selector_survives_truncation_without_claiming_a_complete_document():
    arguments = {"document_id": "document-123", "heading": "Results", "heading_level": 2,
                 "tab_id": "t.1", "preserve_context": False}
    text = ("Showing only the section under heading 'Results', starting at document index 97.\n"
            + "Section body.\n" * 1000)
    projected = workspace.project_workspace_data(_receipt("get_doc_content", text, arguments))
    assert projected["request"] == arguments
    assert projected["context_truncated"] is True
    assert projected["response_excerpt"] == text[:2200]
    assert "pagination" not in projected
    assert projected["external_content_trust"] == "untrusted"


def test_v240_discovery_guidance_preserves_public_sharing_and_section_boundaries():
    metadata = _config()["tool_metadata"]
    calendar = metadata["manage_calendar"]["description_prefix"]
    assert 'action="create"' in calendar and "secondary calendar" in calendar
    assert "rule_id" in calendar and 'action="list_sharing"' in calendar
    assert 'scope_type="default" makes access public' in calendar
    assert "send_notifications defaults true" in calendar
    assert "writerWithoutPrivateAccess" in calendar
    for name in ("get_doc_content", "get_doc_as_markdown"):
        text = metadata[name]["description_prefix"]
        assert "heading_level=1-6" in text and "tab_id" in text
        assert "next equal or shallower heading" in text
    assert "comments remain document-wide" in metadata["get_doc_as_markdown"]["description_prefix"]
    assert "offset n maps to n+s" in metadata["get_doc_content"]["description_prefix"]
    assert "preserve_context=true" in metadata["get_doc_content"]["description_prefix"]
    assert "destination_spreadsheet_id" in metadata["create_sheet"]["description_prefix"]
    shortcut = metadata["create_drive_file"]["description_prefix"]
    assert "shortcut_target_id" in shortcut and "does not copy" in shortcut
    assert "grant sharing access" in shortcut and "stash_ref" in shortcut


def test_calendar_acl_receipt_uses_existing_workspace_web_card_and_escapes_text():
    result = _receipt("manage_calendar", "Shared calendar '<fixture>':\n"
                      "- reader: user reader@example.test (Rule ID: user:reader@example.test)", {
        "action": "share", "calendar_id": "fixture-calendar", "scope_type": "user",
        "scope_value": "reader@example.test", "role": "reader", "send_notifications": False,
    })
    _run_renderer_assertions(f"""
const html = renderer.render({json.dumps({PREFIX + "manage_calendar": result})});
assert.ok(html.includes('Google Workspace'));
assert.ok(html.includes('&lt;fixture&gt;'));
assert.ok(!html.includes("'<fixture>'"));
assert.ok(html.includes('Rule ID: user:reader@example.test'));
""")
