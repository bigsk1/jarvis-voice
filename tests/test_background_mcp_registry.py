"""Reviewed MCP background metadata preserves ordinary discovery boundaries."""

import json
import os
import subprocess
import sys
import textwrap
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from tool_schema import ToolRegistry

TOOL = 'mcp_google_workspace_run_script_function'
PROJECT_LOOKUP = 'mcp_google_workspace_get_script_project'


def raw_tool(name='run_script_function'):
    return {
        'name': name,
        'description': 'Run the selected Apps Script function.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'script_id': {'type': 'string'},
                'function_name': {'type': 'string'},
                'user_google_email': {'type': 'string'},
            },
            'required': ['script_id', 'function_name', 'user_google_email'],
        },
        'annotations': {'readOnlyHint': False},
    }


def registry(*, blocked_profile=False):
    value = ToolRegistry.__new__(ToolRegistry)
    value.tools = {}
    value.mcp_clients = {}
    value._profile_overrides = {TOOL: False} if blocked_profile else {}
    value._refresh_tool_dependencies = lambda: None
    return value


def client():
    return SimpleNamespace(
        tool_defaults={'user_google_email': 'dedicated@example.test'},
        proxy_policy='off',
    )


def test_reviewed_tool_has_optional_background_capability_without_new_model_arguments():
    catalog = registry()
    raw = raw_tool()
    original = deepcopy(raw)

    assert catalog._register_mcp_tools('google_workspace', client(), {}, [raw]) == 1

    schema = catalog.get_tool(TOOL)
    assert schema.background_adapter == 'mcp_tool_v1'
    assert schema.background_execution['timeout_seconds'] == 420
    assert schema.background_execution['completion_scope'] == 'remote_work'
    assert schema.background_required is False
    assert schema.permissions['dangerous'] is True
    assert schema.permissions['auto_approve'] is True
    assert 'user_google_email' not in schema.parameters['properties']
    assert 'user_google_email' not in schema.parameters['required']
    assert 'dedicated@example.test' in schema.description
    assert 'execution' not in schema.to_openai_format()['function']['parameters']['properties']
    assert raw == original


@pytest.mark.parametrize(('server', 'name'), [
    ('google_workspace', 'create_spreadsheet'),
    ('another_server', 'run_script_function'),
])
def test_unreviewed_server_or_tool_cannot_declare_its_own_background_adapter(server, name):
    catalog = registry()
    spoof = {'tool_metadata': {name: {'execution': {'background': {
        'supported': True, 'adapter': 'mcp_tool_v1', 'timeout_seconds': 420,
    }}}}}

    catalog._register_mcp_tools(server, client(), spoof, [raw_tool(name)])

    schema = catalog.get_tool(f'mcp_{server}_{name}')
    assert schema.background_adapter is None
    assert schema.background_required is False


@pytest.mark.parametrize('boundary', ['server_allowlist', 'profile'])
def test_background_registration_does_not_bypass_existing_discovery_restrictions(boundary):
    catalog = registry(blocked_profile=boundary == 'profile')
    config = {'allowed_tools': ['create_spreadsheet']} if boundary == 'server_allowlist' else {}

    assert catalog._register_mcp_tools('google_workspace', client(), config, [raw_tool()]) == 0
    assert catalog.get_tool(TOOL) is None


