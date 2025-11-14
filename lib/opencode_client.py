#!/usr/bin/env python3
"""
OpenCode Client for Jarvis
Python wrapper for OpenCode HTTP API.
"""

import json
import time
from typing import Dict, Any, Optional, List
import requests
from opencode_logger import OpenCodeLogger


class OpenCodeClient:
    """Client for communicating with OpenCode server."""

    def __init__(self, base_url: Optional[str] = None):
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
            self.default_model_id = get_config_value("OPENCODE_MODEL", "claude-sonnet-4-20250514")
            self.default_provider_id = get_config_value("OPENCODE_PROVIDER", "anthropic")
        except:
            self.default_model_id = "claude-sonnet-4-20250514"
            self.default_provider_id = "anthropic"
        
        self._verify_connection()

    def _verify_connection(self, max_retries: int = 3) -> bool:
        """Verify OpenCode server is accessible."""
        for attempt in range(max_retries):
            try:
                response = requests.get(f"{self.base_url}/config", timeout=5)
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

    def health_check(self) -> Dict[str, Any]:
        """Check OpenCode server health."""
        try:
            response = requests.get(f"{self.base_url}/config", timeout=5)
            if response.status_code != 200:
                return {"healthy": False, "status": "error"}

            sessions_response = requests.get(f"{self.base_url}/session", timeout=5)
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

    def create_session(self, title: str = "Jarvis Session") -> Dict[str, Any]:
        """Create a new OpenCode session."""
        response = requests.post(
            f"{self.base_url}/session", json={"title": title}, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session information."""
        response = requests.get(
            f"{self.base_url}/session/{session_id}", timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions."""
        response = requests.get(f"{self.base_url}/session", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def send_message(
        self,
        session_id: str,
        message: str,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        no_reply: bool = False,
    ) -> Dict[str, Any]:
        """Send a message to an OpenCode session."""
        # Use configured defaults if not specified
        if provider_id is None:
            provider_id = self.default_provider_id
        if model_id is None:
            model_id = self.default_model_id
        
        payload: Dict[str, Any] = {"parts": [{"type": "text", "text": message}]}

        if no_reply:
            payload["noReply"] = True
        else:
            payload["model"] = {"providerID": provider_id, "modelID": model_id}

        response = requests.post(
            f"{self.base_url}/session/{session_id}/message",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def execute_task(
        self,
        task: str,
        session_id: Optional[str] = None,
        model: Optional[Dict[str, str]] = None,
        context: Optional[Dict[str, Any]] = None,
        agent_mode: str = "build"  # "build" or "plan"
    ) -> Dict[str, Any]:
        """Execute a task via OpenCode."""
        start_time = time.time()
        task_type = context.get("task_type", "general") if context else "general"
        
        try:
            # Create or use existing session
            if session_id is None:
                session = self.create_session(title=f"Jarvis: {task[:50]}")
                session_id = session.get("id")
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

            # Inject system prompt explaining Jarvis integration
            system_prompt = """# You are OpenCode - A specialized coding agent called by Jarvis

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

1. **NEVER create, modify, or delete files in `/home/boss/jarvis-voice`**
   - This is Jarvis's codebase - READ ONLY
   - If asked to modify Jarvis code, refuse and explain it's protected

2. **ALL file operations MUST be in `/home/boss/jarvis-workspace`**
   - Your workspace root: `/home/boss/jarvis-workspace`
   - Projects: `/home/boss/jarvis-workspace/projects/`
   - Temp files: `/home/boss/jarvis-workspace/temp/`
   - Deployments: `/home/boss/jarvis-workspace/deployments/`

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
                context["workspace"] = "/home/boss/jarvis-workspace"
            
            context_text = f"""# Jarvis Context

## Workspace
Your workspace root: `/home/boss/jarvis-workspace`

All file operations must be within this directory. DO NOT access `/home/boss/jarvis-voice`.

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

    def get_providers(self) -> Dict[str, Any]:
        """Get available LLM providers and models."""
        response = requests.get(
            f"{self.base_url}/config/providers", timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def abort_session(self, session_id: str) -> bool:
        """Abort a running session."""
        try:
            response = requests.post(
                f"{self.base_url}/session/{session_id}/abort", timeout=self.timeout
            )
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
