import json
import threading
import uuid

import pytest
from craft_gateway.api import create_app
from craft_gateway.models import Operation, Submission
from craft_gateway.store import Conflict, Store
from fastapi.testclient import TestClient

KEY = 'fixture-only-private-key-' + 'a' * 40
HEADERS = {'Authorization': 'Bearer ' + KEY}

@pytest.fixture
def app(tmp_path):
    return create_app({'api_key':KEY,'state_dir':str(tmp_path / 'state'),'apps_root':str(tmp_path / 'apps')})

def test_auth_all_routes_and_no_credentials_in_capabilities(app):
    with TestClient(app) as client:
        for method,path in [('GET','capabilities'),('POST','projects'),('GET','projects/'+'a'*32),
                            ('GET','jobs/'+'a'*32),('GET','artifacts/'+'a'*32)]:
            assert client.request(method,'/craft-api/v1/'+path).status_code == 401
        result=client.get('/craft-api/v1/capabilities',headers=HEADERS)
        assert result.status_code == 200
        assert KEY not in result.text and 'binary' not in result.text
        assert not any(item['supported'] for item in result.json()['apps'].values())

def test_stream_upload_limits_headers_and_project_containment(tmp_path):
    app=create_app({'api_key':KEY,'state_dir':str(tmp_path),'apps_root':str(tmp_path / 'apps'),'upload_bytes':64})
    with TestClient(app) as client:
        project=client.post('/craft-api/v1/projects',headers=HEADERS).json()['id']
        url='/craft-api/v1/projects/'+project+'/inputs'
        for name,data,status in [('../bad.pdf',b'%PDF-1.4',422),('native.ecproj',b'{}',422),
                                 ('bad.png',b'%PDF-1.4',422),('big.pdf',b'%PDF-'+b'x'*100,413)]:
            assert client.post(url,params={'filename':name},content=data,headers=HEADERS).status_code == status
        assert not list((tmp_path/'projects'/project/'inputs').glob('*/*'))
        first=client.post(url,params={'filename':'source.pdf'},content=b'%PDF-1.4\n',headers=HEADERS).json()
        second=client.post(url,params={'filename':'source.pdf'},content=b'%PDF-1.4\n',headers=HEADERS).json()
        assert first['id'] != second['id']
        assert client.get('/craft-api/v1/artifacts/'+first['id'],headers=HEADERS).content == b'%PDF-1.4\n'
        other=client.post('/craft-api/v1/projects',headers=HEADERS).json()['id']
        with pytest.raises(KeyError):
            app.state.service.store.artifact(first['id'],other)
        assert client.get('/craft-api/v1/projects/not-an-id',headers=HEADERS).status_code == 422

def test_idempotency_revision_and_single_writer(tmp_path):
    store=Store(tmp_path)
    project=store.create_project()
    submission=Submission(request_id=uuid.uuid4().hex,project_id=project['id'],revision=0,
                          operation=Operation(app='effectcraft',action='title'))
    first=store.submit(submission,'/fixture/binary','v0.7.0')
    assert store.submit(submission,'/changed/binary','v0.8.0')['id'] == first['id']
    with pytest.raises(Conflict):
        store.submit(submission.model_copy(update={'revision':1}),'','')
    with pytest.raises(Conflict):
        store.submit(submission.model_copy(update={'request_id':uuid.uuid4().hex}),'','')
    assert store.claim()['id'] == first['id']
    store.finish(first['id'],'succeeded')
    with pytest.raises(Conflict):
        store.submit(submission.model_copy(update={'request_id':uuid.uuid4().hex}),'','')
    assert store.project(project['id'])['revision'] == 1

def test_restart_marks_interrupted_without_replay(tmp_path):
    from craft_gateway.service import Service
    config={'api_key':KEY,'state_dir':str(tmp_path),'apps_root':str(tmp_path)}
    service=Service(config)
    project=service.store.create_project()
    submission=Submission(request_id=uuid.uuid4().hex,project_id=project['id'],revision=0,
                          operation=Operation(app='effectcraft',action='title'))
    job=service.store.submit(submission,'/does/not/exist','v0.7.0')
    service.store.claim()
    service.start()
    try:
        assert service.store.job(job['id'])['state'] == 'interrupted'
        assert service.store.claim() is None
    finally:
        service.close()

def test_operation_rejects_paths_scripts_and_nonfinite_values():
    for args in [{'app':'effectcraft','action':'title','inputs':['/etc/passwd']},
                 {'app':'effectcraft','action':'title','script':'evil'},
                 {'app':'lightcraft','action':'develop','inputs':['a'*32],'exposure':float('nan')},
                 {'app':'pdfcraft','action':'extract','inputs':['a'*32],'pages':[0]},
                 {'app':'photocraft','action':'invert','inputs':['a'*32],'gpu':True}]:
        with pytest.raises(ValueError):
            Operation(**args)

def test_cancel_running_process_group(tmp_path):
    from craft_gateway.engine import Cancelled, Engine
    cancel=threading.Event()
    started=threading.Event()
    pid=[]
    engine=Engine('/bin/sleep',tmp_path, cancel.is_set,
                  lambda value:(pid.append(value),started.set()),timeout=10)
    outcome=[]
    def run():
        try:
            engine.run('60')
        except Cancelled:
            outcome.append('cancelled')
    thread=threading.Thread(target=run)
    thread.start()
    assert started.wait(5)
    cancel.set()
    thread.join(5)
    assert not thread.is_alive() and outcome == ['cancelled']
    import os
    with pytest.raises(ProcessLookupError):
        os.killpg(pid[0],0)


def test_persisted_operation_keeps_only_selected_adapter_options(tmp_path):
    store=Store(tmp_path)
    project=store.create_project()
    submission=Submission(request_id=uuid.uuid4().hex,project_id=project['id'],revision=0,
                          operation=Operation(app='photocraft',action='invert',inputs=['a'*32]))
    store.submit(submission,'/fixture/binary','v0.6.0')
    row=store.claim()
    restored=Operation.model_validate(json.loads(row['body'])['operation'])
    assert restored.app=='photocraft' and restored.action=='invert'


def test_cancel_queued_is_terminal_and_cannot_be_claimed(tmp_path):
    store=Store(tmp_path)
    project=store.create_project()
    submission=Submission(request_id=uuid.uuid4().hex,project_id=project['id'],revision=0,
                          operation=Operation(app='effectcraft',action='title'))
    job=store.submit(submission,'/fixture/binary','v0.7.0')
    assert store.cancel(job['id'])['state']=='cancelled'
    assert store.claim() is None


def test_engine_timeout_reaps_process(tmp_path):
    from craft_gateway.engine import Engine
    engine=Engine('/bin/sleep',tmp_path,lambda:False,lambda pid:None,timeout=.1)
    with pytest.raises(TimeoutError):
        engine.run('60')
    assert engine.process is None


def test_json_body_limit_applies_before_large_submission_parse(app):
    with TestClient(app) as client:
        response=client.post('/craft-api/v1/jobs',content=b'{' + b' ' * (1024*1024+1),headers=HEADERS)
        assert response.status_code==413


def test_recent_jobs_recovers_ids_after_observer_disappears(tmp_path):
    store=Store(tmp_path)
    project=store.create_project()
    submission=Submission(request_id=uuid.uuid4().hex,project_id=project['id'],revision=0,
                          operation=Operation(app='effectcraft',action='title'))
    accepted=store.submit(submission,'/fixture/binary','v0.7.0')
    jobs=store.recent_jobs()
    assert jobs[0]['id']==accepted['id'] and jobs[0]['request_id']==submission.request_id
