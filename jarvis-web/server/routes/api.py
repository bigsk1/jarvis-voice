"""
API Routes for Jarvis Web UI
REST endpoints for status, tools, settings, and more
"""
import os
import json
import functools
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path

import yaml
from flask import Blueprint, jsonify, request, send_file, send_from_directory, abort
from werkzeug.datastructures import FileStorage
from ..services.log_explorer import get_log_explorer, LogExplorerError
from ..services.pdf_upload import (
    PDFUploadError,
    check_pdf_upload_rate,
    get_pdf_upload_max_bytes,
    save_pdf_upload,
)
from ..services.tool_discovery import get_tool_service
from ..services.usage_metadata import format_usage_markdown
from ..services.settings_manager import (
    CLOUD_TTS_PROVIDER_OPTIONS,
    LOCAL_TTS_PROVIDER_OPTIONS,
    get_settings_manager,
)
from ..config import (
    get_web_setting,
    JARVIS_ROOT,
    reload_web_config,
    DEFAULT_JARVIS_QA_WORD_LIMIT,
    DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT,
)
from webui_auth import is_auth_enabled
import sys

api_bp = Blueprint('api', __name__, url_prefix='/api')
# Ensure shared lib helpers are importable in this module
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))
sys.path.insert(0, str(JARVIS_ROOT / 'orchestrator'))
from model_catalog import get_provider_fallback_model
from intel_filename import validate_create_filename
from status_activity_logger import log_status_event
from tool_sync_status import read_tool_sync_status
from vision_multimodal import max_vision_images
from retention_cleanup import find_upload_stash_fallback
from router_prompt_catalog import available_router_prompt_versions
from stash_helper import get_stash_dir


def _get_jarvis_version():
    """Read Jarvis version from central VERSION file."""
    try:
        from version import JARVIS_VERSION
        return JARVIS_VERSION
    except ImportError:
        try:
            return (JARVIS_ROOT / 'VERSION').read_text().strip()
        except Exception:
            return '0.0.0'


def _apply_tts_provider_override(mode: str) -> str | None:
    """Return the validated per-mode Web UI TTS provider override."""
    from ..config import load_web_config

    web_config = load_web_config()
    mode_overrides = web_config.get(mode, {}) if isinstance(web_config, dict) else {}
    tts_provider = mode_overrides.get('tts_provider')
    allowed = LOCAL_TTS_PROVIDER_OPTIONS if mode == 'local' else CLOUD_TTS_PROVIDER_OPTIONS
    if tts_provider not in (None, *allowed):
        tts_provider = None
    return tts_provider


def _apply_router_prompt_override(mode: str) -> str | None:
    """Return the validated per-mode Web UI router prompt override."""
    from ..config import load_web_config

    web_config = load_web_config()
    mode_overrides = web_config.get(mode, {}) if isinstance(web_config, dict) else {}
    version = mode_overrides.get('router_prompt_version')
    return version if version in available_router_prompt_versions() else None


def _scoped_request_config(handler):
    """Run a Web API handler in its requested immutable config scope."""
    @functools.wraps(handler)
    def wrapper(*args, **kwargs):
        payload = request.get_json(silent=True) if request.method != 'GET' else None
        mode = (
            request.args.get('mode')
            or ((payload or {}).get('mode') if isinstance(payload, dict) else None)
            or request.form.get('mode')
            or get_web_setting('defaults.mode', 'cloud')
        )
        mode = str(mode).strip().lower()
        if mode not in ('cloud', 'local'):
            return jsonify({'ok': False, 'error': 'Mode must be "cloud" or "local"'}), 400
        tts_provider = _apply_tts_provider_override(mode)
        overrides = {}
        if tts_provider:
            overrides['TTS_PROVIDER'] = str(tts_provider)
        from config_loader import config_scope
        with config_scope(mode, overrides=overrides or None):
            return handler(*args, **kwargs)
    return wrapper


def _effective_elevenlabs_models(get_setting):
    final_model = str(
        get_setting('ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2') or ''
    ).strip() or 'eleven_multilingual_v2'
    status_model = str(
        get_setting('ELEVENLABS_STATUS_TTS_MODEL', final_model) or ''
    ).strip() or final_model
    return final_model, status_model


def _status_tts_cache_settings(provider, get_setting):
    """Return only settings that affect the selected provider's status audio."""
    if provider == 'elevenlabs':
        _, model = _effective_elevenlabs_models(get_setting)
        settings = {
            'voice': get_setting('ELEVENLABS_TTS_VOICE', ''),
            'model': model,
            'stability': get_setting('ELEVENLABS_TTS_STABILITY', '0.5'),
            'similarity_boost': get_setting('ELEVENLABS_TTS_SIMILARITY_BOOST', '0.75'),
        }
        if model != 'eleven_v3':
            settings.update({
                'style': get_setting('ELEVENLABS_TTS_STYLE', '0.5'),
                'use_speaker_boost': get_setting(
                    'ELEVENLABS_TTS_USE_SPEAKER_BOOST', 'true'
                ),
            })
        return settings
    if provider == 'xai':
        settings = {
            key: get_setting(key, '')
            for key in (
                'XAI_TTS_VOICE', 'XAI_TTS_LANGUAGE', 'XAI_TTS_CODEC',
                'XAI_TTS_SAMPLE_RATE', 'XAI_TTS_BIT_RATE',
            )
        }
        settings['XAI_TTS_MAX_CHARS'] = get_setting('XAI_TTS_MAX_CHARS', '5000')
        return settings
    if provider == 'qwen3-tts':
        return {
            key: get_setting(key, '')
            for key in (
                'QWEN3_TTS_VOICE', 'QWEN3_TTS_SPEED',
                'QWEN3_TTS_FORMAT', 'QWEN3_TTS_URL',
            )
        }
    if provider == 'kokoro':
        return {
            key: get_setting(key, '')
            for key in ('KOKORO_TTS_VOICE', 'KOKORO_TTS_SPEED', 'KOKORO_TTS_URL')
        }
    return {
        'voice': get_setting('VOICE', ''),
        'model': get_setting('TTS_MODEL', ''),
    }


def _status_tts_cache_paths(mode, provider, text, get_setting):
    settings = _status_tts_cache_settings(provider, get_setting)
    digest = hashlib.sha256(json.dumps({
        'version': 1,
        'mode': mode,
        'provider': provider,
        'text': text,
        'settings': settings,
    }, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    configured_cache_dir = str(
        get_setting('WEB_STATUS_TTS_CACHE_DIR', '') or ''
    ).strip()
    if configured_cache_dir:
        cache_dir = Path(configured_cache_dir).expanduser() / mode
    else:
        cache_dir = Path.home() / '.cache' / 'jarvis' / 'status-tts-web' / mode
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f'{digest}.audio', cache_dir / f'{digest}.mime'


def _write_status_tts_cache(audio_path: Path, mime_path: Path, content: bytes, content_type: str):
    for target, payload, binary in (
        (audio_path, content, True),
        (mime_path, content_type, False),
    ):
        with tempfile.NamedTemporaryFile(
            mode='wb' if binary else 'w',
            dir=target.parent,
            delete=False,
        ) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        os.replace(temporary, target)


# Path to generated images
IMAGES_PATH = JARVIS_ROOT / 'data' / 'generated_images'

# Path to generated music
MUSIC_PATH = JARVIS_ROOT / 'data' / 'generated_music'

# Path to generated videos
VIDEOS_PATH = JARVIS_ROOT / 'data' / 'generated_videos'

# Paths for prompts and workflows
WEB_DATA_PATH = JARVIS_ROOT / 'jarvis-web' / 'data'
PROMPTS_PATH = WEB_DATA_PATH / 'prompts'
WORKFLOWS_PATH = JARVIS_ROOT / 'data' / 'workflows'  # Workflows are in main data folder


def _workflow_step_summary(steps: list[dict]) -> list[dict]:
    """Build workflow step metadata for Web UI tooltips."""
    step_summary = []
    for step in steps:
        tool = step.get('tool', 'unknown')
        action = step.get('action', '')
        desc = step.get('description', '')
        step_text = f"{tool}.{action}" if action else tool
        if desc:
            step_text += f" - {desc}"
        step_summary.append({
            'step': step.get('step', len(step_summary) + 1),
            'tool': tool,
            'action': action,
            'description': desc,
            'display': step_text,
        })
    return step_summary


def _workflow_record(wf_id: str, wf_data: dict) -> dict:
    steps = wf_data.get('steps', [])
    triggers = wf_data.get('triggers', {})
    explicit_cmds = triggers.get('explicit', [])
    return {
        'id': wf_id,
        'name': wf_data.get('name', wf_id),
        'description': wf_data.get('description', ''),
        'version': wf_data.get('version', '1.0'),
        'triggers': explicit_cmds,
        'step_count': len(steps),
        'tools_used': list(dict.fromkeys(s.get('tool', '') for s in steps)),
        'steps': _workflow_step_summary(steps),
        'icon': '🔄',
    }


def _web_workflow_availability(workflow: dict) -> dict:
    """Resolve workflow availability against the Web-visible tool surface."""
    from workflow_availability import check_workflow_availability

    tools = get_tool_service().get_tools(include_blocked=True)
    available = {
        tool['name']
        for tool in tools
        if tool.get('name')
        and tool.get('enabled', True)
        and tool.get('available', True)
        and not tool.get('blocked', False)
    }
    blocked = {
        tool['name']
        for tool in tools
        if tool.get('name') and tool.get('blocked', False)
    }
    return check_workflow_availability(
        workflow,
        available_tools=available,
        excluded_tools=blocked,
    )


def _resolve_workflow(loader, workflow_id: str) -> dict | None:
    workflow = loader.get_workflow(workflow_id)
    if workflow:
        return workflow
    search_trigger = workflow_id if workflow_id.startswith('/') else f'/{workflow_id}'
    for candidate in loader.workflows.values():
        triggers = candidate.get('triggers', {}).get('explicit', [])
        if search_trigger in triggers or workflow_id in triggers:
            return candidate
    return None


def _parse_prompt_frontmatter(content: str) -> tuple[str, list[str]]:
    """Return prompt body and optional tool_hints from YAML frontmatter."""
    text = content or ''
    stripped = text.lstrip()
    lines = stripped.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        return text, []

    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == '---'),
        None,
    )
    if closing_index is None:
        return text, []

    frontmatter_text = ''.join(lines[1:closing_index])
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f'Invalid prompt YAML frontmatter: {exc}') from exc
    if not isinstance(frontmatter, dict):
        raise ValueError('Prompt YAML frontmatter must be a mapping')

    raw_tool_hints = frontmatter.get('tool_hints', [])
    if raw_tool_hints is None:
        raw_tool_hints = []
    if not isinstance(raw_tool_hints, list):
        raise ValueError('Prompt frontmatter tool_hints must be a list of tool names')

    tool_hints = []
    for hint in raw_tool_hints:
        if not isinstance(hint, str) or not hint.strip():
            raise ValueError('Prompt frontmatter tool_hints must contain non-empty strings')
        name = hint.strip()
        if name not in tool_hints:
            tool_hints.append(name)

    body = ''.join(lines[closing_index + 1:]).lstrip('\r\n')
    return body, tool_hints


def _resolve_prompt_file(name: str) -> Path | None:
    """Personal prompts override shared prompts with the same stem."""
    if name.casefold() == 'readme':
        return None
    personal_file = PROMPTS_PATH / 'personal' / f'{name}.md'
    if personal_file.exists():
        return personal_file
    shared_file = PROMPTS_PATH / f'{name}.md'
    if shared_file.exists():
        return shared_file
    return None


def _iter_prompt_files():
    """Yield (stem, path) for shared and personal prompt files."""
    prompts: dict[str, Path] = {}
    if PROMPTS_PATH.exists():
        for prompt_file in PROMPTS_PATH.glob('*.md'):
            prompts[prompt_file.stem] = prompt_file
        personal_dir = PROMPTS_PATH / 'personal'
        if personal_dir.exists():
            for prompt_file in personal_dir.glob('*.md'):
                if prompt_file.name.casefold() == 'readme.md':
                    continue
                prompts[prompt_file.stem] = prompt_file
    for stem in sorted(prompts):
        yield stem, prompts[stem]


def _load_prompt_record(name: str, prompt_file: Path) -> dict:
    content = prompt_file.read_text()
    body, tool_hints = _parse_prompt_frontmatter(content)
    lines = body.strip().split('\n')
    description = ''
    if lines and lines[0].startswith('#'):
        description = lines[0].lstrip('#').strip()

    key_points = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if line.startswith(('-', '*', '•')) or (len(line) > 2 and line[0].isdigit() and line[1] in '.):'):
            point = line.lstrip('-*•0123456789.) ').strip()
            if point and len(point) > 3:
                key_points.append(point[:80])
        elif line.startswith('##'):
            key_points.append(line.lstrip('#').strip())
        if len(key_points) >= 5:
            break

    if not key_points:
        for line in lines[1:6]:
            line = line.strip()
            if line and not line.startswith('#'):
                key_points.append(line[:80])

    record = {
        'name': name,
        'description': description,
        'content': body,
        'key_points': key_points[:5],
    }
    if tool_hints:
        record['tool_hints'] = tool_hints
    return record


def _prompt_is_available(record: dict, tools_by_name: dict[str, dict]) -> bool:
    """Hide a single-tool prompt when its required hinted tool is unavailable."""
    tool_hints = record.get('tool_hints') or []
    if len(tool_hints) != 1:
        return True

    tool = tools_by_name.get(tool_hints[0])
    return bool(
        tool
        and tool.get('enabled', True)
        and tool.get('available', True)
        and not tool.get('blocked', False)
    )


def _prompt_tools_by_name() -> dict[str, dict]:
    """Return the current Web UI tool registry keyed by exact tool name."""
    return {
        tool['name']: tool
        for tool in get_tool_service().get_tools(include_blocked=True)
        if tool.get('name')
    }


@api_bp.route('/status', methods=['GET'])
def get_status():
    """Health check and basic status info"""
    requested_mode = str(request.args.get('mode', '')).strip().lower()
    current_mode = get_web_setting('defaults.mode', 'cloud')
    settings = get_settings_manager(current_mode)
    warning_mode = requested_mode if requested_mode in {'cloud', 'local'} else settings.mode
    tool_service = get_tool_service(warning_mode)
    tool_sync_status = read_tool_sync_status(warning_mode, project_root=JARVIS_ROOT)
    tool_sync_warning = (
        tool_sync_status
        if tool_sync_status and tool_sync_status.get('status') == 'failed'
        else None
    )
    
    from ..app import get_startup_mode

    return jsonify({
        'ok': True,
        'status': 'running',
        'version': _get_jarvis_version(),
        'mode': settings.mode,
        'startup_mode': get_startup_mode(),
        'tools_count': tool_service.get_tool_count(),
        'tool_sync_warning': tool_sync_warning,
        'features': {
            'tts': get_web_setting('audio.tts_enabled', False),
            'stt': get_web_setting('audio.stt_enabled', False),
            'auth': is_auth_enabled()  # Dynamic from WEBUI_PASSWORD env var
        }
    })


