"""Real Apify binding/admission/worker journeys with disposable native HTTP data."""

import importlib
import io
import json
import shutil
import threading
from collections import deque
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from flask import Flask
from server_package_utils import load_server_package
from urllib3.response import HTTPResponse

from lib import apify as provider
from lib import config_loader as package_config
from lib.background_tasks import AdmissionDenied, LostLease, ReceiptEvidence, TaskStore, production
from lib.background_tasks import apify as binding
from lib.background_tasks.admission import BackgroundAdmissionService
from lib.background_tasks.models import remote_checkpoint
from lib.background_tasks.worker import (
    ExecutionContext,
    Interrupted,
    ResumableRemoteAdapter,
    TaskWorker,
)

ROOT = Path(__file__).resolve().parents[1]
ACTOR = 'Actor123'
BUILD = 'Build123'
RUN = 'Run123'
DATASET = 'Dataset123'
HANDLE = {'run_id': RUN, 'actor_id': ACTOR, 'build_id': BUILD,
          'default_dataset_id': DATASET}
ARGUMENTS = {'actor': 'fixture/scraper', 'input': {'query': 'fixture query'}}


class Response:
    def __init__(self, value, status=200):
        self.status_code = status
        self.headers = {'Content-Type': 'application/json'}
        self.raw = HTTPResponse(body=io.BytesIO(json.dumps(value).encode()),
                                headers=self.headers, preload_content=False)

    def close(self):
        self.raw.close()


class NativePlatform:
    """Only the transport is replaced; prepare/start/poll/collect stay real."""

    def __init__(self):
        self.statuses = deque(['SUCCEEDED'])
        self.calls = []
        self.tokens = []
        self.get_failures = 0
        self.submit_lost = False
        self.abort_lost = False
        self.receipt_build = BUILD
        self.read_build = BUILD
        self.build_status = 'SUCCEEDED'
        self.details = {'id': ACTOR, 'username': 'fixture', 'name': 'scraper',
                        'actorPermissionLevel': 'LIMITED_PERMISSIONS',
                        'defaultRunOptions': {'memoryMbytes': 128}}
        self.lookup_overrides = {}
        self.on_call = None

    @property
    def submissions(self):
        return [call for call in self.calls if call[:2] == ('POST', f'/acts/{ACTOR}/runs')]

    @property
    def aborts(self):
        return [call for call in self.calls if call[:2] == ('POST', f'/actor-runs/{RUN}/abort')]

    @property
    def reads(self):
        return [call for call in self.calls if call[:2] == ('GET', f'/actor-runs/{RUN}')]

    def run(self, status):
        return {'id': RUN, 'actId': ACTOR, 'buildId': self.read_build, 'status': status,
                'defaultDatasetId': DATASET, 'startedAt': '2026-01-01T00:00:00Z'}

    def __call__(self, method, url, **kwargs):
        assert url.startswith(provider.API_BASE + '/')
        path = url.removeprefix(provider.API_BASE)
        self.calls.append((method, path, kwargs.get('params')))
        self.tokens.append(kwargs['headers']['Authorization'])
        assert kwargs['proxy_policy'] == 'off'
        assert kwargs['allow_redirects'] is False
        assert kwargs['timeout'] <= 10
        if self.on_call:
            self.on_call(method, path)
        if method == 'GET' and path in self.lookup_overrides:
            return Response({'data': self.lookup_overrides[path]})
        actor_path = '/acts/' + self.details['username'] + '~' + self.details['name']
        if method == 'GET' and path in {actor_path, '/acts/' + ACTOR}:
            return Response({'data': self.details})
        if (method, path) == ('GET', f'/acts/{ACTOR}/builds/default'):
            return Response({'data': {'id': BUILD, 'actId': ACTOR, 'status': self.build_status,
                'buildNumber': '1.2.3', 'actorDefinition': {'input': {'type': 'object',
                    'properties': {'query': {'type': 'string'}}, 'required': ['query'],
                    'additionalProperties': False}}}})
        if (method, path) == ('POST', f'/acts/{ACTOR}/runs'):
            assert kwargs['json'] == ARGUMENTS['input']
            assert kwargs['params']['build'] == '1.2.3'
            if self.submit_lost:
                raise requests.Timeout('Fixture lost the native submission receipt')
            return Response({'data': {**self.run('READY'), 'buildId': self.receipt_build}})
        if (method, path) == ('GET', f'/actor-runs/{RUN}'):
            if self.get_failures:
                self.get_failures -= 1
                raise requests.ConnectionError('Fixture transient GET failure')
            status = self.statuses.popleft() if len(self.statuses) > 1 else self.statuses[0]
            return Response({'data': self.run(status)})
        if (method, path) == ('POST', f'/actor-runs/{RUN}/abort'):
            if self.abort_lost:
                raise requests.Timeout('Fixture lost the abort receipt')
            return Response({'data': self.run('ABORTING')})
        if (method, path) == ('GET', f'/datasets/{DATASET}'):
            return Response({'data': {'id': DATASET, 'itemCount': 2}})
        if (method, path) == ('GET', f'/datasets/{DATASET}/items'):
            return Response([{'url': 'https://fixture.invalid/one', 'nested': [False, None]},
                             {'url': 'https://fixture.invalid/two', 'count': 0}])
        pytest.fail(f'Unexpected fixture HTTP operation: {method} {path}')


