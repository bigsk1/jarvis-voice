"""Google MCP boundaries: optional activation, receipts, replay and private setup."""

import asyncio
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import config_loader
import test_mcp_discovery_graceful as discovery_helpers
from config_loader import config_scope
from mcp_client import MCPManager, MCPRemoteClient, _normalize_call_tool_result
from test_deepwiki_context import _assembler, followup
from test_structured_results_adapters import _run_renderer_assertions

from lib.google_workspace import normalize_workspace_result, project_workspace_data

ROOT = Path(__file__).resolve().parents[1]
TOOL = "mcp_google_workspace_create_spreadsheet"
FILE_ID = "sheet-returned-123"
FILE_URL = f"https://docs.google.com/spreadsheets/d/{FILE_ID}/edit"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(title="First sheet", file_id=FILE_ID):
    return normalize_workspace_result("create_spreadsheet", {"content": [{"type": "text", "text": (
        f"Successfully created spreadsheet '{title}'. "
        f"ID: {file_id} | URL: https://docs.google.com/spreadsheets/d/{file_id}/edit | Locale: en_US"
    )}]}, {"title": title, "user_google_email": "dedicated@example.test"})


@pytest.mark.parametrize("flag", [None, "false", "0", "true", "1", "yes"])
def test_optional_server_requires_selected_mode_enable_and_secret(tmp_path, monkeypatch, flag):
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("GOOGLE_WORKSPACE_MCP_ENABLED=true\nGOOGLE_WORKSPACE_MCP_TOKEN=cloud-secret\nGOOGLE_ACCOUNT=cloud@example.test\n")
    (config_dir / "local.env").write_text("GOOGLE_ACCOUNT=local@example.test\n")
    config_path = tmp_path / "mcp.json"
    server = json.loads((ROOT / "config/mcp-servers.json").read_text())["mcpServers"]["google_workspace"]
    config_path.write_text(json.dumps({"mcpServers": {"google_workspace": server}}))
    overrides = {} if flag is None else {"GOOGLE_WORKSPACE_MCP_ENABLED": flag}
    with config_scope("local", overrides=overrides):
        assert not MCPManager(str(config_path)).servers  # Never borrow cloud's token.
    with config_scope("local", overrides={**overrides, "GOOGLE_WORKSPACE_MCP_TOKEN": "local-secret"}):
        manager = MCPManager(str(config_path))
        assert bool(manager.servers) == (flag in {"true", "1", "yes"})
    with config_scope("cloud", overrides={"GOOGLE_WORKSPACE_MCP_URL": "http://service:8000/mcp"}):
        connection = MCPManager(str(config_path)).servers["google_workspace"]
        assert connection.url == "http://service:8000/mcp"
        assert connection.headers == {"Authorization": "Bearer cloud-secret"}
        assert connection.tool_defaults == {"user_google_email": "cloud@example.test"}
        assert connection.proxy_policy == "off"


@pytest.mark.parametrize("account_arguments", [
    {}, {"user_google_email": None}, {"user_google_email": "boss@example.com"},
])
def test_configured_account_default_reaches_protocol_and_receipt(monkeypatch, account_arguments):
    connection = MCPRemoteClient("google_workspace", "http://localhost/mcp", "http")
    connection.tool_defaults = {"user_google_email": "dedicated@example.test"}
    calls = []
    def send(method, parameters):
        calls.append((method, parameters))
        return {"content": [{"type": "text", "text": "ID: file-123"}]}
    monkeypatch.setattr(connection, "_send_request", send)
    result = connection.call_tool("get_drive_file_content", {"file_id": "file-123", **account_arguments})
    assert calls[0][1]["arguments"] == {"file_id": "file-123", "user_google_email": "dedicated@example.test"}
    assert result["data"]["request"] == calls[0][1]["arguments"]
    assert result["ok"]


def test_dedicated_identity_is_in_descriptions_and_absent_from_model_parameters():
    class GoogleClient(discovery_helpers.FakeRemoteClient):
        name = "google_workspace"
        def __init__(self):
            super().__init__()
            self.name = "google_workspace"
            self.tool_defaults = {"user_google_email": "dedicated@example.test"}
        def list_tools(self):
            return [{
                "name": "list_gmail_labels",
                "description": "Lists Gmail labels.\nArgs:\n    user_google_email (str): Account email. Required.\n",
                "inputSchema": {"type": "object", "properties": {
                    "user_google_email": {"type": "string"},
                    "prefix": {"type": "string"},
                }, "required": ["user_google_email"]},
            }]

    registry = discovery_helpers.TestMCPDiscoveryGraceful()._build_registry(GoogleClient())
    schema = registry.tools["mcp_google_workspace_list_gmail_labels"]
    assert "user_google_email" not in schema.parameters["properties"]
    assert "user_google_email" not in schema.parameters["required"]
    assert "prefix" in schema.parameters["properties"]
    assert "dedicated@example.test" in schema.to_ollama_description()
    assert "dedicated@example.test" in schema.to_openai_format()["function"]["description"]
    assert "dedicated@example.test" in schema.to_anthropic_format()["description"]
    assert "Account email. Required" not in schema.description


def test_account_independent_google_helper_does_not_receive_login_argument(monkeypatch):
    client = MCPRemoteClient("google_workspace", "http://localhost/mcp", "http")
    client.tool_defaults = {"user_google_email": "dedicated@example.test"}
    client._tools_cache = [{"name": "generate_trigger_code", "inputSchema": {
        "properties": {"handler_function": {"type": "string"}},
    }}]
    sent = []
    def send(method, parameters):
        sent.append(parameters["arguments"])
        return {"content": [{"type": "text", "text": "Generated trigger code."}]}
    monkeypatch.setattr(client, "_send_request", send)
    assert client.call_tool("generate_trigger_code", {"handler_function": "runDaily"})["ok"]
    assert sent == [{"handler_function": "runDaily"}]


def test_gmail_draft_hints_and_search_prerequisite_reach_registered_schema():
    client = discovery_helpers.FakeRemoteClient()
    client.name = 'google_workspace'
    client.tool_defaults = {'user_google_email': 'dedicated@example.test'}
    client.list_tools = lambda: [{
        'name': name, 'description': 'Upstream Gmail operation.',
        'inputSchema': {'type': 'object', 'properties': {
            'user_google_email': {'type': 'string'},
            **{parameter: {'type': 'string'} for parameter in parameters},
        }, 'required': ['user_google_email', *parameters]},
    } for name, parameters in (
        ('draft_gmail_message', ['subject', 'body']), ('search_gmail_messages', ['query']),
        ('get_gmail_message_content', ['message_id']),
    )]
    config = json.loads((ROOT / 'config/mcp-servers.json').read_text())['mcpServers']['google_workspace']
    registry = discovery_helpers.TestMCPDiscoveryGraceful()._build_registry(client, tool_metadata=config['tool_metadata'])
    reader = registry.get_tool('mcp_google_workspace_get_gmail_message_content')
    assert 'Draft ID' in reader.description
    assert 'in:drafts' in reader.description
    assert 'Draft ID' in reader.parameters['properties']['message_id']['description']
    assert reader.prerequisite_tools == ['mcp_google_workspace_search_gmail_messages']
    assert 'Returns a Draft ID' in registry.get_tool('mcp_google_workspace_draft_gmail_message').description
    assert 'Show me that draft' in registry.get_tool('mcp_google_workspace_search_gmail_messages').description


