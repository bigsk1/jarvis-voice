"""The transcript tool must report whether its readable Stash artifact exists."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOL_PATH = Path(__file__).parent.parent / "skills" / "auto-tools" / "youtube_transcript.py"
SPEC = importlib.util.spec_from_file_location("youtube_transcript_status_test", TOOL_PATH)
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


@pytest.mark.parametrize(
    ("srt_saved", "md_saved", "expected_ok"),
    [
        (False, False, False),
        (True, False, False),
        (False, True, True),
        (True, True, True),
    ],
)
def test_transcript_status_requires_markdown_stash_artifact(
    monkeypatch, capsys, srt_saved, md_saved, expected_ok
):
    space = SimpleNamespace(space_id="space_transcript")
    saves = iter(
        [
            (srt_saved, space if srt_saved else None, "stash://space_transcript/srt" if srt_saved else None),
            (md_saved, space if md_saved else None, "stash://space_transcript/md" if md_saved else None),
        ]
    )
    monkeypatch.setattr(sys, "argv", [str(TOOL_PATH), json.dumps({"url": "https://youtu.be/example"})])
    monkeypatch.setattr(TOOL, "load_config", lambda: None)
    monkeypatch.setattr(TOOL, "build_proxy_url_attempts", lambda **_kwargs: [None])
    monkeypatch.setattr(
        TOOL,
        "download_transcript",
        lambda _url, proxy=None: ("1\n00:00:00,000 --> 00:00:01,000\nHello\n", "Example", None),
    )
    monkeypatch.setattr(TOOL, "save_to_stash", lambda *_args: next(saves))
    monkeypatch.setattr(TOOL, "MemoryDB", lambda: SimpleNamespace(remember=lambda **_kwargs: None))

    TOOL.main()

    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is expected_ok
    assert result["data"]["srt_saved"] is srt_saved
    assert result["data"]["md_saved"] is md_saved
    if md_saved:
        assert result["data"]["space_id"] == space.space_id
    if not expected_ok:
        assert "stash" in result["error"].lower()
