#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Orchestrator Executor
Executes tools/skills and formats responses for TTS.
"""
import os
import sys
import json
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config
from tool_logger import get_logger


class ToolExecutor:
    """Executes tools and skills with permission checking."""
    
    def __init__(self, mode='cloud', registry=None):
        """
        Initialize executor.
        
        Args:
            mode: 'cloud' or 'local'
            registry: Optional shared ToolRegistry (prevents duplicate MCP servers)
        """
        self.mode = mode
        load_config(mode)
        self.project_root = Path(__file__).parent.parent.resolve()
        self.skills_dir = self.project_root / "skills"
        
        # Use provided registry or create new one
        if registry:
            self.registry = registry
        else:
            # Backward compatibility: create own registry
            sys.path.insert(0, str(self.project_root / "lib"))
            from tool_schema import ToolRegistry
            mcp_config = str(self.project_root / "config" / "mcp-servers.json")
            self.registry = ToolRegistry(str(self.skills_dir), mcp_config)
        
        # Initialize logger
        self.logger = get_logger(mode)
    
    def execute(self, tool_name: str, args: Dict[str, Any], skip_permission_check: bool = False) -> Dict[str, Any]:
        """
        Execute a tool/skill with permission checking.
        
        Args:
            tool_name: Name of the tool to execute
            args: Arguments to pass to the tool
            skip_permission_check: Skip permission validation (use with caution)
            
        Returns:
            dict: Tool result
            {
                "ok": True/False,
                "speech": "Text to speak",
                "data": {...} (optional),
                "requires_confirmation": bool (if permission check fails)
            }
        """
        # Get tool schema for permission check
        tool_schema = self.registry.get_tool(tool_name)
        
        if not tool_schema:
            return {
                "ok": False,
                "speech": f"Tool {tool_name} not found",
                "error": "Tool not found"
            }
        
        # Check permissions (unless explicitly skipped)
        if not skip_permission_check and tool_schema.requires_confirmation():
            # For voice control, we announce what we're about to do
            warning = tool_schema.get_permission_warning()
            # Only print if not in JSON mode (for voice scripts)
            if sys.stdout.isatty() or os.environ.get('JARVIS_JSON_MODE') != '1':
                print(f"⚠️  Permission check: {warning}", file=sys.stderr)
            
            # In future, could add verbal confirmation loop here
            # For now, we announce and proceed with caution
        
        # Check if this is an MCP tool
        if self.registry.is_mcp_tool(tool_name):
            return self._execute_mcp_tool(tool_name, args)
        
        # Get script path from schema
        tool_script = Path(tool_schema.script_path)
        
        if not tool_script.exists():
            return {
                "ok": False,
                "speech": f"Tool script not found at {tool_script}",
                "error": "Script not found"
            }
        
        # Execute tool
        start_time = time.time()
        try:
            input_json = json.dumps(args)
            
            # Determine command based on file extension
            if tool_script.suffix == '.py':
                # Run Python scripts with python3, passing JSON as argument
                cmd = ['python3', str(tool_script), input_json]
            else:
                # Run bash scripts or other executables directly
                cmd = [str(tool_script)]
            
            # Use longer timeout for local mode (Ollama can be slower)
            # OpenCode tasks need much more time (building, coding, etc.)
            # Ingest intel needs time for embedding generation
            if tool_name == "opencode":
                timeout = 360  # 6 minutes for OpenCode tasks (complex builds)
            elif tool_name == "ingest_intel":
                timeout = 60  # 1 minute for ingesting files with embeddings
            elif tool_name == "manage_intel":
                timeout = 60  # 1 minute (can auto-ingest, which needs time for embeddings)
            else:
                timeout = 30 if self.mode == "local" else 15
            
            result = subprocess.run(
                cmd,
                input=input_json if tool_script.suffix != '.py' else None,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.skills_dir
            )
            
            duration_ms = (time.time() - start_time) * 1000
            
            if result.returncode != 0:
                output = {
                    "ok": False,
                    "speech": f"Tool {tool_name} failed",
                    "error": result.stderr
                }
                # Log the failed execution
                self.logger.log_tool_call(
                    tool_name=tool_name,
                    arguments=args,
                    result=output,
                    duration_ms=duration_ms,
                    mode=self.mode
                )
                return output
            
            # Parse output
            output = json.loads(result.stdout)
            
            # Log successful execution
            self.logger.log_tool_call(
                tool_name=tool_name,
                arguments=args,
                result=output,
                duration_ms=duration_ms,
                mode=self.mode
            )
            
            return output
            
        except subprocess.TimeoutExpired:
            duration_ms = (time.time() - start_time) * 1000
            output = {
                "ok": False,
                "speech": f"Tool {tool_name} timed out",
                "error": "Timeout"
            }
            self.logger.log_tool_call(
                tool_name=tool_name,
                arguments=args,
                result=output,
                duration_ms=duration_ms,
                mode=self.mode
            )
            return output
        except json.JSONDecodeError as e:
            duration_ms = (time.time() - start_time) * 1000
            output = {
                "ok": False,
                "speech": f"Tool {tool_name} returned invalid JSON",
                "error": str(e)
            }
            self.logger.log_tool_call(
                tool_name=tool_name,
                arguments=args,
                result=output,
                duration_ms=duration_ms,
                mode=self.mode
            )
            return output
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            output = {
                "ok": False,
                "speech": f"Error executing {tool_name}",
                "error": str(e)
            }
            self.logger.log_tool_call(
                tool_name=tool_name,
                arguments=args,
                result=output,
                duration_ms=duration_ms,
                mode=self.mode
            )
            return output
    
    def _execute_mcp_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an MCP tool.
        
        Args:
            tool_name: Full MCP tool name (e.g., "mcp.duckduckgo.search")
            args: Tool arguments
            
        Returns:
            Tool result
        """
        start_time = time.time()
        
        try:
            # Extract server and tool names
            server_name, mcp_tool_name = self.registry.get_mcp_info(tool_name)
            
            if not server_name or not mcp_tool_name:
                return {
                    "ok": False,
                    "speech": f"Invalid MCP tool name: {tool_name}",
                    "error": "Invalid tool name format"
                }
            
            # Get MCP client (should be initialized at startup)
            mcp_client = self.registry.mcp_clients.get(server_name)
            
            if not mcp_client:
                return {
                    "ok": False,
                    "speech": f"MCP server {server_name} not available. Server may have failed to start.",
                    "error": "MCP server not connected"
                }
            
            # Execute tool via MCP
            result = mcp_client.call_tool(mcp_tool_name, args)
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Log execution
            self.logger.log_tool_call(
                tool_name=tool_name,
                arguments=args,
                result=result,
                duration_ms=duration_ms,
                mode=self.mode
            )
            
            return result
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            output = {
                "ok": False,
                "speech": f"MCP tool {tool_name} failed",
                "error": str(e)
            }
            self.logger.log_tool_call(
                tool_name=tool_name,
                arguments=args,
                result=output,
                duration_ms=duration_ms,
                mode=self.mode
            )
            return output


def main():
    """CLI interface for testing."""
    if len(sys.argv) < 3:
        print("Usage: executor.py <mode> <tool_name> [args_json]", file=sys.stderr)
        sys.exit(1)
    
    mode = sys.argv[1]
    tool_name = sys.argv[2]
    args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    
    executor = ToolExecutor(mode)
    result = executor.execute(tool_name, args)
    
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

