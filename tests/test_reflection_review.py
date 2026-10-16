"""Reflection review uses isolated SQLite data and mocked reflection calls only."""

import asyncio
import importlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))

from intelligence import IntelligenceLayer  # noqa: E402
from reflection_review import (  # noqa: E402
    _BACKGROUND_PREFIX,
    ReflectionBusy,
    processing_lock,
    project_review,
)


@pytest.fixture
def layers(tmp_path):
    with patch('intelligence.get_intel_logger'):
        values = {mode: IntelligenceLayer(str(tmp_path / f'{mode}.db'), load_runtime_config=False)
                  for mode in ('cloud', 'local')}
        try:
            yield values
        finally:
            for layer in values.values():
                layer.conn.close()


def add_item(layer, query='Which one?', *, priority=0.5, queued_at='2026-10-15 12:00:00',
             context=None, processed=0):
    raw = json.dumps({'context': context or {}})
    cursor = layer.conn.execute(
        'INSERT INTO experiences(query, tools_used, outcome_success, raw_data) VALUES (?, ?, ?, ?)',
        (query, '["search_memory"]', 1, raw))
    experience_id = cursor.lastrowid
    cursor = layer.conn.execute(
        'INSERT INTO reflection_queue(experience_id, priority, queued_at, processed) VALUES (?, ?, ?, ?)',
        (experience_id, priority, queued_at, processed))
    layer.conn.commit()
    return cursor.lastrowid, experience_id


@pytest.fixture
def dashboard(monkeypatch, layers):
    # A distinct namespace prevents importing the production app or touching its databases.
    package_name = '_reflection_dashboard_test'
    spec = importlib.util.spec_from_file_location(
        package_name, ROOT / 'jarvis-intelligence/server/__init__.py',
        submodule_search_locations=[str(ROOT / 'jarvis-intelligence/server')])
    package = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, package_name, package)
    # The package initializer need not execute: only the services/routes under test are loaded.
    service_module = importlib.import_module(f'{package_name}.services.intelligence_service')
    stats = importlib.import_module(f'{package_name}.routes.stats')
    maintenance = importlib.import_module(f'{package_name}.routes.maintenance')
    experiences = importlib.import_module(f'{package_name}.routes.experiences')
    services = {}
    for mode, layer in layers.items():
        service = service_module.IntelligenceService.__new__(service_module.IntelligenceService)
        service.db_path = Path(layer.db_path)
        service.mode = mode
        services[mode] = service
    monkeypatch.setattr(stats, 'get_service', lambda: services[stats.request.args.get('mode', 'cloud')])
    monkeypatch.setattr(experiences, 'get_service', lambda: services[experiences.request.args.get('mode', 'cloud')])
    monkeypatch.setattr('intelligence.get_intelligence_layer', lambda mode: layers[mode])
    # Real ContextVar scoping, with empty config snapshots and no production configuration reads.
    monkeypatch.setattr('config_loader._load_mode_config', lambda _mode: {})
    app = Flask(__name__)
    app.register_blueprint(stats.stats_bp)
    app.register_blueprint(maintenance.maintenance_bp)
    app.register_blueprint(experiences.experiences_bp)
    return app.test_client(), services


@pytest.fixture
def main_api(monkeypatch, layers):
    routes = importlib.import_module('api.routes.intelligence')
    app = FastAPI()
    app.include_router(routes.router)
    monkeypatch.setattr('intelligence.get_intelligence_layer', lambda: layers['cloud'])

    async def call(method, path):
        # ASGITransport exercises real HTTP responses without a TestClient portal/thread.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            return await client.request(method, '/api/intelligence' + path)

    return call


def test_projection_recognizes_only_exact_legacy_wrapper_and_never_guesses_source():
    query = _BACKGROUND_PREFIX + "\n\nUser's request: compare them"
    review = project_review({'query': query}, {'context': {}})
    assert review['user_query'] == 'compare them'
    assert review['query_origin'] == 'legacy_background_wrapper'
    assert review['source'] == 'unknown'
    assert query.startswith(_BACKGROUND_PREFIX)  # Projection does not rewrite source evidence.
    arbitrary = "My text\n\nUser's request: keep all of this"
    assert project_review({'query': arbitrary})['user_query'] == arbitrary
    assert project_review({'query': query}, {'context': {'web_conversation_id': 'abc'}})['source'] == 'web'