@pytest.mark.parametrize('tool_name', ['send_gmail_message', 'draft_gmail_message'])
def test_local_contact_hints_reach_registered_gmail_schema(tool_name):
    client = discovery_helpers.FakeRemoteClient()
    client.name = 'google_workspace'
    client.list_tools = lambda: [{
        'name': tool_name, 'description': 'Upstream Gmail operation.',
        'inputSchema': {'type': 'object', 'properties': {
            key: {'type': 'string', 'description': 'Upstream email parameter.'}
            for key in ('to', 'cc', 'bcc', 'from_email')
        }},
    }]
    registry = discovery_helpers.TestMCPDiscoveryGraceful()._build_registry(client)
    schema = registry.get_tool('mcp_google_workspace_' + tool_name)
    assert 'config/contacts.json' in schema.description
    assert 'Unknown names fail without sending' in schema.description
    for key in ('to', 'cc', 'bcc'):
        assert 'contact key or display name' in schema.parameters['properties'][key]['description']
    assert schema.parameters['properties']['from_email']['description'] == 'Upstream email parameter.'


@pytest.mark.parametrize('draft_id', ['r1234567890123456789', 'r-123456789'])
def test_draft_id_is_rejected_before_calling_message_endpoint(monkeypatch, draft_id):
    from unittest.mock import Mock
    client = MCPRemoteClient('google_workspace', 'http://localhost/mcp', 'http')
    protocol = Mock(return_value={'content': [{'text': 'Message ID: 1abcdef0123456789'}]})
    monkeypatch.setattr(client, '_send_request', protocol)
    result = client.call_tool('get_gmail_message_content', {'message_id': draft_id})
    assert not result['ok']
    assert 'Draft ID' in result['error'] and 'in:drafts' in result['error']
    protocol.assert_not_called()
    assert client.call_tool('get_gmail_message_content', {'message_id': '1abcdef0123456789'})['ok']
    assert protocol.call_args[0][1]['arguments']['message_id'] == '1abcdef0123456789'


@pytest.mark.parametrize("text,is_error", [
    ("Error: denied", False), ("**Error:** access denied", False),
    ("**ACTION REQUIRED: Google Authentication Needed**\nhttps://accounts.google.com/o/oauth2/auth?state=x", False),
    ("Google API denied", True), ("", False),
])
def test_errors_and_consent_are_not_success_receipts(text, is_error):
    result = _normalize_call_tool_result("search_drive_files", {
        "isError": is_error, "content": [{"type": "text", "text": text}],
    }, server_name="google_workspace")
    assert result["ok"] is False
    assert "error" in result


def test_document_body_error_word_is_not_mistaken_for_a_tool_error():
    result = normalize_workspace_result("get_doc_content", {"content": [{"type": "text", "text":
        "Document ID: doc-123\n--- CONTENT ---\nError: this is a line in the document."}]})
    assert result["ok"] is True


def test_complete_tier_consent_url_is_preserved_intact():
    url = "https://accounts.google.com/o/oauth2/auth?scope=" + "scope%20" * 600
    result = normalize_workspace_result("start_google_auth", {"content": [{"type": "text", "text":
        f"**ACTION REQUIRED: Google Authentication Needed**\nAuthorization URL: {url}"}]})
    assert result["ok"] is False
    assert result["data"]["authentication_required"] is True
    assert result["data"]["links"][0]["url"] == url


def test_disabled_api_error_becomes_actionable_setup_metadata():
    result = normalize_workspace_result("list_gmail_labels", {"isError": True, "content": [{
        "type": "text", "text": (
            "Gmail API is not enabled for your project (123456789).\n"
            "Enable it here: https://console.cloud.google.com/flows/enableapi?apiid=gmail.googleapis.com"
        ),
    }]})
    assert result["ok"] is False
    assert result["data"]["configuration_required"] == {
        "reason": "api_disabled", "api_id": "gmail.googleapis.com", "project_number": "123456789",
    }


@pytest.mark.parametrize('tool_name, text, resource_id, url', [
    ('create_form',
     'Successfully created form. Form ID: returned-form-123. Edit URL: https://docs.google.com/forms/d/returned-form-123/edit.',
     'returned-form-123', 'https://docs.google.com/forms/d/returned-form-123/edit'),
    ('create_drive_folder',
     "Successfully created folder 'Research' (ID: returned-folder-123) in folder 'root' for dedicated@example.test. Link: https://drive.google.com/drive/folders/returned-folder-123",
     'returned-folder-123', 'https://drive.google.com/drive/folders/returned-folder-123'),
])
def test_creation_receipt_retains_clean_id_and_provider_button(tool_name, text, resource_id, url):
    result = normalize_workspace_result(tool_name, {'content': [{'type': 'text', 'text': text}]})
    assert result['data']['references'][0]['id'] == resource_id
    assert result['data']['links'][0]['url'] == url
    _run_renderer_assertions(f"""
const payload = {json.dumps(result)};
const html = renderer.render({{['mcp_google_workspace_' + payload.data.tool]: payload}});
assert.ok(html.includes('href="' + {json.dumps(url)}));
""")


def test_pagination_and_contact_resource_handles_survive_long_text():
    result = normalize_workspace_result("list_contacts", {"content": [{"type": "text", "text":
        "Contact details. " * 1500 + "\nResource Name: people/c1234\nNext page token: opaque-token=."}]})
    compact = project_workspace_data(result)
    assert compact["references"] == [
        {"label": "Resource Name", "id": "people/c1234"},
        {"label": "Next page token", "id": "opaque-token=."},
    ]


def test_streamable_http_utf8_event_survives_requests_latin1_default():
    message = {"jsonrpc": "2.0", "id": 7, "result": {
        "content": [{"type": "text", "text": "✅ File moved to trash. Separator: \u2028 retained."}],
    }}
    response = requests.Response()
    response.encoding = "ISO-8859-1"
    response._content = ("event: message\ndata: " + json.dumps(message, ensure_ascii=False) + "\n\n").encode()
    response._content_consumed = True
    client = MCPRemoteClient("google_workspace", "http://localhost/mcp", "http")
    assert client._parse_sse_response(response) == message


@pytest.mark.parametrize("budget", [512, 1200, 2500, 4500])
def test_bounded_projection_keeps_complete_handles_and_does_not_mutate(budget):
    result = _result()
    result["data"]["response_text"] = "界" * 16000
    result["data"]["api_token"] = "SECRET_SENTINEL"
    result["data"]["links"] *= 20
    result["data"]["references"] *= 20
    before = deepcopy(result)
    projected = project_workspace_data(result, max_chars=budget)
    encoded = json.dumps(projected)
    assert len(encoded) <= budget
    assert "SECRET_SENTINEL" not in encoded
    assert projected["context_truncated"] is True
    assert result == before
    for reference in projected["references"]:
        assert reference["id"] == FILE_ID
    for link in projected["links"]:
        assert link["url"] == FILE_URL