@pytest.fixture
def integration(tmp_path, monkeypatch):
    import config_loader
    import tool_profiles

    from lib.webhook_integrations import private_bindings

    root = tmp_path / 'installation'
    (root / 'config').mkdir(parents=True)
    (root / 'skills' / 'profiles').mkdir(parents=True)
    (root / 'lib').mkdir()
    for name in ('apify_run_actor.py', 'apify_run_actor.tool.json'):
        shutil.copyfile(ROOT / 'skills' / name, root / 'skills' / name)
    shutil.copyfile(ROOT / 'lib' / 'apify.py', root / 'lib' / 'apify.py')
    copied_binding = root / 'lib' / 'apify_binding.py'
    shutil.copyfile(Path(binding.__file__), copied_binding)
    for mode in ('cloud', 'local'):
        (root / 'config' / f'{mode}.env').write_text(
            f'APIFY_MCP_ENABLED=true\nAPIFY_TOKEN=fixture-{mode}\nAPIFY_POLL_SECONDS=5\n'
            'JARVIS_TOOL_PROFILE=default\nAPIFY_RUN_TIMEOUT_SECONDS=1800\n'
            'APIFY_MAX_MEMORY_MB=2048\nAPIFY_MAX_CHARGE_USD=1\nAPIFY_RESULT_PAGE_SIZE=20\n'
            'APIFY_ALLOWED_ACTORS=fixture/scraper\n'
            f'STASH_DIR={tmp_path / (mode + "-stash")}\n')
    monkeypatch.setattr(package_config, 'get_project_root', lambda: root)
    monkeypatch.setattr(config_loader, 'get_project_root', lambda: root)
    monkeypatch.setattr(tool_profiles, 'get_profiles_dir', lambda: root / 'skills' / 'profiles')
    monkeypatch.setenv('STASH_DIR', str(tmp_path / 'fallback-stash'))
    monkeypatch.delenv('JARVIS_OVERRIDE_STASH_DIR', raising=False)
    monkeypatch.setattr(binding, 'ROOT', root)
    monkeypatch.setattr(binding, '__file__', str(copied_binding))
    original_policy = binding.policy
    monkeypatch.setattr(binding, 'policy', lambda: original_policy(root))
    monkeypatch.setattr(production, 'ROOT', root)
    monkeypatch.setattr(production, 'bindings', lambda: {binding.TOOL: binding.ADAPTER})
    monkeypatch.setattr(private_bindings, 'bindings', lambda: {})
    clock = [1000.0]
    store = TaskStore(tmp_path / 'tasks.db', clock=lambda: clock[0])
    store.initialize()
    store.configure(background_enabled=True, background_tools=[binding.TOOL],
                    max_running=1, max_per_adapter=1)
    native = NativePlatform()
    monkeypatch.setattr(binding, 'ApifyClient',
                        lambda settings=None: provider.ApifyClient(settings, request=native))
    return SimpleNamespace(root=root, clock=clock, store=store, native=native)


