"""Shared metadata for selectable Jarvis router system prompts."""

DEFAULT_ROUTER_PROMPT_VERSION = "v1"
ROUTER_PROMPT_LABELS = {
    "v1": "v1 - Full context system prompt",
    "v2": "v2 - Compact full-context prompt",
    "v3": "v3 - Caveman hybrid prompt",
    "v4": "v4 - Caveman-light hybrid prompt",
}
ROUTER_PROMPT_VERSIONS = tuple(ROUTER_PROMPT_LABELS)


def available_router_prompt_versions() -> tuple[str, ...]:
    return ROUTER_PROMPT_VERSIONS


def router_prompt_version_options() -> list[dict[str, str]]:
    return [
        {"id": version, "label": ROUTER_PROMPT_LABELS[version]}
        for version in ROUTER_PROMPT_VERSIONS
    ]


def normalize_router_prompt_version(version: str | None) -> str:
    normalized = str(version or DEFAULT_ROUTER_PROMPT_VERSION).strip().lower()
    return normalized or DEFAULT_ROUTER_PROMPT_VERSION
