#!/usr/bin/env python3
"""
OpenCode Client for Jarvis
Python wrapper for OpenCode HTTP API.
"""

import json
import os
import time
from typing import Any
import requests
from model_catalog import get_provider_fallback_model
from opencode_logger import OpenCodeLogger
from paths import get_jarvis_workspace, get_project_root


def resolve_opencode_defaults(mode: str | None = None) -> dict[str, str]:
    """Resolve OpenCode provider/model from config with model_catalog fallbacks.

    OpenCode remains independently configurable: explicit OPENCODE_PROVIDER /
    OPENCODE_MODEL always win. When OpenCode's provider resolves to Ollama with
    no OpenCode-specific model, the mode-aware Ollama resolver is used so cloud
    mode picks OLLAMA_CLOUD_MODEL rather than the local OLLAMA_MODEL.
    """
    try:
        from config_loader import get_config_value, get_active_config_mode
        mode = get_active_config_mode(mode)
    except ImportError:
        get_config_value = lambda key, default="": default  # noqa: E731
        if mode is None:
            mode = os.environ.get("JARVIS_MODE", "cloud")

    def _ollama_default_model() -> str:
        try:
            from ollama_utils import resolve_ollama_model
            return resolve_ollama_model(mode)
        except Exception:
            return get_provider_fallback_model("ollama")

    configured_provider = get_config_value("OPENCODE_PROVIDER", "").strip()
    configured_model = get_config_value("OPENCODE_MODEL", "").strip()

    if configured_provider and configured_model:
        provider, model_id = configured_provider, configured_model
    elif configured_provider:
        provider = configured_provider
        model_id = _ollama_default_model() if provider == "ollama" else get_provider_fallback_model(provider)
    elif configured_model:
        provider = "ollama" if mode == "local" else "anthropic"
        model_id = configured_model
    elif mode == "local":
        provider = "ollama"
        model_id = _ollama_default_model()
    else:
        provider = "anthropic"
        model_id = get_provider_fallback_model(provider)

    return {"providerID": provider, "modelID": model_id}


