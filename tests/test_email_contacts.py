"""Native and MCP email routes share local recipient lookup, without live sends."""
# ruff: noqa: E402 - match the app's lib import bootstrap

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import email_contacts
from google_workspace import resolve_workspace_recipients
from mcp_client import MCPRemoteClient


@pytest.fixture
def contacts_file(tmp_path, monkeypatch):
    path = tmp_path / "contacts.json"
    path.write_text(json.dumps({"contacts": {
        "boss": {"name": "The Boss", "email": "boss@example.test"},
        "recipient_one": {"name": "Sample Recipient One", "email": "recipient.one@example.test"},
        "recipient_two": {"name": "Sample Recipient Two", "email": "recipient.two@example.test"},
    }}))
    monkeypatch.setattr(email_contacts, "CONTACTS_FILE", path)
    return path


@pytest.mark.parametrize("name,expected", [
    ("Boss", "boss@example.test"), ("  bOsS  ", "boss@example.test"),
    ("THE BOSS", "boss@example.test"), ("Sample Recipient One", "recipient.one@example.test"),
    ("Sample Recipient Two", "recipient.two@example.test"), ("direct@example.test", "direct@example.test"),
])
def test_shared_lookup_by_key_display_name_or_direct_address(contacts_file, name, expected):
    assert email_contacts.resolve_email(name, email_contacts.load_contacts())[0] == expected


@pytest.mark.parametrize("value,expected", [
    ("Boss, Sample Recipient One", "boss@example.test, recipient.one@example.test"),
    ("Boss, person@example.test", "boss@example.test, person@example.test"),
    ('Boss, "Smith, Pat" <pat@example.test>', 'boss@example.test, "Smith, Pat" <pat@example.test>'),
    ('"Smith, Pat" <pat@example.test>', '"Smith, Pat" <pat@example.test>'),
    ("Pat (work, home) <pat@example.test>", "Pat (work, home) <pat@example.test>"),
    ("Boss, Pat (work, home) <pat@example.test>", "boss@example.test, Pat (work, home) <pat@example.test>"),
])
def test_recipient_lists_preserve_names_and_explicit_addresses(contacts_file, value, expected):
    assert email_contacts.resolve_email_recipients(value, email_contacts.load_contacts()) == expected


@pytest.mark.parametrize("contents", ["{", "[]", "null", '{"contacts": []}', '{}'])
def test_invalid_contacts_file_does_not_resolve_names_or_block_direct_addresses(
    contacts_file, contents,
):
    contacts_file.write_text(contents)
    assert email_contacts.load_contacts() == {}
    assert email_contacts.resolve_email("Boss", email_contacts.load_contacts())[0] is None
    assert email_contacts.resolve_email_recipients("direct@example.test", {}) == "direct@example.test"


def test_missing_file_and_invalid_contact_entries_do_not_resolve(contacts_file):
    contacts_file.unlink()
    assert email_contacts.load_contacts() == {}
    for contact in (None, [], {}, {"email": None}, {"email": ""}, {"email": "not-an-email"}):
        assert email_contacts.resolve_email("Boss", {"boss": contact})[0] is None


@pytest.mark.parametrize("tool", ["send_gmail_message", "draft_gmail_message"])
def test_gmail_protocol_and_receipt_use_selected_addresses_only(contacts_file, monkeypatch, tool):
    client = MCPRemoteClient("google_workspace", "http://localhost/mcp", "http")
    client.tool_defaults = {"user_google_email": "dedicated@example.test"}
    protocol = Mock(return_value={"content": [{"type": "text", "text": "Message ID: message-123"}]})
    monkeypatch.setattr(client, "_send_request", protocol)
    arguments = {
        "to": "Boss", "cc": "Sample Recipient One, direct@example.test", "bcc": "Sample Recipient Two",
        "from_email": "alias@example.test", "subject": "Test", "body": "Hello",
        "user_google_email": "wrong@example.test",
    }
    original = deepcopy(arguments)
    result = client.call_tool(tool, arguments)
    assert result["ok"]
    assert protocol.call_args.args == ("tools/call", {"name": tool, "arguments": {
        **arguments, "to": "boss@example.test", "cc": "recipient.one@example.test, direct@example.test",
        "bcc": "recipient.two@example.test", "user_google_email": "dedicated@example.test",
    }})
    assert result["data"]["request"]["to"] == "boss@example.test"
    assert arguments == original