def test_request_projection_redacts_and_keeps_explicit_source_unknown():
    secret = 'sk-' + 'a' * 30
    context = {'interaction': {'version': 1, 'source': 'cli',
                               'user_query': secret + ' ' + 'x' * 700}}
    review = project_review({'query': 'canonical'}, {'context': context})
    assert review['source_label'] == 'CLI'
    assert review['user_query_truncated'] is True
    assert len(review['user_query']) == 600
    assert secret not in json.dumps(review)
    context['interaction']['source'] = []
    context['web_conversation_id'] = 'saved-conversation'
    assert project_review({'query': 'canonical'}, {'context': context})['source'] == 'unknown'
    assert project_review({'query': 'canonical'}, {'context': {'interaction': 'invalid json'}})['source'] == 'unknown'


def test_pagination_search_and_global_batch_order_are_truthful(dashboard, layers):
    client, _ = dashboard
    intel = layers['cloud']
    ids = [add_item(intel, f'Original request {index}', priority=1 if index < 3 else 0.5)[0]
           for index in range(61)]
    # A match past preview truncation must remain searchable; routing hints are excluded.
    target_id, _ = add_item(intel, 'augmented routing hints only', context={'interaction': {
        'version': 1, 'source': 'voice', 'user_query': 'x' * 700 + ' unique_needle',
        'previous_turns': [], 'context_truncated': False}})
    payload = client.get('/api/stats/reflection-queue?limit=50').get_json()
    assert payload['total'] == payload['filtered_total'] == 62
    assert payload['count'] == 50 and payload['has_more']
    assert payload['next_batch_ids'] == ids[:20]
    second = client.get('/api/stats/reflection-queue?limit=50&offset=50').get_json()
    assert second['count'] == 12 and not second['has_more']
    filtered = client.get('/api/stats/reflection-queue?q=unique_needle').get_json()
    assert filtered['filtered_total'] == 1 and filtered['total'] == 62
    assert filtered['queue'][0]['id'] == target_id
    assert filtered['next_batch_ids'] == ids[:20]
    assert client.get('/api/stats/reflection-queue?q=augmented%20routing').get_json()['filtered_total'] == 0
    assert client.get('/api/stats/reflection-queue?mode=local').get_json()['total'] == 0
    assert client.get('/api/stats/reflection-queue?limit=101').status_code == 400
    assert client.get('/api/stats/reflection-queue?mode=bogus').status_code == 400


def test_detail_returns_only_request_and_recorded_answer_and_discard_preserves_experience(dashboard, layers):
    client, _ = dashboard
    secret = 'sk-' + 'z' * 30
    queue_id, experience_id = add_item(layers['cloud'], context={
        'tool_results': secret, 'raw_llm_response': 'stored response',
        'interaction': {'version': 1, 'source': 'web', 'user_query': 'Which one?',
                        'previous_turns': [{'role': 'assistant', 'content': 'Blue or red?'}]}})
    payload = client.get(f'/api/stats/reflection-queue/{queue_id}').get_json()
    assert set(payload) == {'ok', 'item'}
    assert payload['item']['review']['response'] == 'stored response'
    assert 'raw_data' not in payload['item']
    assert secret not in json.dumps(payload)
    assert set(payload['item']['review']) == {
        'user_query', 'user_query_truncated', 'source', 'source_label', 'query_origin',
        'response', 'response_truncated'}
    assert client.get(f'/api/stats/reflection-queue/{queue_id}?mode=local').status_code == 404
    assert client.delete(f'/api/stats/reflection-queue/{queue_id}').status_code == 200
    assert client.get(f'/api/stats/reflection-queue/{queue_id}').status_code == 404
    assert layers['cloud'].conn.execute('SELECT id FROM experiences WHERE id = ?', (experience_id,)).fetchone()