class OpenCodeClient:
    """Client for communicating with OpenCode server."""

    def __init__(self, base_url: str | None = None):
        """
        Initialize OpenCode client.
        
        Args:
            base_url: OpenCode server URL (defaults to config or localhost:4096)
        """
        if base_url is None:
            # Try to get from config
            try:
                from config_loader import get_config_value
                base_url = get_config_value("OPENCODE_BASE_URL", "http://localhost:4096")
            except:
                base_url = "http://localhost:4096"
        
        self.base_url = base_url
        self.timeout = 360  # 6 minutes for complex builds/tasks (web apps, games, etc.)
        self.logger = OpenCodeLogger()
        
        # Load model config from environment
        try:
            from config_loader import get_config_value

            defaults = resolve_opencode_defaults()
            self.default_provider_id = defaults["providerID"]
            self.default_model_id = defaults["modelID"]
            server_password = get_config_value("OPENCODE_SERVER_PASSWORD", "").strip()
            server_username = get_config_value("OPENCODE_SERVER_USERNAME", "opencode").strip() or "opencode"
        except Exception:
            self.default_provider_id = "anthropic"
            self.default_model_id = get_provider_fallback_model("anthropic")
            server_password = ""
            server_username = "opencode"

        self.auth = (server_username, server_password) if server_password else None
        
        self._verify_connection()

    def _request_kwargs(self, timeout: int | float) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"timeout": timeout}
        if self.auth:
            kwargs["auth"] = self.auth
        return kwargs

    def _get(self, path: str, timeout: int | float | None = None):
        return requests.get(
            f"{self.base_url}{path}",
            **self._request_kwargs(timeout or self.timeout),
        )

    def _post(
        self,
        path: str,
        json_payload: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ):
        kwargs = self._request_kwargs(timeout or self.timeout)
        if json_payload is not None:
            kwargs["json"] = json_payload
        return requests.post(f"{self.base_url}{path}", **kwargs)

    def _verify_connection(self, max_retries: int = 3) -> bool:
        """Verify OpenCode server is accessible."""
        for attempt in range(max_retries):
            try:
                response = self._get("/config", timeout=5)
                if response.status_code == 200:
                    return True
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    print(f"⚠️  OpenCode server not reachable at {self.base_url}")
                    return False
            except Exception as e:
                print(f"⚠️  Error connecting to OpenCode: {e}")
                return False
        return False

    def health_check(self) -> dict[str, Any]:
        """Check OpenCode server health."""
        try:
            response = self._get("/config", timeout=5)
            if response.status_code != 200:
                return {"healthy": False, "status": "error"}

            sessions_response = self._get("/session", timeout=5)
            sessions = (
                sessions_response.json() if sessions_response.status_code == 200 else []
            )

            return {
                "healthy": True,
                "status": "running",
                "active_sessions": len(sessions),
            }
        except Exception as e:
            return {"healthy": False, "status": "error", "error": str(e)}

    def create_session(
        self,
        title: str = "Jarvis Session",
        agent_mode: str = "build"
    ) -> dict[str, Any]:
        """Create a new OpenCode session."""
        payload: dict[str, Any] = {"title": title}
        if agent_mode:
            payload["agent"] = agent_mode

        response = self._post("/session", json_payload=payload)
        response.raise_for_status()
        return response.json()

    def get_session(self, session_id: str) -> dict[str, Any]:
        """Get session information."""
        response = self._get(f"/session/{session_id}")
        response.raise_for_status()
        return response.json()

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions."""
        response = self._get("/session")
        response.raise_for_status()
        return response.json()

    def send_message(
        self,
        session_id: str,
        message: str,
        provider_id: str | None = None,
        model_id: str | None = None,
        no_reply: bool = False,
    ) -> dict[str, Any]:
        """Send a message to an OpenCode session."""
        # Use configured defaults if not specified
        if provider_id is None:
            provider_id = self.default_provider_id
        if model_id is None:
            model_id = self.default_model_id
        
        payload: dict[str, Any] = {"parts": [{"type": "text", "text": message}]}

        if no_reply:
            payload["noReply"] = True
        else:
            payload["model"] = {"providerID": provider_id, "modelID": model_id}

        response = self._post(
            f"/session/{session_id}/message",
            json_payload=payload,
        )
        response.raise_for_status()
        return response.json()

    def execute_task(
        self,
        task: str,
        session_id: str | None = None,
        model: dict[str, str] | None = None,
        context: dict[str, Any] | None = None,
        agent_mode: str = "build"  # "build" or "plan"
    ) -> dict[str, Any]:
        """Execute a task via OpenCode."""
        start_time = time.time()
        task_type = context.get("task_type", "general") if context else "general"
        
        try:
            # Create or use existing session
            if session_id is None:
                session = self.create_session(
                    title=f"Jarvis: {task[:50]}",
                    agent_mode=agent_mode,
                )
                session_id = session.get("id") or session.get("sessionId")
                if not session_id:
                    raise Exception("Failed to get session ID")
            
            # Log session start
            self.logger.log_session_start(
                session_id=session_id,
                task=task,
                task_type=task_type,
                model=model,
                context=context
            )

            _ws = get_jarvis_workspace().resolve()
            _repo = get_project_root().resolve()
            _ws_str = str(_ws)
            _repo_str = str(_repo)
            _proj_str = str(_ws / "projects")
            _temp_str = str(_ws / "temp")
            _dep_str = str(_ws / "deployments")

            # Inject system prompt explaining Jarvis integration (paths from lib.paths — portable across users)
            system_prompt = f"""# You are OpenCode - A specialized coding agent called by Jarvis

## Your Identity
- **Name**: OpenCode (always use "OpenCode" when referring to yourself, never "Claude" or "Claude Code")
- **Role**: Autonomous coding agent specialized in software development
- **Context**: You're being called by Jarvis, a voice-controlled AI assistant

## Your Role
You are executing tasks on behalf of Jarvis. The user spoke to Jarvis via voice, and Jarvis determined this task requires your specialized coding capabilities.

**IMPORTANT**: You are responding to Jarvis (a powerful LLM), NOT directly to the user. Jarvis will translate your response into natural language for voice output.

## Response Style
- **Skip lengthy introductions** unless specifically asked "what can you do?"
- **Get straight to work** on the task at hand
- **Focus on deliverables** (code, files, analysis) rather than explaining who you are

## Response Format Guidelines
- **Be detailed and technical**: Jarvis needs full context to understand what happened
- **Include all relevant information**: URLs, file paths, error details, technical specifics
- **Use technical jargon freely**: Jarvis understands technical terms and will translate appropriately
- **Provide complete context**: What was done, how it was done, what files were created/modified, any errors encountered
- **Include actionable details**: File paths, URLs, command outputs, error messages - Jarvis will decide what to tell the user
- **Be thorough**: Better to give too much detail than too little - Jarvis can condense