def test_complete_workspace_receipt_drops_duplicate_echo_without_truncation():
    result = _result()
    result['data']['structured_result'] = {'result': result['data']['response_text']}
    before = deepcopy(result)
    assembler = _assembler()
    preview, total, shown, truncated = assembler.build_llm_result_context_preview(TOOL, result)
    assert shown < total
    assert not truncated
    projected = json.loads(preview)['data']
    assert projected['response_excerpt'] == result['data']['response_text']
    assert 'structured_result' not in projected
    message, metadata = assembler.build_provider_tool_result_message(tool_name=TOOL, arguments={}, result=result)
    assert not metadata['result_truncated']
    assert 'result_chars_total=' not in message
    assert result == before


def test_workspace_projection_retains_distinct_structured_evidence():
    result = _result()
    result['data']['structured_result'] = {'result': 'Additional API detail', 'revision': 'revision-123'}
    assert project_workspace_data(result)['structured_result'] == result['data']['structured_result']


def test_saved_stash_receipt_uses_browser_link_in_all_model_contexts():
    download_tool = 'mcp_google_workspace_get_drive_file_download_url'
    private_url = 'http://localhost:8765/attachments/12345678-1234-1234-1234-123456789abc'
    text = f'File downloaded successfully!\nDownload URL: {private_url}\nThe file will expire after 1 hour.'
    result = normalize_workspace_result('get_drive_file_download_url', {'content': [{'text': text}], 'structuredContent': {'result': text}})
    result['data']['artifacts'] = [{'space_id': 'space_pdf', 'file_id': 'f_pdf', 'mode': 'cloud',
                                  'ref': 'stash://space_pdf/f_pdf', 'download_url': 'https://untrusted.example/wrong'}]
    before = deepcopy(result)
    browser_url = '/api/stash/space_pdf/f_pdf?mode=cloud'
    projected = project_workspace_data(result)
    assert private_url not in json.dumps(projected)
    assert browser_url in projected['response_excerpt']
    assert projected['artifacts'][0]['download_url'] == browser_url
    assert 'The file will expire after' not in projected['response_excerpt']
    assert not projected['context_truncated']
    assembler = _assembler()
    preview = assembler.build_llm_result_context_preview(download_tool, result)[0]
    provider = assembler.build_provider_tool_result_message(tool_name=download_tool, arguments={}, result=result)[0]
    synthesis = assembler.extract_useful_data({download_tool: result}, has_text_summarizer_summary_for_ref=lambda *_: False)
    saved = followup.extract_followup_data({download_tool: result['data']})
    for context in (preview, provider, synthesis, json.dumps(saved)):
        assert private_url not in context
        assert browser_url in context
    assert result == before


def test_repeated_runs_provider_context_and_workflow_keep_their_own_ids():
    first, second = _result(), _result("Second sheet", "sheet-second")
    saved = followup.extract_followup_data({TOOL: [first["data"], second["data"]]})[TOOL]
    assert saved["runs_count"] == 2
    assert [item["request"]["title"] for item in saved["results"]] == ["First sheet", "Second sheet"]
    assert [item["references"][0]["id"] for item in saved["results"]] == [FILE_ID, "sheet-second"]
    assembler = _assembler()
    preview, _, _, _ = assembler.build_llm_result_context_preview(TOOL, first)
    assert json.loads(preview)["data"]["references"][0]["id"] == FILE_ID
    first["data"]["response_text"] = "Long content. " * 1000
    message, _ = assembler.build_provider_tool_result_message(
        tool_name=TOOL, arguments={}, result=first, max_chars=1800,
    )
    assert len(message) <= 1800
    projected = json.loads(message.split("\nResult:\n")[1])["result"]["data"]
    assert projected["references"][0]["id"] == FILE_ID
    workflow = {"ok": True, "data": {"action": "run", "workflow_id": "sheets", "results": [
        {"tool": TOOL, "ok": True, "data": second["data"]},
    ]}}
    steps = assembler.build_workflow_result_preview(workflow, max_chars=8000)["llm_context_preview"]["step_results"]
    assert json.loads(steps[0]["result_preview"])["results"][0]["references"][0]["id"] == "sheet-second"
    saved_workflow = followup.extract_followup_data({"workflow": workflow["data"]})
    assert saved_workflow[TOOL]["request"]["title"] == "Second sheet"


def test_web_preview_escapes_google_text_and_handles_future_tools_and_repeated_calls():
    _run_renderer_assertions("""
const tool = 'mcp_google_workspace_future_tool';
const payload = {
  source: 'google_workspace', tool: 'future_tool', ok: true,
  response_text: '<script>alert(1)</script> Result ID: retained-id',
  request: {subject: 'Dedicated account result'},
  references: [{label: 'ID', id: 'retained-id'}],
  links: [{title: 'Document', url: 'https://docs.google.com/document/d/retained-id/edit'},
          {title: 'Unsafe', url: 'javascript:alert(1)'}],
};
const html = renderer.render({[tool]: payload});
assert.ok(html.includes('Google Workspace'));
assert.ok(html.includes('retained-id'));
assert.ok(html.includes('Read response'));
assert.ok(html.includes('&lt;script&gt;'));
assert.ok(!html.includes('<script>'));
assert.ok(!html.includes('href="javascript:'));
assert.ok(!html.includes('href="https://docs.google.com/document/d/retained-id/edit'));
const repeated = renderer.render({[tool]: [payload, {...payload, request: {subject: 'Second result'}}],
  _tool_trace: [{tool, ok: true}, {tool, ok: true}]});
assert.ok(repeated.includes('Dedicated account result'));
assert.ok(repeated.includes('Second result'));
""")


@pytest.mark.parametrize("path,method,headers,status", [
    ("/mcp", "POST", [], 401),
    ("/mcp", "GET", [(b"authorization", b"Bearer wrong")], 401),
    ("/attachments/file.txt", "GET", [], 401),
    ("/oauth2callback", "POST", [], 401),
    ("/oauth2callback", "GET", [], 204),
    ("/health", "GET", [], 204),
    ("/mcp", "POST", [(b"authorization", b"Bearer " + b"x" * 48)], 204),
])
def test_http_access_boundary_keeps_callback_public_and_tools_private(path, method, headers, status):
    middleware = _load(ROOT / "google-workspace/entrypoint.py", "google_test_entrypoint")
    sent = []
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 204})
    async def send(value):
        sent.append(value)
    wrapped = middleware.ServiceTokenMiddleware(app, "x" * 48)
    asyncio.run(wrapped({"type": "http", "path": path, "method": method, "headers": headers}, None, send))
    assert sent[0]["status"] == status


