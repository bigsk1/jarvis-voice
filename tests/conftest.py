"""Pytest collection boundaries for the core Jarvis project suite."""

# These are interactive diagnostics with CLI arguments and printed reports,
# not fixture-driven pytest modules. They remain directly executable.
collect_ignore = [
    "test_tool_similarity.py",
]
