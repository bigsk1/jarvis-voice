"""Storage and validation helpers for the Jarvis Web prompt library."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

MAX_PROMPT_BYTES = 64 * 1024
MAX_PROMPT_HINTS = 5
PROMPT_NAME_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
RESERVED_PROMPT_NAMES = frozenset({"readme", "manage", "personal"})


class PromptLibraryError(ValueError):
    """A safe validation or persistence error for the prompt library."""


def _frontmatter_parts(content: str, *, require_closing: bool = False):
    """Return ``(mapping, body, raw_hints)`` for optional YAML frontmatter."""
    text = content or ""
    stripped = text.lstrip()
    lines = stripped.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text, []

    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        if require_closing:
            raise PromptLibraryError("Prompt YAML frontmatter is missing its closing --- delimiter")
        return {}, text, []

    frontmatter_text = "".join(lines[1:closing_index])
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise PromptLibraryError(f"Invalid prompt YAML frontmatter: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise PromptLibraryError("Prompt YAML frontmatter must be a mapping")

    raw_tool_hints = frontmatter.get("tool_hints", [])
    if raw_tool_hints is None:
        raw_tool_hints = []
    if not isinstance(raw_tool_hints, list):
        raise PromptLibraryError("Prompt frontmatter tool_hints must be a list of tool names")

    body = "".join(lines[closing_index + 1 :]).lstrip("\r\n")
    return frontmatter, body, raw_tool_hints


def parse_prompt_frontmatter(content: str) -> tuple[str, list[str]]:
    """Return runtime prompt body and de-duplicated optional tool hints."""
    _, body, raw_tool_hints = _frontmatter_parts(content)
    tool_hints: list[str] = []
    for hint in raw_tool_hints:
        if not isinstance(hint, str) or not hint.strip():
            raise PromptLibraryError(
                "Prompt frontmatter tool_hints must contain non-empty strings"
            )
        name = hint.strip()
        if name not in tool_hints:
            tool_hints.append(name)
    return body, tool_hints


def validate_prompt_name(name: Any) -> str:
    """Validate and return a safe personal prompt stem."""
    if not isinstance(name, str):
        raise PromptLibraryError("Prompt name must be text")
    value = name.strip()
    if not value:
        raise PromptLibraryError("Prompt name is required")
    if len(value) > 64:
        raise PromptLibraryError("Prompt name must be at most 64 characters")
    if value != name or not PROMPT_NAME_RE.fullmatch(value):
        raise PromptLibraryError(
            "Prompt name must use lowercase letters, numbers, and single underscores"
        )
    if value.casefold() in RESERVED_PROMPT_NAMES:
        raise PromptLibraryError(f"Prompt name is reserved: {value}")
    return value


def _warning(code: str, message: str, tool: str | None = None) -> dict[str, str]:
    warning = {"code": code, "message": message}
    if tool:
        warning["tool"] = tool
    return warning


def _contains_affirmative_side_effect(body: str) -> bool:
    verbs = r"(?:save|send|publish|remember|delete|modify)"
    for line in body.splitlines():
        candidate = re.sub(r"^[\s>*#\-\d.)]+", "", line).strip()
        if not candidate:
            continue
        if re.match(r"(?i)^(?:do not|don't|never|avoid|without)\b", candidate):
            continue
        if re.match(rf"(?i)^(?:always\s+)?{verbs}\b", candidate):
            return True
    return False


def prompt_advisories(
    content: str,
    body: str,
    tool_hints: list[str],
    tools_by_name: dict[str, dict] | None = None,
) -> list[dict[str, str]]:
    """Return non-blocking authoring and current-environment warnings."""
    warnings: list[dict[str, str]] = []
    if not re.search(r"(?m)^#\s+\S", body):
        warnings.append(_warning("missing_heading", "Add a level-one heading for the prompt label."))
    if len(content) > 12_000:
        warnings.append(_warning(
            "long_prompt",
            "This prompt is unusually long and will consume substantial model context.",
        ))
    if _contains_affirmative_side_effect(body):
        warnings.append(_warning(
            "possible_side_effect",
            "Review unconditional save, send, publish, remember, delete, or modify instructions.",
        ))
    if len(tool_hints) > 1:
        warnings.append(_warning(
            "multiple_tool_hints",
            "Multiple hints keep the prompt visible as a group; inactive hints are filtered at send time.",
        ))

    registry = tools_by_name or {}
    for hint in tool_hints:
        tool = registry.get(hint)
        if not tool:
            warnings.append(_warning(
                "unknown_tool_hint", f"#{hint} is not in the current tool registry.", hint
            ))
            continue
        if tool.get("blocked", False):
            message = f"#{hint} is blocked in Jarvis Web."
        elif tool.get("enabled", True) is False:
            message = f"#{hint} is disabled in the current mode or tool profile."
        elif tool.get("available", True) is False:
            message = f"#{hint} is missing required configuration."
        else:
            continue
        warnings.append(_warning("inactive_tool_hint", message, hint))
    return warnings


def validate_prompt_draft(
    name: Any,
    content: Any,
    tools_by_name: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Validate a UI-authored prompt and return parsed metadata plus warnings."""
    safe_name = validate_prompt_name(name)
    if not isinstance(content, str):
        raise PromptLibraryError("Prompt content must be UTF-8 text")
    if not content.strip():
        raise PromptLibraryError("Prompt content cannot be empty")
    try:
        encoded_content = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PromptLibraryError("Prompt content must be valid UTF-8 text") from exc
    if len(encoded_content) > MAX_PROMPT_BYTES:
        raise PromptLibraryError("Prompt content must be 64 KiB or smaller")

    _, body, raw_tool_hints = _frontmatter_parts(content, require_closing=True)
    tool_hints: list[str] = []
    for hint in raw_tool_hints:
        if not isinstance(hint, str) or not hint.strip():
            raise PromptLibraryError(
                "Prompt frontmatter tool_hints must contain non-empty strings"
            )
        normalized = hint.strip()
        if normalized in tool_hints:
            raise PromptLibraryError(f"Duplicate tool hint: {normalized}")
        tool_hints.append(normalized)
    if len(tool_hints) > MAX_PROMPT_HINTS:
        raise PromptLibraryError(
            f"Prompt frontmatter accepts at most {MAX_PROMPT_HINTS} tool hints"
        )

    warnings = prompt_advisories(content, body, tool_hints, tools_by_name)

    return {
        "name": safe_name,
        "content": content,
        "body": body,
        "tool_hints": tool_hints,
        "warnings": warnings,
    }