def test_upstream_uvicorn_configuration_disables_query_access_logging():
    middleware = _load(ROOT / "google-workspace/entrypoint.py", "google_test_runtime")
    class FakeServer:
        def http_app(self, **kwargs):
            return kwargs
        def run(self, **kwargs):
            return kwargs
    def wrap(cls, **kwargs):
        return (cls, kwargs)
    middleware.configure_server(FakeServer, wrap, "x" * 48)
    server = FakeServer()
    options = server.run(transport="streamable-http", uvicorn_config={"log_level": "warning", "access_log": True})
    assert options["uvicorn_config"] == {"log_level": "warning", "access_log": False}
    assert server.http_app()["middleware"][0][0] is middleware.ServiceTokenMiddleware


def test_setup_copies_only_explicit_keys_and_changes_only_selected_mode(tmp_path, monkeypatch):
    setup = _load(ROOT / "lib/google_workspace_setup.py", "google_test_setup")
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "SERVICE", tmp_path / "google-workspace")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    cloud_text = "GOOGLE_ACCOUNT=dedicated@gmail.com\nGOOGLE_OAUTH_CLIENT_ID=cloud-client\nGOOGLE_OAUTH_CLIENT_SECRET=client-secret\nGOOGLE_ACCOUNT_PASSWORD=PASSWORD_SENTINEL\nUNRELATED_SECRET=UNRELATED_SENTINEL\n"
    (config_dir / "cloud.env").write_text(cloud_text)
    (config_dir / "local.env").write_text("GOOGLE_ACCOUNT=dedicated@gmail.com\n")
    setup.prepare("cloud")
    private = setup.service_config()
    service_text = (setup.SERVICE / ".env").read_text()
    assert "PASSWORD_SENTINEL" not in service_text and "UNRELATED_SENTINEL" not in service_text
    assert private["GOOGLE_OAUTH_CLIENT_ID"] == "cloud-client"
    assert (setup.SERVICE / ".env").stat().st_mode & 0o777 == 0o600
    assert (setup.SERVICE / "data").stat().st_mode & 0o777 == 0o700
    setup.prepare("cloud")
    assert setup.service_config()["GOOGLE_WORKSPACE_MCP_TOKEN"] == private["GOOGLE_WORKSPACE_MCP_TOKEN"]
    setup.update_mode_settings("local", {"GOOGLE_WORKSPACE_MCP_ENABLED": "false"})
    assert (config_dir / "cloud.env").read_text() == cloud_text
    assert 'GOOGLE_WORKSPACE_MCP_ENABLED="false"' in (config_dir / "local.env").read_text()
    with pytest.raises(ValueError, match="refresh token"):
        setup.enable("cloud")


def test_operator_auth_forces_fresh_offline_consent_without_changing_state():
    from urllib.parse import parse_qs, urlsplit

    setup = _load(ROOT / "lib/google_workspace_setup.py", "google_test_consent")
    url = setup.offline_consent_url(
        "https://accounts.google.com/o/oauth2/auth?state=retained-state&code_challenge=retained-challenge&prompt=select_account"
    )
    query = parse_qs(urlsplit(url).query)
    assert query["state"] == ["retained-state"]
    assert query["code_challenge"] == ["retained-challenge"]
    assert query["prompt"] == ["consent select_account"]
    assert query["access_type"] == ["offline"]


def test_labeled_id_cleanup_reaches_prose_speech_and_structured_replay():
    text = 'Form ID: actual-id. Next Page Token: opaque=. A sentence.'
    result = normalize_workspace_result('create_form', {'content': [{'text': text}], 'structuredContent': {'result': text}})
    assert 'actual-id.' not in json.dumps(result)
    assert 'opaque=.' in result['data']['response_text']
    assert 'A sentence.' in result['speech']
    assert 'actual-id.' not in json.dumps(project_workspace_data(result))


def test_optional_bridge_schema_is_only_on_file_tools():
    from lib.google_workspace import extend_workspace_schema
    plain = {'type': 'object', 'properties': {'query': {'type': 'string'}}}
    assert extend_workspace_schema('list_gmail_labels', plain, 'labels') == 'labels'
    assert set(plain['properties']) == {'query'}
    download = {'properties': {}}
    description = extend_workspace_schema('get_drive_file_download_url', download, 'download')
    assert download['properties']['stash']['default'] is False
    assert 'stash_space_id' in download['properties']
    assert 'stash://' in description
    upload = {'properties': {'file_path': {'type': 'string'}}}
    extend_workspace_schema('create_drive_file', upload, 'upload')
    assert 'stash_ref' in upload['properties']
    assert 'stash' not in upload['properties']


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    from unittest.mock import Mock

    import stash_helper
    monkeypatch.setattr(stash_helper, 'get_stash_dir', lambda: tmp_path / 'custom-stash')
    connection = MCPRemoteClient('google_workspace', 'http://google-workspace:8000/mcp', 'http', {'Authorization': 'Bearer private'}, proxy_policy='off')
    connection.tool_defaults = {'user_google_email': 'dedicated@example.test'}
    connection._tools_cache = [{'name': 'create_drive_file', 'inputSchema': {'properties': {'file_path': {}}}}]
    uuid = '12345678-1234-1234-1234-123456789abc'
    def protocol(method, args):
        return {'content': [{'text': f'Download URL: http://localhost:8765/attachments/{uuid}'}]}
    monkeypatch.setattr(connection, '_send_request', protocol)
    reply = Mock(status_code=200, headers={'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename="test.pdf"'})
    reply.iter_content.return_value = iter([b'%PDF-test'])
    request = Mock(return_value=reply)
    monkeypatch.setattr(connection, '_http_request', request)
    return connection, request, reply, tmp_path / 'custom-stash'


def test_download_without_stash_creates_no_copy_or_http_fetch(bridge):
    connection, request, _, root = bridge
    result = connection.call_tool('get_drive_file_download_url', {'file_id': 'drive-id', 'stash': False})
    assert result['ok']
    assert not root.exists()
    request.assert_not_called()


def test_stash_bridge_uses_configured_origin_and_canonical_root_and_preserves_followups(bridge):
    connection, request, reply, root = bridge
    result = connection.call_tool('get_drive_file_download_url', {'file_id': 'drive-id', 'stash': True})
    assert result['ok']
    artifact = result['data']['artifacts'][0]
    assert artifact['ref'].startswith('stash://')
    assert artifact['download_url'].endswith('?mode=cloud')
    assert list(root.glob('*/test.pdf'))[0].read_bytes() == b'%PDF-test'
    args, kwargs = request.call_args
    assert args[1].startswith('http://google-workspace:8000/attachments/')
    assert kwargs['headers'] == {'Authorization': 'Bearer private'}
    assert kwargs['allow_redirects'] is False
    assert project_workspace_data(result)['artifacts'] == [artifact]
    assert followup.extract_followup_data({'mcp_google_workspace_get_drive_file_download_url': result['data']})['mcp_google_workspace_get_drive_file_download_url']['artifacts'] == [artifact]
    reply.iter_content.return_value = iter([b'%PDF-test'])
    second = connection.call_tool('get_drive_file_download_url', {'file_id': 'drive-id', 'stash': True, 'stash_space_id': artifact['space_id']})
    assert second['data']['artifacts'][0]['ref'] == artifact['ref']
    assert len(list(root.glob('*/*.pdf'))) == 1


