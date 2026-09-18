"""Real local media, trusted policy, isolated stash and process ownership evidence."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_background_tasks import admission, receipt
from test_background_tasks import config_root as config_root
from test_background_tasks import store as store

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT / 'lib', ROOT / 'orchestrator'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from tool_process import (  # noqa: E402
    OutputLimitExceeded,
    group_alive,
    run_local_process,
    terminate_verified,
)

from lib.background_tasks import (  # noqa: E402
    LostLease,
    production,
)
from lib.background_tasks.local_contract import LOCAL_ADAPTERS  # noqa: E402
from lib.background_tasks.local_skill import LocalSkillRunner, bounded_failure  # noqa: E402
from lib.background_tasks.worker import ExecutionContext, TaskWorker  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Production supervision requires Linux')


@pytest.fixture
def conversion(store, config_root, tmp_path, monkeypatch):
    import executor
    from config_loader import config_scope
    store.configure(background_tools=['convert_file'])

    monkeypatch.setattr(executor, 'get_logger', lambda mode: SimpleNamespace(log_tool_call=lambda **kw: None))
    stash = tmp_path / 'stash'
    values = {'STASH_DIR': str(stash), 'JARVIS_TOOL_PROFILE': 'default'}
    for mode in ('cloud', 'local'):
        (config_root / 'config' / f'{mode}.env').write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
    with config_scope('cloud', overrides=values):
        schema, evidence = production.runner().policy('convert_file')
    authorization = ({'operator': 'installation', 'source': 'web', 'conversation_id': 'conversation-1', 'generation': 1,
        'selected': ['convert_file'], 'tool_policy': 'auto', 'tool_policies': {'convert_file': evidence}})
    source = tmp_path / 'tone.wav'
    with wave.open(str(source), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x00\x01' * 8000)

    def admit(mode='cloud', args=None, invocation='convert-1'):
        payload = {**authorization, 'mode':mode, 'request_id':'request-1'}
        adapter = production.ADAPTER
        auth = store.save_authorization(payload)
        job = store.admit(admission(tool='convert_file', adapter=adapter, mode=mode,
             arguments=args or {'source': str(source), 'target_format': 'flac'},
             authorization_id=auth, invocation_id=invocation))
        store.release(job['id'], receipt(job))
        return job

    return SimpleNamespace(store=store, stash=stash, source=source, admit=admit, values=values, schema=schema)


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_actual_conversion_keeps_input_and_writes_decodable_stash(conversion, mode):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg is optional')
    c = conversion
    before = hashlib.sha256(c.source.read_bytes()).hexdigest()
    job = c.admit(mode)
    assert TaskWorker(c.store, production.worker_adapters()).run_once()
    result = c.store.get(job['id'])
    assert result['state'] == 'succeeded', result
    assert result['mode'] == mode
    media = list(c.stash.rglob('*.flac'))
    assert len(media) == 1
    decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(media[0]), '-f', 's16le', '-'],
                             capture_output=True, check=True, timeout=10)
    assert decoded.stdout == b'\x00\x01' * 8000
    assert hashlib.sha256(c.source.read_bytes()).hexdigest() == before
    assert result['result']['data']['stash_ref'].startswith('stash://')
    assert c.store.pending_deliveries()
    assert not list((c.store.path.parent / 'task-workspaces').iterdir())


@pytest.mark.parametrize('failure', ['invalid_source', 'input_limit', 'changed_policy'])
def test_conversion_failure_never_replays(conversion, failure, monkeypatch):
    c = conversion
    args = {'source': str(c.source), 'target_format': 'flac'}
    if failure == 'invalid_source':
        args['source'] += '.missing'
    elif failure == 'input_limit':
        with c.source.open('r+b') as handle:
            handle.truncate(512 * 1024**2 + 1)  # Sparse, no large fixture allocation.
    else:
        original = LocalSkillRunner.policy
        monkeypatch.setattr(LocalSkillRunner, 'policy', lambda self, name: (original(self, name)[0], {'changed': True}))
    job = c.admit(args=args)
    worker = TaskWorker(c.store, production.worker_adapters())
    assert worker.run_once()
    result = c.store.get(job['id'])
    assert result['state'] == 'failed', result
    assert not worker.run_once()
    assert not list(c.stash.rglob('*.flac'))


def test_background_png_to_jpeg_preserves_original_and_returns_decodable_image(conversion):
    if not shutil.which('convert'):
        pytest.skip('ImageMagick is optional')
    from PIL import Image

    c = conversion
    source = c.source.with_suffix('.png')
    Image.new('RGB', (80, 60), (50, 100, 180)).save(source)
    original = source.read_bytes()
    job = c.admit(args={'source': str(source), 'target_format': 'jpg', 'options': {'quality': 90}})
    assert TaskWorker(c.store, production.worker_adapters()).run_once()
    saved = c.store.get(job['id'])
    assert saved['state'] == 'succeeded', saved
    outputs = list(c.stash.rglob('*.jpg'))
    assert len(outputs) == 1
    with Image.open(outputs[0]) as converted:
        converted.load()
        assert converted.format == 'JPEG'
        assert converted.size == (80, 60)
    assert source.read_bytes() == original
    assert c.store.pending_deliveries()


def supervise(script, tmp_path, *, checkpoint=lambda: None, max_output_bytes=4096, process_factory=subprocess.Popen):
    return run_local_process([sys.executable, str(ROOT / 'lib/background_tasks/child.py'), '10',
             sys.executable, str(script)], '', python_script=True, cwd=tmp_path, tool_env=dict(os.environ),
             timeout=10, tool_name='supervised-fixture', consume_progress=lambda line: False,
             cancel_check=None, terminate=lambda p, grace_seconds, verify=False: terminate_verified(p, grace_seconds),
             checkpoint=checkpoint, max_output_bytes=max_output_bytes, process_factory=process_factory)


def test_output_limit_stops_the_whole_group(tmp_path):
    script = tmp_path / 'noisy.py'
    script.write_text("import time\nprint('x'*10000, flush=True)\ntime.sleep(20)\n")
    processes = []
    def launch(*args, **kwargs):
        process = subprocess.Popen(*args, **kwargs)
        processes.append(process)
        return process
    with pytest.raises(OutputLimitExceeded):
        supervise(script, tmp_path, process_factory=launch)
    assert not group_alive(processes[0])


def test_lease_loss_during_real_ffmpeg_stops_descendants(store, tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg is optional')
    script = tmp_path / 'encoding.py'
    script.write_text("""import pathlib, subprocess
