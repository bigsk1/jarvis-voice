"""HeyGen video controls appear only with a selected-mode configured API key."""

import importlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from server_package_utils import load_server_package
from test_web_attachment_bundle_ui import run_browser

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings_runtime(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    monkeypatch.syspath_prepend(str(ROOT))
    namespace = "heygen_settings_test_server"
    load_server_package(namespace, ROOT / "jarvis-web/server")
    module = importlib.import_module(namespace + ".services.settings_manager")
    config = importlib.import_module("config_loader")
    values = {"LLM_PROVIDER": "openai", "XAI_AUTH_MODE": "api_key"}
    web = {"cloud": {"video_provider": "heygen", "video_models": {"heygen": "heygen-video-1"}}}
    def getter(key, default=None):
        return values.get(key, default)
    monkeypatch.setattr(module, "get_jarvis_setting", getter)
    monkeypatch.setattr(config, "get_config_value", getter)
    monkeypatch.setattr(module, "load_web_config", lambda: web)
    manager = module.SettingsManager.__new__(module.SettingsManager)
    manager.mode = "cloud"
    monkeypatch.setattr(manager, "_ensure_jarvis_config", lambda: None)
    monkeypatch.setattr(manager, "_get_provider_models", lambda: {})
    return SimpleNamespace(module=module, manager=manager, values=values, web=web, config=config)


@pytest.mark.parametrize("key", [None, "", " \t"])
@pytest.mark.parametrize("provider", ["heygen", "HEYGEN", " HeyGen "])
def test_missing_key_hides_metadata_and_cannot_restore_stale_provider(settings_runtime, key, provider):
    runtime = settings_runtime
    runtime.values.update(HEYGEN_API_KEY=key, VIDEO_TOOL_PROVIDER=provider)
    ui = runtime.manager.get_settings_for_ui()
    assert "heygen" not in ui["video_providers"]
    assert "heygen" not in ui["provider_availability"]["video"]
    assert "heygen" not in ui["video"]["provider"]["options"]
    assert ui["video"]["provider"]["value"] is None
    assert ui["video"]["provider"]["default"] is None
    assert ui["video"]["provider"]["selection_required"] is True
    assert not ui["video"]["provider"]["is_override"]
    assert not any(item["id"] == "heygen" for section in ui["api_keys"] for item in section["items"])
    with pytest.raises(runtime.module.SettingsValidationError):
        runtime.manager._validate_provider_overrides({"video_provider": "heygen"})


def test_configured_key_enables_model_metadata_and_override_without_exposing_key(settings_runtime):
    runtime = settings_runtime
    runtime.values.update(HEYGEN_API_KEY="SYNTHETIC_HEYGEN_SECRET", VIDEO_TOOL_PROVIDER=" HEYGEN ")
    ui = runtime.manager.get_settings_for_ui()
    assert ui["video"]["provider"]["value"] == "heygen" and ui["video"]["provider"]["is_override"]
    assert ui["video"]["provider"]["default"] == "heygen"
    assert ui["provider_availability"]["video"]["heygen"]["status"] == "available"
    provider = ui["video_providers"]["heygen"]
    assert provider["model"] == "heygen-video-1"
    assert provider["duration_seconds"] == {"min": 5, "max": 15}
    assert provider["resolutions"] == ["480p", "768p", "1080p", "2k"]
    assert provider["pricing"]["estimated"] is True
    assert provider["pricing"]["usd_by_resolution"]["768p"] == 0.018
    assert "SYNTHETIC_HEYGEN_SECRET" not in json.dumps(ui)
    runtime.manager._validate_provider_overrides({"video_provider": "heygen"})


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("source", ["saved_only", "env_only", "both"])
def test_key_removal_is_neutral_preserves_selection_and_restores_it(settings_runtime, mode, source):
    runtime = settings_runtime
    runtime.manager.mode = mode
    runtime.web.clear()
    runtime.web.update({mode: {"video_models": {"heygen": "heygen-video-1"}},
                        "local" if mode == "cloud" else "cloud": {"video_provider": "gemini"}})
    if source != "env_only":
        runtime.web[mode]["video_provider"] = "heygen"
    runtime.values.update(HEYGEN_API_KEY="configured-test-key", VIDEO_TOOL_PROVIDER="heygen" if source != "saved_only" else "xai")
    before = deepcopy(runtime.web)
    configured = runtime.manager.get_settings_for_ui()
    assert configured["video"]["provider"]["value"] == "heygen"
    assert configured["video"]["provider"].get("selection_required", False) is False

    runtime.values["HEYGEN_API_KEY"] = ""
    missing = runtime.manager.get_settings_for_ui()
    selection = missing["video"]["provider"]
    assert selection["value"] is None and selection["selection_required"] is True
    assert selection["default"] == ("xai" if source == "saved_only" else None)
    assert missing["video"]["model"]["value"] == ""
    assert "heygen" not in missing["video_providers"]
    assert "heygen" not in selection["options"]
    assert runtime.web == before

    runtime.values["HEYGEN_API_KEY"] = "restored-test-key"
    restored = runtime.manager.get_settings_for_ui()
    assert restored["video"]["provider"]["value"] == "heygen"
    assert restored["video"]["provider"].get("selection_required", False) is False
    assert restored["video"]["model"]["value"] == "heygen-video-1"
    assert runtime.web == before


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_explicit_available_replacement_can_be_saved_without_changing_env(settings_runtime, monkeypatch, mode):
    runtime = settings_runtime
    runtime.manager.mode = mode
    runtime.web[mode] = {"video_provider": "heygen", "video_models": {"heygen": "heygen-video-1"}}
    runtime.values.update(HEYGEN_API_KEY="", VIDEO_TOOL_PROVIDER="heygen", XAI_API_KEY="synthetic-xai-key")
    monkeypatch.setattr(runtime.module, "save_web_config", lambda config: config is runtime.web)
    assert runtime.manager.get_settings_for_ui()["video"]["provider"]["selection_required"] is True
    assert runtime.manager.save_web_overrides({"response_style": "auto"})
    assert runtime.web[mode]["video_provider"] == "heygen"
    assert runtime.web[mode]["video_models"]["heygen"] == "heygen-video-1"
    assert runtime.manager.save_web_overrides({"video_provider": "xai", "video_model": None})
    selection = runtime.manager.get_settings_for_ui()["video"]["provider"]
    assert selection["value"] == "xai" and selection.get("selection_required", False) is False
    assert selection["default"] is None and selection["is_override"] is True
    assert runtime.values["VIDEO_TOOL_PROVIDER"] == "heygen"
    runtime.values["HEYGEN_API_KEY"] = "restored-test-key"
    assert runtime.manager.get_settings_for_ui()["video"]["provider"]["value"] == "xai"


def test_catalog_options_gate_heygen_but_static_model_ownership_remains(settings_runtime):
    catalog = importlib.import_module("model_catalog")
    assert "heygen" in catalog.get_media_catalog_providers("video")
    assert "heygen" not in catalog.get_media_provider_options("video")
    with pytest.raises(ValueError, match="belongs to heygen"):
        catalog.validate_media_model_provider("video", "xai", "heygen-video-1")
    settings_runtime.values["HEYGEN_API_KEY"] = "synthetic-only"
    assert catalog.get_media_provider_options("video")["heygen"]["model"] == "heygen-video-1"


def test_background_admission_freezes_provider_and_model_without_credentials(settings_runtime):
    from lib.background_tasks.admission import _media_arguments_for_worker, media_job_overrides

    runtime = settings_runtime
    runtime.values.update(VIDEO_TOOL_PROVIDER="heygen", HEYGEN_API_KEY="SYNTHETIC_HEYGEN_SECRET")
    args = _media_arguments_for_worker("generate_video", {"prompt": "A clip"})
    assert args["provider"] == "heygen" and args["model"] == "heygen-video-1"
    assert media_job_overrides("generate_video", args) == {
        "VIDEO_TOOL_PROVIDER": "heygen", "HEYGEN_VIDEO_MODEL": "heygen-video-1",
    }
    assert "SYNTHETIC_HEYGEN_SECRET" not in json.dumps(args)
    runtime.values["HEYGEN_API_KEY"] = ""
    with pytest.raises(ValueError, match="HEYGEN_API_KEY"):
        _media_arguments_for_worker("generate_video", {"prompt": "A clip"})


def test_foreground_environment_declares_heygen_and_retains_existing_video_inputs(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    from tool_child_environment import parse_child_environment_policy, restrict_child_environment

    manifest = json.loads((ROOT / "skills/generate_video.tool.json").read_text())
    names = parse_child_environment_policy(manifest["child_environment"], manifest["availability"])
    assert names is not None
    assert {"XAI_API_KEY", "GEMINI_API_KEY", "HEYGEN_API_KEY", "HEYGEN_WAIT_SECONDS",
            "HEYGEN_VIDEO_MODEL", "VIDEO_TOOL_PROVIDER", "STASH_DIR", "OLLAMA_BASE_URL"} <= names
    environment = restrict_child_environment(
        {"HEYGEN_API_KEY": "selected-key", "UNRELATED_SECRET": "unrelated", "LOCAL_PROXY": "http://proxy.test"},
        names, home="/synthetic/scratch", proxy_policy="inherit",
    )
    assert environment["HEYGEN_API_KEY"] == "selected-key"
    assert environment["LOCAL_PROXY"] == "http://proxy.test"
    assert "UNRELATED_SECRET" not in environment


def test_modal_adds_and_removes_heygen_with_catalog_driven_limits():
    run_browser(r"""
class Choice {
  constructor(text, value) { this.textContent = text; this.value = value; this.dataset = {}; }
  remove() { this.parent.options = this.parent.options.filter(option => option !== this); }
}
class Select {
  constructor(value = '') { this.value = value; this.options = []; }
  add(option) { option.parent = this; this.options.push(option); }
  appendChild(option) { this.add(option); }
  replaceChildren() { this.options = []; }
  querySelector(selector) { return this.options.find(option => selector === 'option[value="' + option.value + '"]') || null; }
}
sandbox.Option = Choice;
const elements = {};
for (const id of ['imgActionVideoProvider', 'imgActionVideoModel', 'imgActionVideoResolution', 'imgActionVideoRatio',
                  'setting-video-provider', 'setting-video-model']) elements[id] = new Select();
elements.imgActionVideoProvider.add(new Choice('xAI', 'xai'));
elements.imgActionVideoProvider.add(new Choice('Gemini', 'gemini'));
elements.imgActionVideoDuration = {value:'5'};
elements.imgActionVideoDurationDesc = {};
elements.imgActionVideoModelDesc = {};
sandbox.document.getElementById = id => elements[id] || null;
const heygen = {name:'HeyGen', model:'heygen-video-1', models:[{
  id:'heygen-video-1', name:'HeyGen Video 1', resolutions:['480p','768p','1080p','2k'],
  aspect_ratios:['16:9','9:16','1:1','4:3','3:4','21:9'], duration_seconds:{min:5,max:15},
}]};
sandbox.window.jarvisApp = {_settingsData:{video:{provider:{value:'heygen'}}, video_providers:{xai:{name:'xAI'},gemini:{name:'Gemini'}}}};
const ui = chat(); ui._updateImageProviderOptions = () => {};
ui._resetImageActionOptions();
assert.equal(elements.imgActionVideoProvider.value, 'xai');
assert.ok(!elements.imgActionVideoProvider.options.some(option => option.value === 'heygen'));
sandbox.window.jarvisApp._settingsData.video_providers.heygen = heygen;
ui._resetImageActionOptions();
assert.equal(elements.imgActionVideoProvider.value, 'heygen');
assert.equal(elements.imgActionVideoModel.value, 'heygen-video-1');
assert.deepEqual(elements.imgActionVideoResolution.options.map(option => option.value), heygen.models[0].resolutions);
assert.deepEqual(elements.imgActionVideoRatio.options.map(option => option.value), heygen.models[0].aspect_ratios);
elements.imgActionVideoDuration.value = '99'; ui._updateVideoProviderOptions();
assert.equal(elements.imgActionVideoDuration.value, '15');
assert.equal(elements.imgActionVideoDuration.min, '5');
delete sandbox.window.jarvisApp._settingsData.video_providers.heygen;
ui._resetImageActionOptions();
assert.equal(elements.imgActionVideoProvider.value, 'xai');
assert.ok(!elements.imgActionVideoProvider.options.some(option => option.value === 'heygen'));
const app = Object.create(JarvisApp.prototype);
app._settingsData = {video_providers:{heygen}};
app._populateMediaProviderDropdown('video');
assert.ok(elements['setting-video-provider'].options.some(option => option.value === 'heygen'));
app._settingsData.video_providers = {};
app._populateMediaProviderDropdown('video');
assert.ok(!elements['setting-video-provider'].options.some(option => option.value === 'heygen'));
assert.match(app._formatMediaProviderPrice({unit:'second',estimated:true,usd_by_resolution:{'480p':0.01,'768p':0.018}}), /estimated.*0.01\/s/);
""")


def test_settings_form_requires_explicit_provider_and_preserves_unresolved_choice_on_save():
    run_browser(r"""
class Choice {
  constructor(text, value) { this.textContent = text; this.value = value; this.dataset = {}; }
}
class Select {
  constructor() { this.value = ''; this.options = []; }
  add(option) { this.options.push(option); }
  replaceChildren() { this.options = []; }
}
sandbox.Option = Choice;
const elements = {};
for (const id of ['setting-video-provider', 'setting-video-model']) elements[id] = new Select();
for (const id of ['video-provider-default', 'video-model-default', 'video-provider-capabilities']) elements[id] = {};
let mode = 'cloud';
sandbox.document.getElementById = id => elements[id] || {
  value: id === 'setting-mode' ? mode : id === 'setting-history-limit' ? '20' : '', checked: false,
};
const captured = [];
sandbox.fetch = async (url, options) => {
  assert.equal(url, '/api/settings/web');
  captured.push(JSON.parse(options.body));
  return {status:200,json:async()=>({ok:true})};
};
sandbox.Utils.storage.set = () => {};
const app = Object.create(JarvisApp.prototype);
Object.assign(app, {
  socket:{mode:'cloud'}, settingsModal:{classList:{remove(){}}},
  _loadSettings:async()=>{}, _updateAudioButton(){}, _applyGlowIntensity(){},
});
for (mode of ['cloud', 'local']) {
  app.socket.mode = mode;
  app._settingsData = {
    mode, video:{provider:{value:null,default:'xai',is_override:false,selection_required:true}},
    video_providers:{xai:{name:'xAI',model:'grok-imagine-video',model_default:'grok-imagine-video',
                        models:[{id:'grok-imagine-video',name:'Grok Imagine Video'}]}},
  };
  app._populateVideoProviderSettings(mode+'.env');
  const provider = elements['setting-video-provider'];
  const model = elements['setting-video-model'];
  assert.equal(provider.value, '');
  assert.equal(provider.options[0].textContent, 'Choose video provider');
  assert.equal(provider.options[0].disabled, true);
  assert.deepEqual(provider.options.map(option=>option.value), ['', 'xai']);
  assert.match(elements['video-provider-default'].textContent, /Choose a video provider/);
  assert.equal(model.disabled, true);
  assert.deepEqual(model.options.map(option=>option.value), ['']);
  assert.equal(elements['video-provider-capabilities'].textContent, '');
  await app._saveSettings();
  const unchanged = captured.at(-1);
  assert.equal(unchanged.mode, mode);
  assert.ok(!Object.hasOwn(unchanged, 'video_provider'));
  assert.ok(!Object.hasOwn(unchanged, 'video_model'));

  provider.value = 'xai';
  app._populateMediaModelDropdown('video');
  app._updateMediaProviderDetail('video');
  assert.equal(model.disabled, false);
  assert.ok(model.options.some(option=>option.value==='grok-imagine-video'));
  assert.match(elements['video-provider-capabilities'].textContent, /Grok Imagine Video/);
  await app._saveSettings();
  const changed = captured.at(-1);
  assert.equal(changed.mode, mode);
  assert.equal(changed.video_provider, 'xai');
  assert.equal(changed.video_model, null);
}
assert.ok(!notices.some(notice=>String(notice[0]).startsWith('Error:')));
""")


def test_key_removal_state_follows_actual_mode_scope_without_cross_mode_leak(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    load_server_package("heygen_scoped_settings_server", ROOT / "jarvis-web/server")
    module = importlib.import_module("heygen_scoped_settings_server.services.settings_manager")
    config = importlib.import_module("config_loader")
    configs = {
        "cloud": {"HEYGEN_API_KEY": "synthetic-cloud-key", "VIDEO_TOOL_PROVIDER": "heygen", "XAI_AUTH_MODE": "api_key"},
        "local": {"HEYGEN_API_KEY": "", "VIDEO_TOOL_PROVIDER": "heygen", "XAI_AUTH_MODE": "api_key"},
    }
    web = {mode: {"video_provider": "heygen"} for mode in configs}
    monkeypatch.setattr(config, "_load_mode_config", lambda mode: dict(configs[mode]))
    monkeypatch.setattr(module, "get_jarvis_setting", config.get_config_value)
    monkeypatch.setattr(module, "load_web_config", lambda: web)
    monkeypatch.setattr(module.SettingsManager, "_ensure_jarvis_config", lambda _: None)
    monkeypatch.setattr(module.SettingsManager, "_get_provider_models", lambda _: {})

    def selection(mode):
        with config.config_scope(mode):
            ui = module.SettingsManager(mode).get_settings_for_ui()
            assert ("heygen" in ui["video_providers"]) == bool(configs[mode]["HEYGEN_API_KEY"])
            return ui["video"]["provider"]

    assert selection("cloud")["value"] == "heygen"
    assert selection("local")["selection_required"] is True
    configs["cloud"]["HEYGEN_API_KEY"] = ""
    configs["local"]["HEYGEN_API_KEY"] = "synthetic-restored-local-key"
    assert selection("local")["value"] == "heygen"
    assert selection("cloud")["selection_required"] is True
    assert web == {mode: {"video_provider": "heygen"} for mode in configs}
