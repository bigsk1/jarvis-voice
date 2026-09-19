"""The foreground OpenClaw skill keeps its answer in Jarvis tool-card data."""

import importlib.util
from pathlib import Path


def test_openclaw_success_exposes_response_to_tool_card_without_changing_cli_fields(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'skills/openclaw.py'
    spec = importlib.util.spec_from_file_location('openclaw_foreground_skill', path)
    skill = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(skill)
    monkeypatch.setattr(skill, 'OPENCLAW_URL', 'https://private.example/v1/chat/completions')
    monkeypatch.setattr(skill, 'OPENCLAW_TOKEN', 'test-token')

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {'choices': [{'message': {'content': 'OpenClaw found three sources.'}}],
                    'model': 'openclaw/main', 'usage': {'total_tokens': 42}}

    monkeypatch.setattr(skill.requests, 'post', lambda *_args, **_kwargs: Response())
    result = skill.call_openclaw('Find sources', session='jarvis-review')

    assert result['ok'] is True
    assert result['response'] == 'OpenClaw found three sources.'
    assert result['speech'] == 'OpenClaw says: OpenClaw found three sources.'
    assert result['data'] == {
        'response': 'OpenClaw found three sources.',
        'model': 'openclaw/main',
        'session': 'jarvis-review',
        'priority': 'normal',
        'usage': {'total_tokens': 42},
    }
    assert 'no access to Jarvis' not in result['note']
    assert 'test-token' not in str(result)
