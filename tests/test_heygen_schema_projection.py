"""Actual LLM exports honor the current optional-provider configuration scope."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from config_loader import config_scope
from tool_schema import ToolSchema

ROOT = Path(__file__).resolve().parents[1]
EXPORTERS = ('to_openai_format', 'to_anthropic_format', 'to_ollama_description')


@pytest.fixture
def video_schema():
    return ToolSchema.from_json_file(str(ROOT / 'skills/generate_video.tool.json'))


def _export(schema, method):
    result = getattr(schema, method)()
    if isinstance(result, str):
        return result, None
    if method == 'to_openai_format':
        result = result['function']
        return result['description'], result['parameters']
    return result['description'], result['input_schema']


def _assert_hidden(schema, method):
    description, parameters = _export(schema, method)
    serialized = json.dumps((description, parameters)).lower()
    assert 'heygen' not in serialized
    assert '21:9' not in serialized
    assert '768p' not in serialized
    assert '2k' not in serialized
    if parameters is not None:
        properties = parameters['properties']
        assert properties['provider']['enum'] == ['xai', 'gemini']
        assert properties['aspect_ratio']['enum'] == [
            value for value in schema.parameters['properties']['aspect_ratio']['enum']
            if value != '21:9'
        ]
        assert properties['resolution']['enum'] == ['720p', '480p', '1080p', '4k']
        for name in ('prompt', 'image_url', 'video_url', 'negative_prompt', 'save', 'model'):
            assert properties[name] == schema.parameters['properties'][name]


def _assert_present(schema, method):
    description, parameters = _export(schema, method)
    assert 'HeyGen' in description
    if parameters is not None:
        for name in ('provider', 'aspect_ratio', 'resolution'):
            assert parameters['properties'][name] == schema.parameters['properties'][name]


@pytest.mark.parametrize('method', EXPORTERS)
@pytest.mark.parametrize('key', [None, '', '   '])
def test_missing_key_hides_optional_video_formats_from_actual_llm_exports(video_schema, method, key):
    original = deepcopy(video_schema.parameters)
    description = video_schema.description
    with config_scope('cloud', {'HEYGEN_API_KEY': key}):
        _assert_hidden(video_schema, method)
    assert video_schema.parameters == original
    assert video_schema.description == description


@pytest.mark.parametrize('method', EXPORTERS)
def test_same_schema_reprojects_on_mode_and_key_changes_without_mutation(video_schema, method):
    original = deepcopy(video_schema.parameters)
    description = video_schema.description
    with config_scope('cloud', {'HEYGEN_API_KEY': 'cloud-test-key'}):
        _assert_present(video_schema, method)
        with config_scope('local', {'HEYGEN_API_KEY': ''}):
            _assert_hidden(video_schema, method)
        _assert_present(video_schema, method)
        with config_scope('cloud', {'HEYGEN_API_KEY': ''}):
            _assert_hidden(video_schema, method)
        _assert_present(video_schema, method)
    assert video_schema.parameters == original
    assert video_schema.description == description
    assert 'cloud-test-key' not in repr(vars(video_schema))


@pytest.mark.parametrize('method', EXPORTERS)
def test_projection_does_not_rewrite_other_tools_with_similar_metadata(method):
    schema = ToolSchema(
        'another_video_tool', 'HeyGen 21:9 768p 2k remain useful here',
        {'type': 'object', 'properties': {'provider': {'type': 'string', 'enum': ['heygen']}}},
        'another_video_tool.py',
    )
    with config_scope('local', {'HEYGEN_API_KEY': ''}):
        description, parameters = _export(schema, method)
    assert schema.description in description
    if parameters is not None:
        assert parameters == schema.parameters
