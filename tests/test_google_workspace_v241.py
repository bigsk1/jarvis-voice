"""Range-copy identities and account-addressed Gmail links survive Jarvis handoffs."""

import json

import google_workspace as workspace
import pytest
from test_deepwiki_context import _assembler, followup
from test_google_workspace_v240 import PREFIX, _receipt
from test_structured_results_adapters import _run_renderer_assertions


@pytest.mark.parametrize("paste_type", ["PASTE_NORMAL", "PASTE_VALUES", "PASTE_FORMULA"])
def test_range_copy_receipt_survives_model_context_and_saved_followup(paste_type):
    arguments = {
        "spreadsheet_id": "sheet-123", "source_range": "Budget!A2:C2",
        "range_name": "'Budget copy'!A3", "paste_type": paste_type,
    }
    text = (f"Successfully copied 'Budget!A2:C2' to 'Budget copy!A3' ({paste_type}) "
            "in spreadsheet sheet-123 for dedicated@example.test.")
    result = _receipt("modify_sheet_values", text, arguments)
    tool_name = PREFIX + "modify_sheet_values"
    projected = workspace.project_workspace_data(result)
    assert projected["request"] == arguments
    preview, _, _, truncated = _assembler().build_llm_result_context_preview(tool_name, result)
    assert json.loads(preview)["data"]["request"] == arguments
    assert not truncated
    saved = followup.extract_followup_data({tool_name: result["data"]})[tool_name]
    assert saved["request"] == arguments
    assert saved["response_excerpt"] == text


def test_account_addressed_gmail_link_is_preserved_in_context_and_web_card():
    url = "https://mail.google.com/mail/u/dedicated%2Bfixture@example.test/#all/msg-123"
    result = _receipt("get_gmail_message_content", f"Message ID: msg-123\nWeb Link: {url}", {
        "message_id": "msg-123", "format": "metadata",
    })
    projected = workspace.project_workspace_data(result)
    assert url in projected["response_excerpt"]
    assert projected["content_links_untrusted"] is True
    _run_renderer_assertions(f"""
const html = renderer.render({json.dumps({PREFIX + "get_gmail_message_content": result})});
assert.ok(html.includes('Google Workspace'));
assert.ok(html.includes({json.dumps(url)}));
assert.ok(!html.includes('https://mail.google.com/mail/u/0/'));
""")
