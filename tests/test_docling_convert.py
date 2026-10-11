"""Docling async wire contract, failure evidence, opt-in and saved follow-ups."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from test_background_tasks import store as store

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills'))
sys.path.insert(0, str(ROOT / 'lib'))
import docling_convert as tool  # noqa: E402
from config_loader import config_scope  # noqa: E402
from tool_availability import check_tool_availability  # noqa: E402

TASK = '00000000-0000-4000-8000-000000000001'


@pytest.fixture
def server(tmp_path):
    state = {'posts': 0, 'gets': [], 'submit_status': 200, 'poll_status': 200, 'state': 'success',
             'payload': {'status': 'success', 'document': {'filename': 'input.png',
              'md_content': '# Report\n\nInvoice 314159 | Total 42.75', 'text_content': 'Invoice 314159 Total 42.75',
              'json_content': {'pages': {'1': {}}, 'tables': [{'data': {}}], 'texts': []}}, 'errors': [], 'processing_time': 1}}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, data):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_POST(self):
            state['posts'] += 1
            state['key'] = self.headers.get('X-Custom-Key')
            state['body'] = self.rfile.read(int(self.headers['Content-Length']))
            self.reply(state['submit_status'], {'task_id': TASK, 'task_status': 'pending', 'task_type': 'convert'})

        def do_GET(self):
            state['gets'].append(self.path)
            if '/status/poll/' in self.path:
                self.reply(state['poll_status'], {'task_id': state.get('task_id', TASK), 'task_status': state['state'], 'task_type': 'convert'})
            elif '/result/' in self.path:
                self.reply(200, state['payload'])
            elif self.path == '/ready':
                self.reply(200, {'status': 'ok'})
            else:
                self.reply(200, {'versions': {'docling-serve': '1.36.0'}})
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    state['settings'] = {'DOCLING_BASE_URL': f'http://127.0.0.1:{http.server_port}',
                         'DOCLING_API_KEY': 'fixture-key-secret', 'DOCLING_API_KEY_HEADER': 'X-Custom-Key',
                         'DOCLING_TIMEOUT_SECONDS': '300', 'STASH_DIR': str(tmp_path / 'stash')}
    state['source'] = tmp_path / 'source.pdf'
    state['source'].write_bytes(b'%PDF-fixture')
    try:
        yield state
    finally:
        http.shutdown()
        http.server_close()
        thread.join(5)


def convert(state, **args):
    with config_scope('cloud', state['settings']):
        return tool.execute({'action': 'convert', 'file_path': str(state['source']), **args})


def test_multipart_options_exports_and_custom_header(server):
    result = convert(server, page_start=2, page_end=4)
    assert result['ok'], result
    data = result['data']
    assert data['task_id'] == TASK and data['page_count'] == 1 and data['table_count'] == 1
    assert data['space_id'].startswith('space_') and len(data['outputs']) == 3
    assert server['posts'] == 1 and server['key'] == 'fixture-key-secret'
    assert b'name="page_range"\r\n\r\n2' in server['body']
    assert b'name="page_range"\r\n\r\n4' in server['body']
    assert b'name="target_type"\r\n\r\ninbody' in server['body']
    assert b'name="to_formats"\r\n\r\nmd' in server['body']
    assert Path(data['file_path']).read_text().startswith('# Report')
    assert data['receipt_stash_ref'].startswith('stash://')
    json.dumps(result)  # All returned fields must be JSON-serializable.


def test_stash_input_and_collect_never_uploads_again(server):
    from stash_helper import StashFile, open_space
    with config_scope('local', server['settings']):
        space, _ = open_space(scope='project')
        ref = StashFile(space).save_binary(b'%PDF', 'input.pdf')['ref']
        first = tool.execute({'action': 'convert', 'stash_ref': ref})
        assert first['data']['source_stash_ref'] == ref
        again = tool.execute({'action': 'collect', 'task_id': first['data']['task_id'], 'output_name': 'second'})
    assert again['ok'] and server['posts'] == 1
    assert first['data']['stash_ref'] != again['data']['stash_ref']


@pytest.mark.parametrize('args', [
    {'stash_ref': 'stash://space/file'}, {'formats': ['bad']}, {'formats': ['md','md']},
    {'page_start': 2, 'page_end': 1}, {'force_ocr': True, 'do_ocr': False},
    {'task_id': TASK}, {'output_name': '../escape'},
    {'do_ocr': 'false'}, {'formats': [{}]}, {'arbitrary_option': 'not allowed'},
])
def test_reject_invalid_combinations_before_submission(server, args):
    result = convert(server, **args)
    assert not result['ok'] and result['completion'] == 'rejected'
    assert server['posts'] == 0


@pytest.mark.parametrize('status,completion', [(401,'rejected'), (403,'rejected'), (422,'rejected'), (429,'rejected'), (500,'unknown'), (302,'unknown')])
def test_submit_failure_is_not_replayed_and_redirect_does_not_receive_key(server, status, completion):
    server['submit_status'] = status
    result = convert(server)
    assert not result['ok'] and result['completion'] == completion
    assert server['posts'] == 1 and not server['gets']
    assert server['settings']['DOCLING_API_KEY'] not in result['error']


@pytest.mark.parametrize('status', [404, 503])
def test_lost_observation_keeps_task_id_without_reupload(server, status):
    server['poll_status'] = status
    result = convert(server)
    assert not result['ok'] and result['completion'] == 'unknown'
    assert result['data']['task_id'] == TASK and result['data']['receipt_stash_ref']
    assert server['posts'] == 1


def test_mismatched_polled_task_cannot_save_another_document(server):
    server['task_id'] = '00000000-0000-4000-8000-000000000002'
    result = convert(server)
    assert not result['ok'] and result['completion'] == 'unknown'
    assert not any('/result/' in path for path in server['gets'])


@pytest.mark.parametrize('status', ['failure', 'skipped'])
def test_terminal_conversion_failure_is_confirmed(server, status):
    server['state'] = status
    result = convert(server)
    assert not result['ok'] and result['completion'] == 'completed'
    assert result['data']['task_id'] == TASK


def test_partial_and_empty_output_are_not_described_as_full_success(server):
    server['state'] = 'partial_success'
    server['payload']['status'] = 'partial_success'
    server['payload']['errors'] = [{'message': 'one page failed'}]
    result = convert(server)
    assert result['ok'] and result['data']['partial'] and result['data']['error_count'] == 1
    assert 'partially' in result['speech']
    server['state'] = 'success'
    server['payload']['status'] = 'success'
    server['payload']['document'] = {'md_content': '', 'text_content': '', 'json_content': {'pages': {}, 'texts': [], 'tables': []}}
    result = convert(server)
    assert not result['ok'] and result['completion'] == 'completed'


def test_timeout_receipt_differs_from_background_uncertainty(server, monkeypatch):
    server['state'] = 'started'
    monkeypatch.setattr(tool.Client, 'wait', lambda self, identifier: self.job(identifier))
    result = convert(server)
    assert result['ok'] and result['data']['state'] == 'started' and 'file_path' not in result['data']
    with config_scope('cloud', {**server['settings'], 'JARVIS_BACKGROUND_MAX_INPUT_BYTES': str(tool.MAX_UPLOAD)}):
        result = tool.execute({'action': 'convert', 'file_path': str(server['source'])})
    assert not result['ok'] and result['completion'] == 'unknown' and result['data']['task_id'] == TASK


def test_submission_emits_recovery_before_wait_and_receipt_write(server, monkeypatch):
    events = []
    original = tool.StashFile.save_binary
    monkeypatch.setattr(tool, 'emit_tool_progress', lambda payload: events.append(payload))

    def save_receipt(self, data, name, **kwargs):
        if name == 'docling-task.json':
            assert events == [{'phase': 'Docling conversion accepted', 'recovery': {'task_id': TASK}}]
        return original(self, data, name, **kwargs)

    def wait(self, identifier):
        assert events[-1]['recovery'] == {'task_id': TASK, 'receipt_stash_ref': self.receipt}
        raise TimeoutError('Fixture observer ended before final stdout')

    monkeypatch.setattr(tool.StashFile, 'save_binary', save_receipt)
    monkeypatch.setattr(tool.Client, 'wait', wait)
    result = convert(server)
    assert result['completion'] == 'unknown' and len(events) == 2
    assert server['posts'] == 1 and not server['gets']
    assert server['settings']['DOCLING_API_KEY'] not in json.dumps(events)


def test_task_id_progress_survives_receipt_storage_failure(server, monkeypatch):
    events = []
    monkeypatch.setattr(tool, 'emit_tool_progress', lambda payload: events.append(payload))
    monkeypatch.setattr(tool, 'open_space', lambda **kwargs: (_ for _ in ()).throw(OSError('unwritable')))
    result = convert(server)
    assert result['completion'] == 'unknown'
    assert events == [{'phase': 'Docling conversion accepted', 'recovery': {'task_id': TASK}}]
    assert server['posts'] == 1 and not server['gets']


def test_oversized_response_keeps_accepted_task(server, monkeypatch):
    monkeypatch.setattr(tool, 'MAX_RESPONSE', 150)
    result = convert(server)
    assert not result['ok'] and result['completion'] == 'completed'
    assert result['data']['task_id'] == TASK


def test_opt_in_modes_and_remote_https_configuration(server):
    manifest = json.loads((ROOT/'skills/docling_convert.tool.json').read_text())
    with config_scope('cloud', server['settings']):
        assert check_tool_availability(manifest).available
    for settings in ({'DOCLING_BASE_URL':'', 'DOCLING_API_KEY':''}, {'DOCLING_BASE_URL':'https://docling.example.com','DOCLING_API_KEY':''}):
        with config_scope('local', settings):
            assert not check_tool_availability(manifest).available
            result = tool.execute({'action':'status'})
            assert not result['ok'] and result['completion'] == 'rejected'
    with config_scope('local', {**server['settings'], 'DOCLING_BASE_URL':'https://docling.example.com'}):
        client = tool.Client()
        assert client.base == 'https://docling.example.com' and client.session.verify is True
        client.session.close()


def test_restricted_background_policy_and_schema(server):
    from lib.background_tasks import production
    from lib.background_tasks.local_skill import restrict_child_environment, validate_arguments
    with config_scope('cloud', server['settings']):
        schema, policy = production.runner().policy('docling_convert')
        assert policy['adapter'] == 'remote_skill_v1' and policy['timeout_seconds'] == 960
        validate_arguments(schema, {'action':'convert','stash_ref':'stash://space/file'})
        validate_arguments(schema, {'action':'collect','task_id':TASK})
        clean = restrict_child_environment({'DOCLING_API_KEY':'own', 'OPENAI_API_KEY':'unrelated',
                   'DOCLING_API_KEY_HEADER':'X-Custom-Key','DOCLING_TIMEOUT_SECONDS':'300','STASH_DIR':'/tmp/stash'},
                   production.CHILD_ENVIRONMENT_POLICIES['docling_convert'], {}, Path('/tmp/docling-child'))
        assert clean['DOCLING_API_KEY'] == 'own' and clean['DOCLING_TIMEOUT_SECONDS'] == '300'
        assert 'OPENAI_API_KEY' not in clean


def test_followup_keeps_excerpt_and_native_table_reference(server):
    sys.path.insert(0, str(ROOT/'jarvis-web'))
    from server.services.followup_extractor import extract_followup_data
    result = convert(server)
    result['data']['markdown_excerpt'] = 'A' * 12000
    followup = extract_followup_data({'docling_convert':result})['docling_convert']
    assert followup['task_id'] == TASK and followup['json_stash_ref'] == result['data']['json_stash_ref']
    assert len(followup['markdown_excerpt']) <= 3100 and followup['table_count'] == 1


@pytest.mark.parametrize('action',['status','job','convert','collect'])
def test_background_selection_queues_work_but_not_read_only_checks(monkeypatch, action):
    from types import SimpleNamespace

    from lib.background_tasks.admission import WebTaskContext
    from orchestrator.executor import ToolExecutor
    calls=[]
    context=WebTaskContext(SimpleNamespace(admit=lambda *args:calls.append('background') or {'ok':True}),
                           'fixture-auth', ('docling_convert',))
    executor=ToolExecutor('cloud', SimpleNamespace(get_tool=lambda name:None), load_runtime_config=False)
    monkeypatch.setattr(executor,'_execute_foreground',lambda *args:calls.append('foreground') or {'ok':True})
    assert executor.execute('docling_convert',{'action':action},background_context=context)['ok']
    assert calls==(['foreground'] if action in ('status','job') else ['background'])


def test_jarvis_background_id_is_rejected_without_remote_poll(server):
    with config_scope('cloud',server['settings']):
        result=tool.execute({'action':'job','task_id':'a'*32})
    assert not result['ok'] and 'Jarvis background job_id' in result['error']
    assert not server['gets'] and not server['posts']


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('action', ['collect', 'job'])
def test_real_routing_preserves_conversion_when_model_polls_jarvis_receipt(server, store, monkeypatch, mode, action):
    from types import SimpleNamespace

    import test_orchestrator_tool_turn_budget as fixture

    from lib.background_tasks import production
    from lib.background_tasks.admission import BackgroundAdmissionService
    from orchestrator.executor import ToolExecutor

    with config_scope(mode, server['settings']):
        schema, policy = production.runner().policy('docling_convert')
        store.configure(background_tools=['docling_convert'])
        store.touch_worker('docling-fixture', {'remote_skill_v1'})
        service = BackgroundAdmissionService(store, adapters={'docling_convert': 'remote_skill_v1'},
                                            validate_source=lambda _: True, ready=lambda: True)
        registry = SimpleNamespace(list_tools=lambda: ['docling_convert'], get_tool=lambda _: schema)
        context = service.authorize({'operator': 'installation', 'source': 'web',
            'conversation_id': 'conversation-1', 'generation': 1, 'request_id': 'request-1',
            'mode': mode, 'selected': ['docling_convert'], 'tool_policy': 'auto',
            'tool_policies': {'docling_convert': policy}}, registry)
        orchestrator = fixture.ToolTurnBudgetTests()._build_orchestrator(fail_on_calls=set())
        orchestrator.registry = registry
        orchestrator.executor = ToolExecutor(mode, registry, load_runtime_config=False)
        orchestrator.background_context = context
        monkeypatch.setattr(orchestrator.executor, '_execute_foreground',
                            lambda *a, **kw: pytest.fail('No remote request may use the Jarvis job ID'))
        orchestrator._format_multi_turn_summary = lambda transcript, tools, data, text: text
        orchestrator._format_auto_mode = lambda transcript, tools, data, text, turn: text
        steps = iter(range(3))

        def route(*args, **kwargs):
            step = next(steps)
            if step == 2:
                return {'intent': 'qa', 'text_response': 'The conversion is queued.'}
            arguments = ({'action': 'convert', 'file_path': str(server['source']), 'formats': ['md']}
                         if step == 0 else {'action': action, 'task_id': next(iter(context.receipts))})
            return {'intent': 'tool', 'tool_name': 'docling_convert', 'arguments': arguments,
                    'tool_call_id': f'call-{step}'}

        orchestrator.router.route = route
        result = orchestrator.process('Convert this PDF to Markdown using Docling')
    assert result['ok'] and not result['tools_used'] and len(result['pending_jobs']) == 1
    assert len(store.conversation_jobs()) == 1 and store.conversation_jobs()[0]['dispatch_state'] == 'held'
    assert len(result['tool_trace']) == 2 and all(item['ok'] is None for item in result['tool_trace'])
    assert result['data']['docling_convert'][-1]['receipt_reused']
    assert server['posts'] == 0 and not server['gets']


@pytest.mark.parametrize('args', [
    {'action': 'collect', 'task_id': 'a' * 32},
    {'action': 'collect'},
    {'action': 'job', 'task_id': TASK},
    {'action': 'status'},
])
def test_actual_admission_rejects_bad_ids_and_foreground_actions(server, store, args):
    from types import SimpleNamespace

    from lib.background_tasks import AdmissionDenied, production
    from lib.background_tasks.admission import BackgroundAdmissionService
    with config_scope('cloud', server['settings']):
        schema, policy = production.runner().policy('docling_convert')
        store.configure(background_tools=['docling_convert'])
        store.touch_worker('docling-fixture', {'remote_skill_v1'})
        service = BackgroundAdmissionService(store, adapters={'docling_convert': 'remote_skill_v1'},
                                            validate_source=lambda _: True, ready=lambda: True)
        registry = SimpleNamespace(list_tools=lambda: ['docling_convert'], get_tool=lambda _: schema)
        context = service.authorize({'operator': 'installation', 'source': 'web',
            'conversation_id': 'conversation-1', 'generation': 1, 'request_id': 'request-1',
            'mode': 'cloud', 'selected': ['docling_convert'], 'tool_policy': 'auto',
            'tool_policies': {'docling_convert': policy}}, registry)
        before = store.counts()
        with pytest.raises(AdmissionDenied, match='no task was queued'):
            context.admit('docling_convert', args, 'invalid', schema)
        assert store.counts() == before and not context.receipts
        assert not store.pending_deliveries() and not server['gets'] and not server['posts']
        receipt = context.admit('docling_convert', {'action': 'collect', 'task_id': TASK}, 'valid', schema)
        assert store.get(receipt['job_id'])['admission']['arguments']['task_id'] == TASK


def test_status_is_bounded_readiness_without_capabilities(server):
    with config_scope('cloud', server['settings']):
        result = tool.execute({'action': 'status'})
    assert result['ok'] and result['data'] == {'ready': True}
    assert server['gets'] == ['/ready']


def test_consumed_result_survives_stash_failure_and_collects_offline(server, monkeypatch):
    original = tool.StashFile.save_binary

    def fail_exports(self, content, filename, **kwargs):
        if filename != 'docling-task.json':
            raise OSError('fixture disk failure')
        return original(self, content, filename, **kwargs)

    monkeypatch.setattr(tool.StashFile, 'save_binary', fail_exports)
    result = convert(server)
    assert not result['ok'] and result['completion'] == 'completed'
    assert result['data']['recovery_available'] and 'conversion completed' in result['speech']
    assert sum('/result/' in path for path in server['gets']) == 1
    requests_before = (server['posts'], list(server['gets']))
    monkeypatch.setattr(tool.StashFile, 'save_binary', original)
    server['poll_status'] = 404  # Single-use task no longer exists remotely.
    with config_scope('cloud', server['settings']):
        recovered = tool.execute({'action': 'collect', 'task_id': TASK})
        assert recovered['ok'] and len(recovered['data']['outputs']) == 3
        assert Path(recovered['data']['file_path']).read_text().startswith('# Report')
        client = tool.Client()
        assert not client.recovery_path(TASK).exists()
        client.session.close()
    assert (server['posts'], server['gets']) == requests_before


def test_stash_preflight_failure_never_consumes_result(server, monkeypatch):
    monkeypatch.setattr(tool, 'open_space', lambda **kwargs: (_ for _ in ()).throw(OSError('unwritable')))
    with config_scope('cloud', server['settings']):
        result = tool.execute({'action': 'collect', 'task_id': TASK})
    assert not result['ok'] and not result['data']['recovery_available']
    assert not any('/result/' in path for path in server['gets'])


def test_cached_result_cannot_cross_services(server, monkeypatch):
    monkeypatch.setattr(tool.StashFile, 'save_binary', lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    with config_scope('cloud', server['settings']):
        client = tool.Client()
        path = client.recovery_path(TASK)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(server['payload']))
        client.session.close()
    with config_scope('cloud', {**server['settings'], 'DOCLING_BASE_URL': 'https://other.example.com'}):
        client = tool.Client()
        assert client.cached_result(TASK) is None
        client.session.close()


INVALID_RESULTS = [
    {'status': 'success', 'document': {'md_content': '', 'text_content': '',
        'json_content': {'pages': {}, 'texts': [], 'tables': []}}},
    {'status': 'failure', 'document': {'md_content': 'failed conversion'}},
    {'status': 'success', 'document': []},
    {'status': 'success', 'document': {'json_content': 'invalid structure'}},
    {'status': 'success', 'document': {'md_content': ['invalid text']}},
    {'status': 'success', 'document': {'md_content': '\ud800'}},
    {'status': 'success', 'document': {'md_content': 'Report', 'json_content': {'tables': {}}}},
    {'status': 'success', 'document': {'md_content': 'Report'}, 'errors': None},
]


@pytest.mark.parametrize('payload', INVALID_RESULTS)
def test_unexportable_results_are_not_retained_as_recovery(server, payload):
    server['payload'] = payload
    result = convert(server)
    assert not result['ok'] and result['completion'] == 'completed'
    assert not result['data']['recovery_available']
    with config_scope('cloud', server['settings']):
        client = tool.Client()
        path = client.recovery_path(TASK)
        assert not path.exists()
        # A failed validation leaves neither a recovery response nor its spool.
        assert all(item.name.endswith('.lock') for item in path.parent.iterdir())
        client.session.close()


@pytest.mark.parametrize('payload', INVALID_RESULTS + [None])
def test_collect_discards_legacy_invalid_cache_and_checks_provider(server, payload):
    with config_scope('cloud', server['settings']):
        client = tool.Client()
        path = client.recovery_path(TASK)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(payload) if payload is not None else '{broken JSON')
        client.session.close()
        result = tool.execute({'action': 'collect', 'task_id': TASK})
    assert result['ok'] and len(result['data']['outputs']) == 3
    assert server['posts'] == 0
    assert any('/status/poll/' in item for item in server['gets'])
    assert sum('/result/' in item for item in server['gets']) == 1
    assert not path.exists()


def test_invalid_cache_is_removed_even_when_single_use_task_is_gone(server):
    server['poll_status'] = 404
    with config_scope('cloud', server['settings']):
        client = tool.Client()
        path = client.recovery_path(TASK)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(INVALID_RESULTS[0]))
        client.session.close()
        for _ in range(2):
            result = tool.execute({'action': 'collect', 'task_id': TASK})
            assert not result['ok'] and not result['data']['recovery_available']
            assert result['data']['task_id'] == TASK
            assert not path.exists()
    assert len(server['gets']) == 2 and all('/status/poll/' in item for item in server['gets'])
    assert server['posts'] == 0


def test_partial_conversion_cache_keeps_real_state_and_survives_storage_failure(server, monkeypatch):
    server['state'] = server['payload']['status'] = 'partial_success'
    server['payload']['errors'] = [{'message': 'one page failed'}]
    original = tool.StashFile.save_binary

    def fail_exports(self, content, filename, **kwargs):
        if filename != 'docling-task.json':
            raise OSError('fixture export failure')
        return original(self, content, filename, **kwargs)

    monkeypatch.setattr(tool.StashFile, 'save_binary', fail_exports)
    failed = convert(server)
    assert not failed['ok'] and failed['data']['recovery_available']
    before = list(server['gets'])
    original_space = tool.open_space
    monkeypatch.setattr(tool, 'open_space', lambda **kwargs: (_ for _ in ()).throw(OSError('fixture preflight')))
    with config_scope('cloud', server['settings']):
        failed_again = tool.execute({'action': 'collect', 'task_id': TASK})
        assert not failed_again['ok'] and failed_again['data']['recovery_available']
        assert 'saving outputs needs recovery' in failed_again['speech']
        monkeypatch.setattr(tool, 'open_space', original_space)
        monkeypatch.setattr(tool.StashFile, 'save_binary', original)
        server['poll_status'] = 404
        recovered = tool.execute({'action': 'collect', 'task_id': TASK})
    assert recovered['ok'] and recovered['data']['state'] == 'partial_success'
    assert recovered['data']['partial'] and recovered['data']['error_count'] == 1
    assert server['gets'] == before and server['posts'] == 1
