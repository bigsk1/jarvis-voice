#!/usr/bin/env python3
"""
Tool Schema and Registry System
Universal tool definition that works across all LLM providers.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any

from http_client import normalize_proxy_policy
from hybrid_retrieval import adaptive_rank_cutoff, query_segments
from tool_rag_typo_hints import expand_tool_rag_query_for_typo_hints

_logger = logging.getLogger(__name__)
_MANDATORY_GHOST_TOOLS = ("tool_search", "workflow")
_ADAPTIVE_DYNAMIC_TOOL_MAX = 5
_COMPOUND_SEGMENT_TOOL_MAX = 2


def _merge_compound_segment_rankings(
    primary: list[dict[str, Any]],
    segment_rankings: list[tuple[str, list[dict[str, Any]]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge small per-clause retrieval views into the full-query ranking."""
    by_name: dict[str, dict[str, Any]] = {}
    for row in primary:
        name = str(row.get("name") or "")
        if not name:
            continue
        item = dict(row)
        item["full_query_hybrid_score"] = float(row.get("hybrid_score") or 0.0)
        by_name[name] = item

    segment_meta: list[dict[str, Any]] = []
    for segment, ranked in segment_rankings:
        selected, cutoff_meta = adaptive_rank_cutoff(
            ranked,
            budget=_COMPOUND_SEGMENT_TOOL_MAX,
        )
        segment_meta.append(
            {
                "query": segment,
                "selected_tools": [row.get("name") for row in selected],
                "adaptive_selection": cutoff_meta,
            }
        )
        for row in selected:
            name = str(row.get("name") or "")
            if not name:
                continue
            segment_score = float(row.get("hybrid_score") or 0.0)
            item = by_name.get(name)
            if item is None:
                item = dict(row)
                item["full_query_hybrid_score"] = None
                item["segment_only"] = True
                by_name[name] = item
            current_segment_score = float(item.get("segment_hybrid_score") or 0.0)
            if segment_score >= current_segment_score:
                item["segment_hybrid_score"] = segment_score
            if segment_score > float(item.get("hybrid_score") or 0.0):
                for field in (
                    "similarity",
                    "dense_rank",
                    "dense_confidence",
                    "keyword_rank",
                    "keyword_bm25",
                    "keyword_coverage",
                    "keyword_confidence",
                    "exact_name_match",
                    "retrieval_channels",
                    "rrf_score",
                ):
                    if field in row:
                        item[field] = row[field]
                item["hybrid_score"] = segment_score
            segment_queries = item.setdefault("segment_queries", [])
            if segment not in segment_queries:
                segment_queries.append(segment)

    merged = list(by_name.values())
    merged.sort(
        key=lambda item: (
            float(item.get("hybrid_score") or 0.0),
            float(item.get("rrf_score") or 0.0),
            float(item.get("similarity") or 0.0),
        ),
        reverse=True,
    )
    return merged, segment_meta


def _merged_ghost_tool_names(raw_value: str | None, available_names: set[str]) -> list[str]:
    """Return configured ghost tools plus mandatory discovery helpers."""
    names = [t.strip() for t in str(raw_value or "").split(",") if t.strip()]
    for mandatory in _MANDATORY_GHOST_TOOLS:
        if mandatory in available_names and mandatory not in names:
            names.append(mandatory)
    return names


