"""Conversation export/import regressions for structured workflow results."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from flask import Flask

from server_package_utils import load_server_package


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
load_server_package(
    "jarvis_web_workflow_roundtrip_test_server",
    PROJECT_ROOT / "jarvis-web" / "server",
)

from jarvis_web_workflow_roundtrip_test_server.routes import api  # noqa: E402
from jarvis_web_workflow_roundtrip_test_server.services import conversation_store  # noqa: E402
from jarvis_web_workflow_roundtrip_test_server.services.conversation_store import (  # noqa: E402
    ConversationStore,
)


def _make_client(tmp_path: Path, monkeypatch):
    store = ConversationStore(tmp_path / "conversations")
    monkeypatch.setattr(conversation_store, "_store", store)
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client(), store


def test_json_export_import_preserves_complete_workflow_rendering_data(
    tmp_path,
    monkeypatch,
):
    client, store = _make_client(tmp_path, monkeypatch)
    conversation = store.create_conversation("Movie Night")
    store.add_message(
        conversation["id"],
        "user",
        "/movie_night thoughtful science fiction like Arrival",
    )
    store.update_title(conversation["id"], "Movie Night")

    workflow_data = {
        "workflow_id": "movie_night",
        "workflow_name": "Movie Night",
        "results": [
            {
                "step": 1,
                "tool": "trakt_movies",
                "ok": True,
                "data": {
                    "action": "recommend",
                    "results": [{"title": "Project Hail Mary", "year": 2026}],
                },
            },
            {
                "step": 2,
                "tool": "tmdb_movies",
                "ok": True,
                "data": {
                    "action": "images",
                    "results": [
                        {
                            "title": "Project Hail Mary poster",
                            "image_url": "https://image.tmdb.org/poster.jpg",
                        }
                    ],
                },
            },
            {
                "step": 3,
                "tool": "serpapi_youtube_search",
                "ok": True,
                "data": {
                    "results": [
                        {
                            "title": "Project Hail Mary Official Trailer",
                            "video_id": "abc123def45",
                        }
                    ]
                },
            },
        ],
        "trakt_movies": {
            "action": "recommend",
            "results": [{"title": "Project Hail Mary", "year": 2026}],
        },
        "tmdb_movies": {
            "action": "images",
            "results": [
                {
                    "title": "Project Hail Mary poster",
                    "image_url": "https://image.tmdb.org/poster.jpg",
                }
            ],
        },
        "serpapi_youtube_search": {
            "results": [
                {
                    "title": "Project Hail Mary Official Trailer",
                    "video_id": "abc123def45",
                }
            ]
        },
        "canvas": {
            "action": "create",
            "page_id": "movie-night-project-hail-mary",
            "title": "Workflows/Movie Night/Project Hail Mary",
            "url": "http://localhost:8890/movie-night-project-hail-mary",
        },
        "speech": "Your movie-night shortlist is ready in Canvas.",
    }
    tools_used = [
        "trakt_movies",
        "tmdb_movies",
        "serpapi_youtube_search",
        "canvas",
    ]
    source_message = store.add_message(
        conversation["id"],
        "assistant",
        "Your movie-night shortlist is ready in Canvas.",
        data=workflow_data,
        tools_used=tools_used,
    )

    exported_response = client.get(
        f"/api/conversations/{conversation['id']}/export?format=json"
    )
    assert exported_response.status_code == 200
    exported = json.loads(exported_response.data)
    exported_assistant = exported["messages"][-1]
    assert exported_assistant["data"] == workflow_data
    assert exported_assistant["tools_used"] == tools_used

    imported_response = client.post(
        "/api/conversations/import",
        data={
            "file": (
                io.BytesIO(exported_response.data),
                "movie-night.json",
            )
        },
        content_type="multipart/form-data",
    )
    assert imported_response.status_code == 200
    imported = imported_response.get_json()["conversation"]
    imported_assistant = imported["messages"][-1]

    assert imported["id"] != conversation["id"]
    assert imported_assistant["id"] != source_message["id"]
    assert imported_assistant["data"] == workflow_data
    assert imported_assistant["tools_used"] == tools_used
    assert imported_assistant["data"]["results"][2]["tool"] == "serpapi_youtube_search"
    assert imported_assistant["data"]["canvas"]["action"] == "create"
