"""
WebSocket handlers for chat functionality
Real-time message handling and tool execution streaming
"""
import sys
import uuid
import time
import traceback
from pathlib import Path
from flask_socketio import emit, join_room, leave_room
from flask import request

# Add Jarvis libs to path
JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))
sys.path.insert(0, str(JARVIS_ROOT / 'orchestrator'))


class ChatHandler:
    """Handles WebSocket chat events"""
    
    def __init__(self, socketio):
        self.socketio = socketio
        self.sessions = {}  # session_id -> {mode, conversation_id, ...}
        self._register_handlers()
    
    def _register_handlers(self):
        """Register all socket event handlers"""
        
        @self.socketio.on('connect')
        def handle_connect():
            session_id = request.sid
            self.sessions[session_id] = {
                'mode': 'cloud',
                'conversation_id': None,
                'connected_at': time.time()
            }
            
            # Join personal room
            join_room(session_id)
            
            # Send connection confirmation
            from ..services.tool_discovery import get_tool_service
            tool_service = get_tool_service()
            
            emit('connected', {
                'session_id': session_id,
                'mode': 'cloud',
                'tools_count': tool_service.get_tool_count()
            })
            print(f"[WS] Client connected: {session_id}")
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            session_id = request.sid
            if session_id in self.sessions:
                del self.sessions[session_id]
            leave_room(session_id)
            print(f"[WS] Client disconnected: {session_id}")
        
        @self.socketio.on('chat:send')
        def handle_chat_send(data):
            """Handle incoming chat message"""
            session_id = request.sid
            message = data.get('message', '').strip()
            mode = data.get('mode', self.sessions.get(session_id, {}).get('mode', 'cloud'))
            conversation_id = data.get('conversation_id')
            
            if not message:
                emit('chat:error', {
                    'error': 'Empty message',
                    'conversation_id': conversation_id
                })
                return
            
            # Create or get conversation
            from ..services.conversation_store import get_conversation_store
            store = get_conversation_store()
            
            if not conversation_id:
                # Create new conversation
                conv = store.create_conversation()
                conversation_id = conv['id']
                # Notify client of new conversation
                emit('conversation:created', {
                    'conversation_id': conversation_id,
                    'title': conv['title']
                })
            
            # Save user message
            store.add_message(conversation_id, 'user', message)
            
            # Update session
            if session_id in self.sessions:
                self.sessions[session_id]['mode'] = mode
                self.sessions[session_id]['conversation_id'] = conversation_id
            
            # Generate message ID
            message_id = str(uuid.uuid4())
            
            # Emit thinking state
            emit('chat:thinking', {
                'message_id': message_id,
                'conversation_id': conversation_id
            })
            
            # Process in background to not block
            self.socketio.start_background_task(
                self._process_message,
                session_id,
                message,
                mode,
                message_id,
                conversation_id
            )
        
        @self.socketio.on('conversation:load')
        def handle_load_conversation(data):
            """Load a conversation history"""
            session_id = request.sid
            conv_id = data.get('conversation_id')
            
            if not conv_id:
                emit('chat:error', {'error': 'No conversation_id provided'})
                return
            
            from ..services.conversation_store import get_conversation_store
            store = get_conversation_store()
            
            conversation = store.get_conversation(conv_id)
            if conversation:
                # Update session
                if session_id in self.sessions:
                    self.sessions[session_id]['conversation_id'] = conv_id
                
                emit('conversation:loaded', {
                    'conversation': conversation
                })
            else:
                emit('chat:error', {'error': 'Conversation not found'})
        
        @self.socketio.on('chat:cancel')
        def handle_chat_cancel(data):
            """Cancel current processing (placeholder)"""
            session_id = request.sid
            emit('chat:cancelled', {
                'conversation_id': data.get('conversation_id')
            })
        
        @self.socketio.on('mode:set')
        def handle_mode_set(data):
            """Set the mode for this session and reload settings"""
            session_id = request.sid
            mode = data.get('mode', 'cloud')
            
            if mode in ['cloud', 'local']:
                if session_id in self.sessions:
                    self.sessions[session_id]['mode'] = mode
                
                # Update settings manager and reload config for new mode
                from ..services.settings_manager import get_settings_manager
                from ..config import reload_web_config
                settings = get_settings_manager()
                settings.set_mode(mode)
                reload_web_config()
                
                emit('mode:changed', {'mode': mode})
        
        @self.socketio.on('tools:refresh')
        def handle_tools_refresh():
            """Refresh tools list"""
            from ..services.tool_discovery import get_tool_service
            tool_service = get_tool_service()
            tool_service.refresh()
            
            emit('tools:updated', {
                'count': tool_service.get_tool_count(),
                'tools': tool_service.get_tools_summary()
            })
    
    def _get_conversation_context(self, conversation_id: str) -> list:
        """Get recent conversation history for LLM context"""
        try:
            from ..services.conversation_store import get_conversation_store
            from ..config import get_web_setting
            store = get_conversation_store()
            
            conversation = store.get_conversation(conversation_id)
            if not conversation:
                return []
            
            messages = conversation.get('messages', [])
            
            # Get configurable history limit (default 20)
            history_limit = get_web_setting('conversation.history_limit', 20)
            
            # Format for orchestrator: [{role: str, content: str}, ...]
            history = []
            for msg in messages[-history_limit:]:
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                if content:
                    history.append({'role': role, 'content': content})
            
            return history
        except Exception as e:
            print(f"[CHAT] Error getting conversation context: {e}")
            return []
    
    def _process_message(self, session_id: str, message: str, mode: str,
                         message_id: str, conversation_id: str):
        """Process a chat message through the orchestrator"""
        start_time = time.time()
        print(f"[CHAT] Processing message: {message[:50]}... (mode={mode}, session={session_id[:8]})")
        
        try:
            # Import and create orchestrator
            print("[CHAT] Importing orchestrator...")
            from orchestrator_v2 import Orchestrator
            
            # Get LLM overrides from web config (per-mode)
            from ..config import get_web_setting, load_web_config
            web_config = load_web_config()
            mode_overrides = web_config.get(mode, {})
            provider_override = mode_overrides.get('llm_provider')
            model_override = mode_overrides.get('llm_model')
            
            if provider_override:
                print(f"[CHAT] Using {mode} override: provider={provider_override}, model={model_override}")
            
            # Create orchestrator instance with overrides
            print(f"[CHAT] Creating orchestrator (mode={mode})...")
            orchestrator = Orchestrator(
                mode=mode,
                provider_override=provider_override,
                model_override=model_override
            )
            
            # Set up status callback to emit via WebSocket instead of local TTS
            def status_callback(status_message: str):
                """Send status updates to browser via WebSocket"""
                print(f"[CHAT] Status update: {status_message}")
                self.socketio.emit('chat:status', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'status': status_message,
                    'timestamp': time.time()
                }, room=session_id)
            
            orchestrator.set_status_callback(status_callback)
            
            # Get conversation history for context
            conversation_history = self._get_conversation_context(conversation_id)
            
            # Get blocked tools for web mode
            from ..config import get_web_setting
            blocked_tools = get_web_setting('tools.blocked', [])
            
            # Process the query with conversation context and excluded tools
            print(f"[CHAT] Calling orchestrator.process() with {len(conversation_history)} history messages, {len(blocked_tools)} blocked tools...")
            result = orchestrator.process(
                message, 
                conversation_history=conversation_history,
                excluded_tools=blocked_tools
            )
            print(f"[CHAT] Got result: ok={result.get('ok')}, tools={result.get('tools_used', [])}")
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Extract tools used from result
            tools_used = result.get('tools_used', [])
            
            # Emit tool completion events for each tool
            data = result.get('data', {})
            for tool in tools_used:
                tool_result = data.get(tool, {})
                self.socketio.emit('tool:complete', {
                    'tool': tool,
                    'result': tool_result,
                    'duration_ms': duration_ms // max(len(tools_used), 1),
                    'success': True,
                    'message_id': message_id
                }, room=session_id)
            
            # Save assistant response to conversation
            try:
                from ..services.conversation_store import get_conversation_store
                store = get_conversation_store()
                response_text = result.get('speech', result.get('raw_llm_response', ''))
                store.add_message(
                    conversation_id, 
                    'assistant', 
                    response_text,
                    data=data,
                    tools_used=tools_used
                )
            except Exception as save_err:
                print(f"[CHAT] Failed to save response: {save_err}")
            
            # Generate TTS if enabled
            audio_url = None
            try:
                from ..config import get_web_setting
                if get_web_setting('audio.tts_enabled', False):
                    speech_text = result.get('speech', '')
                    if speech_text:
                        audio_url = self._generate_tts(speech_text)
            except Exception as tts_err:
                print(f"[CHAT] TTS generation failed: {tts_err}")
            
            # Emit final response
            self.socketio.emit('chat:response', {
                'message_id': message_id,
                'conversation_id': conversation_id,
                'text': result.get('raw_llm_response', result.get('speech', '')),
                'speech': result.get('speech', ''),
                'data': data,
                'tools_used': tools_used,
                'ok': result.get('ok', True),
                'duration_ms': duration_ms,
                'usage': result.get('usage', {}),
                'audio_url': audio_url
            }, room=session_id)
            
        except Exception as e:
            error_msg = str(e)
            print(f"[CHAT] ERROR: {error_msg}")
            traceback.print_exc()
            
            self.socketio.emit('chat:error', {
                'message_id': message_id,
                'conversation_id': conversation_id,
                'error': error_msg,
                'traceback': traceback.format_exc()
            }, room=session_id)
    
    def _generate_tts(self, text: str) -> str:
        """Generate TTS audio and return URL"""
        try:
            import requests
            from datetime import datetime
            from ..config import load_jarvis_config, get_jarvis_setting
            from ..services.settings_manager import get_settings_manager
            
            settings = get_settings_manager()
            load_jarvis_config(settings.mode)
            
            provider = get_jarvis_setting('TTS_PROVIDER', 'elevenlabs')
            
            # Create output directory
            project_root = Path(__file__).parent.parent.parent.parent
            tts_dir = project_root / 'audio' / 'cloud' / 'tts'
            tts_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if provider == 'elevenlabs':
                audio_path = self._elevenlabs_tts(text, tts_dir, timestamp)
            else:
                audio_path = self._openai_tts(text, tts_dir, timestamp)
            
            if audio_path and audio_path.exists():
                return f'/api/audio/{audio_path.name}'
            
            return None
        except Exception as e:
            print(f"[CHAT] TTS error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _elevenlabs_tts(self, text: str, output_dir: Path, timestamp: str) -> Path:
        """Generate TTS using ElevenLabs API"""
        import requests
        from ..config import get_jarvis_setting
        
        api_key = get_jarvis_setting('ELEVENLABS_API_KEY', '')
        voice_id = get_jarvis_setting('ELEVENLABS_TTS_VOICE', 'pgCnBQgKPGkIP8fJuita')
        model_id = get_jarvis_setting('ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2')
        
        if not api_key:
            print("[CHAT] ELEVENLABS_API_KEY not configured")
            return None
        
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
            print(f"[CHAT] ElevenLabs error: {response.status_code} - {response.text}")
            return None
        
        output_path = output_dir / f"tts_{timestamp}.mp3"
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        return output_path
    
    def _openai_tts(self, text: str, output_dir: Path, timestamp: str) -> Path:
        """Generate TTS using OpenAI API"""
        import requests
        from ..config import get_jarvis_setting
        
        api_key = get_jarvis_setting('OPENAI_API_KEY', '')
        model = get_jarvis_setting('TTS_MODEL', 'gpt-4o-mini-tts')
        voice = get_jarvis_setting('VOICE', 'onyx')
        
        if not api_key:
            print("[CHAT] OPENAI_API_KEY not configured")
            return None
        
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
            print(f"[CHAT] OpenAI TTS error: {response.status_code} - {response.text}")
            return None
        
        output_path = output_dir / f"tts_{timestamp}.mp3"
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        return output_path

