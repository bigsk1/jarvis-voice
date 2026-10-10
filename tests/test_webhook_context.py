"""Payload guidance must survive the real model handoff and stored follow-ups."""

import importlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from zoneinfo import ZoneInfo

from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'orchestrator'))
from orchestrator_v2 import Orchestrator  # noqa: E402

from lib.webhook_context import project_webhook_data, project_webhook_runs  # noqa: E402

load_server_package('webhook_context_test_server', ROOT / 'jarvis-web/server')
followup = importlib.import_module('webhook_context_test_server.services.followup_extractor')


def contract(name='sample_notification'):
    return {
        'webhook': name, 'description': 'Create a notification with the requested timestamp.',
        'required_fields': ['action', 'notification'], 'optional_fields': ['callback'],
        'notes': 'Use the chosen destination; this is a separate service.',
        'payload_schema': {'type': 'object', 'required': ['action', 'notification'], 'properties': {
            'action': {'const': 'create'},
            'notification': {'type': 'object', 'required': ['title', 'scheduled_at'], 'properties': {
                'title': {'type': 'string'},
                'scheduled_at': {'type': 'string', 'pattern': r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'},
            }},
        }},
        'example': {'action': 'create', 'notification': {'title': 'Sample', 'scheduled_at': '2030-01-01T12:00:00Z'}},
    }


def failed_result():
    return {'ok': False, 'error': 'Missing required fields. No webhook was sent.', 'data': {
        **contract(), 'request_sent': False, 'missing_fields': ['action', 'notification'],
        'validation_path': 'notification.scheduled_at', 'retry_after_seconds': 1,
    }}


def orchestrator():
    instance = Orchestrator.__new__(Orchestrator)
    instance.timezone = ZoneInfo('UTC')
    return instance


def test_failed_call_keeps_complete_contract_in_next_turn():
    instance = orchestrator()
    result = failed_result()
    context = instance._build_turn_context('Send a sample notification', [{
        'tool': 'send_webhook', 'arguments': {'webhook': 'sample_notification', 'data': {}},
        'result': result,
    }])
    for field in ('payload_schema', 'required_fields', 'missing_fields', 'validation_path',
                  'example', 'request_sent', 'retry_after_seconds', 'optional_fields', 'notes'):
        assert f'"{field}"' in context
    preview = instance._build_llm_result_context_preview('send_webhook', result)[0]
    projected = json.loads(preview)['data']
    assert projected['payload_schema'] == contract()['payload_schema']
    assert projected['request_sent'] is False


def test_six_full_contracts_keep_last_destinations_and_nested_patterns():
    entries = [{**contract('service_'+str(i)), 'name': 'service_'+str(i)} for i in range(6)]
    result = {'ok': True, 'data': {'webhooks': entries, 'request_sent': False}}
    instance = orchestrator()
    text, _, _, truncated = instance._build_llm_result_context_preview('send_webhook', result)
    data = json.loads(text)['data']
    assert [item['name'] for item in data['webhooks']] == ['service_'+str(i) for i in range(6)]
    assert not truncated
    assert data['webhooks'][0]['payload_schema'] == entries[0]['payload_schema']


def test_stored_followup_keeps_contract_and_failed_trace_guidance():
    data = {'send_webhook': {'webhooks': [{'name': 'sample_notification', **contract()}]},
            '_tool_trace': [{'tool': 'send_webhook', 'ok': True},
                            {'tool': 'send_webhook', 'ok': False, 'error': failed_result()['error'],
                             'result_data': project_webhook_data(failed_result())}]}
    before = deepcopy(data)
    extracted = followup.extract_followup_data(data)['send_webhook']
    assert extracted['results'][0]['webhooks'][0]['description'] == contract()['description']
    failed = extracted['results'][1]
    assert failed['payload_schema'] == contract()['payload_schema']
    assert failed['required_fields'] == ['action', 'notification']
    assert failed['request_sent'] is False and failed['retry_after_seconds'] == 1
    assert data == before


def test_followup_keeps_failure_then_success_in_execution_order():
    delivered = {'webhook': 'sample_notification', 'request_sent': True, 'delivery_status': 'accepted', 'status_code': 200}
    result = followup.extract_followup_data({
        'send_webhook': delivered,
        '_tool_trace': [{'tool': 'send_webhook', 'ok': False, 'result_data': project_webhook_data(failed_result())},
                        {'tool': 'send_webhook', 'ok': True}],
    })['send_webhook']['results']
    assert result[0]['request_sent'] is False
    assert result[1]['request_sent'] is True
    assert result[1]['delivery_status'] == 'accepted'


def test_failed_trace_alone_survives_when_no_tool_succeeded():
    result = followup.extract_followup_data({'_tool_trace': [{
        'tool': 'send_webhook', 'ok': False, 'error': failed_result()['error'],
        'result_data': project_webhook_data(failed_result()),
    }]})
    assert result['send_webhook']['example'] == contract()['example']


def test_large_catalog_retains_names_and_advertises_single_contract_lookup():
    entries = [{'name': 'service_'+str(i), **contract(), 'notes': 'Guidance '*500} for i in range(6)]
    result = project_webhook_data({'webhooks': entries}, max_chars=6000)
    assert result.get('catalog_compacted')
    assert [entry['name'] for entry in result['webhooks']] == ['service_'+str(i) for i in range(6)]
    assert 'describe=true' in result['contract_lookup']
    assert len(json.dumps(result, separators=(',', ':'))) <= 6000
    assert project_webhook_data(result) == result


def test_provider_budget_uses_complete_json_or_explicit_contract_omission():
    instance = orchestrator()
    text, meta = instance._get_context_assembler().build_provider_tool_result_message(
        tool_name='send_webhook', arguments={'webhook': 'sample_notification', 'data': {}},
        result=failed_result(), max_chars=1400,
    )
    assert len(text) <= 1400
    data = json.loads(text.split('Result:\n', 1)[1])['result']
    data = data.get('data', data)
    if 'payload_schema' in data:
        assert data['payload_schema'] == contract()['payload_schema']
    else:
        assert data.get('contract_truncated')


def test_projection_does_not_copy_credentials_or_mutate_canonical_result():
    result = failed_result()
    result['data'].update(headers={'Authorization': 'Bearer SECRET_SENTINEL'}, api_token='SECRET_SENTINEL')
    result['data']['example']['token'] = 'SECRET_SENTINEL'
    before = deepcopy(result)
    projected = project_webhook_data(result)
    assert 'SECRET_SENTINEL' not in json.dumps(projected)
    assert result == before


def test_final_synthesis_and_stored_history_keep_complete_contracts():
    instance = orchestrator()
    failed = project_webhook_data(failed_result())
    accepted = {'webhook': 'sample_notification', 'request_sent': True, 'delivery_status': 'accepted'}
    saved = project_webhook_runs([failed, accepted])
    synthesis = instance._extract_useful_data({'send_webhook': saved})
    projected = json.loads(synthesis.split('=== send_webhook ===\n', 1)[1])
    assert projected['results'][0]['payload_schema'] == contract()['payload_schema']
    assert projected['results'][1]['request_sent'] is True
    history = instance._format_conversation_context('Use that contract', [{
        'role': 'assistant', 'content': 'Sample webhook attempt', 'tools_used': ['send_webhook'],
        'tool_results': {'send_webhook': saved},
    }])
    projected = json.loads(history.split('send_webhook data: ', 1)[1].splitlines()[0])
    assert projected['results'][0]['payload_schema'] == contract()['payload_schema']
    assert projected['results'][1]['delivery_status'] == 'accepted'


def test_history_retains_unknown_delivery_without_converting_it_to_false():
    result = {'webhook': 'sample_notification', 'request_sent': None,
              'delivery_status': 'unknown', 'retry_safe': False}
    context = orchestrator()._format_conversation_context('Did it send?', [{
        'role': 'assistant', 'content': 'Delivery unknown', 'tool_results': {'send_webhook': result},
    }])
    projected = json.loads(context.split('send_webhook data: ', 1)[1].splitlines()[0])
    assert 'request_sent' in projected and projected['request_sent'] is None
    assert projected['retry_safe'] is False
