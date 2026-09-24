"""Mixed-source chat journey with real temporary uploads/storage and mocked providers."""
from __future__ import annotations

import io
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from flask import Flask, request
from server_package_utils import load_server_package
from werkzeug.datastructures import FileStorage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
sys.path.insert(0, str(ROOT / 'orchestrator'))
load_server_package('jarvis_bundle_chat_test', ROOT / 'jarvis-web/server')

from jarvis_bundle_chat_test import config as web_config  # noqa: E402
from jarvis_bundle_chat_test.services import (  # noqa: E402
    conversation_store,
    pdf_upload,
    text_upload,
)
from jarvis_bundle_chat_test.sockets import chat  # noqa: E402


class Socket:
    def __init__(self):
        self.handlers = {}
        self.events = []

    def on(self, event):
        def register(fn):
            self.handlers[event] = fn
            return fn
        return register

    def emit(self, event, data, **kwargs):
        self.events.append((event, data, kwargs))


@pytest.fixture
def journey(tmp_path, monkeypatch, request):
    import config_loader
    import orchestrator_v2
    from lib.background_tasks import store as task_store

    # All ConversationStore instances in this journey, including recovery
    # instances, must use disposable task storage instead of the live install.
    monkeypatch.setattr(task_store, 'default_store_path', lambda: tmp_path / 'tasks.db')

    monkeypatch.setenv('STASH_DIR', str(tmp_path / 'stash'))
    monkeypatch.delenv('JARVIS_OVERRIDE_STASH_DIR', raising=False)
    monkeypatch.setattr(config_loader, '_load_mode_config', lambda mode: {})
    monkeypatch.setattr(web_config, 'load_web_config', lambda: {})
    monkeypatch.setattr(web_config, 'get_web_setting', lambda key, default=None: (
        False if key in ('ui.progress_events', 'audio.tts_enabled') else default
    ))
    store = conversation_store.ConversationStore(tmp_path / 'conversations')
    monkeypatch.setattr(conversation_store, 'get_conversation_store', lambda: store)
    socket = Socket()
    monkeypatch.setattr(chat, 'emit', socket.emit)
    handler = chat.ChatHandler(socket)
    request.addfinalizer(lambda: [lease.release() for lease in handler.runs.leases.values()])
    handler.sessions['client'] = {'mode': 'cloud'}
    monkeypatch.setattr(handler, '_join_conversation_room', lambda *args: None)
    monkeypatch.setattr(handler, '_get_completion_guard_config', lambda mode: {'enabled': False})
    monkeypatch.setattr(handler, '_compute_effective_evidence', lambda *args: None)
    monkeypatch.setattr(handler, '_is_user_reaction_eligible', lambda *args, **kwargs: False)
    monkeypatch.setattr(handler, '_hydrate_uploaded_image_payload', lambda payload, **kwargs: None)
    captured = []
    monkeypatch.setattr(handler, '_start_blocking_task', lambda target, *args, **kwargs: captured.append((target, args)))
    routes = []
    instances = []
    provider_result = {'ok': True, 'speech': 'Compared the supplied sources.', 'data': {}, 'tools_used': []}

    class Orchestrator:
        def __init__(self, **kwargs):
            self.router = SimpleNamespace(provider_type='test', model_name='test-model')
            self.cancel_check = None
            instances.append(self)

        def set_status_callback(self, fn): pass
        def set_progress_callback(self, fn): pass
        def set_web_conversation_id(self, value): pass
        def set_reflection_queue_enabled(self, enabled): pass
        def set_cancel_check(self, fn): self.cancel_check = fn

        def process(self, prompt, **kwargs):
            routes.append((prompt, kwargs))
            import copy
            return copy.deepcopy(provider_result)

    monkeypatch.setattr(orchestrator_v2, 'Orchestrator', Orchestrator)
    app = Flask(__name__)

    def send(**payload):
        with app.test_request_context('/') as context:
            context.request.sid = 'client'
            socket.handlers['chat:send']({'message': 'Compare these sources.', 'mode': 'cloud', **payload})

    def process():
        target, args = captured.pop(0)
        target(*args)

    def pdf(text='Document evidence', name='source.pdf'):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 72), text)
            payload = doc.tobytes()
        return pdf_upload.save_pdf_upload(
            FileStorage(io.BytesIO(payload), filename=name, content_type='application/pdf'), str(uuid.uuid4())
        )[0]

    return SimpleNamespace(handler=handler, socket=socket, store=store, routes=routes,
                           instances=instances, send=send, process=process, pending=captured,
                           pdf=pdf, tmp=tmp_path, provider_result=provider_result)


