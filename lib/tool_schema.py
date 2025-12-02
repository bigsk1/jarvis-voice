#!/usr/bin/env python3
"""
Tool Schema and Registry System
Universal tool definition that works across all LLM providers.
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional


class ToolSchema:
    """Defines a tool's capabilities in a provider-agnostic way."""
    
    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        script_path: str,
        permissions: Optional[Dict[str, Any]] = None
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
    
    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
    
    def to_anthropic_format(self) -> Dict[str, Any]:
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
    
    def __init__(self, skills_dir: str, mcp_config_path: Optional[str] = None):
        """
        Initialize tool registry.
        
        Args:
            skills_dir: Path to skills directory
            mcp_config_path: Path to MCP servers config (optional)
        """
        self.skills_dir = Path(skills_dir)
        self.mcp_config_path = mcp_config_path
        self.tools: Dict[str, ToolSchema] = {}
        self.mcp_clients: Dict[str, Any] = {}
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
    
    def get_tool(self, name: str) -> Optional[ToolSchema]:
        """Get tool by name."""
        return self.tools.get(name)
    
    def list_tools(self) -> List[str]:
        """List all tool names."""
        return list(self.tools.keys())
    
    def to_openai_format(self) -> List[Dict[str, Any]]:
        """Get all tools in OpenAI format."""
        return [tool.to_openai_format() for tool in self.tools.values()]
    
    def to_anthropic_format(self) -> List[Dict[str, Any]]:
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

    def find_tools(self, query: str, limit: int = 5) -> List[ToolSchema]:
        """
        Find relevant tools for a user query using vector search.
        Always includes GHOST_TOOLS (configured core tools).
        """
        from memory_db import get_memory_db
        from config_loader import get_config_value, get_float
        
        # Get Core "Ghost" Tools from config (or use defaults)
        # These ensure basic functionality never fails
        ghost_tools_str = get_config_value('GHOST_TOOLS', 'search_memory,semantic_recall,remember,check_tool_logs,get_recent_conversations,get_time')
        CORE_TOOLS = [t.strip() for t in ghost_tools_str.split(',')]
        
        # Get similarity threshold from config
        threshold = get_float('TOOL_SIMILARITY_THRESHOLD', 0.0)
        
        try:
            db = get_memory_db()
            
            # 1. Get relevant tools from vector search
            relevant_tools_data = db.search_tools(query, limit=limit, threshold=threshold)
            
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



