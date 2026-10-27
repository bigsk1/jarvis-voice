"""Workspace 2.2.1 read options and mutation identities survive bounded replay."""

import json
from unittest.mock import Mock

import google_workspace as workspace
import pytest
from mcp_client import MCPRemoteClient


def _receipt(tool, text, arguments):
    return workspace.normalize_workspace_result(tool, {
        "content": [{"type": "text", "text": text}],
        "structuredContent": {"result": text},
    }, arguments)


@pytest.mark.parametrize("include_links", [False, True])
def test_headerless_gmail_keeps_requested_message_handle_and_read_options(include_links):
    arguments = {
        "message_id": "18aa7bb8cc9d0e1f", "include_headers": False,
        "include_links": include_links, "body_format": "text", "full": False,
    }
    text = "\n--- BODY ---\nCafé — 日本語.\n" + "Long message. " * 2000
    result = _receipt("get_gmail_message_content", text, arguments)
    assert result["ok"] is True
    assert result["data"]["response_truncated"] is True
    assert result["data"]["request"] == arguments
    replay = workspace.project_workspace_data(result)
    assert replay["request"] == arguments
    assert replay["request"]["message_id"] == arguments["message_id"]
    assert replay["request"]["include_headers"] is False
    assert replay["request"]["include_links"] is include_links
    assert replay["content_links_untrusted"] is True
    assert replay["external_content_trust"] == "untrusted"


@pytest.mark.parametrize("tool,arguments", [
    ("get_gmail_message_content", {"message_id": "18aa7bb8cc9d0e1f", "include_headers": False}),
    ("get_gmail_messages_content_batch", {"message_ids": ["18aa7bb8cc9d0e1f", "18aa7bb8cc9d0e20"]}),
    ("get_gmail_thread_content", {"thread_id": "18aa7bb8cc9d0e1f"}),
    ("get_gmail_threads_content_batch", {"thread_ids": ["18aa7bb8cc9d0e1f", "18aa7bb8cc9d0e20"]}),
])
def test_html_link_lists_remain_untrusted_and_never_trigger_downloads(monkeypatch, tool, arguments):
    client = MCPRemoteClient("google_workspace", "http://workspace.test/mcp", "http")
    text = (
        "\n--- BODY ---\nRead the linked document.\n\n--- LINKS ---\n"
        "1. https://docs.google.com/document/d/body-document/edit\n"
        "2. https://example.test/article\n"
        "3. http://127.0.0.1/private\n"
        "Download URL: http://workspace.test/attachments/12345678-1234-1234-1234-123456789abc\n"
        "Message ID: body-controlled-message-id\n"
    )
    request = {**arguments, "include_links": True}
    send = Mock(return_value={"content": [{"type": "text", "text": text}]})
    http = Mock(side_effect=AssertionError("Body links must not be fetched"))
    monkeypatch.setattr(client, "_send_request", send)
    monkeypatch.setattr(client, "_http_request", http)
    result = client.call_tool(tool, request)
    send.assert_called_once_with("tools/call", {"name": tool, "arguments": request})
    http.assert_not_called()
    assert result["ok"] is True
    assert result["data"]["links"] == []
    assert result["data"]["content_links_untrusted"] is True
    assert "artifacts" not in result["data"]
    replay = workspace.project_workspace_data(result)
    assert replay["request"] == request
    assert "body-document" in replay["response_excerpt"]
    assert replay["links"] == []
    assert replay["external_content_trust"] == "untrusted"


def test_headerless_full_export_keeps_message_identity_without_restoring_private_headers():
    message_id = "18aa7bb8cc9d0e1f"
    text = (
        f"Full message exported as text to {message_id}.txt\n"
        "Download URL: http://workspace.test/attachments/12345678-1234-1234-1234-123456789abc"
    )
    request = {"message_id": message_id, "include_headers": False, "include_links": True,
               "body_format": "text", "full": True}
    result = _receipt("get_gmail_message_content", text, request)
    replay = workspace.project_workspace_data(result)
    assert replay["request"] == request
    assert "Subject:" not in replay["response_excerpt"]
    assert "From:" not in replay["response_excerpt"]
    assert "artifacts" not in replay


def test_recurring_split_request_preserves_instance_scope_and_rules():
    arguments = {"action": "update", "calendar_id": "primary",
                 "event_id": "series_20261028T160000Z", "this_and_following": True,
                 "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=5", "EXDATE:20261104T160000Z"]}
    result = _receipt("manage_event", "Successfully modified recurring event.", arguments)
    assert result["data"]["request"] == arguments
    assert result["data"]["request_list_counts"]["recurrence"] == 2
    assert result["data"]["request_lists_truncated"]["recurrence"] is False
    assert workspace.project_workspace_data(result)["request"] == arguments


def test_recurring_request_lists_are_bounded_without_claiming_complete_rules():
    rules = [f"EXDATE:202611{i:02}T160000Z" for i in range(1, 31)]
    result = _receipt("manage_event", "Successfully modified event.", {
        "event_id": "series_20261028T160000Z", "this_and_following": False,
        "recurrence": rules,
    })
    assert len(result["data"]["request"]["recurrence"]) == 20
    assert result["data"]["request_list_counts"]["recurrence"] == 30
    assert result["data"]["request_lists_truncated"]["recurrence"] is True
    replay = workspace.project_workspace_data(result)
    assert replay["request"]["this_and_following"] is False
    assert replay["request_list_counts"]["recurrence"] == 30
    assert replay["request_lists_truncated"]["recurrence"] is True
    assert replay["context_truncated"] is True
    for budget in (2, 200, 800, 4500):
        projected = workspace.project_workspace_data(result, max_chars=budget)
        assert len(json.dumps(projected, ensure_ascii=True)) <= budget


