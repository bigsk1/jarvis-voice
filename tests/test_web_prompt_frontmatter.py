"""Web UI @prompt frontmatter and personal-prompt regressions."""

import subprocess
from pathlib import Path

import pytest

from server_package_utils import load_server_package


ROOT = Path(__file__).resolve().parents[1]
load_server_package("jarvis_web_test_server", ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.routes import api  # noqa: E402


def test_parse_prompt_frontmatter_uses_yaml_and_returns_clean_body():
    body, hints = api._parse_prompt_frontmatter(
        """---
tool_hints:
  - create_social_clip # Prefer the configured renderer.
  - 'stash'
---

# Social Clip

Create the requested clip.
"""
    )

    assert hints == ["create_social_clip", "stash"]
    assert body.startswith("# Social Clip")
    assert "tool_hints:" not in body


@pytest.mark.parametrize(
    "frontmatter, message",
    [
        ("tool_hints: create_social_clip", "must be a list"),
        ("tool_hints: [create_social_clip, 42]", "non-empty strings"),
        ("- create_social_clip", "must be a mapping"),
    ],
)
def test_parse_prompt_frontmatter_rejects_invalid_metadata(frontmatter, message):
    with pytest.raises(ValueError, match=message):
        api._parse_prompt_frontmatter(f"---\n{frontmatter}\n---\n# Body\n")


def test_parse_prompt_frontmatter_leaves_plain_markdown_unchanged():
    content = "# Plain prompt\n\nUse these instructions.\n"

    assert api._parse_prompt_frontmatter(content) == (content, [])


def test_personal_prompt_overrides_shared_and_readme_is_not_loaded(tmp_path, monkeypatch):
    prompts_dir = tmp_path / "prompts"
    personal_dir = prompts_dir / "personal"
    personal_dir.mkdir(parents=True)
    (prompts_dir / "social_clip.md").write_text("# Shared\n")
    personal_prompt = personal_dir / "social_clip.md"
    personal_prompt.write_text("# Personal\n")
    (personal_dir / "README.md").write_text("# Personal prompt documentation\n")
    monkeypatch.setattr(api, "PROMPTS_PATH", prompts_dir)

    prompts = dict(api._iter_prompt_files())

    assert prompts == {"social_clip": personal_prompt}
    assert api._resolve_prompt_file("social_clip") == personal_prompt
    assert api._resolve_prompt_file("README") is None


@pytest.mark.parametrize(
    "tool, expected",
    [
        ({"name": "create_social_clip", "enabled": True, "available": True}, True),
        ({"name": "create_social_clip", "enabled": False, "available": True}, False),
        ({"name": "create_social_clip", "enabled": True, "available": False}, False),
        ({"name": "create_social_clip", "enabled": True, "blocked": True}, False),
    ],
)
def test_single_tool_prompt_requires_an_available_tool(tool, expected):
    record = {"tool_hints": ["create_social_clip"]}

    assert api._prompt_is_available(record, {tool["name"]: tool}) is expected


def test_single_tool_prompt_is_hidden_when_tool_is_not_loaded():
    assert api._prompt_is_available({"tool_hints": ["missing_tool"]}, {}) is False


def test_general_and_multi_tool_prompts_are_not_availability_gated():
    assert api._prompt_is_available({}, {}) is True
    assert api._prompt_is_available({"tool_hints": ["search_one", "search_two"]}, {}) is True


def test_saved_prompt_and_tool_badges_are_reconstructed_safely():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8')
  .split('// Global command system instance')[0];
global.fetch = async () => { throw new Error('registry loading disabled in test'); };
eval(source + '\nglobal.CommandSystem = CommandSystem;');

const commands = Object.create(global.CommandSystem.prototype);
Object.assign(commands, {prompts: {}, workflows: {}, tools: {}, maxToolHints: 5});

const badge = commands.getPersistedDisplay({
  prompt: 'social_clip',
  tool_hints: ['create_social_clip']
});
if (badge !== '@social_clip 📝 + #create_social_clip 🛠️') {
  throw new Error(`Unexpected persisted badge: ${badge}`);
}

const sanitized = commands.getPersistedDisplay({
  prompt: '<img_onerror>',
  tool_hints: ['safe_tool', '<script>', 'safe_tool']
});
if (sanitized !== '#safe_tool 🛠️') {
  throw new Error(`Unsafe or duplicate metadata survived: ${sanitized}`);
}
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
