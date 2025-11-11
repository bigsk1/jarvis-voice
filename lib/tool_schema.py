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
    """Registry of all available tools."""
    
    def __init__(self, skills_dir: str):
        """
        Initialize tool registry.
        
        Args:
            skills_dir: Path to skills directory
        """
        self.skills_dir = Path(skills_dir)
        self.tools: Dict[str, ToolSchema] = {}
        self._discover_tools()
    
    def _discover_tools(self):
        """Auto-discover tools by finding .tool.json files."""
        import sys
        # Only print registration if stdout is a TTY (interactive mode)
        verbose = sys.stdout.isatty()
        
        for tool_file in self.skills_dir.glob("*.tool.json"):
            try:
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

