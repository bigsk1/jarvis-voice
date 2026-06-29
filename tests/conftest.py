"""Pytest collection boundaries for the core Jarvis project suite."""

# These are interactive diagnostics with CLI arguments and printed reports,
# not fixture-driven pytest modules. They remain directly executable.
collect_ignore = [
    "integration/test_intelligence_integration.py",
    "test_tool_similarity.py",
]
