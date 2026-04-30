#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Client
Communicates with MCP servers via JSON-RPC over multiple transports:
- stdio: Local subprocess with stdin/stdout
- sse: Server-Sent Events over HTTP
- http: Streamable HTTP (JSON-RPC over HTTP POST)
"""
import sys
import os
import json
import subprocess
import time
import re
import queue
import requests
from typing import Any, Union
from threading import Lock, Thread, Event


class MCPClient:
    """Client for communicating with MCP servers."""
    
    # Crash recovery settings
    MAX_RESTART_ATTEMPTS = 3
    RESTART_COOLDOWN_SECONDS = 60  # After max restarts, wait before allowing more
    
    def __init__(self, name: str, command: str, args: list[str], env: dict[str, str] | None = None):
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
        
        # Crash recovery state
        self._restart_count = 0
        self._last_restart_time = 0
        self._in_cooldown = False

    def _force_restart(self, reason: str = "unknown"):
        """
        Hard-reset the MCP client process after a wedged/timeout call.
        This is more aggressive than normal crash recovery and is used
        when a request appears stuck.
        """
        try:
            print(f"🛠️ Force-restarting MCP {self.name}: {reason}", file=sys.stderr)
        except Exception:
            pass

        # Kill current process if present
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                    self.process.wait(timeout=2)
                except Exception:
                    pass

        # Reset in-memory state so future calls can proceed cleanly
        self.process = None
        self._tools_cache = None
        self.request_id = 0

        # Critical: replace lock in case a prior thread is stuck holding it
        self.lock = Lock()
    
    def _check_health(self) -> bool:
        """
        Check if MCP process is healthy and restart if crashed.
        
        Returns:
            True if healthy (or successfully restarted), False if in cooldown
        """
        if not self.process:
            return True  # Will be started on first use
        
        # Check if process is still running
        exit_code = self.process.poll()
        if exit_code is None:
            # Process is running, reset restart count on successful operation
            self._restart_count = 0
            return True
        
        # Process has died
        print(f"⚠️ MCP {self.name} crashed (exit code: {exit_code})", file=sys.stderr)
        
        # Check if we're in cooldown
        if self._in_cooldown:
            elapsed = time.time() - self._last_restart_time
            if elapsed < self.RESTART_COOLDOWN_SECONDS:
                remaining = int(self.RESTART_COOLDOWN_SECONDS - elapsed)
                print(f"🛑 MCP {self.name} in cooldown ({remaining}s remaining), skipping restart", file=sys.stderr)
                return False
            else:
                # Cooldown expired, reset
                self._in_cooldown = False
                self._restart_count = 0
        
        # Check restart limit
        if self._restart_count >= self.MAX_RESTART_ATTEMPTS:
            print(f"🛑 MCP {self.name} hit max restarts ({self.MAX_RESTART_ATTEMPTS}), entering cooldown", file=sys.stderr)
            self._in_cooldown = True
            self._last_restart_time = time.time()
            return False
        
        # Attempt restart
        self._restart_count += 1
        self._last_restart_time = time.time()
        print(f"🔄 Restarting MCP {self.name} (attempt {self._restart_count}/{self.MAX_RESTART_ATTEMPTS})...", file=sys.stderr)
        
        try:
            self.process = None
            self._tools_cache = None  # Clear cache on restart
            self.start()
            print(f"✅ MCP {self.name} restarted successfully", file=sys.stderr)
            return True
        except Exception as e:
            print(f"❌ MCP {self.name} restart failed: {e}", file=sys.stderr)
            return False
    
    def start(self):
        """Start the MCP server process."""
        if self.process:
            return  # Already running
        
        # Build environment with substitution
        # SECURITY: Only pass explicitly listed env vars, not the entire os.environ
        mcp_env = self._build_env_with_substitution()
        
        # Expand ${VAR} in args as well
        expanded_args = self._expand_args()
        
        # For Docker commands, add container naming to prevent duplicates
        if self.command == "docker" and "run" in expanded_args:
            container_name = f"jarvis-mcp-{self.name}"
            
            # Check if container with this name already exists (running or stopped)
            try:
                result = subprocess.run(
                    ["docker", "ps", "-aq", "--filter", f"name=^{container_name}$"],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip():
                    # Container exists - remove it (handles both running and stopped)
                    if os.environ.get("MCP_DEBUG", "").lower() == "true":
                        print(f"[MCP DEBUG] Removing existing container: {container_name}", file=sys.stderr)
                    subprocess.run(
                        ["docker", "rm", "-f", result.stdout.strip()],
                        capture_output=True, timeout=10
                    )
            except Exception as e:
                if os.environ.get("MCP_DEBUG", "").lower() == "true":
                    print(f"[MCP DEBUG] Container check failed: {e}", file=sys.stderr)
            
            # Inject --name after "run" in args
            run_idx = expanded_args.index("run")
            expanded_args = (
                expanded_args[:run_idx + 1] + 
                ["--name", container_name] + 
                expanded_args[run_idx + 1:]
            )
        
        # Start process
        self.process = subprocess.Popen(
            [self.command] + expanded_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=mcp_env
        )
        
        # Give it a moment to start
        time.sleep(0.2)
        
        # Check if it started successfully
        if self.process.poll() is not None:
            stderr = self.process.stderr.read()
            raise Exception(f"MCP server failed to start: {stderr}")
        
        # Initialize the MCP connection
        self._initialize()
    
    def _expand_args(self) -> list[str]:
        """
        Expand ${VAR_NAME} syntax in args from environment variables.
        
        This allows mcp-servers.json to use variables like:
            "--proxy-server", "${LOCAL_PROXY}"
        
        Returns:
            List of args with variables expanded
        """
        def replace_var(match):
            var_name = match.group(1)
            return os.environ.get(var_name, f"${{{var_name}}}")
        
        expanded = []
        for arg in self.args:
            if isinstance(arg, str) and '${' in arg:
                expanded.append(re.sub(r'\$\{([^}]+)\}', replace_var, arg))
            else:
                expanded.append(arg)
        return expanded
    
    def _build_env_with_substitution(self) -> dict[str, str]:
        """
        Build environment dict with variable substitution.
        
        Supports ${VAR_NAME} syntax to reference variables from:
        1. Parent environment (os.environ)
        2. Cloud/local .env files (already loaded into os.environ)
        
        SECURITY: Only passes explicitly listed variables, not entire os.environ.
        
        Example:
            "env": {"API_KEY": "${WEATHER_API_KEY}"}
            → API_KEY will be set to the value of WEATHER_API_KEY from .env
        
        Returns:
            Dict with substituted values
        """
        result = {}
        
        for key, value in self.env.items():
            if isinstance(value, str):
                # Substitute ${VAR_NAME} with actual value from environment
                def replace_var(match):
                    var_name = match.group(1)
                    return os.environ.get(var_name, f"${{{var_name}}}")  # Keep ${} if not found
                
                substituted_value = re.sub(r'\$\{([^}]+)\}', replace_var, value)
                result[key] = substituted_value
            else:
                result[key] = str(value)
        
        return result
    
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
        
        # For Docker commands, also explicitly stop the named container
        if self.command == "docker":
            container_name = f"jarvis-mcp-{self.name}"
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    capture_output=True, timeout=10
                )
            except:
                pass  # Ignore errors - container may already be gone
    
    def _initialize(self):
        """Initialize MCP connection with handshake (optional, some servers don't need it)."""
        try:
            # Send initialize request with short timeout
            self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "jarvis-voice",
                    "version": "1.0.0"
                }
            })
            
            # Send initialized notification
            self._send_notification("notifications/initialized")
            
        except Exception:
            # Many MCP servers work without explicit initialization
            # Just log and continue
            pass
    
    def _send_notification(self, method: str, params: dict | None = None):
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
    
    def _send_request(self, method: str, params: dict | None = None) -> Any:
        """
        Send JSON-RPC request to MCP server.
        
        Args:
            method: JSON-RPC method name
            params: Method parameters
            
        Returns:
            Response result
        """
        # IMPORTANT: Never call start() while holding self.lock.
        # start() performs MCP initialize -> _send_request(), and taking
        # the same non-reentrant lock here causes a deadlock on first call.
        if not self._check_health():
            raise Exception(f"MCP server {self.name} is in cooldown after repeated crashes")
        
        if not self.process:
            self.start()
        
        with self.lock:
            # Process may have changed after startup/restart checks.
            if not self._check_health():
                raise Exception(f"MCP server {self.name} is in cooldown after repeated crashes")
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
            timeout_seconds = 8  # Timeout per read attempt - was 5 increased to 8 for more time allowed for MCP servers to respond
            
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
                if os.environ.get("MCP_DEBUG", "").lower() == "true":
                    print(f"[MCP DEBUG] Raw response: {response_line.strip()}", file=sys.stderr)
                
                response = json.loads(response_line)
                
                # Skip notifications, wait for actual response
                if "method" in response:
                    # This is a notification, not a response
                    if os.environ.get("MCP_DEBUG", "").lower() == "true":
                        print(f"[MCP DEBUG] Skipping notification: {response.get('method')}", file=sys.stderr)
                    continue
                
                # Debug: print parsed response
                if os.environ.get("MCP_DEBUG", "").lower() == "true":
                    print(f"[MCP DEBUG] Parsed response: {json.dumps(response, indent=2)}", file=sys.stderr)
                
                # Check for error
                if "error" in response:
                    error = response["error"]
                    raise Exception(f"MCP error: {error.get('message', 'Unknown error')}")
                
                # Check if this is our response (matching request ID)
                if response.get("id") == self.request_id:
                    return response.get("result")
            
            raise Exception("Did not receive response from MCP server after multiple attempts")
    
    def list_tools(self) -> list[dict[str, Any]]:
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
    
    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool on the MCP server.
        
        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            
        Returns:
            Tool result
        """
        timeout_seconds = int(os.environ.get("MCP_TOOL_CALL_TIMEOUT_SECONDS", "35"))
        response_holder: dict[str, Any] = {}

        def _runner():
            try:
                # MCP protocol expects this format
                response_holder["result"] = self._send_request("tools/call", {
                    "name": tool_name,
                    "arguments": arguments
                })
            except Exception as e:
                response_holder["error"] = e

        worker = Thread(target=_runner, daemon=True)
        worker.start()
        worker.join(timeout=timeout_seconds)

        if worker.is_alive():
            self._force_restart(f"tools/call timeout ({timeout_seconds}s)")
            return {
                "ok": False,
                "speech": f"MCP tool {tool_name} timed out",
                "error": f"MCP tools/call timed out after {timeout_seconds}s; server restarted"
            }

        try:
            if "error" in response_holder:
                err = response_holder["error"]
                err_text = str(err)
                if "timeout" in err_text.lower():
                    self._force_restart(f"tools/call error timeout: {err_text[:120]}")
                raise err

            result = response_holder.get("result")
            
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


class MCPRemoteClient:
    """
    Client for communicating with remote MCP servers via SSE or HTTP transport.
    
    Supports:
    - SSE (Server-Sent Events): Bidirectional via SSE stream + HTTP POST  
    - HTTP (Streamable HTTP): JSON-RPC over HTTP POST with session management
    
    For Streamable HTTP (type="http"):
    - Initialize request is sent WITHOUT session ID
    - Server returns session ID in Mcp-Session-Id header
    - Subsequent requests MUST include the session ID header
    
    SECURITY: This client follows the same security model as MCPClient (stdio):
    - Only EXPLICITLY configured headers are sent to the remote server
    - No environment variables are passed unless explicitly mapped in config
    - The entire os.environ is NEVER exposed to remote servers
    
    Example secure config:
        "headers": {"Authorization": "Bearer ${MY_API_KEY}"}
        → Only MY_API_KEY is substituted, nothing else is exposed
    """
    
    def __init__(self, name: str, url: str, transport_type: str, headers: dict[str, str] | None = None):
        """
        Initialize remote MCP client.
        
        Args:
            name: Server name (e.g., "coingecko")
            url: Base URL for the MCP server
            transport_type: "sse" or "http"
            headers: Optional HTTP headers (e.g., for API keys)
                     SECURITY: Only these explicit headers are sent - no os.environ leakage
        """
        self.name = name
        self.url = url.rstrip('/')
        self.transport_type = transport_type
        self.headers = headers or {}
        self.lock = Lock()
        self.request_id = 0
        self._tools_cache = None
        self._initialized = False
        
        # Session management for Streamable HTTP
        self._session_id = None
        
        # SSE-specific attributes (for type="sse")
        self._sse_endpoint = None  # POST endpoint for sending messages
        self._sse_response_queue = queue.Queue()
        self._sse_thread = None
        self._sse_stop_event = Event()
        self._sse_connected = Event()

    def _force_restart(self, reason: str = "unknown"):
        """
        Hard-reset remote MCP client state after timeout/wedge.
        """
        try:
            print(f"🛠️ Force-restarting remote MCP {self.name}: {reason}", file=sys.stderr)
        except Exception:
            pass

        try:
            self.stop()
        except Exception:
            pass

        # Critical: replace lock in case a prior request thread is wedged
        self.lock = Lock()
        self.request_id = 0
    
    def start(self):
        """Start the remote MCP connection."""
        if self._initialized:
            return
        
        if self.transport_type == "sse":
            self._start_sse()
        elif self.transport_type == "http":
            self._initialize_http()
        
        self._initialized = True
    
    def _start_sse(self):
        """Start SSE connection in a background thread."""
        self._sse_stop_event.clear()
        self._sse_thread = Thread(target=self._sse_listener, daemon=True)
        self._sse_thread.start()
        
        # Wait for connection with timeout
        if not self._sse_connected.wait(timeout=10):
            raise Exception(f"SSE connection timeout for {self.name}")
        
        # Initialize the MCP connection
        self._initialize_mcp()
    
    def _sse_listener(self):
        """Background thread to listen for SSE events."""
        try:
            headers = {
                'Accept': 'text/event-stream',
                'Cache-Control': 'no-cache',
                **self.headers
            }
            
            response = requests.get(self.url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            event_type = None
            event_data = []
            
            for line in response.iter_lines(decode_unicode=True):
                if self._sse_stop_event.is_set():
                    break
                
                if line is None:
                    continue
                
                # Parse SSE format
                if line.startswith('event:'):
                    event_type = line[6:].strip()
                elif line.startswith('data:'):
                    event_data.append(line[5:].strip())
                elif line == '':
                    # End of event
                    if event_data:
                        data = '\n'.join(event_data)
                        self._handle_sse_event(event_type, data)
                        event_data = []
                        event_type = None
                        
        except Exception as e:
            if os.environ.get("MCP_DEBUG", "").lower() == "true":
                print(f"[MCP DEBUG] SSE listener error: {e}", file=sys.stderr)
            self._sse_response_queue.put({"error": str(e)})
    
    def _handle_sse_event(self, event_type: str | None, data: str):
        """Handle incoming SSE event."""
        if os.environ.get("MCP_DEBUG", "").lower() == "true":
            print(f"[MCP DEBUG] SSE event: {event_type} - {data[:200]}", file=sys.stderr)
        
        if event_type == 'endpoint':
            # Server is telling us where to POST messages
            self._sse_endpoint = data.strip()
            # Handle relative URLs
            if self._sse_endpoint.startswith('/'):
                # Extract base URL
                from urllib.parse import urlparse
                parsed = urlparse(self.url)
                self._sse_endpoint = f"{parsed.scheme}://{parsed.netloc}{self._sse_endpoint}"
            self._sse_connected.set()
        elif event_type == 'message' or event_type is None:
            # JSON-RPC response
            try:
                parsed = json.loads(data)
                self._sse_response_queue.put(parsed)
            except json.JSONDecodeError:
                if os.environ.get("MCP_DEBUG", "").lower() == "true":
                    print(f"[MCP DEBUG] Invalid JSON in SSE: {data}", file=sys.stderr)
    
    def _initialize_http(self):
        """
        Initialize Streamable HTTP transport connection.
        
        For Streamable HTTP:
        1. Send initialize request WITHOUT session ID
        2. Server returns session ID in Mcp-Session-Id response header
        3. Store session ID for subsequent requests
        """
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
            **self.headers
        }
        
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "jarvis-voice",
                    "version": "1.0.0"
                }
            }
        }
        
        if os.environ.get("MCP_DEBUG", "").lower() == "true":
            print(f"[MCP DEBUG] HTTP Initialize: {json.dumps(request)}", file=sys.stderr)
        
        response = requests.post(
            self.url,
            json=request,
            headers=headers,
            timeout=30,
            stream=True
        )
        response.raise_for_status()
        
        # Extract session ID from response headers
        self._session_id = response.headers.get('Mcp-Session-Id')
        
        if os.environ.get("MCP_DEBUG", "").lower() == "true":
            print(f"[MCP DEBUG] Got session ID: {self._session_id}", file=sys.stderr)
        
        # Consume the SSE response (initialization result)
        for line in response.iter_lines(decode_unicode=True):
            if os.environ.get("MCP_DEBUG") and line:
                print(f"[MCP DEBUG] Init response: {line}", file=sys.stderr)
        
        self.request_id = 1  # We used ID 1 for initialize
        
        # Send initialized notification
        self._send_notification("notifications/initialized")
    
    def _initialize_mcp(self):
        """Send MCP initialization handshake (for SSE transport)."""
        try:
            self._send_request("initialize", {
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
            if os.environ.get("MCP_DEBUG", "").lower() == "true":
                print(f"[MCP DEBUG] MCP init failed (may be ok): {e}", file=sys.stderr)
    
    def _send_notification(self, method: str, params: dict | None = None):
        """Send JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method
        }
        if params:
            notification["params"] = params
        
        self._post_message(notification)
    
    def _send_request(self, method: str, params: dict | None = None) -> Any:
        """Send JSON-RPC request and wait for response."""
        with self.lock:
            if not self._initialized and method != "initialize":
                self.start()
            
            self.request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method
            }
            if params:
                request["params"] = params
            
            if os.environ.get("MCP_DEBUG", "").lower() == "true":
                print(f"[MCP DEBUG] Sending: {json.dumps(request)}", file=sys.stderr)
            
            if self.transport_type == "sse":
                return self._send_sse_request(request)
            else:
                return self._send_http_request(request)
    
    def _send_sse_request(self, request: dict, retry_count: int = 0) -> Any:
        """Send request via SSE transport (POST to endpoint, receive via stream)."""
        if not self._sse_endpoint:
            raise Exception(f"SSE endpoint not established for {self.name}")
        
        # Clear queue of old responses
        while not self._sse_response_queue.empty():
            try:
                self._sse_response_queue.get_nowait()
            except queue.Empty:
                break
        
        # POST the request
        headers = {
            'Content-Type': 'application/json',
            **self.headers
        }
        
        try:
            response = requests.post(
                self._sse_endpoint,
                json=request,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            # Stale SSE session (400 + session/transport wording); reconnect once
            if e.response.status_code == 400 and retry_count < 1:
                error_text = e.response.text if hasattr(e.response, 'text') else ''
                if 'session' in error_text.lower() or 'transport' in error_text.lower():
                    if os.environ.get("MCP_DEBUG", "").lower() == "true":
                        print(f"[MCP DEBUG] Stale SSE session detected for {self.name}, reconnecting...", file=sys.stderr)
                    # Reconnect SSE
                    self._reconnect_sse()
                    # Retry the request once
                    return self._send_sse_request(request, retry_count=1)
            raise
        
        # Wait for response from SSE stream
        return self._wait_for_sse_response(request)
    
    def _reconnect_sse(self):
        """Reconnect the SSE connection (for stale session recovery)."""
        # Stop existing connection
        self._sse_stop_event.set()
        if self._sse_thread and self._sse_thread.is_alive():
            self._sse_thread.join(timeout=2)
        
        # Reset state
        self._sse_endpoint = None
        self._sse_connected.clear()
        self._initialized = False
        
        # Restart
        self._start_sse()
    
    def _wait_for_sse_response(self, request: dict) -> Any:
        """Wait for response from SSE stream after sending a request."""
        try:
            result = self._sse_response_queue.get(timeout=30)
            
            if "error" in result and "id" not in result:
                raise Exception(f"SSE error: {result['error']}")
            
            if result.get("id") == request["id"]:
                if "error" in result:
                    raise Exception(f"MCP error: {result['error'].get('message', 'Unknown')}")
                return result.get("result")
            
        except queue.Empty:
            raise Exception(f"Timeout waiting for SSE response from {self.name}")
        
        return None
    
    def _send_http_request(self, request: dict) -> Any:
        """
        Send request via Streamable HTTP transport.
        
        Session ID is required for all requests after initialization.
        Response can be either JSON or SSE (server decides).
        """
        headers = {
            'Content-Type': 'application/json',
            # MCP Streamable HTTP requires accepting both JSON and SSE
            'Accept': 'application/json, text/event-stream',
            **self.headers
        }
        
        # Include session ID for all requests after initialization
        if self._session_id:
            headers['Mcp-Session-Id'] = self._session_id
        
        if os.environ.get("MCP_DEBUG", "").lower() == "true":
            print(f"[MCP DEBUG] HTTP Request: {json.dumps(request)}", file=sys.stderr)
            print(f"[MCP DEBUG] Session ID: {self._session_id}", file=sys.stderr)
        
        response = requests.post(
            self.url,
            json=request,
            headers=headers,
            timeout=30,
            stream=True  # Enable streaming for potential SSE responses
        )
        response.raise_for_status()
        
        # Check content type to determine response format
        content_type = response.headers.get('Content-Type', '')
        
        if 'text/event-stream' in content_type:
            # Parse SSE response
            result = self._parse_sse_response(response)
        else:
            # Parse JSON response
            result = response.json()
        
        if os.environ.get("MCP_DEBUG", "").lower() == "true":
            print(f"[MCP DEBUG] HTTP response: {json.dumps(result, indent=2)}", file=sys.stderr)
        
        if "error" in result:
            raise Exception(f"MCP error: {result['error'].get('message', 'Unknown')}")
        
        return result.get("result")
    
    def _parse_sse_response(self, response) -> dict:
        """
        Parse SSE (Server-Sent Events) response from Streamable HTTP.
        
        The response may contain multiple events, we want the final JSON-RPC result.
        """
        result = None
        event_data = []
        
        for line in response.iter_lines(decode_unicode=True):
            if line is None:
                continue
            
            if line.startswith('event:'):
                line[6:].strip()
            elif line.startswith('data:'):
                event_data.append(line[5:].strip())
            elif line == '':
                # End of event - process it
                if event_data:
                    data = '\n'.join(event_data)
                    try:
                        parsed = json.loads(data)
                        # Keep the last valid JSON-RPC response
                        if 'id' in parsed or 'result' in parsed or 'error' in parsed:
                            result = parsed
                    except json.JSONDecodeError:
                        pass
                    event_data = []
        
        # Handle any remaining data
        if event_data:
            data = '\n'.join(event_data)
            try:
                parsed = json.loads(data)
                if 'id' in parsed or 'result' in parsed or 'error' in parsed:
                    result = parsed
            except json.JSONDecodeError:
                pass
        
        if result is None:
            raise Exception("No valid JSON-RPC response in SSE stream")
        
        return result
    
    def _post_message(self, message: dict):
        """Post a message without waiting for response."""
        if self.transport_type == "sse" and self._sse_endpoint:
            endpoint = self._sse_endpoint
        else:
            endpoint = self.url
        
        headers = {
            'Content-Type': 'application/json',
            **self.headers
        }
        
        try:
            requests.post(endpoint, json=message, headers=headers, timeout=10)
        except Exception as e:
            if os.environ.get("MCP_DEBUG", "").lower() == "true":
                print(f"[MCP DEBUG] Post notification failed: {e}", file=sys.stderr)
    
    def stop(self):
        """Stop the remote MCP connection."""
        self._sse_stop_event.set()
        if self._sse_thread and self._sse_thread.is_alive():
            self._sse_thread.join(timeout=2)
        self._initialized = False
        self._session_id = None
        self._sse_endpoint = None
        self._sse_connected.clear()
        self._tools_cache = None
    
    def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from remote MCP server."""
        if self._tools_cache:
            return self._tools_cache
        
        try:
            result = self._send_request("tools/list")
            tools = result.get("tools", []) if result else []
            self._tools_cache = tools
            return tools
        except Exception as e:
            print(f"Error listing tools from remote MCP server {self.name}: {e}", file=sys.stderr)
            return []
    
    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the remote MCP server."""
        timeout_seconds = int(os.environ.get("MCP_TOOL_CALL_TIMEOUT_SECONDS", "35"))
        response_holder: dict[str, Any] = {}

        def _runner():
            try:
                response_holder["result"] = self._send_request("tools/call", {
                    "name": tool_name,
                    "arguments": arguments
                })
            except Exception as e:
                response_holder["error"] = e

        worker = Thread(target=_runner, daemon=True)
        worker.start()
        worker.join(timeout=timeout_seconds)

        if worker.is_alive():
            self._force_restart(f"remote tools/call timeout ({timeout_seconds}s)")
            return {
                "ok": False,
                "speech": f"MCP tool {tool_name} timed out",
                "error": f"Remote MCP tools/call timed out after {timeout_seconds}s; client restarted"
            }

        try:
            if "error" in response_holder:
                err = response_holder["error"]
                err_text = str(err)
                if "timeout" in err_text.lower():
                    self._force_restart(f"remote tools/call error timeout: {err_text[:120]}")
                raise err

            result = response_holder.get("result")
            
            if not result:
                return {
                    "ok": False,
                    "speech": f"MCP tool {tool_name} returned no result",
                    "error": "Empty result"
                }
            
            # Extract content from MCP response
            content = result.get("content", [])
            
            if not content:
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
                "speech": combined_text[:500],
                "data": {"raw": content, "full_text": combined_text}
            }
            
        except Exception as e:
            import traceback
            if os.environ.get("MCP_DEBUG", "").lower() == "true":
                print(f"MCP remote tool error: {traceback.format_exc()}", file=sys.stderr)
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


