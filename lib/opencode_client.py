#!/usr/bin/env python3
"""
OpenCode Client for Jarvis
Python wrapper for OpenCode HTTP API.
"""

import json
import time
from typing import Dict, Any, Optional, List
import requests


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
        self.timeout = 30
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
        provider_id: str = "anthropic",
        model_id: str = "claude-sonnet-4-20250514",
        no_reply: bool = False,
    ) -> Dict[str, Any]:
        """Send a message to an OpenCode session."""
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
    ) -> Dict[str, Any]:
        """Execute a task via OpenCode."""
        try:
            # Create or use existing session
            if session_id is None:
                session = self.create_session(title=f"Jarvis: {task[:50]}")
                session_id = session.get("id")
                if not session_id:
                    raise Exception("Failed to get session ID")

            # Inject context if provided
            if context:
                context_text = f"# Jarvis Context\n{json.dumps(context, indent=2)}"
                self.send_message(
                    session_id=session_id, message=context_text, no_reply=True
                )

            # Default model
            if model is None:
                model = {
                    "providerID": "anthropic",
                    "modelID": "claude-sonnet-4-20250514",
                }

            # Execute task
            result = self.send_message(
                session_id=session_id,
                message=task,
                provider_id=model["providerID"],
                model_id=model["modelID"],
            )

            return {"ok": True, "session_id": session_id, "result": result}
        except Exception as e:
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
