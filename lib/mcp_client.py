#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Client
Communicates with MCP servers via JSON-RPC over stdin/stdout.
"""
import sys
import json
import subprocess
import time
from typing import Dict, Any, List, Optional
from threading import Lock


class MCPClient:
    """Client for communicating with MCP servers."""
    
    def __init__(self, name: str, command: str, args: List[str], env: Optional[Dict[str, str]] = None):
        """
        Initialize MCP client.
        
        Args:
            name: Server name (e.g., "duckduckgo")
            command: Command to start server (e.g., "docker")
            args: Arguments for command
            env: Environment variables
        """
        self.name = name
        self.command = command
        self.args = args
        self.env = env or {}
        self.process = None
        self.lock = Lock()
        self.request_id = 0
        self._tools_cache = None
    
    def start(self):
        """Start the MCP server process."""
        if self.process:
            return  # Already running
        
        # Merge environment variables
        full_env = {**os.environ, **self.env}
        
        # Start process
        self.process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=full_env
        )
        
        # Give it a moment to start
        time.sleep(0.2)
        
        # Check if it started successfully
        if self.process.poll() is not None:
            stderr = self.process.stderr.read()
            raise Exception(f"MCP server failed to start: {stderr}")
        
        # Initialize the MCP connection
        self._initialize()
    
    def stop(self):
        """Stop the MCP server process."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except:
                self.process.kill()
            finally:
                self.process = None
    
    def _initialize(self):
        """Initialize MCP connection with handshake (optional, some servers don't need it)."""
        try:
            # Send initialize request with short timeout
            result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "jarvis-voice",
                    "version": "1.0.0"
                }
            })
            
            # Send initialized notification
            self._send_notification("notifications/initialized")
            
        except Exception as e:
            # Many MCP servers work without explicit initialization
            # Just log and continue
            pass
    
    def _send_notification(self, method: str, params: Optional[Dict] = None):
        """Send JSON-RPC notification (no response expected)."""
        with self.lock:
            notification = {
                "jsonrpc": "2.0",
                "method": method
            }
            
            if params:
                notification["params"] = params
            
            notification_json = json.dumps(notification) + "\n"
            self.process.stdin.write(notification_json)
            self.process.stdin.flush()
    
    def _send_request(self, method: str, params: Optional[Dict] = None) -> Any:
        """
        Send JSON-RPC request to MCP server.
        
        Args:
            method: JSON-RPC method name
            params: Method parameters
            
        Returns:
            Response result
        """
        with self.lock:
            if not self.process:
                self.start()
            
            self.request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method
            }
            
            if params:
                request["params"] = params
            
            # Send request
            request_json = json.dumps(request) + "\n"
            self.process.stdin.write(request_json)
            self.process.stdin.flush()
            
            # Read response (may need to skip notifications)
            max_attempts = 10  # Avoid infinite loop
            timeout_seconds = 5  # Timeout per read attempt
            
            for attempt in range(max_attempts):
                # Use select to timeout on readline
                import select
                ready, _, _ = select.select([self.process.stdout], [], [], timeout_seconds)
                
                if not ready:
                    raise Exception(f"MCP server response timeout after {timeout_seconds}s")
                
                response_line = self.process.stdout.readline()
                
                if not response_line:
                    raise Exception(f"MCP server closed connection")
                
                # Debug: print raw response
                if os.environ.get("MCP_DEBUG"):
                    print(f"[MCP DEBUG] Raw response: {response_line.strip()}")
                
                response = json.loads(response_line)
                
                # Skip notifications, wait for actual response
                if "method" in response:
                    # This is a notification, not a response
                    if os.environ.get("MCP_DEBUG"):
                        print(f"[MCP DEBUG] Skipping notification: {response.get('method')}")
                    continue
                
                # Debug: print parsed response
                if os.environ.get("MCP_DEBUG"):
                    print(f"[MCP DEBUG] Parsed response: {json.dumps(response, indent=2)}")
                
                # Check for error
                if "error" in response:
                    error = response["error"]
                    raise Exception(f"MCP error: {error.get('message', 'Unknown error')}")
                
                # Check if this is our response (matching request ID)
                if response.get("id") == self.request_id:
                    return response.get("result")
            
            raise Exception("Did not receive response from MCP server after multiple attempts")
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """
        List available tools from MCP server.
        
        Returns:
            List of tool definitions
        """
        if self._tools_cache:
            return self._tools_cache
        
        try:
            result = self._send_request("tools/list")
            tools = result.get("tools", [])
            self._tools_cache = tools
            return tools
        except Exception as e:
            print(f"Error listing tools from MCP server {self.name}: {e}", file=sys.stderr)
            return []
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a tool on the MCP server.
        
        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            
        Returns:
            Tool result
        """
        try:
            # MCP protocol expects this format
            result = self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments
            })
            
            # Check if result has content
            if not result:
                return {
                    "ok": False,
                    "speech": f"MCP tool {tool_name} returned no result",
                    "error": "Empty result"
                }
            
            # Extract content from MCP response
            content = result.get("content", [])
            
            if not content:
                # Some MCP servers might return data differently
                return {
                    "ok": True,
                    "speech": str(result),
                    "data": {"raw": result}
                }
            
            # Combine text content
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    text_parts.append(item)
            
            combined_text = "\n".join(text_parts) if text_parts else str(content)
            
            return {
                "ok": True,
                "speech": combined_text[:500],  # Limit length for voice
                "data": {"raw": content, "full_text": combined_text}
            }
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"MCP tool error details: {error_detail}", file=sys.stderr)
            return {
                "ok": False,
                "speech": f"MCP tool {tool_name} failed",
                "error": str(e)
            }
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()


import os


class MCPManager:
    """Manages multiple MCP servers."""
    
    def __init__(self, config_path: str):
        """
        Initialize MCP manager.
        
        Args:
            config_path: Path to MCP servers config JSON
        """
        self.config_path = config_path
        self.servers: Dict[str, MCPClient] = {}
        self._load_config()
    
    def _load_config(self):
        """Load MCP servers from config file."""
        if not os.path.exists(self.config_path):
            return
        
        with open(self.config_path, 'r') as f:
            config = json.load(f)
        
        for name, server_config in config.get("mcpServers", {}).items():
            command = server_config.get("command")
            args = server_config.get("args", [])
            env = server_config.get("env", {})
            
            self.servers[name] = MCPClient(name, command, args, env)
    
    def get_server(self, name: str) -> Optional[MCPClient]:
        """Get MCP server by name."""
        return self.servers.get(name)
    
    def list_all_tools(self) -> Dict[str, List[Dict[str, Any]]]:
        """List tools from all MCP servers."""
        all_tools = {}
        for name, server in self.servers.items():
            tools = server.list_tools()
            if tools:
                all_tools[name] = tools
        return all_tools
    
    def stop_all(self):
        """Stop all MCP servers."""
        for server in self.servers.values():
            server.stop()