@api_bp.route('/logs/folders', methods=['GET'])
def list_log_folders():
    """List folders under logs/ that contain supported view-only files."""
    explorer = get_log_explorer()
    return jsonify({
        'ok': True,
        'folders': explorer.list_folders(),
    })


@api_bp.route('/logs/files', methods=['GET'])
def list_log_files():
    """List supported log files in a folder with filtering and pagination."""
    explorer = get_log_explorer()
    folder = request.args.get('folder', '')
    search = request.args.get('search', '')
    extension = request.args.get('extension', '')
    sort = request.args.get('sort', 'newest')
    days = request.args.get('days', type=int)
    offset = max(request.args.get('offset', 0, type=int) or 0, 0)
    limit = min(max(request.args.get('limit', 50, type=int) or 50, 1), 200)

    try:
        payload = explorer.list_files(
            folder=folder,
            search=search,
            extension=extension,
            sort=sort,
            days=days,
            offset=offset,
            limit=limit,
        )
    except LogExplorerError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

    return jsonify({
        'ok': True,
        **payload,
    })


@api_bp.route('/logs/content', methods=['GET'])
def get_log_content():
    """Read a supported log file with lazy-loaded content."""
    explorer = get_log_explorer()
    relative_path = request.args.get('path', '')
    search = request.args.get('search', '')
    offset = max(request.args.get('offset', 0, type=int) or 0, 0)
    limit = min(max(request.args.get('limit', 50, type=int) or 50, 1), 200)

    try:
        payload = explorer.read_file(relative_path, offset=offset, limit=limit, search=search)
    except LogExplorerError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

    return jsonify({
        'ok': True,
        **payload,
    })


@api_bp.route('/tools', methods=['GET'])
@_scoped_request_config
def list_tools():
    """List tools for the explicitly requested cloud/local mode."""
    tool_service = get_tool_service()
    summary_only = request.args.get('summary', 'false').lower() == 'true'
    include_blocked = request.args.get('include_blocked', 'true').lower() == 'true'
    
    if summary_only:
        tools = tool_service.get_tools_summary()
    else:
        tools = tool_service.get_tools(include_blocked=include_blocked)
    
    return jsonify({
        'ok': True,
        'count': len(tools),
        'stats': tool_service.get_stats(),
        'tools': tools
    })


@api_bp.route('/tools/<name>', methods=['GET'])
@_scoped_request_config
def get_tool(name):
    """Get tool details for the explicitly requested cloud/local mode."""
    tool_service = get_tool_service()
    tool = tool_service.get_tool(name)
    
    if tool:
        return jsonify({
            'ok': True,
            'tool': tool
        })
    else:
        return jsonify({
            'ok': False,
            'error': f'Tool not found: {name}'
        }), 404


@api_bp.route('/tools/refresh', methods=['POST'])
@_scoped_request_config
def refresh_tools():
    """Reload tools from disk for the explicitly requested mode."""
    tool_service = get_tool_service()
    tool_service.refresh()
    
    return jsonify({
        'ok': True,
        'message': 'Tools refreshed',
        'count': tool_service.get_tool_count()
    })


@api_bp.route('/settings', methods=['GET'])
@_scoped_request_config
def get_settings():
    """Get current settings for UI"""
    # REST requests do not carry the Socket.IO session, so callers should pass
    # the active session mode explicitly. Keep the persisted default as a
    # backward-compatible fallback for older clients.
    current_mode = request.args.get('mode') or get_web_setting('defaults.mode', 'cloud')
    if current_mode not in ('cloud', 'local'):
        return jsonify({'ok': False, 'error': 'Mode must be "cloud" or "local"'}), 400
    settings = get_settings_manager(current_mode)
    
    return jsonify({
        'ok': True,
        'settings': settings.get_settings_for_ui(),
        # Legacy format for backward compat
        'jarvis': settings.get_settings_with_status(),
        'web': settings.get_web_settings()
    })


@api_bp.route('/settings/schema', methods=['GET'])
@_scoped_request_config
def get_settings_schema():
    """Get settings schema for UI form generation"""
    settings = get_settings_manager()
    
    return jsonify({
        'ok': True,
        'schema': settings.get_schema()
    })


@api_bp.route('/settings/system', methods=['GET'])
@_scoped_request_config
def get_system_config():
    """Get read-only system config values from current mode's env file"""
    from ..config import load_jarvis_config, get_jarvis_setting
    
    # Use mode from query param or fall back to default
    mode = request.args.get('mode') or get_web_setting('defaults.mode', 'cloud')
    load_jarvis_config(mode)
    _apply_tts_provider_override(mode)
    tool_rag_limit_key = 'LOCAL_TOOL_RAG_LIMIT' if mode == 'local' else 'CLOUD_TOOL_RAG_LIMIT'
    tool_rag_limit_default = '6' if mode == 'local' else '15'
    
    # Return key system settings (read-only, informational)
    config = {
        # LLM Settings
        'LLM_PROVIDER': get_jarvis_setting('LLM_PROVIDER', 'ollama' if mode == 'local' else 'xai'),
        'JARVIS_ROUTER_PROMPT_VERSION': (
            _apply_router_prompt_override(mode)
            or get_jarvis_setting('JARVIS_ROUTER_PROMPT_VERSION', 'v1')
        ),
        
        # Thresholds (important!)
        'TOOL_SIMILARITY_THRESHOLD': get_jarvis_setting('TOOL_SIMILARITY_THRESHOLD', '0.0'),
        'TOOL_SIMILARITY_THRESHOLD_FULL': get_jarvis_setting('TOOL_SIMILARITY_THRESHOLD_FULL', ''),
        'TOOL_RAG_LIMIT': get_jarvis_setting(tool_rag_limit_key, tool_rag_limit_default),
        'SEMANTIC_SIMILARITY_THRESHOLD': get_jarvis_setting('SEMANTIC_SIMILARITY_THRESHOLD', '0.30'),
        
        # TTS/Audio (mode-specific)
        'TTS_PROVIDER': get_jarvis_setting('TTS_PROVIDER', 'qwen3-tts' if mode == 'local' else 'elevenlabs'),
        'STATUS_UPDATES_ENABLED': get_jarvis_setting('STATUS_UPDATES_ENABLED', 'true'),
        'STATUS_UPDATE_INTERVAL': get_jarvis_setting('STATUS_UPDATE_INTERVAL', '18'),
        'STATUS_UPDATE_DEBOUNCE_MS': get_jarvis_setting('STATUS_UPDATE_DEBOUNCE_MS', '250'),
        'STATUS_CACHE_ENABLED': get_jarvis_setting('STATUS_CACHE_ENABLED', 'true'),
        'STATUS_LLM_ENABLED': get_jarvis_setting('STATUS_LLM_ENABLED', 'false'),
        'STATUS_LLM_PROVIDER': get_jarvis_setting('STATUS_LLM_PROVIDER', 'ollama' if mode == 'local' else 'openai'),
        'STATUS_LLM_MODEL': get_jarvis_setting('STATUS_LLM_MODEL', ''),
        'STATUS_LLM_DEADLINE_MS': get_jarvis_setting('STATUS_LLM_DEADLINE_MS', '1000'),
        
        # Features
        'JARVIS_INTELLIGENCE': get_jarvis_setting('JARVIS_INTELLIGENCE', 'true'),
        'OPENCODE_BASE_URL': get_jarvis_setting('OPENCODE_BASE_URL', 'http://localhost:4096'),
    }
    
    # Add mode-specific model info
    if mode == 'local':
        config['OLLAMA_MODEL'] = get_jarvis_setting('OLLAMA_MODEL', 'qwen3')
        config['OLLAMA_BASE_URL'] = get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434')
        config['ALLOW_OLLAMA_CLOUD'] = get_jarvis_setting('ALLOW_OLLAMA_CLOUD', 'false')
        config['KOKORO_TTS_URL'] = get_jarvis_setting('KOKORO_TTS_URL', '')
        config['KOKORO_TTS_VOICE'] = get_jarvis_setting('KOKORO_TTS_VOICE', '')
        config['QWEN3_TTS_URL'] = get_jarvis_setting('QWEN3_TTS_URL', '')
        config['QWEN3_TTS_VOICE'] = get_jarvis_setting('QWEN3_TTS_VOICE', '')
        config['QWEN3_TTS_FORMAT'] = get_jarvis_setting('QWEN3_TTS_FORMAT', 'mp3')
    else:
        config['XAI_MODEL'] = get_jarvis_setting('XAI_MODEL', '')
        config['XAI_AUTH_MODE'] = get_jarvis_setting('XAI_AUTH_MODE', 'auto')
        config['XAI_OAUTH_MODEL'] = get_jarvis_setting('XAI_OAUTH_MODEL', 'grok-build')
        config['XAI_SEARCH'] = get_jarvis_setting('XAI_SEARCH', 'false')
        config['ANTHROPIC_MODEL'] = get_jarvis_setting('ANTHROPIC_MODEL', '')
        config['OPENAI_MODEL'] = get_jarvis_setting('OPENAI_MODEL', '')
        # Ollama-cloud-primary (safe metadata only; never OLLAMA_API_KEY)
        config['OLLAMA_CLOUD_MODEL'] = get_jarvis_setting('OLLAMA_CLOUD_MODEL', '')
        config['OLLAMA_BASE_URL'] = get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434')
        config['TTS_MODEL'] = get_jarvis_setting('TTS_MODEL', 'gpt-4o-mini-tts')
        config['VOICE'] = get_jarvis_setting('VOICE', 'alloy')
        config['QWEN3_TTS_URL'] = get_jarvis_setting('QWEN3_TTS_URL', '')
        config['QWEN3_TTS_VOICE'] = get_jarvis_setting('QWEN3_TTS_VOICE', '')
        config['QWEN3_TTS_FORMAT'] = get_jarvis_setting('QWEN3_TTS_FORMAT', 'mp3')
        config['ELEVENLABS_TTS_VOICE'] = get_jarvis_setting('ELEVENLABS_TTS_VOICE', '')
        (
            config['ELEVENLABS_TTS_MODEL'],
            config['ELEVENLABS_STATUS_TTS_MODEL'],
        ) = _effective_elevenlabs_models(get_jarvis_setting)
        config['XAI_TTS_VOICE'] = get_jarvis_setting('XAI_TTS_VOICE', 'eve')
        config['XAI_TTS_LANGUAGE'] = get_jarvis_setting('XAI_TTS_LANGUAGE', 'en')
        config['XAI_TTS_CODEC'] = get_jarvis_setting('XAI_TTS_CODEC', 'mp3')
        config['XAI_TTS_TIMEOUT'] = get_jarvis_setting('XAI_TTS_TIMEOUT', '180')
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'config': {
            **config,
            
            # Media providers
            'IMAGE_TOOL_PROVIDER': get_jarvis_setting('IMAGE_TOOL_PROVIDER', 'gemini'),
            'VIDEO_TOOL_PROVIDER': get_jarvis_setting('VIDEO_TOOL_PROVIDER', 'xai'),
            'MUSIC_TOOL_PROVIDER': get_jarvis_setting('MUSIC_TOOL_PROVIDER', 'elevenlabs'),
            'JARVIS_RESPONSE_STYLE': get_jarvis_setting('JARVIS_RESPONSE_STYLE', 'auto'),
            'JARVIS_QA_WORD_LIMIT': get_jarvis_setting('JARVIS_QA_WORD_LIMIT', str(DEFAULT_JARVIS_QA_WORD_LIMIT)),
            'JARVIS_MULTI_TURN_WORD_LIMIT': get_jarvis_setting('JARVIS_MULTI_TURN_WORD_LIMIT', str(DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT)),
            'JARVIS_COMPLETION_GUARD_ENABLED': get_jarvis_setting('JARVIS_COMPLETION_GUARD_ENABLED', 'false'),
            'JARVIS_COMPLETION_GUARD_MODE': get_jarvis_setting('JARVIS_COMPLETION_GUARD_MODE', 'manual'),
            'JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD': get_jarvis_setting('JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD', '0.70'),
            'JARVIS_COMPLETION_GUARD_EVAL_PROVIDER': get_jarvis_setting('JARVIS_COMPLETION_GUARD_EVAL_PROVIDER', 'ollama' if mode == 'local' else 'openai'),
            'JARVIS_COMPLETION_GUARD_EVAL_MODEL': get_jarvis_setting(
                'JARVIS_COMPLETION_GUARD_EVAL_MODEL',
                get_jarvis_setting('OLLAMA_MODEL', 'qwen3.5:latest') if mode == 'local' else get_provider_fallback_model('openai'),
            ),
            
            # Feedback/Evolution System
            'FEEDBACK_RANDOM_ENABLED': get_jarvis_setting('FEEDBACK_RANDOM_ENABLED', 'false'),
            'FEEDBACK_RANDOM_CHANCE': get_jarvis_setting('FEEDBACK_RANDOM_CHANCE', '0.0'),
            'FEEDBACK_PROVIDER': get_jarvis_setting('FEEDBACK_PROVIDER', 'anthropic'),
            
            # System
            'JARVIS_TIMEZONE': get_jarvis_setting('JARVIS_TIMEZONE', 'America/Los_Angeles'),
            'JARVIS_DEFAULT_LOCATION': get_jarvis_setting('JARVIS_DEFAULT_LOCATION', 'Hillsboro, Oregon'),
            'JARVIS_DEFAULT_POSTAL_CODE': get_jarvis_setting('JARVIS_DEFAULT_POSTAL_CODE', ''),
        }
    })