@pytest.mark.parametrize('wrapped', [False, True])
def test_lazy_detail_returns_full_clean_legacy_request_without_preview_truncation(dashboard, layers, wrapped):
    client, _ = dashboard
    secret = 'sk-' + 'q' * 30
    original = 'Long original request ' + 'more details ' * 600 + secret + ' final detail'
    stored = (_BACKGROUND_PREFIX + "\n\nUser's request: " if wrapped else '') + original
    queue_id, experience_id = add_item(layers['cloud'], stored)
    preview = client.get('/api/stats/reflection-queue').get_json()['queue'][0]['review']
    assert len(preview['user_query']) == 600 and preview['user_query_truncated'] is True
    payload = client.get(f'/api/stats/reflection-queue/{queue_id}').get_json()
    review = payload['item']['review']
    assert review['user_query'].startswith('Long original request ')
    assert review['user_query'].endswith(' final detail')
    assert len(review['user_query']) > 6000
    assert _BACKGROUND_PREFIX not in review['user_query']
    assert secret not in json.dumps(payload)
    assert review['user_query_truncated'] is False
    assert layers['cloud'].conn.execute('SELECT query FROM experiences WHERE id = ?',
                                        (experience_id,)).fetchone()[0] == stored


@pytest.mark.parametrize('saved_truncated', [False, True])
def test_detail_request_truncation_flag_describes_saved_capture(dashboard, layers, saved_truncated):
    client, _ = dashboard
    original = 'Captured original ' + 'details ' * 1000
    queue_id, _ = add_item(layers['cloud'], 'canonical', context={'interaction': {
        'version': 1, 'source': 'web', 'user_query': original,
        'user_query_truncated': saved_truncated}})
    review = client.get(f'/api/stats/reflection-queue/{queue_id}').get_json()['item']['review']
    assert review['user_query'] == original
    assert review['user_query_truncated'] is saved_truncated


def test_deterministic_processing_failures_orphans_and_legacy_integer(layers):
    intel = layers['cloud']
    later, later_exp = add_item(intel, 'later', priority=1, queued_at='2026-10-15 13:00:00')
    first, first_exp = add_item(intel, 'first', priority=1)
    second, second_exp = add_item(intel, 'second', priority=1)
    orphan, orphan_exp = add_item(intel, 'orphan', priority=2)
    intel.conn.execute('DELETE FROM experiences WHERE id = ?', (orphan_exp,))
    intel.conn.commit()
    calls = []

    async def reflect(experience_id):
        calls.append(experience_id)
        if experience_id == second_exp:
            return None
        intel.conn.execute('UPDATE reflection_queue SET processed = 1 WHERE experience_id = ?', (experience_id,))
        intel.conn.commit()
        return {'is_procedural': False}  # A valid settled reflection need not generate an insight.

    intel.reflect_on_experience = reflect
    result = asyncio.run(intel.process_reflection_queue_detailed(batch_size=4))
    assert calls == [first_exp, second_exp, later_exp]
    assert [item['reflection_id'] for item in result['outcomes']] == [first, second, later]
    assert {key: result[key] for key in ('requested', 'attempted', 'processed', 'failed', 'skipped', 'remaining')} == {
        'requested': 3, 'attempted': 3, 'processed': 2, 'failed': 1, 'skipped': 0, 'remaining': 1}
    assert result['discarded_orphans'] == 1
    assert intel.conn.execute('SELECT processed FROM reflection_queue WHERE id = ?', (orphan,)).fetchone()[0] == 1
    assert asyncio.run(intel.process_reflection_queue(batch_size=1)) == 0
    assert calls == [first_exp, second_exp, later_exp, second_exp]
    explicit = asyncio.run(intel.process_reflection_queue_detailed(reflection_ids=[orphan]))
    assert explicit['attempted'] == 0 and explicit['skipped'] == 1
    assert explicit['outcomes'][0]['reason'] == 'missing_experience'


