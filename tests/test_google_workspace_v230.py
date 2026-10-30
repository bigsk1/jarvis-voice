"""Workspace pagination follows text delivered to Jarvis, including bounded replay."""

import hashlib
import json

import google_workspace as workspace
import pytest


def _receipt(tool, text, arguments):
    return workspace.normalize_workspace_result(tool, {
        "content": [{"type": "text", "text": text}],
        "structuredContent": {"result": text},
    }, arguments)


def _gmail_page(body, *, offset=0, total=None):
    end = offset + len(body)
    total = total if total is not None else end
    return {
        "message_id": "18aa7bb8cc9d0e1f", "body_format": "text", "body": body,
        "page_offset": offset, "next_offset": end if end < total else None,
        "total_chars": total, "complete": end == total,
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "scope": "Decoded outer message body, excluding attachments and attached messages.",
        "headers": {"Subject": "Synthetic message"},
    }


def _gmail_request(**changes):
    return {"message_id": "18aa7bb8cc9d0e1f", "body_format": "text", "page_offset": 0,
            "page_size": 20000, "include_links": True, **changes}


def _drive_page(body, *, offset=0, total=None, file_id="drive_7", version="42"):
    end = offset + len(body)
    text = (f'File: "Synthetic document" (ID: {file_id}, Type: text/plain, Version: {version})\n'
            "Link: https://drive.google.com/file/d/drive_7/view\n\n--- CONTENT ---\n" + body)
    if total is not None and end < total:
        text += (f"\n\n[Truncated: showing characters {offset:,} to {end:,} of {total:,}; "
                 f"{total - end:,} more follow (default page size {len(body):,}, set by "
                 "WORKSPACE_MCP_MAX_CONTENT_CHARS). Call again with "
                 f"offset={end} to read on, or pass full_content=True for the whole file.]")
    return text


@pytest.mark.parametrize("kind", ["gmail", "drive"])
def test_large_provider_page_retains_metadata_and_continues_after_delivered_text(kind):
    body = "Café 日本語 Message ID: untouched.id.\n" * 1000
    if kind == "gmail":
        body = body[:20000]
        text = json.dumps(_gmail_page(body, total=50000), ensure_ascii=False)
        arguments = _gmail_request()
        tool = "get_gmail_message_content"
    else:
        text = _drive_page(body, total=100000)
        arguments = {"file_id": "drive_7", "offset": 0, "full_content": False}
        tool = "get_drive_file_content"
    result = _receipt(tool, text, arguments)
    assert result["ok"] is True
    assert result["data"]["request"] == arguments
    assert result["data"]["response_truncated"] is True
    page = result["data"]["pagination"]
    assert page["upstream_next_offset"] == len(body)
    assert page["page_complete"] is False
    assert page["kind"] == kind
    assert result["data"]["page_body"] == body[:16000]
    replay = workspace.project_workspace_data(result)
    delivered = len(replay["response_excerpt"])
    assert 0 < delivered <= 2200
    assert replay["response_excerpt"] == body[:delivered]
    assert replay["pagination"]["next_offset"] == delivered
    assert replay["pagination"]["delivered_end"] == delivered
    assert replay["pagination"]["content_delivered"] is False
    assert replay["pagination"]["upstream_next_offset"] == len(body)
    assert replay["context_truncated"] is True
    assert replay["external_content_trust"] == "untrusted"
    assert replay["links"] == []
    assert "page_body" not in replay
    if kind == "gmail":
        assert replay["pagination"]["body_sha256"] == _gmail_page(body)["body_sha256"]
    else:
        assert replay["pagination"]["file_version"] == "42"


@pytest.mark.parametrize("kind", ["gmail", "drive"])
def test_final_api_page_is_incomplete_for_model_until_every_character_is_delivered(kind):
    body = "x" * 4000
    if kind == "gmail":
        arguments = _gmail_request(page_offset=500)
        text = json.dumps(_gmail_page(body, offset=500))
        tool = "get_gmail_message_content"
    else:
        arguments = {"file_id": "drive_7", "offset": 500, "full_content": True}
        text = _drive_page(body, offset=500)
        tool = "get_drive_file_content"
    result = _receipt(tool, text, arguments)
    replay = workspace.project_workspace_data(result)
    assert replay["pagination"]["page_complete"] is True
    assert replay["pagination"]["content_delivered"] is False
    assert replay["pagination"]["next_offset"] == 2700
    assert replay["pagination"]["total_chars"] == 4500