@api_bp.route('/settings/web', methods=['PUT'])
@_scoped_request_config
def update_web_settings():
    """Update web UI settings/overrides"""
    data = request.get_json()
    
    if not data:
        return jsonify({'ok': False, 'error': 'No data provided'}), 400

    # The settings modal can be showing a different mode than the stale
    # persisted default. Persist its explicit selection even when the active
    # socket session is already in that mode and no mode:set event will fire.
    data = dict(data)
    requested_mode = data.pop('mode', None)
    if requested_mode is not None and requested_mode not in ('cloud', 'local'):
        return jsonify({'ok': False, 'error': 'Mode must be "cloud" or "local"'}), 400

    settings = get_settings_manager()

    structured = any(k in data for k in [
        'llm_provider', 'llm_model', 'router_prompt_version', 'image_provider', 'video_provider',
        'music_provider',
        'response_style', 'tool_rag_limit', 'qa_word_limit', 'multi_turn_word_limit',
        'completion_guard_enabled', 'completion_guard_mode',
        'completion_guard_ticket_on_fail', 'completion_guard_show_ui_prompt',
        'completion_guard_include_qa', 'completion_guard_include_tool_tasks',
        'completion_guard_auto_threshold', 'completion_guard_eval_provider', 'completion_guard_eval_model',
        'tts_provider', 'tool_similarity', 'memory_similarity', 'tts_enabled'
    ])

    if structured:
        # Validate the full payload against the REQUESTED mode before
        # persisting anything (including the mode itself) so a rejected
        # request leaves web_config.json completely untouched.
        from ..services.settings_manager import SettingsValidationError
        if requested_mode is not None:
            settings.mode = requested_mode  # in-memory only; persisted below
        try:
            settings.validate_web_overrides(data)
        except SettingsValidationError as e:
            return jsonify({'ok': False, **e.to_dict()}), 400

    if requested_mode is not None and not settings.set_mode(requested_mode):
        return jsonify({
            'ok': False,
            'error': 'Failed to persist mode in jarvis-web/config/web_config.json'
        }), 500

    # Use new override system if structured data provided
    if structured:
        try:
            success = settings.save_web_overrides(data)
        except SettingsValidationError as e:
            # save_web_overrides re-validates before mutating; nothing saved.
            return jsonify({'ok': False, **e.to_dict()}), 400
        # Force reload config cache so changes take effect immediately
        reload_web_config()
        return jsonify({
            'ok': success,
            'message': 'Settings saved' if success else 'Failed to save'
        })
    
    # Legacy path-based updates
    updated = []
    for path, value in data.items():
        if settings.update_web_setting(path, value):
            updated.append(path)
    
    return jsonify({
        'ok': True,
        'updated': updated
    })


@api_bp.route('/settings/reset', methods=['POST'])
@_scoped_request_config
def reset_settings():
    """Reset web overrides to the explicitly scoped mode's env defaults."""
    settings = get_settings_manager()
    success = settings.reset_to_defaults()
    
    return jsonify({
        'ok': success,
        'message': 'Reset to defaults' if success else 'Failed to reset'
    })


@api_bp.route('/settings/models/<provider>', methods=['GET'])
@_scoped_request_config
def get_provider_models(provider):
    """Get available models for a provider"""
    mode = request.args.get('mode') or get_web_setting('defaults.mode', 'cloud')

    if provider == 'ollama':
        from ..services.settings_manager import fetch_ollama_models
        from ..config import load_jarvis_config, get_jarvis_setting, load_web_config
        load_jarvis_config(mode)
        mode_config = load_web_config().get(mode, {})
        selected_models = []
        effective_llm_provider = (
            mode_config.get('llm_provider')
            or get_jarvis_setting('LLM_PROVIDER', 'ollama' if mode == 'local' else 'xai')
        )
        if effective_llm_provider == 'ollama' and mode_config.get('llm_model'):
            selected_models.append(mode_config['llm_model'])
        effective_guard_provider = (
            mode_config.get('completion_guard_eval_provider')
            or get_jarvis_setting(
                'JARVIS_COMPLETION_GUARD_EVAL_PROVIDER',
                'ollama' if mode == 'local' else 'openai',
            )
        )
        if effective_guard_provider == 'ollama' and mode_config.get('completion_guard_eval_model'):
            selected_models.append(mode_config['completion_guard_eval_model'])
        models = fetch_ollama_models(
            get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434'),
            mode=mode,
            selected_models=selected_models,
        )
        default_model = get_settings_manager(mode)._ollama_env_default_model()
    else:
        from ..config import load_jarvis_config, get_jarvis_setting
        load_jarvis_config(mode)
        settings = get_settings_manager(mode)
        env_key_map = {
            'openai': 'OPENAI_MODEL',
            'anthropic': 'ANTHROPIC_MODEL',
            'xai': 'XAI_MODEL',
        }
        current_model = get_jarvis_setting(env_key_map.get(provider, ''), '').strip() if provider in env_key_map else ''
        models = settings._get_model_options_with_current(provider, current_model)
        default_model = settings._get_env_provider_model(provider)
    return jsonify({
        'ok': True,
        'provider': provider,
        'models': models,
        'default_model': default_model,
    })


@api_bp.route('/tts/usage', methods=['GET'])
@_scoped_request_config
def get_tts_usage():
    """Get TTS usage/quota for ElevenLabs (only applicable for cloud mode with ElevenLabs)"""
    import requests as http_requests
    from ..config import load_jarvis_config, get_jarvis_setting
    
    # Get mode from query param
    mode = request.args.get('mode', 'cloud')
    load_jarvis_config(mode)
    _apply_tts_provider_override(mode)
    
    tts_provider = get_jarvis_setting('TTS_PROVIDER', 'elevenlabs' if mode == 'cloud' else 'qwen3-tts')
    
    # Only fetch for ElevenLabs
    if tts_provider != 'elevenlabs':
        return jsonify({
            'ok': False,
            'provider': tts_provider,
            'message': 'Usage tracking only available for ElevenLabs'
        })
    
    api_key = get_jarvis_setting('ELEVENLABS_API_KEY', '')
    if not api_key:
        return jsonify({
            'ok': False,
            'provider': 'elevenlabs',
            'error': 'ELEVENLABS_API_KEY not configured'
        })
    
    try:
        response = http_requests.get(
            "https://api.elevenlabs.io/v1/user",
            headers={"xi-api-key": api_key},
            timeout=10
        )
        response.raise_for_status()
        user_data = response.json()
        
        subscription = user_data.get('subscription', {})
        character_count = subscription.get('character_count', 0)
        character_limit = subscription.get('character_limit', 0)
        
        # Calculate percentage and remaining
        percentage_used = (character_count / character_limit * 100) if character_limit > 0 else 0
        remaining = character_limit - character_count
        
        return jsonify({
            'ok': True,
            'provider': 'elevenlabs',
            'usage': {
                'used': character_count,
                'limit': character_limit,
                'remaining': remaining,
                'percentage_used': round(percentage_used, 1),
                'tier': subscription.get('tier', 'unknown'),
                'next_reset': subscription.get('next_character_count_reset_unix', None)
            }
        })
        
    except http_requests.exceptions.Timeout:
        return jsonify({
            'ok': False,
            'provider': 'elevenlabs',
            'error': 'Request timed out'
        })
    except http_requests.exceptions.RequestException as e:
        return jsonify({
            'ok': False,
            'provider': 'elevenlabs',
            'error': f'API request failed: {str(e)}'
        })
    except Exception as e:
        return jsonify({
            'ok': False,
            'provider': 'elevenlabs',
            'error': str(e)
        })


@api_bp.route('/serpapi/account', methods=['GET'])
@_scoped_request_config
def get_serpapi_account():
    """Return sanitized SerpApi quota data for the selected mode."""
    import requests as http_requests
    from ..config import get_jarvis_setting

    api_key = str(get_jarvis_setting('SERP_API_KEY', '') or '').strip()
    configured = bool(api_key)
    base_payload = {
        'ok': False,
        'provider': 'serpapi',
        'configured': configured,
        'valid': False,
    }

    # Do not make an outbound request for a missing or obvious example value.
    normalized_key = api_key.upper()
    if (
        not api_key
        or len(api_key) < 16
        or 'YOUR_' in normalized_key
        or 'REPLACE' in normalized_key
    ):
        return jsonify(base_payload)

    try:
        response = http_requests.get(
            'https://serpapi.com/account.json',
            params={'api_key': api_key},
            timeout=10,
        )
    except http_requests.exceptions.Timeout:
        return jsonify({**base_payload, 'reason': 'timeout'})
    except http_requests.exceptions.RequestException:
        return jsonify({**base_payload, 'reason': 'unavailable'})

    if response.status_code != 200:
        return jsonify({**base_payload, 'reason': 'validation_failed'})

    try:
        account = response.json()
    except (TypeError, ValueError):
        return jsonify({**base_payload, 'reason': 'invalid_response'})

    if not isinstance(account, dict) or not str(account.get('account_status') or '').strip():
        return jsonify({**base_payload, 'reason': 'invalid_response'})

    def safe_int(value):
        if isinstance(value, bool) or value in (None, ''):
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return None

    monthly_limit = safe_int(account.get('searches_per_month'))
    monthly_used = safe_int(account.get('this_month_usage'))
    plan_remaining = safe_int(account.get('plan_searches_left'))
    extra_credits = safe_int(account.get('extra_credits'))
    total_remaining = safe_int(account.get('total_searches_left'))
    if total_remaining is None and (plan_remaining is not None or extra_credits is not None):
        total_remaining = (plan_remaining or 0) + (extra_credits or 0)

    percentage_used = None
    if monthly_limit and monthly_used is not None:
        percentage_used = round(monthly_used / monthly_limit * 100, 1)

    return jsonify({
        **base_payload,
        'ok': True,
        'valid': True,
        'account': {
            'status': str(account.get('account_status') or '').strip()[:64],
            'plan_name': str(account.get('plan_name') or '').strip()[:128] or None,
            'renewal_date': str(account.get('plan_renewal_date') or '').strip()[:64] or None,
        },
        'quota': {
            'monthly_used': monthly_used,
            'monthly_limit': monthly_limit,
            'monthly_remaining': total_remaining,
            'percentage_used': percentage_used,
            'extra_credits': extra_credits,
            'this_hour_searches': safe_int(account.get('this_hour_searches')),
            'hourly_limit': safe_int(account.get('account_rate_limit_per_hour')),
        },
    })


_OLLAMA_CLOUD_STATUS_CACHE = {}
_OLLAMA_CLOUD_STATUS_TTL_SECONDS = 45

_OLLAMA_MODEL_CONTEXT_CACHE = {}
_OLLAMA_MODEL_CONTEXT_TTL_SECONDS = 600


@api_bp.route('/xai/oauth-status', methods=['GET'])
@_scoped_request_config
def get_xai_oauth_status_route():
    """Return sanitized xAI API-key/OAuth readiness for the System tab."""
    from ..config import load_jarvis_config, get_jarvis_setting
    from xai_oauth import XaiOAuthError, get_xai_auth_mode, get_xai_oauth_status

    mode = request.args.get('mode', 'cloud')
    load_jarvis_config(mode)
    api_key = get_jarvis_setting('XAI_API_KEY', '')
    api_key_present = bool(str(api_key or '').strip())
    native_search_requested = (
        str(get_jarvis_setting('XAI_SEARCH', 'false') or '').strip().lower() == 'true'
    )
    payload = {
        'provider': 'xai',
        'dashboard_url': 'https://grok.com',
        'usage_available': False,
        'usage_note': 'xAI does not expose subscription quota through this API',
        'api_key_present': api_key_present,
        'native_search_requested': native_search_requested,
    }
    try:
        auth_mode = get_xai_auth_mode(
            api_key,
            get_jarvis_setting('XAI_AUTH_MODE', 'auto'),
        )
    except XaiOAuthError as exc:
        return jsonify({
            **payload,
            'connection_mode': 'invalid',
            'signed_in': False,
            'status': 'unavailable',
            'reason': str(exc),
        })

    if auth_mode == 'api_key':
        return jsonify({
            **payload,
            'connection_mode': 'api_key',
            'signed_in': api_key_present,
            'status': 'available' if api_key_present else 'unavailable',
            'reason': None if api_key_present else 'XAI_API_KEY missing',
            'native_search_available': native_search_requested and api_key_present,
        })

    return jsonify({
        **payload,
        **get_xai_oauth_status(check_models=True, check_usage=True),
        'connection_mode': 'oauth',
        'native_search_available': False,
        'native_search_note': (
            'XAI_SEARCH requires API-key auth; use Jarvis search tools while OAuth is active'
            if native_search_requested
            else None
        ),
    })


def _extract_ollama_context_length(show_data):
    """Pull the context window from an Ollama /api/show payload.

    The architecture-specific key (e.g. ``qwen3.context_length``) lives under
    ``model_info``. Falls back to any ``*context_length`` key. Returns an int or
    ``None`` when the daemon does not report it (common for proxied cloud models).
    """
    if not isinstance(show_data, dict):
        return None
    info = show_data.get('model_info')
    if isinstance(info, dict):
        for key, value in info.items():
            if isinstance(key, str) and key.endswith('context_length'):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
    return None


def _validate_ollama_signin_url(url):
    """Only allow https://ollama.com[...] sign-in URLs into the UI payload."""
    if not url or not isinstance(url, str):
        return None
    candidate = url.strip()
    if candidate.startswith('https://ollama.com/') or candidate == 'https://ollama.com':
        return candidate
    return None