def admit(h, *, mode='cloud', arguments=None, invocation='invoke-1', timeout=None):
    from config_loader import config_scope

    with config_scope(mode):
        schema, evidence = binding.policy()
        payload = {'operator': 'installation', 'source': 'web', 'conversation_id': 'conversation-1',
            'generation': 1, 'request_id': 'request-' + invocation, 'mode': mode,
            'selected': [binding.TOOL], 'tool_policy': 'auto',
            'tool_policies': {binding.TOOL: evidence}}
        service = BackgroundAdmissionService(h.store, adapters={binding.TOOL: binding.ADAPTER},
            validate_source=lambda _: True, ready=lambda: True)
        h.store.touch_worker('fixture-ready', {binding.ADAPTER})
        registry = SimpleNamespace(list_tools=lambda: [binding.TOOL], get_tool=lambda _: schema)
        context = service.authorize(payload, registry)
        receipt = context.admit(binding.TOOL, ARGUMENTS if arguments is None else arguments,
                                invocation, schema)
    job = h.store.get(receipt['job_id'])
    if timeout is not None:
        # A short observation budget is a fixture of an already admitted job;
        # it does not change the production manifest or provider's native limit.
        with h.store._connection(write=True) as conn:
            conn.execute('UPDATE jobs SET deadline=? WHERE id=?', (h.clock[0] + timeout, job['id']))
    source = job['admission']
    return h.store.release(job['id'], ReceiptEvidence(source['conversation_id'], source['generation'],
        source['request_id'], 'receipt-' + invocation, 'completed', True))


def worker(h):
    return TaskWorker(h.store, {binding.ADAPTER: binding.worker_adapter()})


def configure_mode(h, mode, **values):
    """Change only the disposable installation's selected-mode settings."""
    path = h.root / 'config' / f'{mode}.env'
    current = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)
    current.update({key: str(value) for key, value in values.items()})
    path.write_text(''.join(f'{key}={value}\n' for key, value in current.items()))


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_real_production_binding_pins_policy_and_delivers_provider_neutral_dataset(integration, mode):
    import config_loader

    h = integration
    with config_loader.config_scope(mode):
        policies = production.authorize_tools([binding.TOOL])
        assert policies[binding.TOOL]['timeout_seconds'] == 3600
    assert production.TRUSTED_BINDINGS[binding.TOOL] == binding.ADAPTER
    assert isinstance(production.worker_adapters()[binding.ADAPTER], ResumableRemoteAdapter)
    job = admit(h, mode=mode)
    assert job['admission']['timeout_seconds'] == 3600
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'succeeded'
    assert saved['delivery_state'] == 'pending'
    data = saved['result']['data']
    assert data['contract'] == 'external_result_v1'
    assert data['source']['mode'] == mode
    assert data['execution']['run_id'] == RUN
    assert data['result']['kind'] == 'dataset'
    assert data['result']['complete'] is True
    assert data['result']['sample_items'][0]['nested'] == [False, None]
    assert data['raw_ref'].startswith('stash://')
    from stash_helper import get_space, parse_stash_ref

    with config_loader.config_scope(mode):
        space_id, _file_id = parse_stash_ref(data['raw_ref'])
        assert get_space(space_id).space_path.parent == h.root.parent / (mode + '-stash')
    assert h.native.tokens and set(h.native.tokens) == {'Bearer fixture-' + mode}
    assert len(h.native.submissions) == 1
    assert not worker(h).run_once()
    assert 'fixture-' + mode not in json.dumps(saved)


@pytest.mark.parametrize('arguments', [
    {'actor': 'fixture/scraper', 'input': []},
    {'actor': 'fixture/scraper', 'input': {}, 'token': 'unrequested'},
    {'actor': 'fixture/scraper'},
])
def test_admission_rejects_invalid_gateway_arguments_before_job_or_http(integration, arguments):
    h = integration
    with pytest.raises(AdmissionDenied, match='arguments'):
        admit(h, arguments=arguments)
    assert h.store.list_jobs()['total'] == 0
    assert h.native.calls == []


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_actor_input_schema_denial_never_submits_a_paid_run(integration, mode):
    h = integration
    job = admit(h, mode=mode, arguments={'actor': 'fixture/scraper', 'input': {'query': 7}})
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'failed'
    assert saved['result']['completion'] == 'rejected'
    assert len(h.native.calls) == 2  # Resolve Actor/build, validate before POST.
    assert h.native.submissions == []
    assert h.store.counts()['reserved'] == 0


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('surface', ['background', 'foreground'])
@pytest.mark.parametrize('mismatch', ['canonical_to_official', 'native_id_to_trusted'])
def test_another_eligible_actor_cannot_replace_the_requested_actor(integration, mode, surface, mismatch):
    from config_loader import config_scope

    h = integration
    details = dict(h.native.details)
    if mismatch == 'canonical_to_official':
        requested = ARGUMENTS['actor']
        details.update(username='apify', name='different-official-actor')
    else:
        requested = 'RequestedActor456'
    # Both response bodies describe eligible Actors: an official Actor or the
    # fixture's explicitly trusted community Actor. Trust alone is insufficient.
    path = '/acts/' + requested.replace('/', '~')
    h.native.lookup_overrides[path] = details
    arguments = {**ARGUMENTS, 'actor': requested}
    if surface == 'background':
        job = admit(h, mode=mode, arguments=arguments)
        assert worker(h).run_once()
        saved = h.store.get(job['id'])
        assert saved['state'] == 'failed'
        assert saved['result']['completion'] == 'rejected'
        assert h.store.counts()['reserved'] == 0
        assert not worker(h).run_once()
    else:
        with package_config.config_scope(mode), config_scope(mode):
            client = provider.ApifyClient(request=h.native)
            with pytest.raises(provider.ApifyError):
                provider.run_actor(arguments, client=client)
        assert h.store.list_jobs()['total'] == 0
    assert [call[:2] for call in h.native.calls] == [('GET', path)]
    assert h.native.submissions == []


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('ceiling', [1536, 2048.5])
def test_invalid_start_memory_ceiling_releases_admission_without_any_http(integration, mode, ceiling):
    h = integration
    configure_mode(h, mode, APIFY_MAX_MEMORY_MB=ceiling)
    job = admit(h, mode=mode)
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'failed'
    assert saved['result']['completion'] == 'rejected'
    assert h.store.counts()['reserved'] == 0
    assert h.native.calls == []
    assert not worker(h).run_once()