@pytest.mark.parametrize('kind', ['redirect', 'oversize-header', 'oversize-stream', 'bad-path'])
def test_stash_failures_preserve_google_success_and_never_save_files(bridge, monkeypatch, kind):
    import google_workspace
    connection, request, reply, root = bridge
    if kind == 'redirect':
        reply.status_code = 302
    elif kind == 'oversize-header':
        reply.headers['Content-Length'] = str(51 * 1024 * 1024)
    elif kind == 'oversize-stream':
        monkeypatch.setattr(google_workspace, '_MAX_BRIDGE_BYTES', 2)
    else:
        monkeypatch.setattr(connection, '_send_request', lambda *a: {'content': [{'text': 'Download URL: http://elsewhere/credentials/secret'}]})
    result = connection.call_tool('get_drive_file_download_url', {'file_id': 'drive-id', 'stash': True})
    assert not result['ok']
    assert result['data']['google_ok']
    assert result['data']['stash_error']
    assert not root.exists()
    if kind == 'bad-path':
        request.assert_not_called()


def test_stash_upload_stages_selected_file_and_cleans_cache_without_exposing_bytes(bridge, monkeypatch):
    from unittest.mock import Mock

    import stash_helper
    connection, request, _, root = bridge
    space, _ = stash_helper.open_space()
    saved = stash_helper.StashFile(space).save_text('private test content', 'test.txt')
    uuid = '12345678-1234-1234-1234-123456789abc'
    stage = Mock(status_code=201)
    stage.json.return_value = {'id': uuid, 'path': '/app/store_creds/attachments/test.txt'}
    request.side_effect = [stage, Mock(status_code=200)]
    calls = []
    def send(method, params):
        calls.append(params)
        return {'content': [{'text': 'File ID: drive-created'}]}
    monkeypatch.setattr(connection, '_send_request', send)
    result = connection.call_tool('create_drive_file', {'name': 'test.txt', 'stash_ref': saved['ref']})
    assert result['ok']
    assert 'stash_ref' not in calls[0]['arguments']
    assert calls[0]['arguments']['file_path'].startswith('/app/store_creds/attachments/')
    assert result['data']['request']['stash_ref'] == saved['ref']
    assert 'private test content' not in json.dumps(result)
    assert request.call_args_list[-1].args[0] == 'DELETE'
    assert request.call_args_list[-1].args[1].endswith('/jarvis/stage/' + uuid)
    assert list(root.glob('*/test.txt'))[0].read_text() == 'private test content'


def test_stash_missing_or_conflicting_upload_never_invokes_google(bridge, monkeypatch):
    connection, request, _, _ = bridge
    from unittest.mock import Mock
    protocol = Mock()
    monkeypatch.setattr(connection, '_send_request', protocol)
    for arguments in ({'stash_ref': 'stash://space_missing/f_missing'},
                      {'stash_ref': 'stash://space_missing/f_missing', 'file_path': '/some/file'},
                      {'stash_ref': 'stash://../../config/cloud.env/f'}, {'stash': 'true'}):
        assert not connection.call_tool('create_drive_file', arguments)['ok']
    request.assert_not_called()
    protocol.assert_not_called()


def test_stash_artifact_web_link_is_escaped_same_origin_and_mode_scoped():
    _run_renderer_assertions("""
sandbox.location = {origin: 'http://jarvis.test'};
const rendered = renderer.render({mcp_google_workspace_get_drive_file_download_url: {data: {
  source: 'google_workspace', response_text: 'Downloaded', artifacts: [{
    space_id: 'space_test', file_id: 'f_123', mode: 'local', name: '<script>unsafe</script>.pdf',
    ref: 'stash://space_test/f_123', download_url: 'https://evil.test/wrong',
  }],
}}});
assert.ok(rendered.includes('http://jarvis.test/api/stash/space_test/f_123?mode=local'));
assert.ok(rendered.includes('Download file'));
assert.ok(!rendered.includes('<script>'));
assert.ok(!rendered.includes('evil.test'));
""")


def test_staging_route_auth_size_limit_and_cleanup_preserve_unrelated_cache(monkeypatch, tmp_path):
    import shutil
    import types
    from types import SimpleNamespace

    wrapper = _load(ROOT / 'google-workspace/entrypoint.py', 'google_bridge_service_test')
    class Storage:
        def save_attachment_from_path(self, path, filename, mime):
            target = tmp_path / ('managed_' + filename)
            shutil.move(path, target)
            return SimpleNamespace(file_id='12345678-1234-1234-1234-123456789abc', path=str(target))
        def _cleanup_file(self, file_id):
            (tmp_path / 'managed_probe.txt').unlink(missing_ok=True)
    module = types.ModuleType('core.attachment_storage')
    module.STORAGE_DIR = tmp_path
    module.get_attachment_storage = lambda: Storage()
    monkeypatch.setitem(sys.modules, 'core', types.ModuleType('core'))
    monkeypatch.setitem(sys.modules, 'core.attachment_storage', module)
    async def upstream(scope, receive, send):
        if scope['type'] == 'lifespan':
            while True:
                event = await receive()
                if event['type'] == 'lifespan.startup':
                    await send({'type': 'lifespan.startup.complete'})
                elif event['type'] == 'lifespan.shutdown':
                    await send({'type': 'lifespan.shutdown.complete'})
                    return
        await send({'type': 'http.response.start', 'status': 204})
        await send({'type': 'http.response.body', 'body': b''})
    app = wrapper.ServiceTokenMiddleware(wrapper.AttachmentBridgeMiddleware(upstream), 'x' * 48)
    headers = {'Authorization': 'Bearer ' + 'x' * 48, 'X-Jarvis-Filename': '..%2Fprobe.txt'}
    (tmp_path / 'unrelated.txt').write_text('keep')
    # Exercise ASGI directly. TestClient's thread portal requires socket
    # wakeups that the shell sandbox denies; disk thread behavior is live-tested.
    async def immediate_thread(function, *args):
        return function(*args)
    monkeypatch.setattr(asyncio, 'to_thread', immediate_thread)
    def call(method, path, content=b'', headers=None):
        sent = []
        async def receive():
            return {'type': 'http.request', 'body': content, 'more_body': False}
        async def send(message):
            sent.append(message)
        asyncio.run(app({'type': 'http', 'method': method, 'path': path,
                         'headers': [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]}, receive, send))
        return sent[0]['status'], json.loads(sent[1].get('body', b'{}'))
    assert call('POST', '/jarvis/stage', b'private')[0] == 401
    assert not (tmp_path / 'managed_probe.txt').exists()
    assert call('POST', '/jarvis/stage', b'a', {**headers, 'Content-Length': str(51*1024*1024)})[0] == 413
    assert not list(tmp_path.glob('stage_*'))
    status, uploaded = call('POST', '/jarvis/stage', b'probe', headers)
    assert status == 201
    assert (tmp_path / 'managed_probe.txt').read_bytes() == b'probe'
    assert call('DELETE', '/jarvis/stage/unrelated', headers=headers)[0] == 404
    assert call('DELETE', '/jarvis/stage/' + uploaded['id'], headers=headers)[0] == 200
    assert not (tmp_path / 'managed_probe.txt').exists()
    assert (tmp_path / 'unrelated.txt').read_text() == 'keep'


