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
            
            # Use startup mode as default for new sessions
            from ..app import get_startup_mode
            default_mode = get_startup_mode()
            
            self.sessions[session_id] = {
                'mode': default_mode,
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
                'mode': default_mode,
                'tools_count': tool_service.get_tool_count()
            })
            print(f"[WS] Client connected: {session_id} (default mode: {default_mode})")
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            session_id = request.sid
            if session_id in self.sessions:
                del self.sessions[session_id]
            leave_room(session_id)
            print(f"[WS] Client disconnected: {session_id}")
        
        @self.socketio.on('chat:send')
        def handle_chat_send(data):
            """Handle incoming chat message (with optional image)"""
            session_id = request.sid
            message = data.get('message', '').strip()
            mode = data.get('mode', self.sessions.get(session_id, {}).get('mode', 'cloud'))
            conversation_id = data.get('conversation_id')
            
            # Image data for vision requests
            image_data = data.get('image')  # {base64, url, filename}
            
            if not message and not image_data:
                emit('chat:error', {
                    'error': 'Empty message',
                    'conversation_id': conversation_id
                })
                return
            
            # Default message for image-only
            if not message and image_data:
                message = "What's in this image?"
            
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
            
            # Save user message (include image URL if present)
            user_msg_data = {'image_url': image_data.get('url')} if image_data else None
            store.add_message(conversation_id, 'user', message, data=user_msg_data)
            
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
                conversation_id,
                image_data
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
                from ..config import reload_web_config, load_jarvis_config
                
                settings = get_settings_manager()
                settings.set_mode(mode)
                reload_web_config()
                
                # Force reload Jarvis config for new mode
                load_jarvis_config(mode)
                
                # Reset singletons that cache mode-specific data
                try:
                    from intelligence import reset_intelligence_layer
                    reset_intelligence_layer()
                    print(f"[MODE] Reset intelligence layer for {mode} mode")
                except Exception as e:
                    print(f"[MODE] Warning: Could not reset intelligence: {e}")
                
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
        
        # =====================================================================
        # Proactive Notification Handlers
        # =====================================================================
        
        @self.socketio.on('proactive:subscribe')
        def handle_proactive_subscribe(data=None):
            """Client wants to receive proactive notifications"""
            session_id = request.sid
            print(f"[Proactive] Client {session_id[:8]} subscribed to notifications")
            
            # Get current counts immediately
            from ..services.proactive_service import get_proactive_service
            service = get_proactive_service()
            counts = service.get_pending_counts()
            
            emit('proactive:counts', counts)
        
        @self.socketio.on('proactive:check')
        def handle_proactive_check(data=None):
            """Manual check for new notifications"""
            from ..services.proactive_service import get_proactive_service
            service = get_proactive_service()
            
            # Poll and get results
            result = service.poll_and_notify()
            
            # Send counts to this client
            emit('proactive:counts', result['counts'])
            
            # Send any new items
            for alert in result['new_alerts']:
                emit('proactive:alert', {
                    'type': 'alert',
                    'alert': alert,
                    'timestamp': time.time()
                })
            
            for reminder in result['new_reminders']:
                emit('proactive:reminder', {
                    'type': 'reminder',
                    'reminder': reminder,
                    'timestamp': time.time()
                })
        
        @self.socketio.on('proactive:ack_alert')
        def handle_ack_alert(data):
            """Acknowledge an alert"""
            alert_id = data.get('alert_id')
            if not alert_id:
                emit('proactive:error', {'error': 'Missing alert_id'})
                return
            
            from ..services.proactive_service import get_proactive_service
            service = get_proactive_service()
            
            success = service.acknowledge_alert(alert_id)
            if success:
                emit('proactive:ack_success', {
                    'type': 'alert',
                    'id': alert_id
                })
                # Broadcast updated counts
                self.socketio.emit('proactive:counts', service.get_pending_counts())
            else:
                emit('proactive:error', {'error': f'Failed to acknowledge alert {alert_id}'})
        
        @self.socketio.on('proactive:ack_reminder')
        def handle_ack_reminder(data):
            """Acknowledge a reminder"""
            reminder_id = data.get('reminder_id')
            if not reminder_id:
                emit('proactive:error', {'error': 'Missing reminder_id'})
                return
            
            from ..services.proactive_service import get_proactive_service
            service = get_proactive_service()
            
            success = service.acknowledge_reminder(reminder_id)
            if success:
                emit('proactive:ack_success', {
                    'type': 'reminder',
                    'id': reminder_id
                })
                # Broadcast updated counts
                self.socketio.emit('proactive:counts', service.get_pending_counts())
            else:
                emit('proactive:error', {'error': f'Failed to acknowledge reminder {reminder_id}'})
    
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
                         message_id: str, conversation_id: str, image_data: dict = None):
        """Process a chat message through the orchestrator (with optional vision)"""
        start_time = time.time()
        print(f"[CHAT] Processing message: {message[:50]}... (mode={mode}, session={session_id[:8]}, has_image={image_data is not None})")
        
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
            
            # Handle vision if image is provided
            if image_data and image_data.get('base64'):
                print(f"[CHAT] Processing image with vision model...")
                self.socketio.emit('chat:status', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'status': 'Analyzing image...',
                    'timestamp': time.time()
                }, room=session_id)
                
                vision_result = self._process_vision(
                    image_data['base64'], 
                    message, 
                    mode
                )
                
                if vision_result:
                    # Check if this is a simple image question (no action requested)
                    simple_question = self._is_simple_image_question(message)
                    
                    if simple_question:
                        # For simple image questions, return vision result directly
                        # without going through orchestrator tool loop
                        print(f"[CHAT] Simple image question - returning vision result directly")
                        
                        # Create a short spoken response from the vision analysis
                        short_response = self._summarize_vision_for_speech(vision_result, message, mode)
                        
                        # Save to conversation
                        from ..services.conversation_store import get_conversation_store
                        store = get_conversation_store()
                        store.add_message(
                            conversation_id, 'assistant', short_response,
                            tools_used=[], 
                            data={'vision_analysis': vision_result}
                        )
                        
                        # Send response
                        self.socketio.emit('chat:response', {
                            'text': short_response,
                            'message_id': message_id,
                            'conversation_id': conversation_id,
                            'tools_used': [],
                            'data': {'vision_analysis': vision_result},
                            'duration_ms': int((time.time() - start_time) * 1000)
                        }, room=session_id)
                        
                        # Generate TTS
                        self._generate_tts(short_response, mode, session_id)
                        return
                    else:
                        # Complex request - pass to orchestrator with vision context
                        message = f"[Image Analysis: {vision_result}]\n\nUser's request: {message}\n\nNote: The image has already been analyzed above. Use this analysis to complete the user's request."
                        print(f"[CHAT] Complex image request - passing to orchestrator with vision context")
            
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
                        audio_url = self._generate_tts(speech_text, mode=mode)
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
    
    def _generate_tts(self, text: str, mode: str = None) -> str:
        """Generate TTS audio and return URL - mode-aware"""
        try:
            import requests
            from datetime import datetime
            from ..config import load_jarvis_config, get_jarvis_setting
            from ..services.settings_manager import get_settings_manager
            
            settings = get_settings_manager()
            current_mode = mode or settings.mode
            
            # Force reload config for correct mode
            load_jarvis_config(current_mode)
            
            # Get provider FIRST - this determines which TTS to use
            provider = get_jarvis_setting('TTS_PROVIDER', 'elevenlabs' if current_mode == 'cloud' else 'kokoro')
            print(f"[CHAT TTS] Mode: {current_mode}, Provider: {provider}")
            
            # Create output directory
            project_root = Path(__file__).parent.parent.parent.parent
            tts_dir = project_root / 'audio' / current_mode / 'tts'
            tts_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Route based on provider (not TTS_URL existence)
            if provider == 'kokoro':
                # Local TTS via TTS_URL
                tts_url = get_jarvis_setting('TTS_URL', '')
                if not tts_url:
                    print("[CHAT TTS] Kokoro provider but TTS_URL not set!")
                    return None
                audio_path = self._local_tts(text, tts_dir, timestamp, tts_url)
            elif provider == 'elevenlabs':
                audio_path = self._elevenlabs_tts(text, tts_dir, timestamp)
            else:
                # Default to OpenAI
                audio_path = self._openai_tts(text, tts_dir, timestamp)
            
            if audio_path and audio_path.exists():
                return f'/api/audio/{audio_path.name}'
            
            return None
        except Exception as e:
            print(f"[CHAT] TTS error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _local_tts(self, text: str, output_dir: Path, timestamp: str, tts_url: str) -> Path:
        """Generate TTS using local/Kokoro API (OpenAI-compatible)"""
        import requests
        from ..config import get_jarvis_setting
        
        voice = get_jarvis_setting('TTS_VOICE', 'af_nicole')
        speed = float(get_jarvis_setting('TTS_SPEED', '1.0'))
        
        payload = {
            "model": "kokoro",
            "input": text,
            "voice": voice,
            "speed": speed,
            "response_format": "mp3"
        }
        
        try:
            response = requests.post(tts_url, json=payload, timeout=30)
            if response.status_code == 200:
                output_path = output_dir / f"tts_{timestamp}.mp3"
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return output_path
            else:
                print(f"[CHAT] Local TTS error: {response.status_code} - {response.text[:100]}")
                return None
        except Exception as e:
            print(f"[CHAT] Local TTS failed: {e}")
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

    def _is_simple_image_question(self, message: str) -> bool:
        """
        Check if the user's message is a simple image identification question
        that doesn't require tools (just vision analysis + response).
        """
        message_lower = message.lower().strip()
        
        # Simple question patterns - just asking about the image
        simple_patterns = [
            'what is this',
            'what\'s this',
            'what am i looking at',
            'what do you see',
            'describe this',
            'describe the image',
            'what is in this',
            'what\'s in this',
            'tell me about this',
            'analyze this',
            'what does this show',
            'identify this',
            'what kind of',
            'what type of',
            'who is this',
            'where is this',
            'when was this',
            'explain this',
            'what happened here',
        ]
        
        # Action keywords that require orchestrator
        action_keywords = [
            'create', 'make', 'generate', 'draw', 'save', 'store', 
            'remember', 'canvas', 'email', 'send', 'search for',
            'find similar', 'look up', 'research', 'schedule',
            'remind', 'add to', 'put in', 'write', 'similar',
            'like this', 'based on this', 'using this'
        ]
        
        # If any action keyword is present, it's not simple
        for keyword in action_keywords:
            if keyword in message_lower:
                return False
        
        # If it matches a simple pattern, it's simple
        for pattern in simple_patterns:
            if pattern in message_lower:
                return True
        
        # Short messages about images are usually simple
        if len(message.split()) <= 8:
            return True
        
        return False

    def _summarize_vision_for_speech(self, vision_result: str, question: str, mode: str) -> str:
        """
        Create a short, spoken-friendly response from the vision analysis.
        Uses LLM to summarize if needed.
        """
        from ..config import get_jarvis_setting, load_jarvis_config
        import requests
        
        load_jarvis_config(mode)
        
        # If vision result is already short, use it directly
        if len(vision_result.split()) <= 50:
            return vision_result
        
        # Use LLM to create a short spoken summary
        try:
            if mode == 'local':
                base_url = get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434')
                model = get_jarvis_setting('OLLAMA_MODEL', 'mistral')
                
                response = requests.post(
                    f"{base_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": f"""Summarize this image description in 1-2 sentences for voice output (max 30 words).
Be direct and conversational.

Image analysis: {vision_result}
User asked: {question}

Short spoken response:""",
                        "stream": False
                    },
                    timeout=30
                )
                
                if response.status_code == 200:
                    return response.json().get('response', vision_result[:200])
            else:
                # Cloud mode - use configured LLM
                provider = get_jarvis_setting('LLM_PROVIDER', 'xai')
                
                if provider == 'xai':
                    api_key = get_jarvis_setting('XAI_API_KEY', '')
                    model = get_jarvis_setting('XAI_MODEL', 'grok-3-mini-fast-latest')
                    url = "https://api.x.ai/v1/chat/completions"
                elif provider == 'anthropic':
                    api_key = get_jarvis_setting('ANTHROPIC_API_KEY', '')
                    model = get_jarvis_setting('ANTHROPIC_MODEL', 'claude-sonnet-4-20250514')
                    url = "https://api.anthropic.com/v1/messages"
                else:
                    api_key = get_jarvis_setting('OPENAI_API_KEY', '')
                    model = get_jarvis_setting('OPENAI_MODEL', 'gpt-4o-mini')
                    url = "https://api.openai.com/v1/chat/completions"
                
                if not api_key:
                    return vision_result[:200]
                
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                
                if provider == 'anthropic':
                    headers["x-api-key"] = api_key
                    headers["anthropic-version"] = "2023-06-01"
                    del headers["Authorization"]
                    
                    payload = {
                        "model": model,
                        "max_tokens": 100,
                        "messages": [{
                            "role": "user",
                            "content": f"Summarize this image description in 1-2 sentences for voice output (max 30 words). Be direct.\n\nImage: {vision_result}\nQuestion: {question}"
                        }]
                    }
                else:
                    payload = {
                        "model": model,
                        "messages": [{
                            "role": "user",
                            "content": f"Summarize this image description in 1-2 sentences for voice output (max 30 words). Be direct.\n\nImage: {vision_result}\nQuestion: {question}"
                        }],
                        "max_tokens": 100
                    }
                
                response = requests.post(url, json=payload, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    result = response.json()
                    if provider == 'anthropic':
                        return result.get('content', [{}])[0].get('text', vision_result[:200])
                    else:
                        return result.get('choices', [{}])[0].get('message', {}).get('content', vision_result[:200])
        except Exception as e:
            print(f"[CHAT] Error summarizing vision: {e}")
        
        # Fallback - truncate
        return vision_result[:200] + "..." if len(vision_result) > 200 else vision_result


    def _process_vision(self, image_base64: str, prompt: str, mode: str) -> str:
        """
        Process an image with a vision model.
        Returns the vision model's description/analysis.
        """
        import requests
        from ..config import get_jarvis_setting, load_jarvis_config
        
        # Load mode-specific config
        load_jarvis_config(mode)
        
        try:
            if mode == 'local':
                return self._vision_ollama(image_base64, prompt)
            else:
                return self._vision_cloud(image_base64, prompt, mode)
        except Exception as e:
            print(f"[VISION] Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _vision_ollama(self, image_base64: str, prompt: str) -> str:
        """Use Ollama vision model (llava, llama3.2-vision, etc.)"""
        import requests
        from ..config import get_jarvis_setting
        
        base_url = get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434')
        vision_model = get_jarvis_setting('OLLAMA_VISION_MODEL', 'llava:latest')
        
        print(f"[VISION] Using Ollama: {vision_model} at {base_url}")
        
        payload = {
            "model": vision_model,
            "prompt": prompt,
            "images": [image_base64],
            "stream": False
        }
        
        response = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=120  # Vision can be slow
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get('response', '')
        else:
            print(f"[VISION] Ollama error: {response.status_code} - {response.text[:200]}")
            return None
    
    def _vision_cloud(self, image_base64: str, prompt: str, mode: str) -> str:
        """Use cloud provider's vision model (Anthropic, xAI, OpenAI)"""
        import requests
        from ..config import get_jarvis_setting
        
        provider = get_jarvis_setting('LLM_PROVIDER', 'xai')
        vision_model = get_jarvis_setting('VISION_MODEL', '')  # Empty = use main model
        
        print(f"[VISION] Using cloud provider: {provider}")
        
        if provider == 'anthropic':
            return self._vision_anthropic(image_base64, prompt, vision_model)
        elif provider == 'xai':
            return self._vision_xai(image_base64, prompt, vision_model)
        elif provider == 'openai':
            return self._vision_openai(image_base64, prompt, vision_model)
        else:
            print(f"[VISION] Unknown provider: {provider}, trying xAI format")
            return self._vision_xai(image_base64, prompt, vision_model)
    
    def _vision_anthropic(self, image_base64: str, prompt: str, model: str = None) -> str:
        """Use Anthropic Claude for vision"""
        import requests
        from ..config import get_jarvis_setting
        
        api_key = get_jarvis_setting('ANTHROPIC_API_KEY', '')
        if not api_key:
            print("[VISION] ANTHROPIC_API_KEY not configured")
            return None
        
        model = model or get_jarvis_setting('ANTHROPIC_MODEL', 'claude-sonnet-4-20250514')
        print(f"[VISION] Anthropic model: {model}")
        
        payload = {
            "model": model,
            "max_tokens": 1024,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        }
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result.get('content', [])
            if content and content[0].get('type') == 'text':
                return content[0].get('text', '')
        else:
            print(f"[VISION] Anthropic error: {response.status_code} - {response.text[:200]}")
        return None
    
    def _vision_xai(self, image_base64: str, prompt: str, model: str = None) -> str:
        """Use xAI Grok for vision (grok-4 or newer)"""
        import requests
        from ..config import get_jarvis_setting
        
        api_key = get_jarvis_setting('XAI_API_KEY', '')
        if not api_key:
            print("[VISION] XAI_API_KEY not configured")
            return None
        
        # Use VISION_MODEL if set, otherwise fall back to XAI_MODEL or grok-4
        model = model or get_jarvis_setting('VISION_MODEL') or get_jarvis_setting('XAI_MODEL', 'grok-4')
        print(f"[VISION] xAI model: {model}")
        
        # xAI uses OpenAI-compatible format with detail parameter
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}",
                            "detail": "high"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }],
            "max_tokens": 2048
        }
        
        response = requests.post(
            "https://api.x.ai/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            timeout=120  # Vision can be slower
        )
        
        if response.status_code == 200:
            result = response.json()
            choices = result.get('choices', [])
            if choices:
                return choices[0].get('message', {}).get('content', '')
        else:
            print(f"[VISION] xAI error: {response.status_code} - {response.text[:500]}")
        return None
    
    def _vision_openai(self, image_base64: str, prompt: str, model: str = None) -> str:
        """Use OpenAI GPT-4V for vision"""
        import requests
        from ..config import get_jarvis_setting
        
        api_key = get_jarvis_setting('OPENAI_API_KEY', '')
        if not api_key:
            print("[VISION] OPENAI_API_KEY not configured")
            return None
        
        model = model or 'gpt-4o'
        print(f"[VISION] OpenAI model: {model}")
        
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }],
            "max_tokens": 1024
        }
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            choices = result.get('choices', [])
            if choices:
                return choices[0].get('message', {}).get('content', '')
        else:
            print(f"[VISION] OpenAI error: {response.status_code} - {response.text[:200]}")
        return None
