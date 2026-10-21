"""OpenCode V2 HTTP admission, execution, and result-boundary contracts.

Fixtures follow the official 2.1.0 OpenAPI and schema/session-event.ts. All
transport is mocked; these tests never contact a provider or a live server.
"""

import queue
import threading
from unittest.mock import MagicMock, patch

import pytest
import requests

from lib.opencode_client import OpenCodeClient


class Response:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'HTTP {self.status_code}')


def page(messages, cursor=None):
    return Response({'data': messages, 'cursor': {'next': cursor, 'previous': None}})


def user(message_id='msg_input'):
    return {'id': message_id, 'type': 'user', 'time': {'created': 100}, 'text': 'Build it'}


def assistant(text='Current answer', *, message_id='msg_answer', completed=True):
    time = {'created': 101}
    if completed:
        time['completed'] = 102
    return {
        'id': message_id, 'type': 'assistant', 'time': time,
        'content': [{'type': 'reasoning', 'text': 'PRIVATE REASONING'}, {'type': 'text', 'text': text}],
        'model': {'providerID': 'xai', 'id': 'fixture-model'}, 'finish': 'stop',
    }


def idle(outcome='succeeded', **extra):
    return {'id': 'msg_idle', 'type': 'idle', 'outcome': outcome, 'time': {'created': 103}, **extra}


