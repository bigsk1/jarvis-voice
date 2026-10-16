"""Real child-process contention, isolated databases, and no provider requests."""

import asyncio
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))

from intelligence import IntelligenceLayer  # noqa: E402
from reflection_review import (  # noqa: E402
    ReflectionBusy,
    processing_lock,
    project_review,
)

WORKER = '''
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from intelligence import IntelligenceLayer
layer = IntelligenceLayer(sys.argv[2], load_runtime_config=False)
async def simulated_model(experience_id):
    assert not layer.conn.in_transaction, "SQLite write transaction held during model call"
    Path(sys.argv[3]).write_text("ready")
    sys.stdin.readline()
    layer.conn.execute("UPDATE reflection_queue SET processed = 1 WHERE experience_id = ?", (experience_id,))
    layer.conn.commit()
layer.reflect_on_experience = simulated_model
try:
    print(json.dumps(asyncio.run(layer.process_reflection_queue_detailed(batch_size=1))), flush=True)
finally:
    layer.conn.close()
'''


@pytest.fixture
def layer(tmp_path):
    with patch('intelligence.get_intel_logger'):
        intel = IntelligenceLayer(str(tmp_path / 'intelligence.db'), load_runtime_config=False)
        exp_id = intel.conn.execute(
            'INSERT INTO experiences(query, tools_used, outcome_success, raw_data) VALUES (?, ?, ?, ?)',
            ('Compare those results', '["search_memory"]', 1, '{"context": {}}')).lastrowid
        queue_id = intel.conn.execute(
            'INSERT INTO reflection_queue(experience_id, priority) VALUES (?, ?)', (exp_id, 0.5)).lastrowid
        intel.conn.commit()
        yield intel, exp_id, queue_id
        intel.conn.close()