class MCPManager:
    """Manages multiple MCP servers (stdio, SSE, and HTTP transports)."""
    
    def __init__(self, config_path: str):
        """
        Initialize MCP manager.
        
        Args:
            config_path: Path to MCP servers config JSON
        """
        self.config_path = config_path
        self.servers: dict[str, Union[MCPClient, MCPRemoteClient]] = {}
        self._load_config()
    
    def _load_config(self):
        """
        Load MCP servers from config file.
        
        Supports multiple transport types:
        - stdio: Local subprocess (command + args)
        - sse: Server-Sent Events (url + type: "sse")
        - http: Streamable HTTP (url + type: "http")
        
        Config examples:
        
        stdio (existing format):
        {
            "brave_search": {
                "command": "docker",
                "args": ["run", "-i", "mcp/brave-search"],
                "env": {"API_KEY": "${BRAVE_API_KEY}"}
            }
        }
        
        SSE (new format):
        {
            "coingecko": {
                "type": "sse",
                "url": "https://mcp.api.coingecko.com/sse",
                "headers": {"X-API-Key": "${COINGECKO_API_KEY}"}
            }
        }
        
        HTTP (new format):
        {
            "some_api": {
                "type": "http",
                "url": "https://api.example.com/mcp",
                "headers": {}
            }
        }
        """
        if not os.path.exists(self.config_path):
            return
        
        with open(self.config_path, 'r') as f:
            config = json.load(f)
        
        for name, server_config in config.get("mcpServers", {}).items():
            # Skip disabled servers
            if not server_config.get("enabled", True):
                continue
            
            transport_type = server_config.get("type", "").lower()
            
            if transport_type in ("sse", "http"):
                # Remote MCP server (SSE or HTTP transport)
                url = server_config.get("url")
                if not url:
                    print(f"Warning: MCP server '{name}' has type={transport_type} but no url", file=sys.stderr)
                    continue
                
                # Process headers with environment variable substitution
                raw_headers = server_config.get("headers", {})
                headers = self._substitute_env_vars(raw_headers)
                
                self.servers[name] = MCPRemoteClient(name, url, transport_type, headers)
                
                if os.environ.get("MCP_DEBUG", "").lower() == "true":
                    print(f"[MCP DEBUG] Loaded remote server: {name} ({transport_type}) -> {url}", file=sys.stderr)
            
            elif "command" in server_config:
                # Local MCP server (stdio transport)
                command = server_config.get("command")
                args = server_config.get("args", [])
                env = server_config.get("env", {})
                
                self.servers[name] = MCPClient(name, command, args, env)
                
                if os.environ.get("MCP_DEBUG", "").lower() == "true":
                    print(f"[MCP DEBUG] Loaded stdio server: {name} -> {command}", file=sys.stderr)
            
            else:
                print(f"Warning: MCP server '{name}' has unknown config (need 'command' or 'type'+'url')", file=sys.stderr)
    
    def _substitute_env_vars(self, data: dict[str, str]) -> dict[str, str]:
        """
        Substitute ${VAR_NAME} placeholders with environment variable values.
        
        SECURITY: This method only substitutes values for keys that are
        EXPLICITLY defined in the input dict. It does NOT pass the entire
        os.environ to any server. This prevents accidental exposure of
        sensitive environment variables (SSH keys, API tokens, etc.).
        
        Example:
            Input:  {"Authorization": "Bearer ${MY_API_KEY}"}
            Output: {"Authorization": "Bearer actual-key-value"}
            
            Only MY_API_KEY is read from os.environ, nothing else.
        
        Args:
            data: Dict with potential ${VAR} placeholders
            
        Returns:
            Dict with substituted values (only for explicitly defined keys)
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                def replace_var(match):
                    var_name = match.group(1)
                    return os.environ.get(var_name, f"${{{var_name}}}")
                
                result[key] = re.sub(r'\$\{([^}]+)\}', replace_var, value)
            else:
                result[key] = str(value)
        return result
    
    def get_server(self, name: str) -> MCPClient | None:
        """Get MCP server by name."""
        return self.servers.get(name)
    
    def list_all_tools(self) -> dict[str, list[dict[str, Any]]]:
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

