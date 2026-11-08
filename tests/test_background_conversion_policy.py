"""Named conversion permission review without network or provider execution."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_background_tasks import config_root as config_root

from lib.background_tasks import AdmissionDenied, production
from lib.background_tasks.local_contract import ADAPTER
from lib.background_tasks.local_skill import LocalSkillRunner, restrict_child_environment

ROOT = Path(__file__).resolve().parents[1]
PERMISSIONS = {
    'dangerous': False, 'auto_approve': True, 'network': True,
    'bash': True, 'filesystem': True,
}


@pytest.fixture
def conversion_policy(tmp_path, config_root):
    root = tmp_path / 'policy-checkout'
    skills = root / 'skills'
    skills.mkdir(parents=True)
    manifest = skills / 'convert_file.tool.json'
    shutil.copyfile(ROOT / 'skills' / manifest.name, manifest)
    (skills / 'convert_file.py').write_text('# Policy fixture; never executed.\n')
    runner = LocalSkillRunner(
        root, {'convert_file': ADAPTER},
        child_environment_policies=production.CHILD_ENVIRONMENT_POLICIES,
        permission_policies=production.TRUSTED_PERMISSION_POLICIES,
    )
    return SimpleNamespace(root=root, manifest=manifest, runner=runner)


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_convert_permission_review_keeps_process_adapter_proxy_and_fingerprinted_authority(
    conversion_policy, mode,
):
    from config_loader import config_scope

    with config_scope(mode, overrides={'JARVIS_TOOL_PROFILE': 'default'}):
        schema, evidence = conversion_policy.runner.policy('convert_file')
        authorized = conversion_policy.runner.authorize_tools(['convert_file'])

    assert schema.permissions == PERMISSIONS
    assert schema.background_adapter == evidence['adapter'] == ADAPTER
    assert schema.background_execution['completion_scope'] == 'process_group'
    assert schema.proxy_policy == evidence['proxy_policy'] == 'off'
    assert len(evidence['permission_policy_sha256']) == 64
    assert authorized == {'convert_file': evidence}


@pytest.mark.parametrize(('field', 'value'), [
    ('dangerous', True), ('auto_approve', False), ('network', False),
    ('bash', False), ('filesystem', False), ('network', 1), ('unexpected_permission', True),
])
def test_convert_permission_exception_requires_every_exact_reviewed_value(
    conversion_policy, field, value,
):
    manifest = json.loads(conversion_policy.manifest.read_text())
    manifest['permissions'][field] = value
    conversion_policy.manifest.write_text(json.dumps(manifest))

    with pytest.raises(AdmissionDenied, match='policy'):
        conversion_policy.runner.policy('convert_file')


def test_convert_permission_exception_rejects_missing_permission(conversion_policy):
    manifest = json.loads(conversion_policy.manifest.read_text())
    del manifest['permissions']['bash']
    conversion_policy.manifest.write_text(json.dumps(manifest))

    with pytest.raises(AdmissionDenied, match='policy'):
        conversion_policy.runner.policy('convert_file')


def test_named_conversion_permission_exception_cannot_authorize_another_local_tool(conversion_policy):
    other = 'unreviewed_local_conversion'
    manifest = json.loads(conversion_policy.manifest.read_text())
    manifest.update(name=other, script=f'{other}.py')
    (conversion_policy.root / 'skills' / f'{other}.tool.json').write_text(json.dumps(manifest))
    (conversion_policy.root / 'skills' / f'{other}.py').write_text('# Never executed.\n')
    conversion_policy.runner.bindings[other] = ADAPTER
    conversion_policy.runner.child_environment_policies[other] = production.CHILD_ENVIRONMENT_POLICIES['convert_file']

    with pytest.raises(AdmissionDenied, match='policy'):
        conversion_policy.runner.policy(other)


def test_conversion_child_retains_custom_certificate_paths_without_provider_or_proxy_secrets(tmp_path):
    certificates = {key: str(tmp_path / key.lower()) for key in (
        'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
    )}
    environment = {
        **certificates, 'PATH': '/usr/bin', 'JARVIS_MODE': 'local', 'STASH_DIR': str(tmp_path / 'stash'),
        'HOME': '/worker-home', 'OPENAI_API_KEY': 'unrelated-provider-secret',
        'GOOGLE_WORKSPACE_MCP_TOKEN': 'unrelated-workspace-secret',
        'HTTP_PROXY': 'http://proxy.invalid', 'LOCAL_PROXY': 'http://proxy.invalid',
    }
    child = restrict_child_environment(
        environment, production.CHILD_ENVIRONMENT_POLICIES['convert_file'], {}, tmp_path / 'scratch',
    )

    assert all(child[key] == value for key, value in certificates.items())
    assert child['HOME'] == str(tmp_path / 'scratch')
    assert child['JARVIS_RESTRICTED_TOOL_ENV'] == '1'
    assert child['JARVIS_MODE'] == 'local'
    assert child['STASH_DIR'] == str(tmp_path / 'stash')
    assert not {'OPENAI_API_KEY', 'GOOGLE_WORKSPACE_MCP_TOKEN', 'HTTP_PROXY', 'LOCAL_PROXY'} & child.keys()
