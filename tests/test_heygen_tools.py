"""HeyGen tool and REST contracts without provider requests or paid submissions."""

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = {"script": "Welcome to the demonstration.", "avatar_id": "ready_look_7", "voice_id": "voice_7"}
RECEIPT = {"provider": "heygen", "kind": "avatar", "status": "pending",
           "provider_video_id": "video_7", "receipt_stash_ref": "stash://receipts/avatar_7"}


@pytest.fixture
def tools(monkeypatch):
    # The production entry points adjust sys.path when loaded as standalone scripts.
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    avatar = importlib.import_module("skills.generate_avatar_video")
    catalog = importlib.import_module("skills.heygen")
    core = importlib.import_module("heygen_client")
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(core, "HeyGenClient", factory)
    for module in (avatar, catalog):
        monkeypatch.setattr(module, "load_config", lambda: None)
        monkeypatch.setattr(module, "get_config_value", lambda key, default="": "test-key" if key == "HEYGEN_API_KEY" else default)
    # Even accidental calls through the real core must never reach the network.
    monkeypatch.setattr(core, "http_request", Mock(side_effect=AssertionError("Unexpected provider request")))
    return avatar, catalog, core, client, factory


@pytest.mark.parametrize("which,arguments", [(0, SCRIPT), (1, {"action": "account"})])
def test_key_absent_fails_before_client_construction(tools, monkeypatch, which, arguments):
    module = tools[which]
    monkeypatch.setattr(module, "get_config_value", lambda *_: "")
    result = module.run(arguments)
    assert result["ok"] is False
    assert result["completion"] == "rejected"
    assert "HEYGEN_API_KEY" in result["error"]
    tools[4].assert_not_called()


@pytest.mark.parametrize("arguments", [
    {}, {**SCRIPT, "audio_source": "stash://audio/input"},
    {**SCRIPT, "image_source": "stash://images/input"},
    {"script": "hello", "avatar_id": "look"},
    {"audio_source": "stash://audio/input", "avatar_id": "look", "voice_id": "voice"},
    {**SCRIPT, "script": "word " * 76}, {**SCRIPT, "script": "x" * 1001},
    {**SCRIPT, "title": "x" * 201}, {**SCRIPT, "resolution": "4k"},
    {**SCRIPT, "aspect_ratio": "4:3"}, {**SCRIPT, "engine": "avatar_v"},
    {**SCRIPT, "voice_id": 7}, {**SCRIPT, "script": "   "}, [],
])
def test_avatar_invalid_scalars_and_alternatives_do_not_construct_client(tools, arguments):
    result = tools[0].run(arguments)
    assert result["ok"] is False
    assert result["completion"] == "rejected"
    tools[4].assert_not_called()


def test_avatar_exact_script_and_saved_artifact_envelope(tools, monkeypatch):
    avatar, _, core, client, _ = tools
    script = "  Hello,\nworld!  "
    normalized = {**RECEIPT, "status": "completed", "video_url": "https://media.example.test/video.mp4"}
    completed = {"ok": True, "speech": "Saved video.", "data": {**normalized, "stash_ref": "stash://videos/output"}}
    client.generate_avatar.return_value = normalized
    save = Mock(return_value=completed)
    monkeypatch.setattr(core, "save_result", save)
    assert avatar.run({**SCRIPT, "script": script}) is completed
    client.generate_avatar.assert_called_once_with(**{**SCRIPT, "script": script})
    save.assert_called_once_with(normalized, prompt=script)
    client.submit_avatar.assert_not_called()


def test_existing_audio_and_image_pass_to_shared_validation_without_voice(tools, monkeypatch):
    avatar, _, core, client, _ = tools
    arguments = {"audio_source": "stash://audio/existing", "image_source": "https://example.test/portrait.png",
                 "aspect_ratio": "auto", "resolution": "1080p", "title": "Existing audio"}
    monkeypatch.setattr(core, "save_result", Mock(return_value={"ok": True}))
    assert avatar.run(arguments)["ok"] is True
    client.generate_avatar.assert_called_once_with(**arguments)


