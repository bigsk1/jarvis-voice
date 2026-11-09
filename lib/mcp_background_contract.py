"""Pure MCP capabilities shared by lib-only discovery and background workers.

Native sync scripts expose lib/ without the repository package. Keep this
declaration independent of worker/storage imports and their package setup.
"""

from dataclasses import dataclass

ADAPTER = 'mcp_tool_v1'


@dataclass(frozen=True)
class MCPRegistration:
    server: str
    tool: str
    timeout_seconds: int
    transports: tuple[str, ...] = ('http',)


# Configuration and upstream metadata cannot add to this trusted registry.
# Apps Script executes remotely for at most six minutes. The job adds one
# minute for queueing, connection setup, and returning the ordinary response.
REGISTRATIONS = {
    'mcp_google_workspace_run_script_function': MCPRegistration(
        'google_workspace', 'run_script_function', 420,
    ),
}


def execution_for_tool(name, server, tool):
    registration = REGISTRATIONS.get(name)
    if registration is None or (registration.server, registration.tool) != (server, tool):
        return {}
    return {'background': {
        'supported': True, 'adapter': ADAPTER, 'completion_scope': 'remote_work',
        'timeout_seconds': registration.timeout_seconds,
    }}
