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
