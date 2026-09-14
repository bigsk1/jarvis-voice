"""Parse production preview HTML to verify imported values stay inert data."""

import json
import subprocess
from html.parser import HTMLParser

import pytest
from test_web_assistant_message_rendering import HARNESS, ROOT


class PreviewHTML(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def render_previews(payloads):
    script = f"const ROOT = {json.dumps(str(ROOT))};\n" + HARNESS
    script += f"\nconst payloads = {json.dumps(payloads)};\n"
    script += "console.log('PREVIEWS:' + JSON.stringify(payloads.map(value => sandbox.window.assistantMessageRenderer.renderConvertedFile(value))));"
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(next(line.removeprefix("PREVIEWS:") for line in result.stdout.splitlines() if line.startswith("PREVIEWS:")))


def assert_inert(preview):
    assert preview.elements
    assert all(tag in {"a", "div", "span", "img", "audio", "video", "source"} for tag, _ in preview.elements)
    assert all(not name.lower().startswith("on") for _, attrs in preview.elements for name in attrs)


@pytest.mark.parametrize("target", ["png", "mp4", "ogg", "pdf"])
def test_quoted_filename_and_size_text_cannot_add_html_or_event_attributes(target):
    filename = 'report" onmouseover="window.__injected=1" data-name="<img src=x> & \'quoted\'.' + target
    size = '<svg onload="window.__injected=2"> & 10%'
    html, = render_previews([{
        "stash_ref": "stash://space_test/f_preview", "filename": filename,
        "target_format": target, "size_change": size,
    }])
    preview = PreviewHTML(html)
    assert_inert(preview)
    link = next(attrs for tag, attrs in preview.elements if tag == "a")
    assert link["download"] == filename
    assert link["href"] == "/api/stash/space_test/f_preview"
    if "title" in link:
        assert link["title"] == "Download " + filename
    assert size in "".join(preview.text)
    assert filename in "".join(preview.text)


def test_imported_format_cannot_add_markup_and_wrong_types_do_not_abort_rendering():
    dangerous_format = '\"><svg onload="window.__injected=3">'
    html, malformed, = render_previews([
        {"stash_ref": "stash://space_test/f_preview", "target_format": dangerous_format, "filename": "result"},
        {"stash_ref": "stash://space_test/f_preview", "target_format": {"toString": "bad"}, "filename": [], "size_change": {"toString": "bad"}},
    ])
    assert_inert(PreviewHTML(html))
    assert_inert(PreviewHTML(malformed))
    assert "converted file" in "".join(PreviewHTML(malformed).text)


def test_reference_encoding_preserves_custom_spaces_and_legacy_filenames():
    references = [
        ("stash://space_20260913_123456_abcdef12/f_012345abcdef", "/api/stash/space_20260913_123456_abcdef12/f_012345abcdef"),
        ("stash://My Space/café image.png", "/api/stash/My%20Space/caf%C3%A9%20image.png"),
        ("stash://space_legacy/image.png", "/api/stash/space_legacy/image.png"),
        ("stash://space_legacy/100%20literal.png", "/api/stash/space_legacy/100%2520literal.png"),
        ("stash://space_legacy/file%2Fname.png", "/api/stash/space_legacy/file%252Fname.png"),
        ("stash://space_legacy/file#?&name.png", "/api/stash/space_legacy/file%23%3F%26name.png"),
        ("stash://space_legacy/image');window.__injected=4;('.png", "/api/stash/space_legacy/image')%3Bwindow.__injected%3D4%3B('.png"),
        ('stash://space_legacy/image" onerror="probe.png', "/api/stash/space_legacy/image%22%20onerror%3D%22probe.png"),
    ]
    outputs = render_previews([{"stash_ref": ref, "target_format": "png"} for ref, _ in references])
    for html, (_, expected_url) in zip(outputs, references, strict=True):
        preview = PreviewHTML(html)
        assert_inert(preview)
        for _, attrs in preview.elements:
            for name in ("src", "href", "data-converted-image-url"):
                if name in attrs:
                    assert attrs[name] == expected_url
        assert any("data-converted-image-url" in attrs for _, attrs in preview.elements)


def test_malformed_references_are_omitted_without_reinterpreting_a_prefix_or_path():
    invalid = [
        None, 42, [], {}, "", "https://example.test/image.png", "prefix stash://space/f_image",
        "stash://space", "stash:///f_image", "stash://space/", "stash://space/f_image/extra",
        "stash://../f_image", "stash://space/..", "stash://./f_image", "stash://space/.",
        "stash://space/image..png", "stash://space/a\\b.png", "stash://space/f_image\x00",
        "stash://space/f_image\n", "stash://space/\ud800",
        "stash://space/f_image');window.__injected=5;//",
    ]
    assert render_previews([{"stash_ref": ref, "target_format": "png"} for ref in invalid]) == [""] * len(invalid)