def test_orphan_at_queue_head_does_not_block_single_item_processing(layers):
    intel = layers['cloud']
    orphan, orphan_exp = add_item(intel, 'missing experience', priority=1)
    valid, valid_exp = add_item(intel, 'valid next item', priority=0.5)
    intel.conn.execute('DELETE FROM experiences WHERE id = ?', (orphan_exp,))
    intel.conn.commit()

    async def settle(experience_id):
        intel.conn.execute('UPDATE reflection_queue SET processed = 1 WHERE experience_id = ?', (experience_id,))
        intel.conn.commit()
        return {'is_procedural': False}

    intel.reflect_on_experience = AsyncMock(side_effect=settle)
    result = asyncio.run(intel.process_reflection_queue_detailed(batch_size=1))
    assert result['processed'] == 1 and result['discarded_orphans'] == 1
    assert result['outcomes'][0]['reflection_id'] == valid
    assert result['remaining'] == 0
    intel.reflect_on_experience.assert_awaited_once_with(valid_exp)
    assert intel.conn.execute('SELECT processed FROM reflection_queue WHERE id = ?', (orphan,)).fetchone()[0] == 1


def test_process_one_orphan_returns_successful_skip_and_refresh_removes_it(dashboard, layers):
    client, _ = dashboard
    intel = layers['cloud']
    orphan, orphan_exp = add_item(intel, 'removed experience', priority=1)
    valid, _ = add_item(intel, 'still pending')
    intel.conn.execute('DELETE FROM experiences WHERE id = ?', (orphan_exp,))
    intel.conn.commit()
    intel.reflect_on_experience = AsyncMock()

    response = client.post('/api/maintenance/reflect', json={'reflection_id': orphan})
    assert response.status_code == 200
    result = response.get_json()
    assert result['ok'] is True and 'error' not in result
    assert result['processed'] == result['attempted'] == result['failed'] == 0
    assert result['skipped'] == result['remaining'] == 1
    assert result['outcomes'][0]['reason'] == 'missing_experience'
    assert intel.conn.execute('SELECT processed FROM reflection_queue WHERE id = ?', (orphan,)).fetchone()[0] == 1
    queue = client.get('/api/stats/reflection-queue').get_json()
    assert [item['id'] for item in queue['queue']] == [valid]
    intel.reflect_on_experience.assert_not_awaited()


def test_batch_ids_do_not_retry_failed_rows_and_single_statuses(dashboard, layers):
    client, _ = dashboard
    intel = layers['cloud']
    ids = [add_item(intel, str(index))[0] for index in range(20)]
    intel.reflect_on_experience = AsyncMock(return_value=None)
    attempted = []
    for index in range(0, 20, 5):
        response = client.post('/api/maintenance/reflect', json={'reflection_ids': ids[index:index + 5]})
        assert response.status_code == 200
        result = response.get_json()
        assert result['attempted'] == result['failed'] == 5
        attempted.extend(item['reflection_id'] for item in result['outcomes'])
    assert attempted == ids
    assert intel.reflect_on_experience.await_count == 20
    assert client.post('/api/maintenance/reflect', json={'reflection_id': 9999}).status_code == 404
    intel.conn.execute('UPDATE reflection_queue SET processed = 1 WHERE id = ?', (ids[0],))
    intel.conn.commit()
    assert client.post('/api/maintenance/reflect', json={'reflection_id': ids[0]}).status_code == 409
    assert client.delete(f'/api/stats/reflection-queue/{ids[0]}').status_code == 409
    for body in ({'reflection_ids': ids[:6]}, {'reflection_id': True},
                 {'reflection_ids': [1, 1]}, {'reflection_ids': None},
                 {'reflection_id': 1, 'reflection_ids': [1]}):
        assert client.post('/api/maintenance/reflect', json=body).status_code == 400
    for size in ('0', '21', 'abc'):
        assert client.post('/api/maintenance/reflect?batch_size=' + size).status_code == 400
    assert intel.reflect_on_experience.await_count == 20


