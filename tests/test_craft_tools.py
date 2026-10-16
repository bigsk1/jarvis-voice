"""Configuration, transfer and delivery tests for optional Craft clients."""
import hashlib
import importlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from config_loader import config_scope  # noqa: E402
from craft_client import CraftClient  # noqa: E402
from craft_tools import save_outputs  # noqa: E402
from tool_availability import check_availability_block  # noqa: E402


@pytest.fixture
def followup_extractor():
    load_server_package('craft_followup_test_server', ROOT / 'jarvis-web/server')
    return importlib.import_module('craft_followup_test_server.services.followup_extractor')


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
def test_followup_preserves_editable_artifacts_and_editing_limits(tool, followup_extractor):
    outputs=[{'role':'project','craft_ref':'craft://'+'a'*32+'/'+'b'*32,'stash_ref':'stash://space/file'}]
    note='Each call creates a new composition; this adapter cannot reopen a saved composition.'
    data={tool:{'ok':True,'data':{'project_id':'a'*32,'job_id':'b'*32,'state':'succeeded','outputs':outputs,'followup_note':note}}}
    followup=followup_extractor.extract_followup_data(data)[tool]
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


def test_image_metadata_and_editable_project_are_delivered_and_kept_in_followup(provider,tmp_path,monkeypatch,followup_extractor):
    document={'width':800,'height':450,'layers':[{'id':3,'name':'Caption','kind':'Type','text':'All words','fully_visible':True}]}
    items=[('image.png','primary',b'png','image/png'),('image.pcraft','project',b'native','application/octet-stream'),('document.json','inspection',json.dumps(document).encode(),'application/json')]
    outputs=[{'id':str(i)*32,'name':name,'role':role,'size_bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'mime_type':mime} for i,(name,role,content,mime) in enumerate(items,1)]
    job={'id':'b'*32,'request_id':'d'*32,'project_id':'a'*32,'app_version':'v0.6.0','state':'succeeded','operation':{'app':'photocraft'},'outputs':outputs}
    with config_scope('cloud',{**settings(provider['url']),'STASH_DIR':str(tmp_path/'stash')}):
        client=CraftClient()
        monkeypatch.setattr(client,'download',lambda item:items[int(item['id'][0])-1][2])
        result=save_outputs(client,job,'craft_image')
        client.close()
    data=result['data']
    assert data['document']==document
    assert data['editable_project_ref']=='craft://'+'a'*32+'/'+'2'*32
    followup=followup_extractor.extract_followup_data({'craft_image':result})['craft_image']
    assert followup['editable_project_ref']==data['editable_project_ref']
    assert followup['document']==document


@pytest.mark.parametrize('name,args', [
    ('craft_image',{'action':'edit','sources':['stash://space/file'],'edits':[{'action':'text','text':'Hello'}]}),
    ('craft_video',{'action':'edit','sources':['stash://space/file'],'clips':[{'source':0,'start':1,'end':3}],
                    'video_edits':[{'action':'title','text':'On footage'}],'output':'mp4'}),
    ('craft_video',{'action':'edit','editable_project_ref':'craft://'+'a'*32+'/'+'b'*32,
                    'video_edits':[{'action':'update_text','clip':13,'placement':'top','start':0,'duration':None}]}),
    ('craft_video',{'action':'edit','editable_project_ref':'craft://'+'a'*32+'/'+'b'*32,
                    'video_edits':[{'action':'update_text','clip':13,'placement':'top','start':.5,'duration':1}]}),
])
def test_edit_schemas_validate_in_the_real_background_admission_path(name,args):
    from lib.background_tasks import production
    from lib.background_tasks.local_skill import validate_arguments
    with config_scope('cloud',settings('https://craft.invalid/craft-api/v1')):
        schema,_=production.runner().policy(name)
        validate_arguments(schema,args)


def test_stale_project_revision_is_rejected_before_upload_or_submit(provider,monkeypatch):
    import craft_tools
    with config_scope('cloud',settings(provider['url'])):
        client=CraftClient()
        monkeypatch.setattr(client,'capabilities',lambda:{'apps':{'photocraft':{'supported':True,'actions':['edit']}}})
        monkeypatch.setattr(client,'project',lambda project_id:{'id':project_id,'revision':2})
        monkeypatch.setattr(craft_tools,'CraftClient',lambda:client)
        result=craft_tools.execute_tool('craft_image',{'action':'edit','sources':['craft://'+'a'*32+'/'+'b'*32],
                    'project_revision':1,'edits':[{'action':'update_text','layer':3,'text':'New words'}]})
    assert not result['ok'] and result['completion']=='rejected'
    assert 'revision changed' in result['error']
    assert result['data']['current_project_revision']==2
    assert result['data']['requested_project_revision']==1
    assert result['data']['edit_submitted'] is False
    assert provider['posts']==0 and provider['gets']==0


@pytest.mark.parametrize('source',['stash://space/file','/tmp/flattened.png'])
def test_flat_text_revision_rejected_before_project_creation(provider,source):
    from craft_tools import execute_tool
    with config_scope('cloud',settings(provider['url'])):
        result=execute_tool('craft_image',{'action':'edit','sources':[source],
                    'edits':[{'action':'update_text','layer':3,'text':'Changed'}]})
    assert not result['ok'] and 'editable_project_ref' in result['error']
    assert provider['posts']==0 and provider['gets']==0


def test_explicit_native_project_input_drives_revision_without_sources(provider,monkeypatch):
    import craft_tools
    source='craft://'+'a'*32+'/'+'b'*32
    calls=[]
    class Client:
        def capabilities(self):return {'apps':{'photocraft':{'supported':True,'actions':['edit']}}}
        def project(self,identifier):return {'id':identifier,'revision':1,'artifacts':[{'id':'b'*32,'role':'project','name':'image.pcraft'}]}
        identifier=staticmethod(CraftClient.identifier)
        def submit(self,project,operation):
            calls.append(operation)
            return {'state':'running','id':'c'*32,'project_id':'a'*32,'request_id':'d'*32}
        def wait(self,job,seconds):return job
        def close(self):pass
    monkeypatch.setattr(craft_tools,'CraftClient',Client)
    with config_scope('cloud',{**settings(provider['url']),'JARVIS_BACKGROUND_MAX_INPUT_BYTES':''}):
        result=craft_tools.execute_tool('craft_image',{'action':'edit','editable_project_ref':source,'project_revision':1,
                      'edits':[{'action':'update_text','layer':3,'text':'Changed','name':'Caption'}]})
    assert result['ok'] and calls[0]['inputs']==['b'*32]
    assert 'editable_project_ref' not in calls[0]