def event(kind, data, *, version=1):
    return {
        'id': 'evt_fixture', 'type': kind, 'created': 100, 'data': data,
        'durable': {'aggregateID': data.get('sessionID', 'ses_123'), 'seq': 1, 'version': version},
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("lib.opencode_client.uuid.uuid4", lambda: MagicMock(hex="input"))
    client = OpenCodeClient.__new__(OpenCodeClient)
    client.base_url = 'http://opencode.test'
    client.timeout = 360
    client.task_timeout = 900
    client.auth = None
    client.default_provider_id = 'xai'
    client.default_model_id = 'fixture-model'
    client.active_session_id = 'ses_123'
    client.active_input_id = None
    client._pending_input_ids = {}
    client._cancelled_sessions = set()
    client.logger = MagicMock()
    return client


def test_prompt_admission_waits_before_collecting_completed_output(client):
    waiting = threading.Event()
    release = threading.Event()
    answer = {}

    def post(path, **kwargs):
        if path.endswith('/model'):
            assert kwargs['json_payload'] == {'model': {'providerID': 'xai', 'id': 'fixture-model'}}
            return Response(status=204)
        if path.endswith('/prompt'):
            assert kwargs['json_payload'] == {'id': 'msg_input', 'text': 'Build it', 'delivery': 'queue'}
            assert client._pending_input_ids['ses_123'] == ['msg_input']
            return Response({'data': {'id': 'msg_input', 'sessionID': 'ses_123', 'type': 'user', 'time': {'created': 100}, 'payload': {'text': 'Build it'}, 'delivery': 'queue'}})
        assert path == '/api/experimental/session/ses_123/wait'
        waiting.set()
        assert release.wait(timeout=2)
        return Response(status=204)

    def send():
        answer['result'] = client.send_message('ses_123', 'Build it')

    with patch.object(client, '_post', side_effect=post), \
         patch.object(client, '_get', return_value=page([idle(), assistant(), user()])) as get:
        worker = threading.Thread(target=send)
        worker.start()
        try:
            assert waiting.wait(timeout=2)
            assert not answer
            get.assert_not_called()
            assert client.active_input_id == 'msg_input'
        finally:
            release.set()
            worker.join(timeout=2)
    assert not worker.is_alive()
    assert answer['result']['parts'] == [{'type': 'text', 'text': 'Current answer'}]
    assert 'PRIVATE' not in str(answer['result'])


def test_synthetic_context_does_not_resume_or_switch_models(client):
    receipt = {'id': 'msg_input', 'type': 'synthetic', 'sessionID': 'ses_123', 'time': {'created': 99}, 'payload': {'text': 'context'}, 'delivery': 'queue'}
    with patch.object(client, '_post', return_value=Response({'data': receipt})) as post:
        assert client.send_message('ses_123', 'context', no_reply=True) == receipt
    post.assert_called_once_with('/api/session/ses_123/synthetic', json_payload={'id': 'msg_input', 'text': 'context', 'resume': False, 'delivery': 'queue'}, timeout=30)


@pytest.mark.parametrize('outcome', ['failed', 'interrupted'])
def test_unsuccessful_execution_rejects_prior_assistant_text(client, outcome):
    with patch.object(client, '_get', return_value=page([idle(outcome), assistant('Looks successful'), user()])):
        with pytest.raises(RuntimeError, match=outcome):
            client._collect_final_response('ses_123', 'msg_input')


def test_missing_prompt_receipt_never_reuses_a_previous_answer(client):
    with patch.object(client, '_get', return_value=page([idle(), assistant('Old answer'), user('msg_old')])):
        with pytest.raises(RuntimeError):
            client._collect_final_response('ses_123', 'msg_input')


def test_idle_after_previous_prompt_is_not_current_completion(client):
    with patch.object(client, '_get', return_value=page([assistant(), user(), idle(), assistant('Old answer')])):
        with pytest.raises(RuntimeError, match='completion'):
            client._collect_final_response('ses_123', 'msg_input')


@pytest.mark.parametrize('latest', [assistant(completed=False), assistant('  ')])
def test_requires_completed_assistant_with_public_text(client, latest):
    with patch.object(client, '_get', return_value=page([idle(), latest, user()])):
        with pytest.raises(RuntimeError, match='usable assistant'):
            client._collect_final_response('ses_123', 'msg_input')


def test_result_collection_follows_message_cursor_to_exact_input(client):
    with patch.object(client, '_get', side_effect=[page([idle(), assistant()], 'older-page'), page([user(), assistant('Previous answer')])]) as get:
        result = client._collect_final_response('ses_123', 'msg_input')
    assert result['parts'][0]['text'] == 'Current answer'
    assert get.call_args_list[0].kwargs['params'] == {'order': 'desc', 'limit': 100}
    assert get.call_args_list[1].kwargs['params'] == {'cursor': 'older-page', 'limit': 100}


def test_repeating_cursor_fails_without_reusing_unrelated_output(client):
    with patch.object(client, '_get', side_effect=[page([idle(), assistant()], 'same'), page([], 'same')]) as get:
        with pytest.raises(RuntimeError, match='could not be confirmed'):
            client._collect_final_response('ses_123', 'msg_input')
    assert get.call_count == 2


def test_prompt_receipt_must_be_user_input(client):
    with patch.object(client, '_post', side_effect=[Response(status=204), Response({'data': {'id': 'msg_old', 'type': 'assistant'}})]) as post:
        with pytest.raises(RuntimeError, match='receipt'):
            client.send_message('ses_123', 'Build it')
    assert post.call_count == 2


def test_wait_timeout_propagates_without_collecting_old_output(client):
    with patch.object(client, '_post', side_effect=[Response(status=204), Response({'data': user()}), requests.Timeout('deadline')]), \
         patch.object(client, '_collect_final_response') as collect:
        with pytest.raises(requests.Timeout):
            client.send_message('ses_123', 'Build it')
    collect.assert_not_called()


@pytest.mark.parametrize('version', ['1.19.0', '', 'garbage'])
def test_health_rejects_v1_or_unknown_server(client, version):
    with patch.object(client, '_get', return_value=Response({'version': version})):
        health = client.health_check()
    assert not health['healthy']
    assert health['status'] == 'incompatible'


def test_v2_health_accepts_server_info(client):
    with patch.object(client, '_get', return_value=Response({'version': '2.1.0', 'pid': 1, 'urls': [], 'paths': {'tmp': '/tmp'}})) as get:
        assert client.health_check()['healthy']
    get.assert_called_once_with('/api/info', timeout=5)


def test_v2_session_api_unwraps_metadata_and_message_envelopes(client):
    with patch.object(client, '_get', side_effect=[page([{'id': 'ses_123'}]), Response({'data': {'id': 'ses_123'}}), page([assistant()])]) as get:
        assert client.list_sessions() == [{'id': 'ses_123'}]
        assert client.get_session('ses_a/b')['id'] == 'ses_123'
        assert client.get_messages('ses_a/b')[0]['type'] == 'assistant'
    assert get.call_args_list[0].args[0] == '/api/session'
    assert get.call_args_list[1].args[0] == '/api/session/ses_a%2Fb'
    assert get.call_args_list[2].args[0] == '/api/session/ses_a%2Fb/message'


def test_malformed_v1_envelope_is_rejected(client):
    with patch.object(client, '_get', return_value=Response({'messages': []})):
        with pytest.raises(RuntimeError, match='response format'):
            client.get_messages('ses_123')


def test_native_event_data_routes_progress_and_filters_other_sessions():
    data = {'sessionID': 'ses_123', 'assistantMessageID': 'msg_answer', 'id': 'call_123', 'input': {'filePath': '/workspace/app.py', 'token': 'PRIVATE TOKEN'}, 'executed': True}
    progress = OpenCodeClient._normalize_progress_event(event('session.tool.called', data), 'ses_123')
    assert progress['phase'] == 'tool'
    assert progress['tool_status'] == 'running'
    assert 'PRIVATE TOKEN' not in str(progress)
    assert OpenCodeClient._normalize_progress_event(event('session.tool.called', data), 'ses_other') is None
    reasoning = event('session.reasoning.delta', {'sessionID': 'ses_123', 'assistantMessageID': 'msg_answer', 'ordinal': 0, 'delta': 'PRIVATE REASONING'})
    assert OpenCodeClient._normalize_progress_event(reasoning, 'ses_123') is None


@pytest.mark.parametrize('kind,data', [
    ('permission.asked', {'id': 'prm_123', 'sessionID': 'ses_123', 'action': 'bash', 'resources': ['PRIVATE COMMAND']}),
    ('form.created', {'form': {'id': 'form_123', 'sessionID': 'ses_123', 'title': 'Choose port', 'fields': [{'key': 'port', 'type': 'string'}]}}),
])
def test_native_blockers_remain_terminal_without_exposing_resource_payloads(kind, data):
    # Permission/form events are ephemeral (no durable envelope).
    progress = OpenCodeClient._normalize_progress_event({'id': 'evt_blocked', 'created': 1, 'type': kind, 'data': data}, 'ses_123')
    assert progress['terminal']
    assert progress['phase'] == 'blocked'
    assert 'PRIVATE COMMAND' not in str(progress)


@pytest.mark.parametrize('suffix,pending', [
    ('permission', {'id': 'prm_123', 'sessionID': 'ses_123', 'action': 'bash', 'resources': []}),
    ('form', {'id': 'form_123', 'sessionID': 'ses_123', 'title': 'Choose port', 'fields': [{'key': 'port', 'type': 'string'}]}),
])
def test_poll_recovers_missed_permissions_and_forms(client, suffix, pending):
    def get(path, **kwargs):
        return page([pending] if path.endswith('/' + suffix) else [])
    with patch.object(client, '_get', side_effect=get) as get_mock:
        progress = client._poll_session_progress('ses_123')
    assert progress['terminal']
    assert progress['source'] == 'poll'
    assert any(call.args[0] == f'/api/session/ses_123/{suffix}' for call in get_mock.call_args_list)


def test_poll_does_not_replay_tools_before_the_latest_idle(client):
    prior = assistant('old')
    prior['content'] = [{'type': 'tool', 'id': 'call_old', 'name': 'bash', 'state': {'status': 'completed', 'input': {}, 'content': [{'type': 'text', 'text': 'old'}]}, 'time': {'created': 1}}]
    with patch.object(client, '_get', return_value=page([])), \
         patch.object(client, 'get_messages', return_value=[idle(), prior]):
        assert client._poll_session_progress('ses_123') is None


def test_disconnected_supervisor_aborts_a_polled_form_without_a_ui_callback(client):
    release_request = threading.Event()
    observed = []

    def disconnected(events, stop, ready):
        ready.set()
        events.put({'_monitor_error': 'offline'})

    def send(*args):
        assert release_request.wait(timeout=2)
        return {'parts': []}

    def abort(session_id):
        release_request.set()
        return True

    blocker = {'session_id': 'ses_123', 'source': 'poll', 'phase': 'blocked', 'status': 'OpenCode needs an answer', 'terminal': True, 'event_type': 'jarvis.poll.form'}
    with patch.object(client, '_stream_events', side_effect=disconnected), \
         patch.object(client, 'send_message', side_effect=send), \
         patch.object(client, '_poll_session_progress', return_value=blocker), \
         patch.object(client, 'abort_session', side_effect=abort) as aborted:
        with pytest.raises(RuntimeError, match='needs an answer'):
            client._send_message_with_progress(session_id='ses_123', message='Build', provider_id='xai', model_id='fixture-model', progress_callback=observed.append)
    aborted.assert_called_once_with('ses_123')
    assert observed[0]['terminal']


def test_cancel_interrupts_without_resume_and_removes_only_our_pending_inputs(client):
    client.auth = ('opencode', 'fixture-password')
    client._pending_input_ids = {'ses_123': ['msg_context', 'msg_input'], 'ses_other': ['msg_other']}
    with patch.object(client, '_post', return_value=Response(status=204)) as post, \
         patch('lib.opencode_client.requests.delete', side_effect=[Response(status=404), Response(status=204)]) as delete:
        assert client.abort_session('ses_123')
    post.assert_called_once_with('/api/session/ses_123/interrupt?resume=false', timeout=5)
    assert [call.args[0] for call in delete.call_args_list] == ['http://opencode.test/api/session/ses_123/inbox/msg_context', 'http://opencode.test/api/session/ses_123/inbox/msg_input']
    assert all(call.kwargs['auth'] == ('opencode', 'fixture-password') for call in delete.call_args_list)
    assert client._pending_input_ids == {'ses_other': ['msg_other']}


def test_execution_is_supervised_even_without_a_progress_listener(client):
    with patch.object(client, 'create_session', return_value={'id': 'ses_123'}), \
         patch.object(client, 'send_message', return_value={'id': 'msg_context'}), \
         patch.object(client, '_send_message_with_progress', side_effect=RuntimeError('OpenCode needs an answer')) as supervised:
        result = client.execute_task('Build it', progress_callback=None)
    assert not result['ok']
    assert 'needs an answer' in result['error']
    supervised.assert_called_once()


def test_v2_rejects_an_unsupported_custom_basic_auth_username():
    values = {'OPENCODE_PROVIDER': 'xai', 'OPENCODE_MODEL': 'fixture-model', 'OPENCODE_SERVER_USERNAME': 'custom-user', 'OPENCODE_SERVER_PASSWORD': 'fixture-password'}
    with patch('config_loader.get_config_value', side_effect=lambda key, default='': values.get(key, default)), \
         patch('lib.opencode_client.OpenCodeLogger', return_value=MagicMock()), \
         patch.object(OpenCodeClient, '_verify_connection') as verify:
        with pytest.raises(ValueError, match='opencode'):
            OpenCodeClient('http://opencode.test')
    verify.assert_not_called()


@pytest.mark.parametrize('no_reply', [False, True])
def test_timeout_before_receipt_retains_known_input_for_cancel(client, no_reply):
    def post(path, **kwargs):
        if path.endswith('/model'):
            return Response(status=204)
        assert kwargs['json_payload']['id'] == 'msg_input'
        assert client._pending_input_ids['ses_123'] == ['msg_input']
        raise requests.Timeout('response lost after admission')
    with patch.object(client, '_post', side_effect=post):
        with pytest.raises(requests.Timeout):
            client.send_message('ses_123', 'Build it', no_reply=no_reply)
    with patch.object(client, '_post', return_value=Response(status=204)), \
         patch('lib.opencode_client.requests.delete', return_value=Response(status=204)) as delete:
        assert client.abort_session('ses_123')
    assert delete.call_args.args[0].endswith('/inbox/msg_input')


def test_receipt_id_mismatch_cannot_trigger_a_wait_or_reuse_an_answer(client):
    with patch.object(client, '_post', side_effect=[Response(status=204), Response({'data': user('msg_other')})]) as post, \
         patch.object(client, '_collect_final_response') as collect:
        with pytest.raises(RuntimeError, match='receipt'):
            client.send_message('ses_123', 'Build it')
    assert post.call_count == 2
    collect.assert_not_called()


def test_final_result_excludes_provider_native_replay_metadata(client):
    message = assistant()
    message['native'] = {'private': 'PROVIDER REPLAY'}
    message['content'][1]['native'] = {'private': 'CONTENT REPLAY'}
    with patch.object(client, '_get', return_value=page([idle(), message, user()])):
        result = client._collect_final_response('ses_123', 'msg_input')
    assert result['parts'] == [{'type': 'text', 'text': 'Current answer'}]
    assert 'REPLAY' not in str(result)
    assert 'PRIVATE REASONING' not in str(result)


def test_cancellation_during_model_switch_prevents_later_prompt_admission(client):
    inflight, release = threading.Event(), threading.Event()
    errors = []

    def post(path, **kwargs):
        if path.endswith('/model'):
            inflight.set()
            assert release.wait(timeout=2)
        return Response(status=204)

    def send():
        try:
            client.send_message('ses_123', 'Build it')
        except Exception as error:
            errors.append(error)

    with patch.object(client, '_post', side_effect=post) as posts:
        worker = threading.Thread(target=send)
        worker.start()
        try:
            assert inflight.wait(timeout=2)
            assert client.abort_session('ses_123')
        finally:
            release.set()
            worker.join(timeout=2)
    assert not worker.is_alive()
    assert len(errors) == 1 and 'cancelled' in str(errors[0])
    assert not any(call.args[0].endswith('/prompt') for call in posts.call_args_list)
    assert not any(call.args[0].endswith('/wait') for call in posts.call_args_list)


@pytest.mark.parametrize('no_reply', [False, True])
@pytest.mark.parametrize('response_lost', [False, True])
def test_cancellation_reconciles_a_late_admission_even_if_response_is_lost(client, no_reply, response_lost):
    inflight, release = threading.Event(), threading.Event()
    errors = []
    admission_suffix = '/synthetic' if no_reply else '/prompt'

    def post(path, **kwargs):
        if path.endswith(admission_suffix):
            inflight.set()
            assert release.wait(timeout=2)
            # The server admitted this input only AFTER the initial cancellation
            # DELETE was already processed as a no-op. The response may be lost.
            if response_lost:
                raise requests.Timeout('admitted input but response lost')
            return Response({'data': {'id': kwargs['json_payload']['id'], 'type': 'synthetic' if no_reply else 'user'}})
        return Response(status=204)

    def send():
        try:
            client.send_message('ses_123', 'Build it', no_reply=no_reply)
        except Exception as error:
            errors.append(error)

    with patch.object(client, '_post', side_effect=post) as posts, \
         patch('lib.opencode_client.requests.delete', return_value=Response(status=204)) as deletes:
        worker = threading.Thread(target=send)
        worker.start()
        try:
            assert inflight.wait(timeout=2)
            assert client.abort_session('ses_123')
        finally:
            release.set()
            worker.join(timeout=2)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert deletes.call_count == 2
    assert all(call.args[0].endswith('/inbox/msg_input') for call in deletes.call_args_list)
    assert not any(call.args[0].endswith('/wait') for call in posts.call_args_list)


def test_comment_only_v2_keepalives_observe_cancellation_and_close_stream(client):
    stop, ready = threading.Event(), threading.Event()
    events = queue.Queue()

    class HeartbeatResponse:
        closed = False
        read_past_cancel = False

        def raise_for_status(self):
            pass

        def iter_lines(self, *, chunk_size, decode_unicode):
            assert chunk_size == 1
            assert decode_unicode
            yield ': heartbeat'
            yield ''
            stop.set()
            yield ': heartbeat'
            self.read_past_cancel = True
            yield ''

        def close(self):
            self.closed = True

    response = HeartbeatResponse()
    with patch.object(client, '_get', return_value=response) as get:
        client._stream_events(events, stop, ready)
    assert ready.is_set()
    assert response.closed
    assert not response.read_past_cancel
    assert events.get_nowait() == {'_monitor_connected': True}
    assert events.empty()
    assert get.call_count == 1


def test_connection_failure_after_admission_reconciles_our_pending_work(client):
    def connection_failure(**kwargs):
        client._pending_input_ids['ses_123'] = ['msg_input']
        raise requests.ConnectionError('connection lost after prompt admission')

    with patch.object(client, 'create_session', return_value={'id': 'ses_123'}), \
         patch.object(client, 'send_message', return_value={'id': 'msg_context'}), \
         patch.object(client, '_send_message_with_progress', side_effect=connection_failure), \
         patch.object(client, 'abort_session', return_value=True) as abort:
        result = client.execute_task('Build it')
    assert not result['ok']
    assert 'connection lost after prompt admission' in result['error']
    abort.assert_called_once_with('ses_123')


def test_session_listing_reads_beyond_first_fifty_and_preserves_cursor_order(client):
    first = [{'id': f'ses_{index}'} for index in range(100, 50, -1)]
    second = [{'id': f'ses_{index}'} for index in range(50, 0, -1)]
    third = [{'id': 'ses_oldest'}]
    with patch.object(client, '_get', side_effect=[page(first, 'next/one?'), page(second, 'next-two'), page(third)]) as get:
        assert client.list_sessions() == first + second + third
    assert [call.kwargs['params'] for call in get.call_args_list] == [
        {'order': 'desc', 'limit': 50},
        {'cursor': 'next/one?', 'limit': 50},
        {'cursor': 'next-two', 'limit': 50},
    ]
    assert all(call.args == ('/api/session',) for call in get.call_args_list)


@pytest.mark.parametrize('cursors', [['same', 'same'], ['first', 'second', 'first']])
def test_session_listing_rejects_cursor_cycles_without_returning_partial_history(client, cursors):
    with patch.object(client, '_get', side_effect=[page([{'id': f'ses_{index}'}], cursor) for index, cursor in enumerate(cursors)]) as get:
        with pytest.raises(RuntimeError, match='pagination cursor'):
            client.list_sessions()
    assert get.call_count == len(cursors)


@pytest.mark.parametrize('pagination', [None, [], {'next': ''}, {'next': 123}, {'next': {'cursor': 'invalid'}}])
def test_session_listing_rejects_malformed_cursor_instead_of_truncating_history(client, pagination):
    with patch.object(client, '_get', return_value=Response({'data': [{'id': 'ses_newest'}], 'cursor': pagination})) as get:
        with pytest.raises(RuntimeError, match='pagination'):
            client.list_sessions()
    get.assert_called_once()


def test_session_listing_propagates_later_page_failure(client):
    with patch.object(client, '_get', side_effect=[page([{'id': 'ses_newest'}], 'older'), Response(status=503)]):
        with pytest.raises(requests.HTTPError):
            client.list_sessions()


def test_streaming_tool_poll_reports_activity_without_partial_arguments(client):
    message = assistant()
    message['content'] = [{
        'type': 'tool', 'id': 'call_streaming', 'name': 'bash',
        'state': {'status': 'streaming', 'input': '{"command":"PRIVATE PARTIAL COMMAND'},
        'time': {'created': 100},
    }]
    with patch.object(client, '_get', return_value=page([])), \
         patch.object(client, 'get_messages', return_value=[message]):
        progress = client._poll_session_progress('ses_123')
    assert progress['phase'] == 'tool'
    assert progress['tool_status'] == 'streaming'
    assert progress['source'] == 'poll'
    assert progress['opencode_tool'] == 'bash'
    assert 'Running a command' in progress['status']
    assert 'PRIVATE' not in str(progress)


def test_task_prompt_explains_service_host_and_headless_gui_validation(client):
    with patch.object(client, 'create_session', return_value={'id': 'ses_123'}), \
         patch.object(client, 'send_message', return_value={}) as send, \
         patch.object(client, '_send_message_with_progress', return_value=({'parts': [{'type': 'text', 'text': 'done'}]}, 'none')):
        result = client.execute_task('Create a GUI game')
    assert result['ok']
    prompt = send.call_args_list[0].kwargs['message']
    assert 'runs on its service host' in prompt
    assert 'Inspect the operating system, distribution, and available tools' in prompt
    assert 'headless unless the task explicitly provides a graphical display' in prompt
    assert 'headless compilation, import checks, or self-tests' in prompt
    assert 'graphical run belongs on a machine with a display' in prompt
    assert 'Ubuntu 24' not in prompt


def test_v2_tool_sequence_reconstructs_safe_command_context_without_claiming_task_completion():
    context = {}
    base = {'sessionID': 'ses_123', 'assistantMessageID': 'msg_answer', 'id': 'call_shell'}
    OpenCodeClient._normalize_progress_event(event('session.tool.input.started', {**base, 'name': 'shell'}), 'ses_123', context)
    called = OpenCodeClient._normalize_progress_event(event('session.tool.called', {
        **base, 'input': {'command': 'python3 -m pytest tests/test_game.py -q', 'workdir': '/workspace'}, 'executed': True,
    }), 'ses_123', context)
    completed = OpenCodeClient._normalize_progress_event(event('session.tool.success', {
        **base, 'content': [{'type': 'text', 'text': 'PRIVATE OUTPUT'}], 'executed': True,
        'metadata': {'status': 'completed', 'exit': 0},
    }, version=2), 'ses_123', context)
    assert called['opencode_tool'] == completed['opencode_tool'] == 'shell'
    assert 'python3 -m pytest tests/test_game.py -q' in called['status']
    assert 'python3 -m pytest tests/test_game.py -q' in completed['status']
    assert 'step complete' in completed['status'] and 'continuing' in completed['status']
    assert 'OpenCode finished' not in completed['status']
    assert not completed.get('terminal')
    assert 'PRIVATE OUTPUT' not in str(completed)
    assert 'input' not in str(context) and 'PRIVATE OUTPUT' not in str(context)
    heartbeat = OpenCodeClient._heartbeat_status(completed, 45)
    assert heartbeat == 'OpenCode is working on the next step (45s elapsed)'
    assert 'pytest' not in heartbeat


def test_v2_completed_shell_with_nonzero_exit_reports_step_issue_while_task_continues():
    progress = OpenCodeClient._normalize_progress_event(event('session.tool.success', {
        'sessionID': 'ses_123', 'assistantMessageID': 'msg_answer', 'id': 'call_shell',
        'executed': True, 'content': [{'type': 'text', 'text': 'PRIVATE TRACEBACK'}],
        'metadata': {'status': 'completed', 'exit': 1},
    }, version=2), 'ses_123')
    assert 'exited with status 1' in progress['status']
    assert 'task continues' in progress['status']
    assert 'PRIVATE' not in str(progress)
    assert not progress.get('terminal')


def test_v2_tool_success_background_metadata_remains_running():
    context = {}
    base = {'sessionID': 'ses_123', 'assistantMessageID': 'msg_answer', 'id': 'call_shell'}
    OpenCodeClient._normalize_progress_event(event('session.tool.called', {
        **base, 'input': {'command': 'python3 -m http.server 8080', 'background': True}, 'executed': True,
    }), 'ses_123', context)
    progress = OpenCodeClient._normalize_progress_event(event('session.tool.success', {
        **base, 'executed': True, 'content': [{'type': 'text', 'text': 'PRIVATE OUTPUT'}],
        'metadata': {'status': 'running', 'shellID': 'sh_example'},
    }, version=2), 'ses_123', context)
    assert progress['tool_status'] == 'running'
    assert 'running in background' in progress['status']
    assert 'python3 -m http.server 8080' in progress['status']
    assert 'step complete' not in progress['status']


def test_v2_file_context_is_scoped_to_call_and_assistant_and_cache_is_bounded():
    context = {}
    for assistant_id, target in [('msg_one', '/workspace/one.py'), ('msg_two', '/workspace/two.py')]:
        base = {'sessionID': 'ses_123', 'assistantMessageID': assistant_id, 'id': 'same_call_id'}
        OpenCodeClient._normalize_progress_event(event('session.tool.input.started', {**base, 'name': 'write'}), 'ses_123', context)
        OpenCodeClient._normalize_progress_event(event('session.tool.called', {
            **base, 'input': {'path': target, 'content': 'PRIVATE FILE CONTENT'}, 'executed': True,
        }), 'ses_123', context)
    progress = OpenCodeClient._normalize_progress_event(event('session.tool.success', {
        'sessionID': 'ses_123', 'assistantMessageID': 'msg_one', 'id': 'same_call_id',
        'executed': True, 'content': [{'type': 'text', 'text': 'PRIVATE OUTPUT'}],
    }, version=2), 'ses_123', context)
    assert 'one.py' in progress['status'] and 'two.py' not in progress['status']
    assert 'PRIVATE' not in str(context)
    for index in range(OpenCodeClient.MAX_PROGRESS_TOOL_CONTEXT + 2):
        OpenCodeClient._normalize_progress_event(event('session.tool.input.started', {
            'sessionID': 'ses_123', 'assistantMessageID': 'msg_extra', 'id': f'call_{index}', 'name': 'read',
        }), 'ses_123', context)
    assert len(context) == OpenCodeClient.MAX_PROGRESS_TOOL_CONTEXT
    before = dict(context)
    assert OpenCodeClient._normalize_progress_event(event('session.tool.called', {
        'sessionID': 'ses_other', 'assistantMessageID': 'msg_extra', 'id': 'call_0', 'input': {'command': 'PRIVATE'}, 'executed': True,
    }), 'ses_123', context) is None
    assert context == before


def test_command_context_redacts_credentials_urls_and_embedded_code():
    cleaned = OpenCodeClient._command_progress_text(
        "API_KEY='private env value' curl -u 'private-user:private-pass' --token \"private cli value\" "
        "https://user:password@example.test/path?token=private-query#private-fragment"
    )
    for secret in ['private env value', 'private-user', 'private-pass', 'private cli value', 'user:password', 'private-query', 'private-fragment']:
        assert secret not in cleaned
    assert 'curl' in cleaned and '[redacted]' in cleaned
    assert len(cleaned) <= 140
    assert 'PRIVATE CODE' not in OpenCodeClient._command_progress_text('python3 -c "print(\'PRIVATE CODE\')"')
    assert 'PRIVATE CODE' not in OpenCodeClient._command_progress_text("python3 -c $'print(\"PRIVATE CODE\")'")
    assert 'PRIVATE CODE' not in OpenCodeClient._command_progress_text("node --eval='console.log(\"PRIVATE CODE\")'")
    assert 'PRIVATE BODY' not in OpenCodeClient._command_progress_text("python3 - <<'PY'\nPRIVATE BODY\nPY")


def test_poll_tool_metadata_uses_same_context_and_step_completion_wording(client):
    message = assistant()
    message['content'] = [{
        'type': 'tool', 'id': 'call_shell', 'name': 'shell', 'time': {'created': 1},
        'state': {'status': 'completed', 'input': {'command': 'python3 --version'},
                  'content': [{'type': 'text', 'text': 'PRIVATE OUTPUT'}],
                  'metadata': {'status': 'completed', 'exit': 0}},
    }]
    with patch.object(client, '_get', return_value=page([])), patch.object(client, 'get_messages', return_value=[message]):
        progress = client._poll_session_progress('ses_123')
    assert progress['call_id'] == 'call_shell'
    assert progress['assistant_message_id'] == message['id']
    assert 'python3 --version' in progress['status']
    assert 'step complete' in progress['status'] and 'continuing' in progress['status']
    assert 'PRIVATE' not in str(progress)


@pytest.mark.parametrize('polled_state', ['completed', 'running'])
def test_sse_and_poll_do_not_replay_completed_calls_after_heartbeats(client, polled_state):
    client.HEARTBEAT_INTERVAL_SECONDS = 0
    client.HEALTHY_POLL_INTERVAL_SECONDS = 0
    client.DEGRADED_POLL_INTERVAL_SECONDS = 0
    release = threading.Event()
    completed_seen = threading.Event()
    completed_polled = threading.Event()
    observed = []
    base = {'sessionID': 'ses_123', 'assistantMessageID': 'msg_answer', 'id': 'call_shell'}
    state = {
        'status': polled_state, 'input': {'command': 'python3 --version'},
        'metadata': {'status': 'completed', 'exit': 0} if polled_state == 'completed' else {},
    }
    message = assistant()
    message['content'] = [{'type': 'tool', 'id': 'call_shell', 'name': 'shell', 'state': state, 'time': {'created': 1}}]

    def stream(events, stop, ready):
        events.put({'_monitor_connected': True})
        events.put(event('session.tool.input.started', {**base, 'name': 'shell'}))
        events.put(event('session.tool.called', {**base, 'input': {'command': 'python3 --version'}, 'executed': True}))
        events.put(event('session.tool.success', {**base, 'executed': True, 'content': [{'type': 'text', 'text': 'PRIVATE OUTPUT'}], 'metadata': {'status': 'completed', 'exit': 0}}, version=2))
        ready.set()

    def messages(session_id):
        if completed_seen.is_set():
            completed_polled.set()
            return [message]
        return []

    def observe(progress):
        observed.append(progress)
        if progress.get('tool_status') == 'completed':
            completed_seen.set()
        if progress['phase'] == 'heartbeat' and completed_polled.is_set():
            release.set()

    def final(*args):
        assert release.wait(timeout=2)
        return {'parts': [{'type': 'text', 'text': 'Task final answer'}]}

    with patch.object(client, '_stream_events', side_effect=stream), \
         patch.object(client, 'send_message', side_effect=final), \
         patch.object(client, '_get', return_value=page([])), \
         patch.object(client, 'get_messages', side_effect=messages):
        result, transport = client._send_message_with_progress(session_id='ses_123', message='Build', provider_id='xai', model_id='fixture-model', progress_callback=observe)
    assert result['parts'][0]['text'] == 'Task final answer'
    assert transport == 'sse+poll'
    assert len([progress for progress in observed if progress.get('tool_status') == 'completed']) == 1
    completion_index = next(index for index, progress in enumerate(observed) if progress.get('tool_status') == 'completed')
    after_completion = observed[completion_index + 1:]
    assert after_completion and all(progress['phase'] == 'heartbeat' for progress in after_completion)
    assert all('working on the next step' in progress['status'] for progress in after_completion)
    assert all('python3' not in progress['status'] for progress in after_completion)


@pytest.mark.parametrize('authorization', [
    'Authorization: Basic cHJpdmF0ZS1jcmVkZW50aWFs',
    'Authorization: Bearer private-bearer-token',
    'Authorization: CustomScheme private-custom-token',
])
def test_progress_redacts_complete_authorization_scheme_and_credential(authorization):
    cleaned = OpenCodeClient._clean_progress_text(authorization, 300)
    assert cleaned == 'Authorization: [redacted]'
    command = OpenCodeClient._command_progress_text(f'curl -H "{authorization}" https://example.invalid/api')
    assert 'cHJpdmF0ZS1jcmVkZW50aWFs' not in command
    assert 'private-' not in command
    assert 'curl' in command and 'https://example.invalid/api' in command


@pytest.mark.parametrize('payload', [
    '-H "Cookie: PRIVATE_COOKIE"',
    '--header "X-Custom-Auth: PRIVATE_AUTH"',
    "-H'X-Custom-Auth: PRIVATE_AUTH'",
    '--header="X-Custom-Auth: PRIVATE_AUTH"',
    '-H"X-Custom-Auth: PRIVATE_AUTH""PRIVATE_TRAILING_AUTH"',
    '-b "session=PRIVATE_COOKIE"',
    '--cookie="session=PRIVATE_COOKIE"',
    '-d \'{"value":"PRIVATE_BODY"}\'',
    '--data-raw=PRIVATE_BODY',
    '--data-binary PRIVATE_BODY',
    '--data-urlencode PRIVATE_BODY',
    '--json \'{"token":"PRIVATE_BODY"}\'',
    '-F "field=PRIVATE_FORM"',
    '--form-string="field=PRIVATE_FORM"',
    '--user=alice:PRIVATE_PASSWORD',
    '-ualice:PRIVATE_PASSWORD',
    '--proxy-user=alice:PRIVATE_PASSWORD',
])
def test_command_preview_omits_headers_cookies_payloads_and_user_credentials(payload):
    preview = OpenCodeClient._command_progress_text(f'curl {payload} https://example.invalid/api')
    assert 'PRIVATE_' not in preview
    assert 'curl' in preview and 'https://example.invalid/api' in preview
    assert '[redacted]' in preview


@pytest.mark.parametrize('command', [
    'bash -lc "echo PRIVATE_INLINE_CODE"',
    "bash -lc'echo PRIVATE_INLINE_CODE'",
    'sh -ec "echo PRIVATE_INLINE_CODE"',
    'python3 -Ic "print(\'PRIVATE_INLINE_CODE\')"',
    'perl -ne \'print "PRIVATE_INLINE_CODE"\'',
    'node --eval="console.log(\'PRIVATE_INLINE_CODE\')"',
    'cmd.exe /c "echo PRIVATE_INLINE_CODE"',
    'CMD.EXE /C "echo PRIVATE_INLINE_CODE"',
])
def test_command_preview_omits_inline_code_for_combined_interpreter_flags(command):
    preview = OpenCodeClient._command_progress_text(command)
    assert 'PRIVATE_INLINE_CODE' not in preview
    assert '[inline code]' in preview


def test_malformed_or_multiline_quoted_command_omits_unparsed_arguments():
    preview = OpenCodeClient._command_progress_text('curl -H "X-Auth: PRIVATE_AUTH\nPRIVATE_BODY" https://example.invalid')
    assert preview == 'curl [arguments omitted]'


def test_legacy_tool_and_idle_events_do_not_announce_task_completion():
    tool = OpenCodeClient._normalize_progress_event({'type': 'session.next.tool.success', 'properties': {'sessionID': 'ses_123'}}, 'ses_123')
    idle_progress = OpenCodeClient._normalize_progress_event({'type': 'session.idle', 'properties': {'sessionID': 'ses_123'}}, 'ses_123')
    assert tool['status'] == 'OpenCode step complete — continuing'
    assert idle_progress['status'] == 'OpenCode is preparing the task result'
    assert tool['phase'] == 'tool' and idle_progress['phase'] == 'finishing'
    assert not tool.get('terminal') and not idle_progress.get('terminal')