def test_stash_upload_google_failure_still_cleans_staging(bridge, monkeypatch):
    from unittest.mock import Mock

    import stash_helper
    connection, request, _, _ = bridge
    space, _ = stash_helper.open_space()
    saved = stash_helper.StashFile(space).save_text('probe', 'test.txt')
    stage = Mock(status_code=201)
    stage.json.return_value = {'id': '12345678-1234-1234-1234-123456789abc', 'path': '/app/store_creds/attachments/test.txt'}
    request.side_effect = [stage, Mock(status_code=200)]
    monkeypatch.setattr(connection, '_send_request', Mock(side_effect=RuntimeError('Google failed')))
    assert not connection.call_tool('create_drive_file', {'stash_ref': saved['ref']})['ok']
    assert request.call_args_list[-1].args[0] == 'DELETE'


def test_gmail_stash_requests_upstream_full_message_export(bridge, monkeypatch):
    from unittest.mock import Mock
    connection, _, _, _ = bridge
    protocol = Mock(return_value={'content': [{'text': 'Download URL: http://localhost:8765/attachments/12345678-1234-1234-1234-123456789abc'}]})
    monkeypatch.setattr(connection, '_send_request', protocol)
    result = connection.call_tool('get_gmail_message_content', {'message_id': 'mail', 'stash': True, 'body_format': 'raw'})
    assert result['ok']
    assert protocol.call_args.args[1]['arguments']['full'] is True
    assert 'stash' not in protocol.call_args.args[1]['arguments']


def test_stash_download_retains_local_mode_for_web_link(bridge):
    connection, _, _, _ = bridge
    with config_scope('local'):
        result = connection.call_tool('get_drive_file_download_url', {'file_id': 'drive-id', 'stash': True})
    assert result['data']['artifacts'][0]['mode'] == 'local'
    assert result['data']['artifacts'][0]['download_url'].endswith('?mode=local')


@pytest.mark.parametrize('use_runtime_override', [False, True])
def test_stash_bridge_resolves_real_configured_root_and_runtime_override(monkeypatch, tmp_path, use_runtime_override):
    from unittest.mock import Mock
    root = tmp_path / ('docker-mounted-stash' if use_runtime_override else 'native-custom-stash')
    if use_runtime_override:
        monkeypatch.setenv('JARVIS_OVERRIDE_STASH_DIR', str(root))
    else:
        monkeypatch.delenv('JARVIS_OVERRIDE_STASH_DIR', raising=False)
    connection = MCPRemoteClient('google_workspace', 'http://service:8000/mcp', 'http')
    uuid = '12345678-1234-1234-1234-123456789abc'
    monkeypatch.setattr(connection, '_send_request', lambda *a: {'content': [{'text': f'Download URL: http://localhost:8765/attachments/{uuid}'}]})
    response = Mock(status_code=200, headers={'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename="test.pdf"'})
    response.iter_content.return_value = iter([b'pdf bytes'])
    monkeypatch.setattr(connection, '_http_request', Mock(return_value=response))
    monkeypatch.setenv('STASH_DIR', str(tmp_path / 'unselected'))
    with config_scope('cloud', overrides={} if use_runtime_override else {'STASH_DIR': str(root)}):
        result = connection.call_tool('get_drive_file_download_url', {'file_id': 'drive-id', 'stash': True})
    assert result['ok']
    assert list(root.glob('*/test.pdf'))[0].read_bytes() == b'pdf bytes'
    assert not (tmp_path / 'unselected').exists()


def test_cancelled_stash_stream_never_publishes_a_file(bridge, monkeypatch):
    from mcp_client import _remote_call_budget
    connection, _, response, root = bridge
    def chunks(**kwargs):
        _remote_call_budget.get().cancelled.set()
        yield b'bytes from cancelled response'
    response.iter_content.side_effect = chunks
    result = connection.call_tool('get_drive_file_download_url', {'file_id': 'drive-id', 'stash': True})
    assert not result['ok']
    assert result['data']['google_ok']
    assert not root.exists()


def test_nullable_stash_option_defaults_to_no_copy(bridge):
    connection, request, _, root = bridge
    assert connection.call_tool('get_drive_file_download_url', {'file_id': 'drive-id', 'stash': None})['ok']
    request.assert_not_called()
    assert not root.exists()


@pytest.mark.parametrize('discovered', [False, True])
def test_account_independent_helper_after_cache_reset_keeps_correct_arguments(monkeypatch, discovered):
    connection = MCPRemoteClient('google_workspace', 'http://localhost/mcp', 'http')
    connection.tool_defaults = {'user_google_email': 'dedicated@example.test'}
    sent = []
    def send(method, params=None):
        if method == 'tools/list':
            return {'tools': [
                {'name': 'generate_trigger_code', 'inputSchema': {'properties': {'handler_function': {}}}},
                {'name': 'list_gmail_labels', 'inputSchema': {'properties': {'user_google_email': {}}}},
            ]}
        sent.append(params['arguments'])
        return {'content': [{'text': 'OK'}]}
    monkeypatch.setattr(connection, '_send_request', send)
    if discovered:
        connection.list_tools()
    connection._force_restart('test timeout')
    assert connection._tools_cache is None
    assert connection.call_tool('generate_trigger_code', {'handler_function': 'run', 'user_google_email': 'guessed@example.test'})['ok']
    assert 'user_google_email' not in sent[-1]
    assert connection.call_tool('list_gmail_labels', {'user_google_email': 'guessed@example.test'})['ok']
    assert sent[-1]['user_google_email'] == 'dedicated@example.test'


def test_stash_upload_schema_facts_survive_tool_list_cache_reset(bridge, monkeypatch):
    from unittest.mock import Mock

    import stash_helper
    connection, request, _, _ = bridge
    connection._tool_properties = {'create_drive_file': {'file_path'}}
    connection._tools_cache = None
    space, _ = stash_helper.open_space()
    saved = stash_helper.StashFile(space).save_text('probe', 'test.txt')
    stage = Mock(status_code=201)
    stage.json.return_value = {'id': '12345678-1234-1234-1234-123456789abc', 'path': '/app/store_creds/attachments/test.txt'}
    request.side_effect = [stage, Mock(status_code=200)]
    monkeypatch.setattr(connection, '_send_request', lambda *a: {'content': [{'text': 'File ID: uploaded'}]})
    assert connection.call_tool('create_drive_file', {'stash_ref': saved['ref']})['ok']


