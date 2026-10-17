"""Native catalog bridge through the real remote-MCP call lifecycle."""

import io
import json
import time
from threading import Event
from urllib.parse import urlsplit

import config_loader
import http_client
import mcp_client
import pytest
from urllib3.response import HTTPResponse

from lib import config_loader as package_config

OFFICIAL = {'id': 'OfficialActor123', 'username': 'apify', 'name': 'web-scraper',
            'title': 'Web Scraper', 'description': 'Scrape requested web pages',
            'actorPermissionLevel': 'LIMITED_PERMISSIONS',
            'stats': {'actorReviewCount': 0, 'totalUsers30Days': 0}}
COMMUNITY = {'id': 'TrustedActor123', 'username': 'community', 'name': 'trusted',
             'title': 'Trusted scraper', 'description': 'Scrape requested web pages',
             'actorPermissionLevel': 'LIMITED_PERMISSIONS',
             'stats': {'actorReviewCount': 0, 'totalUsers30Days': 0}}


class Response:
    def __init__(self, value, *, status=200):
        self.status_code = status
        self.headers = {'Content-Type': 'application/json'}
        self.raw = HTTPResponse(body=io.BytesIO(json.dumps(value).encode()),
                                headers=self.headers, preload_content=False)
        self.closed = False

    def close(self):
        self.closed = True
        self.raw.close()


class NativeCatalog:
    """The HTTP boundary is replaced; MCP budgeting and native search stay real."""

    def __init__(self):
        self.calls = []
        self.responses = []
        self.status = 200
        self.entered = Event()
        self.release = None

    def __call__(self, method, url, **kwargs):
        parsed = urlsplit(url)
        assert parsed.scheme == 'https'
        assert parsed.netloc == 'api.apify.com'
        assert method == 'GET', 'Catalog discovery must never execute an Actor'
        assert kwargs['allow_redirects'] is False
        assert kwargs['proxies'] == {'http': None, 'https': None, 'all': None}
        assert isinstance(kwargs['timeout'], tuple)
        assert all(0 < seconds <= 3 for seconds in kwargs['timeout'])
        self.calls.append((method, parsed.path, kwargs,
                           config_loader.get_active_config_mode(),
                           package_config.get_active_config_mode()))
        self.entered.set()
        if self.release is not None:
            assert self.release.wait(4), 'The test must release its native HTTP fixture'
        if parsed.path == '/v2/store':
            value = {'data': {'items': [OFFICIAL], 'total': 1, 'offset': 0, 'limit': 1}}
        elif parsed.path in {'/v2/acts/community~trusted', '/v2/acts/TrustedActor123'}:
            value = {'data': COMMUNITY}
        else:
            pytest.fail(f'Unexpected native catalog endpoint: {parsed.path}')
        response = Response(value, status=self.status)
        self.responses.append(response)
        return response


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    config = tmp_path / 'config'
    config.mkdir()
    for mode in ('cloud', 'local'):
        (config / f'{mode}.env').write_text(
            f'APIFY_MCP_ENABLED=true\nAPIFY_TOKEN=fixture-{mode}-file\n'
            'APIFY_ALLOWED_ACTORS=\nAPIFY_RUN_TIMEOUT_SECONDS=1800\n'
            'APIFY_MAX_MEMORY_MB=2048\nAPIFY_MAX_CHARGE_USD=1\n'
            'APIFY_POLL_SECONDS=30\nAPIFY_RESULT_PAGE_SIZE=20\n'
            'JARVIS_TOOL_PROXY_POLICY=require\nLOCAL_PROXY=http://fixture-proxy.invalid:8111\n'
            f'STASH_DIR={tmp_path / (mode + "-stash")}\n')
    monkeypatch.setattr(config_loader, 'get_project_root', lambda: tmp_path)
    monkeypatch.setattr(package_config, 'get_project_root', lambda: tmp_path)
    monkeypatch.setenv('HTTPS_PROXY', 'http://ambient-proxy.invalid:8112')
    monkeypatch.setenv('MCP_TOOL_CALL_TIMEOUT_SECONDS', '3')
    monkeypatch.setenv('STASH_DIR', str(tmp_path / 'fallback-stash'))
    monkeypatch.delenv('JARVIS_OVERRIDE_STASH_DIR', raising=False)
    native = NativeCatalog()
    monkeypatch.setattr(http_client.requests, 'request', native)
    return native


def connection(*, name='apify', contract='external_result_v1'):
    return mcp_client.MCPRemoteClient(name, 'https://mcp.apify.com/mcp', 'http',
        {'Authorization': 'Bearer fixture-hosted-header'}, proxy_policy='off', result_contract=contract)