def test_submit_only_returns_recovery_receipt_without_wait_or_save(tools, monkeypatch):
    avatar, _, core, client, _ = tools
    client.submit_avatar.return_value = dict(RECEIPT)
    save = Mock(side_effect=AssertionError("Submission is not completed output"))
    monkeypatch.setattr(core, "save_result", save)
    result = avatar.run(SCRIPT, submit_only=True)
    assert result["ok"] is True
    assert result["data"] == {**RECEIPT, "submission_only": True}
    client.submit_avatar.assert_called_once_with(**SCRIPT)
    client.generate_avatar.assert_not_called()
    client.wait_for_video.assert_not_called()
    save.assert_not_called()


@pytest.mark.parametrize("which,arguments,method", [
    (0, SCRIPT, "generate_avatar"), (1, {"action": "status", "video_id": "video_7", "kind": "avatar"}, "status"),
])
def test_unknown_failure_preserves_job_evidence_without_resubmission(tools, which, arguments, method):
    _, _, core, client, factory = tools
    getattr(client, method).side_effect = core.HeyGenError("Still processing; collect this job", dict(RECEIPT))
    result = tools[which].run(arguments)
    assert result["ok"] is False
    assert result["completion"] == "unknown"
    assert result["data"] == RECEIPT
    factory.assert_called_once()
    assert len(client.mock_calls) == 1


def test_unexpected_exception_does_not_expose_credentials(tools):
    tools[3].account.side_effect = RuntimeError("https://secret-user:SECRET_KEY@example.test")
    result = tools[1].run({"action": "account"})
    assert result["ok"] is False
    assert "SECRET_KEY" not in json.dumps(result)


@pytest.mark.parametrize("action,extra,method,expected_args,expected_kwargs", [
    ("account", {}, "account", (), {}),
    ("list_avatars", {"limit": 2, "cursor": "opaque+/= token"}, "list_avatars", (), {"limit": 2, "cursor": "opaque+/= token"}),
    ("list_voices", {}, "list_voices", (), {"limit": 20, "cursor": None}),
    ("status", {"video_id": "video_7", "kind": "avatar"}, "status", ("video_7",), {"kind": "avatar"}),
])
def test_catalog_status_exact_contract_does_not_generate(tools, action, extra, method, expected_args, expected_kwargs):
    client = tools[3]
    getattr(client, method).return_value = {"items": [{"id": "look_7"}], "next_cursor": "next-page"}
    result = tools[1].run({"action": action, **extra})
    assert result["ok"] is True
    assert result["data"]["action"] == action
    assert result["data"]["next_cursor"] == "next-page"
    getattr(client, method).assert_called_once_with(*expected_args, **expected_kwargs)
    assert len(client.mock_calls) == 1


@pytest.mark.parametrize("payload", [
    {"ok": True, "speech": "Still processing", "data": RECEIPT},
    {"ok": True, "speech": "Saved", "data": {**RECEIPT, "status": "completed", "stash_ref": "stash://videos/saved"}},
    {"ok": False, "completion": "completed", "speech": "Failed", "data": {**RECEIPT, "status": "failed"}},
])
def test_collect_observes_same_job_and_preserves_completion(tools, payload):
    client = tools[3]
    client.collect.return_value = json.loads(json.dumps(payload))
    result = tools[1].run({"action": "collect", "video_id": "video_7", "kind": "avatar"})
    assert result == {**payload, "data": {**payload["data"], "action": "collect", "kind": "avatar"}}
    client.collect.assert_called_once_with("video_7", kind="avatar")
    assert len(client.mock_calls) == 1


@pytest.mark.parametrize("arguments", [
    {"action": "create"}, {"action": "account", "limit": 1},
    {"action": "list_avatars", "limit": True}, {"action": "list_voices", "limit": 51},
    {"action": "list_avatars", "cursor": "x" * 501}, {"action": "list_voices", "cursor": " "},
    {"action": "status", "video_id": "https://example.test/id"},
    {"action": "collect", "video_id": "video_7", "kind": "agent"},
])
def test_catalog_rejects_invalid_or_truncated_arguments_before_client(tools, arguments):
    assert tools[1].run(arguments)["completion"] == "rejected"
    tools[4].assert_not_called()