def note(content='Text evidence', name='note.txt'):
    return text_upload.ingest_text_context({'name': name, 'content': content})


def image():
    return {'action': 'analyze', 'images': [{'base64': 'fake-pixels', 'url': '/data/uploads/image.jpg', 'filename': 'photo.jpg'}]}


def test_two_pdfs_and_text_are_saved_routed_and_restored_in_order(journey):
    sources = [journey.pdf('First version'), note('Budget is 120'), journey.pdf('Second version')]
    journey.send(attachments=sources)
    assert len(journey.pending) == 1
    journey.process()
    assert len(journey.routes) == 1
    prompt, kwargs = journey.routes[0]
    positions = [prompt.index(source['stash_ref']) for source in sources]
    assert positions == sorted(positions)
    assert 'Source 3: source.pdf' in prompt
    assert 'Budget is 120' in prompt
    assert 'filenames and metadata are not evidence of contents' in prompt
    assert kwargs['vision_pre_analyzed'] is False
    assert journey.instances[0].cancel_check is not None  # also when progress UI is disabled

    conversation_id = journey.handler.sessions['client']['conversation_id']
    restored = conversation_store.ConversationStore(journey.tmp / 'conversations')
    conversation = restored.get_conversation(conversation_id)
    assert [source['stash_ref'] for source in conversation['messages'][0]['data']['attachments']] == [source['stash_ref'] for source in sources]
    journey.send(message='How does the second PDF differ?', conversation_id=conversation_id)
    journey.process()
    history = journey.routes[-1][1]['conversation_history']
    assert all(source['stash_ref'] in history[0]['attachment_context'] for source in sources)
    assert 'Budget is 120' in history[0]['attachment_context']


def test_denied_web_tool_saves_partial_result_for_followup(journey, monkeypatch):
    """A real Web run pauses, stops its sequence, and persists prior data."""
    import threading
    import time
    import orchestrator_v2

    orchestrator = orchestrator_v2.Orchestrator
    histories = []
    monkeypatch.setattr(journey.handler, '_should_prompt_completion_guard', lambda *_: True)
    monkeypatch.setattr(journey.handler, '_should_auto_evaluate_completion_guard', lambda *_: True)
    monkeypatch.setattr(orchestrator, 'set_tool_approval_callback',
                        lambda self, callback: setattr(self, 'approval_callback', callback), raising=False)

    def process(self, _prompt, **kwargs):
        histories.append(kwargs['conversation_history'])
        if len(histories) == 1:
            decision = self.approval_callback(
                'api_call', {'url': 'https://example.test/path?token=private', 'method': 'GET'},
                {'network': True, 'auto_approve': False}, 0)
            assert decision == 'denied'
            return {'ok': True, 'speech': 'Stopped before running api_call. Earlier lookup is saved.',
                    'raw_llm_response': 'Stopped before running api_call. Earlier lookup is saved.',
                    'data': {'safe_read': {'title': 'Earlier result', 'url': 'https://example.test/source'}},
                    'tools_used': ['safe_read'], 'cancelled': True,
                    'approval_outcome': {'tool': 'api_call', 'decision': decision}}
        return {'ok': True, 'speech': 'The earlier result is available.', 'data': {}, 'tools_used': []}

    monkeypatch.setattr(orchestrator, 'process', process)
    journey.send(message='Read, then call the API')
    conversation_id = journey.handler.sessions['client']['conversation_id']
    worker = threading.Thread(target=journey.process, daemon=True)
    worker.start()
    deadline = time.monotonic() + 2
    while not journey.handler.runs.active[conversation_id].get('approval') and time.monotonic() < deadline:
        time.sleep(0.01)
    pending = journey.handler.runs.active[conversation_id]['approval']
    assert pending['preview']['url'] == 'https://example.test/path'
    with Flask(__name__).test_request_context('/') as context:
        context.request.sid = 'client'
        journey.socket.handlers['tool:approval_decide']({
            'approval_id': pending['approval_id'], 'conversation_id': conversation_id,
            'message_id': pending['message_id'], 'approved': False,
        })
    worker.join(3)
    assert not worker.is_alive()
    saved = journey.store.get_conversation(conversation_id)
    assert saved['messages'][-1]['data']['safe_read']['title'] == 'Earlier result'
    assert saved['messages'][-1]['data']['_approval_outcome']['decision'] == 'denied'
    assert saved['messages'][-1]['data']['cancelled'] is True
    response = next(payload for event, payload, _ in journey.socket.events
                    if event == 'chat:response' and payload['message_id'] == pending['message_id'])
    assert response['completion_guard']['prompt_user'] is False
    assert not journey.pending
    journey.send(message='Tell me about the earlier result', conversation_id=conversation_id)
    journey.process()
    assert histories[1][-1]['tool_results']['safe_read']['title'] == 'Earlier result'