@pytest.fixture
def model_process(layer, tmp_path):
    intel, _, _ = layer
    ready = tmp_path / 'model-ready'
    child = subprocess.Popen(
        [sys.executable, '-c', WORKER, str(ROOT / 'lib'), intel.db_path, str(ready)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            if child.poll() is not None:
                pytest.fail('Reflection child exited before readiness: ' + child.communicate()[1])
            if time.monotonic() >= deadline:
                pytest.fail('Reflection child did not reach its simulated model call')
            time.sleep(0.01)
        yield child
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


def test_another_service_cannot_reflect_or_delete_during_model_call(layer, model_process, monkeypatch):
    import intelligence

    from api.routes import intelligence as api_intelligence

    intel, exp_id, queue_id = layer
    monkeypatch.setattr(intelligence, 'get_intelligence_layer', lambda: intel)
    with pytest.raises(ReflectionBusy):
        asyncio.run(intel.process_reflection_queue(batch_size=1))
    for request in (
        api_intelligence.trigger_reflection_endpoint(batch_size=1),
        api_intelligence.delete_reflection(queue_id),
        api_intelligence.delete_all_reflections(),
    ):
        assert asyncio.run(request).status_code == 409

    spec = importlib.util.spec_from_file_location(
        '_cross_process_intelligence_service',
        ROOT / 'jarvis-intelligence/server/services/intelligence_service.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    service = module.IntelligenceService.__new__(module.IntelligenceService)
    service.db_path = Path(intel.db_path)
    service.mode = 'cloud'
    for mutation in (lambda: service.delete_experience(exp_id), service.delete_all_pending_reflections):
        with pytest.raises(ReflectionBusy):
            mutation()
    assert intel.conn.execute('SELECT processed FROM reflection_queue WHERE id = ?', (queue_id,)).fetchone()[0] == 0

    # Learning can still write unrelated experiences during the slow model call.
    intel.conn.execute('PRAGMA busy_timeout = 250')
    intel.conn.execute('INSERT INTO experiences(query) VALUES (?)', ('Another completed turn',))
    intel.conn.commit()

    output, error = model_process.communicate(input='finish\n', timeout=10)
    assert model_process.returncode == 0, error
    assert json.loads(output.splitlines()[-1])['processed'] == 1
    lock = processing_lock(intel.db_path)
    assert lock.acquire(blocking=False)
    lock.release()
    assert intel.conn.execute('SELECT COUNT(*) FROM experiences WHERE id = ?', (exp_id,)).fetchone()[0] == 1


@pytest.mark.parametrize('inside_event_loop', [False, True])
def test_python_helper_propagates_busy_instead_of_reporting_zero(layer, model_process, monkeypatch, inside_event_loop):
    import intelligence_hooks

    intel, _, queue_id = layer
    monkeypatch.setattr(intelligence_hooks, '_get_intel', lambda: intel)
    with patch.object(intelligence_hooks.logger, 'warning') as warning, pytest.raises(ReflectionBusy):
        if inside_event_loop:
            async def call_helper():
                return intelligence_hooks.trigger_reflection(batch_size=1)

            asyncio.run(call_helper())
        else:
            intelligence_hooks.trigger_reflection(batch_size=1)
    warning.assert_not_called()
    assert intel.conn.execute('SELECT processed FROM reflection_queue WHERE id = ?', (queue_id,)).fetchone()[0] == 0


def test_worker_crash_releases_lock_and_leaves_entry_pending(layer, model_process):
    intel, _, queue_id = layer
    lock = processing_lock(intel.db_path)
    assert not lock.acquire(blocking=False)
    model_process.kill()
    model_process.communicate(timeout=5)
    assert lock.acquire(blocking=False)
    lock.release()
    assert intel.conn.execute('SELECT processed FROM reflection_queue WHERE id = ?', (queue_id,)).fetchone()[0] == 0
    # The sidecar is intentionally persistent; its presence is not a busy signal.
    assert Path(intel.db_path + '.reflection.lock').exists()


@pytest.mark.parametrize('raw_key', ['raw_llm_response', 'llm_response', 'final_speech'])
def test_detail_selects_one_recorded_answer_with_raw_response_precedence(raw_key):
    context = {raw_key: 'The recorded answer.', 'final_speech': 'Spoken receipt.'}
    if raw_key == 'final_speech':
        context[raw_key] = 'The recorded answer.'
    raw = {'context': context}
    review = project_review({'query': 'compare'}, raw, full_request=True)
    assert review['response'] == 'The recorded answer.'
    assert review['response_truncated'] is False
    assert 'response' not in project_review({'query': 'compare'}, raw)


def test_detail_redacts_and_marks_stored_or_display_answer_cutoffs():
    secret = 'sk-' + 'a' * 30
    full = secret + ' ' + 'Legacy answer ' * 1000
    review = project_review({'query': 'compare'}, {'context': {'raw_llm_response': full}}, full_request=True)
    assert len(review['response']) == 6000
    assert review['response_truncated'] is True
    assert secret not in review['response']
    clipped = project_review({'query': 'compare'}, {'context': {'llm_response': 'Saved excerpt... [truncated]'}},
                             full_request=True)
    assert clipped['response'] == 'Saved excerpt... [truncated]'
    assert clipped['response_truncated'] is True
    missing = project_review({'query': 'compare'}, full_request=True)
    assert missing['response'] == '' and missing['response_truncated'] is False


@pytest.mark.parametrize('source,label', [
    ('web', 'Web'), ('voice', 'Voice'), ('cli', 'CLI'), ('api', 'API'),
    ('scheduled', 'Scheduled task'), ('unknown', 'Unknown'), ('unrecognized', 'Unknown'),
])
def test_legacy_source_metadata_stays_read_only_and_honest(source, label):
    raw = {'context': {'interaction': {'version': 1, 'source': source, 'user_query': 'Original'}}}
    before = json.dumps(raw)
    assert project_review({'query': 'stored'}, raw)['source_label'] == label
    assert json.dumps(raw) == before
