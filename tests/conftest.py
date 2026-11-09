"""Pytest collection boundaries for the core Jarvis project suite."""

import importlib

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
def restore_test_application_state(tmp_path):
    with isolated_test_state(), pytest.MonkeyPatch.context() as patch:
        # Keep the real incident writer active, but put its unconfigured fallback
        # under this test's temporary root. Explicit configured directories and
        # fixtures that replace the writer root still take precedence normally.
        for name in ('lib.prompt_guard_incidents', 'prompt_guard_incidents'):
            patch.setattr(importlib.import_module(name), 'get_project_root', lambda: tmp_path)
        yield