@pytest.mark.parametrize('boundary', ['available', 'request_exclusion', 'profile', 'server_allowlist'])
def test_apps_script_execution_retrieval_carries_source_lookup_from_tracked_config(boundary, monkeypatch):
    """Retrieving execution offers source discovery without bypassing tool blocks."""
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'orchestrator'))
    from router_v2 import expand_prerequisite_tool_names

    config_path = root / 'config' / 'mcp-servers.json'
    config = json.loads(config_path.read_text())['mcpServers']['google_workspace']
    catalog = registry()
    if boundary == 'profile':
        catalog._profile_overrides[PROJECT_LOOKUP] = False
    elif boundary == 'server_allowlist':
        config['allowed_tools'] = ['run_script_function']
    lookup = {
        'name': 'get_script_project',
        'description': 'Read Apps Script projects and their source files.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'action': {'type': 'string'},
                'script_id': {'type': 'string'},
                'file_name': {'type': 'string'},
                'user_google_email': {'type': 'string'},
            },
            'required': ['action', 'user_google_email'],
        },
        'annotations': {'readOnlyHint': True},
    }
    catalog._register_mcp_tools('google_workspace', client(), config, [raw_tool(), lookup])

    names, added = expand_prerequisite_tool_names(
        [TOOL], catalog, set(catalog.list_tools()),
        excluded_tools={PROJECT_LOOKUP} if boundary == 'request_exclusion' else set(),
    )

    if boundary == 'available':
        assert names == [PROJECT_LOOKUP, TOOL]
        assert added == [f'{TOOL}:{PROJECT_LOOKUP}']
        model_schemas = [catalog.get_tool(name).to_openai_format()['function'] for name in names]
        assert [schema['name'] for schema in model_schemas] == [PROJECT_LOOKUP, TOOL]
        assert model_schemas[0]['parameters']['required'] == ['action']
        assert 'file_name' in model_schemas[0]['parameters']['properties']
        assert model_schemas[1]['parameters']['required'] == ['script_id', 'function_name']
        assert all('user_google_email' not in schema['parameters']['properties']
                   for schema in model_schemas)
        assert catalog.get_tool(PROJECT_LOOKUP).background_adapter is None
        assert catalog.get_tool(TOOL).background_adapter == 'mcp_tool_v1'
        existing_names, existing_added = expand_prerequisite_tool_names(
            names, catalog, set(catalog.list_tools()),
        )
        assert existing_names == names
        assert existing_added == []
    else:
        assert names == [TOOL]
        assert added == []


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_native_sync_import_layout_discovers_mcp_without_loading_workers(tmp_path, mode):
    """Direct bin scripts expose lib/, without pytest's repository-root path."""
    probe = tmp_path / 'probe.py'
    probe.write_text(textwrap.dedent('''
        import json
        import sys
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch

        root, fixture = Path(sys.argv[1]), Path(sys.argv[2])
        sys.path.insert(0, str(root / 'lib'))
        assert str(root) not in sys.path
        from config_loader import config_scope
        from tool_schema import ToolRegistry

        class Client:
            proxy_policy = 'off'
            tool_defaults = {'user_google_email': 'dedicated@example.test'}

            def __init__(self, names):
                self.names = names

            def start(self):
                pass

            def stop(self):
                pass

            def list_tools(self):
                return [{'name': name, 'description': name, 'inputSchema': {
                    'type': 'object', 'properties': {},
                }} for name in self.names]

        clients = {
            'google_workspace': Client(['run_script_function', 'get_doc_content']),
            'remote_docs': Client(['search']),
        }
        manager = SimpleNamespace(servers=clients)
        config = fixture / 'mcp.json'
        config.write_text(json.dumps({'mcpServers': {
            name: {'enabled': True} for name in clients
        }}))
        with (
            patch('config_loader._load_mode_config', return_value={}),
            patch('mcp_client.MCPManager', return_value=manager),
            patch('tool_profiles.load_active_profile_overrides', return_value={}),
            patch('tool_profiles.warn_missing_profile_file'),
            patch('time.sleep'),
            config_scope(sys.argv[3]),
        ):
            registry = ToolRegistry(str(fixture / 'skills'), str(config))
        assert not registry.mcp_unavailable, registry.mcp_unavailable
        assert set(registry.list_tools()) == {
            'mcp_google_workspace_run_script_function',
            'mcp_google_workspace_get_doc_content', 'mcp_remote_docs_search',
        }
        assert registry.get_tool('mcp_google_workspace_run_script_function').background_adapter == 'mcp_tool_v1'
        assert registry.get_tool('mcp_google_workspace_get_doc_content').background_adapter is None
        assert registry.get_tool('mcp_remote_docs_search').background_adapter is None
        assert not any(name == 'background_tasks' or name.startswith('background_tasks.')
                       or name.startswith('lib.background_tasks') for name in sys.modules)
        print(json.dumps({'registered': len(registry.tools), 'mode': sys.argv[3]}))
    '''))
    result = subprocess.run(
        [sys.executable, '-I', str(probe), str(Path(__file__).resolve().parents[1]),
         str(tmp_path), mode], cwd=tmp_path,
        env={'PATH': os.defpath}, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"registered": 3' in result.stdout