def test_legacy_text_payload_is_durable_and_chat_only_compatible(journey):
    journey.send(message='Explain the note.', file_context={'name': 'note.md', 'content': 'The exact project name is Elm.'}, tool_policy='none')
    journey.process()
    cid = journey.handler.sessions['client']['conversation_id']
    source = journey.store.get_conversation(cid)['messages'][0]['data']['attachments'][0]
    assert source['kind'] == 'text'
    assert text_upload.read_text_attachment(source) == 'The exact project name is Elm.'
    assert journey.routes[0][1]['tool_policy'] == 'none'
    assert 'The exact project name is Elm.' in journey.routes[0][0]


@pytest.mark.parametrize('payload', [
    {'mode': 'local', 'attachments': lambda j: [note('a'), note('b'), note('c')]},
    {'tool_policy': 'none', 'attachments': lambda j: [j.pdf()]},
    {'image': {'action': 'image', 'images': [{'base64': 'fake'}]}, 'attachments': lambda j: [note()]},
    {'attachments': lambda j: [{'kind': 'pdf', 'stash_ref': 'stash://../../private/file'}]},
])
def test_invalid_or_incompatible_bundle_never_persists_or_starts(journey, payload):
    payload = dict(payload)
    payload['attachments'] = payload['attachments'](journey)
    journey.send(**payload)
    assert not journey.pending
    assert not list((journey.tmp / 'conversations').glob('*.json'))
    assert journey.socket.events[-1][0] == 'chat:error'


def test_vision_uses_only_image_question_then_all_sources_reach_orchestrator(journey, monkeypatch):
    vision_prompts = []
    monkeypatch.setattr(journey.handler, '_process_vision', lambda images, prompt, mode: (
        vision_prompts.append(prompt) or 'The image shows a red label.'
    ))
    monkeypatch.setattr(journey.handler, '_auto_stash_image', lambda *args: {'stash_ref': 'stash://image-space/image-file'})
    journey.send(attachments=[note('PRIVATE DOCUMENT TEXT')], image=image())
    journey.process()
    assert 'PRIVATE DOCUMENT TEXT' not in vision_prompts[0]
    assert 'Image 1: photo.jpg' in vision_prompts[0]
    assert 'PRIVATE DOCUMENT TEXT' in journey.routes[0][0]
    assert 'Image 1: photo.jpg' in journey.routes[0][0]
    assert journey.routes[0][1]['vision_pre_analyzed'] is True


def test_mixed_vision_failure_preserves_other_sources_and_reports_partial_result(journey, monkeypatch):
    def unavailable(*args): raise RuntimeError('mock vision outage')
    monkeypatch.setattr(journey.handler, '_process_vision', unavailable)
    monkeypatch.setattr(journey.handler, '_auto_stash_image', lambda *args: {'stash_ref': 'stash://image-space/image-file'})
    attachment = note()
    journey.send(attachments=[attachment], image=image())
    journey.process()
    assert attachment['stash_ref'] in journey.routes[0][0]
    assert 'UNAVAILABLE IMAGE SOURCES' in journey.routes[0][0]
    assert 'stash://image-space/image-file' in journey.routes[0][0]
    result = next(data for event, data, _ in journey.socket.events if event == 'chat:response')
    assert result['ok'] is False
    assert 'photo.jpg' in result['text']
    assert result['data']['attachment_errors'][0]['status'] == 'unavailable'
    cid = journey.handler.sessions['client']['conversation_id']
    saved = journey.store.get_conversation(cid)['messages'][-1]['data']
    assert saved['attachment_errors'][0]['filename'] == 'photo.jpg'
    assert saved['stash']['stash_ref'] == 'stash://image-space/image-file'


@pytest.mark.parametrize('when', ['before', 'during'])
def test_cancel_during_preparation_prevents_orchestration_and_cleans_state(journey, monkeypatch, when):
    def vision(*args):
        journey.handler.pending_cancellations[message_id] = True
        return 'The image shows a label.'
    monkeypatch.setattr(journey.handler, '_process_vision', vision)
    monkeypatch.setattr(journey.handler, '_auto_stash_image', lambda *args: pytest.fail('No stash work after cancellation'))
    journey.send(attachments=[note()], image=image())
    message_id = next(data['message_id'] for event, data, _ in journey.socket.events if event == 'chat:thinking')
    if when == 'before':
        journey.handler.pending_cancellations[message_id] = True
    journey.process()
    assert not journey.routes
    assert not journey.instances
    assert message_id not in journey.handler.pending_cancellations
    response = next(data for event, data, _ in journey.socket.events if event == 'chat:response')
    assert response['cancelled'] is True
    cid = journey.handler.sessions['client']['conversation_id']
    saved = journey.store.get_conversation(cid)['messages'][-1]
    assert saved['data']['cancelled'] is True
    assert saved['content'] == response['text']