def _json_type_for_const(value: Any) -> str | None:
    """Infer a JSON Schema primitive type for a const value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return None


def _collapse_simple_combinator(variants: Any) -> dict[str, Any]:
    """
    Convert simple anyOf/oneOf const/type unions into OpenAI-safe schema pieces.

    OpenAI rejects JSON Schema combinators, but many MCP schemas use them only
    to express "one of these string constants" or "a string matching one of
    these known shortcuts or a free-form date range". Preserve that signal
    instead of dropping the constraint entirely.
    """
    if not isinstance(variants, list):
        return {}

    types: set[str] = set()
    enum_values: list[Any] = []
    has_generic_branch = False

    for variant in variants:
        if not isinstance(variant, dict):
            continue

        variant_type = variant.get("type")

        if "const" in variant:
            const_value = variant["const"]
            inferred_type = variant_type or _json_type_for_const(const_value)
            if inferred_type:
                types.add(inferred_type)
            if const_value not in enum_values:
                enum_values.append(const_value)
            continue

        if isinstance(variant.get("enum"), list):
            if variant_type:
                types.add(variant_type)
            for enum_value in variant["enum"]:
                inferred_type = variant_type or _json_type_for_const(enum_value)
                if inferred_type:
                    types.add(inferred_type)
                if enum_value not in enum_values:
                    enum_values.append(enum_value)
            continue

        if variant_type:
            types.add(variant_type)
            has_generic_branch = True

    if len(types) != 1:
        return {}

    collapsed: dict[str, Any] = {"type": next(iter(types))}
    if enum_values and not has_generic_branch:
        collapsed["enum"] = enum_values
    return collapsed


def _schema_type_includes(schema_type: Any, expected_type: str) -> bool:
    if isinstance(schema_type, str):
        return schema_type == expected_type
    if isinstance(schema_type, list):
        return expected_type in schema_type
    return False


def _sanitize_schema_for_openai(schema: Any, *, is_root: bool = False) -> Any:
    """
    Strip JSON Schema features that OpenAI function calling rejects.

    OpenAI tool schemas require a top-level object schema and are stricter than
    full JSON Schema. In practice, combinators like allOf/anyOf/oneOf/not and
    conditional keywords can cause the entire request to fail before routing.
    We keep the core object/property shape and drop unsupported validation-only
    constructs so tool calling stays available.
    """
    if isinstance(schema, list):
        return [_sanitize_schema_for_openai(item, is_root=False) for item in schema]

    if not isinstance(schema, dict):
        return schema

    unsupported_keys = {
        "allOf", "not",
        "if", "then", "else", "dependentSchemas"
    }

    sanitized: dict[str, Any] = {}
    for key, value in schema.items():
        if key in {"anyOf", "oneOf"}:
            for collapsed_key, collapsed_value in _collapse_simple_combinator(value).items():
                sanitized.setdefault(collapsed_key, collapsed_value)
            continue
        if key == "const":
            sanitized.setdefault("enum", [value])
            sanitized.setdefault("type", _json_type_for_const(value) or "string")
            continue
        if key in unsupported_keys:
            continue
        if is_root and key == "enum":
            continue
        sanitized[key] = _sanitize_schema_for_openai(value, is_root=False)

    if is_root:
        sanitized.setdefault("type", "object")
        sanitized.setdefault("properties", {})
    elif _schema_type_includes(sanitized.get("type"), "array"):
        sanitized.setdefault("items", {})

    return sanitized


class ToolSchema:
    """Defines a tool's capabilities in a provider-agnostic way."""
    
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        script_path: str,
        permissions: dict[str, Any] | None = None,
        deterministic_routing: dict[str, Any] | None = None,
        proxy_policy: str = "inherit",
        prerequisite_tools: list[str] | None = None,
    ):
        """
        Initialize a tool schema.
        
        Args:
            name: Tool name (e.g., "send_webhook")
            description: What the tool does
            parameters: JSON Schema for parameters
            script_path: Path to executable script
            permissions: Permission settings
                {
                    "dangerous": bool,  # Requires confirmation
                    "bash": bool,       # Executes bash commands
                    "network": bool,    # Makes network requests
                    "filesystem": bool, # Accesses filesystem
                    "auto_approve": bool # Skip confirmation (for safe tools)
                }
            deterministic_routing: Optional metadata for non-LLM fallback routing.
            proxy_policy: Runtime network policy: inherit, off, prefer, or require.
            prerequisite_tools: Optional upstream tools that should be visible
                whenever this tool is retrieved so required inputs can be resolved.
        """
        self.name = name
        self.description = description
        self.parameters = parameters
        self.script_path = script_path
        self.permissions = permissions or {
            "dangerous": False,
            "bash": False,
            "network": False,
            "filesystem": False,
            "auto_approve": True
        }
        self.deterministic_routing = deterministic_routing or {}
        self.proxy_policy = normalize_proxy_policy(proxy_policy)
        raw_prerequisites = prerequisite_tools if isinstance(prerequisite_tools, list) else []
        self.prerequisite_tools = list(dict.fromkeys(
            tool_name.strip()
            for tool_name in raw_prerequisites
            if isinstance(tool_name, str) and tool_name.strip()
        ))
    
    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _sanitize_schema_for_openai(self.parameters, is_root=True)
            }
        }
    
    def to_anthropic_format(self) -> dict[str, Any]:
        """Convert to Anthropic tool calling format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters
        }
    
    def to_ollama_description(self) -> str:
        """Convert to plain text description for Ollama structured prompts."""
        params_desc = []
        if "properties" in self.parameters:
            for param_name, param_info in self.parameters["properties"].items():
                required = param_name in self.parameters.get("required", [])
                req_str = "(required)" if required else "(optional)"
                param_type = param_info.get("type", "string")
                param_desc = param_info.get("description", "")
                params_desc.append(f"  - {param_name} ({param_type}) {req_str}: {param_desc}")
        
        params_str = "\n".join(params_desc) if params_desc else "  No parameters"
        
        return f"""Tool: {self.name}
