"""Pytest collection boundaries for the core Jarvis project suite."""

import pytest
from suite_isolation import install_default_isolation, isolated_test_state

install_default_isolation()

# These are interactive diagnostics with CLI arguments and printed reports,
# not fixture-driven pytest modules. They remain directly executable.
collect_ignore = [
    "comprehensive_test.py",
    "test_tool_similarity.py",
]


@pytest.fixture(autouse=True)
def restore_test_application_state():
    with isolated_test_state():
        yield