@pytest.mark.parametrize("tool", ["send_gmail_message", "draft_gmail_message"])
@pytest.mark.parametrize("field", ["to", "cc", "bcc"])
@pytest.mark.parametrize("recipient", ["Unknown", "Sample Recipient Three", "Boss, Unknown", "Boss,", ["Boss"]])
def test_unresolved_or_invalid_recipient_prevents_entire_google_call(
    contacts_file, monkeypatch, tool, field, recipient,
):
    client = MCPRemoteClient("google_workspace", "http://localhost/mcp", "http")
    protocol = Mock()
    monkeypatch.setattr(client, "_send_request", protocol)
    result = client.call_tool(tool, {"to": "Boss", "subject": "Test", "body": "Hello", field: recipient})
    assert not result["ok"]
    assert "recipient" in result["error"] or "Contact" in result["error"]
    protocol.assert_not_called()


def test_optional_reply_recipients_and_non_gmail_fields_are_not_resolved(contacts_file):
    reply = {"to": None, "cc": None, "bcc": "", "reply_all": True}
    assert resolve_workspace_recipients("send_gmail_message", reply) == reply
    filter_args = {"criteria": {"from": "Boss"}, "filter_action": {"forward": "Boss"}}
    assert resolve_workspace_recipients("manage_gmail_filter", filter_args) == filter_args
    assert resolve_workspace_recipients("manage_drive_access", {"share_with": "Boss"}) == {"share_with": "Boss"}


def test_other_mcp_servers_do_not_use_local_gmail_contacts(contacts_file, monkeypatch):
    client = MCPRemoteClient("other_server", "http://localhost/mcp", "http")
    protocol = Mock(return_value={"content": [{"type": "text", "text": "Done"}]})
    monkeypatch.setattr(client, "_send_request", protocol)
    assert client.call_tool("send_gmail_message", {"to": "Boss"})["ok"]
    assert protocol.call_args.args[1]["arguments"] == {"to": "Boss"}


def test_contact_changes_are_read_on_next_call(contacts_file):
    assert resolve_workspace_recipients("send_gmail_message", {"to": "Boss"})["to"] == "boss@example.test"
    contacts_file.write_text(json.dumps({"contacts": {"boss": {"email": "changed@example.test"}}}))
    assert resolve_workspace_recipients("draft_gmail_message", {"to": "Boss"})["to"] == "changed@example.test"


