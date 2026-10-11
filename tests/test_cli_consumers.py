"""Existing orchestrator subprocess callers retain failed structured results."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from tool_builder import ToolBuilder  # noqa: E402


@pytest.mark.parametrize('exit_code', [0, 1])
def test_builder_preserves_failed_research_answer_and_error(monkeypatch, exit_code):
    payload = {'ok': False, 'speech': 'Search could not complete.', 'error': 'fixture provider unavailable',
               'tools_used': ['search'], 'data': {'search': {'state': 'failed'}}}
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, exit_code, json.dumps(payload), ''))
    builder = ToolBuilder.__new__(ToolBuilder)
    builder.mode = 'cloud'
    entries = []
    builder._log_research = entries.append
    result = builder.research_via_jarvis('test research')
    assert 'Search could not complete.' in result and 'fixture provider unavailable' in result
    assert entries[-1]['status'] == 'failed'
    assert entries[-1]['jarvis_response']['speech'] == payload['speech']
    assert entries[-1]['tools_used'] == ['search']


def test_builder_falls_back_to_stderr_without_json(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 2, '', 'fixture usage error'))
    builder = ToolBuilder.__new__(ToolBuilder)
    builder.mode = 'cloud'
    builder._log_research = lambda entry: None
    assert 'fixture usage error' in builder.research_via_jarvis('test research')


def comprehensive():
    spec = importlib.util.spec_from_file_location('cli_comprehensive_fixture', ROOT / 'tests/comprehensive_test.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    test = module.ComprehensiveTest.__new__(module.ComprehensiveTest)
    test.project_root = ROOT
    test.orchestrator = ROOT / 'orchestrator/orchestrator_v2.py'
    test.mode = 'cloud'
    test.tools_tested = set()
    return test


def test_comprehensive_preserves_failed_json_and_tool_evidence(monkeypatch):
    payload = {'ok': False, 'error': 'fixture engine failed', 'speech': 'The edit failed.', 'tools_used': ['craft_image']}
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, json.dumps(payload), ''))
    test = comprehensive()
    assert test.run_query('test edit') == payload
    assert test.tools_tested == {'craft_image'}


def test_comprehensive_falls_back_to_stderr_without_json(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 2, '', 'fixture usage error'))
    assert 'fixture usage error' in comprehensive().run_query('test edit')['error']
