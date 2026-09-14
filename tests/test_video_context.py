"""Video evidence survives routing, repeated reads, and Canvas follow-up context."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
sys.path.insert(0, str(ROOT / 'orchestrator'))

from executor import ToolExecutor  # noqa: E402
from orchestrator_v2 import Orchestrator  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
from router_v2 import build_tool_retrieval_signals, merge_tool_signal_names  # noqa: E402
from server_package_utils import load_server_package  # noqa: E402

load_server_package('video_context_server', ROOT / 'jarvis-web/server')
spec = importlib.util.spec_from_file_location(
    'video_context_server.services.followup_extractor',
    ROOT / 'jarvis-web/server/services/followup_extractor.py'
)
followup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(followup)


def evidence(source='stash://clips/first', start=0):
    return {
        'source_stash_ref': source, 'source_filename': 'recording.mp4',
        'mode': 'local', 'duration_seconds': 600, 'start_seconds': start,
        'end_seconds': start + 30, 'frame_timestamps': [start + 1, start + 29],
        'visual_status': 'complete', 'audio_status': 'unavailable',
        'analysis': 'At the sampled timestamp the screen displays CONNECTION FAILED. ' * 100,
        'transcript': '', 'partial': True,
        'warnings': ['Speech unavailable; only sampled frames support these findings.'],
    }


def test_video_preview_preserves_evidence_scope_and_discards_raw_fields():
    orch = Orchestrator.__new__(Orchestrator)
    data = {**evidence(), 'transcript': 'Spoken evidence. ' * 1000, 'raw': 'SECRET_SENTINEL' * 2000}
    text, total, shown, truncated = orch._build_llm_result_context_preview(
        'analyze_video', {'ok': True, 'data': data}
    )
    preview = json.loads(text)['llm_context_preview']['data_preview']
    assert preview['source_stash_ref'] == data['source_stash_ref']
    assert preview['frame_timestamps'] == [1, 29]
    assert preview['start_seconds'] == 0
    assert preview['partial'] is True
    assert preview['audio_status'] == 'unavailable'
    assert preview['warnings'] == data['warnings']
    assert 'CONNECTION FAILED' in preview['analysis']
    assert 'truncated' in preview['transcript']
    assert 'SECRET_SENTINEL' not in text
    assert shown <= 10000 < total and truncated


def test_repeated_video_ranges_keep_their_own_sources_and_timestamps():
    sources = [evidence(start=0), evidence(start=40), evidence('stash://clips/second', 20)]
    output = followup.extract_followup_data({'analyze_video': [{'ok': True, 'data': data} for data in sources]})
    rows = output['analyze_video']['results']
    assert [row['source_stash_ref'] for row in rows] == [item['source_stash_ref'] for item in sources]
    assert [row['start_seconds'] for row in rows] == [0, 40, 20]
    assert all(row['audio_status'] == 'unavailable' and row['partial'] for row in rows)
    assert sum(len(row['analysis']) for row in rows) <= 6000
    orch = Orchestrator.__new__(Orchestrator)
    prompt = orch._format_conversation_context('Save the findings to Canvas.', [
        {'role': 'assistant', 'content': 'Summary', 'tool_results': output,
         'tools_used': ['analyze_video']},
    ])
    assert 'recorded interval and sampled timestamps' in prompt
    assert 'start_seconds/end_seconds' in prompt
    assert 'stash://clips/second' in prompt
    # A restored thread must rediscover the reader even before live Tool RAG sync.
    signals = build_tool_retrieval_signals(prompt, {'canvas', 'analyze_video'})
    assert 'analyze_video' in signals.positive_tools
    names, _ = merge_tool_signal_names(['canvas'], signals, {'canvas', 'analyze_video'})
    assert names == ['canvas', 'analyze_video']


def test_video_schema_hint_works_before_persisted_index_sync_and_respects_exclusions():
    prompt = "[CONTEXT - Tool preference for this request]\nSelected tool hints: analyze_video.\n[END CONTEXT]\nUser's request: Explain this clip."
    enabled = {'analyze_video', 'transcribe_audio', 'canvas'}
    signals = build_tool_retrieval_signals(prompt, enabled)
    names, metadata = merge_tool_signal_names(['canvas'], signals, enabled)
    assert 'analyze_video' in names
    assert metadata['appended'] == ['analyze_video']
    blocked, _ = merge_tool_signal_names([], signals, enabled, excluded_tools=['analyze_video'])
    assert 'analyze_video' not in blocked
    disabled = build_tool_retrieval_signals(prompt, {'canvas'})
    assert 'analyze_video' not in disabled.positive_tools


def test_workflow_video_result_captures_input_and_executor_allows_reader_cleanup():
    result = {'ok': True, 'data': evidence()}
    PipelineExecutor._capture_source_arguments(result, 'analyze_video', {
        'source': 'stash://clips/first', 'question': 'Private prompt', 'start_seconds': 40,
    })
    assert result['_workflow_source_arguments'] == {'source': 'stash://clips/first'}
    assert ToolExecutor.__new__(ToolExecutor)._get_subprocess_timeout('analyze_video') == 630
