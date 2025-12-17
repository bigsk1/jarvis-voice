"""
API Routes for Jarvis Web UI
REST endpoints for status, tools, settings, and more
"""
import os
from pathlib import Path
from flask import Blueprint, jsonify, request, send_from_directory, abort
from ..services.tool_discovery import get_tool_service
from ..services.settings_manager import get_settings_manager
from ..config import get_web_setting, JARVIS_ROOT, reload_web_config
import sys

api_bp = Blueprint('api', __name__, url_prefix='/api')

# Path to generated images
IMAGES_PATH = JARVIS_ROOT / 'data' / 'generated_images'


@api_bp.route('/status', methods=['GET'])
def get_status():
    """Health check and basic status info"""
    tool_service = get_tool_service()
    settings = get_settings_manager()
    
    return jsonify({
        'ok': True,
        'status': 'running',
        'version': '1.0.0',
        'mode': settings.mode,
        'tools_count': tool_service.get_tool_count(),
        'features': {
            'tts': get_web_setting('audio.tts_enabled', False),
            'stt': get_web_setting('audio.stt_enabled', False),
            'auth': get_web_setting('auth.enabled', False)
        }
    })


@api_bp.route('/tools', methods=['GET'])
def list_tools():
    """List all available tools"""
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
def get_tool(name):
    """Get details for a specific tool"""
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
def refresh_tools():
    """Reload tools from disk"""
    tool_service = get_tool_service()
    tool_service.refresh()
    
    return jsonify({
        'ok': True,
        'message': 'Tools refreshed',
        'count': tool_service.get_tool_count()
    })


@api_bp.route('/settings', methods=['GET'])
def get_settings():
    """Get current settings for UI"""
    settings = get_settings_manager()
    
    return jsonify({
        'ok': True,
        'settings': settings.get_settings_for_ui(),
        # Legacy format for backward compat
        'jarvis': settings.get_settings_with_status(),
        'web': settings.get_web_settings()
    })


@api_bp.route('/settings/schema', methods=['GET'])
def get_settings_schema():
    """Get settings schema for UI form generation"""
    settings = get_settings_manager()
    
    return jsonify({
        'ok': True,
        'schema': settings.get_schema()
    })


@api_bp.route('/settings/system', methods=['GET'])
def get_system_config():
    """Get read-only system config values from cloud.env"""
    from ..config import load_jarvis_config, get_jarvis_setting
    
    # Load the current mode's config
    mode = get_web_setting('defaults.mode', 'cloud')
    load_jarvis_config(mode)
    
    # Return key system settings (read-only, informational)
    return jsonify({
        'ok': True,
        'mode': mode,
        'config': {
            # LLM Settings
            'LLM_PROVIDER': get_jarvis_setting('LLM_PROVIDER', 'xai'),
            'XAI_MODEL': get_jarvis_setting('XAI_MODEL', ''),
            'ANTHROPIC_MODEL': get_jarvis_setting('ANTHROPIC_MODEL', ''),
            'OPENAI_MODEL': get_jarvis_setting('OPENAI_MODEL', ''),
            
            # Thresholds (important!)
            'TOOL_SIMILARITY_THRESHOLD': get_jarvis_setting('TOOL_SIMILARITY_THRESHOLD', '0.0'),
            'SEMANTIC_SIMILARITY_THRESHOLD': get_jarvis_setting('SEMANTIC_SIMILARITY_THRESHOLD', '0.30'),
            
            # TTS/Audio
            'TTS_PROVIDER': get_jarvis_setting('TTS_PROVIDER', 'elevenlabs'),
            'ELEVENLABS_TTS_VOICE': get_jarvis_setting('ELEVENLABS_TTS_VOICE', ''),
            'STATUS_UPDATES_ENABLED': get_jarvis_setting('STATUS_UPDATES_ENABLED', 'true'),
            
            # Features
            'JARVIS_INTELLIGENCE': get_jarvis_setting('JARVIS_INTELLIGENCE', 'false'),
            
            # Image
            'IMAGE_TOOL_PROVIDER': get_jarvis_setting('IMAGE_TOOL_PROVIDER', 'gemini'),
            
            # System
            'JARVIS_TIMEZONE': get_jarvis_setting('JARVIS_TIMEZONE', 'America/Los_Angeles'),
        }
    })