def no_hosted_call(*args, **kwargs):
    pytest.fail('Native Actor search must not initialize or call the hosted MCP tool')


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_native_search_bridge_uses_selected_request_scope_for_token_proxy_and_archive(isolated, tmp_path, monkeypatch, mode):
    from stash_helper import get_space, parse_stash_ref

    native = isolated
    client = connection()
    monkeypatch.setattr(client, '_send_request', no_hosted_call)
    other_mode = 'local' if mode == 'cloud' else 'cloud'
    selected_token = 'fixture-' + mode + '-request'
    with package_config.config_scope(other_mode, {'APIFY_TOKEN': 'fixture-wrong-package-token'}):
        with config_loader.config_scope(mode, {'APIFY_TOKEN': selected_token,
                                               'APIFY_ALLOWED_ACTORS': 'community/trusted'}):
            result = client.call_tool('search-actors', {'keywords': 'web pages', 'limit': 5})
            assert result['ok'] is True, result
            assert result['data']['contract'] == 'external_result_v1'
            assert result['data']['source']['mode'] == mode
            space_id, _file_id = parse_stash_ref(result['data']['raw_ref'])
            assert get_space(space_id).space_path.parent == tmp_path / (mode + '-stash')
    assert native.calls
    assert any(path == '/v2/store' for _, path, *_ in native.calls)
    assert any(path.startswith('/v2/acts/') for _, path, *_ in native.calls)
    for _, path, kwargs, top_mode, package_mode in native.calls:
        assert kwargs['headers']['Authorization'] == 'Bearer ' + selected_token
        assert (top_mode, package_mode) == (mode, mode)
        assert 'fixture-hosted-header' not in json.dumps(kwargs)
        if path == '/v2/store':
            assert kwargs['params']['username'] == 'apify'
            assert kwargs['params']['search'] == 'web pages'
    assert all(response.closed for response in native.responses)
    assert client._call_budgets == {}
    assert mcp_client._remote_call_budget.get() is None
    assert client.get_proxy_log_metadata()['direct_reason'] == 'policy_off'
    assert selected_token not in json.dumps(result)
    assert 'fixture-wrong-package-token' not in json.dumps(result)


@pytest.mark.parametrize('name,tool,contract', [
    ('apify', 'fetch-actor-details', 'external_result_v1'),
    ('other_server', 'search-actors', 'external_result_v1'),
    ('apify', 'search-actors', None),
    ('Apify', 'search-actors', 'external_result_v1'),
])
def test_other_server_tool_and_contract_paths_still_call_hosted_mcp(isolated, monkeypatch, name, tool, contract):
    client = connection(name=name, contract=contract)
    sent = []
    raw = {'content': [{'type': 'text', 'text': 'Hosted fixture response'}],
           'structuredContent': {'exact_id': 'Hosted123'}}

    def hosted(method, params):
        sent.append((method, params))
        return raw

    monkeypatch.setattr(client, '_send_request', hosted)
    with config_loader.config_scope('cloud'):
        result = client.call_tool(tool, {'keywords': 'requested query'})
    assert result['ok'] is True
    assert sent == [('tools/call', {'name': tool, 'arguments': {'keywords': 'requested query'}})]
    assert isolated.calls == []
    if contract:
        assert result['data']['contract'] == contract
        assert result['data']['source']['provider'] == name
    else:
        assert result['data']['structuredContent'] == raw['structuredContent']
        assert 'contract' not in result['data']
    assert client._call_budgets == {}


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('overrides', [
    {'APIFY_TOKEN': ''},
    {'APIFY_MCP_ENABLED': 'false'},
])
def test_native_search_cannot_fall_back_to_another_modes_credential_or_enable_flag(isolated, monkeypatch, mode, overrides):
    client = connection()
    monkeypatch.setattr(client, '_send_request', no_hosted_call)
    other_mode = 'local' if mode == 'cloud' else 'cloud'
    with package_config.config_scope(other_mode, {'APIFY_TOKEN': 'fixture-unrelated-token',
                                                 'APIFY_MCP_ENABLED': 'true'}):
        with config_loader.config_scope(mode, overrides):
            result = client.call_tool('search-actors', {'keywords': 'requested query'})
    assert result['ok'] is False
    assert isolated.calls == []
    assert 'fixture-unrelated-token' not in json.dumps(result)
    assert client._call_budgets == {}


def test_native_search_http_failure_closes_response_and_clears_call_budget(isolated, monkeypatch):
    client = connection()
    monkeypatch.setattr(client, '_send_request', no_hosted_call)
    isolated.status = 503
    with config_loader.config_scope('cloud'):
        result = client.call_tool('search-actors', {'keywords': 'requested query'})
    assert result['ok'] is False
    assert len(isolated.calls) == 1
    assert isolated.responses[0].closed
    assert client._call_budgets == {}


def test_timed_out_native_search_cannot_archive_or_enrich_after_http_returns(isolated, tmp_path, monkeypatch):
    native = isolated
    native.release = Event()
    client = connection()
    monkeypatch.setattr(client, '_send_request', no_hosted_call)
    monkeypatch.setenv('MCP_TOOL_CALL_TIMEOUT_SECONDS', '1')
    try:
        started = time.monotonic()
        with config_loader.config_scope('local', {'APIFY_ALLOWED_ACTORS': 'community/trusted'}):
            result = client.call_tool('search-actors', {'keywords': 'requested query'})
        assert native.entered.is_set()
        assert result['ok'] is False
        assert any(marker in result['error'].lower() for marker in ('timed out', 'deadline', 'cancelled'))
        assert time.monotonic() - started < 2.5
        started_before_cancel = len(native.calls)
        native.release.set()
        until = time.monotonic() + 3
        while (client._call_budgets or len(native.responses) < started_before_cancel
               or any(not response.closed for response in native.responses)) and time.monotonic() < until:
            time.sleep(0.01)
        assert client._call_budgets == {}, 'Cancelled native search left a live worker budget'
        assert len(native.calls) == started_before_cancel, 'Cancelled discovery started a late request'
        assert len(native.responses) == started_before_cancel
        assert all(response.closed for response in native.responses)
        assert not list(tmp_path.rglob('external-response.json'))
        assert not list(tmp_path.rglob('meta.json'))
    finally:
        native.release.set()
        until = time.monotonic() + 3
        while (client._call_budgets or len(native.responses) < len(native.calls)
               or any(not response.closed for response in native.responses)) and time.monotonic() < until:
            time.sleep(0.01)
