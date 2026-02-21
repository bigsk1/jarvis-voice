"""
API Routes for Jarvis Web UI
REST endpoints for status, tools, settings, and more
"""
import os
import json
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, request, send_from_directory, abort
from ..services.tool_discovery import get_tool_service
from ..services.settings_manager import get_settings_manager
from ..config import get_web_setting, JARVIS_ROOT, reload_web_config
from webui_auth import is_auth_enabled
import sys

api_bp = Blueprint('api', __name__, url_prefix='/api')


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


# Path to generated images
IMAGES_PATH = JARVIS_ROOT / 'data' / 'generated_images'

# Path to generated music
MUSIC_PATH = JARVIS_ROOT / 'data' / 'generated_music'

# Path to generated videos
VIDEOS_PATH = JARVIS_ROOT / 'data' / 'generated_videos'

# Path to stash
STASH_PATH = JARVIS_ROOT / 'data' / 'stash'

# Paths for prompts and workflows
WEB_DATA_PATH = JARVIS_ROOT / 'jarvis-web' / 'data'
PROMPTS_PATH = WEB_DATA_PATH / 'prompts'
WORKFLOWS_PATH = JARVIS_ROOT / 'data' / 'workflows'  # Workflows are in main data folder


@api_bp.route('/status', methods=['GET'])
def get_status():
    """Health check and basic status info"""
    tool_service = get_tool_service()
    current_mode = get_web_setting('defaults.mode', 'cloud')
    settings = get_settings_manager(current_mode)
    
    return jsonify({
        'ok': True,
        'status': 'running',
        'version': _get_jarvis_version(),
        'mode': settings.mode,
        'tools_count': tool_service.get_tool_count(),
        'features': {
            'tts': get_web_setting('audio.tts_enabled', False),
            'stt': get_web_setting('audio.stt_enabled', False),
            'auth': is_auth_enabled()  # Dynamic from WEBUI_PASSWORD env var
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
    # Ensure settings manager has correct mode
    current_mode = get_web_setting('defaults.mode', 'cloud')
    settings = get_settings_manager(current_mode)
    
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
    """Get read-only system config values from current mode's env file"""
    from ..config import load_jarvis_config, get_jarvis_setting
    
    # Use mode from query param or fall back to default
    mode = request.args.get('mode') or get_web_setting('defaults.mode', 'cloud')
    load_jarvis_config(mode)
    
    # Return key system settings (read-only, informational)
    config = {
        # LLM Settings
        'LLM_PROVIDER': get_jarvis_setting('LLM_PROVIDER', 'ollama' if mode == 'local' else 'xai'),
        
        # Thresholds (important!)
        'TOOL_SIMILARITY_THRESHOLD': get_jarvis_setting('TOOL_SIMILARITY_THRESHOLD', '0.0'),
        'SEMANTIC_SIMILARITY_THRESHOLD': get_jarvis_setting('SEMANTIC_SIMILARITY_THRESHOLD', '0.30'),
        
        # TTS/Audio (mode-specific)
        'TTS_PROVIDER': get_jarvis_setting('TTS_PROVIDER', 'kokoro' if mode == 'local' else 'elevenlabs'),
        'STATUS_UPDATES_ENABLED': get_jarvis_setting('STATUS_UPDATES_ENABLED', 'true'),
        
        # Features
        'JARVIS_INTELLIGENCE': get_jarvis_setting('JARVIS_INTELLIGENCE', 'false'),
    }
    
    # Add mode-specific model info
    if mode == 'local':
        config['OLLAMA_MODEL'] = get_jarvis_setting('OLLAMA_MODEL', 'qwen3')
        config['OLLAMA_BASE_URL'] = get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434')
        config['TTS_URL'] = get_jarvis_setting('TTS_URL', '')
        config['TTS_VOICE'] = get_jarvis_setting('TTS_VOICE', '')
        # Kokoro doesn't have models, but Qwen3-TTS might
        config['QWEN3_TTS_VOICE'] = get_jarvis_setting('QWEN3_TTS_VOICE', '')
    else:
        config['XAI_MODEL'] = get_jarvis_setting('XAI_MODEL', '')
        config['ANTHROPIC_MODEL'] = get_jarvis_setting('ANTHROPIC_MODEL', '')
        config['OPENAI_MODEL'] = get_jarvis_setting('OPENAI_MODEL', '')
        config['ELEVENLABS_TTS_VOICE'] = get_jarvis_setting('ELEVENLABS_TTS_VOICE', '')
        config['ELEVENLABS_TTS_MODEL'] = get_jarvis_setting('ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2')
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'config': {
            **config,
            
            # Image
            'IMAGE_TOOL_PROVIDER': get_jarvis_setting('IMAGE_TOOL_PROVIDER', 'gemini'),
            'VIDEO_TOOL_PROVIDER': get_jarvis_setting('VIDEO_TOOL_PROVIDER', 'xai'),
            
            # Feedback/Evolution System
            'FEEDBACK_RANDOM_ENABLED': get_jarvis_setting('FEEDBACK_RANDOM_ENABLED', 'false'),
            'FEEDBACK_RANDOM_CHANCE': get_jarvis_setting('FEEDBACK_RANDOM_CHANCE', '0.0'),
            'FEEDBACK_PROVIDER': get_jarvis_setting('FEEDBACK_PROVIDER', 'anthropic'),
            
            # System
            'JARVIS_TIMEZONE': get_jarvis_setting('JARVIS_TIMEZONE', 'America/Los_Angeles'),
            'JARVIS_DEFAULT_LOCATION': get_jarvis_setting('JARVIS_DEFAULT_LOCATION', 'Hillsboro, Oregon'),
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
    if any(k in data for k in ['llm_provider', 'llm_model', 'image_provider', 'video_provider', 'tool_similarity', 'memory_similarity', 'tts_enabled']):
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


@api_bp.route('/tts/usage', methods=['GET'])
def get_tts_usage():
    """Get TTS usage/quota for ElevenLabs (only applicable for cloud mode with ElevenLabs)"""
    import requests as http_requests
    from ..config import load_jarvis_config, get_jarvis_setting
    
    # Get mode from query param
    mode = request.args.get('mode', 'cloud')
    load_jarvis_config(mode)
    
    tts_provider = get_jarvis_setting('TTS_PROVIDER', 'elevenlabs' if mode == 'cloud' else 'kokoro')
    
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
    conversations = store.list_conversations(limit=100)  # Search up to 100 conversations
    
    for conv_summary in conversations:
        conv = store.get_conversation(conv_summary['id'])
        if not conv:
            continue
        
        matches = []
        for msg in conv.get('messages', []):
            content = msg.get('content', '').lower()
            if query in content:
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
                
                if len(matches) >= limit_per_conv:
                    break
        
        if matches:
            results.append({
                'conversation_id': conv['id'],
                'title': conv.get('title', 'Untitled'),
                'updated_at': conv.get('updated_at'),
                'matches': matches,
                'total_matches': len([m for m in conv.get('messages', []) 
                                      if query in m.get('content', '').lower()])
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
            
            # Include tool info if present
            tools = msg.get('tools_used', [])
            if tools:
                lines.append(f"*Tools used: {', '.join(tools)}*")
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
def speech_to_text():
    """Transcribe audio to text - uses mode-specific provider
    
    Cloud mode: OpenAI Whisper API
    Local mode: faster-whisper (local)
    
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
        stt_model = get_jarvis_setting('STT_MODEL', 'whisper-1')
        print(f"[STT] ========================================", flush=True)
        print(f"[STT] Mode: {mode}, Provider: {provider}, Model: {stt_model}", flush=True)
        
        # Save uploaded audio to temp file
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
            audio_file.save(tmp.name)
            tmp_path = tmp.name
        
        print(f"[STT] Audio saved to: {tmp_path}", flush=True)
        
        try:
            if provider == 'faster-whisper':
                # Local: use faster-whisper via stt_local.py
                print(f"[STT] Using LOCAL faster-whisper...", flush=True)
                transcript = _transcribe_local(tmp_path)
            else:
                # Cloud: use OpenAI Whisper API
                print(f"[STT] Using CLOUD OpenAI Whisper API...", flush=True)
                transcript = _transcribe_openai(tmp_path)
            
            if not transcript:
                return jsonify({'ok': False, 'error': 'No speech detected'}), 400
            
            print(f"[STT] ✓ Transcript: {transcript}", flush=True)
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


def _transcribe_openai(audio_path: str) -> str:
    """Transcribe audio using OpenAI Whisper API"""
    import os
    import requests
    from ..config import get_jarvis_setting
    
    api_key = get_jarvis_setting('OPENAI_API_KEY', '')
    model = get_jarvis_setting('STT_MODEL', 'whisper-1')
    
    if not api_key:
        raise ValueError('OPENAI_API_KEY not configured')
    
    # Convert webm to wav if needed (OpenAI prefers wav/mp3)
    wav_path = _convert_to_wav(audio_path)
    
    try:
        url = "https://api.openai.com/v1/audio/transcriptions"
        
        with open(wav_path, 'rb') as f:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (os.path.basename(wav_path), f, "audio/wav")},
                data={"model": model},
                timeout=30
            )
        
        if response.status_code != 200:
            raise ValueError(f"OpenAI STT error: {response.status_code} - {response.text}")
        
        result = response.json()
        return result.get('text', '').strip()
    finally:
        # Clean up converted file
        if wav_path != audio_path and os.path.exists(wav_path):
            os.unlink(wav_path)


def _transcribe_local(audio_path: str) -> str:
    """Transcribe audio using local faster-whisper"""
    import os
    import subprocess
    
    # Convert webm to wav for faster-whisper
    wav_path = _convert_to_wav(audio_path)
    
    try:
        # Use the existing stt_local.py script
        stt_script = JARVIS_ROOT / 'bin' / 'stt_local.py'
        
        result = subprocess.run(
            ['python3', str(stt_script), wav_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"[STT] Local STT error: {result.stderr}", flush=True)
            raise ValueError(f"Local STT failed: {result.stderr}")
        
        return result.stdout.strip()
    finally:
        # Clean up converted file
        if wav_path != audio_path and os.path.exists(wav_path):
            os.unlink(wav_path)


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
def text_to_speech():
    """Generate TTS audio from text - uses mode-specific provider"""
    data = request.get_json() or {}
    text = data.get('text', '')
    mode = data.get('mode')  # Accept mode from client to ensure sync
    
    if not text:
        return jsonify({'ok': False, 'error': 'No text provided'}), 400
    
    try:
        import requests
        from datetime import datetime
        
        # Load config for specified mode (from client) or fall back to settings
        from ..config import load_jarvis_config, get_jarvis_setting
        if not mode:
            settings = get_settings_manager()
            mode = settings.mode
        
        # Force reload config for the correct mode
        load_jarvis_config(mode)
        
        provider = get_jarvis_setting('TTS_PROVIDER', 'elevenlabs')
        print(f"[TTS] Mode: {mode}, Provider: {provider}", flush=True)
        
        # Qwen3-TTS (OpenAI-compatible voice cloning on local network)
        if provider == 'qwen3-tts':
            tts_url = get_jarvis_setting('QWEN3_TTS_URL', '') or get_jarvis_setting('TTS_URL', '')
            if not tts_url:
                return jsonify({'ok': False, 'error': 'QWEN3_TTS_URL not configured'}), 500
            
            tts_voice = get_jarvis_setting('QWEN3_TTS_VOICE', '') or get_jarvis_setting('TTS_VOICE', 'Jarvis')
            tts_format = get_jarvis_setting('QWEN3_TTS_FORMAT', 'mp3')
            tts_speed = get_jarvis_setting('QWEN3_TTS_SPEED', '') or get_jarvis_setting('TTS_SPEED', '1.0')
            
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
            return response.content, 200, {
                'Content-Type': content_type,
                'Content-Disposition': 'inline'
            }
        
        # Kokoro TTS (local)
        if provider == 'kokoro':
            tts_url = get_jarvis_setting('KOKORO_TTS_URL', '') or get_jarvis_setting('TTS_URL', '')
            if not tts_url:
                return jsonify({'ok': False, 'error': 'TTS_URL not configured for local mode'}), 500
            
            tts_voice = get_jarvis_setting('KOKORO_TTS_VOICE', '') or get_jarvis_setting('TTS_VOICE', 'af_nicole')
            tts_speed = get_jarvis_setting('KOKORO_TTS_SPEED', '') or get_jarvis_setting('TTS_SPEED', '1.0')
            
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
            return response.content, 200, {
                'Content-Type': 'audio/mpeg',
                'Content-Disposition': 'inline'
            }
        
        # Cloud mode: ElevenLabs or OpenAI
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
    
    # v3 has 5k char limit, v2 has 10k - truncate if needed
    char_limit = 5000 if model_id == 'eleven_v3' else 10000
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
    allowed_extensions = {'.mp3', '.wav', '.ogg', '.m4a'}
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
    allowed_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv'}
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        abort(404)
    
    if not VIDEOS_PATH.exists():
        abort(404)
    
    return send_from_directory(str(VIDEOS_PATH), filename)


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
    
    space_path = STASH_PATH / space_id
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
    
    return send_from_directory(str(space_path), file_path.name, mimetype=mimetype)


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
        space_path = STASH_PATH / space_id
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

@api_bp.route('/upload-image', methods=['POST'])
def upload_image():
    """
    Upload an image for vision analysis.
    Resizes large images and stores for conversation history.
    Returns URL and base64 for immediate use.
    """
    import base64
    from datetime import datetime
    from PIL import Image, ImageOps
    import io
    
    if 'image' not in request.files:
        return jsonify({'ok': False, 'error': 'No image file provided'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'ok': False, 'error': 'No file selected'}), 400
    
    # Check file type
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed_extensions:
        return jsonify({'ok': False, 'error': f'Invalid file type. Allowed: {", ".join(allowed_extensions)}'}), 400
    
    try:
        # Read and process image
        img = Image.open(file.stream)
        # Apply EXIF orientation (iPhone photos often have Orientation tag; PIL doesn't auto-apply)
        img = ImageOps.exif_transpose(img)
        
        # Convert to RGB if necessary (for JPEG output)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # Smart resize - max 1024px on longest side (reduces base64 size for socket)
        max_size = 1024
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            print(f"[Upload] Resized image from {file.filename} to {new_size}")
        
        # Save to uploads directory
        UPLOADS_PATH.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"upload_{timestamp}.jpg"
        filepath = UPLOADS_PATH / filename
        
        # Save with quality optimization
        img.save(filepath, 'JPEG', quality=85, optimize=True)
        
        # Generate base64 for immediate use
        buffer = io.BytesIO()
        img.save(buffer, 'JPEG', quality=85)
        base64_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        file_size_kb = filepath.stat().st_size / 1024
        print(f"[Upload] Saved {filename} ({img.size[0]}x{img.size[1]}, {file_size_kb:.1f}KB)")
        
        return jsonify({
            'ok': True,
            'filename': filename,
            'url': f'/api/uploads/{filename}',
            'base64': base64_data,
            'width': img.size[0],
            'height': img.size[1],
            'size_kb': round(file_size_kb, 1)
        })
        
    except Exception as e:
        print(f"[Upload] Error processing image: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@api_bp.route('/uploads/<filename>', methods=['GET'])
def serve_upload(filename):
    """Serve uploaded images"""
    if '..' in filename or '/' in filename:
        abort(404)
    
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        abort(404)
    
    if not UPLOADS_PATH.exists():
        abort(404)
    
    return send_from_directory(str(UPLOADS_PATH), filename)


# =============================================================================
# WORKFLOWS API - Explicit multi-tool pipelines (triggered via /workflow_name)
# =============================================================================

@api_bp.route('/workflows', methods=['GET'])
def list_workflows():
    """List all available workflows (auto-discovered from data/workflows/*.json)"""
    import json
    
    workflows = {}
    
    if WORKFLOWS_PATH.exists():
        for wf_file in WORKFLOWS_PATH.glob('*.json'):
            try:
                with open(wf_file, 'r') as f:
                    wf_data = json.load(f)
                    
                    # Skip disabled workflows
                    if not wf_data.get('enabled', True):
                        continue
                    
                    wf_id = wf_data.get('id') or wf_file.stem
                    triggers = wf_data.get('triggers', {})
                    explicit_cmds = triggers.get('explicit', [])
                    steps = wf_data.get('steps', [])
                    
                    # Build step summary for tooltip
                    step_summary = []
                    for s in steps:
                        tool = s.get('tool', 'unknown')
                        action = s.get('action', '')
                        desc = s.get('description', '')
                        step_text = f"{tool}.{action}" if action else tool
                        if desc:
                            step_text += f" - {desc}"
                        step_summary.append({
                            'step': s.get('step', len(step_summary) + 1),
                            'tool': tool,
                            'action': action,
                            'description': desc,
                            'display': step_text
                        })
                    
                    workflows[wf_id] = {
                        'id': wf_id,
                        'name': wf_data.get('name', wf_id),
                        'description': wf_data.get('description', ''),
                        'version': wf_data.get('version', '1.0'),
                        'triggers': explicit_cmds,  # e.g., ["/research", "/deep-research"]
                        'step_count': len(steps),
                        'tools_used': list(dict.fromkeys(s.get('tool', '') for s in steps)),  # Preserve order
                        'steps': step_summary,  # For hover tooltip
                        'icon': '🔄'  # Default workflow icon
                    }
            except Exception as e:
                print(f"[Workflows] Error loading {wf_file}: {e}")
    
    return jsonify({
        'ok': True,
        'count': len(workflows),
        'workflows': workflows
    })


@api_bp.route('/workflows/<workflow_id>', methods=['GET'])
def get_workflow(workflow_id):
    """Get a specific workflow by ID"""
    import json
    
    wf_file = WORKFLOWS_PATH / f"{workflow_id}.json"
    
    if wf_file.exists():
        try:
            with open(wf_file, 'r') as f:
                wf_data = json.load(f)
                return jsonify({
                    'ok': True,
                    'workflow': wf_data
                })
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500
    
    return jsonify({'ok': False, 'error': f'Workflow not found: {workflow_id}'}), 404


@api_bp.route('/prompts', methods=['GET'])
def list_prompts():
    """List all available @prompts (auto-discovered from data/prompts/*.md)"""
    prompts = {}
    
    if PROMPTS_PATH.exists():
        for prompt_file in PROMPTS_PATH.glob('*.md'):
            try:
                with open(prompt_file, 'r') as f:
                    content = f.read()
                    name = prompt_file.stem
                    
                    # Extract description from first line (# Title)
                    lines = content.strip().split('\n')
                    description = ''
                    if lines and lines[0].startswith('#'):
                        description = lines[0].lstrip('#').strip()
                    
                    # Extract key points for tooltip (bullets or first meaningful lines)
                    key_points = []
                    for line in lines[1:]:  # Skip title
                        line = line.strip()
                        if not line:
                            continue
                        # Look for bullet points or numbered items
                        if line.startswith(('-', '*', '•')) or (len(line) > 2 and line[0].isdigit() and line[1] in '.):'):
                            point = line.lstrip('-*•0123456789.) ').strip()
                            if point and len(point) > 3:
                                key_points.append(point[:80])  # Truncate long points
                        # Also capture section headers
                        elif line.startswith('##'):
                            key_points.append(line.lstrip('#').strip())
                        # Stop after finding enough points
                        if len(key_points) >= 5:
                            break
                    
                    # If no bullets found, take first few non-empty lines
                    if not key_points:
                        for line in lines[1:6]:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                key_points.append(line[:80])
                    
                    prompts[name] = {
                        'name': name,
                        'description': description,
                        'content': content,
                        'key_points': key_points[:5]  # Max 5 points
                    }
            except Exception as e:
                print(f"[Prompts] Error loading {prompt_file}: {e}")
    
    return jsonify({
        'ok': True,
        'count': len(prompts),
        'prompts': prompts
    })


@api_bp.route('/prompts/<name>', methods=['GET'])
def get_prompt(name):
    """Get a specific prompt by name"""
    prompt_file = PROMPTS_PATH / f"{name}.md"
    
    if prompt_file.exists():
        try:
            with open(prompt_file, 'r') as f:
                content = f.read()
                lines = content.strip().split('\n')
                description = ''
                if lines and lines[0].startswith('#'):
                    description = lines[0].lstrip('#').strip()
                
                return jsonify({
                    'ok': True,
                    'prompt': {
                        'name': name,
                        'description': description,
                        'content': content
                    }
                })
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500
    
    return jsonify({'ok': False, 'error': f'Prompt not found: {name}'}), 404


@api_bp.route('/enhance-prompt', methods=['POST'])
def enhance_prompt():
    """
    ✨ AI-powered prompt enhancement
    Takes a rough user query and transforms it into an optimal prompt
    using full knowledge of Jarvis capabilities, tools, and best practices.
    """
    
    data = request.get_json() or {}
    user_input = data.get('input', '').strip()
    
    if not user_input:
        return jsonify({'ok': False, 'error': 'No input provided'}), 400
    
    # Get current mode
    current_mode = get_web_setting('defaults.mode', 'cloud')
    
    try:
        # Load LLM provider
        sys.path.insert(0, str(JARVIS_ROOT / 'lib'))
        from config_loader import load_config, get_config_value
        from llm_provider import create_provider
        
        load_config(mode=current_mode)
        
        # Get tool summaries for context (only enabled, non-blocked tools)
        tool_service = get_tool_service()
        tools = tool_service.get_tools_summary()
        # Filter to only available tools
        available_tools = [
            t for t in tools 
            if t.get('enabled', True) and not t.get('blocked', False)
        ]
        tool_descriptions = "\n".join([
            f"- {t['name']}: {t.get('description', 'No description')[:100]}"
            for t in available_tools[:30]  # Limit to top 30 tools
        ])
        
        # Build the enhancement system prompt
        system_prompt = f"""You are a prompt enhancement assistant for Jarvis, an AI voice assistant.

Your job is to take a rough, casual user input and transform it into an optimal, detailed prompt that will get the best results from Jarvis.

## Jarvis Capabilities
- **Native Web Search**: Jarvis has built-in web search that provides comprehensive, real-time information. This is BETTER than external search tools.
- **Tools Available**:
{tool_descriptions}

## Enhancement Guidelines
1. **Be Specific**: Add details about what information is wanted
2. **Request Format**: Suggest how results should be structured (bullet points, sections, comparisons)
3. **Time Context**: Add "current", "latest", "December 2025" when asking for news/data
4. **Scope**: Define scope (e.g., "past 24 hours", "top 5", "major sources")
5. **DON'T add commands** like /canvas or @prompts - just enhance the natural language
6. **Keep it conversational** - this is for a voice assistant
7. **If user wants to save/view results**, mention Canvas but naturally

## Examples
Input: "bitcoin news"
Enhanced: "What's the latest Bitcoin news and price action? Include the current price, significant price movements in the last 24 hours, and the top 3-5 major news headlines affecting the market. Summarize key analyst predictions if available."

Input: "weather"
Enhanced: "What's the current weather and forecast for my location? Include today's conditions, temperature range, and the outlook for the next few days."

Input: "email john about meeting"
Enhanced: "Send an email to John about scheduling a meeting. Keep it professional and brief, asking about his availability this week."

Now enhance the following input. Return ONLY the enhanced prompt text, nothing else."""

        # Create provider based on mode
        provider_type = get_config_value('LLM_PROVIDER', 'xai')
        
        if provider_type == 'ollama':
            provider = create_provider(
                'ollama',
                model=get_config_value('OLLAMA_MODEL', 'qwen3:14b'),
                base_url=get_config_value('OLLAMA_BASE_URL', 'http://localhost:11434')
            )
        elif provider_type == 'xai':
            provider = create_provider(
                'xai',
                api_key=get_config_value('XAI_API_KEY'),
                model=get_config_value('XAI_MODEL', 'grok-4-1-fast-non-reasoning-latest')
            )
        elif provider_type == 'anthropic':
            provider = create_provider(
                'anthropic',
                api_key=get_config_value('ANTHROPIC_API_KEY'),
                model=get_config_value('ANTHROPIC_MODEL', 'claude-sonnet-4-5-20250929')
            )
        else:
            provider = create_provider(
                'openai',
                api_key=get_config_value('OPENAI_API_KEY'),
                model=get_config_value('OPENAI_MODEL', 'gpt-4o')
            )
        
        # Call LLM to enhance
        # chat() signature: chat(message: str, system_prompt: str = None, max_tokens: int = None) -> str
        enhanced = provider.chat(
            message=user_input,
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
        
        return jsonify({
            'ok': True,
            'original': user_input,
            'enhanced': enhanced,
            'mode': current_mode
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'ok': False,
            'error': str(e),
            'original': user_input
        }), 500
