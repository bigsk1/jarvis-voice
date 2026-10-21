"""Pinned 2.1.2 receipts describe outcomes, not merely admitted requests."""

import json
from unittest.mock import Mock

import google_workspace as workspace
import pytest
import requests
from mcp_client import MCPRemoteClient


def receipt(text, *, tool="batch_modify_gmail_message_labels", error=False, arguments=None):
    return workspace.normalize_workspace_result(tool, {"content": [{"text": text}], "isError": error}, arguments)


@pytest.mark.parametrize("text,expected", [
    ("Label changes for 2 message ID(s): Removed labels: INBOX\nApplied: 2/2", True),
    ("Label changes for 2 message ID(s): Removed labels: INBOX\nApplied: 1/2\nNo such message (1): bad", False),
    ("Label changes for 2 message ID(s): Removed labels: INBOX\nApplied: 0/2\nUnchanged (1): a\nCould not verify (1): b", False),
    ("Label changes for 2 thread ID(s): Added labels: STARRED\nApplied: 0/2\nNo such thread (1): a\nFailed (1): b (failed: denied)", False),
    ("Requested label changes for 2 message ID(s): Removed labels: INBOX\nNOT VERIFIED: Gmail's batchModify returns no per-message result", False),
    ("Label changes for 2 message ID(s): Removed labels: INBOX\nApplied: 3/2", False),
    ("Label changes for 2 message ID(s): Removed labels: INBOX\nApplied: 1/2", False),
    ("Label changes for 2 message ID(s): Removed labels: INBOX\nApplied: 2/3", False),
    ("Label changes for 2 message ID(s): Removed labels: INBOX\nApplied: unknown", False),
])
def test_batch_receipts_require_all_outcomes_confirmed(text, expected):
    result = receipt(text)
    assert result["ok"] is expected
    assert result["data"]["ok"] is expected
    assert result["data"]["response_text"] == text
    if not expected:
        assert "not fully confirmed" in result["speech"]
    assert project(result)["batch_outcomes"] == result["data"]["batch_outcomes"]


def project(result, **kwargs):
    return workspace.project_workspace_data(result, **kwargs)


def test_batch_mixed_receipt_partial_thread_and_unverified_message_never_claims_success():
    text = ("Requested label changes for 1 message ID(s): Removed labels: INBOX\nNOT VERIFIED: unknown\n\n"
            "Label changes for 1 thread ID(s): Removed labels: INBOX\nApplied: 1/1")
    assert receipt(text)["ok"] is False


def test_verified_message_and_thread_receipts_can_both_succeed():
    text = ("Label changes for 2 message ID(s): Removed labels: INBOX\nApplied: 2/2\n\n"
            "Label changes for 1 thread ID(s): Removed labels: INBOX\nApplied: 1/1")
    result = receipt(text, arguments={"message_ids": ["a", "b"], "thread_ids": ["t"]})
    assert result["ok"]
    assert set(result["data"]["batch_outcomes"]) == {"message", "thread"}


def test_upstream_omitted_outcome_ids_remain_explicitly_truncated():
    ids = ", ".join(f"bad{i}" for i in range(10)) + ", … (+90 more)"
    result = receipt(f"Label changes for 100 message ID(s): Removed labels: INBOX\nApplied: 0/100\nNo such message (100): {ids}")
    outcome = result["data"]["batch_outcomes"]["message"]["outcomes"]["No such message"]
    assert not result["ok"]
    assert outcome["count"] == 100
    assert outcome["details_truncated"]
    assert "bad10" not in outcome["details"]


def test_batch_raw_tool_error_overrides_successful_subreceipt():
    text = ("Label change for message_ids failed: forbidden\n\nThe thread_ids part was already processed:\n"
            "Label changes for 1 thread ID(s): Removed labels: INBOX\nApplied: 1/1")
    result = receipt(text, error=True)
    assert not result["ok"]
    assert result["error"] == text
    assert result["data"]["batch_outcomes"]["thread"]["applied"] == 1


def test_batch_receipt_must_cover_all_requested_groups_and_counts():
    text = "Label changes for 1 thread ID(s): Removed labels: INBOX\nApplied: 1/1"
    assert not receipt(text, arguments={"message_ids": ["m"], "thread_ids": ["t"]})["ok"]
    assert not receipt(text, arguments={"thread_ids": ["t", "t2"]})["ok"]
    assert receipt(text, arguments={"thread_ids": ["t"]})["ok"]


def test_ordinary_email_with_receipt_words_stays_untrusted_mail_content():
    text = "Subject: Failed\nApplied: 0/2\nNo such thread (2): hello, world"
    result = receipt(text, tool="get_gmail_message_content")
    assert result["ok"]
    assert "batch_outcomes" not in result["data"]
    assert result["data"]["external_content_trust"] == "untrusted"


def test_old_saved_partial_batch_receipt_is_downgraded_during_replay():
    text = "Label changes for 2 message ID(s): Removed labels: INBOX\nApplied: 1/2\nUnchanged (1): b"
    saved = {"tool": "batch_modify_gmail_message_labels", "ok": True, "response_text": text,
             "request": {"message_ids": ["a", "b"]}}
    replay = project(saved)
    assert not replay["ok"]
    assert replay["batch_outcomes"]["message"]["applied"] == 1
    assert replay["response_excerpt"] == text
    saved["ok"] = False
    saved["response_text"] = "Label changes for 2 message ID(s): Removed labels: INBOX\nApplied: 2/2"
    assert not project(saved)["ok"]