def test_image_only_failure_still_stops_with_retryable_error(journey, monkeypatch):
    def unavailable(*args): raise RuntimeError('mock vision outage')
    monkeypatch.setattr(journey.handler, '_process_vision', unavailable)
    journey.send(image=image())
    journey.process()
    assert not journey.routes
    result = journey.socket.events[-1]
    assert result[0] == 'chat:error'
    assert result[1]['error_code'] == 'vision_analysis_failed'
    assert result[1]['retryable'] is True
    assert not journey.handler.pending_cancellations


def test_primary_tool_failure_survives_simultaneous_image_failure(journey, monkeypatch):
    def unavailable(*args):
        raise RuntimeError('mock vision outage')
    monkeypatch.setattr(journey.handler, '_process_vision', unavailable)
    monkeypatch.setattr(journey.handler, '_auto_stash_image', lambda *args: {'stash_ref': 'stash://image-space/image-file'})
    source = journey.pdf()
    journey.provider_result.update(ok=False, speech='The PDF could not be read.',
                                   error='PDF storage expired', tool_name='pdf_read',
                                   tool_args={'stash_ref': source['stash_ref']})
    journey.send(attachments=[source], image=image())
    journey.process()
    cid = journey.handler.sessions['client']['conversation_id']
    saved = journey.store.get_conversation(cid)['messages'][-1]
    assert saved['data']['_error']['message'] == 'PDF storage expired'
    assert saved['data']['_error']['tool_failed'] == 'pdf_read'
    assert saved['data']['_error']['tool_args']['stash_ref'] == source['stash_ref']
    assert saved['data']['attachment_errors'][0]['filename'] == 'photo.jpg'
    assert 'PDF could not be read' in saved['content']


def test_explicit_workflow_stays_explicit_after_mixed_vision(journey, monkeypatch):
    from workflow_loader import WorkflowLoader

    monkeypatch.setattr(journey.handler, '_process_vision', lambda *args: 'The image shows a chart.')
    monkeypatch.setattr(journey.handler, '_auto_stash_image', lambda *args: {'stash_ref': 'stash://image-space/image-file'})
    journey.send(message='/research Compare the sources.', attachments=[journey.pdf()], image=image())
    journey.process()
    prompt = journey.routes[0][0]
    loader = WorkflowLoader.__new__(WorkflowLoader)
    assert loader._score_match(prompt.lower(), {'triggers': {'explicit': ['/research']}}, check_patterns=False) >= 100
    assert '[ATTACHED PDF ARTIFACT]' in prompt
    assert 'image shows a chart' in prompt


def test_stash_tool_results_are_not_replaced_by_image_upload_metadata(journey, monkeypatch):
    monkeypatch.setattr(journey.handler, '_process_vision', lambda *args: 'The image shows a label.')
    monkeypatch.setattr(journey.handler, '_auto_stash_image', lambda *args: {'stash_ref': 'stash://image-space/image-file'})
    reads = [{'ref': 'stash://documents/first', 'content': 'First note'},
             {'ref': 'stash://documents/second', 'content': 'Second note'}]
    journey.provider_result.update(data={'stash': reads}, tools_used=['stash', 'stash'])
    journey.send(attachments=[note()], image=image())
    journey.process()
    cid = journey.handler.sessions['client']['conversation_id']
    saved = journey.store.get_conversation(cid)['messages'][-1]['data']
    response = next(data for event, data, _ in journey.socket.events if event == 'chat:response')
    for data in (saved, response['data']):
        assert data['stash'] == reads
        assert data['_web_upload_stash']['stash_ref'] == 'stash://image-space/image-file'


