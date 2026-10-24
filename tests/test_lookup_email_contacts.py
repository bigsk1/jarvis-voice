"""Local contact inspection must report its source without sending or guessing."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lookup_email_contacts_tool', ROOT / 'skills/lookup_email_contacts.py')
assert spec is not None and spec.loader is not None
tool = importlib.util.module_from_spec(spec)
original_path = sys.path.copy()
try:
    spec.loader.exec_module(tool)
finally:
    sys.path[:] = original_path


@pytest.fixture
def contacts_file(tmp_path, monkeypatch):
    path = tmp_path / 'contacts.json'
    path.write_text(json.dumps({
        'contacts': {
            'bot': {'name': 'Example Bot', 'email': 'bot@example.test', 'notes': 'PRIVATE_NOTE', 'phone': 'PRIVATE_PHONE'},
            'boss': {'name': 'Operator', 'email': 'operator@example.test'},
            'phone-only': {'name': 'Phone Person', 'phone': 'PRIVATE_PHONE'},
        },
        'jarvis_email': {'approved_senders': ['PRIVATE_SENDER'], 'allowed_tools': ['PRIVATE_POLICY']},
        '_default_from': {'email': 'PRIVATE_FROM'},
    }))
    monkeypatch.setattr(tool.contact_store, 'CONTACTS_FILE', path)
    return path


@pytest.mark.parametrize('query', ['BOT', 'example bot', 'BOT@EXAMPLE.TEST'])
def test_key_display_name_and_email_filters_are_case_insensitive(contacts_file, query):
    result = tool.lookup_contacts({'query': query})
    assert result['ok']
    assert result['data'] == {
        'status': 'found', 'source': 'jarvis_local_contacts', 'contacts_file': 'config/contacts.json',
        'lookup_complete': True, 'contacts': [{'key': 'bot', 'name': 'Example Bot', 'email': 'bot@example.test'}],
        'count': 1, 'total_matches': 1, 'truncated': False,
    }
    assert 'Google Contacts and memory were not checked' in result['speech']


def test_list_omits_non_email_entries_and_private_policy_fields(contacts_file):
    result = tool.lookup_contacts({})
    assert result['data']['count'] == 2
    assert [row['key'] for row in result['data']['contacts']] == ['boss', 'bot']
    assert 'PRIVATE_' not in json.dumps(result)
    assert all(set(row) == {'key', 'name', 'email'} for row in result['data']['contacts'])


def test_alias_lookup_uses_shared_outbound_resolver(contacts_file, monkeypatch):
    calls = []
    real_resolver = tool.contact_store.resolve_email

    def resolve(value, contacts):
        calls.append(value)
        return real_resolver(value, contacts)

    monkeypatch.setattr(tool.contact_store, 'resolve_email', resolve)
    result = tool.lookup_contacts({'query': 'bot'})
    assert result['data']['contacts'][0]['email'] == 'bot@example.test'
    assert set(calls) == {'bot', 'boss'}


def test_phone_only_and_unknown_raw_addresses_mean_no_local_match(contacts_file):
    for query in ('phone-only', 'new-recipient@example.test'):
        result = tool.lookup_contacts({'query': query})
        assert result['ok'] and result['data']['status'] == 'not_found'
        assert result['data']['lookup_complete'] is True
        assert result['data']['total_matches'] == 0


def test_missing_file_is_not_configured_without_claiming_completed_lookup(contacts_file):
    contacts_file.unlink()
    result = tool.lookup_contacts({})
    assert result['ok'] and result['data']['status'] == 'not_configured'
    assert result['data']['lookup_complete'] is False
    assert result['data']['contacts'] == []


@pytest.mark.parametrize('contents', ['{', '[]', '{}', '{"contacts": []}', '{"contacts": null}'])
def test_invalid_source_cannot_be_reported_as_a_missing_contact(contacts_file, contents):
    contacts_file.write_text(contents)
    result = tool.lookup_contacts({'query': 'bot'})
    assert result['ok'] is False
    assert result['data']['status'] == 'unavailable'
    assert result['data']['lookup_complete'] is False


def test_unreadable_source_returns_no_error_payload_or_secret_paths(contacts_file, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError('/private/SECRET_PATH')

    monkeypatch.setattr(Path, 'read_text', denied)
    result = tool.lookup_contacts({})
    assert result['data']['status'] == 'unavailable' and not result['ok']
    assert not result['data']['lookup_complete']
    assert 'SECRET_PATH' not in json.dumps(result)


def test_valid_empty_map_is_a_complete_local_lookup(contacts_file):
    contacts_file.write_text('{"contacts": {}}')
    result = tool.lookup_contacts({})
    assert result['ok'] and result['data']['lookup_complete']
    assert result['data']['status'] == 'not_found'


def test_limit_is_explicit_without_losing_total_match_count(contacts_file):
    result = tool.lookup_contacts({'limit': 1})
    assert result['data']['count'] == 1 and result['data']['total_matches'] == 2
    assert result['data']['truncated'] and result['data']['lookup_complete']


@pytest.mark.parametrize('arguments', [[], None, {'query': None}, {'limit': True}, {'limit': 0},
                                      {'limit': 51}, {'limit': '20'}, {'limit': 1.5}, {'action': 'send'},
                                      {'contacts_file': '/private/config.json'}])
def test_invalid_invocations_fail_before_reading_source(contacts_file, monkeypatch, arguments):
    monkeypatch.setattr(Path, 'read_text', lambda *args, **kwargs: pytest.fail('Source read before validation'))
    result = tool.lookup_contacts(arguments)
    assert result['ok'] is False and result['data']['lookup_complete'] is False
    assert result['data']['status'] == 'unavailable'


def test_address_shaped_keys_do_not_override_the_configured_email(contacts_file):
    contacts_file.write_text(json.dumps({'contacts': {
        'alias@example.test': {'name': 'Saved Alias', 'email': 'actual@example.test'},
        'fallback': {'email': 'fallback@example.test', 'name': None},
        'broken': {'email': 42},
    }}))
    result = tool.lookup_contacts({})
    assert result['data']['contacts'] == [
        {'key': 'alias@example.test', 'name': 'Saved Alias', 'email': 'actual@example.test'},
        {'key': 'fallback', 'name': 'fallback', 'email': 'fallback@example.test'},
    ]


def test_main_emits_normal_tool_envelope_and_rejects_invalid_json(contacts_file, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['lookup_email_contacts.py', '{"query":"bot"}'])
    assert tool.main() == 0
    assert json.loads(capsys.readouterr().out)['data']['source'] == 'jarvis_local_contacts'
    monkeypatch.setattr(sys, 'argv', ['lookup_email_contacts.py', '{'])
    assert tool.main() == 1
    assert json.loads(capsys.readouterr().out)['data']['lookup_complete'] is False


def test_manifest_exposes_only_read_only_restricted_inspection():
    manifest = json.loads((ROOT / 'skills/email_contacts.tool.json').read_text())
    assert manifest['name'] == 'email_contacts'
    assert manifest['script'] == 'lookup_email_contacts.py'
    assert manifest['child_environment'] == {'mode': 'restricted', 'allow': []}
    assert manifest['proxy_policy'] == 'off'
    assert set(manifest['parameters']['properties']) == {'query', 'limit'}
    assert manifest['parameters']['additionalProperties'] is False
    assert manifest['permissions'] == {
        'dangerous': False, 'bash': False, 'network': False, 'filesystem': True, 'auto_approve': True,
    }