@pytest.mark.parametrize("kind", ["gmail", "drive"])
def test_short_final_pages_finish_without_another_read(kind):
    body = "Message ID: preserve.trailing.period.\n" if kind == "gmail" else "Short file.\n"
    arguments = _gmail_request(page_offset=100) if kind == "gmail" else {"file_id": "drive_7", "offset": 100}
    text = json.dumps(_gmail_page(body, offset=100)) if kind == "gmail" else _drive_page(body, offset=100)
    tool = "get_gmail_message_content" if kind == "gmail" else "get_drive_file_content"
    replay = workspace.project_workspace_data(_receipt(tool, text, arguments))
    assert replay["response_excerpt"] == body
    assert replay["pagination"]["content_delivered"] is True
    assert replay["pagination"]["page_complete"] is True
    assert replay["pagination"]["next_offset"] is None
    assert replay["context_truncated"] is False


def test_gmail_paging_retains_checksum_and_read_options_in_replay():
    page = _gmail_page("continued body", offset=50, total=100)
    arguments = _gmail_request(page_offset=50, page_size=100, expected_sha256=page["body_sha256"])
    replay = workspace.project_workspace_data(_receipt("get_gmail_message_content", json.dumps(page), arguments))
    assert replay["request"] == arguments
    assert replay["pagination"]["offset"] == 50
    assert replay["pagination"]["next_offset"] == 64
    assert replay["pagination"]["body_sha256"] == arguments["expected_sha256"]


@pytest.mark.parametrize("change", [
    {"message_id": "wrong"}, {"page_offset": 1}, {"page_offset": True},
    {"next_offset": 9}, {"next_offset": True}, {"complete": True}, {"complete": "false"},
    {"total_chars": -1}, {"body_sha256": "bad"}, {"body_format": "raw"},
    {"body": ["wrong type"]}, {"unexpected": "not upstream metadata"},
    {"headers": "not headers"}, {"headers": {"Subject": ["not text"]}},
])
def test_malformed_or_mismatched_gmail_page_is_not_control_metadata(change):
    page = {**_gmail_page("body", total=100), **change}
    result = _receipt("get_gmail_message_content", json.dumps(page), _gmail_request())
    assert "pagination" not in result["data"]
    assert "pagination" not in workspace.project_workspace_data(result)


@pytest.mark.parametrize("arguments", [
    {"message_id": "18aa7bb8cc9d0e1f"}, _gmail_request(full=True),
    _gmail_request(format="metadata"), _gmail_request(body_format="raw"),
    _gmail_request(expected_sha256="0" * 64), _gmail_request(page_size=2),
])
def test_gmail_json_inside_legacy_or_incompatible_read_never_becomes_control_metadata(arguments):
    result = _receipt("get_gmail_message_content", json.dumps(_gmail_page("body", total=100)), arguments)
    assert "pagination" not in result["data"]


@pytest.mark.parametrize("arguments,text", [
    ({"file_id": "other"}, _drive_page("body", total=100)),
    ({"file_id": "drive_7", "offset": 1}, _drive_page("body", total=100)),
    ({"file_id": "drive_7", "full_content": True}, _drive_page("body", total=100)),
    ({"file_id": "drive_7"}, _drive_page("body", total=100).replace("offset=4 ", "offset=99 ")),
    ({"file_id": "drive_7"}, _drive_page("body", total=100).replace("96 more", "95 more")),
    ({"file_id": "drive_7"}, "Body content\n" + _drive_page("body", total=100)),
])
def test_spoofed_or_inconsistent_drive_footer_does_not_supply_control_metadata(arguments, text):
    result = _receipt("get_drive_file_content", text, arguments)
    assert "pagination" not in result["data"]