## Workspace & Boundaries - CRITICAL

**ABSOLUTE RULES - DO NOT VIOLATE:**

1. **NEVER create, modify, or delete files in `{_repo_str}`**
   - This is Jarvis's codebase - READ ONLY
   - If asked to modify Jarvis code, refuse and explain it's protected

2. **ALL file operations MUST be in `{_ws_str}`**
   - Your workspace root: `{_ws_str}`
   - Projects: `{_proj_str}/`
   - Temp files: `{_temp_str}/`
   - Deployments: `{_dep_str}/`
   - Do not use `/tmp`; use `{_temp_str}/` for scratch files, temporary scripts, test artifacts, and command output.

3. **If asked to work outside workspace:**
   - Politely refuse
   - Explain the security boundary
   - Suggest alternative in workspace

**Working directory will be specified in context**

## Error Handling
- Provide full technical error details: stack traces, error codes, specific failure points
- Include diagnostic information: What was attempted, what failed, why it failed
- Suggest technical solutions: Jarvis will translate these into user-friendly language

## Context
You will receive additional context about the task, workspace, and user preferences in the next message.

Remember: Your response goes to Jarvis, who will intelligently format it for voice output to the user. Be thorough and technical!
"""
            # Log system prompt
            self.logger.log_message_sent(
                session_id=session_id,
                message=system_prompt,
                message_type="system",
                no_reply=True
            )
            self.send_message(
                session_id=session_id, message=system_prompt, no_reply=True
            )

            # Inject context if provided, always include workspace path
            if context is None:
                context = {}
            
            # Always specify workspace
            if "workspace" not in context:
                context["workspace"] = _ws_str
            
            context_text = f"""# Jarvis Context

## Workspace
Your workspace root: `{_ws_str}`

All file operations must be within this directory. DO NOT access `{_repo_str}`.

## Task Context
{json.dumps(context, indent=2)}"""
            
            # Log context injection
            self.logger.log_message_sent(
                session_id=session_id,
                message=context_text,
                message_type="context",
                no_reply=True
            )
            self.send_message(
                session_id=session_id, message=context_text, no_reply=True
            )

            # Default model from config
            if model is None:
                model = {
                    "providerID": self.default_provider_id,
                    "modelID": self.default_model_id,
                }

            # Log task message
            self.logger.log_message_sent(
                session_id=session_id,
                message=task,
                message_type="task",
                no_reply=False
            )
            
            # Execute task
            msg_start_time = time.time()
            result = self.send_message(
                session_id=session_id,
                message=task,
                provider_id=model["providerID"],
                model_id=model["modelID"],
            )
            msg_duration = (time.time() - msg_start_time) * 1000
            
            # Log response
            self.logger.log_message_received(
                session_id=session_id,
                response=result,
                duration_ms=msg_duration
            )
            
            # Log session completion
            total_duration = (time.time() - start_time) * 1000
            self.logger.log_session_complete(
                session_id=session_id,
                success=True,
                result_summary=f"Task completed in {total_duration:.0f}ms"
            )

            return {"ok": True, "session_id": session_id, "result": result}
        except Exception as e:
            # Log error
            self.logger.log_error(
                session_id=session_id,
                error_type=type(e).__name__,
                error_message=str(e),
                context={"task": task, "task_type": task_type}
            )
            self.logger.log_session_complete(
                session_id=session_id if session_id else "unknown",
                success=False,
                error=str(e)
            )
            return {"ok": False, "error": str(e)}

    def get_providers(self) -> dict[str, Any]:
        """Get available LLM providers and models."""
        response = self._get("/config/providers")
        response.raise_for_status()
        return response.json()

    def abort_session(self, session_id: str) -> bool:
        """Abort a running session."""
        try:
            response = self._post(f"/session/{session_id}/abort")
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Failed to abort session: {e}")
            return False


def get_client() -> OpenCodeClient:
    """Get singleton OpenCode client instance."""
    return OpenCodeClient()


if __name__ == "__main__":
    # Test the client
    print("Testing OpenCode Client...")
    client = OpenCodeClient()
    health = client.health_check()
    print(f"Health: {json.dumps(health, indent=2)}")

    if health["healthy"]:
        sessions = client.list_sessions()
        print(f"Active sessions: {len(sessions)}")
        providers = client.get_providers()
        print(f"Providers: {json.dumps(providers, indent=2)}")