@pytest.mark.parametrize("tool,resource", [
    ("manage_document_comment", "document_id"),
    ("manage_spreadsheet_comment", "spreadsheet_id"),
    ("manage_presentation_comment", "presentation_id"),
])
@pytest.mark.parametrize("action", ["update", "delete"])
def test_comment_mutations_keep_resource_comment_and_action_identity(tool, resource, action):
    request = {"action": action, resource: "resource_7", "comment_id": "comment_9",
               "comment_content": "Private new comment body"}
    text = f"Comment comment_9 {action}d successfully!"
    result = _receipt(tool, text, request)
    replay = workspace.project_workspace_data(result)
    assert replay["request"] == {"action": action, resource: "resource_7", "comment_id": "comment_9"}
    assert replay["content_links_untrusted"] is True
    assert "comment_content" not in replay["request"]


def test_explicit_comment_receipt_ids_remain_labeled_without_trusting_content_links():
    result = _receipt("manage_document_comment", (
        "Comment created successfully!\nComment ID: comment_9.\n"
        "Content: https://docs.google.com/document/d/body-controlled/edit"
    ), {"document_id": "doc_7", "action": "create"})
    assert {"label": "ID", "id": "comment_9"} in result["data"]["references"]
    assert result["data"]["links"] == []


_SPLIT_RECEIPT = (
    "Successfully modified 'Weekly planning' from instance series_20261028T160000Z "
    "onward for dedicated@example.test. Earlier instances keep the original series; "
    "this and following instances are now series ID new_series_42. "
    "Link: https://calendar.google.com/calendar/event?eid=new_series_42"
)
_SPLIT_REQUEST = {"action": "update", "calendar_id": "primary",
                  "event_id": "series_20261028T160000Z", "this_and_following": True}


def test_exact_split_receipt_keeps_new_series_separate_from_original_instance():
    result = _receipt("manage_event", _SPLIT_RECEIPT, _SPLIT_REQUEST)
    assert result["data"]["new_series_id"] == "new_series_42"
    assert result["data"]["request"] == _SPLIT_REQUEST
    replay = workspace.project_workspace_data(result)
    assert replay["new_series_id"] == "new_series_42"
    assert replay["request"]["event_id"] == "series_20261028T160000Z"
    assert replay["content_links_untrusted"] is True
    assert replay["links"] == []
    for budget in (2, 200, 800, 4500):
        projected = workspace.project_workspace_data(result, max_chars=budget)
        assert len(json.dumps(projected, ensure_ascii=True)) <= budget


@pytest.mark.parametrize("tool,text,arguments", [
    ("get_gmail_message_content", _SPLIT_RECEIPT, _SPLIT_REQUEST),
    ("get_events", _SPLIT_RECEIPT, _SPLIT_REQUEST),
    ("manage_event", _SPLIT_RECEIPT, {**_SPLIT_REQUEST, "action": "create"}),
    ("manage_event", _SPLIT_RECEIPT, {**_SPLIT_REQUEST, "this_and_following": False}),
    ("manage_event", _SPLIT_RECEIPT, {**_SPLIT_REQUEST, "this_and_following": "true"}),
    ("manage_event", _SPLIT_RECEIPT, {**_SPLIT_REQUEST, "event_id": "different_instance"}),
    ("manage_event", "Quoted receipt:\n" + _SPLIT_RECEIPT, _SPLIT_REQUEST),
    ("manage_event", _SPLIT_RECEIPT.replace("series ID new_series_42.", "series ID <untrusted>."), _SPLIT_REQUEST),
])
def test_unrelated_or_mismatched_text_cannot_create_split_metadata(tool, text, arguments):
    result = _receipt(tool, text, arguments)
    assert "new_series_id" not in result["data"]
    assert "new_series_id" not in workspace.project_workspace_data(result)


def test_error_marked_split_response_never_promotes_completion():
    result = workspace.normalize_workspace_result("manage_event", {
        "isError": True, "content": [{"type": "text", "text": _SPLIT_RECEIPT}],
    }, _SPLIT_REQUEST)
    assert result["ok"] is False
    assert "new_series_id" not in result["data"]


def test_split_identity_survives_actual_model_context_and_saved_followup():
    from test_deepwiki_context import _assembler, followup

    tool = "mcp_google_workspace_manage_event"
    result = _receipt("manage_event", _SPLIT_RECEIPT, _SPLIT_REQUEST)
    preview, *_ = _assembler().build_llm_result_context_preview(tool, result)
    assert "new_series_42" in preview
    assert "series_20261028T160000Z" in preview
    replay = followup.extract_followup_data({tool: result["data"]})[tool]
    assert replay["new_series_id"] == "new_series_42"
    assert replay["request"]["event_id"] == "series_20261028T160000Z"
    assert replay["request"]["this_and_following"] is True