@api_bp.route('/settings/web', methods=['PUT'])
def update_web_settings():
    """Update web UI settings/overrides"""
    settings = get_settings_manager()
    data = request.get_json()
    
    if not data:
        return jsonify({'ok': False, 'error': 'No data provided'}), 400
    
    # Use new override system if structured data provided
    if any(k in data for k in ['llm_provider', 'llm_model', 'image_provider', 'tool_similarity', 'memory_similarity', 'tts_enabled']):
        success = settings.save_web_overrides(data)
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
def reset_settings():
    """Reset web overrides to cloud.env defaults"""
    settings = get_settings_manager()
    success = settings.reset_to_defaults()
    
    return jsonify({
        'ok': success,
        'message': 'Reset to defaults' if success else 'Failed to reset'
    })


@api_bp.route('/settings/models/<provider>', methods=['GET'])
def get_provider_models(provider):
    """Get available models for a provider"""
    from ..services.settings_manager import PROVIDER_MODELS
    
    models = PROVIDER_MODELS.get(provider, [])
    return jsonify({
        'ok': True,
        'provider': provider,
        'models': models
    })


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
    
    # Refresh tool discovery to reflect new blocked list
    tool_service = get_tool_service()
    tool_service.refresh()
    
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
    
    limit = request.args.get('limit', 50, type=int)
    conversations = store.list_conversations(limit=limit)
    
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
    
    data = request.get_json() or {}
    title = data.get('title', '')
    
    if store.update_title(conv_id, title):
        return jsonify({
            'ok': True,
            'message': 'Title updated'
        })
    else:
        return jsonify({
            'ok': False,
            'error': 'Conversation not found'
        }), 404


@api_bp.route('/tts', methods=['POST'])
def text_to_speech():
    """Generate TTS audio from text using ElevenLabs or OpenAI"""
    data = request.get_json() or {}
    text = data.get('text', '')
    
    if not text:
        return jsonify({'ok': False, 'error': 'No text provided'}), 400
    
    try:
        import subprocess
        import tempfile
        from datetime import datetime
        
        # Load config
        from ..config import load_jarvis_config, get_jarvis_setting
        settings = get_settings_manager()
        load_jarvis_config(settings.mode)
        
        provider = get_jarvis_setting('TTS_PROVIDER', 'elevenlabs')
        
        # Create output directory
        tts_dir = JARVIS_ROOT / 'audio' / 'cloud' / 'tts'
        tts_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if provider == 'elevenlabs':
            audio_path = _generate_elevenlabs_tts(text, tts_dir, timestamp)
        else:
            audio_path = _generate_openai_tts(text, tts_dir, timestamp)
        
        if audio_path and audio_path.exists():
            return send_from_directory(
                str(audio_path.parent),
                audio_path.name,
                mimetype='audio/mpeg'
            )
        else:
            return jsonify({'ok': False, 'error': 'TTS generation failed'}), 500
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


def _generate_elevenlabs_tts(text: str, output_dir: Path, timestamp: str) -> Path:
    """Generate TTS using ElevenLabs API"""
    import requests
    from ..config import get_jarvis_setting
    
    api_key = get_jarvis_setting('ELEVENLABS_API_KEY', '')
    voice_id = get_jarvis_setting('ELEVENLABS_TTS_VOICE', 'pgCnBQgKPGkIP8fJuita')
    model_id = get_jarvis_setting('ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2')
    
    if not api_key:
        raise ValueError('ELEVENLABS_API_KEY not configured')
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.7,
            "similarity_boost": 0.75,
            "style": 0.5,
            "use_speaker_boost": True
        }
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code != 200:
        raise ValueError(f"ElevenLabs API error: {response.status_code} - {response.text}")
    
    # Save audio (ElevenLabs returns mp3)
    output_path = output_dir / f"tts_{timestamp}.mp3"
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
    
    response = requests.post(url, json=payload, headers=headers)
    
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
    allowed_extensions = {'.mp3', '.wav', '.ogg', '.m4a'}
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        abort(404)
    
    # Check TTS directory first (cloud/tts)
    tts_path = JARVIS_ROOT / 'audio' / 'cloud' / 'tts'
    if tts_path.exists() and (tts_path / filename).exists():
        return send_from_directory(str(tts_path), filename)
    
    # Check recordings directory 
    recordings_path = JARVIS_ROOT / 'audio' / 'cloud' / 'recordings'
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