def test_mixed_images_use_server_bytes_and_reject_missing_or_linked_uploads(journey, monkeypatch):
    import base64
    import hashlib

    from PIL import Image

    # Exercise the actual hydration boundary; no network or model calls.
    monkeypatch.setattr(chat, 'JARVIS_ROOT', journey.tmp)
    uploads = journey.tmp / 'jarvis-web/data/uploads'
    uploads.mkdir(parents=True)
    path = uploads / 'trusted.jpg'
    Image.new('RGB', (2, 2), 'red').save(path, format='JPEG')
    pixels = path.read_bytes()
    payload = {'images': [{'filename': path.name, 'base64': 'forged pixels', 'url': 'https://forged.invalid/elsewhere'}]}
    hydrate = chat.ChatHandler._hydrate_uploaded_image_payload
    assert hydrate(journey.handler, payload, authoritative=True) is None
    assert base64.b64decode(payload['images'][0]['base64']) == pixels
    assert payload['images'][0]['uploaded_sha256'] == hashlib.sha256(pixels).hexdigest()
    assert payload['images'][0]['url'] == '/api/uploads/trusted.jpg'
    linked = uploads / 'linked.jpg'
    linked.symlink_to(path)
    assert 'unavailable' in hydrate(journey.handler, {'images': [{'filename': linked.name}]}, authoritative=True)
    assert 'not found' in hydrate(journey.handler, {'images': [{'filename': 'missing.jpg', 'base64': 'forged'}]}, authoritative=True)


def test_all_six_text_sources_survive_real_history_formatting(journey):
    from zoneinfo import ZoneInfo

    from context_assembler import ContextAssembler

    sources = [note(f'UNIQUE_EVIDENCE_{index}\n' + 'x' * 5000, name=('n' * 184) + f'{index}.txt') for index in range(6)]
    journey.send(attachments=sources)
    journey.process()
    cid = journey.handler.sessions['client']['conversation_id']
    journey.send(message='Compare all six again.', conversation_id=cid)
    history = journey.handler._get_conversation_context(cid)
    assert len(history[0]['attachment_context']) <= 8000
    assembler = ContextAssembler.__new__(ContextAssembler)
    assembler.timezone = ZoneInfo('UTC')
    assembler._safe_iso_to_local_datetime = lambda value: None
    assembler._format_gap_for_prompt = lambda value: ''
    rendered = assembler.format_conversation_context('Compare all six again.', history)
    for index, source in enumerate(sources):
        assert source['stash_ref'] in rendered
        assert f'UNIQUE_EVIDENCE_{index}' in rendered
    assert 'Excerpt only' in rendered


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_socket_validation_and_processing_share_selected_stash_root(journey, monkeypatch, mode):
    import config_loader

    roots = {key: journey.tmp / key for key in ('cloud', 'local')}
    monkeypatch.setattr(config_loader, '_load_mode_config', lambda selected: {'STASH_DIR': str(roots[selected])})
    with config_loader.config_scope(mode):
        source = note(f'{mode} evidence')
        pdf = journey.pdf()
    journey.send(mode=mode, attachments=[source, pdf])
    assert len(journey.pending) == 1
    journey.process()
    assert len(journey.routes) == 1
    assert f'{mode} evidence' in journey.routes[0][0]
    assert source['stash_ref'] in journey.routes[0][0]
    other = 'local' if mode == 'cloud' else 'cloud'
    assert not roots[other].exists()


def test_legacy_text_is_committed_in_local_request_scope(journey, monkeypatch):
    import config_loader

    monkeypatch.setattr(config_loader, '_load_mode_config', lambda mode: {'STASH_DIR': str(journey.tmp / mode)})
    journey.send(mode='local', file_context={'name': 'legacy.txt', 'content': 'local legacy evidence'})
    journey.process()
    assert 'local legacy evidence' in journey.routes[0][0]
    assert len(list((journey.tmp / 'local').glob('space_web_text_*'))) == 1
    assert not (journey.tmp / 'cloud').exists()


def test_image_stash_preserves_analyzed_bytes_and_never_overwrites_prior_source(journey, monkeypatch):
    import base64
    import hashlib
    import json

    import memory_db
    from PIL import Image

    monkeypatch.setattr(chat, 'JARVIS_ROOT', journey.tmp)
    monkeypatch.setattr(memory_db, 'MemoryDB', lambda: SimpleNamespace(remember=lambda **kwargs: None, close=lambda: None))
    uploads = journey.tmp / 'jarvis-web/data/uploads'
    uploads.mkdir(parents=True)
    source = uploads / 'trusted.jpg'
    stashed = []
    for color in ('red', 'blue'):
        Image.new('RGB', (2, 2), color).save(source, format='JPEG')
        image_data = {'images': [{'filename': source.name}]}
        assert chat.ChatHandler._hydrate_uploaded_image_payload(journey.handler, image_data, authoritative=True) is None
        payload = image_data['images'][0]
        result = journey.handler._auto_stash_image(payload, 'The image shows a colored square.', 'cloud')
        assert result and result['stash_ref']
        space_id, file_id = result['stash_ref'][8:].split('/')
        space = journey.tmp / 'stash' / space_id
        metadata = json.loads((space / 'meta.json').read_text())
        record = next(row for row in metadata['files'] if row['file_id'] == file_id)
        path = space / record['stored_name']
        assert path.read_bytes() == base64.b64decode(payload['base64'])
        stashed.append((path, hashlib.sha256(path.read_bytes()).hexdigest()))
    assert stashed[0][0] != stashed[1][0]
    assert hashlib.sha256(stashed[0][0].read_bytes()).hexdigest() == stashed[0][1]
    # A concurrent replacement after hydration must never be attributed to old pixels.
    payload['uploaded_sha256'] = '0' * 64
    assert journey.handler._auto_stash_image(payload, 'Earlier image evidence', 'cloud') is None