def test_container_skips_upstream_account_injection_only_for_pure_helper():
    wrapper = _load(ROOT / 'google-workspace/entrypoint.py', 'google_helper_wrapper_test')
    seen = []
    class Base:
        async def call_tool(self, name, arguments, *args, **kwargs):
            seen.append((name, arguments))
            return arguments
    class Secure(Base):
        async def call_tool(self, name, arguments, *args, **kwargs):
            arguments = {**(arguments or {}), 'user_google_email': 'dedicated@example.test'}
            return await super().call_tool(name, arguments, *args, **kwargs)
    wrapper.configure_account_independent_tools(Secure, Base)
    server = Secure()
    helper = asyncio.run(server.call_tool('generate_trigger_code', {'function_name': 'run', 'user_google_email': 'wrong@example.test'}))
    assert helper == {'function_name': 'run'}
    regular = asyncio.run(server.call_tool('list_gmail_labels', {}))
    assert regular['user_google_email'] == 'dedicated@example.test'
    assert len(seen) == 2


@pytest.mark.parametrize('missing_key', ['GOOGLE_ACCOUNT', 'GOOGLE_OAUTH_CLIENT_ID', 'GOOGLE_OAUTH_CLIENT_SECRET'])
def test_prepare_never_borrows_existing_service_credentials(tmp_path, monkeypatch, missing_key):
    setup = _load(ROOT / 'lib/google_workspace_setup.py', 'google_prepare_isolation')
    monkeypatch.setattr(setup, 'ROOT', tmp_path)
    monkeypatch.setattr(setup, 'SERVICE', tmp_path / 'google-workspace')
    monkeypatch.setattr(config_loader, 'get_project_root', lambda: tmp_path)
    config = tmp_path / 'config'
    config.mkdir()
    values = {'GOOGLE_ACCOUNT': 'dedicated@gmail.com', 'GOOGLE_OAUTH_CLIENT_ID': 'cloud-id', 'GOOGLE_OAUTH_CLIENT_SECRET': 'cloud-secret'}
    (config / 'cloud.env').write_text(''.join(f'{key}={value}\n' for key, value in values.items()))
    setup.prepare('cloud')
    before = (setup.SERVICE / '.env').read_text()
    (config / 'local.env').write_text(''.join(f'{key}={value}\n' for key, value in values.items() if key != missing_key))
    with pytest.raises(setup.SetupError, match=missing_key):
        setup.prepare('local')
    assert (setup.SERVICE / '.env').read_text() == before


@pytest.mark.parametrize('budget', [2, 32, 80, 128, 256, 512, 1000])
def test_projection_handles_small_budgets_and_large_diagnostics(budget):
    from lib.google_workspace import project_workspace_data
    result = _result()
    result['data'].update({'stash_error': 'oversized diagnostic ' * 1000, 'artifacts': [
        {'ref': 'stash://space_one/f_one', 'name': '長い' * 1000} for _ in range(10)
    ], 'request': {'file_id': 'a' * 1000}})
    before = deepcopy(result)
    projected = project_workspace_data(result, max_chars=budget)
    assert len(json.dumps(projected, ensure_ascii=True)) <= budget
    if projected:
        assert projected.get('context_truncated') is True
    assert result == before


def test_projection_reports_trimming_only_artifacts_or_request():
    from lib.google_workspace import project_workspace_data
    for field, value in (('artifacts', [{'ref': 'stash://space_a/f_a', 'name': 'a'*1000}]), ('request', {'file_id': 'a'*1000})):
        data = {'source': 'google_workspace', 'tool': 'download', 'ok': True, 'response_text': '', field: value}
        projected = project_workspace_data({'data': data}, max_chars=160)
        assert projected['context_truncated']


def test_google_workflow_multiple_runs_keep_per_step_budget():
    runs = [_result()['data'] for _ in range(3)]
    workflow = {'ok': True, 'data': {'action': 'run', 'results': [
        {'tool': TOOL, 'ok': True, 'data': runs} for _ in range(20)
    ]}}
    projected = _assembler().build_workflow_result_preview(workflow, max_chars=8000)
    steps = projected['llm_context_preview']['step_results']
    assert all(len(step['result_preview']) <= 260 for step in steps)
    for step in steps:
        json.loads(step['result_preview'])  # Shrinking must preserve valid JSON.
    assert len(json.dumps(projected)) <= 8000


@pytest.mark.parametrize('tool_name', [
    'get_gmail_message_content', 'get_gmail_thread_content', 'get_gmail_threads_content_batch',
    'get_doc_as_markdown', 'get_events', 'get_form', 'get_presentation', 'future_reader',
])
def test_untrusted_body_links_are_not_provider_actions(tool_name):
    result = normalize_workspace_result(tool_name, {'content': [{'text':
        'Subject: example\nBody: https://phishing.example.test/login https://docs.google.com/document/d/bodylink/edit'}]})
    assert result['data']['links'] == []
    assert 'phishing.example.test' in result['data']['response_text']
    created = _result()
    assert created['data']['links'][0]['url'] == FILE_URL
    _run_renderer_assertions("""
const html = renderer.render({mcp_google_workspace_get_gmail_message_content: {data: {
 source: 'google_workspace', tool: 'get_gmail_message_content', response_text: 'Body with a link',
 links: [{url: 'https://phishing.example.test'}, {url: 'https://docs.google.com/document/d/bodylink/edit'}],
}}});
assert.ok(!html.includes('href="https://phishing.example.test'));
assert.ok(!html.includes('href="https://docs.google.com/document/d/bodylink/edit'));
assert.ok(html.includes('untrusted external content'));
const receipt = renderer.render({mcp_google_workspace_create_doc: {data: {
 source: 'google_workspace', tool: 'create_doc', response_text: 'Created document',
 links: [{url: 'https://docs.google.com/document/d/created/edit'}],
}}});
assert.ok(receipt.includes('href="https://docs.google.com/document/d/created/edit'));
""")


def test_link_policy_names_match_pinned_advertised_catalog():
    from lib.google_workspace import _RECEIPT_LINK_TOOLS
    catalog = json.loads((ROOT / 'tests/fixtures/google_workspace_tool_names.json').read_text())
    assert _RECEIPT_LINK_TOOLS <= set(catalog['tools'])
    assert {'get_gmail_thread_content', 'get_doc_as_markdown', 'get_events'} <= set(catalog['tools'])
    for name in catalog['tools']:
        data = normalize_workspace_result(name, {'content': [{'text': 'https://docs.google.com/document/d/example/edit'}]})['data']
        assert data['content_links_untrusted'] is (name not in _RECEIPT_LINK_TOOLS)


def test_model_cannot_select_container_paths_and_public_url_uploads_remain_optional(bridge, monkeypatch):
    from unittest.mock import Mock
    connection, request, _, root = bridge
    protocol = Mock(return_value={'content': [{'text': 'File ID: uploaded'}]})
    monkeypatch.setattr(connection, '_send_request', protocol)
    for arguments in ({'file_path': '/app/store_creds/credentials/private.json'}, {'file_path': None},
                      *({key: value} for key in ('fileUrl', 'file_url') for value in (
                          'file:///app/store_creds/attachments/some.pdf',
                          '/app/store_creds/attachments/some.pdf', 'relative.pdf',
                          '//example.test/file.pdf', 'ftp://example.test/file.pdf',
                          'https:', '', 123,
                      ))):
        assert not connection.call_tool('create_drive_file', arguments)['ok']
    protocol.assert_not_called()
    assert connection.call_tool('create_drive_file', {'fileUrl': 'https://public.example.test/report.pdf'})['ok']
    assert not root.exists()
    request.assert_not_called()