def test_transient_status_failure_keeps_same_run_and_backoff_then_collects(integration, monkeypatch):
    h = integration
    h.native.get_failures = 1
    h.native.statuses = deque(['RUNNING', 'SUCCEEDED'])
    delays = []

    def wait(context, seconds, *, allow_cancel=False):
        delays.append(seconds)
        context.checkpoint(allow_cancel=allow_cancel)

    monkeypatch.setattr(ExecutionContext, 'wait', wait)
    job = admit(h)
    assert worker(h).run_once()
    assert h.store.get(job['id'])['state'] == 'succeeded'
    assert len(h.native.submissions) == 1
    assert len(h.native.reads) == 3
    assert delays == [10, 5]


def test_ambiguous_paid_post_has_no_checkpoint_and_is_never_repeated(integration):
    h = integration
    h.native.submit_lost = True
    job = admit(h)
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert remote_checkpoint(binding.ADAPTER, saved['progress']) is None
    assert saved['result']['completion'] == 'unknown'
    h.clock[0] += 31
    assert not worker(h).run_once()
    assert len(h.native.submissions) == 1


def test_cancel_during_actor_preparation_never_starts_native_submission(integration):
    h = integration
    job = admit(h)

    def cancel_before_submit(method, path):
        if (method, path) == ('GET', f'/acts/{ACTOR}/builds/default'):
            saved = h.store.get(job['id'])
            h.store.request_cancel(job['id'], saved['revision'], supported_adapters={binding.ADAPTER})

    h.native.on_call = cancel_before_submit
    assert worker(h).run_once()
    assert h.store.get(job['id'])['state'] == 'cancelled'
    assert h.native.submissions == []
    assert h.native.aborts == []


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('phase', ['actor', 'build'])
def test_worker_stop_during_preparation_is_definitive_failure_before_submission(integration, monkeypatch, mode, phase):
    import llm_provider

    h = integration
    job = admit(h, mode=mode)
    stop = threading.Event()
    target = '/acts/fixture~scraper' if phase == 'actor' else f'/acts/{ACTOR}/builds/default'

    def stop_during_preparation(method, path):
        if (method, path) == ('GET', target):
            stop.set()

    h.native.on_call = stop_during_preparation
    assert worker(h).run_once(stop)
    saved = h.store.get(job['id'])
    assert saved['state'] == 'failed'
    assert saved['result']['completion'] == 'rejected'
    assert 'before provider submission' in saved['result']['speech'].lower()
    assert h.native.submissions == []
    assert remote_checkpoint(binding.ADAPTER, saved['progress']) is None
    assert h.store.counts()['reserved'] == h.store.counts()['running'] == 0
    assert not worker(h).run_once()

    # Project the actual saved failure through Web's generic late-answer path.
    # No uncertain-provider warning or native retry is introduced by delivery.
    alias = 'apify_stopped_preparation_test_server'
    load_server_package(alias, ROOT / 'jarvis-web' / 'server')
    web = importlib.import_module(alias + '.services.background_tasks').WebBackgroundTasks
    prompts = []

    def chat(prompt, **kwargs):
        prompts.append(json.loads(prompt))
        return saved['result']['speech']

    def provider_factory(**kwargs):
        assert kwargs['mode'] == mode
        assert kwargs['disable_server_side_tools'] is True
        return 'fixture', 'fixture-model', SimpleNamespace(chat=chat)

    monkeypatch.setattr(llm_provider, 'create_configured_provider', provider_factory)
    handler = SimpleNamespace(_prepare_web_response_text=lambda result, text: (text, text))
    background = web(handler, adapters={})
    card = background.card(saved)
    assert card['state'] == 'failed'
    assert not card['can_reconcile']
    reply = background._synthesize(saved, {'provider': 'fixture', 'model': 'fixture-model'},
        {'messages': [{'role': 'user', 'content': 'Scrape fixture query',
                       'data': {'_request_id': saved['admission']['request_id']}}]})
    assert prompts[0]['state'] == 'failed'
    assert prompts[0]['result']['completion'] == 'rejected'
    assert '_background_attention' not in reply['data']
    assert reply['data'][binding.TOOL]['completion'] == 'rejected'
    assert 'may still be running' not in reply['text'].lower()
    assert h.native.submissions == []


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_worker_stop_inside_post_without_receipt_keeps_uncertainty_and_never_resubmits(integration, mode):
    h = integration
    job = admit(h, mode=mode)
    stop = threading.Event()

    def stop_inside_submission(method, path):
        if (method, path) == ('POST', f'/acts/{ACTOR}/runs'):
            stop.set()
            raise Interrupted('Fixture observer stopped while native POST was in flight')

    h.native.on_call = stop_inside_submission
    assert worker(h).run_once(stop)
    saved = h.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert saved['result']['completion'] == 'unknown'
    assert remote_checkpoint(binding.ADAPTER, saved['progress']) is None
    assert h.store.counts()['reserved'] == 1
    h.clock[0] += 31
    assert not worker(h).run_once()
    assert len(h.native.submissions) == 1