def test_full_six_source_bundle_keeps_documents_audio_and_image_identity_after_reload(journey, monkeypatch):
    import base64
    import json
    import wave
    from zoneinfo import ZoneInfo

    import memory_db
    from context_assembler import ContextAssembler
    from jarvis_bundle_chat_test.services import audio_upload
    from PIL import Image

    monkeypatch.setattr(chat, 'JARVIS_ROOT', journey.tmp)
    monkeypatch.setattr(memory_db, 'MemoryDB', lambda: SimpleNamespace(
        remember=lambda **kwargs: None, close=lambda: None,
    ))
    monkeypatch.setattr(
        journey.handler,
        '_hydrate_uploaded_image_payload',
        chat.ChatHandler._hydrate_uploaded_image_payload.__get__(journey.handler),
    )
    uploads = journey.tmp / 'jarvis-web/data/uploads'
    uploads.mkdir(parents=True)
    image_items = []
    original_pixels = []
    for color in ('red', 'blue'):
        path = uploads / f'{color}.jpg'
        Image.new('RGB', (3, 3), color).save(path, format='JPEG')
        original_pixels.append(path.read_bytes())
        image_items.append({
            'filename': path.name,
            'url': f'/api/uploads/{path.name}',
            'base64': 'client pixels must not replace the committed upload',
        })

    recording_bytes = io.BytesIO()
    with wave.open(recording_bytes, 'wb') as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16000)
        recording.writeframes(b'\0\0' * 1600)
    recording = audio_upload.save_audio_upload(
        FileStorage(io.BytesIO(recording_bytes.getvalue()), filename='recording.wav', content_type='audio/wav'),
        str(uuid.uuid4()),
    )[0]
    note_text = 'Café budget is €120. Compare the revised agreement with the recording.'
    sources = [
        journey.pdf('FIRST_PDF_BODY_NOT_INLINE', name='agreement.pdf'),
        journey.pdf('SECOND_PDF_BODY_NOT_INLINE', name='agreement.pdf'),
        note(note_text, name='notes.md'),
        recording,
    ]
    vision_calls = []

    def vision(images, prompt, mode):
        vision_calls.append((images, prompt, mode))
        return 'Image 1 shows a red square. Image 2 shows a blue square.'

    monkeypatch.setattr(journey.handler, '_process_vision', vision)
    journey.send(
        message='Compare both agreements, the note, the recording, and the two pictures.',
        attachments=sources,
        image={'action': 'analyze', 'images': image_items},
    )
    assert len(journey.pending) == 1
    journey.process()
    assert len(vision_calls) == len(journey.routes) == 1
    images, vision_prompt, mode = vision_calls[0]
    assert mode == 'cloud'
    assert [base64.b64decode(value) for value in images] == original_pixels
    assert note_text not in vision_prompt
    assert 'Image 1: red.jpg' in vision_prompt and 'Image 2: blue.jpg' in vision_prompt

    prompt, kwargs = journey.routes[0]
    assert kwargs['vision_pre_analyzed'] is True
    for number, source in enumerate(sources, 1):
        assert f"Source {number}: {source['filename']}" in prompt
        assert source['stash_ref'] in prompt
        assert (journey.tmp / 'stash' / source['space_id'] / source['filename']).is_file()
    assert sources[0]['filename'] == sources[1]['filename']
    assert sources[0]['stash_ref'] != sources[1]['stash_ref']
    assert note_text in prompt
    assert 'FIRST_PDF_BODY_NOT_INLINE' not in prompt
    assert 'SECOND_PDF_BODY_NOT_INLINE' not in prompt
    assert 'Read each PDF with pdf_read' in prompt
    assert 'transcribe each recording with transcribe_audio' in prompt
    assert 'filenames and metadata are not evidence of contents' in prompt

    cid = journey.handler.sessions['client']['conversation_id']
    reloaded_store = conversation_store.ConversationStore(journey.tmp / 'conversations')
    saved = reloaded_store.get_conversation(cid)
    assert saved['messages'][0]['data']['attachments'] == [
        {**source, 'mode': 'cloud'} for source in sources
    ]
    assert saved['messages'][0]['data']['image_urls'] == ['/api/uploads/red.jpg', '/api/uploads/blue.jpg']
    saved_images = saved['messages'][-1]['data']['_web_upload_stash']['uploaded_images']
    assert len(saved_images) == 2
    image_refs = []
    for index, (saved_image, pixels) in enumerate(zip(saved_images, original_pixels), 1):
        image_ref = saved_image['stash_ref']
        image_refs.append(image_ref)
        assert image_ref in prompt
        assert saved_image['ordinal'] == index
        assert saved_image['source_filename'] == image_items[index - 1]['filename']
        space_id, file_id = image_ref.removeprefix('stash://').split('/')
        space_path = journey.tmp / 'stash' / space_id
        metadata = json.loads((space_path / 'meta.json').read_text())
        stored_file = next(item for item in metadata['files'] if item['file_id'] == file_id)
        assert (space_path / stored_file['stored_name']).read_bytes() == pixels
    assert len(set([source['stash_ref'] for source in sources] + image_refs)) == 6
    assert original_pixels[0] != original_pixels[1]

    monkeypatch.setattr(conversation_store, 'get_conversation_store', lambda: reloaded_store)
    followup_question = 'Compare the second agreement with the second picture again.'
    journey.send(message=followup_question, conversation_id=cid)
    journey.process()
    history = journey.routes[-1][1]['conversation_history']
    assembler = ContextAssembler.__new__(ContextAssembler)
    assembler.timezone = ZoneInfo('UTC')
    assembler._safe_iso_to_local_datetime = lambda value: None
    rendered = assembler.format_conversation_context(followup_question, history)
    for source in sources:
        assert source['stash_ref'] in rendered
    for image_ref in image_refs:
        assert image_ref in rendered
    assert 'Source 2: agreement.pdf' in rendered
    assert 'Uploaded image 2' in rendered
    assert note_text in rendered
    assert 'pdf_read' in rendered and 'transcribe_audio' in rendered
    assert not journey.handler.pending_cancellations


