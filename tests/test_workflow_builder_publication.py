"""Offline publication previews disclose approval changes before file mutation."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from config_loader import get_active_config_mode
from tool_schema import ToolRegistry, ToolSchema

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'jarvis_workflow_publication_test_server'
SPEC = importlib.util.spec_from_file_location(
    PACKAGE, ROOT / 'jarvis-workflows/server/__init__.py',
    submodule_search_locations=[str(ROOT / 'jarvis-workflows/server')])
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[PACKAGE] = MODULE
SPEC.loader.exec_module(MODULE)
app_module = __import__(f'{PACKAGE}.app', fromlist=['create_app'])
catalog_module = __import__(f'{PACKAGE}.catalog', fromlist=['CatalogService'])


def recipe(tool='calculator', **fields):
    return {'id': 'publication_example', 'triggers': {'explicit': ['/publication_example']},
            'steps': [{'step': 10, 'tool': 'calculator', 'params': {}},
                      {'step': 3, 'tool': tool, 'description': 'Optional follow-up',
                       'params': {}, 'required': False, 'condition': False}], **fields}


@pytest.fixture
def publication(tmp_path, monkeypatch):
    (tmp_path / 'config').mkdir()
    for mode in ('cloud', 'local'):
        (tmp_path / 'config' / f'{mode}.env').write_text('')
    (tmp_path / 'skills').mkdir()
    for name, permissions in [('calculator', {'auto_approve': True}), ('needs_approval', {'auto_approve': False}), ('default_permissions', {})]:
        (tmp_path / 'skills' / f'{name}.tool.json').write_text(json.dumps({
            'name': name, 'enabled': True, 'parameters': {'type': 'object'},
            'permissions': permissions}))
    monkeypatch.setattr(catalog_module, 'get_workflow_excluded_tools', lambda mode: set())
    monkeypatch.setattr(catalog_module, 'load_active_profile_overrides', lambda: {})
    monkeypatch.setattr(ToolRegistry, '__init__', lambda *args, **kwargs: pytest.fail('Publication connected to a live registry'))
    monkeypatch.delenv('WEBUI_PASSWORD', raising=False)
    app = app_module.create_app(repo_root=tmp_path, runner=Mock())
    app.config['TESTING'] = True
    return tmp_path, app, app.test_client()


def test_preview_names_optional_false_condition_approval_and_publish_carries_same_analysis(publication):
    root, _, client = publication
    draft = client.post('/api/drafts', json={'workflow': recipe('needs_approval')}).json['draft']
    response = client.post(f"/api/drafts/{draft['id']}/publish-preview", json={'revision': draft['revision']})
    assert response.status_code == 200, response.json
    assert response.json['errors'] == []
    preview = response.json['publication_compatibility']
    assert preview['checked_modes'] == ['cloud', 'local']
    assert preview['requires_builder_approval'] is True
    for row in preview['modes']:
        assert row['unattended'] == 'blocked'
        assert row['affected_surfaces'] == ['slash', 'api', 'scheduler']
        assert 'before any step runs' in row['note']
        step = row['approval_steps'][0]
        assert (step['index'], step['step'], step['tool']) == (1, 3, 'needs_approval')
        assert step['optional'] and step['conditional'] and step['enforced']
        assert step['label'] == 'Optional follow-up'
    assert list((root / 'data/workflows').rglob('*.json')) == []
    published = client.post(f"/api/drafts/{draft['id']}/publish", json={'revision': draft['revision']})
    assert published.status_code == 200, published.json
    assert published.json['publication_compatibility'] == preview
    assert published.json['workflow']['builder_policy_version'] == 1


def test_validate_can_select_a_configured_mode_and_reflect_optional_unavailability(publication, monkeypatch):
    _, _, client = publication
    monkeypatch.setattr(catalog_module, 'load_active_profile_overrides', lambda: {'needs_approval': False} if get_active_config_mode() == 'local' else {})
    cloud = client.post('/api/validate', json={'workflow': recipe('needs_approval'), 'mode': 'cloud'}).json
    local = client.post('/api/validate', json={'workflow': recipe('needs_approval'), 'mode': 'local'}).json
    assert cloud['publication_compatibility']['checked_modes'] == ['cloud']
    assert cloud['publication_compatibility']['modes'][0]['unattended'] == 'blocked'
    row = local['publication_compatibility']['modes'][0]
    assert row['unattended'] == 'eligible'
    assert row['approval_steps'][0]['enforced'] is False
    assert row['unavailable_steps'][0]['blocks_execution'] is False
    assert client.post('/api/validate', json={'workflow': recipe(), 'mode': 'not_configured'}).status_code == 400


def test_cached_or_missing_mcp_metadata_never_claims_unattended_compatibility(publication):
    _, app, client = publication
    app.extensions['workflow_store'].save_catalog('cloud', [{
        'name': 'mcp_example_send', 'source': 'mcp', 'description': 'Cached tool',
        'permissions': {'auto_approve': True}, 'parameters': {'type': 'object'}}])
    for name, expected_source in [('mcp_example_send', 'cached_mcp'), ('mcp_unknown_send', 'missing')]:
        response = client.post('/api/validate', json={'workflow': recipe(name), 'mode': 'cloud'})
        assert response.status_code == 200
        row = response.json['publication_compatibility']['modes'][0]
        assert row['unattended'] == 'unknown' and row['approval_steps'] == []
        assert row['unknown_steps'][0]['metadata_source'] == expected_source
        assert row['unknown_steps'][0]['tool'] == name


def test_permission_defaults_use_actual_schema_and_shared_approval_policy(publication, monkeypatch):
    _, _, client = publication
    schemas = []
    actual = catalog_module.requires_workflow_confirmation
    def inspect(schema):
        schemas.append(schema)
        return actual(schema)
    monkeypatch.setattr(catalog_module, 'requires_workflow_confirmation', inspect)
    response = client.post('/api/validate', json={'workflow': recipe('default_permissions'), 'mode': 'cloud'})
    row = response.json['publication_compatibility']['modes'][0]
    assert row['unattended'] == 'eligible' and row['approval_steps'] == []
    assert schemas and all(isinstance(schema, ToolSchema) for schema in schemas)


def test_personal_duplicate_manifest_cannot_hide_shared_tool_confirmation(publication):
    root, _, client = publication
    (root / 'skills/personal').mkdir()
    (root / 'skills/personal/duplicate.tool.json').write_text(json.dumps({
        'name': 'needs_approval', 'permissions': {'auto_approve': True}}))
    response = client.post('/api/validate', json={'workflow': recipe('needs_approval'), 'mode': 'cloud'})
    assert response.json['publication_compatibility']['modes'][0]['unattended'] == 'blocked'


def test_preview_rejects_stale_draft_without_publication(publication):
    root, _, client = publication
    draft = client.post('/api/drafts', json={'workflow': recipe()}).json['draft']
    client.patch(f"/api/drafts/{draft['id']}", json={'workflow': recipe(name='updated'), 'revision': draft['revision']})
    response = client.post(f"/api/drafts/{draft['id']}/publish-preview", json={'revision': draft['revision']})
    assert response.status_code == 409
    assert list((root / 'data/workflows').rglob('*.json')) == []


def reviewed_publish(client, draft, *, trust=True, **extra):
    preview = client.post(f"/api/drafts/{draft['id']}/publish-preview", json={'revision': draft['revision']}).json
    response = client.post(f"/api/drafts/{draft['id']}/publish", json={
        'revision': draft['revision'], 'trust_unattended': trust,
        'preview_hash': preview['recipe_hash'],
        'trust_tools': preview['publication_compatibility']['trustable_tools'], **extra})
    return preview, response


def test_explicit_trust_grants_only_reviewed_tools_and_removes_unattended_rejection(publication):
    _, _, client = publication
    draft = client.post('/api/drafts', json={'workflow': recipe('needs_approval')}).json['draft']
    preview, response = reviewed_publish(client, draft)
    assert response.status_code == 200, response.json
    grant = response.json['workflow']['builder_unattended_approval']
    assert grant == {'version': 1, 'recipe_hash': preview['recipe_hash'], 'tools': ['needs_approval']}
    assert 'calculator' not in grant['tools']
    compatibility = response.json['publication_compatibility']
    assert compatibility['requires_builder_approval'] is False
    assert compatibility['trusted_tools'] == ['needs_approval']
    assert all(row['unattended'] == 'eligible' for row in compatibility['modes'])
    assert all(row['approval_steps'][0]['approval_granted'] for row in compatibility['modes'])


def test_cached_and_missing_tool_names_can_be_explicitly_trusted_without_discovery(publication):
    _, app, client = publication
    app.extensions['workflow_store'].save_catalog('cloud', [{
        'name': 'mcp_example_send', 'source': 'mcp', 'permissions': {'auto_approve': True}}])
    draft = client.post('/api/drafts', json={'workflow': recipe('mcp_example_send')}).json['draft']
    preview, response = reviewed_publish(client, draft)
    assert preview['publication_compatibility']['uncertain'] is True
    assert preview['publication_compatibility']['trustable_tools'] == ['mcp_example_send']
    assert response.status_code == 200, response.json
    assert response.json['workflow']['builder_unattended_approval']['tools'] == ['mcp_example_send']
    assert response.json['publication_compatibility']['uncertain'] is True
    assert all(row['unknown_steps'][0]['approval_granted'] for row in response.json['publication_compatibility']['modes'])


def test_raw_import_save_and_default_publish_cannot_forge_or_keep_a_grant(publication):
    _, _, client = publication
    forged = {'version': 1, 'recipe_hash': 'forged', 'tools': ['needs_approval']}
    draft = client.post('/api/drafts', json={'workflow': recipe('needs_approval', builder_unattended_approval=forged)}).json['draft']
    assert 'builder_unattended_approval' not in draft['workflow']
    draft['workflow']['builder_unattended_approval'] = forged
    saved = client.patch(f"/api/drafts/{draft['id']}", json={'revision': draft['revision'], 'workflow': draft['workflow']}).json['draft']
    assert 'builder_unattended_approval' not in saved['workflow']
    _, response = reviewed_publish(client, saved, trust=False)
    assert response.status_code == 200
    assert 'builder_unattended_approval' not in response.json['workflow']
    assert response.json['publication_compatibility']['requires_builder_approval'] is True


def test_edit_of_trusted_recipe_requires_fresh_explicit_consent(publication):
    _, _, client = publication
    draft = client.post('/api/drafts', json={'workflow': recipe('needs_approval')}).json['draft']
    preview, response = reviewed_publish(client, draft)
    current = response.json['draft']
    current['workflow']['name'] = 'Edited after approval'
    saved = client.patch(f"/api/drafts/{draft['id']}", json={'revision': current['revision'], 'workflow': current['workflow']}).json['draft']
    stale = client.post(f"/api/drafts/{draft['id']}/publish", json={
        'revision': saved['revision'], 'trust_unattended': True, 'preview_hash': preview['recipe_hash'],
        'trust_tools': ['needs_approval']})
    assert stale.status_code == 409
    _, no_trust = reviewed_publish(client, saved, trust=False)
    assert no_trust.status_code == 200
    assert 'builder_unattended_approval' not in no_trust.json['workflow']


def test_changed_permission_list_requires_another_review_before_trust(publication):
    root, _, client = publication
    draft = client.post('/api/drafts', json={'workflow': recipe('needs_approval')}).json['draft']
    preview = client.post(f"/api/drafts/{draft['id']}/publish-preview", json={'revision': draft['revision']}).json
    (root / 'skills/calculator.tool.json').write_text(json.dumps({'name': 'calculator', 'permissions': {'auto_approve': False}}))
    response = client.post(f"/api/drafts/{draft['id']}/publish", json={
        'revision': draft['revision'], 'trust_unattended': True, 'preview_hash': preview['recipe_hash'],
        'trust_tools': preview['publication_compatibility']['trustable_tools']})
    assert response.status_code == 409
    assert list((root / 'data/workflows').rglob('*.json')) == []