def test_unexpected_native_build_keeps_saved_run_but_never_accepts_wrong_output(integration):
    h = integration
    h.native.receipt_build = h.native.read_build = 'UnexpectedBuild'
    job = admit(h)
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert remote_checkpoint(binding.ADAPTER, saved['progress'])['build_id'] == BUILD
    assert saved['result']['data']['run_id'] == RUN
    assert len(h.native.submissions) == 1
    assert not worker(h).run_once()


def test_completed_run_with_unavailable_dataset_stays_successful_and_collectable(integration):
    h = integration
    job = admit(h)

    def fail_collection(method, path):
        if (method, path) == ('GET', f'/datasets/{DATASET}'):
            raise requests.ConnectionError('Fixture dataset unavailable after native completion')

    h.native.on_call = fail_collection
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'succeeded'
    assert saved['result']['data']['limits']['collection_incomplete'] is True
    assert saved['result']['data']['execution']['run_id'] == RUN
    assert len(h.native.submissions) == 1


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_worker_loss_resumes_native_get_only_with_new_fence_and_existing_capacity(integration, monkeypatch, mode):
    h = integration
    h.native.statuses = deque(['RUNNING', 'SUCCEEDED'])
    previous = []
    job = admit(h, mode=mode)

    def lose_lease(context, seconds, **kwargs):
        previous.append(context.claim)
        h.clock[0] += 31
        raise LostLease('Fixture worker vanished after persisting native receipt')

    with monkeypatch.context() as patch:
        patch.setattr(ExecutionContext, 'wait', lose_lease)
        assert worker(h).run_once()
    old = previous[0]
    saved = h.store.get(job['id'])
    assert saved['state'] == 'running'
    assert remote_checkpoint(binding.ADAPTER, saved['progress']) == HANDLE
    second = admit(h, mode=mode, invocation='second')
    assert h.store.counts()['running'] == 1
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'succeeded'
    assert saved['mode'] == saved['result']['data']['source']['mode'] == mode
    assert saved['fence'] == old.fence + 1
    assert saved['deadline'] == job['deadline']
    assert len(h.native.submissions) == 1
    assert h.store.get(second['id'])['state'] == 'queued'
    with pytest.raises(LostLease):
        h.store.finish(old, {'ok': True})


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('invalid_ceiling', [1536, 2048.5])
def test_graceful_shutdown_then_removed_trust_and_invalid_start_settings_still_observes_saved_run(integration, monkeypatch, mode, invalid_ceiling):
    h = integration
    h.native.statuses = deque(['RUNNING', 'SUCCEEDED'])
    job = admit(h, mode=mode)
    stop = threading.Event()

    def shutdown(context, seconds, **kwargs):
        stop.set()
        context.checkpoint()

    with monkeypatch.context() as patch:
        patch.setattr(ExecutionContext, 'wait', shutdown)
        assert worker(h).run_once(stop)
    configure_mode(h, mode, APIFY_MCP_ENABLED='false', APIFY_ALLOWED_ACTORS='',
                   APIFY_MAX_MEMORY_MB=invalid_ceiling)
    h.store.configure(background_enabled=False, background_tools=[])
    assert worker(h).run_once()
    assert h.store.get(job['id'])['state'] == 'succeeded'
    assert h.store.get(job['id'])['result']['data']['source']['mode'] == mode
    assert len(h.native.submissions) == 1


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_official_actor_remains_eligible_with_unrelated_trusted_community_exceptions(integration, mode):
    h = integration
    h.native.details['username'] = 'apify'
    configure_mode(h, mode, APIFY_ALLOWED_ACTORS='other/trusted-community-actor')
    arguments = {**ARGUMENTS, 'actor': 'apify/scraper'}
    job = admit(h, mode=mode, arguments=arguments)
    assert worker(h).run_once()
    assert h.store.get(job['id'])['state'] == 'succeeded'
    assert len(h.native.submissions) == 1


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_high_ratings_and_usage_do_not_authorize_an_untrusted_community_actor(integration, mode):
    h = integration
    h.native.details['stats'] = {'actorReviewRating': 5, 'actorReviewCount': 1000,
                                 'totalRuns': 1000000, 'totalUsers30Days': 10000}
    configure_mode(h, mode, APIFY_ALLOWED_ACTORS='')
    job = admit(h, mode=mode)
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'failed'
    assert saved['result']['completion'] == 'rejected'
    assert h.native.submissions == []
    assert len(h.native.calls) == 1
    assert h.store.counts()['reserved'] == 0
    assert not worker(h).run_once()


