#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Client
Communicates with MCP servers via JSON-RPC over multiple transports:
- stdio: Local subprocess with stdin/stdout
- sse: Server-Sent Events over HTTP
- http: Streamable HTTP (JSON-RPC over HTTP POST)
"""
import json
import os
import queue
import re
import subprocess
import sys
import time
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from threading import Event, Lock, RLock, Thread
from typing import Any, Union
from uuid import uuid4

import requests
from config_loader import get_config_value
from http_client import (
    STANDARD_PROXY_ENV_KEYS,
    _bounded_request_timeout,
    get_proxy_url_chain,
    http_request,
    normalize_proxy_policy,
    select_reachable_proxy_url,
    standard_proxy_environment,
)
from mcp_docker import owner_labels, reap_orphans


def server_configuration_status(server_config: dict) -> tuple[bool, str]:
    """Check selected-mode gates without starting a server or exposing values."""
    if not server_config.get("enabled", True):
        return False, "disabled in config"
    gate = server_config.get("enabled_env")
    if gate and str(get_config_value(gate, "false")).strip().lower() not in {"1", "true", "yes", "on"}:
        return False, "enable flag is off"
    required = server_config.get("required_env", [])
    if not isinstance(required, list) or not all(isinstance(key, str) and key.strip() for key in required):
        return False, "invalid required_env"
    missing = [key for key in required if not get_config_value(key, None)]
    if missing:
        return False, "missing configuration: " + ", ".join(missing)
    return True, "configured"


@dataclass
class _RemoteCallBudget:
    deadline: float
    cancelled: Event = field(default_factory=Event)
    route: dict[str, Any] = field(default_factory=dict)


_remote_call_budget: ContextVar[_RemoteCallBudget | None] = ContextVar(
    "mcp_remote_call_budget", default=None,
)
_stdio_discovery_budget: ContextVar[_RemoteCallBudget | None] = ContextVar(
    "mcp_stdio_discovery_budget", default=None,
)


def _stdio_timeout(default: float) -> float:
    budget = _stdio_discovery_budget.get()
    if budget is None:
        return default
    remaining = budget.deadline - time.monotonic()
    if budget.cancelled.is_set() or remaining <= 0:
        raise TimeoutError("Stdio MCP discovery deadline exceeded")
    return min(default, remaining)


def _check_remote_call_budget():
    budget = _remote_call_budget.get()
    if budget is not None and (
        budget.cancelled.is_set() or time.monotonic() >= budget.deadline
    ):
        raise requests.exceptions.Timeout("Remote MCP call deadline exceeded")
    return budget



def probe_remote_tools(client, timeout_seconds: float = 3) -> list[dict]:
    """Bound discovery even if a remote response trickles without finishing."""
    budget = _RemoteCallBudget(time.monotonic() + timeout_seconds)
    holder = {}
    budgets = getattr(client, "_call_budgets", None)
    if isinstance(budgets, dict):
        budgets[id(budget)] = budget
    def runner():
        token = _remote_call_budget.set(budget)
        try:
            client.start()
            tools = client.list_tools()
            _check_remote_call_budget()
            holder["tools"] = tools
        except Exception:
            pass
        finally:
            _remote_call_budget.reset(token)
            if isinstance(budgets, dict):
                budgets.pop(id(budget), None)
    worker = Thread(target=copy_context().run, args=(runner,), daemon=True)
    worker.start()
    worker.join(timeout=timeout_seconds)
    if worker.is_alive():
        budget.cancelled.set()
        try:
            client._force_restart("discovery deadline exceeded")
        except AttributeError:
            client.stop()
        return []
    return holder.get("tools", [])


def probe_stdio_tools(client, timeout_seconds: float = 3) -> list[dict]:
    """Probe a fresh, isolated stdio client without holding up tool selection."""
    budget = _RemoteCallBudget(time.monotonic() + timeout_seconds)
    holder = {}
    previous_auto_restart = client._auto_restart
    client._auto_restart = False

    def runner():
        token = _stdio_discovery_budget.set(budget)
        try:
            client.start()
            tools = client.list_tools()
            _stdio_timeout(timeout_seconds)
            holder["tools"] = tools
        except Exception:
            pass
        finally:
            _stdio_discovery_budget.reset(token)
            client._auto_restart = previous_auto_restart
            if budget.cancelled.is_set() or not holder.get("tools"):
                client.stop()

    worker = Thread(target=copy_context().run, args=(runner,), daemon=True)
    worker.start()
    worker.join(timeout=timeout_seconds)
    if worker.is_alive():
        budget.cancelled.set()
        # This client is never published after a failed probe. Cleanup can
        # interrupt a stuck read without delaying selection or a later probe.
        Thread(target=client._force_restart, args=("discovery deadline exceeded",), daemon=True).start()
        return []
    return holder.get("tools", [])

def _duckduckgo_text_error(server_name: str, tool_name: str, text: str) -> bool:
    """Recognize errors that DuckDuckGo returns as successful MCP text content."""
    if server_name != "duckduckgo":
        return False
    normalized = (text or "").lstrip()
    if tool_name == "fetch_content":
        return normalized.startswith("Error:")
    if tool_name == "search":
        return normalized.startswith("An error occurred while searching:")
    return False


def _normalize_call_tool_result(
    tool_name: str,
    result: dict[str, Any] | None,
    *,
    server_name: str = "",
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert an MCP CallToolResult into Jarvis success/error semantics."""
    if not result:
        return {
            "ok": False,
            "speech": f"MCP tool {tool_name} returned no result",
            "error": "Empty result",
        }

    if server_name == "deepwiki":
        from deepwiki import DEEPWIKI_TOOL_NAMES, normalize_deepwiki_result

        if f"mcp_deepwiki_{tool_name}" in DEEPWIKI_TOOL_NAMES:
            return normalize_deepwiki_result(tool_name, result, arguments)

    if server_name == "google_workspace":
        from google_workspace import normalize_workspace_result

        return normalize_workspace_result(tool_name, result, arguments)

    content = result.get("content", [])
    text_parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text_parts.append(item.get("text", ""))
        elif isinstance(item, str):
            text_parts.append(item)
    combined_text = "\n".join(text_parts) if text_parts else (str(content) if content else "")

    if result.get("isError") is True or _duckduckgo_text_error(server_name, tool_name, combined_text):
        error_text = combined_text or str(result.get("error") or f"MCP tool {tool_name} failed")
        return {
            "ok": False,
            "speech": error_text[:500],
            "error": error_text,
            "data": {"raw": content or result, "full_text": combined_text, "isError": True},
        }

    if not content:
        return {
            "ok": True,
            "speech": str(result),
            "data": {"raw": result},
        }

    return {
        "ok": True,
        "speech": combined_text[:500],
        "data": {"raw": content, "full_text": combined_text},
    }


