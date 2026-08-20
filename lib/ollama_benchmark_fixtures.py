"""Frozen production-shaped fixtures for the local Ollama model benchmark.

Tools are loaded from tracked ``skills/*.tool.json`` files (not live memory or
synced DBs). Router text comes from the selected local prompt version plus any
model overlay. Nothing here executes a tool or reads Jarvis data.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from paths import get_project_root

PRODUCTION_SHORTLIST = (
    "weather",
    "calculator",
    "crawl_url",
    "brave_llm_context",
    "create_reminder",
    "send_email",
    "tool_search",
)

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _skills_dir() -> Path:
    return get_project_root() / "skills"


def _skill_tool_path(name: str) -> Path:
    candidates = (
        _skills_dir() / f"{name}.tool.json",
        _skills_dir() / "auto-tools" / f"{name}.tool.json",
    )
    matches = [path for path in candidates if path.is_file()]
    if not matches:
        raise FileNotFoundError(
            f"benchmark fixture missing skill file for {name!r}: "
            + ", ".join(str(path) for path in candidates)
        )
    if len(matches) > 1:
        raise ValueError(
            f"benchmark fixture has ambiguous skill files for {name!r}: "
            + ", ".join(str(path) for path in matches)
        )
    return matches[0]


def load_skill_tool(name: str) -> dict[str, Any]:
    """Load one tracked tool schema into the Anthropic-shaped provider format."""
    path = _skill_tool_path(name)
    payload = json.loads(path.read_text(encoding="utf-8"))
    parameters = payload.get("parameters") or {"type": "object", "properties": {}}
    if not isinstance(parameters, dict):
        raise ValueError(f"{path} parameters must be an object")
    return {
        "name": str(payload.get("name") or name),
        "description": str(payload.get("description") or ""),
        "input_schema": parameters,
        "source": str(path.relative_to(get_project_root())),
    }


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """Return exactly the fields converted and sent by OllamaProvider."""
    return {
        "name": str(tool.get("name") or ""),
        "description": str(tool.get("description") or ""),
        "input_schema": tool.get("input_schema")
        or {
            "type": "object",
            "properties": {},
        },
    }


def tool_schema_sha256(tool: dict[str, Any]) -> str:
    return _canonical_json_sha256(canonical_tool_schema(tool))


def tool_shortlist_sha256(tools: list[dict[str, Any]]) -> str:
    return _canonical_json_sha256([canonical_tool_schema(tool) for tool in tools])


def replay_fixture_path() -> Path:
    return get_project_root() / "config" / "benchmarks" / "ollama-tool-rag-replay-v2.json"


def load_tool_rag_replay_fixture() -> dict[str, Any]:
    """Load content-addressed, redacted Tool RAG decision replay packets.

    The fixture contains synthetic replacement queries and live trace *shape*
    metadata only. Exact schemas stay in their tracked skill files and are
    pinned by SHA-256; schema drift therefore fails closed instead of silently
    changing the comparison workload.
    """
    path = replay_fixture_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("schema_version") or 0) != 2:
        raise ValueError(f"unsupported Ollama replay fixture schema in {path}")
    if payload.get("fixture_id") != "jarvis-ollama-tool-rag-replay-v2":
        raise ValueError(f"unexpected Ollama replay fixture id in {path}")
    safety = payload.get("safety") or {}
    if not safety.get("synthetic_queries_only") or safety.get("live_user_text_copied"):
        raise ValueError(f"unsafe query provenance in Ollama replay fixture {path}")

    resolved_packets = []
    seen_packet_ids: set[str] = set()
    seen_case_ids: set[str] = set()
    allowed_expected_keys = {
        "decision",
        "tool_name",
        "arguments",
        "optional_arguments",
        "argument_concepts",
        "response_concepts",
    }

    def validate_concept_groups(value: Any, label: str) -> None:
        if not isinstance(value, list) or not value:
            raise ValueError(f"{label} must contain at least one concept group")
        for alternatives in value:
            if not isinstance(alternatives, list) or not alternatives:
                raise ValueError(f"{label} contains an empty concept group")
            if not all(isinstance(item, str) and item.strip() for item in alternatives):
                raise ValueError(f"{label} concept alternatives must be non-empty strings")

    for packet in payload.get("packets") or []:
        packet_id = str(packet.get("packet_id") or "")
        names = [str(item) for item in (packet.get("final_tools") or [])]
        if not packet_id or packet_id in seen_packet_ids or not names:
            raise ValueError(f"invalid replay packet in {path}: missing id or final_tools")
        seen_packet_ids.add(packet_id)
        expected_hashes = packet.get("tool_schema_sha256") or {}
        tools = [load_skill_tool(name) for name in names]
        for tool in tools:
            name = str(tool["name"])
            actual = tool_schema_sha256(tool)
            expected = str(expected_hashes.get(name) or "")
            if not expected or actual != expected:
                raise ValueError(
                    f"replay packet {packet_id!r} schema drift for {name!r}; "
                    "refresh and review the frozen benchmark fixture"
                )
        actual_shortlist_hash = tool_shortlist_sha256(tools)
        if actual_shortlist_hash != str(packet.get("schema_snapshot_sha256") or ""):
            raise ValueError(f"replay packet {packet_id!r} shortlist schema snapshot drifted")
        tools_by_name = {str(tool["name"]): tool for tool in tools}
        for case in packet.get("cases") or []:
            case_id = str(case.get("case_id") or "")
            query = str(case.get("query") or "").strip()
            expected = case.get("expected") or {}
            if not case_id or not query or case_id in seen_case_ids:
                raise ValueError(f"invalid or duplicate replay case id {case_id!r}")
            seen_case_ids.add(case_id)
            unknown = set(expected) - allowed_expected_keys
            if unknown:
                raise ValueError(
                    f"replay case {case_id!r} has unknown expectation keys: "
                    + ", ".join(sorted(unknown))
                )
            decision = str(expected.get("decision") or "")
            tool_name = str(expected.get("tool_name") or "")
            if decision not in {"tool", "tool_search", "direct"}:
                raise ValueError(f"replay case {case_id!r} has invalid decision {decision!r}")
            if decision == "direct":
                if tool_name:
                    raise ValueError(f"direct replay case {case_id!r} cannot name a tool")
                extra_direct = set(expected) - {"decision", "response_concepts"}
                if extra_direct:
                    raise ValueError(f"direct replay case {case_id!r} has tool-only expectations")
                validate_concept_groups(
                    expected.get("response_concepts"),
                    f"replay case {case_id!r} response_concepts",
                )
                continue
            required_tool = "tool_search" if decision == "tool_search" else tool_name
            if not required_tool or required_tool not in tools_by_name:
                raise ValueError(
                    f"replay case {case_id!r} expects a tool outside its frozen shortlist"
                )
            if decision == "tool_search" and tool_name != "tool_search":
                raise ValueError(f"replay case {case_id!r} must name tool_search")
            schema = tools_by_name[required_tool].get("input_schema") or {}
            schema_keys = set(schema.get("properties") or {})
            exact_args = expected.get("arguments") or {}
            optional_args = expected.get("optional_arguments") or {}
            concept_args = expected.get("argument_concepts") or {}
            if not all(
                isinstance(value, dict) for value in (exact_args, optional_args, concept_args)
            ):
                raise ValueError(f"replay case {case_id!r} argument expectations must be objects")
            expected_keys = set(exact_args) | set(optional_args) | set(concept_args)
            if expected_keys - schema_keys:
                raise ValueError(
                    f"replay case {case_id!r} references unknown argument keys: "
                    + ", ".join(sorted(expected_keys - schema_keys))
                )
            if set(exact_args) & set(optional_args):
                raise ValueError(f"replay case {case_id!r} repeats exact and optional arguments")
            for key, groups in concept_args.items():
                validate_concept_groups(
                    groups,
                    f"replay case {case_id!r} argument_concepts.{key}",
                )
        resolved = dict(packet)
        resolved["tools"] = tools
        resolved_packets.append(resolved)

    resolved_payload = dict(payload)
    resolved_payload["packets"] = resolved_packets
    resolved_payload["fixture_path"] = str(path.relative_to(get_project_root()))
    resolved_payload["fixture_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return resolved_payload


def load_production_shortlist() -> dict[str, dict[str, Any]]:
    """Return the local-mode-sized tool shortlist used by the benchmark."""
    tools = {name: load_skill_tool(name) for name in PRODUCTION_SHORTLIST}
    missing = [name for name in PRODUCTION_SHORTLIST if tools[name]["name"] != name]
    if missing:
        raise ValueError(f"skill file name mismatch for: {', '.join(missing)}")
    return tools


def load_router_prompt(version: str = "v4") -> tuple[str, str]:
    """Load a router prompt module by version without importing orchestrator."""
    normalized = str(version or "v4").strip().lower() or "v4"
    path = get_project_root() / "orchestrator" / "router_prompts" / f"{normalized}.py"
    if not path.is_file():
        raise FileNotFoundError(f"unknown router prompt version {normalized!r}: {path}")
    spec = importlib.util.spec_from_file_location(f"jarvis_router_prompt_{normalized}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load router prompt {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prompt = getattr(module, "BASE_SYSTEM_PROMPT", None)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"{path} does not define BASE_SYSTEM_PROMPT")
    return normalized, prompt


def build_routing_system_prompt(model: str, *, version: str = "v4") -> dict[str, Any]:
    """Assemble router text plus the Ollama model's production overlay."""
    from model_prompt_overrides import apply_prompt_override_sections, load_model_prompt_override

    resolved_version, base_prompt = load_router_prompt(version)
    override = load_model_prompt_override("ollama", model, mode="local")
    prompt = apply_prompt_override_sections(
        base_prompt,
        override,
        prepend_sections=("routing_prepend", "tool_calling_prepend"),
        append_sections=("routing_append",),
    )
    overlay_sections = {
        section: override.get(section)
        for section in ("routing_prepend", "tool_calling_prepend", "routing_append")
        if override.get(section)
    }
    return {
        "version": resolved_version,
        "prompt": prompt,
        "base_prompt_sha256": hashlib.sha256(base_prompt.encode("utf-8")).hexdigest(),
        "overlay_sha256": _canonical_json_sha256(overlay_sections),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "override_matched_model": override.matched_model or None,
        "override_source": override.source_path or None,
        "override_enabled": bool(override.enabled),
    }


def is_loopback_url(url: str) -> bool:
    """True when a base URL targets this machine's Ollama helper daemon."""
    host = (urlparse(str(url or "").strip()).hostname or "").lower()
    return host in LOOPBACK_HOSTS