def test_partial_batch_is_sent_exactly_once_without_replaying_write(monkeypatch):
    client = MCPRemoteClient("google_workspace", "http://workspace:8000/mcp", "http", {}, proxy_policy="off")
    send = Mock(return_value={"content": [{"text": "Label changes for 1 message ID(s): Removed labels: INBOX\nApplied: 0/1\nNo such message (1): absent"}]})
    monkeypatch.setattr(client, "_send_request", send)
    result = client.call_tool("batch_modify_gmail_message_labels", {"message_ids": ["absent"], "remove_label_ids": ["INBOX"]})
    assert not result["ok"]
    send.assert_called_once()


def test_explicit_id_metadata_and_old_saved_requests_are_bounded_and_truthful():
    args = {"message_ids": [f"m{i}" for i in range(100)], "thread_ids": ["t"],
            "add_label_ids": ["STARRED"], "remove_label_ids": ["INBOX"], "tab_id": "tab1",
            "replace_existing": False, "copy_comments": True, "arbitrary_list": ["private"]}
    result = receipt("message", tool="get_doc_content", arguments=args)
    data = result["data"]
    assert data["request"]["message_ids"] == args["message_ids"][:20]
    assert data["request_list_counts"]["message_ids"] == 100
    assert data["request_lists_truncated"]["message_ids"] is True
    assert data["request_lists_truncated"]["thread_ids"] is False
    assert data["request"]["replace_existing"] is False
    assert data["request"]["copy_comments"] is True
    assert data["request"]["tab_id"] == "tab1"
    assert "arbitrary_list" not in data["request"]
    replay = project({"data": {"request": args}})
    assert replay["request_list_counts"]["message_ids"] == 100
    assert replay["request_lists_truncated"]["message_ids"] is True
    assert replay["context_truncated"]
    assert project(result)["request_list_counts"]["message_ids"] == 100
    for budget in (2, 200, 800, 4500):
        assert len(json.dumps(project(result, max_chars=budget), ensure_ascii=True)) <= budget


def test_id_lists_have_per_item_and_aggregate_bounds():
    args = {"message_ids": ["m" * 513, {"secret": "body"}, "valid"] + ["a" * 512] * 40,
            "thread_ids": ["b" * 512] * 40}
    data = receipt("ok", tool="list_gmail_labels", arguments=args)["data"]
    assert data["request"]["message_ids"][0] == "valid"
    lists = [data["request"][key] for key in args]
    assert sum(len(json.dumps(item, ensure_ascii=True)) + 2 for values in lists for item in values) <= 3000
    assert data["request_list_counts"]["message_ids"] == 43
    assert all(data["request_lists_truncated"].values())


@pytest.fixture
def download(monkeypatch):
    client = Mock(url="http://workspace:8000/mcp", headers={"Authorization": "Bearer test"})
    response = Mock(status_code=200, headers={"Content-Length": "4", "Content-Type": "application/pdf"})
    response.iter_content.return_value = iter([b"test"])
    client._http_request.return_value = response
    result = receipt("Download URL: http://workspace:8000/attachments/12345678-1234-1234-1234-123456789abc", tool="get_drive_file_download_url")
    open_space = Mock(side_effect=RuntimeError("Stash unavailable"))
    monkeypatch.setattr("stash_helper.open_space", open_space)
    return client, response, result, open_space


@pytest.mark.parametrize("failure", ["truncated", "extra", "invalid-length", "stream", "expired"])
def test_download_failure_is_not_claimed_as_google_download_success(download, failure):
    client, response, result, open_space = download
    if failure == "truncated":
        response.iter_content.return_value = iter([b"te"])
    elif failure == "extra":
        response.iter_content.return_value = iter([b"testing"])
    elif failure == "invalid-length":
        response.headers["Content-Length"] = "-1"
    elif failure == "expired":
        response.status_code = 404
    else:
        def chunks(**kwargs):
            yield b"te"
            raise requests.ConnectionError("stream lost")
        response.iter_content.side_effect = chunks
    actual = workspace.stash_workspace_download(client, result)
    assert not actual["ok"]
    assert actual["data"]["google_export_ok"]
    assert actual["data"]["google_ok"] is False
    assert actual["data"]["download_ok"] is False
    assert actual["data"]["download_error"]
    assert "artifacts" not in actual["data"]
    assert "download succeeded" not in actual["speech"]
    assert actual["data"]["response_text"].startswith("Download URL:")
    open_space.assert_not_called()
    response.close.assert_called_once()


def test_stash_save_failure_preserves_confirmed_complete_download(download):
    client, _, result, open_space = download
    actual = workspace.stash_workspace_download(client, result)
    assert not actual["ok"]
    assert actual["data"]["download_ok"]
    assert actual["data"]["google_ok"]
    assert actual["data"]["stash_error"] == "Stash unavailable"
    assert "download_error" not in actual["data"]
    assert "download succeeded, but Stash save failed" in actual["speech"]
    assert "artifacts" not in actual["data"]
    open_space.assert_called_once()


def test_content_length_checks_wire_length_only_for_identity_encoding(download):
    client, response, result, _ = download
    response.headers.update({"Content-Length": "2", "Content-Encoding": "gzip"})
    assert workspace.download_workspace_file(client, result)["body"] == b"test"
