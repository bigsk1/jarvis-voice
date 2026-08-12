"""Shared request-scoped policy for provider-hosted tools."""

from config_loader import get_bool


def server_side_tools_disabled() -> bool:
    """Return whether hosted/native provider tools are disabled for this call."""
    return bool(get_bool("DISABLE_SERVER_SIDE_TOOLS", False))
