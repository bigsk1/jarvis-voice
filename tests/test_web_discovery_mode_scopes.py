"""Cloud/local isolation regressions for Web tool, workflow, and prompt discovery."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from server_package_utils import load_server_package


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "jarvis-web"))
load_server_package(
    "jarvis_web_discovery_mode_test",
    ROOT / "jarvis-web" / "server",
)

from config_loader import get_active_config_mode  # noqa: E402
from jarvis_web_discovery_mode_test.routes import api  # noqa: E402
from jarvis_web_discovery_mode_test.services import tool_discovery  # noqa: E402
from jarvis_web_discovery_mode_test.sockets.chat import ChatHandler  # noqa: E402


def _client():
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client()


class _ModeService:
    def __init__(self, mode: str):
        self.mode = mode
        self.tools = [{
            "name": f"{mode}_tool",
            "description": f"{mode} only",
            "source": "local",
            "enabled": True,
            "available": True,
            "blocked": False,
        }]

    def get_tools(self, include_blocked=True):
        return list(self.tools)

    def get_tools_summary(self):
        return list(self.tools)

    def get_tool(self, name):
        return next((tool for tool in self.tools if tool["name"] == name), None)

    def get_tool_count(self):
        return len(self.tools)

    def get_stats(self):
        return {
            "total": len(self.tools),
            "local": len(self.tools),
            "mcp": 0,
            "enabled": len(self.tools),
            "blocked": 0,
            "unavailable": 0,
        }

    def refresh(self):
        return None


def _install_mode_surfaces(monkeypatch, prompts_dir: Path):
    services = {mode: _ModeService(mode) for mode in ("cloud", "local")}

    def scoped_service(mode=None):
        return services[mode or get_active_config_mode()]

    class FakeWorkflowLoader:
        def __init__(self, explicit_only=True):
            self.workflows = {
                mode: {
                    "id": mode,
                    "name": mode.title(),
                    "triggers": {"explicit": [f"/{mode}"]},
                    "steps": [{"step": 1, "tool": f"{mode}_tool"}],
                }
                for mode in ("cloud", "local")
            }

        def get_workflow(self, workflow_id):
            return self.workflows.get(workflow_id)

    monkeypatch.setattr(api, "get_tool_service", scoped_service)
    monkeypatch.setattr(api, "PROMPTS_PATH", prompts_dir)
    monkeypatch.setitem(
        sys.modules,
        "workflow_loader",
        SimpleNamespace(WorkflowLoader=FakeWorkflowLoader),
    )
    return services


def test_discovery_endpoints_follow_requested_mode_not_startup_mode(tmp_path, monkeypatch):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    for mode in ("cloud", "local"):
        (prompts_dir / f"{mode}.md").write_text(
            f"---\ntool_hints:\n  - {mode}_tool\n---\n\n# {mode.title()}\n"
        )
    _install_mode_surfaces(monkeypatch, prompts_dir)
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    before = dict(os.environ)
    client = _client()

    local_tools = client.get("/api/tools?summary=true&mode=local").get_json()
    cloud_tools = client.get("/api/tools?summary=true&mode=cloud").get_json()
    local_workflows = client.get("/api/workflows?mode=local").get_json()
    cloud_workflows = client.get("/api/workflows?mode=cloud").get_json()
    local_prompts = client.get("/api/prompts?mode=local").get_json()
    cloud_prompts = client.get("/api/prompts?mode=cloud").get_json()

    assert [tool["name"] for tool in local_tools["tools"]] == ["local_tool"]
    assert [tool["name"] for tool in cloud_tools["tools"]] == ["cloud_tool"]
    assert list(local_workflows["workflows"]) == ["local"]
    assert list(cloud_workflows["workflows"]) == ["cloud"]
    assert list(local_prompts["prompts"]) == ["local"]
    assert list(cloud_prompts["prompts"]) == ["cloud"]
    assert dict(os.environ) == before


@pytest.mark.parametrize("path", ["/api/tools", "/api/workflows", "/api/prompts"])
def test_discovery_endpoints_reject_invalid_mode(path):
    response = _client().get(f"{path}?mode=locla")
    assert response.status_code == 400
    assert "Mode must" in response.get_json()["error"]


def test_tool_discovery_applies_profile_for_its_own_mode(tmp_path, monkeypatch):
    manifest = {
        "enabled": True,
        "name": "generate_image",
        "description": "Profile probe",
        "script": "generate_image.py",
        "parameters": {"type": "object", "properties": {}},
    }
    (tmp_path / "generate_image.tool.json").write_text(json.dumps(manifest))
    fake_db = MagicMock()
    fake_db.get_enabled_tool_names.return_value = []
    monkeypatch.delenv("JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE", raising=False)

    import memory_db

    with (
        patch.object(tool_discovery, "get_web_setting", return_value=[]),
        patch.object(memory_db, "get_memory_db", return_value=fake_db),
    ):
        cloud = tool_discovery.ToolDiscoveryService(tmp_path, mode="cloud")
        local = tool_discovery.ToolDiscoveryService(tmp_path, mode="local")

    assert cloud.mode == "cloud"
    assert cloud.get_tool("generate_image") is not None
    assert local.mode == "local"
    assert local.get_tool("generate_image") is None


def test_tool_service_cache_is_partitioned_and_refreshable_by_mode(monkeypatch):
    created = []

    class FakeService:
        def __init__(self, mode=None):
            self.mode = mode
            self.refresh_count = 0
            created.append(self)

        def refresh(self):
            self.refresh_count += 1

    tool_discovery.reset_tool_services()
    monkeypatch.setattr(tool_discovery, "ToolDiscoveryService", FakeService)

    cloud = tool_discovery.get_tool_service("cloud")
    local = tool_discovery.get_tool_service("local")
    assert cloud is tool_discovery.get_tool_service("cloud")
    assert local is tool_discovery.get_tool_service("local")
    assert cloud is not local
    assert [service.mode for service in created] == ["cloud", "local"]

    tool_discovery.refresh_tool_services()
    assert cloud.refresh_count == 1
    assert local.refresh_count == 1
    tool_discovery.reset_tool_services()


def test_tool_hint_validation_uses_chat_message_mode(monkeypatch):
    requested_modes = []

    def service_for_mode(mode=None):
        requested_modes.append(mode)
        return _ModeService(mode)

    monkeypatch.setattr(tool_discovery, "get_tool_service", service_for_mode)

    assert ChatHandler._sanitize_tool_hints(
        ["local_tool", "cloud_tool"],
        mode="local",
    ) == ["local_tool"]
    assert requested_modes == ["local"]


def test_browser_registry_requests_mode_and_ignores_stale_mode_response():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8')
  .split('// Global command system instance')[0];
global.window = {jarvisSocket: {mode: 'cloud'}};
global.Utils = {storage: {get: () => 'cloud'}};
const pendingCloud = [];
const seen = [];
const responseFor = (url, mode) => ({
  ok: true,
  json: async () => url.includes('/api/tools')
    ? {tools: [{name: `${mode}_tool`, enabled: true}]}
    : url.includes('/api/prompts')
      ? {prompts: {[mode]: {name: mode}}}
      : {workflows: {[mode]: {name: mode}}}
});
global.fetch = (url) => {
  seen.push(url);
  const mode = url.includes('mode=local') ? 'local' : 'cloud';
  if (mode === 'cloud') {
    return new Promise(resolve => pendingCloud.push(() => resolve(responseFor(url, mode))));
  }
  return Promise.resolve(responseFor(url, mode));
};
eval(source + '\nglobal.CommandSystem = CommandSystem;');

(async () => {
  const commands = Object.create(global.CommandSystem.prototype);
  Object.assign(commands, {
    prompts: {}, workflows: {}, tools: {}, maxToolHints: 5,
    loaded: false, _registryRequestId: 0
  });
  const cloudLoad = commands._loadRegistry('cloud');
  const localLoad = commands.refreshTools('local');
  await localLoad;
  pendingCloud.forEach(resolve => resolve());
  await cloudLoad;

  if (!seen.filter(url => url.includes('mode=local')).length
      || seen.filter(url => url.includes('mode=local')).length !== 3) {
    throw new Error(`Local mode missing from registry URLs: ${seen.join(', ')}`);
  }
  if (!commands.tools.local_tool || commands.tools.cloud_tool) {
    throw new Error(`Stale cloud response replaced local tools: ${JSON.stringify(commands.tools)}`);
  }
  if (!commands.prompts.local || !commands.workflows.local) {
    throw new Error('Local prompt/workflow registries were not retained');
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_browser_tools_sidebar_requests_explicit_mode():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/app.js', 'utf8')
  .split('// Initialize app when DOM is ready')[0];
const container = {innerHTML: ''};
const toolsCount = {textContent: ''};
global.document = {
  getElementById: id => id === 'toolsCount' ? toolsCount : container
};
let requestedUrl = null;
global.fetch = async (url) => {
  requestedUrl = url;
  return {
    json: async () => ({
      ok: true,
      tools: [],
      stats: {enabled: 63, local: 0, mcp: 0, blocked: 0}
    })
  };
};
eval(source + '\nglobal.JarvisApp = JarvisApp;');

(async () => {
  const app = Object.create(global.JarvisApp.prototype);
  Object.assign(app, {
    modeSelect: {value: 'cloud'},
    socket: {mode: 'cloud'},
    _toolsRequestId: 0,
    _setupToolHoverTooltips: () => {}
  });
  await app._loadToolsList('local');
  if (!requestedUrl || !requestedUrl.includes('mode=local')) {
    throw new Error(`Sidebar omitted selected mode: ${requestedUrl}`);
  }
  if (toolsCount.textContent !== '63 tools') {
    throw new Error(`Header retained stale startup count: ${toolsCount.textContent}`);
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