@pytest.fixture
def api_client(tools):
    spec = importlib.util.spec_from_file_location("heygen_routes_test", ROOT / "api/routes/heygen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as client:
        yield client


def test_api_avatar_returns_202_without_polling_and_preserves_selected_mode(tools, api_client, monkeypatch):
    from config_loader import get_active_config_mode

    modes = []
    tools[4].side_effect = lambda: modes.append(get_active_config_mode()) or tools[3]
    tools[3].submit_avatar.return_value = dict(RECEIPT)
    response = api_client.post("/api/heygen/avatar", json={**SCRIPT, "mode": "local"})
    assert response.status_code == 202
    assert response.json()["data"]["provider_video_id"] == "video_7"
    assert response.json()["data"]["submission_only"] is True
    assert modes == ["local"]
    tools[3].submit_avatar.assert_called_once_with(**SCRIPT, title="", aspect_ratio="16:9", resolution="720p")
    tools[3].generate_avatar.assert_not_called()
    tools[3].wait_for_video.assert_not_called()


@pytest.mark.parametrize("method,path,body,client_method,expected_args,expected_kwargs", [
    ("get", "/api/heygen/account?mode=local", None, "account", (), {}),
    ("get", "/api/heygen/avatars?limit=2&cursor=page2", None, "list_avatars", (), {"limit": 2, "cursor": "page2"}),
    ("get", "/api/heygen/voices", None, "list_voices", (), {"limit": 20, "cursor": None}),
    ("get", "/api/heygen/status/video_7?kind=avatar", None, "status", ("video_7",), {"kind": "avatar"}),
    ("post", "/api/heygen/collect", {"video_id": "video_7", "kind": "avatar"}, "collect", ("video_7",), {"kind": "avatar"}),
])
def test_api_catalog_and_recovery_use_existing_id_only(tools, api_client, method, path, body, client_method, expected_args, expected_kwargs):
    getattr(tools[3], client_method).return_value = {"ok": True, "data": dict(RECEIPT)} if client_method == "collect" else dict(RECEIPT)
    response = api_client.request(method, path, json=body)
    assert response.status_code == 200
    assert response.json()["ok"] is True
    getattr(tools[3], client_method).assert_called_once_with(*expected_args, **expected_kwargs)
    assert len(tools[3].mock_calls) == 1


@pytest.mark.parametrize("body", [{**SCRIPT, "engine": "avatar_v"}, {**SCRIPT, "mode": "other"}, {**SCRIPT, "resolution": "4k"}])
def test_api_schema_refuses_unsupported_generation_before_client(tools, api_client, body):
    assert api_client.post("/api/heygen/avatar", json=body).status_code == 422
    tools[4].assert_not_called()


def test_api_missing_key_never_submits(tools, api_client, monkeypatch):
    monkeypatch.setattr(tools[0], "get_config_value", lambda *_: "")
    result = api_client.post("/api/heygen/avatar", json=SCRIPT)
    assert result.json()["completion"] == "rejected"
    tools[4].assert_not_called()


@pytest.mark.parametrize("which", [0, 1])
def test_cli_invalid_json_returns_one_error_object(tools, monkeypatch, capsys, which):
    monkeypatch.setattr(sys, "argv", ["tool.py", "{"])
    assert tools[which].main() == 1
    output = json.loads(capsys.readouterr().out)
    assert output["completion"] == "rejected"
    tools[4].assert_not_called()


@pytest.mark.parametrize("name", ["heygen", "generate_avatar_video"])
def test_manifest_key_only_gate_and_reviewed_child_environment(tools, name):
    from tool_schema import ToolSchema

    path = ROOT / "skills" / f"{name}.tool.json"
    manifest = json.loads(path.read_text())
    parsed = ToolSchema.from_json_file(str(path))
    assert parsed.name == name
    assert manifest["availability"]["all_of_env"] == ["HEYGEN_API_KEY"]
    assert set(manifest["availability"]) == {"all_of_env", "setup_hint"}
    policy = manifest["child_environment"]
    assert policy["mode"] == "restricted" and policy["from_availability"] is True
    assert {"HEYGEN_WAIT_SECONDS", "STASH_DIR", "STASH_GENERATED_MEDIA_TTL_DAYS"} <= set(policy["allow"])
    assert not any("KEY" in setting for setting in policy["allow"])
    assert (ROOT / "skills" / manifest["script"]).stat().st_mode & 0o111
    if name == "generate_avatar_video":
        background = manifest["execution"]["background"]
        assert background["adapter"] == "remote_skill_v1"
        assert background["timeout_seconds"] == 1200