def test_busy_lock_blocks_processing_and_discard_but_is_mode_local(dashboard, layers):
    client, _ = dashboard
    queue_id, _ = add_item(layers['cloud'])
    add_item(layers['local'])
    lock = processing_lock(layers['cloud'].db_path)
    with lock:
        assert client.post('/api/maintenance/reflect').status_code == 409
        assert client.delete(f'/api/stats/reflection-queue/{queue_id}').status_code == 409
        assert client.delete('/api/stats/reflection-queue').status_code == 409
        assert client.delete('/api/stats/reflection-queue?mode=local').get_json()['deleted'] == 1
        with pytest.raises(ReflectionBusy):
            asyncio.run(layers['cloud'].process_reflection_queue_detailed())
    assert client.get('/api/stats/reflection-queue').get_json()['total'] == 1
    assert client.delete('/api/stats/reflection-queue').get_json()['deleted'] == 1


def test_nonprocedural_reflection_settles_without_creating_an_insight(layers):
    intel = layers['cloud']
    queue_id, experience_id = add_item(intel)
    intel._think_deeply = AsyncMock(return_value={'is_procedural': False})
    result = asyncio.run(intel.process_reflection_queue_detailed(reflection_ids=[queue_id]))
    assert result['processed'] == 1 and result['remaining'] == 0
    assert intel.conn.execute('SELECT COUNT(*) FROM insights').fetchone()[0] == 0
    assert intel._think_deeply.call_args.kwargs['experience_id'] == experience_id


def test_legacy_processor_preserves_larger_positive_batches(layers):
    intel = layers['cloud']
    for index in range(25):
        add_item(intel, str(index))

    async def settle(experience_id):
        intel.conn.execute('UPDATE reflection_queue SET processed = 1 WHERE experience_id = ?', (experience_id,))
        intel.conn.commit()
        return {'is_procedural': False}

    intel.reflect_on_experience = AsyncMock(side_effect=settle)
    result = asyncio.run(intel.process_reflection_queue(batch_size=25))
    assert result == 25 and isinstance(result, int)
    assert intel.reflect_on_experience.await_count == 25


def test_concurrent_request_cannot_duplicate_model_call_and_modes_stay_scoped(dashboard, layers):
    client, _ = dashboard
    add_item(layers['cloud'])
    add_item(layers['local'])
    entered = threading.Event()
    release = threading.Event()
    seen_modes = []

    async def settle(mode, experience_id):
        from config_loader import get_active_config_mode

        seen_modes.append(get_active_config_mode())
        if mode == 'cloud':
            entered.set()
            assert release.wait(5), 'Test did not release the isolated mock reflection'
        layers[mode].conn.execute(
            'UPDATE reflection_queue SET processed = 1 WHERE experience_id = ?', (experience_id,))
        layers[mode].conn.commit()
        return {'is_procedural': False}

    async def cloud_reflect(exp_id):
        return await settle('cloud', exp_id)

    async def local_reflect(exp_id):
        return await settle('local', exp_id)

    layers['cloud'].reflect_on_experience = AsyncMock(side_effect=cloud_reflect)
    layers['local'].reflect_on_experience = AsyncMock(side_effect=local_reflect)

    def request_cloud():
        with client.application.test_client() as other_client:
            return other_client.post('/api/maintenance/reflect').get_json()

    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(request_cloud)
        try:
            assert entered.wait(5)
            assert client.post('/api/maintenance/reflect').status_code == 409
            assert client.delete('/api/stats/reflection-queue').status_code == 409
            assert client.post('/api/maintenance/reflect?mode=local').get_json()['processed'] == 1
        finally:
            release.set()
        assert running.result(timeout=5)['processed'] == 1
    assert layers['cloud'].reflect_on_experience.await_count == 1
    assert layers['local'].reflect_on_experience.await_count == 1
    assert seen_modes == ['cloud', 'local']


