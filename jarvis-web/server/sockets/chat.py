"""
WebSocket handlers for chat functionality
Real-time message handling and tool execution streaming
"""
import os
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
        self.pending_cancellations = {}  # message_id -> True (to signal orchestrator to stop)
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
        
        @self.socketio.on('cancel')
        def handle_cancel(data):
            """Handle request to cancel current processing"""
            session_id = request.sid
            message_id = data.get('message_id')
            
            if message_id:
                self.pending_cancellations[message_id] = True
                print(f"[WS] Cancel requested for message {message_id}")
                
                # Acknowledge cancellation request
                emit('cancel:ack', {
                    'message_id': message_id,
                    'status': 'stopping'
                }, room=session_id)
        
        @self.socketio.on('chat:send')
        def handle_chat_send(data):
            """Handle incoming chat message (with optional image and command metadata)"""
            session_id = request.sid
            message = data.get('message', '').strip()
            mode = data.get('mode', self.sessions.get(session_id, {}).get('mode', 'cloud'))
            conversation_id = data.get('conversation_id')
            
            # Image data (with optional action routing and settings)
            image_data = data.get('image')  # {base64, url, filename, action?, settings?}
            
            # Feedback request - either from toggle or --feedback flag in message
            request_feedback = data.get('request_feedback', False)
            if '--feedback' in message:
                request_feedback = True
                message = message.replace('--feedback', '').strip()
            
            # Prompt metadata from @prompt system (workflows are handled by orchestrator)
            prompt_meta = {
                'system_instruction': data.get('system_instruction'),
                'prompt_name': data.get('prompt_name')
            }
            
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
            
            # Save user message (include image URL and prompt info if present)
            user_msg_data = {}
            if image_data:
                user_msg_data['image_url'] = image_data.get('url')
            if prompt_meta.get('prompt_name'):
                user_msg_data['prompt'] = prompt_meta['prompt_name']
            store.add_message(conversation_id, 'user', message, data=user_msg_data if user_msg_data else None)
            
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
                image_data,
                prompt_meta,
                request_feedback
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
                
                # Reset tool registry (cleans up MCP containers)
                try:
                    from tool_schema import reset_tool_registry
                    reset_tool_registry()
                    print(f"[MODE] Reset tool registry for {mode} mode")
                except Exception as e:
                    print(f"[MODE] Warning: Could not reset tool registry: {e}")
                
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
        
        # =====================
        # Log Streaming Events
        # =====================
        
        @self.socketio.on('logs:subscribe')
        def handle_logs_subscribe(data):
            """Subscribe to log streaming"""
            session_id = request.sid
            sources = data.get('sources', ['llm', 'tool'])  # Default sources
            
            print(f"[LOGS] Client {session_id[:8]} subscribing to logs: {sources}")
            
            # Join logs room
            join_room('logs_subscribers')
            
            # Start log streamer if not running
            self._ensure_log_streamer_running()
            
            emit('logs:subscribed', {
                'sources': sources,
                'available': list(self._get_log_sources().keys())
            })
        
        @self.socketio.on('logs:unsubscribe')
        def handle_logs_unsubscribe():
            """Unsubscribe from log streaming"""
            session_id = request.sid
            leave_room('logs_subscribers')
            print(f"[LOGS] Client {session_id[:8]} unsubscribed from logs")
            emit('logs:unsubscribed', {})
        
        @self.socketio.on('logs:set_sources')
        def handle_logs_set_sources(data):
            """Enable/disable specific log sources"""
            sources = data.get('sources', {})  # {source: enabled}
            
            
            # Get or create streamer
            streamer = self._get_log_streamer()
            if streamer:
                for source, enabled in sources.items():
                    streamer.set_source_enabled(source, enabled)
                
                emit('logs:sources_updated', streamer.get_enabled_sources())
        
        @self.socketio.on('logs:get_sources')
        def handle_logs_get_sources():
            """Get available log sources and their enabled state"""
            emit('logs:sources', self._get_log_sources())
    
    def _get_log_sources(self) -> dict:
        """Get available log sources with enabled state"""
        from ..services.log_streamer import LogStreamer
        return {
            source: {
                'enabled': config['enabled'],
                'name': source.upper(),
                'description': self._get_source_description(source)
            }
            for source, config in LogStreamer.LOG_SOURCES.items()
        }
    
    def _get_source_description(self, source: str) -> str:
        """Get human-readable description for a log source"""
        descriptions = {
            'llm': 'LLM API calls (tokens, cost, latency)',
            'tool': 'Tool executions (success, timing)',
            'opencode': 'OpenCode sessions',
            'thinking': 'Reasoning decisions (if enabled)',
            'feedback': 'Feedback ratings'
        }
        return descriptions.get(source, source)
    
    def _ensure_log_streamer_running(self):
        """Ensure the log streamer is running and broadcasting"""
        if not hasattr(self, '_log_streamer') or self._log_streamer is None:
            from ..services.log_streamer import LogStreamer
            
            def broadcast_log(entry):
                """Broadcast log entry to all subscribed clients"""
                self.socketio.emit('logs:entry', entry.to_dict(), room='logs_subscribers')
            
            self._log_streamer = LogStreamer(broadcast_log)
            self._log_streamer.start()
            print("[LOGS] Log streamer started")
    
    def _get_log_streamer(self):
        """Get the log streamer instance"""
        return getattr(self, '_log_streamer', None)
    
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
                         message_id: str, conversation_id: str, image_data: dict = None,
                         prompt_meta: dict = None, request_feedback: bool = False):
        """Process a chat message through the orchestrator (with optional vision, prompt metadata, and feedback)"""
        start_time = time.time()
        prompt_meta = prompt_meta or {}
        prompt_info = f", prompt={prompt_meta.get('prompt_name')}" if prompt_meta.get('prompt_name') else ""
        feedback_info = f", request_feedback={request_feedback}" if request_feedback else ""
        print(f"[CHAT] Processing message: {message[:50]}... (mode={mode}, session={session_id[:8]}, has_image={image_data is not None}{prompt_info}{feedback_info})")
        
        try:
            # Debug image data
            if image_data:
                print(f"[CHAT] Image data keys: {image_data.keys() if isinstance(image_data, dict) else 'not a dict'}")
                print(f"[CHAT] Image base64 length: {len(image_data.get('base64', '')) if isinstance(image_data, dict) else 'N/A'}")
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
            
            # Apply image/video provider overrides via JARVIS_OVERRIDE_ prefix
            # These survive load_config() in tool subprocesses (which re-reads cloud.env)
            # get_config_value() checks JARVIS_OVERRIDE_{key} before os.environ[key]
            image_provider_override = mode_overrides.get('image_provider')
            video_provider_override = mode_overrides.get('video_provider')
            
            # Set or clear override env vars (cleared = fall back to cloud.env default)
            if image_provider_override:
                os.environ['JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER'] = image_provider_override
            else:
                os.environ.pop('JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER', None)
            
            if video_provider_override:
                os.environ['JARVIS_OVERRIDE_VIDEO_TOOL_PROVIDER'] = video_provider_override
            else:
                os.environ.pop('JARVIS_OVERRIDE_VIDEO_TOOL_PROVIDER', None)
            
            print(f"[CHAT] Provider overrides - image: {image_provider_override or '(env default)'}, video: {video_provider_override or '(env default)'}")
            
            # Image action modal can override providers further (takes priority over AI config)
            if image_data and image_data.get('action') == 'video':
                # Image-to-video is always xAI
                os.environ['JARVIS_OVERRIDE_VIDEO_TOOL_PROVIDER'] = 'xai'
                print(f"[CHAT] Image modal override - video provider: xai (image-to-video)")
            elif image_data and image_data.get('action') == 'image':
                modal_provider = image_data.get('settings', {}).get('provider')
                if modal_provider:
                    os.environ['JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER'] = modal_provider
                    print(f"[CHAT] Image modal override - image provider: {modal_provider}")
            
            # Handle image if provided - route based on action
            vision_result = None
            stash_info = None
            tool_overrides = {}  # Forced param overrides that bypass LLM decisions
            
            if image_data and image_data.get('base64'):
                image_action = image_data.get('action', 'analyze')
                image_settings = image_data.get('settings', {})
                print(f"[CHAT] Image action: {image_action}, settings: {image_settings}")
                
                if image_action == 'video':
                    # IMAGE TO VIDEO: Skip vision, stash image, force params via overrides
                    print(f"[CHAT] Image-to-video mode - skipping vision analysis")
                    self.socketio.emit('chat:status', {
                        'message_id': message_id,
                        'conversation_id': conversation_id,
                        'status': 'Preparing image for video generation...',
                        'timestamp': time.time()
                    }, room=session_id)
                    
                    stash_info = self._auto_stash_image(image_data, '', mode)
                    stash_ref = stash_info.get('stash_ref', '') if stash_info else ''
                    
                    if stash_ref:
                        print(f"[CHAT] Auto-stashed image for video: {stash_ref}")
                    
                    # Build forced overrides - these WILL be applied regardless of
                    # what the LLM decides. The LLM generates the creative prompt,
                    # but technical params are enforced from the user's modal selections.
                    aspect_ratio = image_settings.get('aspect_ratio', '16:9')
                    duration = image_settings.get('duration', 5)
                    resolution = image_settings.get('resolution', '720p')
                    
                    tool_overrides['generate_video'] = {
                        'image_url': stash_ref,
                        'aspect_ratio': aspect_ratio,
                        'duration': int(duration),
                        'resolution': resolution,
                        'provider': 'xai',
                    }
                    
                    message = (
                        f"[User uploaded an image for VIDEO generation (image-to-video).\n"
                        f"Image stashed at: {stash_ref}\n"
                        f"Use generate_video tool. IMPORTANT: The user has pre-selected these video "
                        f"settings via the UI and they will be applied automatically as overrides:\n"
                        f"  aspect_ratio={aspect_ratio}, duration={duration}s, resolution={resolution}, provider=xai\n"
                        f"These parameters are USER-CONTROLLED and will override whatever you pass. "
                        f"Do NOT worry if the tool result shows different values than what you sent - "
                        f"that is expected and correct. The user's chosen settings take priority.\n"
                        f"Your job: craft a detailed, creative prompt from the user's instructions below. "
                        f"Do NOT retry if the result looks successful.]\n\n"
                        f"User's video instructions: {message}"
                    )
                    print(f"[CHAT] Image-to-video - forced overrides: {aspect_ratio}, {duration}s, {resolution}")
                    
                elif image_action == 'image':
                    # IMAGE TO IMAGE: Skip vision, stash image, force params via overrides
                    print(f"[CHAT] Image-to-image mode - skipping vision analysis")
                    self.socketio.emit('chat:status', {
                        'message_id': message_id,
                        'conversation_id': conversation_id,
                        'status': 'Preparing image for generation...',
                        'timestamp': time.time()
                    }, room=session_id)
                    
                    stash_info = self._auto_stash_image(image_data, '', mode)
                    stash_ref = stash_info.get('stash_ref', '') if stash_info else ''
                    
                    if stash_ref:
                        print(f"[CHAT] Auto-stashed image for generation: {stash_ref}")
                    
                    # Build forced overrides for generate_image
                    img_overrides = {}
                    for key, val in image_settings.items():
                        if val is not None and val != '' and val is not False:
                            img_overrides[key] = val
                    tool_overrides['generate_image'] = img_overrides
                    
                    # Build context message for LLM (params are hints, overrides enforce)
                    param_lines = []
                    for key, val in img_overrides.items():
                        param_lines.append(f"- {key}: \"{val}\"" if isinstance(val, str) else f"- {key}: {val}")
                    params_str = '\n'.join(param_lines) if param_lines else '(use defaults)'
                    
                    message = (
                        f"[User uploaded a reference image for IMAGE generation.\n"
                        f"Image stashed at: {stash_ref}\n"
                        f"Use generate_image tool. IMPORTANT: The user has pre-selected these image "
                        f"settings via the UI and they will be applied automatically as overrides:\n"
                        f"{params_str}\n"
                        f"These parameters are USER-CONTROLLED and will override whatever you pass. "
                        f"Do NOT worry if the tool result shows different values than what you sent - "
                        f"that is expected and correct. The user's chosen settings take priority.\n"
                        f"Your job: craft a detailed, creative prompt from the user's instructions below. "
                        f"Do NOT retry if the result looks successful. Do NOT run vision analysis.]\n\n"
                        f"User's image instructions: {message}"
                    )
                    print(f"[CHAT] Image-to-image - forced overrides: {img_overrides}")
                    
                else:
                    # ANALYZE (default): Current vision analysis flow
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
                        # Auto-stash the uploaded image for future tool access
                        stash_info = self._auto_stash_image(
                            image_data, 
                            vision_result, 
                            mode
                        )
                        if stash_info:
                            print(f"[CHAT] Auto-stashed image: {stash_info.get('stash_ref')}")
                        
                        # Prepend vision analysis to message for orchestrator
                        stash_note = ""
                        if stash_info:
                            stash_note = f" Image stashed at: {stash_info.get('stash_ref')}"
                        
                        message = f"[User uploaded an image. Vision analysis: {vision_result}]{stash_note}\n\nUser's message: {message}"
                        print(f"[CHAT] Image analyzed - passing to orchestrator with vision context")
            
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
            
            # Set up progress callback for real-time tool execution events
            # Check if progress events are enabled (default: True)
            from ..config import get_web_setting
            progress_enabled = get_web_setting('ui.progress_events', True)
            
            if progress_enabled:
                def progress_callback(event_type: str, **kwargs):
                    """Send tool progress events to browser via WebSocket"""
                    if event_type == 'tool_start':
                        tool_name = kwargs.get('tool')
                        call_index = kwargs.get('call_index', 0)
                        print(f"[CHAT] Tool starting: {tool_name}[{call_index}] (turn {kwargs.get('turn')}/{kwargs.get('max_turns')})")
                        self.socketio.emit('tool:start', {
                            'message_id': message_id,
                            'tool': tool_name,
                            'call_index': call_index,  # For unique card IDs when same tool called multiple times
                            'args': kwargs.get('args', {}),
                            'turn': kwargs.get('turn'),
                            'max_turns': kwargs.get('max_turns'),
                            'timestamp': time.time()
                        }, room=session_id)
                    
                    elif event_type == 'tool_complete':
                        # Emit tool completion in real-time (success or failure)
                        tool_name = kwargs.get('tool')
                        call_index = kwargs.get('call_index', 0)
                        duration_ms = kwargs.get('duration_ms')
                        success = kwargs.get('success')
                        
                        if success:
                            print(f"[CHAT] Tool completed: {tool_name}[{call_index}] ({duration_ms}ms)")
                            self.socketio.emit('tool:complete', {
                                'message_id': message_id,
                                'tool': tool_name,
                                'call_index': call_index,  # For matching unique card ID
                                'result': {},  # Result will be in final response
                                'duration_ms': duration_ms,
                                'success': True,
                                'timestamp': time.time()
                            }, room=session_id)
                        else:
                            print(f"[CHAT] Tool failed: {tool_name}[{call_index}] - {kwargs.get('error', 'unknown')}")
                            self.socketio.emit('tool:error', {
                                'message_id': message_id,
                                'tool': tool_name,
                                'call_index': call_index,
                                'error': kwargs.get('error', 'Unknown error'),
                                'duration_ms': duration_ms,
                                'timestamp': time.time()
                            }, room=session_id)
                    
                    elif event_type == 'routing':
                        print(f"[CHAT] Routing: {kwargs.get('message')}")
                        self.socketio.emit('tool:progress', {
                            'message_id': message_id,
                            'status': kwargs.get('message'),
                            'timestamp': time.time()
                        }, room=session_id)
                
                orchestrator.set_progress_callback(progress_callback)
                
                # Set cancel check callback
                def cancel_check():
                    return self.pending_cancellations.get(message_id, False)
                
                orchestrator.set_cancel_check(cancel_check)
            
            # Get conversation history for context
            conversation_history = self._get_conversation_context(conversation_id)
            
            # Get blocked tools for web mode
            from ..config import get_web_setting
            blocked_tools = list(get_web_setting('tools.blocked', []))
            
            # Build enhanced message with @prompt instructions if present
            enhanced_message = message
            system_instruction = prompt_meta.get('system_instruction')
            
            if system_instruction:
                print(f"[CHAT] Prepending prompt instruction ({len(system_instruction)} chars)")
                enhanced_message = f"[CONTEXT - Use these guidelines for the request below]\n\n{system_instruction}\n\n[END CONTEXT]\n\nUser's request: {message}"
            
            # Process the query with conversation context, excluded tools, and forced overrides
            override_info = f", tool_overrides={list(tool_overrides.keys())}" if tool_overrides else ""
            print(f"[CHAT] Calling orchestrator.process() with {len(conversation_history)} history messages, {len(blocked_tools)} blocked tools{override_info}...")
            result = orchestrator.process(
                enhanced_message,
                conversation_history=conversation_history,
                excluded_tools=blocked_tools,
                tool_overrides=tool_overrides if tool_overrides else None
            )
            
            # Clean up cancellation flag
            if message_id in self.pending_cancellations:
                del self.pending_cancellations[message_id]
            
            was_cancelled = result.get('cancelled', False)
            print(f"[CHAT] Got result: ok={result.get('ok')}, tools={result.get('tools_used', [])}, cancelled={was_cancelled}")
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Extract tools used from result
            tools_used = result.get('tools_used', [])
            data = result.get('data', {})
            
            # Check if this is a workflow result (has different structure)
            is_workflow = result.get('workflow_executed') or data.get('workflow_id')
            
            if is_workflow:
                # Workflow results have step-by-step data in data.results
                step_results = data.get('results', [])
                emit_index = 0
                for step_data in step_results:
                    tool = step_data.get('tool', 'unknown')
                    step_ok = step_data.get('ok', True)
                    step_num = step_data.get('step')
                    
                    # Check for for_each outputs (multiple iterations of same tool)
                    outputs = step_data.get('outputs', [])
                    if outputs:
                        # Emit separate event for each for_each iteration
                        for idx, output in enumerate(outputs):
                            output_ok = output.get('ok', True) if isinstance(output, dict) else True
                            output_data = output.get('data', output) if isinstance(output, dict) else output
                            self.socketio.emit('tool:complete', {
                                'tool': tool,
                                'result': output_data,
                                'duration_ms': duration_ms // max(len(step_results), 1),
                                'success': output_ok,
                                'message_id': message_id,
                                'workflow_step': f"{step_num}_{idx}"  # Unique per iteration
                            }, room=session_id)
                            emit_index += 1
                    else:
                        # Single execution step
                        self.socketio.emit('tool:complete', {
                            'tool': tool,
                            'result': step_data.get('data', {}),
                            'duration_ms': duration_ms // max(len(step_results), 1),
                            'success': step_ok,
                            'message_id': message_id,
                            'workflow_step': step_num
                        }, room=session_id)
                        emit_index += 1
            else:
                # Normal orchestrator results - tools_used may have duplicates
                # Skip emitting tool:complete if progress_events is enabled - we handle this in real-time
                # via the progress callback (prevents duplicate tool cards)
                if not progress_enabled:
                    # Track how many times each tool has been seen to create unique IDs
                    tool_counts = {}
                    for idx, tool in enumerate(tools_used):
                        # Get result - accumulated_data may be a list for repeated tools
                        tool_result = data.get(tool, {})
                        
                        # If result is a list, get the specific iteration
                        tool_idx = tool_counts.get(tool, 0)
                        if isinstance(tool_result, list):
                            if tool_idx < len(tool_result):
                                tool_result = tool_result[tool_idx]
                            else:
                                tool_result = tool_result[-1] if tool_result else {}
                        
                        tool_counts[tool] = tool_idx + 1
                        
                        self.socketio.emit('tool:complete', {
                            'tool': tool,
                            'result': tool_result,
                            'duration_ms': duration_ms // max(len(tools_used), 1),
                            'success': True,
                            'message_id': message_id,
                            'workflow_step': idx  # Use overall index for unique ID
                        }, room=session_id)
            
            # Save assistant response to conversation
            try:
                from ..services.conversation_store import get_conversation_store
                store = get_conversation_store()
                response_text = result.get('speech', result.get('raw_llm_response', ''))
                # Include raw_llm_response and vision_analysis in saved data for "expand details"
                save_data = data.copy() if data else {}
                raw_response = result.get('raw_llm_response', '')
                if raw_response:
                    save_data['raw_llm_response'] = raw_response
                # Include vision analysis if we processed an image
                if vision_result:
                    save_data['vision_analysis'] = vision_result
                if stash_info:
                    save_data['stash'] = stash_info
                # Include token usage for tracking
                if result.get('usage'):
                    save_data['usage'] = result['usage']
                store.add_message(
                    conversation_id, 
                    'assistant', 
                    response_text,
                    data=save_data,
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
            # Include raw_llm_response and vision_analysis in data for "expand details" feature
            response_data = data.copy() if data else {}
            raw_response = result.get('raw_llm_response', '')
            if raw_response:
                response_data['raw_llm_response'] = raw_response
            # Include vision analysis if we processed an image
            if vision_result:
                response_data['vision_analysis'] = vision_result
            if stash_info:
                response_data['stash'] = stash_info
            
            self.socketio.emit('chat:response', {
                'message_id': message_id,
                'conversation_id': conversation_id,
                'text': result.get('speech', raw_response),  # Show speech (shorter) as main text
                'speech': result.get('speech', ''),
                'data': response_data,
                'tools_used': tools_used,
                'ok': result.get('ok', True),
                'cancelled': was_cancelled,  # True if user stopped processing
                'duration_ms': duration_ms,
                'usage': result.get('usage', {}),
                'audio_url': audio_url,
                'server_side_tools': result.get('server_side_tools', {})  # xAI/Anthropic native tools
            }, room=session_id)
            
            # Collect feedback if requested (runs async after main response)
            # Skip if orchestrator already collected feedback (random 10% case)
            already_has_feedback = result.get('feedback') is not None
            print(f"[CHAT] Feedback check: request_feedback={request_feedback}, ok={result.get('ok', True)}, already_has_feedback={already_has_feedback}")
            
            if request_feedback and result.get('ok', True) and not already_has_feedback:
                print(f"[CHAT] Starting async feedback collection for message {message_id[:8]}...")
                self.socketio.start_background_task(
                    self._collect_feedback_async,
                    session_id,
                    message,
                    mode,
                    message_id,
                    conversation_id,
                    result,
                    tools_used,
                    orchestrator
                )
            elif already_has_feedback and request_feedback:
                # Orchestrator already collected feedback (random trigger), emit that result
                print(f"[CHAT] Using orchestrator's feedback (random trigger)")
                feedback = result.get('feedback', {})
                self.socketio.emit('feedback:start', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'status': 'complete'  # Already done
                }, room=session_id)
                self.socketio.emit('feedback:complete', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'rating': feedback.get('rating'),
                    'suggestions': feedback.get('suggestions', []),
                    'analysis': feedback.get('analysis', ''),
                    'duration_ms': 0,  # Already collected
                    'success': True
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
    
    def _collect_feedback_async(self, session_id: str, query: str, mode: str,
                                 message_id: str, conversation_id: str, 
                                 result: dict, tools_used: list, orchestrator):
        """Collect feedback asynchronously after main response is sent"""
        import time as time_module
        start_time = time_module.time()
        
        try:
            # Emit feedback:start event so UI can show the card
            self.socketio.emit('feedback:start', {
                'message_id': message_id,
                'conversation_id': conversation_id,
                'status': 'analyzing'
            }, room=session_id, namespace='/')
        except Exception as emit_err:
            print(f"[FEEDBACK] ERROR emitting feedback:start: {emit_err}")
        
        try:
            from feedback import FeedbackCollector
            from config_loader import get_config_value, load_config
            
            # Ensure config is loaded for the right mode
            load_config(mode)
            
            collector = FeedbackCollector(mode)
            
            # Get tools used
            if isinstance(tools_used, str):
                tools_used = [tools_used]
            
            num_tools = len(orchestrator.registry.list_tools())
            
            # Get system prompt from router
            system_prompt = orchestrator.router.system_prompt if hasattr(orchestrator.router, 'system_prompt') else None
            
            # Get tool descriptions for relevant tools
            tool_descriptions = {}
            relevant_tools = set(tools_used)
            query_lower = query.lower()
            if "time" in query_lower:
                relevant_tools.add("get_time")
            if "weather" in query_lower:
                relevant_tools.add("weather")
            if "bitcoin" in query_lower or "crypto" in query_lower or "price" in query_lower:
                relevant_tools.add("crypto_price")
            if "memory" in query_lower or "remember" in query_lower:
                relevant_tools.update(["semantic_recall", "search_memory", "remember"])
            
            for tool_name in relevant_tools:
                try:
                    tool = orchestrator.registry.get_tool(tool_name)
                    if tool:
                        tool_descriptions[tool_name] = tool.description
                except:
                    pass
            
            # Build config context
            response_style = get_config_value('JARVIS_RESPONSE_STYLE', 'auto')
            style_explanations = {
                'casual': 'Short voice-friendly output. URLs are REMOVED, search results summarized to ~50 words.',
                'auto': 'Smart mode. Search tools get condensed (no URLs), complex tools keep full details.',
                'detailed': 'FULL LLM response preserved. URLs ARE INCLUDED. Verbose output is EXPECTED and CORRECT.'
            }
            style_explanation = style_explanations.get(response_style, 'Unknown style')
            
            config_context = f"""
Auto-Context: {'Enabled' if orchestrator.auto_context_enabled else 'Disabled'}
Response Style: {response_style}
  → Style Behavior: {style_explanation}
Tools Available: {num_tools}
Mode: {mode}
"""
            
            # Force logging for manually triggered feedback
            import os
            os.environ['JARVIS_FEEDBACK_ALWAYS_LOG'] = '1'
            
            # Collect feedback
            feedback = collector.collect(
                query=query,
                result=result,
                tools_used=tools_used,
                num_tools=num_tools,
                system_prompt=system_prompt,
                tool_descriptions=tool_descriptions,
                intelligence_insights=result.get("intelligence_context", ""),
                config_context=config_context,
                session_id=orchestrator.session_id
            )
            
            # Clean up env var
            os.environ.pop('JARVIS_FEEDBACK_ALWAYS_LOG', None)
            
            duration_ms = int((time_module.time() - start_time) * 1000)
            
            # Extract all feedback fields
            rating = feedback.get('rating')
            summary = feedback.get('summary', '')
            positive = feedback.get('positive', '')
            issues = feedback.get('issues', [])
            suggestions = feedback.get('suggestions', issues)  # Fallback to issues
            tool_ratings = feedback.get('tool_ratings', {})
            analysis = feedback.get('analysis', '')
            
            print(f"[FEEDBACK] Completed: rating={rating}/5, issues={len(issues)}, duration={duration_ms}ms")
            
            # Emit feedback:complete event with all fields
            try:
                self.socketio.emit('feedback:complete', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'rating': rating,
                    'summary': summary,
                    'positive': positive,
                    'issues': issues,
                    'suggestions': suggestions,
                    'tool_ratings': tool_ratings,
                    'analysis': analysis,
                    'duration_ms': duration_ms,
                    'success': True
                }, room=session_id, namespace='/')
            except Exception as emit_err:
                print(f"[FEEDBACK] ERROR emitting feedback:complete: {emit_err}")
            
        except Exception as e:
            duration_ms = int((time_module.time() - start_time) * 1000)
            print(f"[FEEDBACK] ERROR: {e}")
            
            # Emit error state
            try:
                self.socketio.emit('feedback:complete', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'error': str(e),
                    'duration_ms': duration_ms,
                    'success': False
                }, room=session_id, namespace='/')
            except Exception as emit_err:
                print(f"[FEEDBACK] ERROR emitting feedback:complete: {emit_err}")
    
    def _generate_tts(self, text: str, mode: str = None) -> str:
        """Generate TTS audio and return URL - mode-aware"""
        try:
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
                tts_url = get_jarvis_setting('KOKORO_TTS_URL', '') or get_jarvis_setting('TTS_URL', '')
                if not tts_url:
                    print("[CHAT TTS] Kokoro provider but TTS_URL not set!")
                    return None
                audio_path = self._local_tts(text, tts_dir, timestamp, tts_url)
            elif provider == 'qwen3-tts':
                # Qwen3-TTS (OpenAI-compatible API on local network)
                audio_path = self._qwen3_tts(text, tts_dir, timestamp)
            elif provider == 'elevenlabs':
                audio_path = self._elevenlabs_tts(text, tts_dir, timestamp)
            elif provider == 'openai':
                audio_path = self._openai_tts(text, tts_dir, timestamp)
            else:
                # Unknown provider - try qwen3-tts as fallback for local network
                print(f"[CHAT TTS] Unknown provider '{provider}', trying OpenAI TTS")
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
        
        voice = get_jarvis_setting('KOKORO_TTS_VOICE', '') or get_jarvis_setting('TTS_VOICE', 'af_nicole')
        speed = float(get_jarvis_setting('KOKORO_TTS_SPEED', '') or get_jarvis_setting('TTS_SPEED', '1.0'))
        
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
    
    def _qwen3_tts(self, text: str, output_dir: Path, timestamp: str) -> Path:
        """Generate TTS using Qwen3-TTS API (OpenAI-compatible on local network)"""
        import requests
        from ..config import get_jarvis_setting
        
        tts_url = get_jarvis_setting('QWEN3_TTS_URL', '') or get_jarvis_setting('TTS_URL', '')
        if not tts_url:
            print("[CHAT TTS] Qwen3-TTS provider but QWEN3_TTS_URL not set!")
            return None
        
        voice = get_jarvis_setting('QWEN3_TTS_VOICE', '') or get_jarvis_setting('TTS_VOICE', 'Jarvis')
        speed = float(get_jarvis_setting('QWEN3_TTS_SPEED', '') or get_jarvis_setting('TTS_SPEED', '1.0'))
        audio_format = get_jarvis_setting('QWEN3_TTS_FORMAT', 'mp3')
        
        print(f"[CHAT TTS] Qwen3-TTS: url={tts_url}, voice={voice}, format={audio_format}")
        
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": voice,
            "speed": speed,
            "response_format": audio_format
        }
        
        try:
            # Longer timeout for first-time voice builds (Qwen3 caches voices)
            response = requests.post(tts_url, json=payload, timeout=60)
            if response.status_code == 200:
                ext = audio_format if audio_format != 'mp3' else 'mp3'
                output_path = output_dir / f"tts_{timestamp}.{ext}"
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return output_path
            else:
                print(f"[CHAT] Qwen3-TTS error: {response.status_code} - {response.text[:100]}")
                return None
        except Exception as e:
            print(f"[CHAT] Qwen3-TTS failed: {e}")
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
        
        # v3 has 5k char limit, v2 has 10k - truncate if needed
        char_limit = 5000 if model_id == 'eleven_v3' else 10000
        if len(text) > char_limit:
            print(f"[CHAT TTS] Text truncated from {len(text)} to {char_limit} chars for {model_id}")
            text = text[:char_limit]
        
        print(f"[CHAT TTS] ElevenLabs: model={model_id}, voice={voice_id[:8]}..., chars={len(text)}")
        
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
        
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        if response.status_code != 200:
            print(f"[CHAT] OpenAI TTS error: {response.status_code} - {response.text}")
            return None
        
        output_path = output_dir / f"tts_{timestamp}.mp3"
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        return output_path

    def _auto_stash_image(self, image_data: dict, vision_analysis: str = '', mode: str = 'cloud') -> dict:
        """
        Auto-stash uploaded image for future tool access.
        Also adds to memory_db as stash_artifact for cross-session recall.
        vision_analysis can be empty for non-vision flows (image-to-video, image-to-image).
        
        Returns stash info dict or None on failure.
        """
        from datetime import datetime, timezone
        from pathlib import Path
        import shutil
        
        try:
            # Get the uploaded image path
            image_url = image_data.get('url', '')
            image_filename = image_data.get('filename', '')
            
            if not image_url or not image_filename:
                print("[STASH] No image URL/filename to stash")
                return None
            
            # Find the uploaded image file
            web_root = Path(__file__).parent.parent.parent
            uploads_path = web_root / 'data' / 'uploads' / image_filename
            
            if not uploads_path.exists():
                print(f"[STASH] Upload file not found: {uploads_path}")
                return None
            
            # Import stash helper
            from stash_helper import open_space
            
            # Create stash space for web uploads
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            has_vision = bool(vision_analysis)
            space_labels = ['web_upload', 'image']
            if has_vision:
                space_labels.append('vision_analyzed')
            space, is_new = open_space(
                labels=space_labels,
                scope='session',
                ttl_days=7
            )
            
            # Copy image to stash space
            dest_filename = f"upload_{timestamp}.jpg"
            dest_path = space.space_path / dest_filename
            shutil.copy2(uploads_path, dest_path)
            
            # Get file stats
            file_size = dest_path.stat().st_size
            
            # Add file to space metadata
            import hashlib
            with open(dest_path, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            
            file_id = f"f_{file_hash[:12]}"
            file_meta = {
                'file_id': file_id,
                'name': dest_filename,
                'stored_name': dest_filename,
                'mime_type': 'image/jpeg',
                'size_bytes': file_size,
                'hash_sha256': file_hash,
                'tags': ['user_upload', 'vision_analyzed'] if has_vision else ['user_upload'],
                'tool_origin': 'web_upload',
                'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
                'vision_analysis': vision_analysis[:500] if has_vision else ''
            }
            
            # Update space meta
            space.meta.setdefault('files', []).append(file_meta)
            space._save_meta()
            
            stash_ref = f"stash://{space.space_id}/{file_id}"
            
            # Add to memory_db for cross-session recall
            # MemoryDB() uses the already-loaded config (load_jarvis_config was called earlier)
            try:
                from memory_db import MemoryDB
                db = MemoryDB()
                
                memory_key = f"stash_image_{space.space_id}"
                # Build memory value based on whether vision was performed
                if has_vision:
                    short_analysis = vision_analysis[:200] + "..." if len(vision_analysis) > 200 else vision_analysis
                    memory_value = f"Uploaded image: {short_analysis}. STASH: {stash_ref}. FILE: {dest_filename}"
                else:
                    image_action = image_data.get('action', 'upload')
                    memory_value = f"Uploaded image for {image_action}. STASH: {stash_ref}. FILE: {dest_filename}"
                
                memory_tags = ["image", "user_upload"]
                if has_vision:
                    memory_tags.append("vision_analyzed")
                
                db.remember(
                    key=memory_key,
                    value=memory_value,
                    category="stash_artifact",
                    importance=6,  # Same as generate_image
                    source="web_upload",
                    metadata={
                        "stash_ref": stash_ref,
                        "space_id": space.space_id,
                        "file_id": file_id,
                        "filename": dest_filename,
                        "tags": memory_tags,
                        "type": "image"
                    }
                )
                print(f"[STASH] Added to memory_db: {memory_key}")
            except Exception as mem_err:
                print(f"[STASH] Memory save failed (non-fatal): {mem_err}")
            
            return {
                'space_id': space.space_id,
                'file_id': file_id,
                'stash_ref': stash_ref,
                'path': str(dest_path),
                'filename': dest_filename
            }
            
        except Exception as e:
            print(f"[STASH] Auto-stash failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _process_vision(self, image_base64: str, prompt: str, mode: str) -> str:
        """
        Process an image with a vision model.
        Returns the vision model's description/analysis.
        """
        from ..config import load_jarvis_config
        
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
        
        try:
            base_url = get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434')
            vision_model = get_jarvis_setting('OLLAMA_VISION_MODEL', 'llava:latest')
            
            print(f"[VISION] Using Ollama: {vision_model} at {base_url}")
            print(f"[VISION] Image base64 length: {len(image_base64)}")
            
            payload = {
                "model": vision_model,
                "prompt": prompt,
                "images": [image_base64],
                "stream": False
            }
            
            print(f"[VISION] Sending request to Ollama...")
            response = requests.post(
                f"{base_url}/api/generate",
                json=payload,
                timeout=120  # Vision can be slow
            )
            print(f"[VISION] Got response: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                resp_text = result.get('response', '')
                print(f"[VISION] Ollama response length: {len(resp_text)}")
                return resp_text
            else:
                print(f"[VISION] Ollama error: {response.status_code} - {response.text[:200]}")
                return None
        except Exception as e:
            print(f"[VISION] Ollama exception: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _vision_cloud(self, image_base64: str, prompt: str, mode: str) -> str:
        """Use cloud provider's vision model (Anthropic, xAI, OpenAI)"""
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