@pytest.mark.parametrize('kind', ['pdf', 'audio'])
@pytest.mark.parametrize('image_count', [0, 2])
def test_single_document_keeps_source_one_label_with_images_and_after_reload(
    journey, monkeypatch, kind, image_count
):
    if kind == 'pdf':
        source = journey.pdf(name='agreement.pdf')
    else:
        import wave

        from jarvis_bundle_chat_test.services import audio_upload

        payload = io.BytesIO()
        with wave.open(payload, 'wb') as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(16000)
            recording.writeframes(b'\0\0' * 1600)
        source = audio_upload.save_audio_upload(
            FileStorage(io.BytesIO(payload.getvalue()), filename='meeting.wav', content_type='audio/wav'),
            str(uuid.uuid4()),
        )[0]
    monkeypatch.setattr(journey.handler, '_process_vision', lambda *args: 'Both images show the source under review.')
    monkeypatch.setattr(journey.handler, '_auto_stash_image', lambda payload, *args: {
        'stash_ref': f"stash://space_images/f_{int(payload['filename'][0]):012d}",
    })
    image_payload = {
        'action': 'analyze',
        'images': [
            {'base64': 'fake-pixels', 'filename': f'{index}.jpg', 'url': f'/api/uploads/{index}.jpg'}
            for index in range(1, image_count + 1)
        ],
    } if image_count else None

    journey.send(message='Explain Source 1 using the supplied evidence.', attachments=[source], image=image_payload)
    journey.process()
    prompt = journey.routes[0][0]
    label = f"Source 1: {source['filename']}"
    assert label in prompt
    assert source['stash_ref'] in prompt
    assert f'[ATTACHED {kind.upper()} ARTIFACT]' in prompt
    for index in range(1, image_count + 1):
        assert f'Image {index}: {index}.jpg' in prompt

    cid = journey.handler.sessions['client']['conversation_id']
    restored = conversation_store.ConversationStore(journey.tmp / 'conversations')
    monkeypatch.setattr(conversation_store, 'get_conversation_store', lambda: restored)
    journey.send(message='Read Source 1 again.', conversation_id=cid)
    journey.process()
    history = journey.routes[-1][1]['conversation_history']
    assert label in history[0]['attachment_context']
    assert source['stash_ref'] in history[0]['attachment_context']


