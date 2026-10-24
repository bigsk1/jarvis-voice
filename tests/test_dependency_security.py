"""Advisory checks must distinguish checked inventories from incomplete evidence."""

import io
import json

import pytest
import requests
import urllib3.response

from lib import dependency_security as audit


def installed(prefix, name='example-pkg', version='1.0'):
    metadata = prefix / 'lib/python3.12/site-packages' / f'{name}-{version}.dist-info'
    metadata.mkdir(parents=True)
    (metadata / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n')


def lock(root, packages=(('example-pkg', '1.0'),)):
    (root / 'uv.lock').write_text('\n'.join(
        f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {{registry = "https://pypi.org/simple"}}\n'
        for name, version in packages
    ))


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / 'checkout'
    root.mkdir()
    runtime = tmp_path / 'runtime'
    installed(runtime)
    lock(root)
    calls = []

    def clear(method, endpoint, deadline, payload=None):
        calls.append((method, endpoint, payload))
        assert endpoint == '/querybatch'
        return {'results': [{} for _ in payload['queries']]}

    monkeypatch.setattr(audit, '_request_json', clear)
    return root, runtime, calls


def advisory(identifier='GHSA-example', *, name='example-pkg', aliases=None, **extra):
    return {
        'id': identifier, 'aliases': aliases or [], 'summary': 'Example advisory',
        'affected': [{'package': {'ecosystem': 'PyPI', 'name': name},
                      'ranges': [{'type': 'ECOSYSTEM', 'events': [{'introduced': '0'}, {'fixed': '2.0'}]}]}],
        **extra,
    }


def matched(monkeypatch, records):
    def request(method, endpoint, deadline, payload=None):
        if method == 'POST':
            return {'results': [{'vulns': [{'id': key} for key in records]} for _ in payload['queries']]}
        value = records[endpoint.removeprefix('/vulns/')]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(audit, '_request_json', request)


def test_current_runtime_development_and_universal_lock_are_distinct(workspace, monkeypatch):
    root, runtime, calls = workspace
    installed(root / '.venv', 'development-only', '2.0')
    lock(root, [('example-pkg', '1.0'), ('lock-only-conditional', '3.0')])
    monkeypatch.setattr(audit.sys, 'prefix', str(runtime))
    result = audit.run_audit(root)
    assert result['complete'] and result['status'] == 'clear'
    assert result['packages_queried'] == 3
    environments = {item['label']: item for item in result['environments']}
    assert environments['runtime_installed']['path'] == str(runtime)
    assert environments['runtime_installed']['package_count'] == 1
    assert environments['development_installed']['kind'] == 'installed'
    assert environments['uv_lock']['kind'] == 'universal_lock'
    assert environments['uv_lock']['package_count'] == 2
    assert environments['craft_lock']['status'] == 'not_present'
    assert {query['package']['name'] for query in calls[0][2]['queries']} == {
        'example-pkg', 'development-only', 'lock-only-conditional',
    }
    assert not result['alert_needed'] and result['issue_count'] == 0
    assert 'conditional packages' in result['summary_markdown']
    assert 'remote hosts are not audited' in result['summary_markdown']


def test_effective_runtime_does_not_duplicate_development_inventory(workspace):
    root, _, _ = workspace
    installed(root / '.venv')
    result = audit.run_audit(root, runtime_prefix=root / '.venv')
    assert result['complete']
    assert 'development_installed' not in {item['label'] for item in result['environments']}


@pytest.mark.parametrize('contents', [None, 'not toml', 'package = []', 'package = [42]'])
def test_missing_or_malformed_required_lock_cannot_report_clear(workspace, contents):
    root, runtime, _ = workspace
    if contents is None:
        (root / 'uv.lock').unlink()
    else:
        (root / 'uv.lock').write_text(contents)
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert result['status'] == 'incomplete' and not result['complete']
    assert result['issue_count'] >= 1 and result['alert_needed']
    assert 'audit is incomplete' in result['summary_markdown']
    assert any(error.get('environment') == 'uv_lock' for error in result['errors'])


def test_missing_runtime_cannot_be_replaced_by_a_clean_lock(workspace):
    root, runtime, _ = workspace
    result = audit.run_audit(root, runtime_prefix=runtime / 'missing')
    assert not result['complete'] and result['status'] == 'incomplete'
    assert result['errors'][0]['environment'] == 'runtime_installed'


def test_metadata_inventory_never_imports_package_code(workspace):
    root, runtime, _ = workspace
    package = runtime / 'lib/python3.12/site-packages/example_pkg'
    package.mkdir()
    (package / '__init__.py').write_text('raise AssertionError("Package code must never execute")')
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert result['complete']


def test_optional_craft_hashed_lock_is_planned_not_deployed(workspace):
    root, runtime, _ = workspace
    craft = root / 'jarvis-craft-tools'
    craft.mkdir()
    (craft / 'requirements.lock.txt').write_text(
        '# Generated lock\ncraft-dependency==4.0 \\\n    --hash=sha256:example\n    # via gateway\n'
    )
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert result['complete'] and result['packages_queried'] == 2
    environment = next(item for item in result['environments'] if item['label'] == 'craft_lock')
    assert environment['kind'] == 'planned_lock' and environment['package_count'] == 1


def test_aliases_deduplicate_and_fixes_are_only_for_matching_pypi_package(workspace, monkeypatch):
    root, runtime, _ = workspace
    first = advisory(aliases=['CVE-2026-1234'], database_specific={'severity': 'HIGH'})
    first['affected'].extend([
        {'package': {'ecosystem': 'npm', 'name': 'example-pkg'},
         'ranges': [{'type': 'SEMVER', 'events': [{'fixed': '99.0'}]}]},
        {'package': {'ecosystem': 'PyPI', 'name': 'other-pkg'},
         'ranges': [{'type': 'ECOSYSTEM', 'events': [{'fixed': '88.0'}]}]},
    ])
    second = advisory('PYSEC-2026-1234', aliases=['CVE-2026-1234'])
    matched(monkeypatch, {'GHSA-example': first, 'PYSEC-2026-1234': second})
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert result['complete'] and result['status'] == 'findings'
    assert result['issue_count'] == 1
    finding = result['findings'][0]
    assert finding['environments'] == ['runtime_installed', 'uv_lock']
    assert len(finding['advisories']) == 1
    item = finding['advisories'][0]
    assert item['id'] == 'GHSA-example'
    assert item['aliases'] == ['CVE-2026-1234', 'PYSEC-2026-1234']
    assert item['fixed_versions'] == ['2.0'] and item['severity'] == 'high'
    assert 'https://osv.dev/vulnerability/GHSA-example' in result['summary_markdown']


def test_cvss_vector_without_calculator_is_explicitly_unknown(workspace, monkeypatch):
    root, runtime, _ = workspace
    matched(monkeypatch, {'GHSA-example': advisory(severity=[{'type': 'CVSS_V3', 'score': 'CVSS:3.1/AV:N'}])})
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert result['findings'][0]['advisories'][0]['severity'] == 'unknown'


def test_withdrawn_advisories_do_not_create_findings(workspace, monkeypatch):
    root, runtime, _ = workspace
    matched(monkeypatch, {'GHSA-example': advisory(withdrawn='2026-01-01T00:00:00Z')})
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert result['status'] == 'clear' and not result['findings']


@pytest.mark.parametrize('record', [
    advisory(name='unrelated'), advisory(withdrawn=True), advisory(withdrawn='not a date'),
    {'id': 'GHSA-example'}, advisory(aliases='not a list'),
])
def test_invalid_details_preserve_match_without_false_clear(workspace, monkeypatch, record):
    root, runtime, _ = workspace
    matched(monkeypatch, {'GHSA-example': record})
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert result['status'] == 'incomplete' and result['findings']
    item = result['findings'][0]['advisories'][0]
    assert not item['details_complete'] and item['fixed_versions'] == []


def test_detail_network_failure_preserves_positive_matches(workspace, monkeypatch):
    root, runtime, _ = workspace
    matched(monkeypatch, {'GHSA-example': audit.AuditError('advisory_network_error')})
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert not result['complete'] and result['findings'][0]['advisories'][0]['id'] == 'GHSA-example'


def test_query_pagination_repeats_only_affected_queries(workspace, monkeypatch):
    root, runtime, _ = workspace
    lock(root, [('example-pkg', '1.0'), ('second-pkg', '2.0')])
    calls = []

    def request(method, endpoint, deadline, payload=None):
        calls.append((method, payload))
        if method == 'GET':
            return advisory()
        if len(calls) == 1:
            return {'results': [{'next_page_token': 'next'}, {}]}
        assert len(payload['queries']) == 1
        assert payload['queries'][0]['package']['name'] == 'example-pkg'
        assert payload['queries'][0]['page_token'] == 'next'
        return {'results': [{'vulns': [{'id': 'GHSA-example'}]}]}

    monkeypatch.setattr(audit, '_request_json', request)
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert result['complete'] and result['packages_queried'] == 2 and result['findings']


@pytest.mark.parametrize('response', [{'results': []}, {'results': [None]},
                                      {'results': [{'error': 'provider error'}]}, {'results': [{'vulns': None}]}])
def test_missing_or_malformed_query_results_never_mean_clear(workspace, monkeypatch, response):
    root, runtime, _ = workspace
    monkeypatch.setattr(audit, '_request_json', lambda *args: response)
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert not result['complete'] and result['status'] == 'incomplete'


def test_partial_result_array_preserves_returned_matches(workspace, monkeypatch):
    root, runtime, _ = workspace
    lock(root, [('example-pkg', '1.0'), ('second-pkg', '2.0')])
    monkeypatch.setattr(audit, '_request_json', lambda method, *args: (
        {'results': [{'vulns': [{'id': 'GHSA-example'}]}]} if method == 'POST' else advisory()
    ))
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert not result['complete'] and result['findings']


def test_repeated_pagination_and_detail_cap_are_incomplete(workspace, monkeypatch):
    root, runtime, _ = workspace
    monkeypatch.setattr(audit, '_request_json', lambda *args: {'results': [{'next_page_token': 'again'}]})
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert not result['complete']
    assert any(item['code'] == 'repeated_pagination_token' for item in result['errors'])
    matched(monkeypatch, {'GHSA-example': advisory()})
    monkeypatch.setattr(audit, 'MAX_ADVISORIES', 0)
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert not result['complete'] and result['findings']


def test_dedupe_is_independent_of_timestamps_and_inventory_order(workspace, monkeypatch):
    root, runtime, _ = workspace
    matched(monkeypatch, {'GHSA-example': advisory()})
    first = audit.run_audit(root, runtime_prefix=runtime)
    second = audit.run_audit(root, runtime_prefix=runtime)
    assert first['alert_dedupe_key'] == second['alert_dedupe_key']
    matched(monkeypatch, {'GHSA-example': advisory(database_specific={'severity': 'CRITICAL'})})
    changed = audit.run_audit(root, runtime_prefix=runtime)
    assert first['alert_dedupe_key'] != changed['alert_dedupe_key']


class Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload
        self.closed = False
        self.raw = self

    def read1(self, amount, decode_content):
        payload, self.payload = self.payload, b''
        return payload

    def close(self):
        self.closed = True


def test_http_transport_has_fixed_api_redirect_policy_and_bounded_body(monkeypatch):
    response = Response(b'{"results": [{}]}')
    calls = []

    def request(method, url, **options):
        calls.append((method, url, options))
        return response

    monkeypatch.setattr(audit, 'http_request', request)
    deadline = audit.time.monotonic() + 20
    assert audit._request_json('POST', '/querybatch', deadline, {'queries': []}) == {'results': [{}]}
    assert calls[0][1] == 'https://api.osv.dev/v1/querybatch'
    assert calls[0][2]['allow_redirects'] is False
    assert calls[0][2]['deadline'] == deadline and calls[0][2]['stream'] is True
    assert calls[0][2]['headers']['Accept-Encoding'] == 'identity'
    assert calls[0][2]['timeout'] <= 10 and response.closed
    monkeypatch.setattr(audit, 'MAX_RESPONSE_BYTES', 2)
    response.payload = b'{"results": [{}]}'
    with pytest.raises(audit.AuditError, match='advisory_response_limit'):
        audit._request_json('GET', '/vulns/GHSA-example', deadline)


def test_trickling_real_urllib3_body_checks_deadline_before_filling_chunk(monkeypatch):
    clock = [0.0]

    class Trickle(io.BytesIO):
        def read(self, size=-1):
            clock[0] += 0.01
            return super().read(1)

        def read1(self, size=-1):
            return self.read(size)

    body = Trickle(b'{"results": [{}]}')
    response = requests.Response()
    response.status_code = 200
    response.raw = urllib3.response.HTTPResponse(body=body, preload_content=False)
    monkeypatch.setattr(audit.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(audit, 'http_request', lambda *args, **kwargs: response)
    with pytest.raises(audit.AuditError, match='deadline_exceeded'):
        audit._request_json('POST', '/querybatch', 0.03, {'queries': []})
    assert clock[0] <= 0.04, 'The transport buffered the whole trickling body before checking time'
    assert response.raw.closed


def test_unexpected_compression_is_rejected_without_decoder_reads(monkeypatch):
    response = Response(b'not actually gzip')
    response.headers = {'Content-Encoding': 'gzip'}
    monkeypatch.setattr(audit, 'http_request', lambda *args, **kwargs: response)
    with pytest.raises(audit.AuditError, match='unsupported_advisory_encoding'):
        audit._request_json('GET', '/vulns/GHSA-example', audit.time.monotonic() + 10)
    assert response.payload == b'not actually gzip' and response.closed


def test_http_error_payload_and_secrets_are_not_returned(workspace, monkeypatch):
    root, runtime, _ = workspace
    monkeypatch.undo()

    def fail(*args, **kwargs):
        raise requests.RequestException('https://user:private-secret@proxy.example')

    monkeypatch.setattr(audit, 'http_request', fail)
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert not result['complete']
    assert 'private-secret' not in json.dumps(result)
    assert result['errors'] == [{'stage': 'query', 'code': 'advisory_network_error'}]


def test_expired_deadline_never_starts_network_request(workspace, monkeypatch):
    root, runtime, _ = workspace
    monkeypatch.undo()
    monkeypatch.setattr(audit, 'AUDIT_SECONDS', -1)
    monkeypatch.setattr(audit, 'http_request', lambda *args, **kwargs: pytest.fail('expired request started'))
    result = audit.run_audit(root, runtime_prefix=runtime)
    assert not result['complete'] and result['status'] == 'incomplete'
    assert result['packages_queried'] == 0
    assert result['errors'] == [{'stage': 'query', 'code': 'deadline_exceeded'}]