child=subprocess.Popen(['ffmpeg','-v','error','-re','-f','lavfi','-i','sine=frequency=440','-t','30','-f','null','-'])
pathlib.Path('encoding.pid').write_text(str(child.pid))
child.wait()
""")
    job = store.admit(admission())
    store.release(job['id'], receipt(job))
    claim = store.claim('owner', {'local_fixture'})
    store.running(claim)
    context = ExecutionContext(claim, store, threading.Event(), threading.Event(), {})
    processes = []
    def launch(*args, **kwargs):
        process = subprocess.Popen(*args, **kwargs)
        processes.append(process)
        return process
    def checkpoint():
        if (tmp_path / 'encoding.pid').exists():
            store.attention(claim, 'Test revocation while ffmpeg is active')
        context.checkpoint()
    with pytest.raises(LostLease):
        supervise(script, tmp_path, checkpoint=checkpoint, process_factory=launch)
    assert not group_alive(processes[0])
    assert store.get(job['id'])['state'] == 'needs_attention'
    assert store.claim('second', {'local_fixture'}) is None


def test_child_resource_limits_and_parent_death(tmp_path):
    child = tmp_path / 'child.py'
    child.write_text("""import json, os, pathlib, resource, subprocess, sys, time
pathlib.Path('limits.json').write_text(json.dumps({str(r):resource.getrlimit(r) for r in (resource.RLIMIT_AS,resource.RLIMIT_FSIZE,resource.RLIMIT_CPU)}))
subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'])
pathlib.Path('group.pid').write_text(str(os.getpgrp()))
time.sleep(30)
""")
    parent = tmp_path / 'parent.py'
    parent.write_text('import subprocess,sys,time\nsubprocess.Popen('+repr([sys.executable,
        str(ROOT / 'lib/background_tasks/child.py'), '7', sys.executable, str(child)])+
        ', start_new_session=True)\ntime.sleep(30)\n')
    process = subprocess.Popen([sys.executable, str(parent)], cwd=tmp_path)
    group = None
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / 'group.pid').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        group = SimpleNamespace(pid=int((tmp_path / 'group.pid').read_text()))
        limits = json.loads((tmp_path / 'limits.json').read_text())
        import resource
        assert limits[str(resource.RLIMIT_AS)] == [2 * 1024**3] * 2
        assert limits[str(resource.RLIMIT_FSIZE)] == [512 * 1024**2] * 2
        cpu_budget = 7 * len(os.sched_getaffinity(0))
        assert limits[str(resource.RLIMIT_CPU)] == [cpu_budget, cpu_budget + 1]
        process.kill()
        process.wait(timeout=5)
        deadline = time.monotonic() + 4
        while group_alive(group) and time.monotonic() < deadline:
            time.sleep(.05)
        assert not group_alive(group)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if group and group_alive(group):
            import signal
            os.killpg(group.pid, signal.SIGKILL)


@pytest.mark.parametrize('mode', ['cloud','local'])
def test_foreground_conversion_still_uses_original_executor_contract(conversion, mode, monkeypatch):
    import executor
    from config_loader import config_scope
    c = conversion
    import tool_process
    observed = []
    run = tool_process.run_local_process
    def capture(cmd, *args, **kwargs):
        observed.append(kwargs)
        return run(cmd, *args, **kwargs)
    monkeypatch.setattr(tool_process, 'run_local_process', capture)
    monkeypatch.setenv('JARVIS_BACKGROUND_DEADLINE', str(time.time() - 1))
    monkeypatch.setenv('JARVIS_OVERRIDE_JARVIS_BACKGROUND_DEADLINE', str(time.time() - 1))
    monkeypatch.setattr(executor, 'export_config_environment', lambda mode: {
        **os.environ, 'JARVIS_MODE':mode, **{f'JARVIS_OVERRIDE_{k}':v for k,v in c.values.items()}})
    registry = SimpleNamespace(get_tool=lambda name:c.schema, is_mcp_tool=lambda name:False)
    with config_scope(mode, overrides=c.values):
        runner = executor.ToolExecutor(mode, registry, load_runtime_config=False)
        result = runner.execute('convert_file', {'source':str(c.source), 'target_format':'flac'})
    assert result['ok'], result
    assert observed[0]['timeout'] == 180
    assert observed[0]['tool_env']['JARVIS_BACKGROUND_DEADLINE'] == ''
    assert list(c.stash.rglob('*.flac'))
    assert c.store.conversation_jobs() == []


@pytest.mark.parametrize('mode', ['cloud','local'])
def test_metadata_does_not_change_provider_projection_or_description(mode):
    from config_loader import config_scope
    from tool_schema import ToolSchema
    manifest = json.loads((ROOT / 'skills/convert_file.tool.json').read_text())
    with config_scope(mode):
        current = ToolSchema(manifest['name'],manifest['description'],manifest['parameters'],manifest['script'],
                             execution=manifest['execution'])
        previous = ToolSchema(manifest['name'],manifest['description'],manifest['parameters'],manifest['script'])
        for projection in ('to_openai_format','to_anthropic_format','to_ollama_description'):
            assert getattr(current,projection)() == getattr(previous,projection)()
        assert current.background_adapter == production.ADAPTER
        assert previous.background_adapter is None


@pytest.mark.parametrize('interruption', ['cancel','lease_loss','shutdown','worker_kill'])
def test_real_adapter_stops_conversion_before_releasing_or_reserving_capacity(conversion, tmp_path, monkeypatch, interruption):
    c = conversion
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('ffmpeg is optional')
    shims = tmp_path / 'bin'
    shims.mkdir()
    marker = tmp_path / 'ffmpeg.pid'
    shim = shims / 'ffmpeg'
    # Pace the real decoder so the ownership test reaches an active conversion.
    import shlex
    shim.write_text('#!/bin/sh\necho $$ > '+shlex.quote(str(marker))+'\nexec '+shlex.quote(ffmpeg)+' -re "$@"\n')
    shim.chmod(0o700)
    monkeypatch.setenv('PATH', str(shims)+os.pathsep+os.environ['PATH'])
    job = c.admit()
    worker = TaskWorker(c.store, production.worker_adapters())
    process = None
    thread = None
    stop = threading.Event()
    if interruption == 'worker_kill':
        env = {**os.environ, **{f'JARVIS_OVERRIDE_{k}':v for k,v in c.values.items()}}
        process = subprocess.Popen([sys.executable,str(ROOT/'bin/jarvis-task-worker'),'run','--db',str(c.store.path)],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    else:
        thread = threading.Thread(target=worker.run_once, args=(stop,))
        thread.start()
    try:
        deadline = time.monotonic()+6
        while not marker.exists() and time.monotonic()<deadline:
            time.sleep(.01)
        assert marker.exists(), c.store.get(job['id'])
        current = c.store.get(job['id'])
        group = SimpleNamespace(pid=current['progress']['process_group'])
        if interruption == 'cancel':
            c.store.request_cancel(job['id'], current['revision'], supported_adapters=LOCAL_ADAPTERS)
        elif interruption == 'lease_loss':
            with c.store._connection(write=True) as conn:
                conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE id=?',(job['id'],))
        elif interruption == 'shutdown':
            stop.set()
        else:
            process.kill()
            process.wait(timeout=5)
        if thread:
            thread.join(6)
            assert not thread.is_alive()
        deadline = time.monotonic()+4
        while group_alive(group) and time.monotonic()<deadline:
            time.sleep(.02)
        assert not group_alive(group)
        if interruption == 'worker_kill':
            with c.store._connection(write=True) as conn:
                conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE id=?',(job['id'],))
            c.store.reconcile()
        state = c.store.get(job['id'])['state']
        assert state == ('cancelled' if interruption=='cancel' else
                         'needs_attention' if interruption=='worker_kill' else 'failed')
        assert not worker.run_once()
        assert c.store.counts()['reserved'] == (1 if interruption=='worker_kill' else 0)
        assert not list(c.stash.rglob('*.flac'))
    finally:
        if process:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        if thread:
            thread.join(6)


@pytest.mark.parametrize('variable,target', [('JARVIS_TEST_VIDEO','ogg'),('JARVIS_TEST_IMAGE','webp')])
def test_optional_representative_private_media(conversion, tmp_path, variable, target):
    sample = os.environ.get(variable)
    if not sample:
        pytest.skip('Optional operator-provided private sample')
    c = conversion
    original = Path(sample).resolve()
    before = hashlib.sha256(original.read_bytes()).digest()
    source = tmp_path / ('representative'+original.suffix)
    shutil.copy2(original, source)
    job = c.admit(args={'source':str(source),'target_format':target})
    assert TaskWorker(c.store, production.worker_adapters()).run_once()
    result = c.store.get(job['id'])
    assert result['state']=='succeeded', result
    outputs = list(c.stash.rglob('*.'+target))
    assert len(outputs)==1 and outputs[0].stat().st_size>0
    if target=='ogg':
        subprocess.run(['ffmpeg','-v','error','-i',str(outputs[0]),'-f','null','-'],check=True,timeout=30)
    else:
        subprocess.run(['identify',str(outputs[0])],check=True,capture_output=True,timeout=10)
    assert hashlib.sha256(original.read_bytes()).digest()==before


def test_unreadable_process_metadata_cannot_prove_termination(monkeypatch):
    import tool_process
    class Entry:
        name = '123'
        def __truediv__(self, name):
            return self
        def read_text(self):
            raise PermissionError('Injected unavailable process evidence')
    proc = SimpleNamespace(is_dir=lambda:True, iterdir=lambda:[Entry()])
    monkeypatch.setattr(tool_process, 'Path', lambda path:proc)
    monkeypatch.setattr(tool_process.os, 'killpg', lambda *args:None)
    assert group_alive(SimpleNamespace(pid=123))


@pytest.mark.parametrize('diagnostic', ['x' * (700 * 1024), '\\' * (350 * 1024)], ids=['plain', 'json-escaped'])
def test_oversized_failed_conversion_settles_and_frees_capacity(conversion, tmp_path, monkeypatch, diagnostic):
    c = conversion
    c.store.configure(max_running=1)
    shims = tmp_path / 'failing-backend'
    shims.mkdir()
    marker = tmp_path / 'backend.calls'
    program = shims / 'ffmpeg'
    program.write_text('#!' + sys.executable + '\nimport pathlib,sys\n'
                       + 'with pathlib.Path(' + repr(str(marker)) + ').open("a") as calls: calls.write("run\\n")\n'
                       + 'sys.stderr.write("error head\\n" + ' + repr(diagnostic) + ' + "\\nerror tail")\n'
                       + 'sys.exit(1)\n')
    program.chmod(0o700)
    monkeypatch.setenv('PATH', str(shims) + os.pathsep + os.environ['PATH'])
    job = c.admit()
    worker = TaskWorker(c.store, production.worker_adapters())
    assert worker.run_once()
    finished = c.store.get(job['id'])
    assert finished['state'] == 'failed'
    assert finished['result']['diagnostics_truncated'] is True
    assert 'error head' in finished['result']['error'] and 'error tail' in finished['result']['error']
    from lib.background_tasks.models import MAX_RESULT_BYTES, canonical_json
    assert canonical_json(finished['result'], MAX_RESULT_BYTES)
    assert c.store.counts()['reserved'] == 0
    assert len(c.store.pending_deliveries()) == 1
    assert not worker.run_once()
    next_job = c.admit(invocation='next-call', args={'source':str(tmp_path/'missing.wav'), 'target_format':'flac'})
    assert worker.run_once()
    assert c.store.get(next_job['id'])['state'] == 'failed'
    assert marker.read_text() == 'run\n'


@pytest.mark.parametrize('remaining', [900, 90])
def test_background_conversion_uses_remaining_job_budget(conversion, monkeypatch, remaining):
    import tool_process
    c = conversion
    clock = c.store.clock
    c.store.clock = lambda: time.time() - (900 - remaining)
    job = c.admit()
    c.store.clock = clock
    observed = []
    run = tool_process.run_local_process
    def capture(cmd, *args, **kwargs):
        observed.append((cmd, kwargs, c.store.clock()))
        return run(cmd, *args, **kwargs)
    monkeypatch.setattr(tool_process, 'run_local_process', capture)
    assert TaskWorker(c.store, production.worker_adapters()).run_once()
    assert c.store.get(job['id'])['state'] == 'succeeded'
    cmd, options, now = observed[0]
    assert options['timeout'] == pytest.approx(job['deadline'] - now, abs=.1)
    assert float(cmd[2]) == pytest.approx(options['timeout'])
    assert float(options['tool_env']['JARVIS_BACKGROUND_DEADLINE']) == job['deadline']


@pytest.mark.skipif(os.environ.get('JARVIS_TEST_LONG_ENCODE') != '1', reason='Optional 185-second real-time encode')
def test_background_video_encode_survives_foreground_timeout(conversion, tmp_path, monkeypatch):
    import shlex
    c = conversion
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg and ffprobe are required')
    source = tmp_path / 'generated.mp4'
    subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=2',
                    '-t','1','-pix_fmt','yuv420p',str(source)], check=True, timeout=15)
    shims = tmp_path / 'paced-encoder'
    shims.mkdir()
    shim = shims / 'ffmpeg'
    shim.write_text('#!/bin/sh\nexec '+shlex.quote(ffmpeg)+' -re -stream_loop -1 "$@"\n')
    shim.chmod(0o700)
    monkeypatch.setenv('PATH', str(shims)+os.pathsep+os.environ['PATH'])
    job = c.admit(args={'source':str(source),'target_format':'mp4', 'options':{'duration':185}})
    worker = TaskWorker(c.store, production.worker_adapters())
    stop = threading.Event()
    thread = threading.Thread(target=worker.run_once, args=(stop,))
    started = time.monotonic()
    thread.start()
    try:
        while thread.is_alive() and time.monotonic()-started < 181:
            thread.join(timeout=1)
        assert thread.is_alive(), c.store.get(job['id'])['state']
        assert c.store.get(job['id'])['state']=='running'
        print('Real ffmpeg conversion is still running after 180 seconds', flush=True)
        thread.join(timeout=30)
        assert not thread.is_alive()
        assert c.store.get(job['id'])['state']=='succeeded'
        outputs=list(c.stash.rglob('*.mp4'))
        assert len(outputs)==1
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                              '-of','json',str(outputs[0])],capture_output=True,text=True,check=True,timeout=10)
        assert float(json.loads(probe.stdout)['format']['duration'])==pytest.approx(185,abs=1)
    finally:
        stop.set()
        thread.join(timeout=10)


@pytest.mark.parametrize('diagnostic', ['🛑' * 100000, '\udc80' * 200000, '\0' * 200000],
                         ids=['unicode', 'surrogate', 'control'])
def test_bounded_failure_accounts_for_json_escaping(diagnostic):
    from lib.background_tasks.models import MAX_RESULT_BYTES, canonical_json
    result = bounded_failure({'ok':False, 'error':diagnostic})
    assert result['diagnostics_truncated'] is True
    assert result['ok'] is False
    assert canonical_json(result, MAX_RESULT_BYTES)