def test_main_api_reflect_and_pending_deletes_report_busy_without_writes(main_api, layers):
    intel = layers['cloud']
    queue_id, experience_id = add_item(intel)
    intel.reflect_on_experience = AsyncMock(return_value=None)
    with processing_lock(intel.db_path):
        for method, path in (('POST', '/reflect'), ('DELETE', f'/reflections/{queue_id}'),
                             ('DELETE', '/reflections')):
            response = asyncio.run(main_api(method, path))
            assert response.status_code == 409
            assert response.json()['status'] == 'error'
    intel.reflect_on_experience.assert_not_awaited()
    assert intel.conn.execute('SELECT processed FROM reflection_queue WHERE id = ?', (queue_id,)).fetchone()[0] == 0
    assert intel.conn.execute('SELECT id FROM experiences WHERE id = ?', (experience_id,)).fetchone()


def test_main_api_reflect_preserves_success_shape_and_large_batch(main_api, layers):
    intel = layers['cloud']
    for index in range(25):
        add_item(intel, str(index))

    async def settle(experience_id):
        intel.conn.execute('UPDATE reflection_queue SET processed = 1 WHERE experience_id = ?', (experience_id,))
        intel.conn.commit()
        return {'is_procedural': False}

    intel.reflect_on_experience = AsyncMock(side_effect=settle)
    response = asyncio.run(main_api('POST', '/reflect?batch_size=25'))
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'processed': 25,
                               'message': 'Processed 25 pending reflections'}
    assert intel.reflect_on_experience.await_count == 25


def test_main_api_discards_only_pending_rows_and_keeps_source_experiences(main_api, layers):
    intel = layers['cloud']
    single_id, single_exp = add_item(intel)
    add_item(intel, 'another pending')
    processed_id, _ = add_item(intel, 'processed', processed=1)
    response = asyncio.run(main_api('DELETE', f'/reflections/{single_id}'))
    assert response.json() == {'status': 'ok', 'message': f'Reflection {single_id} cancelled'}
    response = asyncio.run(main_api('DELETE', '/reflections'))
    assert response.json() == {'status': 'ok', 'deleted': 1,
                               'message': 'Cancelled 1 pending reflections'}
    assert [row['id'] for row in intel.conn.execute('SELECT id FROM reflection_queue')] == [processed_id]
    assert intel.conn.execute('SELECT id FROM experiences WHERE id = ?', (single_exp,)).fetchone()


def test_experience_deletion_obeys_processing_lock_and_retains_provenance_semantics(dashboard, layers):
    client, services = dashboard
    intel = layers['cloud']
    queue_id, experience_id = add_item(intel)
    insight_id = intel.conn.execute(
        'INSERT INTO insights(description, source_experience_id) VALUES (?, ?)',
        ('Existing learned insight', experience_id)).lastrowid
    intel.conn.execute('INSERT INTO insight_evidence(insight_id, experience_id) VALUES (?, ?)',
                       (insight_id, experience_id))
    intel.conn.commit()
    add_item(layers['local'])
    with processing_lock(intel.db_path):
        assert client.delete(f'/api/experiences/{experience_id}').status_code == 409
        with pytest.raises(ReflectionBusy):
            services['cloud'].delete_experience(experience_id)
        assert client.delete('/api/experiences/1?mode=local').status_code == 200
    assert intel.conn.execute('SELECT id FROM experiences WHERE id = ?', (experience_id,)).fetchone()
    assert intel.conn.execute('SELECT id FROM reflection_queue WHERE id = ?', (queue_id,)).fetchone()
    assert client.delete(f'/api/experiences/{experience_id}').get_json() == {
        'ok': True, 'message': 'Experience deleted'}
    assert intel.conn.execute('SELECT id FROM reflection_queue WHERE id = ?', (queue_id,)).fetchone() is None
    assert intel.conn.execute('SELECT source_experience_id FROM insights WHERE id = ?',
                              (insight_id,)).fetchone()[0] is None
    assert intel.conn.execute('SELECT experience_id FROM insight_evidence WHERE insight_id = ?',
                              (insight_id,)).fetchone()[0] is None
    assert client.delete(f'/api/experiences/{experience_id}').status_code == 404
    assert client.delete('/api/experiences/1?mode=invalid').status_code == 400
