"""Contract tests for the Canvas gallery handoff to Jarvis Web."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANVAS_JS = (PROJECT_ROOT / "jarvis-canvas/client/static/js/gallery.js").read_text()
CANVAS_HTML = (PROJECT_ROOT / "jarvis-canvas/client/templates/gallery.html").read_text()
CANVAS_ROUTES = (PROJECT_ROOT / "jarvis-canvas/server/routes/gallery.py").read_text()
WEB_APP_JS = (PROJECT_ROOT / "jarvis-web/client/js/app.js").read_text()
WEB_CHAT_JS = (PROJECT_ROOT / "jarvis-web/client/js/chat.js").read_text()


def test_canvas_sends_gallery_image_to_web_without_direct_generation_or_cdn_upload():
    assert "buildJarvisWebMediaHandoffUrl" in CANVAS_JS
    assert "media_handoff" in CANVAS_JS
    assert "media_filename" in CANVAS_JS
    assert "media_action" in CANVAS_JS
    assert "window.open" in CANVAS_JS
    assert "'_blank'" in CANVAS_JS
    assert "sendImageToJarvisWebByIndex" in CANVAS_JS
    assert "sendCurrentImageToJarvisWeb" in CANVAS_JS
    assert "Send to Jarvis" in CANVAS_HTML
    assert "videoModal" not in CANVAS_HTML
    assert "/to-video" not in CANVAS_JS
    assert "convert_image_to_video" not in CANVAS_ROUTES


def test_web_handoff_explicitly_starts_new_chat_before_importing_attachment():
    start = WEB_APP_JS.index("async _consumeMediaHandoff()")
    end = WEB_APP_JS.index("\n  /**", start)
    handoff = WEB_APP_JS[start:end]

    new_chat = handoff.index("this._startNewChat();")
    imported = handoff.index("/api/media-handoff/import")
    attached = handoff.index("attachImportedImage")
    assert new_chat < imported < attached
    assert "history.replaceState" in handoff
    assert "this._mediaHandoffStarted" in WEB_APP_JS


def test_web_uses_normal_image_action_modal_with_video_preselected():
    assert "attachImportedImage(uploadData, preferredAction = 'analyze')" in WEB_CHAT_JS
    assert "_showImageActionModal(uploadData, preferredAction)" in WEB_CHAT_JS
    assert "const allowedActions = new Set(['analyze', 'video', 'image'])" in WEB_CHAT_JS
