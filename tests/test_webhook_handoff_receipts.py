"""Artifact handoffs retain retrieval handles without copying task data or secrets."""

import importlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from server_package_utils import load_server_package

from lib.webhook_context import project_webhook_data, project_webhook_runs
from orchestrator.context_assembler import ContextAssembler


def receipt(handoff_id='handoff-first', *, delivery_status='accepted', artifacts=None):
    if artifacts is None:
        artifacts = [
            {'kind': 'stash', 'ref': 'stash://space_handoff/f_report', 'mode': 'cloud'},
            {'kind': 'canvas', 'page_id': 'page_handoff'},
        ]
    return {
        'ok': delivery_status == 'accepted',
        'data': {
            'webhook': 'remote_agent', 'handoff_id': handoff_id,
            'handoff_artifacts_count': len(artifacts), 'handoff_artifacts': artifacts,
            'request_sent': True if delivery_status == 'accepted' else None,
            'response_received': delivery_status == 'accepted',
            'delivery_status': delivery_status, 'retry_safe': False,
        },
    }


@pytest.fixture
def assembler():
    return ContextAssembler(
        timezone_obj=timezone.utc, auto_context_window=10, auto_context_minutes=60,
        safe_iso_to_local_datetime=lambda _: None,
        format_age_seconds=lambda _: 'unknown', format_gap_for_prompt=lambda _: 'unknown',
        conversation_has_text_summary_for_ref=lambda *_: False,
        stash_ref_from_result=lambda *_: '', get_memory_db_fn=lambda: None,
        now_utc_fn=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        parse_utc_timestamp_fn=lambda _: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def followup():
    root = Path(__file__).resolve().parents[1]
    alias = 'handoff_receipt_test_server'
    load_server_package(alias, root / 'jarvis-web/server')
    return importlib.import_module(f'{alias}.services.followup_extractor')


def test_receipt_keeps_exact_handles_and_withholds_payload_and_nested_secrets():
    result = receipt('ID-' + 'x' * 197)
    result['data'].update(
        context={'summary': 'PRIVATE_TASK_SENTINEL'}, payload={'api_key': 'SECRET_SENTINEL'},
        headers={'Authorization': 'Bearer SECRET_SENTINEL'},
        remote_task_completed=True,
    )
    result['data']['handoff_artifacts'][0].update(
        api_key='SECRET_SENTINEL', download_path='/private/SECRET_SENTINEL',
        local_path='/home/operator/SECRET_SENTINEL',
    )
    before = deepcopy(result)
    projected = project_webhook_data(result)
    assert projected['handoff_id'] == result['data']['handoff_id']
    assert projected['handoff_artifacts'] == receipt()['data']['handoff_artifacts']
    assert projected['handoff_artifacts_count'] == 2
    assert projected['delivery_status'] == 'accepted'
    assert 'remote_task_completed' not in projected
    serialized = json.dumps(projected)
    assert 'PRIVATE_TASK_SENTINEL' not in serialized and 'SECRET_SENTINEL' not in serialized
    assert result == before
    assert project_webhook_data(projected) == projected


@pytest.mark.parametrize('delivery_status', ['unknown', 'rejected'])
def test_failed_and_timeout_receipts_keep_correlation_without_inventing_delivery(delivery_status):
    result = receipt(delivery_status=delivery_status)
    if delivery_status == 'rejected':
        result['data']['request_sent'] = False
    projected = project_webhook_data(result)
    assert projected['ok'] is False
    assert projected['request_sent'] is result['data']['request_sent']
    assert projected['response_received'] is False
    assert projected['delivery_status'] == delivery_status
    assert projected['retry_safe'] is False
    assert projected['handoff_id'] == 'handoff-first'
    assert projected['handoff_artifacts_count'] == 2


def test_unicode_filename_and_legacy_canvas_id_survive_exactly():
    artifacts = [
        {'kind': 'stash', 'ref': 'stash://space_handoff/résumé final ? #.pdf', 'mode': 'local'},
        {'kind': 'canvas', 'page_id': 'legacy-document_123'},
    ]
    assert project_webhook_data(receipt(artifacts=artifacts))['handoff_artifacts'] == artifacts


def test_invalid_handles_and_unknown_kinds_are_omitted_with_truthful_count():
    artifacts = [
        {'kind': 'stash', 'ref': 'stash://space_handoff/../secret', 'mode': 'cloud'},
        {'kind': 'stash', 'ref': 'stash://space_handoff/..', 'mode': 'cloud'},
        {'kind': 'stash', 'ref': 'stash://space_handoff/f_report', 'mode': 'other'},
        {'kind': 'canvas', 'page_id': '../secret'},
        {'kind': 'url', 'url': 'https://example.invalid/SECRET_SENTINEL'},
        {'kind': 'canvas', 'page_id': 'page_valid'},
    ]
    projected = project_webhook_data(receipt(artifacts=artifacts))
    assert projected['handoff_artifacts'] == artifacts[-1:]
    assert projected['handoff_artifacts_count'] == 6
    assert projected['handoff_artifacts_omitted'] == 5
    assert projected['context_truncated'] is True
    assert 'SECRET_SENTINEL' not in json.dumps(projected)
    assert project_webhook_data(projected) == projected


def test_cap_limits_receipt_handles_and_records_omissions():
    artifacts = [{'kind': 'canvas', 'page_id': f'page_{index}'} for index in range(18)]
    projected = project_webhook_data(receipt(artifacts=artifacts))
    assert projected['handoff_artifacts'] == artifacts[:12]
    assert projected['handoff_artifacts_count'] == 18
    assert projected['handoff_artifacts_omitted'] == 6
    assert projected['context_truncated'] is True


def test_malformed_correlation_and_counts_do_not_copy_nested_values():
    result = receipt('x' * 201)
    result['data'].update(
        handoff_artifacts_count={'token': 'SECRET_SENTINEL'},
        handoff_artifacts_omitted=True,
    )
    projected = project_webhook_data(result)
    assert 'handoff_id' not in projected
    assert projected['handoff_artifacts_count'] == 2
    assert 'handoff_artifacts_omitted' not in projected
    assert 'SECRET_SENTINEL' not in json.dumps(projected)


def test_small_budget_removes_whole_artifacts_but_preserves_delivery_and_id():
    artifacts = [{'kind': 'canvas', 'page_id': 'page_' + str(index) + 'x' * 100} for index in range(12)]
    projected = project_webhook_data(receipt(artifacts=artifacts), max_chars=450)
    assert len(json.dumps(projected, ensure_ascii=False, separators=(',', ':'))) <= 450
    assert projected['handoff_id'] == 'handoff-first'
    assert projected['delivery_status'] == 'accepted'
    assert projected['handoff_artifacts_count'] == 12
    assert projected['handoff_artifacts_omitted'] == 12 - len(projected['handoff_artifacts'])
    assert projected['context_truncated'] is True
    assert project_webhook_data(projected, max_chars=450) == projected


@pytest.mark.parametrize('budget', [32, 64, 120, 220])
def test_tiny_budgets_stay_bounded_without_partial_ids_or_handles(budget):
    result = receipt('x' * 200)
    for projector, value in ((project_webhook_data, result), (project_webhook_runs, [result, result])):
        projected = projector(value, max_chars=budget)
        assert len(json.dumps(projected, ensure_ascii=False, separators=(',', ':'))) <= budget
        if 'handoff_id' in projected:
            assert projected['handoff_id'] == 'x' * 200
        assert (projected.get('context_truncated') or projected.get('results_omitted')
                or any(run.get('context_truncated') for run in projected.get('results', [])))


def test_ordered_runs_and_existing_omission_counts_survive_reprojection():
    runs = [receipt(f'handoff-{index}') for index in range(5)]
    projected = project_webhook_runs(runs)
    assert projected['runs_count'] == 5 and projected['results_omitted'] == 2
    assert [item['handoff_id'] for item in projected['results']] == [f'handoff-{index}' for index in range(2, 5)]
    assert project_webhook_runs(projected) == projected


def test_budget_compacted_aggregate_keeps_total_and_omission_counts_when_reprojected():
    projected = project_webhook_runs([receipt(f'handoff-{index}') for index in range(5)], max_chars=550)
    assert projected['runs_count'] == 5
    assert projected['results_omitted'] == 4
    assert projected['results'][0]['handoff_id'] == 'handoff-4'
    assert project_webhook_runs(projected, max_chars=550) == projected


def test_handoff_handles_reach_provider_turn_and_continuation(assembler):
    result = receipt(delivery_status='unknown')
    turn = assembler.build_turn_context('Double-check the report', [{
        'tool': 'send_webhook', 'arguments': {'webhook': 'remote_agent', 'data': {}},
        'result': result,
    }])
    assert 'handoff-first' in turn and 'stash://space_handoff/f_report' in turn
    assert '"request_sent":null' in turn and '"delivery_status":"unknown"' in turn
    message, _ = assembler.build_provider_tool_result_message(
        tool_name='send_webhook', arguments={'webhook': 'remote_agent', 'data': {}},
        result=result, max_chars=1800,
    )
    assert 'handoff-first' in message and 'stash://space_handoff/f_report' in message
    payload = json.loads(message.split('Result:\n', 1)[1])['result']
    assert payload.get('data', payload)['retry_safe'] is False


def test_web_saved_followups_keep_failed_then_accepted_handoff_order(followup):
    failed = receipt('handoff-failed', delivery_status='unknown')
    accepted = receipt('handoff-accepted')
    saved = followup.extract_followup_data({
        'send_webhook': accepted['data'],
        '_tool_trace': [
            {'tool': 'send_webhook', 'ok': False, 'result_data': failed['data']},
            {'tool': 'send_webhook', 'ok': True},
        ],
    })['send_webhook']
    assert [run['handoff_id'] for run in saved['results']] == ['handoff-failed', 'handoff-accepted']
    assert saved['results'][0]['request_sent'] is None
    assert saved['results'][1]['request_sent'] is True
    assert saved['results'][1]['handoff_artifacts'] == accepted['data']['handoff_artifacts']
    assert project_webhook_runs(saved) == saved


def test_contract_exposes_only_supported_operator_artifact_opt_in():
    projected = project_webhook_data({'artifact_handoff': 'jarvis_v1', 'payload_schema': {'type': 'object'}})
    assert projected['artifact_handoff'] == 'jarvis_v1'
    assert project_webhook_data({'artifact_handoff': {'token': 'SECRET_SENTINEL'}}) == {}
    assert project_webhook_data({'artifact_handoff': 'unsupported'}) == {}