@pytest.mark.parametrize('trusted_mode', ['cloud', 'local'])
def test_community_exception_cannot_leak_into_another_jobs_execution_mode(integration, trusted_mode):
    h = integration
    other_mode = 'local' if trusted_mode == 'cloud' else 'cloud'
    configure_mode(h, trusted_mode, APIFY_ALLOWED_ACTORS=ACTOR)
    configure_mode(h, other_mode, APIFY_ALLOWED_ACTORS='')
    accepted = admit(h, mode=trusted_mode, invocation='trusted-mode')
    h.clock[0] += 1
    rejected = admit(h, mode=other_mode, invocation='other-mode')
    observer = worker(h)
    assert observer.run_once()
    assert observer.run_once()
    assert h.store.get(accepted['id'])['state'] == 'succeeded'
    assert h.store.get(rejected['id'])['state'] == 'failed'
    assert len(h.native.submissions) == 1
    assert h.native.tokens[-1] == 'Bearer fixture-' + other_mode


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('exception', [ACTOR, 'fixture/scraper'])
def test_explicit_trusted_community_exception_allows_unrated_actor_and_preserves_run_caps(integration, mode, exception):
    h = integration
    h.native.details['stats'] = {'actorReviewRating': 0, 'actorReviewCount': 0,
                                 'totalRuns': 0, 'totalUsers30Days': 0}
    configure_mode(h, mode, APIFY_ALLOWED_ACTORS=exception, APIFY_RUN_TIMEOUT_SECONDS=90,
                   APIFY_MAX_MEMORY_MB=128, APIFY_MAX_CHARGE_USD=0.25)
    job = admit(h, mode=mode)
    assert worker(h).run_once()
    assert h.store.get(job['id'])['state'] == 'succeeded'
    assert len(h.native.submissions) == 1
    options = h.native.submissions[0][2]
    assert options['timeout'] == 90
    assert options['memory'] == 128
    assert options['maxTotalChargeUsd'] == 0.25
    assert options['build'] == '1.2.3'
    assert options['forcePermissionLevel'] == 'LIMITED_PERMISSIONS'


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_explicit_trust_does_not_allow_a_full_permission_actor(integration, mode):
    h = integration
    h.native.details['actorPermissionLevel'] = 'FULL_PERMISSIONS'
    configure_mode(h, mode, APIFY_ALLOWED_ACTORS=ACTOR)
    job = admit(h, mode=mode)
    assert worker(h).run_once()
    assert h.store.get(job['id'])['state'] == 'failed'
    assert h.native.submissions == []
    assert len(h.native.calls) == 1


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_explicit_trust_does_not_allow_an_unverified_actor_build(integration, mode):
    h = integration
    h.native.build_status = 'FAILED'
    configure_mode(h, mode, APIFY_ALLOWED_ACTORS=ACTOR)
    job = admit(h, mode=mode)
    assert worker(h).run_once()
    assert h.store.get(job['id'])['state'] == 'failed'
    assert h.native.submissions == []
    assert len(h.native.calls) == 2


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('owner,exceptions,accepted', [
    ('apify', 'other/trusted', True),
    ('fixture', '', False),
    ('fixture', ACTOR, True),
])
def test_foreground_gateway_uses_same_trust_policy_before_native_submission(integration, mode, owner, exceptions, accepted):
    from config_loader import config_scope

    h = integration
    h.native.details['username'] = owner
    configure_mode(h, mode, APIFY_ALLOWED_ACTORS=exceptions)
    arguments = {**ARGUMENTS, 'actor': owner + '/scraper'}
    with package_config.config_scope(mode), config_scope(mode):
        client = provider.ApifyClient(request=h.native)
        if accepted:
            result = provider.run_actor(arguments, client=client)
            assert result['ok'] is True
            assert result['data']['execution']['run_id'] == RUN
            assert result['data']['source']['mode'] == mode
            assert result['data']['result']['complete'] is False
            assert len(h.native.submissions) == 1
        else:
            with pytest.raises(provider.ApifyError):
                provider.run_actor(arguments, client=client)
            assert h.native.submissions == []
    assert h.store.list_jobs()['total'] == 0


