"""Watch-state workflow boundaries preserve confirmed delivery and health truth."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator import pipeline_executor
from orchestrator.pipeline_executor import PipelineExecutor

ROOT = Path(__file__).resolve().parents[1]


def _workflow(name):
    return json.loads((ROOT / 'data/workflows' / f'{name}.json').read_text())


@pytest.fixture(autouse=True)
def isolated_pipeline(monkeypatch):
    logger = SimpleNamespace(log_tool_call=lambda **kwargs: None,
                             log_workflow_execution=lambda **kwargs: None,
                             log_llm_call=lambda **kwargs: None)
    monkeypatch.setattr(pipeline_executor, 'ToolLogger', lambda: logger)
    monkeypatch.setattr(pipeline_executor, 'LLMLogger', lambda: logger)


class RadarProvider:
    def __init__(self, media):
        self.media = media
        self.prompts = []
        self.outputs = []

    def chat_with_tools(self, messages, tools, **kwargs):
        assert tools == []
        prompt = messages[0]['content']
        self.prompts.append(prompt)
        if 'plain-text' in prompt:
            content = prompt.split('\n\n', 1)[1].split('\n\nExplain why', 1)[0]
        else:
            # Echo the resolved requested document, including its run log. A
            # forgotten template variable must reach the real output validator.
            marker = ('Required full-page structure:\n' if 'Required full-page structure:\n' in prompt
                      else 'Required structure:\n')
            content = prompt.split(marker, 1)[1]
        self.outputs.append(content)
        return content, None, {}, None


class RadarTools:
    """Mock collection/delivery boundaries; leave actual workflow sequencing intact."""

    def __init__(self, media, *, handled=None, email=None, failure=None, existing_page=''):
        self.media = media
        self.key = f'upcoming_{media}_radar'
        self.handled = handled if handled is not None else set()
        self.email = email or {'ok': True, 'data': {'status': 'sent', 'to': 'reader@example.test'}}
        self.failure = failure
        self.existing_page = existing_page
        self.calls = []
        self.canvas = []

    def execute(self, tool, params):
        self.calls.append((tool, deepcopy(params)))
        action = params.get('action')
        if self.failure is not None and self.failure in {action, tool}:
            return {'ok': False, 'error': 'Controlled storage/publication failure'}
        if tool == 'get_time':
            data = {'date_formatted': 'November 13, 2026', 'date': '2026-11-13',
                    'time_12h': '10:00 AM', 'time': '10:00'}
        elif tool == 'watch_state' and action == 'radar_history':
            assert params['key'] == self.key
            data = {'key': self.key, 'handled_ids': sorted(self.handled)}
        elif tool == 'watch_state' and action == 'record_delivery':
            assert params['key'] == self.key and params['channel'] == 'email'
            assert params['receipt'] == self.email
            assert params['receipt']['ok'] is True and params['receipt']['data']['status'] == 'sent'
            assert params['destination'] == 'reader@example.test'
            self.handled.add(str(params['record']['tmdb_id']))
            data = {'key': self.key, 'recorded': True}
        elif tool in {'tmdb_movies', 'tmdb_tv_shows'}:
            genre = 'Science Fiction' if self.media == 'movie' else 'Sci-Fi & Fantasy'
            date_key = 'release_date' if self.media == 'movie' else 'first_air_date'
            rows = [{'tmdb_id': index, 'title': f'Fixture {index}', 'year': 2027,
                     date_key: '2027-01-01', 'genres': [genre], 'overview': 'A future release.',
                     'tmdb_url': f'https://www.themoviedb.org/{"movie" if self.media == "movie" else "tv"}/{index}',
                     'poster_url': f'https://image.tmdb.org/t/p/w500/{index}.jpg'} for index in range(101, 111)]
            if action == 'discover':
                excluded = params['exclude_movie_ids' if self.media == 'movie' else 'exclude_show_ids']
                rows = [row for row in rows if str(row['tmdb_id']) not in excluded]
                data = {'results': rows, 'selection_criteria': {'genres': [genre]},
                        'excluded_result_count': len(excluded), 'attribution_notice': 'TMDB fixture attribution'}
            else:
                identifier = params['movie_id' if self.media == 'movie' else 'show_id']
                data = {'movie' if self.media == 'movie' else 'show': next(row for row in rows if row['tmdb_id'] == identifier)}
        elif tool == 'brave_llm_context':
            data = {'grounding': '', 'sources': []}
        elif tool == 'canvas':
            if action == 'read':
                data = {'page_id': self.existing_page, 'content': 'Earlier fixture pick.' if self.existing_page else ''}
            else:
                self.canvas.append(params['content'])
                data = {'page_id': 'page_radar_fixture', 'url': 'https://canvas.example.test/page_radar_fixture'}
        elif tool == 'send_email':
            return deepcopy(self.email)
        else:
            raise AssertionError((tool, params))
        return {'ok': True, 'data': data}


def _run_radar(tools, *, mode='cloud', request_email=True):
    executor = PipelineExecutor(mode, tools, provider=RadarProvider(tools.media))
    query = f'/{tools.key} science fiction' + (', email me the pick' if request_email else '')
    return executor.execute(_workflow(tools.key), query)


@pytest.mark.parametrize('media', ['movie', 'tv'])
@pytest.mark.parametrize('canvas_action', ['create', 'update'])
def test_radar_resolved_prompts_pass_real_output_validation_and_finish_delivery(media, canvas_action):
    tools = RadarTools(media, existing_page='page_existing_fixture' if canvas_action == 'update' else '')
    provider = RadarProvider(media)
    executor = PipelineExecutor('cloud', tools, provider=provider)
    result = executor.execute(_workflow(tools.key), f'/{tools.key} science fiction, email me the pick')

    assert result['ok'], result
    assert len(provider.prompts) == 2
    assert all('${' not in prompt for prompt in provider.prompts)
    canvas_calls = [params for tool, params in tools.calls
                    if tool == 'canvas' and params['action'] != 'read']
    assert [params['action'] for params in canvas_calls] == [canvas_action]
    assert canvas_calls[0]['content'] == provider.outputs[0]
    email_call = next(params for tool, params in tools.calls if tool == 'send_email')
    assert email_call['body'] == provider.outputs[1]
    assert tools.calls[-1][1]['action'] == 'record_delivery'
    assert tools.handled == {'101'}


@pytest.mark.parametrize('media', ['movie', 'tv'])
def test_radar_records_only_the_selected_delivered_id_and_excludes_it_across_modes(media):
    handled = set()
    first = RadarTools(media, handled=handled)
    result = _run_radar(first)
    assert result['ok'] and handled == {'101'}
    assert len(first.canvas) == 1
    assert [tool for tool, _ in first.calls][-2:] == ['send_email', 'watch_state']
    delivery = first.calls[-1][1]
    assert delivery['record']['tmdb_id'] == 101 and 'results' not in delivery['record']
    assert delivery['destination'] != 'boss'
    second = RadarTools(media, handled=handled)
    result = _run_radar(second, mode='local')
    assert result['ok'] and handled == {'101', '102'}
    discovery = next(params for tool, params in second.calls if tool.startswith('tmdb_') and params['action'] == 'discover')
    assert discovery['exclude_movie_ids' if media == 'movie' else 'exclude_show_ids'] == ['101']
    assert second.calls[-1][1]['record']['tmdb_id'] == 102


@pytest.mark.parametrize('media', ['movie', 'tv'])
def test_radar_uses_real_shared_ledger_with_trusted_workflow_writer(media, tmp_path, monkeypatch):
    from lib.watch_state import Authority, Store, export_writer_context, service

    monkeypatch.setattr(service, 'get_stash_dir', lambda: tmp_path / 'stash')

    class LedgerTools(RadarTools):
        def __init__(self, mode):
            super().__init__(media)
            self.mode = mode

        def execute(self, tool, params):
            if tool != 'watch_state':
                return super().execute(tool, params)
            self.calls.append((tool, deepcopy(params)))
            return service.dispatch(params, project_root=tmp_path, mode=self.mode,
                                    authority=Authority(export_writer_context()))

    cloud = LedgerTools('cloud')
    first = _run_radar(cloud)
    assert first['ok'], first
    ledger = Store(tmp_path, 'shared')
    sent = ledger.handled(cloud.key, 'email')['items']
    assert [row['record_id'] for row in sent] == ['101']
    assert sent[0]['destination'] == 'reader@example.test'
    assert sent[0]['receipt'] == cloud.email
    assert ledger.inspect(cloud.key)['owner'] == f'workflow:{cloud.key}'

    local = LedgerTools('local')
    second = _run_radar(local, mode='local')
    assert second['ok'], second
    discovery = next(params for tool, params in local.calls
                     if tool.startswith('tmdb_') and params['action'] == 'discover')
    assert discovery['exclude_movie_ids' if media == 'movie' else 'exclude_show_ids'] == ['101']
    assert ledger.handled(cloud.key, 'email')['ids'] == ['101', '102']
    assert not Store(tmp_path, 'cloud').health()['items'][0]['stale']


@pytest.mark.parametrize('media', ['movie', 'tv'])
def test_radar_history_capacity_stops_before_discovery_and_preserves_all_sent_ids(media, tmp_path, monkeypatch):
    from lib.watch_state import Authority, Store, export_writer_context, service

    stash = tmp_path / 'stash'
    key = f'upcoming_{media}_radar'
    legacy = stash / f'space_{key}'
    legacy.mkdir(parents=True)
    (legacy / 'meta.json').write_text(json.dumps({
        'files': [{'name': str(identifier), 'kind': 'json'} for identifier in range(1, 502)],
    }))
    monkeypatch.setattr(service, 'get_stash_dir', lambda: stash)

    class LedgerTools(RadarTools):
        def execute(self, tool, params):
            if tool != 'watch_state':
                return super().execute(tool, params)
            self.calls.append((tool, deepcopy(params)))
            try:
                return service.dispatch(params, project_root=tmp_path, mode='cloud',
                                        authority=Authority(export_writer_context()))
            except ValueError as exc:
                return {'ok': False, 'speech': str(exc), 'error': 'invalid_watch_request'}

    tools = LedgerTools(media)
    result = _run_radar(tools)
    assert not result['ok'] and result['data']['failed_tool'] == 'watch_state'
    assert [tool for tool, _ in tools.calls] == ['get_time', 'watch_state']
    assert 'sent-history ledger' in result['speech'] and '500-ID discovery limit' in result['speech']
    assert 'genre' not in result['speech'].lower()
    assert 'No sent history was truncated or reset' in result['speech']
    assert len(Store(tmp_path, 'shared').handled(key, 'email', limit=1000)['ids']) == 501


@pytest.mark.parametrize('media', ['movie', 'tv'])
def test_canvas_only_run_does_not_advance_email_history(media):
    tools = RadarTools(media)
    assert _run_radar(tools, request_email=False)['ok']
    assert tools.canvas and not tools.handled
    assert not any(tool == 'send_email' or params.get('action') == 'record_delivery' for tool, params in tools.calls)


@pytest.mark.parametrize('media', ['movie', 'tv'])
@pytest.mark.parametrize('email', [
    {'ok': False, 'error': 'Controlled send failure'},
    {'ok': True, 'data': {'status': 'queued', 'to': 'reader@example.test'}},
    {'ok': False, 'data': {'status': 'sent', 'to': 'reader@example.test'}},
])
def test_unsuccessful_or_unconfirmed_email_does_not_record_the_selected_id(media, email):
    tools = RadarTools(media, email=email)
    assert _run_radar(tools)['ok']
    assert tools.canvas and not tools.handled
    assert not any(params.get('action') == 'record_delivery' for _, params in tools.calls)


@pytest.mark.parametrize('media', ['movie', 'tv'])
@pytest.mark.parametrize('failure', ['radar_history', 'canvas'])
def test_history_or_publication_failure_stops_before_email_and_delivery_record(media, failure):
    tools = RadarTools(media, failure=failure)
    assert not _run_radar(tools)['ok']
    assert not any(tool == 'send_email' or params.get('action') == 'record_delivery' for tool, params in tools.calls)


@pytest.mark.parametrize('media', ['movie', 'tv'])
def test_post_email_record_failure_aborts_with_do_not_resend_warning(media):
    tools = RadarTools(media, failure='record_delivery')
    result = _run_radar(tools)
    assert not result['ok'] and not tools.handled
    assert [tool for tool, _ in tools.calls].count('send_email') == 1
    assert 'email was sent' in result['speech'] and 'Do not rerun' in result['speech']
    assert 'watch-ledger acknowledgement' in result['speech']


class NoModelProvider:
    def chat_with_tools(self, **kwargs):
        raise AssertionError('Self-check must not call a model')


class HealthTools:
    def __init__(self, *, counts=None, watch_failed=False, host_issues=0, canvas_failed=False):
        self.counts = {'watches_count': 0, 'stale_count': 0, 'error_count': 0,
                       'pending_count': 0, 'parked_count': 0, **(counts or {})}
        self.watch_failed = watch_failed
        self.host_issues = host_issues
        self.canvas_failed = canvas_failed
        self.calls = []
        self.canvas = []
        self.alerts = []

    def execute(self, tool, params):
        self.calls.append((tool, deepcopy(params)))
        if tool == 'get_time':
            data = {'date': '2026-11-13', 'time': '10:00'}
        elif tool == 'system_monitor':
            data = {'status': 'critical' if self.host_issues else 'healthy',
                    'issue_count': self.host_issues, 'highest_severity': 'high' if self.host_issues else 'none',
                    'issue_summary': 'Host fixture summary', 'summary_markdown': 'Host fixture status',
                    'alert_title': 'Host fixture issue', 'alert_description': 'Host fixture details',
                    'alert_severity': 'high', 'alert_dedupe_key': 'jarvis_self_check:cpu_core_hot:core_2',
                    'top_process': {'name': 'fixture', 'cpu_percent': 0, 'cmdline': 'fixture'}}
        elif tool == 'watch_state':
            assert params == {'action': 'health'}
            if self.watch_failed:
                return {'ok': False, 'error': 'Controlled watch storage failure'}
            data = {'ok': not any(self.counts[key] for key in ('stale_count', 'error_count', 'parked_count')),
                    'mode': 'cloud', 'scope': 'cloud+shared', 'items': [], **self.counts}
        elif tool == 'check_tool_logs':
            data = {'workflow_logs': []}
        elif tool == 'query_service_logs':
            data = {'stats': []}
        elif tool == 'canvas':
            if params['action'] == 'read':
                data = {'page_id': '', 'content': ''}
            elif self.canvas_failed:
                return {'ok': False, 'error': 'Controlled Canvas failure'}
            else:
                self.canvas.append(params['content'])
                data = {'page_id': 'page_self_check_fixture'}
        elif tool == 'create_alert':
            assert self.canvas, 'Health report must be saved before alerts'
            self.alerts.append(params)
            data = {'alert_id': len(self.alerts), 'duplicate_suppressed': False}
        else:
            raise AssertionError((tool, params))
        return {'ok': True, 'data': data}


def _run_self_check(tools, *, registry_tools=None, excluded_tools=None):
    if registry_tools is not None:
        tools.registry = SimpleNamespace(list_tools=lambda: registry_tools)
        tools.excluded_tools = set(excluded_tools or [])
    executor = PipelineExecutor('cloud', tools, provider=NoModelProvider())
    return executor.execute(_workflow('jarvis_self_check'), '/jarvis_self_check')


@pytest.mark.parametrize('unavailable_reason', ['profile', 'request'])
def test_self_check_disabled_watch_tool_stays_unavailable_without_false_alert(unavailable_reason):
    tools = HealthTools()
    available = {step['tool'] for step in _workflow('jarvis_self_check')['steps']}
    excluded = set()
    if unavailable_reason == 'profile':
        available.remove('watch_state')
    else:
        excluded.add('watch_state')
    result = _run_self_check(tools, registry_tools=available, excluded_tools=excluded)
    assert result['ok'] and result['data']['degraded']
    assert result['data']['optional_tools_skipped'] == ['watch_state']
    assert not any(tool == 'watch_state' for tool, _ in tools.calls)
    assert not tools.alerts
    assert 'Check: unavailable' in tools.canvas[0]
    assert 'Scope: not enabled for this run' in tools.canvas[0]
    assert 'Watch errors: 0' in tools.canvas[0]
    assert 'Watch check unavailable' in result['speech']
    assert '${' not in tools.canvas[0]


@pytest.mark.parametrize('pending', [0, 3])
def test_self_check_no_watches_or_ordinary_pending_deliveries_do_not_raise_alerts(pending):
    tools = HealthTools(counts={'watches_count': 1 if pending else 0, 'pending_count': pending})
    result = _run_self_check(tools)
    assert result['ok'] and tools.canvas and not tools.alerts
    assert '## Watch State' in tools.canvas[0]
    assert f'Pending deliveries: {pending}' in tools.canvas[0]
    assert 'Watch errors: 0' in tools.canvas[0] and 'Check: checked' in tools.canvas[0]
    assert '${' not in tools.canvas[0]


@pytest.mark.parametrize('field', ['stale_count', 'error_count', 'parked_count'])
def test_self_check_watch_faults_create_a_separate_non_speaking_alert_after_canvas(field):
    tools = HealthTools(counts={'watches_count': 1, field: 1, 'pending_count': 2})
    result = _run_self_check(tools)
    assert result['ok'] and len(tools.alerts) == 1
    alert = tools.alerts[0]
    assert alert['severity'] == 'medium' and alert['speak_immediately'] is False
    assert alert['metadata']['dedupe_key'] == 'jarvis_self_check:watch_state'
    assert alert['metadata'][field] == 1 and alert['metadata']['pending_count'] == 2
    assert tools.calls[-1][0] == 'create_alert'
    assert 'Watch check checked' in result['speech']


def test_self_check_failed_watch_read_is_visible_and_never_reported_as_healthy():
    tools = HealthTools(watch_failed=True)
    result = _run_self_check(tools)
    assert result['ok'] and len(tools.alerts) == 1
    assert 'Check: unavailable' in tools.canvas[0] and 'Watch errors: 1' in tools.canvas[0]
    assert 'Watch check unavailable' in result['speech']
    assert tools.alerts[0]['metadata']['watch_check_status'] == 'unavailable'
    assert '${' not in tools.canvas[0]


def test_self_check_preserves_host_alert_policy_when_watch_storage_also_has_an_issue():
    tools = HealthTools(host_issues=1, counts={'watches_count': 1, 'parked_count': 1})
    assert _run_self_check(tools)['ok']
    assert len(tools.alerts) == 2
    host, watch = tools.alerts
    assert host['severity'] == 'high' and host['speak_immediately'] is True
    assert host['metadata']['dedupe_key'] == 'jarvis_self_check:cpu_core_hot:core_2'
    assert watch['severity'] == 'medium' and watch['speak_immediately'] is False
    assert watch['metadata']['dedupe_key'] == 'jarvis_self_check:watch_state'


def test_self_check_keeps_existing_host_thresholds_and_has_no_model_step():
    workflow = _workflow('jarvis_self_check')
    monitor = next(step for step in workflow['steps'] if step['tool'] == 'system_monitor')
    assert monitor['params'] == {
        'action': 'health_check', 'limit': 15, 'sort_by': 'cpu', 'cpu_total_threshold': 90,
        'cpu_core_threshold': 95, 'process_cpu_threshold': 90, 'process_min_age_minutes': 5,
        'memory_threshold': 90, 'swap_threshold': 50, 'disk_threshold': 90,
        'suspicious_min_age_minutes': 10, 'suspicious_cmd_keywords': ['/dev/null', 'aplay', 'arecord', 'ffmpeg'],
    }
    assert all('llm_prompt' not in step for step in workflow['steps'])


def test_self_check_does_not_raise_host_or_watch_alerts_when_canvas_publication_fails():
    tools = HealthTools(host_issues=1, counts={'parked_count': 1}, canvas_failed=True)
    assert not _run_self_check(tools)['ok']
    assert not tools.alerts
