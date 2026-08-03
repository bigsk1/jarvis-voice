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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, export_config_environment
from http_client import PROXY_POLICY_ENV, STANDARD_PROXY_ENV_KEYS
from tool_logger import get_logger
from tool_search_runtime import search_tools_runtime
try:
    from .workflow_tool_runtime import execute_workflow_tool
except ImportError:
    from workflow_tool_runtime import execute_workflow_tool


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
        self.cancel_check = None
        self.jarvis_session_id = None
        self.web_conversation_id = None
        self.excluded_tools: set[str] = set()
        self.workflow_loader = None
        self.pipeline_executor = None
        self.workflow_status_callback = None

    def set_cancel_check(self, callback):
        """Set callback to check if the current tool execution should be cancelled."""
        self.cancel_check = callback

    def set_session_context(self, jarvis_session_id: str | None = None, web_conversation_id: str | None = None):
        """Set session metadata that should be propagated to tool subprocesses."""
        self.jarvis_session_id = jarvis_session_id
        self.web_conversation_id = web_conversation_id

    def set_excluded_tools(self, excluded_tools: list[str] | None = None):
        """Set request-scoped tools that must remain hidden from discovery."""
        self.excluded_tools = {str(name).strip() for name in (excluded_tools or []) if str(name).strip()}

    def set_workflow_runtime(
        self,
        *,
        workflow_loader=None,
        pipeline_executor=None,
        status_callback=None,
    ):
        """Attach shared foreground workflow components from the orchestrator."""
        self.workflow_loader = workflow_loader
        self.pipeline_executor = pipeline_executor
        self.workflow_status_callback = status_callback

    def _get_subprocess_timeout(self, tool_name: str) -> int:
        """Return the subprocess timeout for a local tool."""
        if tool_name == "opencode":
            return 480  # 8 minutes for OpenCode tasks (complex builds)
        if tool_name == "ingest_intel":
            return 300  # 5 minutes to match API sync ingest timeout for large intel files
        if tool_name == "manage_intel":
            return 600  # 10 minutes; create/update/delete can trigger two sequential ingests
        if tool_name == "generate_image":
            return 300  # 5 minutes for AI image generation (especially with grounding)
        if tool_name == "generate_music":
            return 600  # 10 minutes for music generation (can take 3-5min for longer tracks)
        if tool_name == "generate_video":
            return 600  # 10 minutes for video generation (typically 2-3 min, up to 5 min for 4k)
        if tool_name == "create_social_clip":
            return 1200  # 20 minutes — MoneyPrinterTurbo script + stock + TTS + render + download
        if tool_name == "weather":
            return 90  # Weather API can be slow with proxy fallback
        if tool_name == "flight_search":
            return 120  # SerpApi deep search can take up to 90 seconds
        if tool_name == "serpapi_home_depot":
            return 200  # Direct SerpApi only; up to two sequential 90s HTTP calls if include_product_details
        if tool_name == "status_recap":
            return 180  # 3 minutes - calls multiple tools including generate_image
        if tool_name == "crawl_url":
            return 90  # 90 seconds - web scraping with JS wait can be slow
        if tool_name == "search_docs":
            return 90  # 60 seconds - search documentation with qmd
        if tool_name == "text_summarizer":
            return 180  # May call configured LLM over long stash/transcript artifacts
        if tool_name == "convert_file":
            return 180  # 3 minutes - convert files various formats, audio, video, image, ect.
        if tool_name == "samantha":
            return 180  # 3 minutes - Samantha is a remote assistant, so we need to increase the timeout
        if tool_name == "youtube_video":
            return 900  # 15 minutes - YouTube video download can be slow if downloading 2hr video
        if tool_name == "phone_call":
            return 900  # 15 min — aligns with VAPI_WAIT_TIMEOUT / wait_for_call_completion + Vapi maxDurationSeconds
        return 75 if self.mode == "local" else 60
    
    def execute(self, tool_name: str, args: dict[str, Any], skip_permission_check: bool = False) -> dict[str, Any]:
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
        # Request/surface exclusions are an execution boundary, not just a
        # discovery hint. Workflows bypass normal LLM schema selection.
        if tool_name in self.excluded_tools:
            return {
                "ok": False,
                "speech": f"Tool {tool_name} is blocked for this request",
                "error": "Tool blocked for this request",
            }

        # Get tool schema for permission check
        tool_schema = self.registry.get_tool(tool_name)
        
        if not tool_schema and tool_name.startswith("mcp_"):
            try:
                from tool_schema import get_tool_registry, reset_tool_registry

                shared_registry = get_tool_registry(mode=self.mode)
                shared_schema = shared_registry.get_tool(tool_name)
                if not shared_schema:
                    reset_tool_registry()
                    shared_registry = get_tool_registry(mode=self.mode)
                    shared_schema = shared_registry.get_tool(tool_name)
                if shared_schema:
                    self.registry = shared_registry
                    tool_schema = shared_schema
            except Exception as e:
                if os.environ.get("MCP_DEBUG", "").lower() == "true":
                    print(
                        f"[MCP DEBUG] Shared registry recovery failed for {tool_name}: {e}",
                        file=sys.stderr,
                    )

        if not tool_schema:
            return {
                "ok": False,
                "speech": f"Tool {tool_name} not found",
                "error": "Tool not found"
            }

        if tool_name == "tool_search":
            return self._execute_tool_search(tool_name, args)
        if tool_name == "workflow":
            return self._execute_workflow(tool_name, args)
        
        # Check permissions (unless explicitly skipped)
        if not skip_permission_check and tool_schema.requires_confirmation():
            # For voice control, we announce what we're about to do
            warning = tool_schema.get_permission_warning()
            # Only print if not in JSON mode (for voice scripts)
            if sys.stdout.isatty() or os.environ.get('JARVIS_JSON_MODE') != '1':
                print(f"⚠️  Permission check: {warning}", file=sys.stderr)
            
            # TODO: In future, could add verbal confirmation loop here
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
            
            # @TOOL_CONFIG: tool execution timeouts — add new tools with custom timeouts here
            # Use longer timeout for local mode (Ollama can be slower)
            # OpenCode tasks need much more time (building, coding, etc.)
            # Ingest intel needs time for embedding generation (especially large profiles)
            # phone_call: Vapi max call length + poll loop + canvas save (see skills/phone_call.py)
            # Subprocess timeout settings see tool.json for HTTP timeouts
            timeout = self._get_subprocess_timeout(tool_name)
            
            # Materialize the request's deployment mode into the child env and
            # stamp JARVIS_MODE explicitly so tools never infer mode from the
            # chat provider. Starts from the current environment, so per-request
            # JARVIS_OVERRIDE_* values and session context still propagate.
            tool_env = export_config_environment(self.mode)
            proxy_policy = getattr(tool_schema, "proxy_policy", "inherit")
            if proxy_policy != "inherit":
                tool_env[PROXY_POLICY_ENV] = proxy_policy
                tool_env[f"JARVIS_OVERRIDE_{PROXY_POLICY_ENV}"] = proxy_policy
            if proxy_policy == "off":
                # Child tools commonly call load_config(), so blank override
                # values prevent LOCAL_PROXY* from being rehydrated. Remove
                # conventional variables too so non-Jarvis HTTP libraries do
                # not silently pick up a host proxy.
                for key in ("LOCAL_PROXY", "LOCAL_PROXY2"):
                    tool_env[key] = ""
                    tool_env[f"JARVIS_OVERRIDE_{key}"] = ""
                for key in STANDARD_PROXY_ENV_KEYS:
                    tool_env.pop(key, None)
                    tool_env[f"JARVIS_OVERRIDE_{key}"] = ""
            if self.jarvis_session_id:
                tool_env['JARVIS_SESSION_ID'] = str(self.jarvis_session_id)
            if self.web_conversation_id:
                tool_env['JARVIS_WEB_CONVERSATION_ID'] = str(self.web_conversation_id)
            
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if tool_script.suffix != '.py' else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.skills_dir,
                env=tool_env  # Pass environment so tools see LLM_PROVIDER
            )

            if tool_script.suffix != '.py' and process.stdin:
                process.stdin.write(input_json)
                process.stdin.close()

            deadline = start_time + timeout
            cancelled = False
            stdout = ""
            stderr = ""

            # Read stdout/stderr in a background thread while polling for cancel/timeout.
            # Without this, tools that print >64KB JSON deadlock: the child blocks on a full
            # pipe buffer while the parent waits for process exit before calling communicate().
            with ThreadPoolExecutor(max_workers=1) as io_pool:
                communicate_future = io_pool.submit(process.communicate)

                while True:
                    if self.cancel_check:
                        try:
                            if self.cancel_check():
                                cancelled = True
                                process.terminate()
                                try:
                                    process.wait(timeout=3)
                                except subprocess.TimeoutExpired:
                                    process.kill()
                                break
                        except Exception:
                            pass

                    if communicate_future.done():
                        stdout, stderr = communicate_future.result()
                        break

                    if time.time() >= deadline:
                        process.kill()
                        try:
                            communicate_future.result(timeout=5)
                        except Exception:
                            pass
                        raise subprocess.TimeoutExpired(cmd, timeout)

                    time.sleep(0.25)

            if cancelled:
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
                duration_ms = (time.time() - start_time) * 1000
                output = {
                    "ok": True,
                    "speech": f"Stopped {tool_name}.",
                    "cancelled": True,
                    "error": "Cancelled by user"
                }
                self.logger.log_tool_call(
                    tool_name=tool_name,
                    arguments=args,
                    result=output,
                    duration_ms=duration_ms,
                    mode=self.mode
                )
                return output
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Parse output (tools write JSON to stdout even on failure)
            try:
                output = json.loads(stdout)
            except json.JSONDecodeError:
                # If JSON parsing fails, fallback to error message
                output = {
                    "ok": False,
                    "speech": f"Tool {tool_name} failed",
                    "error": stderr or stdout or "Unknown error"
                }
            
            # Note: We don't check returncode because tools write valid JSON even on failure
            
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

    def _execute_tool_search(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run live tool discovery against the active registry."""
        start_time = time.time()
        result = search_tools_runtime(
            registry=self.registry,
            query=args.get("query", ""),
            limit=args.get("limit", 6),
            excluded_tools=self.excluded_tools,
            tool_names=args.get("tool_names"),
            include_schema=bool(args.get("include_schema")),
        )
        duration_ms = (time.time() - start_time) * 1000
        self.logger.log_tool_call(
            tool_name=tool_name,
            arguments=args,
            result=result,
            duration_ms=duration_ms,
            mode=self.mode
        )
        return result

    def _execute_workflow(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Discover or synchronously run workflows against this executor's registry."""
        start_time = time.time()
        try:
            result = execute_workflow_tool(
                registry=self.registry,
                args=args,
                mode=self.mode,
                excluded_tools=self.excluded_tools,
                loader=self.workflow_loader,
                pipeline_executor=self.pipeline_executor,
                tool_executor=self,
                status_callback=self.workflow_status_callback,
            )
        except Exception as exc:
            result = {
                "ok": False,
                "speech": "Workflow execution failed.",
                "error": str(exc),
            }
        duration_ms = (time.time() - start_time) * 1000
        self.logger.log_tool_call(
            tool_name=tool_name,
            arguments=args,
            result=result,
            duration_ms=duration_ms,
            mode=self.mode,
        )
        return result
    
    def _execute_mcp_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
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

            # Strict outer timeout guard: prevents WebUI "thinking forever"
            mcp_timeout = int(os.environ.get("MCP_EXECUTOR_TIMEOUT_SECONDS", "45"))
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(mcp_client.call_tool, mcp_tool_name, args)
                try:
                    result = future.result(timeout=mcp_timeout)
                except FuturesTimeoutError:
                    # Try to force-recover the MCP client for next calls
                    if hasattr(mcp_client, "_force_restart"):
                        try:
                            mcp_client._force_restart(f"executor timeout ({mcp_timeout}s)")
                        except Exception:
                            pass

                    result = {
                        "ok": False,
                        "speech": f"MCP tool {tool_name} timed out",
                        "error": f"Executor timeout after {mcp_timeout}s"
                    }
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Log execution
            self.logger.log_tool_call(
                tool_name=tool_name,
                arguments=args,
                result=result,
                duration_ms=duration_ms,
                mode=self.mode,
                proxy=(
                    mcp_client.get_proxy_log_metadata()
                    if hasattr(mcp_client, "get_proxy_log_metadata")
                    else None
                ),
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
                mode=self.mode,
                proxy=(
                    mcp_client.get_proxy_log_metadata()
                    if "mcp_client" in locals()
                    and hasattr(mcp_client, "get_proxy_log_metadata")
                    else None
                ),
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