def test_observation_deadline_keeps_native_recovery_evidence_without_claiming_failure(integration, monkeypatch):
    h = integration
    h.native.statuses = deque(['RUNNING'])
    job = admit(h, timeout=10)

    def expire(context, seconds, **kwargs):
        h.clock[0] += 11
        context.checkpoint()

    monkeypatch.setattr(ExecutionContext, 'wait', expire)
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert saved['result']['data']['run_id'] == RUN
    assert saved['result']['completion'] == 'unknown'
    assert not worker(h).run_once()
    assert len(h.native.submissions) == 1


@pytest.mark.parametrize('abort_lost', [False, True])
def test_cancelled_before_observe_waits_for_confirmed_native_abort(integration, monkeypatch, abort_lost):
    h = integration
    job = admit(h)
    claim = h.store.claim('vanished-worker', {binding.ADAPTER})
    h.store.running(claim)
    h.store.checkpoint_remote(claim, HANDLE)
    saved = h.store.get(job['id'])
    h.store.request_cancel(job['id'], saved['revision'], supported_adapters={binding.ADAPTER})
    h.clock[0] += 31
    h.native.statuses = deque(['RUNNING', 'ABORTING', 'ABORTED'])
    h.native.abort_lost = abort_lost
    monkeypatch.setattr(ExecutionContext, 'wait',
                        lambda context, seconds, **kwargs: context.checkpoint(allow_cancel=True))
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'cancelled'
    assert saved['delivery_state'] == 'suppressed'
    assert h.native.submissions == []
    assert len(h.native.aborts) == 1
    assert len(h.native.reads) == 3


def test_new_cancellation_interrupts_configured_five_minute_poll(integration, monkeypatch):
    h = integration
    path = h.root / 'config' / 'cloud.env'
    path.write_text(path.read_text().replace('APIFY_POLL_SECONDS=5', 'APIFY_POLL_SECONDS=300'))
    h.native.statuses = deque(['RUNNING', 'RUNNING', 'ABORTING', 'ABORTED'])
    job = admit(h)
    entered = threading.Event()
    stop = threading.Event()
    original_wait = ExecutionContext.wait
    errors = []

    def wait(context, seconds, *, allow_cancel=False):
        if not allow_cancel:
            assert seconds == 300
            entered.set()
            return original_wait(context, seconds, allow_cancel=False)
        context.checkpoint(allow_cancel=True)

    def execute():
        try:
            worker(h).run_once(stop)
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(ExecutionContext, 'wait', wait)
    thread = threading.Thread(target=execute)
    thread.start()
    try:
        assert entered.wait(3), errors
        saved = h.store.get(job['id'])
        h.store.request_cancel(job['id'], saved['revision'], supported_adapters={binding.ADAPTER})
        thread.join(3)
        assert not thread.is_alive(), 'A new cancellation waited for the five-minute poll interval'
        assert not errors
        assert h.store.get(job['id'])['state'] == 'cancelled'
        assert len(h.native.submissions) == len(h.native.aborts) == 1
    finally:
        stop.set()
        thread.join(5)