def prompt_metadata(name: str, content: str) -> dict[str, Any]:
    """Parse one runtime prompt into the existing chat-registry shape."""
    body, tool_hints = parse_prompt_frontmatter(content)
    lines = body.strip().split("\n")
    description = ""
    if lines and lines[0].startswith("#"):
        description = lines[0].lstrip("#").strip()

    key_points: list[str] = []
    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("-", "*", "•")) or (
            len(line) > 2 and line[0].isdigit() and line[1] in ".):"
        ):
            point = line.lstrip("-*•0123456789.) ").strip()
            if point and len(point) > 3:
                key_points.append(point[:80])
        elif line.startswith("##"):
            key_points.append(line.lstrip("#").strip())
        if len(key_points) >= 5:
            break

    if not key_points:
        for raw_line in lines[1:6]:
            line = raw_line.strip()
            if line and not line.startswith("#"):
                key_points.append(line[:80])

    record: dict[str, Any] = {
        "name": name,
        "description": description,
        "content": body,
        "key_points": key_points[:5],
    }
    if tool_hints:
        record["tool_hints"] = tool_hints
    return record


def resolve_prompt_file(prompts_path: Path, name: str) -> Path | None:
    """Resolve a prompt with personal-over-built-in precedence."""
    if name.casefold() == "readme":
        return None
    personal_file = prompts_path / "personal" / f"{name}.md"
    if personal_file.is_file() and not personal_file.is_symlink():
        return personal_file
    shared_file = prompts_path / f"{name}.md"
    if shared_file.is_file() and not shared_file.is_symlink():
        return shared_file
    return None


def iter_effective_prompt_files(prompts_path: Path) -> Iterable[tuple[str, Path]]:
    """Yield effective prompt files with personal precedence."""
    prompts: dict[str, Path] = {}
    if prompts_path.exists():
        for prompt_file in prompts_path.glob("*.md"):
            if prompt_file.name.casefold() != "readme.md" and not prompt_file.is_symlink():
                prompts[prompt_file.stem] = prompt_file
        personal_dir = prompts_path / "personal"
        if personal_dir.exists():
            for prompt_file in personal_dir.glob("*.md"):
                if prompt_file.name.casefold() != "readme.md" and not prompt_file.is_symlink():
                    prompts[prompt_file.stem] = prompt_file
    for stem in sorted(prompts):
        yield stem, prompts[stem]


def iter_prompt_sources(prompts_path: Path) -> Iterable[dict[str, Any]]:
    """Yield every effective prompt with built-in/override source metadata."""
    shared = {
        path.stem: path
        for path in prompts_path.glob("*.md")
        if path.name.casefold() != "readme.md" and not path.is_symlink()
    } if prompts_path.exists() else {}
    personal_dir = prompts_path / "personal"
    personal = {
        path.stem: path
        for path in personal_dir.glob("*.md")
        if path.name.casefold() != "readme.md" and not path.is_symlink()
    } if personal_dir.exists() else {}

    for name in sorted(set(shared) | set(personal)):
        personal_file = personal.get(name)
        shared_file = shared.get(name)
        yield {
            "name": name,
            "path": personal_file or shared_file,
            "source": "personal" if personal_file else "built_in",
            "overrides_shared": bool(personal_file and shared_file),
            "has_shared": bool(shared_file),
        }


def _personal_destination(prompts_path: Path, name: str) -> tuple[Path, Path]:
    safe_name = validate_prompt_name(name)
    personal_dir = prompts_path / "personal"
    personal_dir.mkdir(parents=True, exist_ok=True)
    if personal_dir.is_symlink():
        raise PromptLibraryError("Refusing to use a symlinked personal prompt directory")
    root = personal_dir.resolve()
    destination = personal_dir / f"{safe_name}.md"
    if destination.is_symlink():
        raise PromptLibraryError("Refusing to write a symlinked prompt file")
    if destination.parent.resolve() != root:
        raise PromptLibraryError("Prompt destination escapes the personal prompt directory")
    return root, destination


def write_personal_prompt(
    prompts_path: Path,
    name: str,
    content: str,
    *,
    must_exist: bool | None = None,
) -> Path:
    """Atomically write one validated personal prompt."""
    _, destination = _personal_destination(prompts_path, name)
    exists = destination.is_file()
    if must_exist is True and not exists:
        raise FileNotFoundError(name)
    if must_exist is False and exists:
        raise FileExistsError(name)

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.stem}-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, destination)
        temporary = None
        return destination
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def delete_personal_prompt(prompts_path: Path, name: str) -> bool:
    """Delete exactly one personal prompt, refusing symlink destinations."""
    _, destination = _personal_destination(prompts_path, name)
    if destination.is_symlink():
        raise PromptLibraryError("Refusing to delete a symlinked prompt file")
    if not destination.is_file():
        raise FileNotFoundError(name)
    destination.unlink()
    return (prompts_path / f"{validate_prompt_name(name)}.md").is_file()
