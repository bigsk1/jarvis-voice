"""Explicit workflow precedence and unchanged foreground pipeline behavior."""
from types import SimpleNamespace

import pytest
import test_orchestrator_tool_turn_budget as fixture


@pytest.mark.parametrize('background', [True, False])
def test_matched_workflow_keeps_foreground_precedence_with_background_preferences(background):
    orchestrator = fixture.ToolTurnBudgetTests()._build_orchestrator(fail_on_calls=set())
    del orchestrator._try_workflow  # Exercise the real method, not the turn-budget fixture stub.
    workflow = {'id':'explicit', 'name':'Explicit fixture', 'steps': []}
    orchestrator.workflow_loader = SimpleNamespace(match=lambda text: workflow if text == '/fixture' else None)
    calls = []
    orchestrator.pipeline_executor = SimpleNamespace(execute=lambda *a, **kw: calls.append(a) or
                                                     {'ok':True,'speech':'Ordinary workflow ran','tools_used':[]})
    orchestrator.executor.excluded_tools = set()
    orchestrator.registry = SimpleNamespace(list_tools=lambda: [])
    orchestrator.background_context = object() if background else None
    assert orchestrator._try_workflow('Unmatched text') is None
    result = orchestrator._try_workflow('/fixture')
    assert result['ok'], result
    assert len(calls) == 1
    assert calls[0] == (workflow, '/fixture')


@pytest.mark.parametrize('leaked_receipt', [False, True])
def test_process_checks_foreground_workflow_result_for_background_receipts(leaked_receipt):
    orchestrator = fixture.ToolTurnBudgetTests()._build_orchestrator(fail_on_calls=set())
    del orchestrator._try_workflow
    workflow = {'id': 'explicit', 'name': 'Explicit fixture', 'steps': []}
    orchestrator.workflow_loader = SimpleNamespace(match=lambda text: workflow if text == '/fixture' else None)
    workflow_data = {'results': [{'ok': True, 'data': {'answer': 'Finished'}}]}
    if leaked_receipt:
        workflow_data['results'] = [{'result_kind': 'background_admission',
                                     'status': 'accepted', 'job_id': 'fixture-job'}]
    orchestrator.pipeline_executor = SimpleNamespace(execute=lambda *a, **kw:
        {'ok': True, 'speech': 'Workflow finished.', 'data': workflow_data, 'tools_used': []})
    orchestrator.executor.excluded_tools = set()
    orchestrator.registry = SimpleNamespace(list_tools=lambda: [])
    orchestrator.background_context = None

    result = orchestrator.process('/fixture')

    assert orchestrator.router.calls == 0
    assert orchestrator.executor.calls == 0
    if leaked_receipt:
        assert result['ok'] is False
        assert result['error_code'] == 'background_admission_unsupported'
    else:
        assert result['ok'] is True
        assert result['workflow_executed'] == 'explicit'
        assert result['data'] == workflow_data
