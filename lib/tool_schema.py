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

from tool_rag_typo_hints import expand_tool_rag_query_for_typo_hints

_logger = logging.getLogger(__name__)


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
        "allOf", "anyOf", "oneOf", "not",
        "if", "then", "else", "dependentSchemas"
    }

    sanitized: dict[str, Any] = {}
    for key, value in schema.items():
        if key in unsupported_keys:
            continue
        if is_root and key == "enum":
            continue
        sanitized[key] = _sanitize_schema_for_openai(value, is_root=False)

    if is_root:
        sanitized.setdefault("type", "object")
        sanitized.setdefault("properties", {})

    return sanitized


class ToolSchema:
    """Defines a tool's capabilities in a provider-agnostic way."""
    
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        script_path: str,
        permissions: dict[str, Any] | None = None
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
        
        return cls(
            name=data["name"],
            description=data["description"],
            parameters=data.get("parameters", {"type": "object", "properties": {}}),
            script_path=script_path,
            permissions=data.get("permissions", None)
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
        self.skills_dir = Path(skills_dir)
        self.mcp_config_path = mcp_config_path
        self.tools: dict[str, ToolSchema] = {}
        self.mcp_clients: dict[str, Any] = {}
        self.mcp_manager = None
        
        # Discover MCP tools FIRST (before local tools)
        if mcp_config_path and os.path.exists(mcp_config_path):
            self._discover_mcp_tools()
        
        # Then discover local tools
        self._discover_tools()
    
    def _discover_tools(self):
        """Auto-discover tools by finding .tool.json files."""
        import sys
        from config_loader import get_config_value
        
        # Only print registration if stdout is a TTY and not in JSON mode
        verbose = sys.stdout.isatty() and not os.environ.get('JARVIS_JSON_MODE')
        
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
                # Read tool config to check if enabled
                with open(tool_file, 'r') as f:
                    tool_config = json.load(f)
                
                # Check if tool is enabled (defaults to True for backward compatibility)
                if not tool_config.get('enabled', True):
                    if verbose:
                        print(f"⊝ Skipping {tool_config.get('name', tool_file.stem)} (disabled)")
                    continue
                
                # Legacy: Skip opencode tool if disabled in config
                if tool_file.stem == 'opencode' and not opencode_enabled:
                    if verbose:
                        print(f"⊝ Skipping opencode tool (disabled in config)")
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
                
                try:
                    if verbose:
                        print(f"  ⏳ Starting {server_name}...")
                    client.start()
                    enabled_servers.append((server_name, client))
                    if verbose:
                        print(f"  ✓ {server_name} started")
                except Exception as e:
                    if verbose:
                        print(f"  ✗ {server_name} failed to start: {str(e)[:60]}")
            
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
            
            for server_name, client in enabled_servers_sorted:
                try:
                    # Get tools from started server
                    tools = client.list_tools()
                    
                    if not tools:
                        if verbose:
                            print(f"  ⚠️  {server_name}: no tools")
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
                            }
                        )
                        
                        self.tools[tool_name] = schema
                    
                    if verbose:
                        print(f"  ✅ {server_name}: {len(tools)} tools")
                
                except Exception as e:
                    if verbose:
                        print(f"  ✗ {server_name}: {str(e)[:60]}")
                    # Clean up failed client
                    try:
                        client.stop()
                    except:
                        pass
        
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
        Find relevant tools for a user query using vector search.
        Always includes GHOST_TOOLS (configured core tools).

        Args:
            query: Text to embed for similarity search.
            limit: Max retrieved tools (before merging ghost list).
            similarity_threshold: Min cosine similarity to keep a tool. If None, uses
                TOOL_SIMILARITY_THRESHOLD from config (router may pass an explicit value).
            typo_hint_source: If set, typo/near-segment RAG hints consider only this text
                (typically the raw user request); ``query`` is still embedded in full with
                hints appended. If None, hint logic scans all of ``query``.
        """
        from memory_db import get_memory_db
        from config_loader import get_config_value, get_float
        
        # Get Core "Ghost" Tools from config (or use defaults)
        # These ensure basic functionality never fails
        ghost_tools_str = get_config_value('GHOST_TOOLS', 'search_memory,semantic_recall,remember')
        CORE_TOOLS = [t.strip() for t in ghost_tools_str.split(',')]
        
        if similarity_threshold is None:
            similarity_threshold = get_float('TOOL_SIMILARITY_THRESHOLD', 0.0)
        threshold = similarity_threshold
        
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
            relevant_tools_data = db.search_tools(rag_query, limit=limit, threshold=threshold)
            
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
            
            # Close DB connection
            db.close()
            
            return final_tools
            
        except Exception as e:
            print(f"⚠️ Tool retrieval failed: {e}. Falling back to ALL enabled tools.")
            # Fallback: return all enabled tools
            return [t for t in self.tools.values() if t.permissions.get('enabled', True)]
    
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


