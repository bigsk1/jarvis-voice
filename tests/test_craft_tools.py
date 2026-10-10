"""Configuration, transfer and delivery tests for optional Craft clients."""
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from config_loader import config_scope  # noqa: E402
from craft_client import CraftClient  # noqa: E402
from craft_tools import save_outputs  # noqa: E402
from tool_availability import check_availability_block  # noqa: E402


@pytest.fixture
def provider():
    state={'posts':0, 'gets':0, 'status':500, 'job':{'id':'b'*32,'state':'running'}, 'bytes':b'%PDF-1.4\nfixture'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            state['posts']+=1
            state['body']=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if state.get('accept', True):
                state['job'].update(request_id=state['body']['request_id'],project_id=state['body']['project_id'],revision=state['body']['revision'],operation=state['body']['operation'])
            self.send_response(state['status'])  # independent acceptance and response
            self.end_headers()
        def do_GET(self):
            state['gets']+=1
            if self.path.startswith('/craft-api/v1/jobs/by-request/'):
                data=json.dumps(state['job']).encode()
            elif self.path.startswith('/craft-api/v1/projects/'):
                data=json.dumps({'revision':1}).encode()
            else:
                data=state['bytes']
            self.send_response(200)
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    state['url']=f'http://127.0.0.1:{server.server_port}/craft-api/v1'
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def settings(url):
    return {'CRAFT_API_URL':url, 'CRAFT_API_KEY':'fixture-secret', 'CRAFT_CA_BUNDLE':''}

def test_unconfigured_tools_and_independent_modes():
    manifest=json.loads((ROOT/'skills/craft_image.tool.json').read_text())
    with config_scope('cloud', settings('http://127.0.0.1:19444/craft-api/v1')):
        assert check_availability_block(manifest['availability']).available
        client=CraftClient()
        client.close()
    with config_scope('local', {'CRAFT_API_URL':'','CRAFT_API_KEY':''}):
        assert not check_availability_block(manifest['availability']).available
        with pytest.raises(ValueError):
            CraftClient()

@pytest.mark.parametrize('url', ['http://remote.example:19444/craft-api/v1', 'https://user:pass@host/craft-api/v1',
                               'https://host/photocraft/', 'https://host/craft-api/v1?secret=x'])
def test_reject_unsafe_or_wrong_endpoints(url):
    with config_scope('cloud',settings(url)):
        with pytest.raises(ValueError):
            CraftClient()


def test_accepted_submission_with_lost_response_is_queried_without_replay(provider):
    with config_scope('local',settings(provider['url'])):
        client=CraftClient()
        try:
            result=client.submit({'id':'a'*32,'revision':0},{'app':'effectcraft','action':'title'})
            assert result == provider['job'] and provider['posts'] == 1
            assert provider['body']['request_id']
        finally:
            client.close()


def test_checksum_and_stash_custom_root_delivery(provider,tmp_path):
    artifact={'id':'c'*32,'name':'result.pdf','role':'primary','size_bytes':len(provider['bytes']),
              'sha256':hashlib.sha256(provider['bytes']).hexdigest(),'mime_type':'application/pdf'}
    job={'id':'b'*32,'request_id':'d'*32,'project_id':'a'*32,'app_version':'v0.5.0','state':'succeeded',
         'renderer':'cpu','operation':{'app':'pdfcraft'},'outputs':[artifact]}
    with config_scope('cloud',{**settings(provider['url']), 'STASH_DIR':str(tmp_path/'custom-stash')}):
        client=CraftClient()
        client.capability={'limits':{'output_bytes':1024}}
        try:
            result=save_outputs(client,job,'craft_pdf')
            assert result['ok'] and result['data']['stash_ref'].startswith('stash://')
            path=Path(result['data']['file_path'])
            assert path.is_relative_to(tmp_path/'custom-stash') and path.read_bytes()==provider['bytes']
            assert result['data']['outputs'][0]['craft_ref']=='craft://'+'a'*32+'/'+'c'*32
            provider['bytes']=b'corrupted'
            with pytest.raises(RuntimeError):
                client.download(artifact)
        finally:
            client.close()


def test_reviewed_background_environment_and_schema():
    from lib.background_tasks import production
    from lib.background_tasks.local_contract import REMOTE_ADAPTER
    from lib.background_tasks.local_skill import restrict_child_environment
    with config_scope('cloud',settings('https://craft.invalid/craft-api/v1')):
        runner=production.runner()
        for name in ('craft_image','craft_pdf','craft_photos','craft_video','craft_motion'):
            schema,policy=runner.policy(name)
            assert policy['adapter']==REMOTE_ADAPTER and policy['timeout_seconds']==1500
            restricted=restrict_child_environment({'CRAFT_API_KEY':'fixture','OPENAI_API_KEY':'unrelated',
                        'STASH_DIR':'/configured/stash'},production.CHILD_ENVIRONMENT_POLICIES[name],{},Path('/tmp/craft-fixture'))
            assert restricted['CRAFT_API_KEY']=='fixture'
            assert 'OPENAI_API_KEY' not in restricted


@pytest.mark.parametrize('tool', ['craft_image', 'craft_pdf', 'craft_photos', 'craft_video', 'craft_motion', 'craft_inspect'])
def test_followup_preserves_editable_artifacts_and_editing_limits(tool):
    sys.path.insert(0, str(ROOT / 'jarvis-web'))
    from server.services import followup_extractor as module
    outputs=[{'role':'project','craft_ref':'craft://'+'a'*32+'/'+'b'*32,'stash_ref':'stash://space/file'}]
    note='Each call creates a new composition; this adapter cannot reopen a saved composition.'
    data={tool:{'ok':True,'data':{'project_id':'a'*32,'job_id':'b'*32,'state':'succeeded','outputs':outputs,'followup_note':note}}}
    followup=module.extract_followup_data(data)[tool]
    assert followup['project_id']=='a'*32 and followup['outputs']==outputs
    assert followup['followup_note']==note


def test_foreground_timeout_leaves_room_for_observation_and_artifact_transfer():
    from orchestrator.executor import ToolExecutor
    executor=ToolExecutor.__new__(ToolExecutor)
    for mode in ('cloud','local'):
        executor.mode=mode
        assert executor._get_subprocess_timeout('craft_image')==300
        assert executor._get_subprocess_timeout('craft_inspect')==180


def test_foreground_empty_background_budget_keeps_upload_available(provider,tmp_path,monkeypatch):
    source=tmp_path/'source.pdf'
    source.write_bytes(b'%PDF-1.4')
    with config_scope('cloud',{**settings(provider['url']),'JARVIS_BACKGROUND_MAX_INPUT_BYTES':''}):
        client=CraftClient()
        client.capability={'limits':{'upload_bytes':1024}}
        monkeypatch.setattr(client,'json',lambda *args,**kwargs:{'id':'a'*32})
        try:
            assert client.upload('b'*32,source)['id']=='a'*32
        finally:
            client.close()


@pytest.mark.parametrize('reason', ['queue-full', 'project-busy', 'revision-conflict', 'request-body-conflict'])
def test_409_is_confirmed_rejection_and_never_returns_a_prior_job(provider, reason):
    from remote_completion import RemoteCompletionError
    provider.update(status=409, accept=False)
    provider['job'].update(id='e'*32, operation={'app':'effectcraft','action':'title','text':'previous edit'})
    with config_scope('cloud',settings(provider['url'])):
        client=CraftClient()
        try:
            with pytest.raises(RemoteCompletionError) as error:
                client.submit({'id':'a'*32,'revision':0},{'app':'effectcraft','action':'title'},request_id='c'*32)
            assert error.value.completion=='rejected'
            assert provider['posts']==1 and provider['gets']==0
        finally:
            client.close()


def test_recovery_refuses_a_mismatched_accepted_job(provider):
    provider['accept']=False
    provider['job'].update(request_id='c'*32,project_id='a'*32,operation={'app':'effectcraft','action':'title','text':'other'})
    with config_scope('cloud',settings(provider['url'])):
        client=CraftClient()
        try:
            with pytest.raises(RuntimeError,match='outcome is unknown'):
                client.submit({'id':'a'*32,'revision':0},{'app':'effectcraft','action':'title'},request_id='c'*32)
            assert provider['posts']==1 and provider['gets']==1
        finally:
            client.close()


def test_motion_sources_are_rejected_before_creating_or_uploading(provider):
    from craft_tools import execute_tool
    with config_scope('cloud',settings(provider['url'])):
        result=execute_tool('craft_motion',{'action':'title','sources':['stash://space/file']})
    assert not result['ok'] and result['completion']=='rejected'
    assert provider['posts']==0 and provider['gets']==0
    manifest=json.loads((ROOT/'skills/craft_motion.tool.json').read_text())
    assert 'sources' not in manifest['parameters']['properties']


def test_disconnected_observer_keeps_running_job_identity(provider,monkeypatch):
    from craft_client import CraftError
    with config_scope('cloud',settings(provider['url'])):
        client=CraftClient()
        job={'id':'b'*32,'project_id':'a'*32,'request_id':'c'*32,'state':'running'}
        monkeypatch.setattr(client,'job',lambda *_: (_ for _ in ()).throw(ConnectionError('disconnected')))
        try:
            with pytest.raises(CraftError) as error:
                client.wait(job,1)
            assert error.value.completion=='unknown' and error.value.job==job
            assert provider['posts']==0
        finally:
            client.close()


def test_https_client_rejects_wrong_ca(tmp_path):
    import importlib.util
    import ssl

    import requests
    setup_path=ROOT/'jarvis-craft-tools/scripts/setup_gateway.py'
    spec=importlib.util.spec_from_file_location('craft_tls_test',setup_path)
    setup=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    (tmp_path/'correct').mkdir()
    (tmp_path/'wrong').mkdir()
    correct=setup.certificate(tmp_path/'correct','127.0.0.1')
    wrong=setup.certificate(tmp_path/'wrong','127.0.0.1')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            data=json.dumps({'protocol_version':1}).encode()
            self.send_response(200)
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(correct/'server.crt',correct/'server.key')
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    url=f'https://127.0.0.1:{server.server_port}/craft-api/v1'
    try:
        with config_scope('cloud',{**settings(url),'CRAFT_CA_BUNDLE':str(wrong/'ca.crt')}):
            client=CraftClient()
            try:
                with pytest.raises(requests.exceptions.SSLError):
                    client.capabilities()
            finally:
                client.close()
        with config_scope('cloud',{**settings(url),'CRAFT_CA_BUNDLE':str(correct/'ca.crt')}):
            client=CraftClient()
            try:
                assert client.capabilities()['protocol_version']==1
            finally:
                client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_submission_rejection_reaches_tool_completion_for_background(provider,monkeypatch):
    import craft_tools
    provider.update(status=409,accept=False)
    with config_scope('cloud',{**settings(provider['url']),'JARVIS_BACKGROUND_MAX_INPUT_BYTES':'52428800'}):
        client=CraftClient()
        real_json=client.json
        monkeypatch.setattr(client,'capabilities',lambda:{'apps':{'effectcraft':{'supported':True,'actions':['title']}}})
        monkeypatch.setattr(client,'json',lambda method,path,**kwargs:
                            {'id':'a'*32,'revision':0} if path=='/projects' else real_json(method,path,**kwargs))
        monkeypatch.setattr(craft_tools,'CraftClient',lambda:client)
        result=craft_tools.execute_tool('craft_motion',{'action':'title'})
    assert not result['ok'] and result['completion']=='rejected'
    assert provider['posts']==1 and provider['gets']==0