def _resolve_config_placeholder(var_name: str) -> str:
    """Resolve one explicitly referenced MCP variable from the active mode.

    ``get_config_value`` honors request-local ``config_scope`` values before
    the startup process environment. Keeping resolution behind this helper
    preserves the MCP allowlist: callers still inspect only placeholders that
    were explicitly declared in mcp-servers.json.
    """
    missing = f"${{{var_name}}}"
    value = get_config_value(var_name, None)
    return missing if value is None else str(value)


class MCPClient:
    """Client for communicating with MCP servers."""
    
    # Crash recovery settings
    MAX_RESTART_ATTEMPTS = 3
    RESTART_COOLDOWN_SECONDS = 60  # After max restarts, wait before allowing more
    
    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        proxy_policy: str = "inherit",
    ):
        """
        Initialize MCP client.
        
        Args:
            name: Server name (e.g., "duckduckgo")
            command: Command to start server (e.g., "docker")
            args: Arguments for command
            env: Environment variables
            proxy_policy: inherit, off, prefer, or require
        """
        self.name = name
        self.command = command
        self.args = args
        self.env = env or {}
        self.proxy_policy = normalize_proxy_policy(proxy_policy)
        self.process = None
        self.lock = Lock()
        self.request_id = 0
        self._tools_cache = None
        
        # Crash recovery state
        self._restart_count = 0
        self._last_restart_time = 0
        self._in_cooldown = False
        # Runtime tool calls auto-restart crashed servers; discovery/sync must fail fast.
        self._auto_restart = True
        self._selected_proxy_url: str | None = None
        self._selected_proxy_slot: str | None = None
        # Stdio sessions belong to one client. Different registries/processes
        # must not replace each other's Docker server (including during sync).
        self._docker_container_name: str | None = None
        self._docker_env: dict[str, str] = {}
        self._start_lock = RLock()

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

        # Signal outside the startup lock to interrupt a wedged handshake.
        process = self.process
        if process:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass

        with self._start_lock:
            if self.process is not None and self.process is not process:
                return  # Another caller already established a successor.
            self._remove_owned_container()
            self.process = None
            self._tools_cache = None
            self.request_id = 0
            # Replace the request lock if a timed-out reader still holds it.
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

        if not self._auto_restart:
            return False
        
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

    def _unhealthy_process_reason(self) -> str:
        if self._in_cooldown:
            return f"MCP server {self.name} is in cooldown after repeated crashes"
        exit_code = self.process.poll() if self.process else None
        if not self._auto_restart:
            return (
                f"MCP server {self.name} exited during discovery (code {exit_code}); "
                "automatic restart is disabled for discovery"
            )
        return f"MCP server {self.name} is unavailable after a crash (code {exit_code})"
    
    def start(self):
        """Start the MCP server process."""
        with self._start_lock:
            self._start()

    def _start(self):
        _stdio_timeout(5)
        if self.process:
            return  # Already running
        
        # Build environment with substitution
        # SECURITY: Only pass explicitly listed env vars, not the entire os.environ
        self._selected_proxy_url = None
        self._selected_proxy_slot = None
        mcp_env = self._build_env_with_substitution()
        
        # Expand ${VAR} in args as well
        expanded_args = self._expand_args()
        
        # Reuse one name for this client's restarts, never a server-wide name.
        if self.command == "docker" and "run" in expanded_args:
            self._docker_env = mcp_env
            labels = owner_labels()
            reaped = reap_orphans(labels, env=mcp_env, timeout=_stdio_timeout(5))
            if reaped:
                print(f"🧹 Removed {reaped} orphaned Docker MCP container(s)", file=sys.stderr)
            if self._docker_container_name is None:
                self._docker_container_name = (
                    f"jarvis-mcp-{self.name}-{os.getpid()}-{uuid4().hex[:12]}"
                )
            container_name = self._docker_container_name
            
            # Only replace a leftover container from this same client.
            try:
                result = subprocess.run(
                    ["docker", "ps", "-aq", "--filter", f"name=^{container_name}$"],
                    capture_output=True, text=True, timeout=_stdio_timeout(5), env=mcp_env,
                )
                if result.stdout.strip():
                    # Handles this client's running or stopped container.
                    if os.environ.get("MCP_DEBUG", "").lower() == "true":
                        print(f"[MCP DEBUG] Removing existing container: {container_name}", file=sys.stderr)
                    if not self._remove_owned_container(timeout=_stdio_timeout(10)):
                        raise RuntimeError(f"MCP container cleanup did not complete for {self.name}")
            except (OSError, subprocess.TimeoutExpired) as e:
                if os.environ.get("MCP_DEBUG", "").lower() == "true":
                    print(f"[MCP DEBUG] Container check failed: {e}", file=sys.stderr)
            
            # Inject --name after "run" in args
            run_idx = expanded_args.index("run")
            expanded_args = self._inject_docker_proxy_env(expanded_args, mcp_env)
            run_idx = expanded_args.index("run")
            label_args = [arg for key, value in labels.items() for arg in ("--label", f"{key}={value}")]
            expanded_args = (
                expanded_args[:run_idx + 1] + 
                ["--name", container_name, *label_args] +
                expanded_args[run_idx + 1:]
            )
        
        # Start process
        _stdio_timeout(5)  # A cancelled probe must not start a late container.
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
        time.sleep(_stdio_timeout(0.2))
        
        # Check if it started successfully
        if self.process.poll() is not None:
            stderr = self.process.stderr.read()
            raise Exception(f"MCP server failed to start: {stderr}")
        
        # Initialize the MCP connection
        self._initialize()
        _stdio_timeout(5)
    
    def _expand_args(self) -> list[str]:
        """
        Expand ${VAR_NAME} syntax in args from the active mode configuration.
        
        This allows mcp-servers.json to use variables like:
            "--proxy-server", "${LOCAL_PROXY}"
        
        Returns:
            List of args with variables expanded
        """
        def replace_var(match):
            var_name = match.group(1)
            return _resolve_config_placeholder(var_name)
        
        expanded = []
        for arg in self.args:
            if isinstance(arg, str) and '${' in arg:
                expanded.append(re.sub(r'\$\{([^}]+)\}', replace_var, arg))
            else:
                expanded.append(arg)
        return expanded

    @staticmethod
    def _declared_docker_env_names(args: list[str]) -> set[str]:
        """Return env names already forwarded by docker run arguments."""
        names: set[str] = set()
        for index, arg in enumerate(args):
            if arg in {"-e", "--env"} and index + 1 < len(args):
                names.add(str(args[index + 1]).split("=", 1)[0])
            elif arg.startswith("--env="):
                names.add(arg.split("=", 1)[1].split("=", 1)[0])
        return names

    def _inject_docker_proxy_env(
        self,
        args: list[str],
        child_env: dict[str, str],
    ) -> list[str]:
        """Forward only policy-derived proxy variables into a Docker MCP."""
        if self.proxy_policy not in {"prefer", "require"}:
            return args
        declared = self._declared_docker_env_names(args)
        additions: list[str] = []
        for key in STANDARD_PROXY_ENV_KEYS:
            if key in child_env and key not in declared:
                additions.extend(["-e", key])
        if not additions:
            return args
        run_idx = args.index("run")
        return args[: run_idx + 1] + additions + args[run_idx + 1 :]
    
    def _build_env_with_substitution(self) -> dict[str, str]:
        """
        Build environment dict with variable substitution.
        
        Supports ${VAR_NAME} syntax using the active cloud/local config scope,
        falling back to the startup process environment outside a scope.
        
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
                # Resolve only the explicitly referenced variable.
                def replace_var(match):
                    var_name = match.group(1)
                    return _resolve_config_placeholder(var_name)
                
                substituted_value = re.sub(r'\$\{([^}]+)\}', replace_var, value)
                result[key] = substituted_value
            else:
                result[key] = str(value)

        if self.proxy_policy == "off":
            for key in STANDARD_PROXY_ENV_KEYS:
                result.pop(key, None)
        elif self.proxy_policy in {"prefer", "require"}:
            proxy_urls = get_proxy_url_chain(respect_policy=False)
            selected = select_reachable_proxy_url(proxy_urls)
            if selected is None:
                if self.proxy_policy == "require":
                    raise RuntimeError(
                        f"MCP server {self.name} requires a proxy, but no configured proxy listener is reachable"
                    )
            else:
                proxy_url, proxy_slot = selected
                self._selected_proxy_url = proxy_url
                self._selected_proxy_slot = proxy_slot
                result.update(standard_proxy_environment(proxy_url))
                print(
                    f"[MCP PROXY] server={self.name} policy={self.proxy_policy} "
                    f"proxy_slot={proxy_slot}",
                    file=sys.stderr,
                )
        
        return result
    
    def stop(self):
        """Stop the MCP server process."""
        with self._start_lock:
            self._stop()

    def _stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            finally:
                self.process = None
        
        self._remove_owned_container()

    def _remove_owned_container(self, timeout: float = 10) -> bool:
        """Bound cleanup, including Docker's short 'removal in progress' race."""
        if self.command == "docker" and self._docker_container_name is not None:
            deadline = time.monotonic() + timeout
            try:
                while time.monotonic() < deadline:
                    result = subprocess.run(
                        ["docker", "rm", "-f", self._docker_container_name],
                        capture_output=True, text=True, env=self._docker_env,
                        timeout=max(.01, deadline - time.monotonic()),
                    )
                    if result.returncode == 0 or "no such container" in result.stderr.lower():
                        return True
                    if "removal" not in result.stderr.lower() or "progress" not in result.stderr.lower():
                        break
                    time.sleep(min(.1, max(0, deadline - time.monotonic())))
            except (OSError, subprocess.TimeoutExpired):
                pass
            print(f"⚠️ MCP {self.name} container cleanup did not complete", file=sys.stderr)
            return False
        return True
    
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
        _stdio_timeout(8)
        if not self._check_health():
            raise Exception(self._unhealthy_process_reason())
        
        if not self.process:
            self.start()
        
        with self.lock:
            # Process may have changed after startup/restart checks.
            if not self._check_health():
                raise Exception(self._unhealthy_process_reason())
            if not self.process:
                self.start()
            
            self.request_id += 1
            request_id = self.request_id
            process = self.process
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method
            }
            
            if params:
                request["params"] = params
            
            # Send request
            request_json = json.dumps(request) + "\n"
            process.stdin.write(request_json)
            process.stdin.flush()
            
            # Read response (may need to skip notifications)
            max_attempts = 10  # Avoid infinite loop
            timeout_seconds = 8  # Timeout per read attempt - was 5 increased to 8 for more time allowed for MCP servers to respond
            
            for _ in range(max_attempts):
                # Use select to timeout on readline
                import select
                ready, _, _ = select.select([process.stdout], [], [], _stdio_timeout(timeout_seconds))
                
                if not ready:
                    raise Exception(f"MCP server response timeout after {timeout_seconds}s")
                
                response_line = process.stdout.readline()
                
                if not response_line:
                    raise Exception("MCP server closed connection")
                
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
                if response.get("id") == request_id:
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

    def _ensure_proxy_listener(self) -> None:
        """Fast-fail a dead selected proxy before an upstream 30s timeout."""
        if self.proxy_policy not in {"prefer", "require"} or not self._selected_proxy_url:
            return
        if select_reachable_proxy_url([self._selected_proxy_url], timeout=0.35) is not None:
            return
        failed_slot = self._selected_proxy_slot or "configured_proxy"
        self._force_restart(f"{failed_slot} listener unavailable before tools/call")

    def get_proxy_log_metadata(self) -> dict[str, Any]:
        """Return credential-free proxy state for the current MCP process.

        For MCP servers, ``used`` means the process handling this call was
        launched with Jarvis-derived conventional proxy variables. It never
        includes the proxy URL, host, port, username, or password.
        """
        metadata: dict[str, Any] = {
            "policy": self.proxy_policy,
            "used": None,
            "basis": "mcp_environment",
        }
        if self.proxy_policy == "inherit":
            metadata["direct_reason"] = "unmanaged"
        elif self.proxy_policy == "off":
            metadata.update({"used": False, "direct_reason": "policy_off"})
        elif self._selected_proxy_slot:
            metadata.update({"used": True, "slot": self._selected_proxy_slot})
        elif self.proxy_policy == "prefer":
            metadata.update({
                "used": False,
                "direct_reason": "no_reachable_proxy",
            })
        else:
            metadata.update({
                "used": False,
                "direct_reason": "required_proxy_unavailable",
            })
        return metadata

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool on the MCP server.
        
        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            
        Returns:
            Tool result
        """
        self._ensure_proxy_listener()
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

        worker = Thread(target=copy_context().run, args=(_runner,), daemon=True)
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

            return _normalize_call_tool_result(
                tool_name,
                response_holder.get("result"),
                server_name=self.name,
                arguments=arguments,
            )
            
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
    
    def __init__(self, name: str, url: str, transport_type: str, headers: dict[str, str] | None = None,
                 proxy_policy: str = "inherit"):
        """
        Initialize remote MCP client.
        
        Args:
            name: Server name (e.g., "coingecko")
            url: Base URL for the MCP server
            transport_type: "sse" or "http"
            headers: Optional HTTP headers (e.g., for API keys)
                     SECURITY: Only these explicit headers are sent - no os.environ leakage
            proxy_policy: Per-server routing; inherit preserves existing behavior.
        """
        self.name = name
        self.url = url.rstrip('/')
        self.transport_type = transport_type
        self.headers = headers or {}
        self.proxy_policy = normalize_proxy_policy(proxy_policy)
        self._proxy_route: dict[str, Any] = {}
        self._call_budgets: dict[int, _RemoteCallBudget] = {}
        # SSE initialization and reconnect both re-enter _send_request() while
        # the outer request is serialized. The remote transport therefore
        # requires a reentrant lock; the stdio client does not.
        self.lock = RLock()
        self.request_id = 0
        self._tools_cache = None
        self._tool_properties: dict[str, set[str]] = {}
        self._initialized = False
        
        # Session management for Streamable HTTP
        self._session_id = None
        
        # SSE-specific attributes (for type="sse")
        self._sse_endpoint = None  # POST endpoint for sending messages
        self._sse_response_queue = queue.Queue()
        self._sse_thread = None
        self._sse_stop_event = Event()
        self._sse_connected = Event()

    def _http_request(self, method: str, url: str, **kwargs):
        """Apply this server's policy without changing process-wide settings."""
        budget = _check_remote_call_budget()
        if self.proxy_policy == "inherit":
            # Preserve existing remote MCP behavior unless explicitly opted in.
            if budget is not None:
                kwargs['timeout'] = _bounded_request_timeout(
                    kwargs.get('timeout', 30), deadline=budget.deadline,
                    cancel_event=budget.cancelled,
                )
            return getattr(requests, method.lower())(url, **kwargs)
        return http_request(
            method, url, proxy_policy=self.proxy_policy,
            route_metadata=budget.route if budget else self._proxy_route,
            proxy_timeout=(3, 5),
            deadline=budget.deadline if budget else None,
            cancel_event=budget.cancelled if budget else None,
            **kwargs,
        )

    def get_proxy_log_metadata(self) -> dict[str, Any]:
        """Describe the last remote HTTP attempt without exposing proxy URLs."""
        return dict(self._proxy_route) if self._proxy_route else {
            "policy": self.proxy_policy,
            "used": None,
            "basis": "http_request",
            "direct_reason": "unmanaged" if self.proxy_policy == "inherit" else "not_requested",
        }

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
        self.lock = RLock()
        self.request_id = 0
    
    def start(self):
        """Start the remote MCP connection."""
        if self._initialized:
            return
        
        if self.transport_type == "sse":
            self._start_sse()
        elif self.transport_type == "http":
            self._initialize_http()
        
        _check_remote_call_budget()
        self._initialized = True
    
    def _start_sse(self):
        """Start SSE connection in a background thread."""
        self._sse_stop_event.clear()
        listener_context = copy_context()
        # The stream outlives a single tool call, but keeps its mode config.
        listener_context.run(_remote_call_budget.set, None)
        self._sse_thread = Thread(
            target=listener_context.run, args=(self._sse_listener,), daemon=True,
        )
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
            
            response = self._http_request("GET", self.url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            event_type = None
            event_data = []
            
            for line in response.iter_lines(decode_unicode=False):
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
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
        
        response = self._http_request(
            "POST", self.url,
            json=request,
            headers=headers,
            timeout=30,
            stream=True
        )
        # Publish session state only after the response finishes within budget.
        session_id = response.headers.get('Mcp-Session-Id')
        
        if os.environ.get("MCP_DEBUG", "").lower() == "true":
            print(f"[MCP DEBUG] Got session ID: {session_id}", file=sys.stderr)
        
        # Consume the SSE response (initialization result).
        try:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=False):
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                _check_remote_call_budget()
                if os.environ.get("MCP_DEBUG", "").lower() == "true" and line:
                    print(f"[MCP DEBUG] Init response: {line}", file=sys.stderr)
            _check_remote_call_budget()
        finally:
            response.close()
        self._session_id = session_id
        
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
        _check_remote_call_budget()
        with self.lock:
            _check_remote_call_budget()
            if not self._initialized and method != "initialize":
                self.start()
            _check_remote_call_budget()
            
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
            response = self._http_request(
                "POST", self._sse_endpoint,
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
        deadline = time.monotonic() + 30
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Exception(f"Timeout waiting for SSE response from {self.name}")

            try:
                result = self._sse_response_queue.get(timeout=remaining)
            except queue.Empty:
                raise Exception(f"Timeout waiting for SSE response from {self.name}")

            if "error" in result and "id" not in result:
                raise Exception(f"SSE error: {result['error']}")

            if result.get("id") != request["id"]:
                continue

            if "error" in result:
                raise Exception(f"MCP error: {result['error'].get('message', 'Unknown')}")
            return result.get("result")
    
    def _send_http_request(self, request: dict, retry_count: int = 0) -> Any:
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
        
        response = self._http_request(
            "POST", self.url,
            json=request,
            headers=headers,
            timeout=30,
            stream=True  # Enable streaming for potential SSE responses
        )
        # A rejected session has not executed this request. Only that explicit
        # rejection permits replay; timeouts and unrelated HTTP errors do not.
        if response.status_code == 404 and self._session_id and retry_count == 0:
            try:
                stale = "session not found" in response.text.lower()
            finally:
                response.close()
            if stale:
                _check_remote_call_budget()
                self._initialized = False
                self._session_id = None
                self.start()
                _check_remote_call_budget()
                self.request_id += 1
                request = {**request, "id": self.request_id}
                return self._send_http_request(request, retry_count=1)
        try:
            response.raise_for_status()
            _check_remote_call_budget()
            content_type = response.headers.get('Content-Type', '')
            if 'text/event-stream' in content_type:
                result = self._parse_sse_response(response)
            else:
                result = response.json()
            _check_remote_call_budget()
        finally:
            response.close()
        
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
        
        # SSE is UTF-8. Requests defaults text/* without a charset to Latin-1;
        # its decoded splitlines then treats the last byte of "✅" as a newline
        # and breaks a valid JSON-RPC event. Split bytes first, then decode.
        for line in response.iter_lines(decode_unicode=False):
            _check_remote_call_budget()
            if line is None:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            
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
        
        if self.transport_type == "http" and self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            response = self._http_request("POST", endpoint, json=message, headers=headers, timeout=10)
            response.close()
        except Exception as e:
            if os.environ.get("MCP_DEBUG", "").lower() == "true":
                print(f"[MCP DEBUG] Post notification failed: {e}", file=sys.stderr)
    
    def stop(self):
        """Stop the remote MCP connection."""
        for budget in list(self._call_budgets.values()):
            budget.cancelled.set()
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
            tools = []
            cursor = None
            seen = set()
            for _page in range(100):
                result = self._send_request("tools/list", {"cursor": cursor} if cursor else None)
                tools.extend(result.get("tools", []) if result else [])
                cursor = result.get("nextCursor") if result else None
                if not cursor:
                    break
                if not isinstance(cursor, str) or cursor in seen:
                    raise ValueError("Invalid or repeated tools/list cursor")
                seen.add(cursor)
            else:
                raise ValueError("tools/list pagination exceeded 100 pages")
            valid_tools = []
            properties = {}
            for tool in tools:
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"]:
                    continue
                schema = tool.get("inputSchema", {})
                if not isinstance(schema, dict) or not isinstance(schema.get("properties", {}), dict):
                    continue
                if any(not isinstance(value, dict) for value in schema.get("properties", {}).values()):
                    continue
                if not isinstance(tool.get("description", ""), str) or not isinstance(tool.get("annotations") or {}, dict):
                    continue
                required = schema.get("required", [])
                if not isinstance(required, list) or any(not isinstance(key, str) for key in required):
                    continue
                if tool["name"] in properties:
                    continue
                valid_tools.append(tool)
                properties[tool["name"]] = set(schema.get("properties", {}))
            _check_remote_call_budget()
            self._tool_properties = properties
            self._tools_cache = valid_tools
            return valid_tools
        except Exception as e:
            print(f"Error listing tools from remote MCP server {self.name}: {e}", file=sys.stderr)
            return []
    
    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the remote MCP server."""
        arguments = dict(arguments)
        for key, default in getattr(self, "tool_defaults", {}).items():
            if self.name == "google_workspace" and key == "user_google_email":
                tool_info = next((
                    info for info in (self._tools_cache or []) if info.get("name") == tool_name
                ), None)
                properties = (set(tool_info.get("inputSchema", {}).get("properties", {}))
                              if tool_info is not None else self._tool_properties.get(tool_name))
                if (properties is not None and key not in properties) or (
                    properties is None and tool_name == "generate_trigger_code"
                ):
                    # Account-independent helpers (such as trigger code generation)
                    # reject this field rather than using Google credentials.
                    arguments.pop(key, None)
                    continue
                # This integration owns one dedicated account. A model's
                # guessed owner must not replace the configured identity.
                arguments[key] = default
                continue
            # Strict provider schemas may send null for an optional property.
            if arguments.get(key) is None:
                arguments[key] = default
        timeout_seconds = int(os.environ.get("MCP_TOOL_CALL_TIMEOUT_SECONDS", "35"))
        response_holder: dict[str, Any] = {}
        budget = _RemoteCallBudget(time.monotonic() + timeout_seconds)
        self._call_budgets[id(budget)] = budget
        self._proxy_route = budget.route

        def _runner():
            token = _remote_call_budget.set(budget)
            staged_id = None
            try:
                resolved_arguments = arguments
                upstream = arguments
                stash = False
                space_id = None
                if self.name == "google_workspace":
                    from google_workspace import prepare_workspace_transfer, resolve_workspace_recipients
                    resolved_arguments = resolve_workspace_recipients(tool_name, arguments)
                    upstream, stash, space_id, staged_id = prepare_workspace_transfer(self, tool_name, resolved_arguments)
                raw = self._send_request("tools/call", {"name": tool_name, "arguments": upstream})
                normalized = _normalize_call_tool_result(tool_name, raw, server_name=self.name, arguments=resolved_arguments)
                if stash:
                    from google_workspace import stash_workspace_download
                    normalized = stash_workspace_download(self, normalized, space_id)
                response_holder["result"] = normalized
            except Exception as e:
                response_holder["error"] = e
            finally:
                if staged_id:
                    from google_workspace import cleanup_workspace_transfer
                    cleanup_workspace_transfer(self, staged_id)
                _remote_call_budget.reset(token)
                self._call_budgets.pop(id(budget), None)

        worker = Thread(target=copy_context().run, args=(_runner,), daemon=True)
        worker.start()
        worker.join(timeout=timeout_seconds)

        if worker.is_alive():
            budget.cancelled.set()
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

            return response_holder["result"]
            
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
            available, reason = server_configuration_status(server_config)
            if not available:
                if reason.startswith(("missing", "invalid")):
                    print(f"Warning: MCP server '{name}' {reason}", file=sys.stderr)
                continue

            transport_type = server_config.get("type", "").lower()
            
            if transport_type in ("sse", "http"):
                # Remote MCP server (SSE or HTTP transport)
                url = server_config.get("url")
                if server_config.get("url_env"):
                    url = get_config_value(server_config["url_env"], None) or url
                if not url:
                    print(f"Warning: MCP server '{name}' has type={transport_type} but no url", file=sys.stderr)
                    continue
                
                # Process headers with environment variable substitution
                raw_headers = server_config.get("headers", {})
                headers = self._substitute_env_vars(raw_headers)
                
                self.servers[name] = MCPRemoteClient(
                    name, url, transport_type, headers,
                    proxy_policy=server_config.get("proxy_policy", "inherit"),
                )
                self.servers[name].tool_defaults = self._substitute_env_vars(
                    server_config.get("tool_defaults", {})
                )
                
                if os.environ.get("MCP_DEBUG", "").lower() == "true":
                    print(f"[MCP DEBUG] Loaded remote server: {name} ({transport_type}) -> {url}", file=sys.stderr)
            
            elif "command" in server_config:
                # Local MCP server (stdio transport)
                command = server_config.get("command")
                args = server_config.get("args", [])
                env = server_config.get("env", {})
                
                proxy_policy = server_config.get("proxy_policy", "inherit")
                self.servers[name] = MCPClient(
                    name,
                    command,
                    args,
                    env,
                    proxy_policy=proxy_policy,
                )
                
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
            
            Only MY_API_KEY is resolved from the active mode, nothing else.
        
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
                    return _resolve_config_placeholder(var_name)
                
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
