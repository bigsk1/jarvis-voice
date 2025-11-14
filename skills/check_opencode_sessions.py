#!/usr/bin/env python3
"""
Check OpenCode Sessions Tool
Query OpenCode API for session history, progress, and build details.
READ-ONLY - does not trigger new builds.
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from opencode_client import OpenCodeClient


def main():
    """Check OpenCode sessions via API."""
    try:
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        session_id = args.get('session_id')
        limit = args.get('limit', 5)
        
        # Initialize OpenCode client
        try:
            client = OpenCodeClient()
        except Exception as e:
            return {
                "ok": False,
                "speech": "OpenCode server is not running. Start it with: systemctl --user start opencode",
                "error": f"Connection failed: {str(e)}"
            }
        
        # Check health
        health = client.health_check()
        if not health.get("healthy"):
            return {
                "ok": False,
                "speech": "OpenCode server is not responding properly",
                "error": "Health check failed"
            }
        
        # Get specific session or list all sessions
        if session_id:
            # Get detailed session info
            try:
                session = client.get_session(session_id)
            except Exception as e:
                return {
                    "ok": False,
                    "speech": f"Session {session_id} not found",
                    "error": str(e)
                }
            
            # Build speech summary
            title = session.get('title', 'Untitled')
            agent = session.get('agent', 'unknown')
            msg_count = len(session.get('messages', []))
            
            speech = f"OpenCode session: {title}. Agent: {agent}. {msg_count} messages in conversation."
            
            # Add token info if available
            if 'metadata' in session and 'tokensUsed' in session['metadata']:
                tokens = session['metadata']['tokensUsed']
                speech += f" Tokens used: {tokens}."
            
            result = {
                "ok": True,
                "speech": speech,
                "data": {
                    "session": session
                }
            }
            
        else:
            # List recent sessions
            try:
                sessions = client.list_sessions()
                if not isinstance(sessions, list):
                    sessions = []
            except Exception as e:
                return {
                    "ok": False,
                    "speech": "Failed to retrieve OpenCode sessions",
                    "error": str(e)
                }
            
            if not sessions:
                return {
                    "ok": True,
                    "speech": "No OpenCode sessions found. Use the opencode tool to build something.",
                    "data": {"sessions": []}
                }
            
            # Sort by last activity (most recent first)
            sessions.sort(key=lambda s: s.get('lastActivity', s.get('created', '')), reverse=True)
            
            # Limit results
            sessions = sessions[:limit]
            
            # Build speech summary
            speech = f"Found {len(sessions)} recent OpenCode session(s): "
            summaries = []
            for s in sessions[:3]:  # Only mention top 3 in speech
                title = s.get('title', 'Untitled')
                agent = s.get('agent', 'unknown')
                summaries.append(f"{title} ({agent} mode)")
            
            speech += ", ".join(summaries)
            
            if len(sessions) > 3:
                speech += f" and {len(sessions) - 3} more"
            
            result = {
                "ok": True,
                "speech": speech,
                "data": {
                    "sessions": sessions,
                    "count": len(sessions)
                }
            }
        
        print(json.dumps(result))
        return result
        
    except Exception as e:
        error_result = {
            "ok": False,
            "speech": f"Failed to check OpenCode sessions: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()