Description: {self.description}
Parameters:
{params_str}"""
    
    def requires_confirmation(self) -> bool:
        """Check if tool requires user confirmation before execution."""
        # If explicitly set to auto_approve, skip confirmation
        if self.permissions.get("auto_approve", False):
            return False
        
        # If marked as dangerous, always require confirmation
        if self.permissions.get("dangerous", False):
            return True
        
        # If uses bash, network, or filesystem, require confirmation
        if any([
            self.permissions.get("bash", False),
            self.permissions.get("network", False),
            self.permissions.get("filesystem", False)
        ]):
            return True
        
        return False
    
    def get_permission_warning(self) -> str:
        """Get warning message about tool permissions."""
        warnings = []
        if self.permissions.get("bash"):
            warnings.append("executes bash commands")
        if self.permissions.get("network"):
            warnings.append("makes network requests")
        if self.permissions.get("filesystem"):
            warnings.append("accesses filesystem")
        if self.permissions.get("dangerous"):
            warnings.append("performs dangerous operations")
        
        if warnings:
            return f"This tool {', '.join(warnings)}."
        return "This tool is safe to execute."
    
    @classmethod
    def from_json_file(cls, json_path: str) -> 'ToolSchema':
        """Load tool schema from a JSON file."""
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        # Resolve script path relative to schema file
        schema_dir = Path(json_path).parent
        script_name = data.get("script", f"{data['name']}.py")
        script_path = str(schema_dir / script_name)
        
        raw_description = data.get("description") or ""
        complementary = data.get("complementary_tools") or data.get("pairs_well_with")
        description = raw_description
        if complementary and isinstance(complementary, list):
            names = [str(x).strip() for x in complementary if str(x).strip()]
            if names:
                description = (
                    f"{raw_description}\n\n"
                    "Follow-up tools when the user wants hits saved, summarized, or packaged "
                    "(only call those that exist in the active tool list / profile): "
                    f"{', '.join(names)}."
                )

        return cls(
            name=data["name"],
            description=description,
            parameters=data.get("parameters", {"type": "object", "properties": {}}),
            script_path=script_path,
            permissions=data.get("permissions", None),
            deterministic_routing=data.get("deterministic_routing", None),
            proxy_policy=data.get("proxy_policy", "inherit"),
            prerequisite_tools=data.get("prerequisite_tools", None),
        )


class ToolRegistry:
    """Registry of all available tools (local + MCP)."""
    
    def __init__(self, skills_dir: str, mcp_config_path: str | None = None):
        """
        Initialize tool registry.
        
        Args:
            skills_dir: Path to skills directory
            mcp_config_path: Path to MCP servers config (optional)
        """
        import sys
        from tool_profiles import (
            describe_active_profile,
            get_active_profile_name,
            load_active_profile_overrides,
            warn_missing_profile_file,
        )

        self.skills_dir = Path(skills_dir)
        self.mcp_config_path = mcp_config_path
        self.tools: dict[str, ToolSchema] = {}
        self.mcp_clients: dict[str, Any] = {}
        self.mcp_manager = None
        self.mcp_unavailable: dict[str, str] = {}
        self.last_tool_search_meta: dict[str, Any] = {
            "retrieval_mode": "hybrid",
            "semantic_disabled_reason": None,
        }
        # Tools excluded because required configuration is missing in the
        # active mode: name -> AvailabilityResult (diagnostics for sync,
        # manage-tools, and web discovery; never contains secret values).
        self.unavailable_tools: dict[str, Any] = {}
        self._registry_verbose = sys.stdout.isatty() and not os.environ.get("JARVIS_JSON_MODE")
        self._profile_name = get_active_profile_name()
        self._profile_overrides = load_active_profile_overrides()
        warn_missing_profile_file()
        if self._registry_verbose:
            print(describe_active_profile(verbose=False))

        # Discover MCP tools FIRST (before local tools)
        if mcp_config_path and os.path.exists(mcp_config_path):
            self._discover_mcp_tools()

        # Then discover local tools
        self._discover_tools()

        # Profile can disable MCP tools (always registered with implicit base enabled)
        self._remove_tools_disabled_by_profile()
    
    def _remove_tools_disabled_by_profile(self) -> None:
        """Drop tools explicitly set to false in the active profile (e.g. MCP tools)."""
        removed: list[str] = []
        for name in list(self.tools.keys()):
            if self._profile_overrides.get(name) is False:
                del self.tools[name]
                removed.append(name)
        if removed and self._registry_verbose:
            for name in sorted(removed):
                print(f"⊝ Skipping {name} (disabled by tool profile '{self._profile_name}')")

    def _discover_tools(self):
        """Auto-discover tools by finding .tool.json files."""
        from config_loader import get_config_value
        from tool_availability import check_tool_availability, describe_missing
        from tool_profiles import effective_enabled

        verbose = self._registry_verbose

        # Check if OpenCode is enabled (legacy config support)
        opencode_enabled = get_config_value('OPENCODE_ENABLED', 'false').lower() == 'true'

        # Sort tool files alphabetically by name for consistent ordering
        # Include root skills/ and subdirectories like auto-tools/
        tool_files = sorted(self.skills_dir.glob("*.tool.json"))

        # Also include auto-tools subdirectory (auto-generated tools)
        auto_tools_dir = self.skills_dir / "auto-tools"
        if auto_tools_dir.exists():
            tool_files.extend(sorted(auto_tools_dir.glob("*.tool.json")))

        for tool_file in tool_files:
            try:
                with open(tool_file, 'r') as f:
                    tool_config = json.load(f)

                name = tool_config.get('name', tool_file.stem)
                base_enabled = tool_config.get('enabled', True)
                effective = effective_enabled(name, base_enabled, self._profile_overrides)

                if not effective:
                    if verbose:
                        if name in self._profile_overrides and not self._profile_overrides[name]:
                            reason = f"disabled by tool profile '{self._profile_name}'"
                        else:
                            reason = f"disabled in {tool_file.name}"
                        print(f"⊝ Skipping {name} ({reason})")
                    continue

                # Legacy: Skip opencode tool if disabled in config
                if tool_file.stem == 'opencode' and not opencode_enabled:
                    if verbose:
                        print("⊝ Skipping opencode tool (disabled in config)")
                    continue

                # Credential-aware availability: runs AFTER profile resolution
                # so a profile force-enable cannot bypass a missing hard
                # requirement. Only requirement NAMES are ever logged.
                availability = check_tool_availability(tool_config)
                if not availability.available:
                    self.unavailable_tools[name] = availability
                    if verbose:
                        print(f"⊝ Skipping {name} (unavailable — {describe_missing(availability)})")
                    continue

                schema = ToolSchema.from_json_file(str(tool_file))
                self.tools[schema.name] = schema
                if verbose:
                    print(f"✓ Registered tool: {schema.name}")
            except Exception as e:
                if verbose:
                    print(f"✗ Failed to load tool {tool_file}: {e}")
    
    def get_tool(self, name: str) -> ToolSchema | None:
        """Get tool by name."""
        return self.tools.get(name)
    
    def list_tools(self) -> list[str]:
        """List all tool names."""
        return list(self.tools.keys())
    
    def to_openai_format(self) -> list[dict[str, Any]]:
        """Get all tools in OpenAI format."""
        return [tool.to_openai_format() for tool in self.tools.values()]
    
    def to_anthropic_format(self) -> list[dict[str, Any]]:
        """Get all tools in Anthropic format."""
        return [tool.to_anthropic_format() for tool in self.tools.values()]
    
    def to_ollama_prompt(self) -> str:
        """Get all tools as structured text for Ollama."""
        if not self.tools:
            return "No tools available."
        
        tools_desc = []
        for tool in self.tools.values():
            tools_desc.append(tool.to_ollama_description())
        
        return "\n\n".join(tools_desc)
    
    def _discover_mcp_tools(self):
        """Discover tools from MCP servers with proper startup sequence."""
        import sys
        import time
        from mcp_client import MCPManager
        
        # Only show verbose output if in TTY mode or not in JSON mode
        verbose = sys.stdout.isatty() and not os.environ.get('JARVIS_JSON_MODE')
        
        try:
            if verbose:
                print("🔌 Starting MCP servers...")
            
            # Load config to check which servers are enabled
            with open(self.mcp_config_path, 'r') as f:
                config = json.load(f)
            
            # Create manager (creates clients but doesn't start them)
            manager = MCPManager(self.mcp_config_path)
            self.mcp_manager = manager
            
            # PHASE 1: Start all enabled servers
            enabled_servers = []
            for server_name, client in manager.servers.items():
                server_config = config.get("mcpServers", {}).get(server_name, {})
                if not server_config.get("enabled", False):
                    if verbose:
                        print(f"  ⊝ {server_name} (disabled)")
                    continue
                
                # Discovery is a bounded startup probe. Disable stdio crash
                # recovery before start(), because start() performs the MCP
                # initialize handshake and can otherwise enter the runtime
                # restart loop before tools/list is reached.
                previous_auto_restart = getattr(client, "_auto_restart", None)
                if previous_auto_restart is not None:
                    client._auto_restart = False

                try:
                    if verbose:
                        print(f"  ⏳ Starting {server_name}...")
                    client.start()
                    enabled_servers.append((server_name, client, previous_auto_restart))
                    if verbose:
                        print(f"  ✓ {server_name} started")
                except Exception as e:
                    reason = str(e).strip() or "failed to start"
                    self.mcp_unavailable[server_name] = reason
                    if verbose:
                        print(f"  ⚠️ {server_name} unavailable (skipped): {reason[:120]}")
                    try:
                        client.stop()
                    except Exception:
                        pass
                    if previous_auto_restart is not None:
                        client._auto_restart = previous_auto_restart
            
            if not enabled_servers:
                if verbose:
                    print("  No enabled MCP servers")
                return
            
            # PHASE 2: Wait for all servers to initialize
            if verbose:
                print(f"\n⏱️  Waiting for {len(enabled_servers)} server(s) to initialize...")
            time.sleep(2)  # Give Docker containers time to fully start
            
            # PHASE 3: Discover tools from each started server
            if verbose:
                print("🔍 Discovering tools...")
            
            # Sort servers alphabetically for consistent ordering
            enabled_servers_sorted = sorted(enabled_servers, key=lambda x: x[0])
            
            for server_name, client, previous_auto_restart in enabled_servers_sorted:
                try:
                    # Get tools from started server
                    tools = client.list_tools()

                    # Remote HTTP/SSE clients have no subprocess. Only inspect
                    # an exit code when this transport actually owns one.
                    process = getattr(client, "process", None)
                    exit_code = process.poll() if process else None
                    if not tools:
                        reason = (
                            f"exited during discovery (code {exit_code})"
                            if exit_code is not None
                            else "no tools returned"
                        )
                        self.mcp_unavailable[server_name] = reason
                        if verbose:
                            print(f"  ⚠️ {server_name} unavailable (skipped): {reason}")
                        try:
                            client.stop()
                        except Exception:
                            pass
                        continue
                    
                    # Store client for later use
                    self.mcp_clients[server_name] = client
                    
                    # Register each MCP tool
                    for tool_info in tools:
                        # Use underscores for compatibility with all LLM providers
                        # (Anthropic doesn't allow dots in tool names)
                        tool_name = f"mcp_{server_name}_{tool_info['name']}"
                        
                        # Convert MCP tool to our ToolSchema format
                        schema = ToolSchema(
                            name=tool_name,
                            description=tool_info.get('description', ''),
                            parameters=tool_info.get('inputSchema', {}),
                            script_path=f"__mcp__{server_name}__{tool_info['name']}",
                            permissions={
                                "dangerous": False,
                                "bash": False,
                                "network": True,
                                "filesystem": False,
                                "auto_approve": True
                            },
                            proxy_policy=getattr(client, "proxy_policy", "inherit"),
                        )
                        
                        self.tools[tool_name] = schema
                    
                    if verbose:
                        print(f"  ✅ {server_name}: {len(tools)} tools")
                
                except Exception as e:
                    reason = str(e).strip() or "discovery failed"
                    self.mcp_unavailable[server_name] = reason
                    if verbose:
                        print(f"  ⚠️ {server_name} unavailable (skipped): {reason[:120]}")
                    try:
                        client.stop()
                    except Exception:
                        pass
                finally:
                    if previous_auto_restart is not None:
                        client._auto_restart = previous_auto_restart
        
        except Exception as e:
            if verbose:
                print(f"✗ MCP discovery failed: {str(e)[:80]}")
    
    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool is an MCP tool."""
        return tool_name.startswith("mcp_")
    
    def get_mcp_info(self, tool_name: str) -> tuple:
        """
        Extract MCP server and tool name from full tool name.
        """
        if not self.is_mcp_tool(tool_name):
            return None, None
        
        # Format: mcp_{server_name}_{mcp_tool_name}
        # Server names can have underscores (e.g., "brave_search")
        # Match against registered MCP clients to find the correct split point
        remaining = tool_name[4:]  # Remove 'mcp_' prefix
        
        # CRITICAL: Try to match against registered server names (longest first)
        # This ensures "brave_search" is matched before "brave" if both existed
        for server_name in sorted(self.mcp_clients.keys(), key=len, reverse=True):
            if remaining.startswith(server_name + "_"):
                mcp_tool_name = remaining[len(server_name) + 1:]  # +1 for the underscore
                return server_name, mcp_tool_name
        
        # Fallback: split on first underscore (handles simple cases like "mcp_oldstyle_tool")
        parts = remaining.split("_", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return None, None

    def find_tools(
        self,
        query: str,
        limit: int = 5,
        similarity_threshold: float | None = None,
        typo_hint_source: str | None = None,
    ) -> list[ToolSchema]:
        """
        Find relevant tools with fused dense/FTS5 ranking and adaptive selection.
        Prioritizes GHOST_TOOLS before retrieved matches.

        The router may apply a final schema cap after this merge, so ghost
        tools are candidates for the final prompt rather than an unlimited
        append outside the Tool RAG budget.

        Args:
            query: Text to embed for similarity search.
            limit: Final schema ceiling used to bound adaptive candidates
                before ghost merge and any router final schema cap.
            similarity_threshold: Min cosine similarity for dense-only candidates.
                Strong lexical matches can also qualify. If None, uses
                TOOL_SIMILARITY_THRESHOLD from config (router may pass an explicit value).
            typo_hint_source: If set, typo/near-segment RAG hints consider only this text
                (typically the raw user request); ``query`` is still embedded in full with
                hints appended. If None, hint logic scans all of ``query``.
        """
        from config_loader import get_config_value, get_float
        from memory_db import get_memory_db
        
        # Get prioritized "ghost" tools from config (or use defaults).
        ghost_tools_str = get_config_value('GHOST_TOOLS', 'search_memory,semantic_recall,remember')
        CORE_TOOLS = _merged_ghost_tool_names(ghost_tools_str, set(self.tools.keys()))
        
        if similarity_threshold is None:
            similarity_threshold = get_float('TOOL_SIMILARITY_THRESHOLD', 0.0)
        threshold = similarity_threshold
        mandatory_count = sum(name in CORE_TOOLS for name in _MANDATORY_GHOST_TOOLS)
        dynamic_budget = max(
            1,
            min(_ADAPTIVE_DYNAMIC_TOOL_MAX, limit - mandatory_count),
        )
        self.last_tool_search_meta = {
            "retrieval_mode": "hybrid",
            "semantic_disabled_reason": None,
        }
        db = None

        try:
            db = get_memory_db()

            enabled_names = [
                t.name
                for t in self.tools.values()
                if t.permissions.get("enabled", True)
            ]
            rag_query, typo_hints = expand_tool_rag_query_for_typo_hints(
                query,
                enabled_names,
                hint_source=typo_hint_source,
            )
            if typo_hints:
                _logger.debug(
                    "[TOOL_RAG] typo_rag_hints=%s embedding_query_len=%s",
                    typo_hints,
                    len(rag_query),
                )

            # 1. Get relevant tools from vector search (embedding uses rag_query may include typo hints)
            # Retrieve a wider fused pool, then let the per-query score shape
            # choose how much of the non-ghost tail is worth sending. The final
            # router cap remains the hard ceiling.
            relevant_tools_data = db.search_tools(
                rag_query,
                limit=max(limit * 2, 16),
                threshold=threshold,
            )
            search_meta = getattr(db, "last_tool_search_meta", {})
            if isinstance(search_meta, dict):
                self.last_tool_search_meta = {
                    "retrieval_mode": search_meta.get("retrieval_mode", "hybrid"),
                    "semantic_disabled_reason": search_meta.get("semantic_disabled_reason"),
                    "dense_candidate_count": search_meta.get("dense_candidate_count", 0),
                    "keyword_candidate_count": search_meta.get("keyword_candidate_count", 0),
                    "fused_candidate_count": search_meta.get("fused_candidate_count", 0),
                }

            # A single embedding can collapse a longer multi-action request
            # around its strongest clause. Retrieve a maximum of three
            # structural clauses independently, keep only the tight top of
            # each, then apply the same global adaptive budget. No intent or
            # phrase-to-tool mapping is involved.
            compound_segments = query_segments(query)
            segment_rankings: list[tuple[str, list[dict[str, Any]]]] = []
            if (
                compound_segments
                and not self.last_tool_search_meta.get("semantic_disabled_reason")
            ):
                for segment in compound_segments:
                    try:
                        segment_rows = db.search_tools(
                            segment,
                            limit=max(dynamic_budget * 2, 8),
                            threshold=threshold,
                        )
                        segment_meta = getattr(db, "last_tool_search_meta", {})
                        if not (
                            isinstance(segment_meta, dict)
                            and segment_meta.get("semantic_disabled_reason")
                        ):
                            segment_rankings.append((segment, segment_rows))
                    except Exception as exc:
                        _logger.debug(
                            "[TOOL_RAG] compound segment retrieval skipped for %r: %s",
                            segment,
                            exc,
                        )

            relevant_tools_data, segment_meta = _merge_compound_segment_rankings(
                relevant_tools_data,
                segment_rankings,
            )
            relevant_tools_data, adaptive_meta = adaptive_rank_cutoff(
                relevant_tools_data,
                budget=dynamic_budget,
            )
            self.last_tool_search_meta["adaptive_selection"] = adaptive_meta
            self.last_tool_search_meta["compound_segments"] = compound_segments
            self.last_tool_search_meta["segment_searches"] = segment_meta
            self.last_tool_search_meta["segment_supported_tools"] = [
                row["name"]
                for row in relevant_tools_data
                if row.get("segment_queries")
            ]
            
            # 2. Collect retrieved tool names
            retrieved_names = [t['name'] for t in relevant_tools_data]
            
            # 3. PRIORITIZE Ghost Tools (add them FIRST for Memory-First visibility)
            # This ensures memory tools appear before action tools in the LLM's tool list
            found_names = []
            for core in CORE_TOOLS:
                if core in self.tools:
                    found_names.append(core)
            
            # 4. Add retrieved tools (if not already in ghost list)
            for name in retrieved_names:
                if name not in found_names:
                    found_names.append(name)
            
            # 5. Map back to ToolSchema objects (ghost tools first, then retrieved)
            final_tools = []
            for name in found_names:
                tool = self.get_tool(name)
                if tool:
                    final_tools.append(tool)
            
            return final_tools
            
        except Exception as e:
            self.last_tool_search_meta = {
                "retrieval_mode": "ghost_only",
                "semantic_disabled_reason": str(e),
            }
            print(f"⚠️ Semantic tool retrieval disabled: {e}. Using ghost tools only.")
            return [self.tools[name] for name in CORE_TOOLS if name in self.tools]
        finally:
            if db is not None:
                db.close()
    
    def cleanup(self):
        """Stop all MCP clients and release resources."""
        if hasattr(self, 'mcp_manager') and self.mcp_manager:
            try:
                self.mcp_manager.stop_all()
                print("🛑 MCP servers stopped")
            except Exception as e:
                print(f"Warning: MCP cleanup error: {e}")
        
        # Clear client references
        self.mcp_clients = {}


# ============================================================================
# SINGLETON PATTERN - Prevents duplicate MCP containers
# ============================================================================

_tool_registry_instance: ToolRegistry | None = None
_tool_registry_mode: str | None = None


def get_tool_registry(skills_dir: str = None, mcp_config_path: str = None, mode: str = None) -> ToolRegistry:
    """
    Get the shared ToolRegistry singleton.
    
    This prevents spawning duplicate MCP Docker containers when multiple
    Orchestrator instances are created (e.g., one per web UI message).
    
    Args:
        skills_dir: Path to skills directory (uses default if not provided)
        mcp_config_path: Path to MCP config (uses default if not provided)
        mode: 'cloud' or 'local' - if mode changes, registry is recreated
        
    Returns:
        Shared ToolRegistry instance
    """
    global _tool_registry_instance, _tool_registry_mode
    
    # Determine paths
    if not skills_dir or not mcp_config_path:
        from pathlib import Path
        project_root = Path(__file__).parent.parent
        skills_dir = skills_dir or str(project_root / "skills")
        mcp_config_path = mcp_config_path or str(project_root / "config" / "mcp-servers.json")
    
    # Check if we need to create or recreate the registry
    need_new = (
        _tool_registry_instance is None or 
        (mode is not None and mode != _tool_registry_mode)
    )
    
    if need_new:
        # Cleanup old instance if mode changed
        if _tool_registry_instance is not None:
            print(f"🔄 Mode changed ({_tool_registry_mode} → {mode}), recreating registry...")
            _tool_registry_instance.cleanup()
        
        _tool_registry_instance = ToolRegistry(skills_dir, mcp_config_path)
        _tool_registry_mode = mode
    
    return _tool_registry_instance


def reset_tool_registry():
    """
    Reset the singleton registry (e.g., when mode changes or for cleanup).
    """
    global _tool_registry_instance, _tool_registry_mode
    
    if _tool_registry_instance is not None:
        _tool_registry_instance.cleanup()
        _tool_registry_instance = None
        _tool_registry_mode = None
