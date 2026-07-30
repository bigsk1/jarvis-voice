"""Conversation and browser contracts for Web PDF attachments."""

from __future__ import annotations

import sys
from pathlib import Path

from server_package_utils import load_server_package


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
load_server_package("jarvis_web_pdf_chat_test", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_pdf_chat_test import config as web_config  # noqa: E402
from jarvis_web_pdf_chat_test.services import conversation_store  # noqa: E402
from jarvis_web_pdf_chat_test.sockets.chat import ChatHandler  # noqa: E402


ATTACHMENT = {
    "kind": "pdf",
    "stash_ref": "stash://space_web_pdf_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/f_bbbbbbbbbbbb",
    "space_id": "space_web_pdf_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "file_id": "f_bbbbbbbbbbbb",
    "filename": "docker-cheatsheet.pdf",
    "size_bytes": 49152,
    "mime_type": "application/pdf",
    "sha256": "c" * 64,
    "page_count": 3,
    "upload_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
}


def test_pdf_context_distinguishes_metadata_from_content_access():
    context = ChatHandler._format_pdf_attachment_context(ATTACHMENT)

    assert ATTACHMENT["stash_ref"] in context
    assert "docker-cheatsheet.pdf" in context
    assert "This metadata does not reveal the document contents" in context
    assert "use pdf_read or another appropriate local tool/workflow" in context
    assert "providers cannot access stash:// directly" in context
    assert "provider-native URL/file tool counts only if it actually receives" in context


def test_prior_user_pdf_reference_survives_into_later_turn_context(monkeypatch):
    conversation = {
        "messages": [
            {
                "role": "user",
                "content": "Keep this handy.",
                "timestamp": "2026-07-30T10:00:00",
                "data": {"attachments": [ATTACHMENT]},
            },
            {
                "role": "assistant",
                "content": "The PDF is attached, but I have not read it.",
                "timestamp": "2026-07-30T10:00:01",
                "data": {},
            },
            {
                # In-flight message is deliberately excluded by the context builder.
                "role": "user",
                "content": "Now inspect the PDF.",
                "timestamp": "2026-07-30T10:00:02",
                "data": None,
            },
        ]
    }

    class Store:
        def get_conversation(self, _conversation_id):
            return conversation

    monkeypatch.setattr(conversation_store, "get_conversation_store", lambda: Store())
    monkeypatch.setattr(web_config, "get_web_setting", lambda _key, default: default)

    history = ChatHandler.__new__(ChatHandler)._get_conversation_context("conversation")

    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"].startswith("[ATTACHED PDF ARTIFACT]")
    assert ATTACHMENT["stash_ref"] in history[0]["content"]
    assert "User's request: Keep this handy." in history[0]["content"]
    assert history[1]["content"] == "The PDF is attached, but I have not read it."


def test_untrusted_or_unbounded_stored_attachment_shape_is_not_prompted():
    stored = ChatHandler._stored_pdf_attachments

    assert stored(None) == []
    assert stored({"attachments": []}) == []
    assert stored({"attachments": [ATTACHMENT, ATTACHMENT]}) == []
    assert stored({"attachments": [{**ATTACHMENT, "kind": "other"}]}) == []
    assert stored({"attachments": [ATTACHMENT]}) == [ATTACHMENT]


def test_browser_pdf_contract_is_stash_only_and_retryable():
    index_html = (PROJECT_ROOT / "jarvis-web/client/index.html").read_text()
    chat_js = (PROJECT_ROOT / "jarvis-web/client/js/chat.js").read_text()
    app_js = (PROJECT_ROOT / "jarvis-web/client/js/app.js").read_text()
    socket_js = (PROJECT_ROOT / "jarvis-web/client/js/socket.js").read_text()

    assert ".pdf" in index_html
    assert "application/pdf" in index_html
    assert "async sendMessage()" in chat_js
    assert "fetch('/api/upload-pdf'" in chat_js
    assert "formData.append('upload_id', pdfState.uploadId)" in chat_js
    assert "pdfState.attachment = payload.attachment" in chat_js
    assert "this.attachedPdf !== pdfState" in chat_js
    assert "payload.attachments = attachments" in socket_js
    assert "msg.data?.attachments" in app_js
    assert "`📄 ${pdfAttachment.filename}" in app_js

    pdf_section = chat_js[
        chat_js.index("async _uploadAttachedPdf"):chat_js.index(
            "/**\n   * Attach an image file",
            chat_js.index("async _uploadAttachedPdf"),
        )
    ]
    assert "/api/stash/upload" not in pdf_section
    assert "/data/uploads" not in pdf_section
