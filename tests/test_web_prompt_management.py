"""Jarvis Web prompt-management API and persistence regressions."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from flask import Flask
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
load_server_package("jarvis_web_prompt_management", ROOT / "jarvis-web" / "server")

from jarvis_web_prompt_management.routes import api  # noqa: E402
from jarvis_web_prompt_management.services import prompt_library  # noqa: E402


class _ToolService:
    def __init__(self, tools=None):
        self.tools = list(tools or [])

    def get_tools(self, include_blocked=True):
        return list(self.tools)


def _client(monkeypatch, prompts_dir: Path, tools=None):
    monkeypatch.setattr(api, "PROMPTS_PATH", prompts_dir)
    monkeypatch.setattr(api, "get_tool_service", lambda *_args, **_kwargs: _ToolService(tools))
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client()


@pytest.mark.parametrize(
    "name",
    [
        "", " quick", "With Space", "has-hyphen", "has.dot", "has/slash", "..",
        "double__underscore", "UPPER", "README", "manage", "personal",
        "a" * 65,
    ],
)
def test_prompt_names_are_rejected_deterministically(name):
    with pytest.raises(prompt_library.PromptLibraryError):
        prompt_library.validate_prompt_name(name)


@pytest.mark.parametrize("name", ["quick", "social_clip", "2v_voices_only"])
def test_existing_prompt_name_shapes_remain_valid(name):
    assert prompt_library.validate_prompt_name(name) == name


@pytest.mark.parametrize(
    "content, message",
    [
        ("---\ntool_hints: [search, search]\n---\n# Test\n", "Duplicate"),
        ("---\ntool_hints: [a, b, c, d, e, f]\n---\n# Test\n", "at most 5"),
        ("---\ntool_hints: search\n---\n# Test\n", "must be a list"),
        ("---\ntool_hints: [search]\n# Test\n", "closing"),
        ("   ", "cannot be empty"),
    ],
)
def test_authoring_validation_rejects_ambiguous_drafts(content, message):
    with pytest.raises(prompt_library.PromptLibraryError, match=message):
        prompt_library.validate_prompt_draft("test", content)


def test_management_uses_runtime_visibility_and_send_hint_predicates_separately(
    tmp_path, monkeypatch
):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "probe.md").write_text(
        "---\ntool_hints:\n  - configured_but_unavailable\n---\n# Probe\n",
        encoding="utf-8",
    )
    tools = [{
        "name": "configured_but_unavailable",
        "enabled": True,
        "available": False,
        "blocked": False,
        "missing": ["PROBE_API_KEY"],
    }]
    client = _client(monkeypatch, prompts, tools)

    record = client.get("/api/prompts/manage?mode=cloud").get_json()["prompts"][0]

    assert record["runtime_visible"] is False
    assert record["availability_status"] == "not_in_menu"
    assert record["active_tool_hints"] == ["configured_but_unavailable"]
    assert record["inactive_tool_hints"] == []
    assert "missing configuration" in record["unavailable_reason"]


def test_multi_hint_management_statuses_preserve_existing_group_visibility(
    tmp_path, monkeypatch
):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "reduced.md").write_text(
        "---\ntool_hints: [active_tool, missing_tool]\n---\n# Reduced\n"
    )
    (prompts / "none.md").write_text(
        "---\ntool_hints: [missing_one, missing_two]\n---\n# None\n"
    )
    client = _client(
        monkeypatch,
        prompts,
        [{"name": "active_tool", "enabled": True, "blocked": False}],
    )

    records = {
        item["name"]: item
        for item in client.get("/api/prompts/manage?mode=cloud").get_json()["prompts"]
    }

    assert records["reduced"]["runtime_visible"] is True
    assert records["reduced"]["availability_status"] == "available_with_reduced_hints"
    assert records["reduced"]["active_tool_hints"] == ["active_tool"]
    assert records["none"]["runtime_visible"] is True
    assert records["none"]["availability_status"] == "available_without_active_hints"


def test_management_lists_malformed_prompt_with_raw_content(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    raw = "---\ntool_hints: [broken\n---\n# Repair me\n"
    (prompts / "broken.md").write_text(raw, encoding="utf-8")
    client = _client(monkeypatch, prompts)

    response = client.get("/api/prompts/manage?mode=local")
    record = response.get_json()["prompts"][0]

    assert response.status_code == 200
    assert record["availability_status"] == "needs_repair"
    assert record["runtime_visible"] is False
    assert record["content"] == raw
    assert "YAML" in record["parse_error"]
    assert "/tmp" not in response.get_data(as_text=True)


def test_management_reports_invalid_utf8_without_exposing_a_path(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "broken_bytes.md").write_bytes(b"# Broken\n\xff")
    client = _client(monkeypatch, prompts)

    payload = client.get("/api/prompts/manage?mode=cloud").get_json()
    record = payload["prompts"][0]

    assert record["content"] == ""
    assert record["parse_error"] == "Prompt file is not valid UTF-8 text"
    assert str(tmp_path) not in str(payload)


def test_create_override_update_and_delete_restores_builtin(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "quick.md").write_text("# Built-in\n", encoding="utf-8")
    client = _client(monkeypatch, prompts)

    collision = client.post("/api/prompts/personal?mode=cloud", json={
        "name": "quick", "content": "# Personal\n", "override_shared": False,
    })
    assert collision.status_code == 409

    created = client.post("/api/prompts/personal?mode=cloud", json={
        "name": "quick", "content": "# Personal\n", "override_shared": True,
    })
    assert created.status_code == 201
    assert created.get_json()["prompt"]["overrides_shared"] is True
    assert (prompts / "personal" / "quick.md").read_text() == "# Personal\n"

    duplicate = client.post("/api/prompts/personal?mode=cloud", json={
        "name": "quick", "content": "# Again\n", "override_shared": True,
    })
    assert duplicate.status_code == 409

    updated = client.put("/api/prompts/personal/quick?mode=cloud", json={
        "content": "# Updated\n",
    })
    assert updated.status_code == 200
    assert (prompts / "personal" / "quick.md").read_text() == "# Updated\n"

    deleted = client.delete("/api/prompts/personal/quick?mode=cloud")
    assert deleted.status_code == 200
    assert deleted.get_json()["restored_builtin"] is True
    assert api._resolve_prompt_file("quick") == prompts / "quick.md"


def test_shared_only_prompt_cannot_be_updated_or_deleted(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    built_in = prompts / "quick.md"
    built_in.write_text("# Built-in\n", encoding="utf-8")
    client = _client(monkeypatch, prompts)

    updated = client.put(
        "/api/prompts/personal/quick?mode=cloud", json={"content": "# Changed\n"}
    )
    deleted = client.delete("/api/prompts/personal/quick?mode=cloud")

    assert updated.status_code == 404
    assert deleted.status_code == 404
    assert built_in.read_text() == "# Built-in\n"


def test_unknown_tool_hint_saves_with_warning(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    client = _client(monkeypatch, prompts)

    response = client.post(
        "/api/prompts/personal?mode=local",
        json={
            "name": "future_tool",
            "content": (
                "---\ntool_hints:\n  - not_installed_here\n---\n\n# Future Tool\n"
            ),
            "override_shared": False,
        },
    )

    assert response.status_code == 201
    assert response.get_json()["warnings"][0]["code"] == "unknown_tool_hint"


def test_personal_prompt_write_is_private_and_atomic(tmp_path):
    prompts = tmp_path / "prompts"
    prompt_library.write_personal_prompt(
        prompts, "private_note", "# Private\n", must_exist=False
    )
    destination = prompts / "personal" / "private_note.md"

    assert destination.read_text() == "# Private\n"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert list(destination.parent.glob("*.tmp")) == []


def test_interrupted_atomic_write_keeps_previous_prompt(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompt_library.write_personal_prompt(
        prompts, "stable", "# Previous\n", must_exist=False
    )
    destination = prompts / "personal" / "stable.md"

    def fail_replace(_source, _destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(prompt_library.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        prompt_library.write_personal_prompt(
            prompts, "stable", "# Incomplete\n", must_exist=True
        )

    assert destination.read_text() == "# Previous\n"
    assert list(destination.parent.glob("*.tmp")) == []


def test_symlinked_personal_destination_is_refused(tmp_path):
    prompts = tmp_path / "prompts"
    personal = prompts / "personal"
    personal.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n")
    (personal / "escape.md").symlink_to(outside)

    with pytest.raises(prompt_library.PromptLibraryError, match="symlinked"):
        prompt_library.write_personal_prompt(
            prompts, "escape", "# Changed\n", must_exist=True
        )
    assert outside.read_text() == "# Outside\n"


def test_management_does_not_follow_prompt_symlinks_outside_library(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    outside = tmp_path / "private.md"
    outside.write_text("# Must not leak\nsecret-value\n")
    (prompts / "linked.md").symlink_to(outside)
    client = _client(monkeypatch, prompts)

    response = client.get("/api/prompts/manage?mode=cloud")

    assert response.status_code == 200
    assert response.get_json()["prompts"] == []
    assert "secret-value" not in response.get_data(as_text=True)


def test_docker_mounts_only_the_personal_prompt_directory_read_write():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    volumes = compose["services"]["jarvis-web"]["volumes"]
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()

    assert (
        "./jarvis-web/data/prompts/personal:"
        "/app/jarvis-web/data/prompts/personal"
    ) in volumes
    assert not any(
        isinstance(volume, str)
        and volume.startswith("./jarvis-web/data/prompts:")
        for volume in volumes
    )
    assert "jarvis-web/data/prompts/personal/" in dockerignore