def test_cross_mode_note_history_does_not_claim_the_original_source_was_deleted(journey, monkeypatch):
    import config_loader

    roots = {mode: journey.tmp / mode for mode in ('cloud', 'local')}
    monkeypatch.setattr(config_loader, '_load_mode_config', lambda mode: {'STASH_DIR': str(roots[mode])})
    with config_loader.config_scope('cloud'):
        source = note('Original cloud note content.')
    journey.send(attachments=[source])
    journey.process()
    cid = journey.handler.sessions['client']['conversation_id']
    journey.send(message='Read Source 1 again.', conversation_id=cid, mode='local')
    journey.process()
    context = journey.routes[-1][1]['conversation_history'][0]['attachment_context']
    assert source['stash_ref'] in context
    assert 'unavailable in the current Stash' in context
    assert 'original cloud mode' in context
    assert 'Original cloud note content.' not in context
    assert (roots['cloud'] / source['space_id'] / source['filename']).exists()


def test_failed_conversation_load_identifies_the_requested_thread(journey):
    app = Flask(__name__)
    with app.test_request_context('/'):
        request.sid = 'client'
        journey.socket.handlers['conversation:load']({'conversation_id': 'missing-thread'})
    event, payload, _ = journey.socket.events[-1]
    assert event == 'chat:error'
    assert payload == {
        'error': 'Conversation not found',
        'error_code': 'conversation_not_found',
        'conversation_id': 'missing-thread',
    }


@pytest.fixture
def video_source(journey):
    import subprocess

    from jarvis_bundle_chat_test.services import video_upload

    path = journey.tmp / 'silent.mp4'
    subprocess.run([
        'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=160x96:r=5',
        '-t', '1', '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', str(path),
    ], check=True, capture_output=True, timeout=15)
    with path.open('rb') as stream:
        return video_upload.save_video_upload(
            FileStorage(stream, filename='silent.mp4', content_type='video/mp4'), str(uuid.uuid4())
        )[0]


def test_video_and_note_admit_route_and_restore_with_original_evidence_scope(
    journey, video_source, monkeypatch,
):
    # Provider work remains mocked; real upload validation and conversation storage
    # use the fixture's disposable destinations.
    monkeypatch.setattr(journey.handler, '_sanitize_tool_hints', lambda hints, **kwargs: hints or [])
    journey.provider_result.update({
        'tools_used': ['analyze_video'],
        'data': {'analyze_video': {'ok': True, 'data': {
            'source_stash_ref': video_source['stash_ref'], 'source_filename': 'silent.mp4',
            'analysis': 'The sampled frames show a blue screen.', 'start_seconds': 0,
            'end_seconds': 1, 'frame_timestamps': [0, 0.8], 'audio_status': 'no_audio',
            'visual_status': 'complete',
        }}},
    })
    journey.send(attachments=[video_source, note('Compare the screen color.')], mode='local')
    journey.process()
    prompt = journey.routes[0][0]
    assert 'Source 1: silent.mp4 (video)' in prompt
    assert 'Audio stream: absent' in prompt
    assert 'Use analyze_video' in prompt
    assert 'Selected tool hints: analyze_video' in prompt
    assert 'samples do not establish what happened between frames' in prompt
    cid = journey.handler.sessions['client']['conversation_id']
    restored = conversation_store.ConversationStore(journey.tmp / 'conversations').get_conversation(cid)
    source = restored['messages'][0]['data']['attachments'][0]
    assert source['kind'] == 'video' and source['mode'] == 'local'
    assert source['has_audio'] is False
    journey.send(message='Save those findings to Canvas.', mode='local', conversation_id=cid)
    journey.process()
    history = journey.routes[-1][1]['conversation_history']
    assert video_source['stash_ref'] in history[0]['attachment_context']
    assert history[-1]['tool_results']['analyze_video']['audio_status'] == 'no_audio'


def test_video_rejects_chat_only_before_admission(journey, video_source):
    journey.send(attachments=[video_source], tool_policy='none')
    assert not journey.pending
    assert not list((journey.tmp / 'conversations').glob('*.json'))
    assert journey.socket.events[-1][0] == 'chat:error'
    assert 'Chat only' in journey.socket.events[-1][1]['error']


def test_video_default_question_and_preparation_cancel_are_durable(journey, video_source):
    journey.send(message='', attachments=[video_source])
    assert len(journey.pending) == 1
    cid = journey.handler.sessions['client']['conversation_id']
    message = journey.store.get_conversation(cid)['messages'][0]
    assert 'video' in message['content']
    request_id = next(data['message_id'] for event, data, _ in journey.socket.events
                      if event == 'chat:thinking')
    journey.handler.pending_cancellations[request_id] = True
    journey.process()
    assert not journey.routes
    saved = journey.store.get_conversation(cid)
    assert saved['messages'][0]['data']['attachments'][0]['stash_ref'] == video_source['stash_ref']
    assert saved['messages'][-1]['data']['cancelled'] is True