def test_native_success_wins_a_racing_cancel_request(integration):
    h = integration
    job = admit(h)

    def cancel_during_read(method, path):
        if (method, path) == ('GET', f'/actor-runs/{RUN}'):
            saved = h.store.get(job['id'])
            h.store.request_cancel(job['id'], saved['revision'], supported_adapters={binding.ADAPTER})

    h.native.on_call = cancel_during_read
    assert worker(h).run_once()
    saved = h.store.get(job['id'])
    assert saved['state'] == 'succeeded'
    assert saved['delivery_state'] == 'pending'
    assert not saved['cancelled']
    assert h.native.aborts == []


@pytest.mark.parametrize('gate', ['profile', 'manifest', 'web_block', 'provider_hash'])
def test_accepted_job_rechecks_trusted_submission_policy_before_any_http(integration, gate):
    h = integration
    job = admit(h)
    if gate == 'profile':
        (h.root / 'skills' / 'profiles' / 'default.json').write_text(
            json.dumps({'overrides': {binding.TOOL: False}}))
    elif gate == 'manifest':
        path = h.root / 'skills' / f'{binding.TOOL}.tool.json'
        manifest = json.loads(path.read_text())
        manifest['enabled'] = False
        path.write_text(json.dumps(manifest))
    elif gate == 'provider_hash':
        (h.root / 'lib' / 'apify.py').write_text('# Changed after admission\n')
    else:
        path = h.root / 'jarvis-web' / 'config' / 'web_config.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'tools': {'blocked': [binding.TOOL]}}))
    assert worker(h).run_once()
    assert h.store.get(job['id'])['state'] == 'failed'
    assert h.native.calls == []


def test_task_card_and_authenticated_cancel_route_control_same_native_handle(integration, monkeypatch):
    import webui_auth

    h = integration
    alias = 'apify_background_test_server'
    load_server_package(alias, ROOT / 'jarvis-web' / 'server')
    routes = importlib.import_module(alias + '.routes.background_tasks')
    web = importlib.import_module(alias + '.services.background_tasks').WebBackgroundTasks
    job = admit(h)
    claim = h.store.claim('vanished-worker', {binding.ADAPTER})
    h.store.running(claim)
    h.store.checkpoint_remote(claim, HANDLE)
    app = Flask(__name__)
    app.extensions['jarvis_background_tasks'] = SimpleNamespace(
        store=h.store, card=web.card,
        handler=SimpleNamespace(runs=SimpleNamespace(conversation_lock=lambda _: nullcontext())),
    )
    app.register_blueprint(routes.background_bp)
    monkeypatch.setattr(webui_auth, 'is_auth_enabled', lambda: True)
    monkeypatch.setattr(webui_auth, 'verify_token', lambda token: token == 'fixture-operator')
    http = app.test_client()
    headers = {'Authorization': 'Bearer fixture-operator', 'Origin': 'http://localhost'}
    shown = http.get('/api/background-jobs', headers=headers).get_json()['jobs'][0]
    assert shown['job_id'] == job['id']
    assert shown['remote_work'] and shown['can_cancel']
    assert http.post(f'/api/background-jobs/{job["id"]}/actions', headers=headers,
        json={'action': 'cancel', 'revision': shown['revision']}).status_code == 200
    shown = http.get('/api/background-jobs', headers=headers).get_json()['jobs'][0]
    assert shown['state'] == 'cancel_requested'
    assert not shown['can_cancel']
    assert shown['progress']['recovery']['run_id'] == RUN
    h.native.statuses = deque(['RUNNING', 'ABORTED'])
    h.clock[0] += 31
    monkeypatch.setattr(ExecutionContext, 'wait',
                        lambda context, seconds, **kwargs: context.checkpoint(allow_cancel=True))
    assert worker(h).run_once()
    assert h.store.get(job['id'])['state'] == 'cancelled'
    assert len(h.native.aborts) == 1
    assert h.native.submissions == []