def test_native_send_email_uses_same_lookup_and_webhook_path(contacts_file, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("native_send_email", ROOT / "skills/send_email.py")
    assert spec and spec.loader
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    assert native.load_contacts is email_contacts.load_contacts
    assert native.resolve_email is email_contacts.resolve_email
    monkeypatch.setattr(native, "load_config", lambda: None)
    monkeypatch.setattr(native, "load_webhook_registry", lambda: {"send_email": {"url": "https://webhook.example.test"}})
    monkeypatch.setattr(native, "check_rate_limit", lambda _email: True)
    monkeypatch.setattr(native, "rate_limit_remaining", lambda _email: 0)
    webhook = Mock(return_value={"ok": True, "status_code": 200})
    monkeypatch.setattr(native, "send_email_webhook", webhook)
    monkeypatch.setattr(sys, "argv", ["send_email.py", json.dumps({"to": "The Boss", "subject": "Test", "body": "Hello"})])
    native.main()
    assert webhook.call_args.args == ("boss@example.test", "Test", "Hello", "https://webhook.example.test")
    assert json.loads(capsys.readouterr().out)["data"]["to_name"] == "The Boss"


@pytest.fixture
def inbound_policy_file(contacts_file):
    data = json.loads(contacts_file.read_text())
    data["jarvis_email"] = {
        "enabled": True, "mode": "cloud", "approved_senders": ["boss"],
        "allowed_tools": ["get_time", "crawl_url"],
    }
    return contacts_file, data


@pytest.mark.parametrize("limited,additions", [
    ("printer", {"printer"}),
    (["printer", "analyze_image", "printer"], {"printer", "analyze_image"}),
    ([], set()),
    (["get_time", "tool_search"], set()),
])
def test_contact_limit_uses_baseline_plus_exact_additions(inbound_policy_file, limited, additions):
    path, data = inbound_policy_file
    data["contacts"]["boss"]["allowed_tools_limited"] = limited
    path.write_text(json.dumps(data))
    policy = email_contacts.load_email_channel("cloud")
    assert policy["allowed_tools"] == ["crawl_url", "get_time", "tool_search"]
    assert set(policy["sender_allowed_tools"]["boss@example.test"]) == (
        set(email_contacts.DEFAULT_EMAIL_TOOLS) | additions | {"tool_search"}
    )
    assert "crawl_url" not in policy["sender_allowed_tools"]["boss@example.test"]


@pytest.mark.parametrize("approved", ["boss", "The Boss", "BOSS@EXAMPLE.TEST"])
def test_contact_limit_matches_canonical_sender_even_for_bare_approval(inbound_policy_file, approved):
    path, data = inbound_policy_file
    data["contacts"]["boss"]["email"] = "Boss@Example.Test"
    data["contacts"]["boss"]["allowed_tools_limited"] = "printer"
    data["jarvis_email"]["approved_senders"] = [approved]
    path.write_text(json.dumps(data))
    policy = email_contacts.load_email_channel("cloud")
    assert policy["senders"] == ["boss@example.test"]
    assert set(policy["sender_allowed_tools"]) == {"boss@example.test"}
    assert "printer" in policy["sender_allowed_tools"]["boss@example.test"]


def test_absent_limit_keeps_global_policy_for_existing_family_contacts(inbound_policy_file):
    path, data = inbound_policy_file
    data["jarvis_email"]["approved_senders"] = ["boss", "Sample Recipient One"]
    data["contacts"]["boss"]["allowed_tools_limited"] = []
    path.write_text(json.dumps(data))
    policy = email_contacts.load_email_channel("cloud")
    assert policy["allowed_tools"] == ["crawl_url", "get_time", "tool_search"]
    assert "recipient.one@example.test" not in policy["sender_allowed_tools"]
    assert "boss@example.test" in policy["sender_allowed_tools"]


def test_limit_field_does_not_approve_contact_or_change_outgoing_resolution(inbound_policy_file):
    path, data = inbound_policy_file
    data["contacts"]["recipient_one"]["allowed_tools_limited"] = "printer"
    path.write_text(json.dumps(data))
    policy = email_contacts.load_email_channel("cloud")
    assert policy["senders"] == ["boss@example.test"]
    assert "recipient.one@example.test" not in policy["sender_allowed_tools"]
    assert email_contacts.resolve_email("Sample Recipient One", email_contacts.load_contacts())[0] == "recipient.one@example.test"


@pytest.mark.parametrize("limited", [
    None, "", " \t", True, 1, {}, {"tools": ["printer"]}, [["printer"]],
    [None], [True], [""], ["printer", 5], "printer ", [" printer"], "send_email ",
])
def test_invalid_contact_limit_fails_closed_even_for_unapproved_contact(inbound_policy_file, limited):
    path, data = inbound_policy_file
    data["contacts"]["recipient_one"]["allowed_tools_limited"] = limited
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        email_contacts.load_email_channel("cloud")


@pytest.mark.parametrize("tool", [
    "email_inbox", "workflow", "send_email", "mcp_google_workspace_send_gmail_message",
    "mcp_google_workspace_draft_gmail_message",
])
@pytest.mark.parametrize("as_list", [False, True])
def test_dispatcher_tools_cannot_be_granted_by_contact_limit(inbound_policy_file, tool, as_list):
    path, data = inbound_policy_file
    data["contacts"]["boss"]["allowed_tools_limited"] = [tool] if as_list else tool
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        email_contacts.load_email_channel("cloud")


def test_conflicting_same_email_limits_fail_closed(inbound_policy_file):
    path, data = inbound_policy_file
    data["contacts"]["boss"]["allowed_tools_limited"] = "printer"
    data["contacts"]["boss_alias"] = {"email": "BOSS@EXAMPLE.TEST", "allowed_tools_limited": ["analyze_image"]}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        email_contacts.load_email_channel("cloud")


@pytest.mark.parametrize("alias_limit", [None, ["printer", "get_time", "printer"]])
def test_equivalent_or_unspecified_same_email_alias_does_not_remove_limit(inbound_policy_file, alias_limit):
    path, data = inbound_policy_file
    data["contacts"]["boss"]["allowed_tools_limited"] = "printer"
    alias = {"email": "BOSS@EXAMPLE.TEST"}
    if alias_limit is not None:
        alias["allowed_tools_limited"] = alias_limit
    data["contacts"]["boss_alias"] = alias
    path.write_text(json.dumps(data))
    policy = email_contacts.load_email_channel("cloud")
    assert set(policy["sender_allowed_tools"]["boss@example.test"]) == set(email_contacts.DEFAULT_EMAIL_TOOLS) | {"printer", "tool_search"}


def test_same_email_aliases_compare_effective_baseline_not_just_extras(inbound_policy_file):
    path, data = inbound_policy_file
    data["contacts"]["boss"]["allowed_tools_limited"] = []
    data["contacts"]["boss_alias"] = {"email": "BOSS@EXAMPLE.TEST", "allowed_tools_limited": "get_time"}
    path.write_text(json.dumps(data))
    policy = email_contacts.load_email_channel("cloud")
    assert set(policy["sender_allowed_tools"]["boss@example.test"]) == set(email_contacts.DEFAULT_EMAIL_TOOLS) | {"tool_search"}


def test_misspelled_contact_limit_does_not_silently_use_global_tools(inbound_policy_file):
    path, data = inbound_policy_file
    data["contacts"]["boss"]["allowed_tools_limted"] = "printer"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="allowed_tools_limited"):
        email_contacts.load_email_channel("cloud")
