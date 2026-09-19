"""Real Web admit → another foreground tool → external HTTP callback → one answer."""
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from test_task_callback_http import callback_app
from test_task_callbacks import configured
from test_web_background_tasks import eventually
from test_web_background_tasks import journey as journey
from test_web_background_tasks import web_tasks as web_tasks

from lib.background_tasks.worker import TaskWorker
from lib.webhook_integrations.contracts import ADAPTER
from lib.webhook_integrations.runner import LocalCallbackRunner


@pytest.mark.parametrize('scheme', ['bearer', 'hmac-sha256'])
def test_separate_http_service_completes_once_after_an_intervening_web_tool(web_tasks, monkeypatch, scheme):
    h = web_tasks
    h.worker.terminate()
    h.worker.communicate(timeout=6)
    service, source, credential, _ = configured(h.tmp, clock=time.time, scheme=scheme)
    service.store.configure(background_tools=['fixture'])
    control = h.tmp / 'callback-service'
    control.mkdir(mode=0o700)
    credentials = control / 'credential.json'
    credentials.write_text(json.dumps(credential))
    credentials.chmod(0o600)
    external = subprocess.Popen([sys.executable, str(Path(__file__).parent / 'fixtures/task_callback_service.py'),
                                 '--control', str(control)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    api_port = listener.getsockname()[1]
    app = callback_app(service, h.tmp, monkeypatch)
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, lifespan='off'))
    api_thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    api_thread.start()
    stop = threading.Event()
    worker_thread = None
    try:
        eventually(lambda: server.started)
        eventually(lambda: (control / 'port').exists())
        source = service.update_source(source['id'], source['revision'],
            callback_base=f'http://127.0.0.1:{api_port}',
            submit_url=f"http://127.0.0.1:{(control / 'port').read_text()}/submit")
        assert service.test_source(source['id'])['ok']
        h.background.adapters = {'fixture': ADAPTER}
        h.background.callback_sources = {'fixture': source['id']}
        schema = h.background.registry.get_tool('fixture')
        schema.background_adapter = ADAPTER
        schema.background_execution['adapter'] = ADAPTER
        runner = LocalCallbackRunner(service, {'fixture': (source['id'], {'type': 'object', 'properties': {}})})
        worker = TaskWorker(h.tasks, {ADAPTER: runner}, poll_seconds=.05)
        worker_thread = threading.Thread(target=worker.run_forever, args=(stop,), daemon=True)
        worker_thread.start()
        eventually(lambda: any(ADAPTER in item['adapters'] for item in h.tasks.healthy_workers()))
        job = h.send_background()
        eventually(lambda: (control / 'submissions.jsonl').exists())
        conversation_id = job['conversation_id']
        eventually(lambda: h.handler.runs.snapshot(conversation_id)['run']['status'] == 'completed')
        h.client.emit('chat:send', {'message': 'What time is it?', 'mode': 'cloud', 'conversation_id': conversation_id})
        eventually(lambda: (h.root / 'foreground_started').exists())
        assert h.tasks.get(job['id'])['state'] == 'running'
        (h.root / 'foreground_finish').touch()
        eventually(lambda: any('foreground clock returned' in message['content']
                              for message in h.store.get_conversation(conversation_id)['messages'] if message['role'] == 'assistant'))
        (control / 'finish').touch()
        eventually(lambda: (control / 'callback-status.json').exists())
        assert json.loads((control / 'callback-status.json').read_text()) == [202, 200]
        eventually(lambda: h.tasks.get(job['id'])['delivery_state'] == 'delivered')
        messages = h.store.get_conversation(conversation_id)['messages']
        assert sum('background fixture completed' in message['content'] for message in messages) == 1
        assert len((control / 'submissions.jsonl').read_text().splitlines()) == 1
        assert len(h.summaries) == 1
        assert h.tasks.get(job['id'])['result']['speech'] == 'The separate HTTP service finished.'
    finally:
        stop.set()
        if worker_thread:
            worker_thread.join(6)
        external.terminate()
        external.communicate(timeout=6)
        server.should_exit = True
        api_thread.join(6)
        listener.close()