@api_bp.route('/ollama/cloud-status', methods=['GET'])
@_scoped_request_config
def get_ollama_cloud_status():
    """Lazy, best-effort Ollama host/account readiness for the System tab.

    Cloud mode uses one of two exclusive paths:

    - ``OLLAMA_API_KEY`` set → report direct ``https://ollama.com`` configuration
    - no key → ``POST {OLLAMA_BASE_URL}/api/me`` on the configured daemon

    Returns a sanitized shape only; never exposes key values or raw profile data.
    """
    import time
    import requests as http_requests
    from ..config import load_jarvis_config, get_jarvis_setting
    from ollama_utils import get_ollama_api_key

    mode = request.args.get('mode', 'cloud')
    load_jarvis_config(mode)

    raw_base = (get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434') or '').strip()
    base_url = raw_base.split(',')[0].strip().rstrip('/') if raw_base else 'http://localhost:11434'

    effective_provider = (get_jarvis_setting('LLM_PROVIDER', 'xai' if mode == 'cloud' else 'ollama') or '').lower()

    api_key_mode = mode == 'cloud' and bool(get_ollama_api_key())
    cache_key = f"{mode}:{'api_key' if api_key_mode else base_url}"
    now = time.time()
    cached = _OLLAMA_CLOUD_STATUS_CACHE.get(cache_key)
    if cached and (now - cached['ts']) < _OLLAMA_CLOUD_STATUS_TTL_SECONDS:
        return jsonify(cached['payload'])

    payload = {
        'provider': 'ollama',
        'connection_mode': 'api_key' if api_key_mode else 'signed_in_host',
        'effective_provider': effective_provider,
        'reachable': False,
        'signed_in': 'unknown',
        'plan': None,
        'quota_available': None,
        'dashboard_url': 'https://ollama.com/settings',
        'signin_url': None,
    }

    if api_key_mode:
        # Match the other provider gates: a nonblank key means configured.
        # Authentication failures are reported by the actual model request.
        payload['reachable'] = True
        payload['signed_in'] = True
        _OLLAMA_CLOUD_STATUS_CACHE[cache_key] = {'ts': now, 'payload': payload}
        return jsonify(payload)

    try:
        response = http_requests.post(f"{base_url}/api/me", timeout=(3, 6))
        payload['reachable'] = True
        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError:
                data = None
            # Treat malformed/empty success payloads as an unsupported schema,
            # not proof of authentication. Surface only plan/state; identity
            # fields are used solely as a capability hint and never returned.
            plan = data.get('plan') if isinstance(data, dict) else None
            looks_like_account = isinstance(data, dict) and bool(data) and (
                isinstance(plan, str)
                or any(data.get(key) for key in ('id', 'email', 'name', 'username'))
            )
            if looks_like_account:
                payload['signed_in'] = True
                payload['plan'] = plan if isinstance(plan, str) else None
            else:
                payload['signed_in'] = 'unknown'
        elif response.status_code in (401, 403):
            payload['signed_in'] = False
            try:
                data = response.json()
            except ValueError:
                data = {}
            payload['signin_url'] = _validate_ollama_signin_url(
                (data or {}).get('signin_url') if isinstance(data, dict) else None
            )
        elif response.status_code == 404:
            # Older/incompatible daemon without /api/me — capability not present.
            payload['signed_in'] = 'unknown'
        else:
            payload['signed_in'] = 'unknown'
    except http_requests.exceptions.Timeout:
        payload['reachable'] = False
        payload['signed_in'] = 'unknown'
        payload['error'] = 'Ollama host timed out'
    except http_requests.exceptions.RequestException:
        payload['reachable'] = False
        payload['signed_in'] = 'unknown'
        payload['error'] = 'Ollama host unreachable'
    except Exception:
        payload['signed_in'] = 'unknown'
        payload['error'] = 'Status check failed'

    _OLLAMA_CLOUD_STATUS_CACHE[cache_key] = {'ts': now, 'payload': payload}
    return jsonify(payload)


@api_bp.route('/ollama/model-context', methods=['GET'])
@_scoped_request_config
def get_ollama_model_context():
    """Return the true context window for an Ollama model via POST /api/show.

    Lets the chat UI show an accurate context-usage percentage for cloud-tagged
    models (whose catalog ``context`` is just the string ``"cloud"``) instead of
    guessing. Best-effort and cached; returns ``context_length: null`` when the
    daemon does not report it, so the client keeps its own fallback.
    """
    import time
    import requests as http_requests
    from ..config import load_jarvis_config, get_jarvis_setting

    mode = request.args.get('mode', 'cloud')
    model = (request.args.get('model') or '').strip()
    if not model:
        return jsonify({'ok': False, 'error': 'model required'}), 400

    load_jarvis_config(mode)
    raw_base = (get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434') or '').strip()
    base_url = raw_base.split(',')[0].strip().rstrip('/') if raw_base else 'http://localhost:11434'

    from ollama_utils import (
        get_ollama_execution_class,
        request_ollama,
        OLLAMA_EXECUTION_LOCAL_DAEMON,
    )

    execution_class = get_ollama_execution_class(model, mode)
    cache_key = f"{execution_class}:{base_url}:{model}"
    now = time.time()
    cached = _OLLAMA_MODEL_CONTEXT_CACHE.get(cache_key)
    if cached and (now - cached['ts']) < _OLLAMA_MODEL_CONTEXT_TTL_SECONDS:
        return jsonify(cached['payload'])

    payload = {'ok': True, 'model': model, 'context_length': None}
    try:
        response, _ = request_ollama(
            "post",
            "/api/show",
            json={"model": model},
            timeout=(3, 6),
            cloud_access=(execution_class != OLLAMA_EXECUTION_LOCAL_DAEMON),
        )
        if response.status_code == 200:
            try:
                payload['context_length'] = _extract_ollama_context_length(response.json())
            except ValueError:
                payload['context_length'] = None
        else:
            payload['ok'] = False
            payload['error'] = f'Ollama /api/show returned {response.status_code}'
    except http_requests.exceptions.RequestException:
        payload['ok'] = False
        payload['error'] = 'Ollama host unreachable'
    except Exception:
        payload['ok'] = False
        payload['error'] = 'Context lookup failed'

    # Cache successful lookups (with a real value) to avoid hammering the daemon.
    if payload.get('context_length'):
        _OLLAMA_MODEL_CONTEXT_CACHE[cache_key] = {'ts': now, 'payload': payload}
    return jsonify(payload)


@api_bp.route('/settings/blocked-tools', methods=['GET'])
def get_blocked_tools():
    """Get list of tools blocked for web mode"""
    settings = get_settings_manager()
    return jsonify({
        'ok': True,
        'blocked': settings.get_blocked_tools()
    })


@api_bp.route('/settings/blocked-tools', methods=['PUT'])
def update_blocked_tools():
    """Update list of blocked tools"""
    settings = get_settings_manager()
    data = request.get_json() or {}
    blocked = data.get('blocked', [])
    
    if not isinstance(blocked, list):
        return jsonify({'ok': False, 'error': 'blocked must be a list'}), 400
    
    success = settings.update_blocked_tools(blocked)
    
    # Web blocking is global, so every cached mode must see the change.
    from ..services.tool_discovery import refresh_tool_services
    refresh_tool_services()
    
    return jsonify({
        'ok': success,
        'blocked': settings.get_blocked_tools()
    })


@api_bp.route('/mode', methods=['GET'])
def get_mode():
    """Get current mode"""
    settings = get_settings_manager()
    return jsonify({
        'ok': True,
        'mode': settings.mode
    })


@api_bp.route('/mode', methods=['PUT'])
def set_mode():
    """Switch mode (cloud/local)"""
    settings = get_settings_manager()
    data = request.get_json()
    mode = data.get('mode') if data else None
    
    if mode not in ['cloud', 'local']:
        return jsonify({
            'ok': False,
            'error': 'Mode must be "cloud" or "local"'
        }), 400
    
    if settings.set_mode(mode):
        return jsonify({
            'ok': True,
            'mode': mode
        })
    else:
        return jsonify({
            'ok': False,
            'error': 'Failed to set mode'
        }), 500


@api_bp.route('/conversations', methods=['GET'])
def list_conversations():
    """List conversation history"""
    from ..services.conversation_store import get_conversation_store
    store = get_conversation_store()
    
    limit = request.args.get('limit', 100, type=int)
    include_archived = request.args.get('include_archived', 'true').lower() in {'1', 'true', 'yes', 'on'}
    conversations = store.list_conversations(limit=limit, include_archived=include_archived)
    
    return jsonify({
        'ok': True,
        'conversations': conversations
    })


@api_bp.route('/conversations', methods=['POST'])
def create_conversation():
    """Create a new conversation"""
    from ..services.conversation_store import get_conversation_store
    store = get_conversation_store()
    
    data = request.get_json() or {}
    title = data.get('title')
    
    conversation = store.create_conversation(title=title)
    
    return jsonify({
        'ok': True,
        'conversation': conversation
    })


@api_bp.route('/conversations/<conv_id>', methods=['GET'])
def get_conversation(conv_id):
    """Get a specific conversation with all messages"""
    from ..services.conversation_store import get_conversation_store
    store = get_conversation_store()
    
    conversation = store.get_conversation(conv_id)
    
    if conversation:
        return jsonify({
            'ok': True,
            'conversation': conversation
        })
    else:
        return jsonify({
            'ok': False,
            'error': 'Conversation not found'
        }), 404


@api_bp.route('/conversations/<conv_id>', methods=['DELETE'])
def delete_conversation(conv_id):
    """Delete a conversation"""
    from ..services.conversation_store import get_conversation_store
    store = get_conversation_store()
    
    store.delete_conversation(conv_id)
    
    return jsonify({
        'ok': True,
        'message': 'Conversation deleted'
    })


@api_bp.route('/conversations/<conv_id>/title', methods=['PUT'])
def update_conversation_title(conv_id):
    """Update conversation title"""
    from ..services.conversation_store import get_conversation_store
    store = get_conversation_store()
    
    data = request.get_json(silent=True) or {}
    title = data.get('title')
    if not isinstance(title, str):
        return jsonify({
            'ok': False,
            'error': 'Conversation name must be a string'
        }), 400

    title = ' '.join(title.split())
    if not title:
        return jsonify({
            'ok': False,
            'error': 'Conversation name cannot be blank'
        }), 400
    if len(title) > 200:
        return jsonify({
            'ok': False,
            'error': 'Conversation name must be 200 characters or fewer'
        }), 400

    conversation = store.get_conversation(conv_id)
    if not conversation:
        return jsonify({
            'ok': False,
            'error': 'Conversation not found'
        }), 404
    if not conversation.get('messages'):
        return jsonify({
            'ok': False,
            'error': 'Add a message before renaming this conversation'
        }), 409
    
    if store.update_title(conv_id, title):
        return jsonify({
            'ok': True,
            'message': 'Title updated'
        })

    return jsonify({
        'ok': False,
        'error': 'Conversation not found'
    }), 404


@api_bp.route('/conversations/<conv_id>/state', methods=['PATCH'])
def update_conversation_state(conv_id):
    """Update pinned/archive state for a conversation."""
    from ..services.conversation_store import get_conversation_store
    store = get_conversation_store()

    data = request.get_json() or {}
    pinned = data['pinned'] if 'pinned' in data else None
    archived = data['archived'] if 'archived' in data else None

    if pinned is None and archived is None:
        return jsonify({
            'ok': False,
            'error': 'No state changes provided'
        }), 400

    updated = store.update_state(conv_id, pinned=pinned, archived=archived)
    if not updated:
        return jsonify({
            'ok': False,
            'error': 'Conversation not found'
        }), 404

    return jsonify({
        'ok': True,
        'conversation': updated
    })


@api_bp.route('/conversations/<conv_id>/clear', methods=['POST'])
def clear_conversation(conv_id):
    """Clear all messages from a conversation (keeps conversation, resets to empty)"""
    from ..services.conversation_store import get_conversation_store
    store = get_conversation_store()

    if store.clear_conversation(conv_id):
        return jsonify({
            'ok': True,
            'message': 'Conversation cleared'
        })
    return jsonify({
        'ok': False,
        'error': 'Conversation not found'
    }), 404


@api_bp.route('/conversations/search', methods=['GET'])
def search_conversations():
    """Search across all conversations for keywords
    
    Query params:
      - q: search query (required)
      - limit: max results per conversation (default 3)
    
    Returns matching messages with context snippets
    """
    from ..services.conversation_store import get_conversation_store
    store = get_conversation_store()
    
    query = request.args.get('q', '').strip().lower()
    limit_per_conv = request.args.get('limit', 3, type=int)
    
    if not query:
        return jsonify({'ok': False, 'error': 'Search query required'}), 400
    
    results = []
    conversations = store.list_conversations(limit=100, include_archived=True)  # Search up to 100 conversations
    
    for conv_summary in conversations:
        conv = store.get_conversation(conv_summary['id'])
        if not conv:
            continue
        
        title = str(conv.get('title') or '')
        title_matches = query in title.lower()
        matches = []
        if title_matches:
            matches.append({
                'message_id': None,
                'role': 'title',
                'snippet': title,
                'timestamp': conv.get('updated_at')
            })

        message_match_count = 0
        for msg in conv.get('messages', []):
            content = msg.get('content', '').lower()
            if query in content:
                message_match_count += 1
                if len(matches) >= limit_per_conv:
                    # Keep counting matches so the result total remains truthful.
                    continue

                # Extract snippet around match
                idx = content.find(query)
                start = max(0, idx - 50)
                end = min(len(content), idx + len(query) + 50)
                snippet = msg.get('content', '')[start:end]
                if start > 0:
                    snippet = '...' + snippet
                if end < len(content):
                    snippet = snippet + '...'
                
                matches.append({
                    'message_id': msg.get('id'),
                    'role': msg.get('role'),
                    'snippet': snippet,
                    'timestamp': msg.get('timestamp')
                })
        
        if matches:
            results.append({
                'conversation_id': conv['id'],
                'title': conv.get('title', 'Untitled'),
                'updated_at': conv.get('updated_at'),
                'matches': matches,
                'total_matches': message_match_count + (1 if title_matches else 0)
            })
    
    return jsonify({
        'ok': True,
        'query': query,
        'results': results,
        'total_conversations': len(results)
    })


@api_bp.route('/conversations/<conv_id>/export', methods=['GET'])
def export_conversation(conv_id):
    """Export a conversation as JSON or Markdown
    
    Query params:
      - format: 'json' (default) or 'markdown'
    """
    from ..services.conversation_store import get_conversation_store
    store = get_conversation_store()
    
    conversation = store.get_conversation(conv_id)
    if not conversation:
        return jsonify({'ok': False, 'error': 'Conversation not found'}), 404
    
    export_format = request.args.get('format', 'json').lower()
    
    if export_format == 'markdown':
        # Generate Markdown
        lines = [
            f"# {conversation.get('title', 'Untitled Conversation')}",
            f"",
            f"**Created:** {conversation.get('created_at', 'Unknown')}",
            f"**Updated:** {conversation.get('updated_at', 'Unknown')}",
            f"",
            "---",
            ""
        ]
        
        for msg in conversation.get('messages', []):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')
            
            if role == 'user':
                lines.append(f"### 👤 User ({timestamp})")
            else:
                lines.append(f"### 🤖 Jarvis ({timestamp})")
            
            lines.append("")
            lines.append(content)
            lines.append("")

            usage_lines = format_usage_markdown((msg.get('data') or {}).get('usage'))
            if usage_lines:
                lines.extend(usage_lines)
                lines.append("")
            
            # Include tool info if present
            tools = msg.get('tools_used', [])
            if tools:
                lines.append(f"*Tools used: {', '.join(tools)}*")
                lines.append("")

            completion_guard = (msg.get('data') or {}).get('_completion_guard')
            if isinstance(completion_guard, dict) and completion_guard:
                lines.append("**Completion Guard**")
                lines.append("")
                lines.append(f"- Status: {completion_guard.get('status', 'unknown')}")
                if completion_guard.get('note'):
                    lines.append(f"- Note: {completion_guard['note']}")
                if completion_guard.get('ticket_path'):
                    lines.append(f"- Ticket: `{completion_guard['ticket_path']}`")
                if completion_guard.get('repair_message_id'):
                    lines.append(f"- Repair Message ID: `{completion_guard['repair_message_id']}`")
                lines.append("")
            
            lines.append("---")
            lines.append("")
        
        markdown_content = '\n'.join(lines)
        
        from flask import Response
        return Response(
            markdown_content,
            mimetype='text/markdown',
            headers={
                'Content-Disposition': f'attachment; filename="{conv_id}.md"'
            }
        )
    else:
        # JSON export (default)
        from flask import Response
        return Response(
            json.dumps(conversation, indent=2),
            mimetype='application/json',
            headers={
                'Content-Disposition': f'attachment; filename="{conv_id}.json"'
            }
        )


@api_bp.route('/conversations/import', methods=['POST'])
def import_conversation():
    """Import a conversation from JSON
    
    Accepts: JSON body with conversation data or file upload
    Returns: The imported conversation
    """
    from ..services.conversation_store import get_conversation_store
    store = get_conversation_store()
    
    try:
        # Check for file upload
        if 'file' in request.files:
            file = request.files['file']
            if file.filename.endswith('.json'):
                conversation_data = json.load(file)
            else:
                return jsonify({'ok': False, 'error': 'Only JSON files supported'}), 400
        else:
            # JSON body
            conversation_data = request.get_json()
        
        if not conversation_data:
            return jsonify({'ok': False, 'error': 'No conversation data provided'}), 400
        
        # Validate required fields
        if 'messages' not in conversation_data:
            return jsonify({'ok': False, 'error': 'Invalid conversation format: missing messages'}), 400
        
        # Create new conversation with imported data
        # Generate new ID to avoid conflicts
        new_conv = store.create_conversation(
            title=conversation_data.get('title', 'Imported Conversation')
        )
        
        # Get the full conversation to update
        conv = store.get_conversation(new_conv['id'])
        
        # Copy messages (but with new IDs)
        import uuid
        for msg in conversation_data.get('messages', []):
            conv['messages'].append({
                'id': str(uuid.uuid4())[:8],
                'role': msg.get('role', 'user'),
                'content': msg.get('content', ''),
                'timestamp': msg.get('timestamp', datetime.now().isoformat()),
                'data': msg.get('data'),
                'tools_used': msg.get('tools_used', [])
            })
        
        # Preserve original timestamps if available
        if 'created_at' in conversation_data:
            conv['created_at'] = conversation_data['created_at']
        if 'updated_at' in conversation_data:
            conv['updated_at'] = conversation_data['updated_at']
        conv['pinned'] = bool(conversation_data.get('pinned', False))
        conv['archived'] = bool(conversation_data.get('archived', False))
        conv['pinned_at'] = conversation_data.get('pinned_at') if conv['pinned'] else None
        conv['archived_at'] = conversation_data.get('archived_at') if conv['archived'] else None
        if conversation_data.get('llm_provider'):
            conv['llm_provider'] = conversation_data['llm_provider']
        if conversation_data.get('llm_model'):
            conv['llm_model'] = conversation_data['llm_model']
        
        # Save updated conversation
        conv_file = store.conversations_dir / f"{new_conv['id']}.json"
        with open(conv_file, 'w') as f:
            json.dump(conv, f, indent=2)
        
        # Update index
        for idx_conv in store._index['conversations']:
            if idx_conv['id'] == new_conv['id']:
                idx_conv['title'] = conv['title']
                idx_conv['message_count'] = len(conv['messages'])
                idx_conv['updated_at'] = conv.get('updated_at', datetime.now().isoformat())
                idx_conv['pinned'] = conv.get('pinned', False)
                idx_conv['archived'] = conv.get('archived', False)
                idx_conv['pinned_at'] = conv.get('pinned_at')
                idx_conv['archived_at'] = conv.get('archived_at')
                break
        store._save_index()
        
        return jsonify({
            'ok': True,
            'conversation': conv,
            'message': f"Imported {len(conv['messages'])} messages"
        })
        
    except json.JSONDecodeError:
        return jsonify({'ok': False, 'error': 'Invalid JSON format'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# Intel directory (jarvis-intel knowledge files)
INTEL_DIR = JARVIS_ROOT / 'jarvis-intel'
SKILLS_DIR = JARVIS_ROOT / 'skills'


def _validate_intel_filename(filename):
    """Validate intel filename - .md or .txt, safe chars only"""
    from pathlib import Path
    name = Path(filename).name
    if not name.endswith(('.md', '.txt')):
        raise ValueError('Filename must end in .md or .txt')
    if name == 'README.md':
        raise ValueError('Cannot modify README.md')
    safe = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.')
    if not all(c in safe for c in name):
        raise ValueError('Use only letters, numbers, hyphens, underscores, and dots')
    return name


@api_bp.route('/intel/upload', methods=['POST'])
def upload_intel_file():
    """Upload a .txt or .md file to jarvis-intel and trigger ingestion.
    
    Accepts: multipart file upload
    Returns: ok, message, filename
    """
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No file provided'}), 400
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'ok': False, 'error': 'No file selected'}), 400
    try:
        filename = _validate_intel_filename(file.filename)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    if file.content_length and file.content_length > 1024 * 1024:
        return jsonify({'ok': False, 'error': 'File too large (max 1MB)'}), 400
    try:
        content = file.read().decode('utf-8', errors='replace')
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Could not read file: {e}'}), 400
    INTEL_DIR.mkdir(parents=True, exist_ok=True)
    filepath = INTEL_DIR / filename
    if not filepath.exists():
        try:
            validate_create_filename(filename)
        except ValueError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400
    try:
        filepath.write_text(content, encoding='utf-8')
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    ingest_script = SKILLS_DIR / 'ingest_intel.py'
    if ingest_script.exists():
        import subprocess
        subprocess.Popen(
            ['python3', str(ingest_script), '--sync'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(JARVIS_ROOT)
        )
    return jsonify({
        'ok': True,
        'message': f'Saved {filename} and started ingestion',
        'filename': filename
    })


@api_bp.route('/stt', methods=['POST'])
@_scoped_request_config
def speech_to_text():
    """Transcribe audio to text with the mode-specific configured provider.

    Defaults remain OpenAI in cloud mode and faster-whisper in local mode. Both
    modes may opt into a separate OpenAI-compatible endpoint.
    
    Accepts: multipart/form-data with 'audio' file
    Returns: { ok: true, text: "transcribed text" }
    """
    print(f"[STT] /api/stt endpoint hit", flush=True)
    
    if 'audio' not in request.files:
        return jsonify({'ok': False, 'error': 'No audio file provided'}), 400
    
    audio_file = request.files['audio']
    mode = request.form.get('mode')
    print(f"[STT] Received audio, mode from form: {mode}", flush=True)
    
    try:
        from ..config import load_jarvis_config, get_jarvis_setting
        import tempfile
        
        # Get mode from form data or settings
        if not mode:
            settings = get_settings_manager()
            mode = settings.mode
        
        # Force reload config for correct mode
        load_jarvis_config(mode)
        
        provider = get_jarvis_setting('STT_PROVIDER', 'openai' if mode == 'cloud' else 'faster-whisper')
        from stt_client import default_model_for_provider, normalize_stt_provider

        provider = normalize_stt_provider(provider)
        stt_model = get_jarvis_setting('STT_MODEL', '') or default_model_for_provider(provider)
        print(f"[STT] ========================================", flush=True)
        print(f"[STT] Mode: {mode}, Provider: {provider}, Model: {stt_model}", flush=True)
        
        # Save uploaded audio to temp file
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
            audio_file.save(tmp.name)
            tmp_path = tmp.name
        
        print(f"[STT] Audio saved to: {tmp_path}", flush=True)
        
        try:
            transcript = _transcribe_configured(tmp_path, mode, provider, stt_model)
            
            if not transcript:
                return jsonify({'ok': False, 'error': 'No speech detected'}), 400
            
            print(f"[STT] Transcription complete ({len(transcript)} characters)", flush=True)
            print(f"[STT] ========================================", flush=True)
            return jsonify({'ok': True, 'text': transcript})
            
        finally:
            # Clean up temp file
            import os
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
                
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


def _stt_timeout() -> float:
    from ..config import get_jarvis_setting
    from stt_client import parse_stt_timeout

    return parse_stt_timeout(get_jarvis_setting('STT_TIMEOUT_SECONDS', '30'))


def _transcribe_openai(audio_path: str, model: str) -> str:
    """Transcribe audio using the OpenAI service."""
    from stt_client import transcribe_openai_compatible
    from ..config import get_jarvis_setting
    
    api_key = get_jarvis_setting('OPENAI_API_KEY', '')
    if not api_key:
        raise ValueError('OPENAI_API_KEY not configured')

    return transcribe_openai_compatible(
        audio_path,
        base_url='https://api.openai.com/v1',
        api_key=api_key,
        model=model,
        timeout=_stt_timeout(),
    )


def _transcribe_compatible(audio_path: str, model: str) -> str:
    """Transcribe audio using the separately configured compatible endpoint."""
    from stt_client import transcribe_openai_compatible
    from ..config import get_jarvis_setting

    return transcribe_openai_compatible(
        audio_path,
        base_url=get_jarvis_setting('STT_BASE_URL', ''),
        api_key=get_jarvis_setting('STT_API_KEY', ''),
        model=model,
        timeout=_stt_timeout(),
    )


def _transcribe_faster_whisper(audio_path: str, mode: str, model: str) -> str:
    """Transcribe audio using faster-whisper in an isolated process."""
    import os
    import subprocess
    from stt_client import STTProviderError
    
    # Convert webm to wav for faster-whisper
    wav_path = _convert_to_wav(audio_path)
    
    try:
        stt_script = JARVIS_ROOT / 'bin' / 'stt.py'
        
        result = subprocess.run(
            [
                sys.executable,
                str(stt_script),
                '--mode',
                mode,
                '--provider',
                'faster-whisper',
                '--model',
                model,
                wav_path,
            ],
            capture_output=True,
            text=True,
            timeout=_stt_timeout(),
        )
        
        if result.returncode != 0:
            detail = result.stderr.strip().replace('\n', ' ')[:300]
            if result.returncode == 3:
                raise STTProviderError(
                    f"faster-whisper process failed: {detail}", retryable=True
                )
            raise ValueError(f"faster-whisper configuration failed: {detail}")
        
        return result.stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise STTProviderError('faster-whisper timed out', retryable=True) from exc
    finally:
        # Clean up converted file
        if wav_path != audio_path and os.path.exists(wav_path):
            os.unlink(wav_path)


def _transcribe_local(audio_path: str) -> str:
    """Backward-compatible faster-whisper helper for local mode."""
    from ..config import get_jarvis_setting

    return _transcribe_faster_whisper(
        audio_path,
        'local',
        get_jarvis_setting('STT_MODEL', 'small.en'),
    )


def _transcribe_configured(
    audio_path: str, mode: str, provider: str, model: str
) -> str:
    """Dispatch configured STT and apply only an explicitly enabled fallback."""
    from ..config import get_jarvis_setting
    from stt_client import default_model_for_provider, run_with_stt_fallback

    fallback_provider = get_jarvis_setting('STT_FALLBACK_PROVIDER', '').strip()
    fallback_model = get_jarvis_setting('STT_FALLBACK_MODEL', '').strip()

    def transcribe(selected_provider: str) -> str:
        selected_model = model
        if selected_provider != provider:
            selected_model = fallback_model or default_model_for_provider(selected_provider)
        if selected_provider == 'faster-whisper':
            return _transcribe_faster_whisper(audio_path, mode, selected_model)
        if selected_provider == 'openai':
            return _transcribe_openai(audio_path, selected_model)
        if selected_provider == 'openai-compatible':
            return _transcribe_compatible(audio_path, selected_model)
        raise ValueError(f"Unsupported STT provider: {selected_provider}")

    def on_fallback(primary, fallback, error):
        print(
            f"[STT] {primary} temporarily unavailable; falling back to {fallback}: {error}",
            flush=True,
        )

    return run_with_stt_fallback(
        provider,
        fallback_provider,
        transcribe,
        on_fallback=on_fallback,
    )


def _convert_to_wav(input_path: str) -> str:
    """Convert audio file to WAV format using ffmpeg"""
    import subprocess
    
    # If already wav, return as-is
    if input_path.lower().endswith('.wav'):
        return input_path
    
    # Create output path
    wav_path = input_path.rsplit('.', 1)[0] + '.wav'
    
    try:
        subprocess.run([
            'ffmpeg', '-y', '-i', input_path,
            '-ar', '16000',  # 16kHz sample rate
            '-ac', '1',      # Mono
            '-f', 'wav',
            wav_path
        ], capture_output=True, check=True, timeout=30)
        
        return wav_path
    except subprocess.CalledProcessError as e:
        print(f"[STT] ffmpeg conversion failed: {e.stderr}", flush=True)
        # Fall back to original file
        return input_path
    except FileNotFoundError:
        print("[STT] ffmpeg not found, using original file", flush=True)
        return input_path


@api_bp.route('/tts', methods=['POST'])
@_scoped_request_config
def text_to_speech():
    """Generate TTS audio from text - uses mode-specific provider"""
    data = request.get_json() or {}
    text = data.get('text', '')
    mode = data.get('mode')  # Accept mode from client to ensure sync
    purpose = str(data.get('purpose') or 'final').strip().lower()
    message_id = data.get('message_id')
    
    if not text:
        return jsonify({'ok': False, 'error': 'No text provided'}), 400

    try:
        import requests
        from datetime import datetime
        from security_utils import sanitize_for_speech
        
        # Load config for specified mode (from client) or fall back to settings
        from ..config import load_jarvis_config, get_jarvis_setting
        if not mode:
            settings = get_settings_manager()
            mode = settings.mode
        
        # Force reload config for the correct mode
        load_jarvis_config(mode)
        _apply_tts_provider_override(mode)
        
        provider = get_jarvis_setting('TTS_PROVIDER', 'qwen3-tts' if mode == 'local' else 'elevenlabs')
        print(f"[TTS] Mode: {mode}, Provider: {provider}", flush=True)

        effective_tts_model = None
        if provider == 'elevenlabs':
            final_tts_model, status_tts_model = _effective_elevenlabs_models(
                get_jarvis_setting
            )
            effective_tts_model = (
                status_tts_model if purpose == 'status' else final_tts_model
            )

        text = sanitize_for_speech(text, preserve_xai_tags=provider == 'xai')
        if not text:
            text = "Done. I shared the details in chat."

        status_cache_enabled = (
            purpose == 'status'
            and get_jarvis_setting('STATUS_CACHE_ENABLED', 'true').strip().lower() == 'true'
        )
        status_cache_paths = None
        if status_cache_enabled:
            status_cache_paths = _status_tts_cache_paths(
                mode,
                provider,
                text,
                get_jarvis_setting,
            )
            cached_audio, cached_mime = status_cache_paths
            if cached_audio.is_file() and cached_audio.stat().st_size and cached_mime.is_file():
                log_status_event(
                    'tts_cache_hit',
                    mode=mode,
                    provider=provider,
                    model=effective_tts_model,
                    message_id=message_id,
                    text_chars=len(text),
                )
                response = send_file(cached_audio, mimetype=cached_mime.read_text().strip())
                response.headers['X-Jarvis-TTS-Cache'] = 'hit'
                return response

        if purpose == 'status':
            log_status_event(
                'tts_provider_started',
                mode=mode,
                provider=provider,
                model=effective_tts_model,
                message_id=message_id,
                cache_enabled=status_cache_enabled,
                text_chars=len(text),
            )
        
        # Qwen3-TTS (OpenAI-compatible voice cloning on local network)
        if provider == 'qwen3-tts':
            tts_url = get_jarvis_setting('QWEN3_TTS_URL', '')
            if not tts_url:
                return jsonify({'ok': False, 'error': 'QWEN3_TTS_URL not configured'}), 500
            
            tts_voice = get_jarvis_setting('QWEN3_TTS_VOICE', 'Jarvis')
            tts_format = get_jarvis_setting('QWEN3_TTS_FORMAT', 'mp3')
            tts_speed = get_jarvis_setting('QWEN3_TTS_SPEED', '1.0')
            
            print(f"[TTS] Calling Qwen3-TTS at {tts_url} with voice={tts_voice}", flush=True)
            
            # Qwen3-TTS uses standard OpenAI-compatible API
            payload = {
                "model": "tts-1",
                "input": text,
                "voice": tts_voice,
                "response_format": tts_format,
                "speed": float(tts_speed)
            }
            
            response = requests.post(tts_url, json=payload, timeout=60)  # Longer timeout for first-time voice builds
            response.raise_for_status()
            
            # Return audio directly
            content_type = 'audio/mpeg' if tts_format == 'mp3' else f'audio/{tts_format}'
            if status_cache_paths:
                _write_status_tts_cache(*status_cache_paths, response.content, content_type)
            if purpose == 'status':
                log_status_event(
                    'tts_provider_completed', mode=mode, provider=provider,
                    message_id=message_id, audio_bytes=len(response.content),
                )
            return response.content, 200, {
                'Content-Type': content_type,
                'Content-Disposition': 'inline',
                'X-Jarvis-TTS-Cache': 'miss' if status_cache_paths else 'disabled',
            }
        
        # Kokoro TTS (local)
        if provider == 'kokoro':
            tts_url = get_jarvis_setting('KOKORO_TTS_URL', '')
            if not tts_url:
                return jsonify({'ok': False, 'error': 'KOKORO_TTS_URL not configured'}), 500
            
            tts_voice = get_jarvis_setting('KOKORO_TTS_VOICE', 'af_nicole')
            tts_speed = get_jarvis_setting('KOKORO_TTS_SPEED', '1.0')
            
            print(f"[TTS] Calling Kokoro at {tts_url} with voice={tts_voice}", flush=True)
            
            # Kokoro uses OpenAI-compatible API
            payload = {
                "model": "kokoro",
                "input": text,
                "voice": tts_voice,
                "speed": float(tts_speed)
            }
            
            response = requests.post(tts_url, json=payload, timeout=30)
            response.raise_for_status()
            
            # Return audio directly (Kokoro returns raw audio)
            content_type = response.headers.get('Content-Type') or 'audio/mpeg'
            if status_cache_paths:
                _write_status_tts_cache(*status_cache_paths, response.content, content_type)
            if purpose == 'status':
                log_status_event(
                    'tts_provider_completed', mode=mode, provider=provider,
                    message_id=message_id, audio_bytes=len(response.content),
                )
            return response.content, 200, {
                'Content-Type': content_type,
                'Content-Disposition': 'inline',
                'X-Jarvis-TTS-Cache': 'miss' if status_cache_paths else 'disabled',
            }
        
        # Cloud mode: ElevenLabs or OpenAI
        tts_dir = JARVIS_ROOT / 'audio' / 'cloud' / 'tts'
        tts_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if provider == 'elevenlabs':
            audio_path = _generate_elevenlabs_tts(
                text,
                tts_dir,
                timestamp,
                model_override=effective_tts_model,
            )
        elif provider == 'xai':
            audio_path = _generate_xai_tts(text, tts_dir, timestamp)
        else:
            audio_path = _generate_openai_tts(text, tts_dir, timestamp)
        
        if audio_path and audio_path.exists():
            mimetype = {
                '.mp3': 'audio/mpeg',
                '.wav': 'audio/wav',
                '.pcm': 'audio/pcm',
                '.mulaw': 'audio/basic',
                '.alaw': 'audio/alaw',
            }.get(audio_path.suffix.lower(), 'application/octet-stream')
            if status_cache_paths:
                _write_status_tts_cache(
                    *status_cache_paths,
                    audio_path.read_bytes(),
                    mimetype,
                )
            if purpose == 'status':
                log_status_event(
                    'tts_provider_completed', mode=mode, provider=provider,
                    model=effective_tts_model, message_id=message_id,
                    audio_bytes=audio_path.stat().st_size,
                )
            response = send_from_directory(
                str(audio_path.parent),
                audio_path.name,
                mimetype=mimetype
            )
            response.headers['X-Jarvis-TTS-Cache'] = 'miss' if status_cache_paths else 'disabled'
            return response
        else:
            return jsonify({'ok': False, 'error': 'TTS generation failed'}), 500
            
    except Exception as e:
        if purpose == 'status':
            log_status_event(
                'tts_provider_failed',
                mode=mode or 'unknown',
                provider=locals().get('provider'),
                model=locals().get('effective_tts_model'),
                message_id=message_id,
                error=str(e)[:300],
            )
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


def _generate_elevenlabs_tts(
    text: str,
    output_dir: Path,
    timestamp: str,
    model_override: str | None = None,
) -> Path:
    """Generate TTS using ElevenLabs API"""
    import requests
    from ..config import get_jarvis_setting
    
    api_key = get_jarvis_setting('ELEVENLABS_API_KEY', '')
    voice_id = get_jarvis_setting('ELEVENLABS_TTS_VOICE', 'pgCnBQgKPGkIP8fJuita')
    model_id = model_override or get_jarvis_setting(
        'ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2'
    )
    
    if not api_key:
        raise ValueError('ELEVENLABS_API_KEY not configured')
    
    # Current ElevenLabs per-request limits: v3 5k, Flash 2.5 40k, v2 10k.
    char_limit = (
        5000 if model_id == 'eleven_v3'
        else 40000 if model_id == 'eleven_flash_v2_5'
        else 10000
    )
    if len(text) > char_limit:
        print(f"[API TTS] Text truncated from {len(text)} to {char_limit} chars for {model_id}")
        text = text[:char_limit]
    
    print(f"[API TTS] ElevenLabs: model={model_id}, chars={len(text)}")
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    # Get voice settings from config (with sensible defaults)
    stability = float(get_jarvis_setting('ELEVENLABS_TTS_STABILITY', '0.5'))
    similarity = float(get_jarvis_setting('ELEVENLABS_TTS_SIMILARITY_BOOST', '0.75'))
    
    # v3 has different voice_settings requirements (stability must be 0.0, 0.5, or 1.0)
    if model_id == 'eleven_v3':
        # Snap stability to valid v3 values
        stability = min([0.0, 0.5, 1.0], key=lambda x: abs(x - stability))
        voice_settings = {
            "stability": stability,
            "similarity_boost": similarity
        }
    else:
        style = float(get_jarvis_setting('ELEVENLABS_TTS_STYLE', '0.5'))
        speaker_boost = get_jarvis_setting('ELEVENLABS_TTS_USE_SPEAKER_BOOST', 'true').lower() == 'true'
        voice_settings = {
            "stability": stability,
            "similarity_boost": similarity,
            "style": style,
            "use_speaker_boost": speaker_boost
        }
    
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": voice_settings
    }
    
    response = requests.post(url, json=payload, headers=headers, timeout=60)
    
    if response.status_code != 200:
        raise ValueError(f"ElevenLabs API error: {response.status_code} - {response.text}")
    
    # Save audio (ElevenLabs returns mp3)
    output_path = output_dir / f"tts_{timestamp}.mp3"
    with open(output_path, 'wb') as f:
        f.write(response.content)
    
    return output_path


def _generate_xai_tts(text: str, output_dir: Path, timestamp: str) -> Path:
    """Generate TTS using xAI's native TTS API"""
    import requests
    from ..config import get_jarvis_setting

    api_key = get_jarvis_setting('XAI_API_KEY', '')
    voice_id = get_jarvis_setting('XAI_TTS_VOICE', 'eve')
    language = get_jarvis_setting('XAI_TTS_LANGUAGE', 'en')
    codec = get_jarvis_setting('XAI_TTS_CODEC', 'mp3').lower()
    sample_rate = int(get_jarvis_setting('XAI_TTS_SAMPLE_RATE', '24000'))
    bit_rate = int(get_jarvis_setting('XAI_TTS_BIT_RATE', '128000'))
    max_chars = int(get_jarvis_setting('XAI_TTS_MAX_CHARS', '5000'))
    timeout = int(get_jarvis_setting('XAI_TTS_TIMEOUT', '180'))

    if not api_key:
        raise ValueError('XAI_API_KEY not configured')

    if len(text) > max_chars:
        print(f"[API TTS] Text truncated from {len(text)} to {max_chars} chars for xAI TTS")
        text = text[:max_chars]

    print(f"[API TTS] xAI: voice={voice_id}, language={language}, codec={codec}, chars={len(text)}")

    output_format = {
        "codec": codec,
        "sample_rate": sample_rate,
    }
    if codec == 'mp3':
        output_format["bit_rate"] = bit_rate

    payload = {
        "text": text,
        "voice_id": voice_id,
        "language": language,
        "output_format": output_format,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post("https://api.x.ai/v1/tts", json=payload, headers=headers, timeout=timeout)

    if response.status_code != 200:
        raise ValueError(f"xAI TTS API error: {response.status_code} - {response.text}")

    ext = 'mp3' if codec == 'mp3' else codec
    output_path = output_dir / f"tts_{timestamp}.{ext}"
    with open(output_path, 'wb') as f:
        f.write(response.content)

    return output_path


def _generate_openai_tts(text: str, output_dir: Path, timestamp: str) -> Path:
    """Generate TTS using OpenAI API"""
    import requests
    from ..config import get_jarvis_setting
    
    api_key = get_jarvis_setting('OPENAI_API_KEY', '')
    model = get_jarvis_setting('TTS_MODEL', 'gpt-4o-mini-tts')
    voice = get_jarvis_setting('VOICE', 'onyx')
    
    if not api_key:
        raise ValueError('OPENAI_API_KEY not configured')
    
    url = "https://api.openai.com/v1/audio/speech"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "voice": voice,
        "input": text
    }
    
    response = requests.post(url, json=payload, headers=headers, timeout=60)
    
    if response.status_code != 200:
        raise ValueError(f"OpenAI TTS API error: {response.status_code} - {response.text}")
    
    # Save audio (OpenAI returns mp3)
    output_path = output_dir / f"tts_{timestamp}.mp3"
    with open(output_path, 'wb') as f:
        f.write(response.content)
    
    return output_path


@api_bp.route('/audio/<filename>', methods=['GET'])
def serve_audio(filename):
    """Serve generated audio files"""
    # Security: only allow audio files, no path traversal
    if '..' in filename or '/' in filename:
        abort(404)
    
    # Check common audio extensions
    allowed_extensions = {'.mp3', '.wav', '.ogg', '.m4a', '.pcm', '.mulaw', '.alaw'}
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        abort(404)
    
    # Check TTS directories (both cloud and local)
    for mode_dir in ['cloud', 'local']:
        tts_path = JARVIS_ROOT / 'audio' / mode_dir / 'tts'
        if tts_path.exists() and (tts_path / filename).exists():
            return send_from_directory(str(tts_path), filename)
    
    # Check recordings directories (both cloud and local)
    for mode_dir in ['cloud', 'local']:
        recordings_path = JARVIS_ROOT / 'audio' / mode_dir / 'recordings'
        if recordings_path.exists() and (recordings_path / filename).exists():
            return send_from_directory(str(recordings_path), filename)
    
    # Fallback to data/audio
    audio_path = JARVIS_ROOT / 'data' / 'audio'
    if audio_path.exists() and (audio_path / filename).exists():
        return send_from_directory(str(audio_path), filename)
    
    abort(404)


@api_bp.route('/images/<filename>', methods=['GET'])
def serve_image(filename):
    """Serve generated images"""
    # Security: only allow image files, no path traversal
    if '..' in filename or '/' in filename:
        abort(404)
    
    # Check common image extensions
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        abort(404)
    
    if not IMAGES_PATH.exists():
        abort(404)
    
    return send_from_directory(str(IMAGES_PATH), filename)


@api_bp.route('/music/<filename>', methods=['GET'])
def serve_music(filename):
    """Serve generated music files"""
    # Security: only allow audio files, no path traversal
    if '..' in filename or '/' in filename:
        abort(404)
    
    # Check common audio extensions
    allowed_extensions = {'.mp3', '.wav', '.ogg', '.opus', '.m4a'}
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        abort(404)
    
    if not MUSIC_PATH.exists():
        abort(404)
    
    return send_from_directory(str(MUSIC_PATH), filename)


@api_bp.route('/videos/<filename>', methods=['GET'])
def serve_video(filename):
    """Serve generated video files"""
    # Security: only allow video files, no path traversal
    if '..' in filename or '/' in filename:
        abort(404)
    
    # Check common video extensions
    allowed_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.m4v'}
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        abort(404)
    
    if not VIDEOS_PATH.exists():
        abort(404)
    
    return send_from_directory(str(VIDEOS_PATH), filename)


@api_bp.route('/videos/<filename>/thumbnail', methods=['GET'])
def serve_video_thumbnail(filename):
    """Serve a cached first-frame poster for generated chat videos."""
    import subprocess

    if '..' in filename or '/' in filename:
        abort(404)

    allowed_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.m4v'}
    if Path(filename).suffix.lower() not in allowed_extensions:
        abort(404)

    video_path = VIDEOS_PATH / filename
    if not video_path.is_file():
        abort(404)

    thumbnail_dir = VIDEOS_PATH / '.thumbnails'
    thumbnail_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_path = thumbnail_dir / f'{Path(filename).stem}.jpg'

    if (
        not thumbnail_path.is_file()
        or thumbnail_path.stat().st_mtime < video_path.stat().st_mtime
    ):
        result = subprocess.run(
            [
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vframes', '1',
                '-vf', 'scale=480:-1',
                '-q:v', '3',
                str(thumbnail_path),
            ],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0 or not thumbnail_path.is_file():
            error = result.stderr.decode(errors='replace')[:200] if result.stderr else 'unknown ffmpeg error'
            print(f'[VIDEO] Failed to generate thumbnail for {filename}: {error}', file=sys.stderr)
            abort(500, 'Failed to generate video thumbnail')

    return send_file(thumbnail_path, mimetype='image/jpeg')


@api_bp.route('/stash/<space_id>/<file_id>', methods=['GET'])
def serve_stash_file(space_id, file_id):
    """
    Serve files from the stash system.
    Resolves file_id via meta.json to get actual filename.
    """
    import json
    
    # Security: no path traversal
    if '..' in space_id or '/' in space_id or '..' in file_id or '/' in file_id:
        abort(404)
    
    space_path = get_stash_dir() / space_id
    meta_path = space_path / 'meta.json'
    
    if not space_path.exists():
        abort(404)
    
    # Try to resolve file_id via meta.json
    file_path = None
    
    if meta_path.exists():
        try:
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            
            # Search for file_id in meta.json files array
            for file_info in meta.get('files', []):
                if file_info.get('file_id') == file_id:
                    filename = file_info.get('stored_name') or file_info.get('name', '')
                    if filename:
                        file_path = space_path / filename
                        break
        except Exception:
            pass
    
    # Fallback: treat file_id as actual filename
    if not file_path or not file_path.exists():
        file_path = space_path / file_id
    
    if not file_path.exists():
        abort(404)
    
    # Determine MIME type
    ext = file_path.suffix.lower()
    mime_types = {
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.ogg': 'audio/ogg',
        '.opus': 'audio/opus',
        '.m4a': 'audio/mp4',
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.mov': 'video/quicktime',
        '.avi': 'video/x-msvideo',
        '.mkv': 'video/x-matroska',
        '.m4v': 'video/mp4',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.svg': 'image/svg+xml',
        '.bmp': 'image/bmp',
        '.ico': 'image/x-icon',
        '.tiff': 'image/tiff',
        '.tif': 'image/tiff',
        '.flac': 'audio/flac',
        '.aac': 'audio/aac',
        '.json': 'application/json',
        '.txt': 'text/plain',
        '.md': 'text/markdown'
    }
    
    mimetype = mime_types.get(ext, 'application/octet-stream')
    
    response = send_from_directory(str(space_path), file_path.name, mimetype=mimetype)
    response.headers['X-Stash-Filename'] = file_path.name
    response.headers['X-Stash-Ref'] = f"stash://{space_id}/{file_id}"
    return response


@api_bp.route('/stash/upload', methods=['POST'])
def upload_to_stash():
    """
    Upload a file to the stash system.
    Used for file conversion (bypasses vision analysis).
    
    Accepts: multipart/form-data with 'file' field
    Optional: 'labels' field (comma-separated)
    
    Returns: { ok: true, stash_ref: "stash://...", space_id: "...", file_id: "..." }
    """
    import json
    import uuid
    import hashlib
    from datetime import datetime
    
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No file provided'}), 400
    
    file = request.files['file']
    if not file.filename:
        return jsonify({'ok': False, 'error': 'No file selected'}), 400
    
    try:
        # Generate space and file IDs
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        space_id = f"space_{timestamp}_{uuid.uuid4().hex[:8]}"
        file_id = f"f_{uuid.uuid4().hex[:12]}"
        
        # Create space directory
        space_path = get_stash_dir() / space_id
        space_path.mkdir(parents=True, exist_ok=True)
        
        # Determine filename (preserve original name)
        original_name = file.filename
        safe_name = original_name.replace('/', '_').replace('\\', '_')
        
        # Read file content
        content = file.read()
        file_size = len(content)
        
        # Calculate hash
        file_hash = hashlib.sha256(content).hexdigest()
        
        # Determine MIME type
        mime_type = file.content_type or 'application/octet-stream'
        
        # Save file
        file_path = space_path / safe_name
        with open(file_path, 'wb') as f:
            f.write(content)
        
        # Parse labels
        labels = request.form.get('labels', 'uploaded')
        label_list = [l.strip() for l in labels.split(',') if l.strip()]
        
        # Create meta.json
        meta = {
            'space_id': space_id,
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'last_used_at': datetime.utcnow().isoformat() + 'Z',
            'labels': label_list,
            'owner': 'jarvis',
            'scope': 'project',
            'ttl_days': 7,
            'pinned': False,
            'files': [{
                'file_id': file_id,
                'name': original_name,
                'stored_name': safe_name,
                'mime_type': mime_type,
                'size_bytes': file_size,
                'hash_sha256': file_hash,
                'tags': [],
                'tool_origin': 'web_upload',
                'created_at': datetime.utcnow().isoformat() + 'Z'
            }]
        }
        
        meta_path = space_path / 'meta.json'
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)
        
        stash_ref = f"stash://{space_id}/{file_id}"
        
        print(f"[Stash Upload] Saved {original_name} ({file_size} bytes) -> {stash_ref}")
        
        return jsonify({
            'ok': True,
            'stash_ref': stash_ref,
            'space_id': space_id,
            'file_id': file_id,
            'filename': original_name,
            'size_bytes': file_size
        })
        
    except Exception as e:
        print(f"[Stash Upload] Error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# =============================================================================
# Image Upload for Vision
# =============================================================================

UPLOADS_PATH = JARVIS_ROOT / 'jarvis-web' / 'data' / 'uploads'
GENERATED_IMAGES_PATH = JARVIS_ROOT / 'data' / 'generated_images'
UPLOAD_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
UPLOAD_MAX_FILE_BYTES = 30 * 1024 * 1024


def _uploaded_file_size_bytes(file) -> int | None:
    """Return upload size without consuming the stream when possible."""
    content_length = getattr(file, 'content_length', None)
    if content_length:
        return content_length

    stream = getattr(file, 'stream', None)
    if not stream or not hasattr(stream, 'tell') or not hasattr(stream, 'seek'):
        return None

    try:
        position = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(position)
        return size
    except Exception:
        return None


def _process_uploaded_image_file(file, suffix: str = '', include_base64: bool = True) -> dict:
    """
    Process one uploaded image file for vision analysis.
    Resizes large images and stores for conversation history.
    Returns {ok, filename, url, base64, ...} or {ok: False, error}.
    """
    from datetime import datetime
    from PIL import Image, ImageOps
    import io
    
    if not file or file.filename == '':
        return {'ok': False, 'error': 'No file selected'}
    
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in UPLOAD_ALLOWED_EXTENSIONS:
        return {
            'ok': False,
            'error': f'Invalid file type. Allowed: {", ".join(sorted(UPLOAD_ALLOWED_EXTENSIONS))}',
        }

    upload_size = _uploaded_file_size_bytes(file)
    if upload_size is not None and upload_size > UPLOAD_MAX_FILE_BYTES:
        return {'ok': False, 'error': 'Image too large (max 30MB)'}

    try:
        img = Image.open(file.stream)
        img = ImageOps.exif_transpose(img)
        
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        max_size = 1024
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            print(f"[Upload] Resized image from {file.filename} to {new_size}")
        
        UPLOADS_PATH.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S%f')
        filename = f"upload_{timestamp}{suffix}.jpg"
        filepath = UPLOADS_PATH / filename
        
        img.save(filepath, 'JPEG', quality=85, optimize=True)
        
        file_size_kb = filepath.stat().st_size / 1024
        print(f"[Upload] Saved {filename} ({img.size[0]}x{img.size[1]}, {file_size_kb:.1f}KB)")

        result = {
            'ok': True,
            'filename': filename,
            'url': f'/api/uploads/{filename}',
            'width': img.size[0],
            'height': img.size[1],
            'size_kb': round(file_size_kb, 1),
        }
        if include_base64:
            import base64

            buffer = io.BytesIO()
            img.save(buffer, 'JPEG', quality=85)
            result['base64'] = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return result
    except Exception as e:
        print(f"[Upload] Error processing image: {e}")
        return {'ok': False, 'error': str(e)}


@api_bp.route('/media-handoff/import', methods=['POST'])
def import_media_handoff():
    """Import generated media into Web's normal attachment storage."""
    data = request.get_json(silent=True) or {}
    media_type = data.get('media_type')
    filename = data.get('filename')

    # Keep this contract typed so a future video-gallery handoff can extend it
    # without allowing callers to submit arbitrary filesystem paths.
    if media_type != 'image':
        return jsonify({
            'ok': False,
            'error': f'Unsupported media type: {media_type or "missing"}',
        }), 400

    if (
        not isinstance(filename, str)
        or not filename
        or filename != Path(filename).name
        or '..' in filename
        or '/' in filename
        or '\\' in filename
    ):
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400

    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in UPLOAD_ALLOWED_EXTENSIONS:
        return jsonify({'ok': False, 'error': 'Unsupported image type'}), 400

    source_path = GENERATED_IMAGES_PATH / filename
    try:
        generated_root = GENERATED_IMAGES_PATH.resolve()
        resolved_source = source_path.resolve(strict=True)
        resolved_source.relative_to(generated_root)
    except (FileNotFoundError, OSError, ValueError):
        return jsonify({'ok': False, 'error': 'Image not found'}), 404

    if not resolved_source.is_file():
        return jsonify({'ok': False, 'error': 'Image not found'}), 404
    if resolved_source.stat().st_size > UPLOAD_MAX_FILE_BYTES:
        return jsonify({'ok': False, 'error': 'Image too large (max 30MB)'}), 400

    with resolved_source.open('rb') as stream:
        result = _process_uploaded_image_file(
            FileStorage(stream=stream, filename=filename),
            include_base64=False,
        )
    if not result.get('ok'):
        return jsonify(result), 400

    result['media_type'] = media_type
    return jsonify(result)


@api_bp.route('/upload-image', methods=['POST'])
def upload_image():
    """Upload a single image for vision analysis."""
    if 'image' not in request.files:
        return jsonify({'ok': False, 'error': 'No image file provided'}), 400

    mode = request.form.get('mode', 'cloud')
    image_limit = max_vision_images(mode)
    current_count = max(0, request.form.get('current_image_count', 0, type=int))
    if current_count + 1 > image_limit:
        return jsonify({
            'ok': False,
            'error': f'Maximum {image_limit} images allowed in {mode} mode',
            'limit': image_limit,
            'provided': current_count + 1,
        }), 400

    include_base64 = request.form.get('include_base64', 'true').lower() in {'1', 'true', 'yes', 'on'}
    result = _process_uploaded_image_file(request.files['image'], include_base64=include_base64)
    if not result.get('ok'):
        return jsonify(result), 400
    return jsonify(result)


@api_bp.route('/upload-pdf', methods=['POST'])
def upload_pdf():
    """Atomically upload one validated PDF directly into Stash."""
    allowed, retry_after = check_pdf_upload_rate(request.remote_addr or "unknown")
    if not allowed:
        response = jsonify({
            "ok": False,
            "error": f"Too many PDF uploads. Try again in {retry_after} seconds.",
            "error_code": "pdf_upload_rate_limited",
            "retryable": True,
        })
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response

    max_bytes = get_pdf_upload_max_bytes()
    # The streaming limit below is authoritative. This early check avoids parsing
    # clearly oversized multipart bodies while leaving room for form boundaries.
    if request.content_length and request.content_length > max_bytes + 1024 * 1024:
        error = PDFUploadError(
            f"PDF is too large (max {max_bytes // (1024 * 1024)}MB).",
            error_code="pdf_upload_too_large",
            status_code=413,
        )
        return jsonify(error.to_payload()), error.status_code

    files = request.files.getlist("file")
    if len(files) != 1 or not files[0].filename:
        error = PDFUploadError(
            "Select exactly one PDF file.",
            error_code="pdf_upload_missing",
        )
        return jsonify(error.to_payload()), error.status_code

    try:
        attachment, idempotent_replay = save_pdf_upload(
            files[0],
            request.form.get("upload_id", ""),
            max_bytes=max_bytes,
        )
        return jsonify({
            "ok": True,
            "attachment": attachment,
            "idempotent_replay": idempotent_replay,
        })
    except PDFUploadError as exc:
        return jsonify(exc.to_payload()), exc.status_code
    except Exception as exc:
        print(
            f"[PDF Upload] Unexpected upload failure: {type(exc).__name__}: {exc}",
            flush=True,
        )
        error = PDFUploadError(
            "The PDF could not be stored. Please retry.",
            error_code="pdf_upload_failed",
            status_code=500,
            retryable=True,
        )
        return jsonify(error.to_payload()), error.status_code


@api_bp.route('/upload-images', methods=['POST'])
def upload_images():
    """Upload one or more images for vision analysis."""
    files = request.files.getlist('images')
    if not files:
        files = request.files.getlist('image')
    if not files:
        return jsonify({'ok': False, 'error': 'No image files provided'}), 400

    mode = request.form.get('mode', 'cloud')
    include_base64 = request.form.get('include_base64', 'true').lower() in {'1', 'true', 'yes', 'on'}
    image_limit = max_vision_images(mode)
    current_count = max(0, request.form.get('current_image_count', 0, type=int))
    provided = current_count + len(files)
    if provided > image_limit:
        return jsonify({
            'ok': False,
            'error': f'Maximum {image_limit} images allowed in {mode} mode',
            'limit': image_limit,
            'provided': provided,
        }), 400

    uploaded = []
    errors = []
    for index, file in enumerate(files):
        result = _process_uploaded_image_file(
            file,
            suffix=f'_{index}' if index else '',
            include_base64=include_base64,
        )
        if result.get('ok'):
            uploaded.append(result)
        else:
            label = file.filename or f'file {index + 1}'
            errors.append(f'{label}: {result.get("error", "upload failed")}')

    if not uploaded:
        return jsonify({'ok': False, 'error': errors[0] if errors else 'Upload failed', 'errors': errors}), 400

    payload = {'ok': True, 'images': uploaded}
    if errors:
        payload['errors'] = errors
    return jsonify(payload)


@api_bp.route('/uploads/<filename>', methods=['GET'])
def serve_upload(filename):
    """Serve uploaded images"""
    if '..' in filename or '/' in filename:
        abort(404)
    
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        abort(404)
    
    upload_path = UPLOADS_PATH / filename
    if upload_path.is_file():
        return send_from_directory(str(UPLOADS_PATH), filename)

    fallback = find_upload_stash_fallback(
        filename,
        JARVIS_ROOT / 'data' / 'web_conversations',
        get_stash_dir(),
    )
    if fallback:
        return send_file(fallback)
    abort(404)


# =============================================================================
# WORKFLOWS API - Explicit multi-tool pipelines (triggered via /workflow_name)
# =============================================================================

@api_bp.route('/workflows', methods=['GET'])
@_scoped_request_config
def list_workflows():
    """List workflows available in the explicitly requested mode."""
    from workflow_loader import WorkflowLoader
    
    workflows = {}

    loader = WorkflowLoader(explicit_only=True)
    for wf_id, wf_data in loader.workflows.items():
        if _web_workflow_availability(wf_data)["available"]:
            workflows[wf_id] = _workflow_record(wf_id, wf_data)
    
    return jsonify({
        'ok': True,
        'count': len(workflows),
        'workflows': workflows
    })


@api_bp.route('/workflows/<workflow_id>', methods=['GET'])
@_scoped_request_config
def get_workflow(workflow_id):
    """Get a workflow only when it is available in the requested mode."""
    from workflow_loader import WorkflowLoader

    loader = WorkflowLoader(explicit_only=True)
    wf_data = _resolve_workflow(loader, workflow_id)
    if wf_data:
        availability = _web_workflow_availability(wf_data)
        if not availability["available"]:
            from workflow_availability import workflow_unavailable_message

            return jsonify({
                'ok': False,
                'error': workflow_unavailable_message(wf_data, availability),
            }), 409
        return jsonify({
            'ok': True,
            'workflow': wf_data,
        })
    
    return jsonify({'ok': False, 'error': f'Workflow not found: {workflow_id}'}), 404


@api_bp.route('/prompts', methods=['GET'])
@_scoped_request_config
def list_prompts():
    """List @prompts visible in the explicitly requested mode."""
    prompts = {}

    tools_by_name = _prompt_tools_by_name()
    for name, prompt_file in _iter_prompt_files():
        try:
            record = _load_prompt_record(name, prompt_file)
            if _prompt_is_available(record, tools_by_name):
                prompts[name] = record
        except Exception as e:
            print(f"[Prompts] Error loading {prompt_file}: {e}")

    return jsonify({
        'ok': True,
        'count': len(prompts),
        'prompts': prompts
    })


@api_bp.route('/prompts/<name>', methods=['GET'])
@_scoped_request_config
def get_prompt(name):
    """Get a prompt only when it is available in the requested mode."""
    prompt_file = _resolve_prompt_file(name)

    if prompt_file:
        try:
            record = _load_prompt_record(name, prompt_file)
            if not _prompt_is_available(record, _prompt_tools_by_name()):
                return jsonify({'ok': False, 'error': f'Prompt not available: {name}'}), 404
            return jsonify({
                'ok': True,
                'prompt': record
            })
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500

    return jsonify({'ok': False, 'error': f'Prompt not found: {name}'}), 404


@api_bp.route('/enhance-prompt', methods=['POST'])
@_scoped_request_config
def enhance_prompt():
    """
    ✨ AI-powered prompt enhancement
    Takes a rough user query and transforms it into an optimal prompt
    using full knowledge of Jarvis capabilities, tools, and best practices.
    """
    
    data = request.get_json() or {}
    user_input = data.get('input', '').strip()
    attached_image = data.get('image') if isinstance(data.get('image'), dict) else None
    image_action = str(data.get('image_action') or '').strip().lower()
    
    if not user_input:
        return jsonify({'ok': False, 'error': 'No input provided'}), 400
    
    # Get current mode
    current_mode = str(data.get('mode') or get_web_setting('defaults.mode', 'cloud')).strip().lower()
    
    try:
        # Load LLM provider
        sys.path.insert(0, str(JARVIS_ROOT / 'lib'))
        from config_loader import load_config, get_config_value
        from llm_provider import create_configured_provider
        from ..config import load_web_config
        
        load_config(mode=current_mode)
        
        mode_config = load_web_config().get(current_mode, {})
        provider_type = str(
            mode_config.get('llm_provider')
            or get_config_value('LLM_PROVIDER', 'xai' if current_mode == 'cloud' else 'ollama')
        ).strip().lower()
        provider_model = mode_config.get('llm_model')
        vision_warning = None

        # Vision-grounded enhancement for an attached image. Resolve only the
        # server-owned upload filename; never fetch an arbitrary client URL.
        if attached_image:
            import base64
            from vision_provider import analyze_images

            filename = str(attached_image.get('filename') or '').strip()
            if not filename:
                image_url = str(attached_image.get('url') or '').split('?', 1)[0]
                filename = image_url.rsplit('/', 1)[-1]
            uploads_root = (WEB_DATA_PATH / 'uploads').resolve()
            upload_path = (uploads_root / filename).resolve()
            if (
                not filename
                or filename != Path(filename).name
                or not upload_path.is_relative_to(uploads_root)
                or not upload_path.is_file()
            ):
                return jsonify({'ok': False, 'error': 'Attached upload could not be resolved'}), 400

            action_label = {
                'video': 'image-to-video generation',
                'image': 'image editing',
                'analyze': 'image analysis',
            }.get(image_action, 'an image task')
            grounded_prompt = f"""Inspect the attached image and rewrite the user's instruction as a concise, production-ready prompt for {action_label}.

Rules:
- Preserve the user's exact intent and requested action.
- Use only visual facts clearly supported by the image.
- Do not invent subjects, people, identities, character counts, objects, locations, or actions.
- Do not guess a real person, brand, franchise, or copyrighted character unless the user explicitly named it.
- For image-to-video, add only useful motion, camera, timing, and audio details that fit the visible scene.
- For image editing, describe only the requested change and necessary visible context.
- Return only the enhanced prompt text, with no explanation or quotation marks.

User instruction: {user_input}"""
            try:
                enhanced = analyze_images(
                    [base64.b64encode(upload_path.read_bytes()).decode('ascii')],
                    grounded_prompt,
                    mode=current_mode,
                    provider=provider_type,
                    model=provider_model,
                ).strip()
                if not enhanced:
                    raise RuntimeError('Vision provider returned no text')
                return jsonify({
                    'ok': True,
                    'original': user_input,
                    'enhanced': enhanced,
                    'mode': current_mode,
                    'provider': provider_type,
                    'vision_grounded': True,
                })
            except Exception as vision_error:
                print(
                    f"[ENHANCE] Vision unavailable for {provider_type}/{provider_model or 'default'}: "
                    f"{vision_error}",
                    file=sys.stderr,
                )
                vision_warning = (
                    "The selected model could not inspect the attached image, so Enhance used text only. "
                    "Visual details were not inferred."
                )

        # Get tool summaries for context (only enabled, non-blocked tools)
        tool_service = get_tool_service()
        tools = tool_service.get_tools_summary()
        # Filter to only available tools
        available_tools = [
            t for t in tools 
            if (
                t.get('enabled', True)
                and t.get('available', True)
                and not t.get('blocked', False)
            )
        ]
        available_tools_by_name = {
            str(tool.get('name') or ''): tool
            for tool in available_tools
            if tool.get('name')
        }
        requested_tool_hints = data.get('tool_hints')
        if not isinstance(requested_tool_hints, list):
            requested_tool_hints = []
        selected_tool_hints = []
        for name in requested_tool_hints:
            if (
                isinstance(name, str)
                and name in available_tools_by_name
                and name not in selected_tool_hints
            ):
                selected_tool_hints.append(name)
            if len(selected_tool_hints) >= 3:
                break

        tool_descriptions = "\n".join([
            f"- {t['name']}: {t.get('description', 'No description')[:100]}"
            for t in available_tools[:100]  # Limit to 100 tools, lists them A-Z , not smart but currently at 70 tools 4/6/26 is 1,900 token context window
        ])
        selected_tool_context = ""
        if selected_tool_hints:
            selected_descriptions = "\n".join(
                f"- {name}: "
                f"{available_tools_by_name[name].get('description', 'No description')[:280]}"
                for name in selected_tool_hints
            )
            selected_tool_context = f"""
## User-Selected Tool Context
The user explicitly selected these capabilities. Use them to understand the
target task, but do not mention their names or internal parameters in the
enhanced prompt:
{selected_descriptions}
"""
        
        # Build the enhancement system prompt
        system_prompt = f"""You are a prompt enhancement assistant for Jarvis, an AI voice assistant.

Your job is to take a rough, casual user input and transform it into an optimal, detailed prompt that will get the best results from Jarvis.

{f'''IMPORTANT: An attached image was present, but vision was unavailable. Enhance only the user's text. Preserve references such as "the person" or "the background" exactly and do not invent any visual details.''' if vision_warning else ''}

## Jarvis Capabilities
- **Native Web Search**: Jarvis has built-in web search that provides comprehensive, real-time information. This is BETTER than external search tools.
- **Tools Available**:
{tool_descriptions}

{selected_tool_context}

## Enhancement Guidelines
1. **Be Specific**: Add details about what information is wanted
2. **Request Format**: Suggest how results should be structured (bullet points, sections, comparisons)
3. **Time Context**: Add "current", "latest", "December 2025" when asking for news/data
4. **Scope**: Define scope (e.g., "past 24 hours", "top 5", "major sources")
5. **DON'T add commands** like /canvas or @prompts - just enhance the natural language
6. **Keep it conversational** - this is for a voice assistant
7. **If user wants to save/view results**, mention Canvas but naturally
8. **Clarify the primary intent**: Make the user's main goal explicit near the start (e.g. find, compare, buy, verify, summarize, troubleshoot, build, update)
9. **Preserve exact entities**: Keep product names, model numbers, company names, URLs, and other exact identifiers unchanged
10. **Reduce distracting nouns**: If the query includes domain words that could pull retrieval the wrong way, rewrite so the real action is clearer than the background topic
11. **Express desired outcome**: State what a successful answer should deliver, such as a compatible product, a verified recommendation, a short comparison, or a direct answer
12. **Stay provider/tool agnostic**: Do not mention tool names, APIs, or internal system behavior
13. **Do not invent operational parameters**: Tool hints are routing preferences, not permission to add model names, providers, durations, dimensions, aspect ratios, resolutions, file types, output formats, filenames, or schema fields unless the user supplied them
14. **Enhance media creatively, not mechanically**: For music, develop useful creative direction such as mood, genre family, instrumentation, energy, arrangement, vocal intent, and an original lyrical theme. Use qualitative tempo language rather than inventing an exact BPM. Do not introduce artist/band names, copyrighted songs or lyrics, or voice imitation. For visual media, improve scene, composition, motion, camera, lighting, and atmosphere without inventing operational parameters
15. **Preserve user choices**: If the user supplied an operational value, keep it exactly; otherwise leave that choice to Jarvis and the selected tool

## Examples
Input: "bitcoin news"
Enhanced: "What's the latest Bitcoin news and price action? Include the current price, significant price movements in the last 24 hours, and the top 3-5 major news headlines affecting the market. Summarize key analyst predictions if available."

Input: "weather"
Enhanced: "What's the current weather and forecast for my location? Include today's conditions, temperature range, and the outlook for the next few days."

Input: "email john about meeting"
Enhanced: "Send an email to John about scheduling a meeting. Keep it professional and brief, asking about his availability this week."

Input: "need mount for ambient weather ws-2902 on amazon"
Enhanced: "Find a compatible Amazon pole-mount option for the Ambient Weather WS-2902 WiFi Smart Weather Station. Focus on products I can actually buy, including fixed pole mounts or right-angle adjustable bracket mounts if they fit. Compare the best compatible options with links, prices, and a short note on why each should work."

Now enhance the following input. Return ONLY the enhanced prompt text, nothing else."""

        enhancement_message = user_input
        if vision_warning:
            # A text-only model cannot ground new visual detail. Use a narrow
            # media rewrite contract instead of the general Jarvis enhancer,
            # which can otherwise replace a short instruction with generic
            # video/image boilerplate or an assistant-style clarification.
            system_prompt = f"""You rewrite user instructions for {action_label}.

The attached image is NOT visible to you. Improve only the instruction text the user supplied.

Rules:
- Preserve every concrete action, subject reference, camera request, timing request, and audio request from the original.
- References such as "it", "the person", "her head", or "the background" must remain references; never guess what they depict.
- Do not invent visual details, identities, objects, scenery, animation, audio, or intent.
- Do not replace the instruction with generic advice such as "create a video with motion".
- Do not ask a question, request more details, offer help, or mention that you cannot see the image.
- If the instruction is already concise and cannot be safely improved without seeing the image, return it unchanged.
- Return only the rewritten generation prompt, with no label, explanation, or quotation marks."""
            enhancement_message = (
                "Rewrite this exact instruction without answering it or changing its intent:\n\n"
                f"{user_input}"
            )

        # Create the text provider from the effective per-mode Web settings.
        _, _, provider = create_configured_provider(
            provider_override=provider_type,
            model_override=provider_model,
            default_provider='ollama' if current_mode == 'local' else 'xai',
            mode=current_mode,
        )
        
        # Call LLM to enhance
        # chat() signature: chat(message: str, system_prompt: str = None, max_tokens: int = None) -> str
        enhanced = provider.chat(
            message=enhancement_message,
            system_prompt=system_prompt,
            max_tokens=500
        )
        
        # Clean up response
        if enhanced:
            enhanced = enhanced.strip()
            # Remove quotes if LLM wrapped the response
            if enhanced.startswith('"') and enhanced.endswith('"'):
                enhanced = enhanced[1:-1]
            if enhanced.startswith("Enhanced:"):
                enhanced = enhanced[9:].strip()
        else:
            enhanced = user_input  # Fallback to original if empty

        if vision_warning:
            # Text-only enhancement must never destructively replace the
            # user's media instruction with assistant chatter. Models differ
            # in instruction-following quality, so keep the original on any
            # clarification/meta-response instead of putting it in the media
            # generation text area.
            unsafe_meta_phrases = (
                "ask me what",
                "what you'd like",
                "what you would like",
                "if you need a specific",
                "please provide",
                "please specify",
                "could you provide",
                "can you provide",
                "i need more",
                "need more details",
                "cannot see the image",
                "can't see the image",
                "unable to see the image",
            )
            enhanced_lower = enhanced.lower()
            if any(phrase in enhanced_lower for phrase in unsafe_meta_phrases):
                enhanced = user_input
                vision_warning += " The model returned a generic clarification, so your original text was kept."
        
        return jsonify({
            'ok': True,
            'original': user_input,
            'enhanced': enhanced,
            'mode': current_mode,
            'provider': provider_type,
            'tool_hints': selected_tool_hints,
            'vision_grounded': False,
            'vision_warning': vision_warning,
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'ok': False,
            'error': str(e),
            'original': user_input
        }), 500