def test_body_footer_and_json_do_not_become_metadata_for_other_tools():
    for text in (_drive_page("body", total=100), json.dumps(_gmail_page("body", total=100))):
        result = _receipt("get_doc_content", text, {"document_id": "drive_7"})
        assert "pagination" not in result["data"]


def test_headerless_gmail_pages_do_not_restore_headers_and_accept_null_checksum():
    page = _gmail_page("body", total=100)
    page.pop("headers")
    arguments = _gmail_request(include_headers=False, expected_sha256=None)
    result = _receipt("get_gmail_message_content", json.dumps(page), arguments)
    assert result["data"]["pagination"]["next_offset"] == 4
    assert "headers" not in workspace.project_workspace_data(result)


@pytest.mark.parametrize("kind", ["gmail", "drive"])
def test_inline_image_text_is_sanitized_without_manufacturing_character_cursors(kind):
    body = "data:image/png;base64," + "A" * 5000
    text = json.dumps(_gmail_page(body)) if kind == "gmail" else _drive_page(body)
    arguments = _gmail_request() if kind == "gmail" else {"file_id": "drive_7"}
    tool = "get_gmail_message_content" if kind == "gmail" else "get_drive_file_content"
    result = _receipt(tool, text, arguments)
    assert "pagination" not in result["data"]
    assert "page_body" not in result["data"]
    assert "A" * 100 not in json.dumps(result)


def test_extreme_or_malformed_drive_footer_numbers_are_ordinary_untrusted_text():
    text = _drive_page("body", total=100)
    for bad in ("," * 20, "9" * 5000, str(2**64)):
        changed = text.replace("of 100;", f"of {bad};")
        result = _receipt("get_drive_file_content", changed, {"file_id": "drive_7"})
        assert "pagination" not in result["data"]


def test_provider_error_does_not_authorize_pagination_even_with_a_matching_envelope():
    result = workspace.normalize_workspace_result("get_gmail_message_content", {
        "isError": True, "content": [{"type": "text", "text": json.dumps(_gmail_page("body"))}],
    }, _gmail_request())
    assert result["ok"] is False
    assert "pagination" not in result["data"]


def test_drive_offset_past_end_is_not_invented_file_content():
    text = _drive_page("[offset=500 is past the end of the content (100 characters).]", offset=500)
    result = _receipt("get_drive_file_content", text, {"file_id": "drive_7", "offset": 500})
    assert "pagination" not in result["data"]


@pytest.mark.parametrize("kind", ["gmail", "drive"])
@pytest.mark.parametrize("budget", [2, 200, 800, 1800, 4500])
def test_small_projection_budget_never_advances_past_delivered_page_body(kind, budget):
    body = "界" * 6000
    text = json.dumps(_gmail_page(body, offset=50, total=50000)) if kind == "gmail" else _drive_page(body, offset=50, total=50000)
    arguments = _gmail_request(page_offset=50) if kind == "gmail" else {"file_id": "drive_7", "offset": 50}
    tool = "get_gmail_message_content" if kind == "gmail" else "get_drive_file_content"
    projected = workspace.project_workspace_data(_receipt(tool, text, arguments), max_chars=budget)
    assert len(json.dumps(projected, ensure_ascii=True)) <= budget
    if "pagination" in projected:
        assert projected["pagination"]["next_offset"] == 50 + len(projected.get("response_excerpt", ""))
        assert projected["pagination"]["content_delivered"] is False


def test_tsv_sheet_rows_keep_absolute_labels_and_escaped_cell_content():
    text = ("Successfully read 2 rows from range 'Sheet1!C41:E42' in spreadsheet sheet_7 for test@example.test:\n"
            "Each line: sheet row number, then tab-separated cells from column C. "
            "Tabs, line breaks and backslashes inside a cell are shown as \\t, \\n, \\r and \\\\.\n"
            "41\tFirst\tline\\ninside\n42\tSecond\tvalue\\tinside")
    result = _receipt("read_sheet_values", text, {"spreadsheet_id": "sheet_7", "range_name": "Sheet1!C41:E42"})
    replay = workspace.project_workspace_data(result)
    assert replay["response_excerpt"] == text
    assert "pagination" not in replay
    assert "41\tFirst" in replay["response_excerpt"]