@pytest.mark.parametrize('tool_name', ['send_gmail_message', 'draft_gmail_message'])
@pytest.mark.parametrize('path', ['/app/store_creds/attachments/guessed.pdf', '', None])
def test_gmail_attachment_paths_never_reach_upstream(bridge, monkeypatch, tool_name, path):
    from unittest.mock import Mock
    connection, request, _, _ = bridge
    protocol = Mock(return_value={'content': [{'text': 'Message ID: created'}]})
    monkeypatch.setattr(connection, '_send_request', protocol)
    assert not connection.call_tool(tool_name, {'attachments': [{'path': path}]})['ok']
    protocol.assert_not_called()
    request.assert_not_called()
    for attachment in ({'url': 'https://public.example.test/file.pdf'},
                       {'content': 'dGVzdA==', 'filename': 'test.txt'}):
        assert connection.call_tool(tool_name, {'attachments': [attachment]})['ok']


def test_gmail_attachment_schema_does_not_advertise_path_loading():
    from lib.google_workspace import extend_workspace_schema
    schema = {'properties': {'attachments': {'type': 'array', 'description': 'OR "path" (file path, auto-encodes)'}}}
    extend_workspace_schema('send_gmail_message', schema, 'send')
    description = schema['properties']['attachments']['description']
    assert 'auto-encodes' not in description
    assert 'not accepted' in description
    calendar = {'properties': {'attachments': {'type': 'array', 'description': 'Calendar Drive files using fileUrl, title, mimeType'}}}
    before = deepcopy(calendar)
    extend_workspace_schema('manage_event', calendar, 'calendar')
    assert calendar == before


def test_synthesis_total_budget_keeps_every_included_json_block_complete():
    import re
    accumulated = {TOOL: [_result(f'Result {index}') for index in range(500)]}
    accumulated['mcp_google_workspace_get_events'] = _result()
    before = deepcopy(accumulated)
    text = _assembler().extract_useful_data(accumulated, has_text_summarizer_summary_for_ref=lambda *_: False)
    assert len(text) <= 10000
    assert 'context_truncated: true' in text
    assert 'omitted_tool_results:' in text
    sections = re.split(r'\n=== [^\n]+ ===\n', text)
    parsed = [json.loads(line) for section in sections for line in section.splitlines() if line.startswith('{')]
    assert parsed and all(isinstance(item, dict) for item in parsed)
    assert any(item.get('context_truncated') is True for item in parsed)
    assert len(parsed) < 501
    assert accumulated == before


def test_concurrent_google_downloads_deduplicate_in_one_space(bridge, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import Mock

    import stash_helper
    connection, request, _, root = bridge
    space, _ = stash_helper.open_space()
    def response(*args, **kwargs):
        reply = Mock(status_code=200, headers={'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename="test.pdf"'})
        reply.iter_content.return_value = iter([b'identical PDF bytes'])
        return reply
    request.side_effect = response
    def download(_):
        return connection.call_tool('get_drive_file_download_url', {'file_id': 'drive-id', 'stash': True, 'stash_space_id': space.space_id})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(download, range(4)))
    assert all(result['ok'] for result in results)
    assert len({result['data']['artifacts'][0]['ref'] for result in results}) == 1
    assert len(stash_helper.get_space(space.space_id).meta['files']) == 1


def test_operator_health_check_tests_real_http_boundary_before_authorized_discovery(monkeypatch):
    from unittest.mock import Mock
    setup = _load(ROOT / 'lib/google_workspace_setup.py', 'google_operator_smoke_test')
    connection = Mock(url='http://localhost:8765/mcp')
    connection._http_request.side_effect = [Mock(status_code=200), Mock(status_code=401)]
    connection.list_tools.return_value = [{'name': 'example'}]
    monkeypatch.setattr(setup, 'service_config', lambda: {'GOOGLE_ACCOUNT': 'dedicated@gmail.com'})
    monkeypatch.setattr(setup, 'client', lambda: connection)
    monkeypatch.setattr(setup, 'stored_grant_status', lambda _: {})
    setup.check()
    calls = connection._http_request.call_args_list
    assert calls[0].args == ('GET', 'http://localhost:8765/health')
    assert calls[1].args == ('POST', 'http://localhost:8765/mcp')
    assert 'Authorization' not in calls[1].kwargs['headers']
    connection.start.assert_called_once()
    connection.stop.assert_called_once()


def test_test_mcp_listing_matches_runtime_selected_mode_gates(tmp_path, monkeypatch, capsys):
    import atexit
    import signal
    probe_dir = tmp_path / 'bin'
    probe_dir.mkdir()
    script = probe_dir / 'mcp_probe.py'
    script.write_text((ROOT / 'bin/test-mcp').read_text())
    monkeypatch.setattr(signal, 'signal', lambda *a: None)
    monkeypatch.setattr(atexit, 'register', lambda *a: None)
    monkeypatch.setattr(config_loader, 'get_project_root', lambda: tmp_path)
    config = tmp_path / 'config'
    config.mkdir()
    server = json.loads((ROOT / 'config/mcp-servers.json').read_text())['mcpServers']['google_workspace']
    (config / 'mcp-servers.json').write_text(json.dumps({'mcpServers': {'google_workspace': server}}))
    (config / 'cloud.env').write_text('GOOGLE_WORKSPACE_MCP_ENABLED=true\nGOOGLE_WORKSPACE_MCP_TOKEN=cloud-secret\nGOOGLE_ACCOUNT=dedicated@gmail.com\n')
    (config / 'local.env').write_text('GOOGLE_WORKSPACE_MCP_ENABLED=true\nGOOGLE_ACCOUNT=dedicated@gmail.com\n')
    probe = _load(script, 'google_mcp_listing_probe')
    for mode, enabled in (('cloud', True), ('local', False)):
        monkeypatch.setattr(sys, 'argv', ['mcp_probe', '--list', '--mode', mode])
        probe.main()
        output = capsys.readouterr().out
        assert f'google_workspace ({"ENABLED" if enabled else "DISABLED"})' in output
        assert 'cloud-secret' not in output
        with config_scope(mode):
            assert bool(MCPManager(str(config / 'mcp-servers.json')).servers) == enabled


def test_google_effect_classification_keeps_operator_selected_autonomy():
    class GoogleClient(discovery_helpers.FakeRemoteClient):
        def __init__(self):
            super().__init__()
            self.name = 'google_workspace'
        def list_tools(self):
            return [{'name': 'send', 'description': 'Send a message', 'annotations': {'readOnlyHint': False},
                     'inputSchema': {'type': 'object', 'properties': {}}}]
    schema = discovery_helpers.TestMCPDiscoveryGraceful()._build_registry(GoogleClient()).get_tool('mcp_google_workspace_send')
    assert schema.permissions['dangerous'] is True
    assert schema.permissions['auto_approve'] is True
    assert not schema.requires_confirmation()
