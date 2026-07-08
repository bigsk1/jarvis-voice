"""Web conversation rename and title-search regressions."""

from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask

from server_package_utils import load_server_package


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
load_server_package("jarvis_web_test_server", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.routes import api  # noqa: E402
from jarvis_web_test_server.services import conversation_store  # noqa: E402
from jarvis_web_test_server.services.conversation_store import ConversationStore  # noqa: E402


def _make_client(tmp_path: Path, monkeypatch):
    store = ConversationStore(tmp_path / "conversations")
    monkeypatch.setattr(conversation_store, "_store", store)
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client(), store


def test_rename_accepts_symbols_and_normalizes_whitespace(tmp_path, monkeypatch):
    client, store = _make_client(tmp_path, monkeypatch)
    conversation = store.create_conversation("Original")
    store.add_message(conversation["id"], "user", "Initial message")

    response = client.put(
        f"/api/conversations/{conversation['id']}/title",
        json={"title": "  !@#z$A12   project  "},
    )

    assert response.status_code == 200
    assert store.get_conversation(conversation["id"])["title"] == "!@#z$A12 project"


def test_rename_rejects_blank_non_string_and_overlong_titles(tmp_path, monkeypatch):
    client, store = _make_client(tmp_path, monkeypatch)
    conversation = store.create_conversation("Original")
    store.add_message(conversation["id"], "user", "Initial message")
    store.update_title(conversation["id"], "Original")
    url = f"/api/conversations/{conversation['id']}/title"

    for title in ("   \n\t", 42, "x" * 201):
        response = client.put(url, json={"title": title})
        assert response.status_code == 400

    assert store.get_conversation(conversation["id"])["title"] == "Original"


def test_rename_rejects_conversation_without_messages(tmp_path, monkeypatch):
    client, store = _make_client(tmp_path, monkeypatch)
    conversation = store.create_conversation("Temporary title")

    response = client.put(
        f"/api/conversations/{conversation['id']}/title",
        json={"title": "Manual title"},
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "Add a message before renaming this conversation"
    assert store.get_conversation(conversation["id"])["title"] == "Temporary title"


def test_deep_search_finds_saved_conversation_title(tmp_path, monkeypatch):
    client, store = _make_client(tmp_path, monkeypatch)
    conversation = store.create_conversation()
    store.add_message(conversation["id"], "user", "Message without the lookup term")
    store.update_title(conversation["id"], "Pinned Saturn Research")

    response = client.get("/api/conversations/search?q=saturn")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["total_conversations"] == 1
    assert payload["results"][0]["title"] == "Pinned Saturn Research"
    assert payload["results"][0]["matches"] == [
        {
            "message_id": None,
            "role": "title",
            "snippet": "Pinned Saturn Research",
            "timestamp": store.get_conversation(conversation["id"])["updated_at"],
        }
    ]
