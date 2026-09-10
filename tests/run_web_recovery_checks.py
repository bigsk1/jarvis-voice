"""Run a reviewed Web recovery test group with disposable defaults and no network.

Usage: timeout 120 .venv/bin/python tests/run_web_recovery_checks.py core
Each group needs a fresh process because older tests install global module stubs.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'lib'), str(ROOT / 'tests')]

import config_loader  # noqa: E402
import flask_error_logger  # noqa: E402
import llm_logger  # noqa: E402
import pytest  # noqa: E402
import tool_logger  # noqa: E402

GROUPS = {
    'core': [
        'test_web_task_recovery', 'test_web_task_recovery_ui',
        'test_web_attachment_bundle_ui', 'test_web_attachment_bundle_chat',
        'test_conversation_store', 'test_web_conversation_workflow_roundtrip',
        'test_web_conversation_titles', 'test_web_socket_reconnect',
    ],
    'guard': ['test_completion_guard_server_side_tools'],
    'adjacent': [
        'test_web_usage_metadata', 'test_web_discovery_mode_scopes', 'test_chat_only_mode',
        'test_web_pdf_chat_context', 'test_web_chat_vision_failure',
    ],
    'executors': ['test_tool_executor_cancel', 'test_pipeline_executor'],
    'settings': ['test_web_settings_mode'],
}


class Isolation:
    def __init__(self, directory):
        self.directory = directory

    def pytest_collection_modifyitems(self, session, config, items):
        self._redirect_web_config()

    def pytest_runtest_call(self, item):
        # Some unittest setUpClass methods import the app after collection.
        self._redirect_web_config()

    def _redirect_web_config(self):
        for module in list(sys.modules.values()):
            path = str(getattr(module, '__file__', '') or '')
            if (path.endswith('/jarvis-web/server/config.py')
                    and module.CONFIG_PATH == ROOT / 'jarvis-web' / 'config' / 'web_config.json'):
                module.CONFIG_PATH = self.directory / 'web_config.json'
                module._web_config = None


def no_network(*args, **kwargs):
    raise AssertionError('Network I/O is not authorized in this isolated test run')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=GROUPS)
    group = parser.parse_args().group
    with tempfile.TemporaryDirectory(prefix='jarvis-recovery-check-') as name, ExitStack() as stack:
        temp = Path(name)
        (temp / 'config').mkdir()
        for mode in ('cloud', 'local'):
            (temp / 'config' / f'{mode}.env').write_text('')
        env = {key: os.environ[key] for key in ('HOME', 'PATH', 'LANG', 'TERM') if key in os.environ}
        env.update(STASH_DIR=str(temp / 'stash'), TMPDIR=str(temp))
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        stack.enter_context(patch.object(config_loader, 'get_project_root', lambda: temp))
        stack.enter_context(patch.object(flask_error_logger, 'LOGS_DIR', temp / 'logs'))
        stack.enter_context(patch.object(tool_logger, 'get_logger',
                                        lambda mode='cloud': tool_logger.ToolLogger(temp / 'logs' / 'tools')))
        stack.enter_context(patch.object(llm_logger, 'get_logger',
                                        lambda mode='cloud': llm_logger.LLMLogger(temp / 'logs')))
        stack.enter_context(patch.object(socket.socket, 'connect', no_network))
        stack.enter_context(patch.object(socket, 'create_connection', no_network))
        return pytest.main(['-q', '--tb=short', *[
            str(ROOT / 'tests' / f'{test}.py') for test in GROUPS[group]
        ]], plugins=[Isolation(temp)])


if __name__ == '__main__':
    raise SystemExit(main())
