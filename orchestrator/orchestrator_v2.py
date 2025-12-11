#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Main Orchestrator (v2)
Enhanced with LLM-based routing and confirmation flow.
"""
import os
import sys
import json
from typing import Dict, Any, List, Tuple
from datetime import datetime

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config
from memory_db import get_memory_db
from status_updater import StatusUpdater

from router_v2 import LLMRouter
from executor import ToolExecutor


def _sanitize_error_for_speech(error: str) -> str:
    """
    Sanitize technical error messages for voice output.
    Removes URLs, IPs, session IDs, and simplifies to user-friendly messages.
    """
    import re
    
    if not error:
        return "an unknown error occurred"
    
    error_lower = error.lower()
    
    # Map common errors to friendly messages
    if "400" in error or "bad request" in error_lower:
        return "the service returned an error"
    if "401" in error or "unauthorized" in error_lower:
        return "authentication failed"
    if "403" in error or "forbidden" in error_lower:
        return "access was denied"
    if "404" in error or "not found" in error_lower:
        return "the resource was not found"
    if "429" in error or "rate limit" in error_lower:
        return "too many requests, try again later"
    if "500" in error or "internal server error" in error_lower:
        return "the service encountered an error"
    if "502" in error or "bad gateway" in error_lower:
        return "the service is temporarily unavailable"
    if "503" in error or "service unavailable" in error_lower:
        return "the service is temporarily unavailable"
    if "timeout" in error_lower:
        return "the request timed out"
    if "connection" in error_lower and ("refused" in error_lower or "error" in error_lower):
        return "couldn't connect to the service"
    if "session" in error_lower or "transport" in error_lower:
        return "connection issue with the service"
    
    # Remove URLs, IPs, and session IDs from error if no pattern matched
    sanitized = re.sub(r'https?://[^\s]+', '', error)
    sanitized = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?', '', sanitized)
    sanitized = re.sub(r'session[Ii]d[=:][^\s&]+', '', sanitized)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    
    # If sanitized is too long or still technical, use generic message
    if len(sanitized) > 100 or not sanitized:
        return "there was a technical error"
    
    return sanitized


class Orchestrator:
    """Main orchestration with LLM-based routing, error recovery, and retry logic."""
    
    def __init__(self, mode='cloud'):
        """Initialize orchestrator."""
        self.mode = mode
        load_config(mode)
        
        # Auto-sync memory database from other mode if needed
        try:
            from auto_sync_memory import auto_sync_on_startup
            auto_sync_on_startup(mode, verbose=False)
        except Exception as e:
            # Non-critical - continue if sync fails
            pass
        
        # Create tool registry once (includes MCP discovery)
        # This prevents duplicate MCP containers
        from pathlib import Path
        from tool_schema import ToolRegistry
        project_root = Path(__file__).parent.parent
        skills_dir = str(project_root / "skills")
        mcp_config = str(project_root / "config" / "mcp-servers.json")
        self.registry = ToolRegistry(skills_dir, mcp_config)
        
        # Pass shared registry to router and executor
        self.router = LLMRouter(mode, registry=self.registry)
        self.executor = ToolExecutor(mode, registry=self.registry)
        self.max_retries = 1  # Maximum retry attempts
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")  # Unique session ID
        
        # Auto-context configuration
        from config_loader import get_config_value, get_int
        self.auto_context_enabled = get_config_value('AUTO_CONTEXT_ENABLED', 'true').lower() == 'true'
        self.auto_context_window = get_int('AUTO_CONTEXT_WINDOW', 3)
        self.auto_context_minutes = get_int('AUTO_CONTEXT_MINUTES', 10)
        
        # Status updates for voice progress feedback
        self.status_updater = StatusUpdater(mode)
    
    def process(self, transcript: str, retry_count: int = 0, error_context: str = None) -> Dict[str, Any]:
        """
        Process user transcript and execute tools or respond.
        Supports multi-turn tool execution until task is complete.
        
        Args:
            transcript: User's spoken input (from STT)
            retry_count: Current retry attempt (for error recovery)
            error_context: Previous error information (for retry)
            
        Returns:
            dict: Response for TTS
            {
                "speech": "Text to speak",
                "ok": bool,
                "data": {...} (optional),
                "error": str (optional)
            }
        """
        # Reset status updater for new task
        self.status_updater.reset()
        
        # Auto-inject recent conversation context (if enabled)
        if self.auto_context_enabled:
            enhanced_transcript = self._build_conversation_context(transcript)
            
            # Debug: Show what's being sent to LLM
            if os.environ.get('JARVIS_DEBUG'):
                print("\n" + "="*80, file=sys.stderr)
                print("DEBUG: Enhanced Transcript Being Sent to LLM:", file=sys.stderr)
                print("="*80, file=sys.stderr)
                print(enhanced_transcript, file=sys.stderr)
                print("="*80 + "\n", file=sys.stderr)
        else:
            enhanced_transcript = transcript
        
        # Pre-fetch available tool names for insight filtering
        # This ensures insights about blocked/unavailable tools aren't shown
        try:
            from memory_db import get_memory_db
            db = get_memory_db()
            available_tool_names = db.get_enabled_tool_names() if hasattr(db, 'get_enabled_tool_names') else []
        except Exception:
            available_tool_names = []  # Fallback: no filtering
        
        # Inject learned insights from self-learning intelligence
        learning_context, applied_insights = self._get_learning_insights(transcript, available_tool_names)
        if learning_context:
            enhanced_transcript = f"{learning_context}\n\n{enhanced_transcript}"
        
        # Multi-turn context tracking
        max_turns = 10  # Safety limit
        conversation_context = []
        tools_used = []
        accumulated_data = {}
        last_tool_call = None  # Track last tool to detect duplicates
        
        # If retrying, augment transcript with error context
        if error_context and retry_count > 0:
            enhanced_transcript = f"{enhanced_transcript}\n\n===PREVIOUS ATTEMPT FAILED WITH ERROR===: {error_context}\nPlease try again with corrected parameters or check logs if needed."
        
        # Track usage info across all turns
        total_usage = {
            "input_tokens": 0, 
            "output_tokens": 0, 
            "cost_usd": 0.0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_savings_usd": 0.0
        }
        
        # Track thinking from first turn (for display)
        first_thinking = None
        
        # Track available tools from first routing (for intelligence reflection)
        available_tools = []
        
        # Multi-turn loop
        for turn_num in range(max_turns):
            # Build context for this turn
            if turn_num == 0:
                # First turn: use original transcript
                turn_input = enhanced_transcript
            else:
                # Subsequent turns: provide context from previous tools
                turn_input = self._build_turn_context(enhanced_transcript, conversation_context)
            
            # Route using LLM
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: About to route turn {turn_num}", file=sys.stderr)
            route = self.router.route(turn_input)
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Routing complete, intent={route.get('intent')}", file=sys.stderr)
            
            # Accumulate usage info if available
            if route.get("usage_info"):
                usage = route["usage_info"]
                if usage.get("input_tokens"):
                    total_usage["input_tokens"] += usage["input_tokens"]
                if usage.get("output_tokens"):
                    total_usage["output_tokens"] += usage["output_tokens"]
                if usage.get("cost_usd"):
                    total_usage["cost_usd"] += usage["cost_usd"]
                # Accumulate cache metrics
                if usage.get("cache_creation_tokens"):
                    total_usage["cache_creation_tokens"] += usage["cache_creation_tokens"]
                if usage.get("cache_read_tokens"):
                    total_usage["cache_read_tokens"] += usage["cache_read_tokens"]
                if usage.get("cache_savings_usd"):
                    total_usage["cache_savings_usd"] += usage["cache_savings_usd"]
            
            # Capture thinking from first turn (for display)
            if turn_num == 0 and route.get("thinking") and not first_thinking:
                first_thinking = route["thinking"]
            
            # Capture available tools from first turn (for intelligence reflection)
            if turn_num == 0 and route.get("available_tools"):
                available_tools = route["available_tools"]
            
            # Handle tool execution
            if route["intent"] == "tool":
                tool_name = route["tool_name"]
                arguments = route["arguments"]
                
                # Detect duplicate tool calls (same tool, similar/empty args)
                current_call = (tool_name, json.dumps(arguments, sort_keys=True))
                if last_tool_call and last_tool_call == current_call:
                    if sys.stdout.isatty():
                        print(f"⚠️  Duplicate tool call detected: {tool_name}")
                        print(f"   Forcing Q&A mode to prevent redundant execution")
                    
                    # Force Q&A mode with summary of what was done
                    tools_summary = ', '.join(set(tools_used))
                    final_speech = f"I've completed the task using {len(set(tools_used))} tool(s): {tools_summary}."
                    
                    self._log_conversation(transcript, final_speech, tools_used, success=True)
                    
                    # Mark status updates complete
                    self.status_updater.mark_complete()
                    
                    return {
                        "speech": final_speech,
                        "ok": True,
                        "tools_used": tools_used,
                        "data": accumulated_data,
                        "duplicate_prevented": True
                    }
                
                last_tool_call = current_call
                
                # Only print if in interactive mode
                if sys.stdout.isatty():
                    turn_marker = f" (turn {turn_num + 1})" if turn_num > 0 else ""
                    print(f"🔧 Executing tool: {tool_name}{turn_marker}")
                    print(f"📝 Arguments: {json.dumps(arguments, indent=2)}")
                
                # Status update before tool execution
                self.status_updater.set_turn(turn_num + 1)
                
                # Determine category based on tool type
                if tool_name == 'opencode':
                    # OpenCode is long-running - start background updates
                    self.status_updater.update(category='building', tool_name=tool_name)
                    self.status_updater.start_background_updates(tool_name=tool_name, category='building')
                elif 'search' in tool_name or 'brave' in tool_name:
                    self.status_updater.update(category='searching', tool_name=tool_name)
                elif 'fetch' in tool_name or 'playwright' in tool_name:
                    self.status_updater.update(category='fetching', tool_name=tool_name)
                elif tool_name == 'weather':
                    self.status_updater.update(category='fetching', tool_name=tool_name)
                elif 'memory' in tool_name or 'recall' in tool_name:
                    # Memory tools are fast, skip status
                    pass
                elif turn_num >= 2:
                    # Multi-turn progress
                    self.status_updater.update(category='multi_turn', tool_name=tool_name)
                else:
                    # Default: acknowledge any other tool at first turn
                    if turn_num == 0:
                        self.status_updater.update(category='task_start', tool_name=tool_name)
                
                # Execute the tool
                result = self.executor.execute(tool_name, arguments)
                
                # Stop background updates after tool completes
                if tool_name == 'opencode':
                    self.status_updater.stop_background_updates()
                
                if result["ok"]:
                    # Success - add to context and continue
                    if sys.stdout.isatty():
                        print(f"✅ Tool succeeded")
                        print(f"📊 Tool result: {json.dumps(result.get('data', {}), indent=2)[:200]}...")
                    
                    # Track tool execution
                    tools_used.append(tool_name)
                    
                    # Aggregate data - handle multiple calls to same tool
                    tool_data = result.get("data", {})
                    if tool_name in accumulated_data:
                        # Convert to list if not already, then append
                        existing = accumulated_data[tool_name]
                        if not isinstance(existing, list):
                            accumulated_data[tool_name] = [existing]
                        accumulated_data[tool_name].append(tool_data)
                    else:
                        accumulated_data[tool_name] = tool_data
                    
                    # Add to conversation context for next turn
                    # Store full result (including speech and data) so LLM can see all information
                    conversation_context.append({
                        "tool": tool_name,
                        "arguments": arguments,
                        "result": result,  # Store full result, not just data
                        "speech": result.get("speech", "")
                    })
                    
                    # Continue to next turn (LLM will decide if more tools needed)
                    continue
                    
                else:
                    # Failure - check if we should retry
                    error = result.get("error", "Unknown error")
                    speech = result.get("speech", f"Failed to execute {tool_name}")
                    if sys.stdout.isatty():
                        print(f"❌ Tool failed: {error}")
                    
                    # Status update on error
                    is_server_error = '500' in str(error) or 'Internal Server Error' in str(error)
                    self.status_updater.update_error(
                        error_type='server' if is_server_error else 'retry',
                        error_message=error,
                        is_server_error=is_server_error
                    )
                    
                    # Retry if we haven't exceeded max retries
                    if retry_count < self.max_retries:
                        if sys.stdout.isatty():
                            print(f"🔄 Attempting retry {retry_count + 1}/{self.max_retries}...")
                        
                        # Build error context for retry
                        error_context = f"Tool '{tool_name}' failed with: {error}. Arguments used: {json.dumps(arguments)}"
                        
                        # Recursive retry with error context
                        return self.process(transcript, retry_count + 1, error_context)
                    
                    # Max retries exceeded - sanitize error for voice output
                    friendly_error = _sanitize_error_for_speech(error)
                    final_speech = f"{speech}. {friendly_error.capitalize()}. I tried {retry_count + 1} time(s) but couldn't complete the task."
                    
                    # Auto-log failed conversation
                    self._log_conversation(transcript, final_speech, tools_used, success=False)
                    
                    # Mark status updates complete
                    self.status_updater.mark_complete()
                    
                    return {
                        "speech": final_speech,
                        "ok": False,
                        "error": error,
                        "tools_used": tools_used,
                        "retries": retry_count
                    }
            
            # Handle Q&A (task complete - LLM decided to respond directly)
            elif route["intent"] == "qa":
                # Status update: near complete (if tools were used)
                if tools_used:
                    self.status_updater.update(category='near_complete')
                
                raw_speech = route.get("text_response", "I'm not sure how to respond.")
                
                # Apply response style formatting (for ALL responses, not just multi-turn)
                response_style = os.environ.get('JARVIS_RESPONSE_STYLE', 'casual').lower()
                
                if response_style == 'casual':
                    # Format for voice (short & sweet)
                    if turn_num > 0:
                        # Multi-turn: summarize all tool results
                        speech = self._format_multi_turn_summary(transcript, tools_used, accumulated_data, raw_speech)
                    else:
                        # Single-turn: condense the LLM's verbose response
                        speech = self._format_single_turn_casual(transcript, raw_speech)
                elif response_style == 'auto':
                    # Smart mode: decide based on tool type and complexity
                    speech = self._format_auto_mode(transcript, tools_used, accumulated_data, raw_speech, turn_num)
                else:
                    # Detailed mode - use LLM's raw response
                    speech = raw_speech
                
                if sys.stdout.isatty():
                    turn_marker = f" after {len(tools_used)} tool(s)" if turn_num > 0 else ""
                    print(f"💬 Task complete{turn_marker}: {speech}")
                
                # Auto-log conversation with all tools used and usage info
                token_info = total_usage if total_usage["cost_usd"] > 0 else None
                self._log_conversation(transcript, speech, tools_used, success=True, token_info=token_info)
                
                # Build response
                response = {
                    "speech": speech,
                    "raw_llm_response": raw_speech,  # Original LLM response before voice formatting
                    "ok": True,
                    "tools_used": tools_used,
                    "data": accumulated_data,
                    "available_tools": available_tools  # Tools LLM could choose from
                }
                
                # Add token info to response if available (cloud only)
                if token_info:
                    response["usage"] = token_info
                
                # Add thinking to response if available
                if first_thinking:
                    response["thinking"] = first_thinking
                
                # Record experience for self-learning (async, non-blocking)
                self._record_learning_experience(transcript, tools_used, response, conversation_context, applied_insights)
                
                # Mark status updates complete before final TTS
                self.status_updater.mark_complete()
                
                return response
            
            # Handle routing errors
            else:
                error = route.get("error", "Unknown routing error")
                speech = route.get("text_response", "Sorry, I had trouble understanding that.")
                if sys.stdout.isatty():
                    print(f"❌ Routing error: {error}")
                
                # Auto-log error
                self._log_conversation(transcript, speech, tools_used, success=False)
                
                # Mark status updates complete
                self.status_updater.mark_complete()
                
                return {
                    "speech": speech,
                    "ok": False,
                    "error": error
                }
        
        # Safety: Max turns reached (after loop completes)
        # Generate intelligent summary of what was accomplished
        response_style = os.environ.get('JARVIS_RESPONSE_STYLE', 'casual').lower()
        
        if response_style == 'casual' or response_style == 'auto':
            # Casual and auto both format max turns summary
            final_speech = self._format_max_turns_summary(transcript, tools_used, accumulated_data, max_turns)
        else:
            # Detailed mode: verbose fallback
            final_speech = f"Reached complexity limit after {len(tools_used)} actions. Tools used: {', '.join(tools_used)}. Please review the results or let me know if you'd like me to continue."
        
        if sys.stdout.isatty():
            print(f"⚠️  Max turns ({max_turns}) reached")
        
        self._log_conversation(transcript, final_speech, tools_used, success=True)
        
        # Mark status updates complete
        self.status_updater.mark_complete()
        
        return {
            "speech": final_speech,
            "ok": True,
            "tools_used": tools_used,
            "data": accumulated_data,
            "max_turns_reached": True
        }
    
    def _format_natural_response(self, user_query: str, tool_name: str, tool_result: Dict[str, Any]) -> str:
        """
        Use LLM to format tool results into natural conversational speech.
        
        Args:
            user_query: Original user question
            tool_name: Name of the tool that was executed
            tool_result: The tool's result dict
            
        Returns:
            Natural language response
        """
        try:
            # Extract relevant data
            data = tool_result.get("data", {})
            
            # Build context for LLM
            context = f"""User asked: "{user_query}"

Tool executed: {tool_name}
Tool result: {json.dumps(data, indent=2)}

Create a short response for voice output (spoken through speakers).

CRITICAL RULES:
1. MAX 25 WORDS (35 if complex data like search results or errors)
2. Answer directly, no greetings or confirmations
3. No emojis, no markdown, no numbered lists
4. Don't say URLs unless critical
5. If a tool failed and you are unable to resolve, say so and the reason why it failed.

GOOD EXAMPLES:
- "Bitcoin is $101,938, down 1% today"
- "Found 3 webhook memories: URL, logger, and port"
- "Time is 11:51 PM Wednesday"
- "Server is up and running started on localhost port 5001"

ERROR EXAMPLES:
- "Webhook failed to send: 404 Not Found"
- "Network error sending webhook: Connection timed out"
- "Unable to create reminder: invalid time format"
- "Server error: -> error message summarized"

BAD EXAMPLES:
- "Great! I've successfully looked up the time for you. It's currently 11:51 PM..."
- "Perfect! The webhook has been sent and here's what happened..."

Your response:"""
            
            # Get natural response from LLM (without tools)
            text_response, _, _ = self.router.provider.chat_with_tools(
                messages=[{"role": "user", "content": context}],
                tools=[],  # No tools for response formatting
                system_prompt="You are a voice assistant. Output ONE sentence, MAX 15 words. No greetings, no explanations."
            )
            
            if text_response:
                return text_response
            else:
                return tool_result.get("speech", "Done")
            
        except Exception as e:
            # Fallback to tool's built-in speech
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format natural response: {e}", file=sys.stderr)
            return tool_result.get("speech", "Completed")
    
    def _format_auto_mode(self, user_query: str, tools_used: list, accumulated_data: dict, raw_response: str, turn_num: int) -> str:
        """
        Smart auto mode: Adapt response based on tool type and complexity.
        
        Rules:
        - Search tools → Format for voice (remove URLs, summarize)
        - Simple data tools → Keep concise
        - Complex/build tools → More detail
        - Multi-turn → Format summary
        
        Args:
            user_query: Original user request
            tools_used: List of tool names executed
            accumulated_data: Results from all tools
            raw_response: Verbose response from LLM
            turn_num: Current turn number
            
        Returns:
            Intelligently formatted response
        """
        try:
            # Multi-turn: always format (could be complex)
            if turn_num > 0:
                return self._format_multi_turn_summary(user_query, tools_used, accumulated_data, raw_response)
            
            # Single-turn: decide based on tool type
            if not tools_used:
                # Pure Q&A, no tools - keep short
                return self._format_single_turn_casual(user_query, raw_response)
            
            tool_name = tools_used[0] if tools_used else ""
            
            # TODO: Need to be able to dynamiticly add tools as tool list grows to the categories without having to edit the code. Search tools might be fine to hardcode like below. 
            # Define tool categories
            SEARCH_TOOLS = [
                'search_memory', 'semantic_recall', 'recall', 'search_conversations',
                'mcp_brave_search',  # Matches all brave search variants (web, local, news, image, video)
                'mcp_fetch'  # Matches mcp_fetch_fetch
            ]
            SIMPLE_TOOLS = ['get_time', 'crypto_price', 'get_weather']
            COMPLEX_TOOLS = ['opencode', 'execute_bash', 'send_webhook', 'api_call']
            
            # Search tools: Format for voice (remove URLs, summarize)
            if any(search in tool_name.lower() for search in SEARCH_TOOLS):
                # Format search results - remove URLs, keep key info
                return self._format_single_turn_casual(user_query, raw_response)
            
            # Simple data tools: Already concise, keep as-is or condense slightly
            elif any(simple in tool_name.lower() for simple in SIMPLE_TOOLS):
                # If already short (<25 words), keep it
                word_count = len(raw_response.split())
                if word_count <= 25:
                    return raw_response
                # Otherwise condense
                return self._format_single_turn_casual(user_query, raw_response)
            
            # Complex/build tools: Check if response is technical or simple
            elif any(complex in tool_name.lower() for complex in COMPLEX_TOOLS):
                # If response is very long (>50 words), it's probably detailed - keep detailed
                word_count = len(raw_response.split())
                if word_count > 50:
                    return raw_response  # Keep detailed for complex operations
                else:
                    # Short response for complex tool - condense it
                    return self._format_single_turn_casual(user_query, raw_response)
            
            # Default: condensed formatting for voice
            else:
                return self._format_single_turn_casual(user_query, raw_response)
                
        except Exception as e:
            if sys.stdout.isatty():
                print(f"⚠️ Auto mode formatting failed: {e}", file=sys.stderr)
            # Fallback to raw response
            return raw_response
    
    def _format_single_turn_casual(self, user_query: str, raw_response: str) -> str:
        """
        Condense a verbose Q&A response for voice output (casual mode).
        
        Args:
            user_query: Original user request
            raw_response: Verbose response from LLM
            
        Returns:
            Concise voice-friendly version
        """
        try:
            # If already short, return as-is
            word_count = len(raw_response.split())
            if word_count <= 20:
                return raw_response
            
            # Use LLM to condense verbose response
            context = f"""User asked: "{user_query}"

Your previous verbose response: {raw_response}

Condense this to ONE SENTENCE (MAX 25 words) for voice output.

CRITICAL RULES:
1. Keep the core answer/outcome
2. Keep critical details (numbers, URLs if essential, status)
3. Remove: greetings, emojis, explanations, numbered lists, markdown

EXAMPLES:
Verbose: "Great! I've successfully looked up the time. It's currently 11:51 PM on Wednesday, November 12th."
Concise: "It's 11:51 PM Wednesday, November 12th"

Verbose: "Perfect! The tetris server has been started successfully and is now running on port 5000!"
Concise: "Tetris server started on port 5000"

Your concise response:"""
            
            response = self.router.provider.chat(context, system_prompt="Output ONE sentence, MAX 25 words. No greetings, no emojis.")
            return response.strip()
        except Exception as e:
            # Fallback: use first sentence of raw response
            if sys.stdout.isatty():
                print(f"⚠️ Failed to condense response: {e}", file=sys.stderr)
            first_sentence = raw_response.split('.')[0] + '.'
            return first_sentence
    
    def _format_multi_turn_summary(self, user_query: str, tools_used: list, accumulated_data: dict, llm_response: str) -> str:
        """
        Format multi-turn results for voice output (short & sweet).
        
        Args:
            user_query: Original user request
            tools_used: List of tool names executed
            accumulated_data: Results from all tools
            llm_response: Raw response from LLM
            
        Returns:
            Concise voice-friendly summary
        """
        try:
            # Use LLM to create a concise voice summary
            # Calculate dynamic truncation - more data for repeated tools (arrays)
            has_arrays = any(isinstance(v, list) for v in accumulated_data.values())
            max_chars = 2000 if has_arrays else 800
            
            context = f"""User asked: "{user_query}"

Tools executed: {', '.join(tools_used)}

Results: {json.dumps(accumulated_data, indent=2)[:max_chars]}

Create a SINGLE SENTENCE response for voice output (will be spoken aloud through speakers).

CRITICAL RULES:
1. MAX 25 WORDS
2. State outcome + essential detail only
3. No emojis, no markdown, no bullet points, no explanations of what you did

GOOD EXAMPLES:
- "Tetris server started on port 5000 at 192.168.70.228"
- "Webhook sent successfully, URL saved to memory"
- "Bitcoin price is $101,000, down 2% today"
- "Email sent to John, confirmation code 12345"

BAD EXAMPLES (TOO LONG):
- "Perfect! I've successfully started the Tetris game server. Here's what I did: 1. Found the game..."
- "Great news! The webhook has been sent successfully to httpbin.org and I've saved the URL..."

Your response:"""
            
            response = self.router.provider.chat(context, system_prompt="You are a voice assistant. Output ONE sentence, MAX 25 words. No explanations.")
            return response.strip()
        except Exception as e:
            # Fallback to LLM's original response
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format multi-turn summary: {e}", file=sys.stderr)
            return llm_response
    
    def _format_max_turns_summary(self, user_query: str, tools_used: list, accumulated_data: dict, max_turns: int) -> str:
        """
        Create intelligent summary when max turns is reached.
        BEST EFFORT MODE: Extract and present whatever useful data was gathered.
        
        Args:
            user_query: Original user request
            tools_used: List of tool names executed
            accumulated_data: Results from all tools
            max_turns: The limit that was hit
            
        Returns:
            Voice-friendly explanation of progress and next steps
        """
        try:
            # Extract useful data from accumulated results (especially for search arrays)
            extracted_data = self._extract_useful_data(accumulated_data)
            
            # Use LLM to create an intelligent progress summary
            context = f"""User asked: "{user_query}"

Tools executed ({len(tools_used)} actions): {', '.join(set(tools_used))}

ALL GATHERED DATA (BEST EFFORT - use this to answer!):
{extracted_data}

IMPORTANT: The task hit a complexity limit after {max_turns} tool calls. 
You MUST provide a BEST EFFORT answer using the data above.

CRITICAL RULES:
1. MAX 30 WORDS - but ACTUALLY ANSWER the question!
2. If you found ANY relevant info (movie titles, prices, names, etc.) - INCLUDE IT
3. Don't apologize or say "couldn't find" - give the best answer you can
4. If data is incomplete, answer what you CAN and note what's missing briefly
5. NEVER say "hit limit" or mention tool counts

GOOD BEST-EFFORT EXAMPLES:
- "Top movies at Regal Hillsboro: Wicked, Avatar Fire and Ash, Zootopia 2. Check fandango.com for exact showtimes."
- "Bitcoin $90k, Solana $143, Ethereum $3k - all up 2-3% today"
- "Found theaters: Regal Evergreen Parkway, AMC Progress Ridge. Current showtimes require checking their websites directly."

BAD EXAMPLES (never do this):
- "I searched 10 times but couldn't find..." (WRONG - use what you found!)
- "Hit complexity limit after 10 tools..." (WRONG - don't mention technical limits!)
- "Unable to find showtimes" (WRONG - at least mention the theaters/movies you DID find!)

Your BEST EFFORT response:"""
            
            response = self.router.provider.chat(context, system_prompt="You are a voice assistant. Provide a BEST EFFORT answer using whatever data you have. MAX 30 words. ALWAYS include any useful info you found - movie titles, theater names, prices, etc.")
            return response.strip()
        except Exception as e:
            # Fallback to simple message
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format max turns summary: {e}", file=sys.stderr)
            return f"Completed {len(tools_used)} actions but reached the complexity limit. Tools used: {', '.join(tools_used)}. Please review or let me know if you'd like me to continue."
    
    def _extract_useful_data(self, accumulated_data: dict) -> str:
        """
        Extract the most useful/relevant data from accumulated tool results.
        Handles arrays (repeated tool calls) and extracts titles, descriptions, key info.
        
        Args:
            accumulated_data: Dict of tool_name -> result or [results]
            
        Returns:
            Formatted string of extracted useful data
        """
        extracted_parts = []
        
        for tool_name, data in accumulated_data.items():
            # Handle arrays (multiple calls to same tool)
            if isinstance(data, list):
                items = data
            else:
                items = [data]
            
            tool_info = []
            for item in items:
                if isinstance(item, dict):
                    # Extract search results (brave search, fetch)
                    if 'raw' in item or 'full_text' in item:
                        # Parse search results - extract titles and descriptions
                        text = item.get('full_text', '')
                        if text:
                            # Extract first 2000 chars of each search result
                            tool_info.append(text[:2000])
                    
                    # Extract specific data fields
                    useful_fields = ['title', 'description', 'url', 'name', 'price', 
                                     'coin', 'price_usd', 'speech', 'result', 'content']
                    for field in useful_fields:
                        if field in item and item[field]:
                            tool_info.append(f"{field}: {str(item[field])[:500]}")
                else:
                    # Plain string/value
                    tool_info.append(str(item)[:1000])
            
            if tool_info:
                extracted_parts.append(f"\n=== {tool_name} ===")
                extracted_parts.extend(tool_info[:5])  # Limit to 5 items per tool
        
        # Join and limit total size
        result = "\n".join(extracted_parts)
        return result[:10000]  # 10k chars should be enough for summary
    
    def _build_conversation_context(self, current_query: str) -> str:
        """
        Auto-inject recent conversation history for context awareness.
        
        This gives Jarvis "short-term memory" of recent interactions, enabling:
        - Natural follow-up responses ("you just said it was hot!")
        - Awareness of recently used tools
        - Learning from recent failures
        - Continued multi-step workflows
        
        Args:
            current_query: User's current question/request
            
        Returns:
            Enhanced query with recent conversation context (if any relevant)
        """
        from datetime import timedelta
        
        try:
            db = get_memory_db()
            
            # Get recent conversations
            recent = db.get_recent_conversations(limit=self.auto_context_window)
            
            if not recent:
                return current_query
            
            # Filter by time window (only include recent conversations)
            cutoff = datetime.now() - timedelta(minutes=self.auto_context_minutes)
            
            relevant = []
            for conv in recent:
                # Parse timestamp (handle both string and datetime)
                ts_str = conv.get('timestamp', '')
                if isinstance(ts_str, str):
                    # Try parsing ISO format
                    try:
                        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    except:
                        # Skip if can't parse
                        continue
                elif hasattr(ts_str, 'timestamp'):
                    ts = ts_str
                else:
                    continue
                
                # Only include if within time window
                if ts > cutoff:
                    relevant.append(conv)
            
            # If no recent context within time window, just return current query
            if not relevant:
                return current_query
            
            # Build context block (oldest first for chronological order)
            # Using simple plain text format (no Unicode boxes - saves tokens!)
            context_parts = ["=== RECENT CONVERSATION HISTORY ==="]
            context_parts.append(f"Last {len(relevant)} conversation(s) in past {self.auto_context_minutes} minutes")
            context_parts.append("")
            
            for i, conv in enumerate(reversed(relevant), 1):  # Oldest first
                context_parts.append(f"[Previous Exchange {i}]")
                context_parts.append(f"User: {conv['user_query']}")
                context_parts.append(f"Assistant: {conv['jarvis_response']}")
                
                # Include tools used (critical for self-learning)
                tools_json = conv.get('tools_used')
                if tools_json:
                    try:
                        tools_list = json.loads(tools_json) if isinstance(tools_json, str) else tools_json
                        if tools_list:
                            context_parts.append(f"Tools used: {', '.join(tools_list)}")
                    except:
                        pass
                
                # Flag failures (critical for learning from mistakes!)
                success = conv.get('success', True)
                if not success:
                    context_parts.append("Status: FAILED - Task did not complete successfully")
                    context_parts.append("Consider using check_tool_logs to understand why")
                else:
                    context_parts.append("Status: Success")
                
                # Include model/cost metadata if available (helps understand complexity)
                metadata_json = conv.get('metadata')
                if metadata_json:
                    try:
                        metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                        if metadata:
                            model = metadata.get('model', 'unknown')
                            tool_count = metadata.get('tool_count', 0)
                            context_parts.append(f"Model: {model}, Tools called: {tool_count}")
                    except:
                        pass
                
                context_parts.append("")  # Blank line between conversations
            
            context_parts.append("=== CURRENT USER QUERY ===")
            context_parts.append(current_query)
            context_parts.append("")
            context_parts.append("Instructions:")
            context_parts.append("- Use the conversation history to provide context-aware responses")
            context_parts.append("- Reference previous topics naturally when relevant")
            context_parts.append("- Learn from failed attempts (check_tool_logs if needed)")
            context_parts.append("- Catch contradictions and continue multi-step workflows seamlessly")
            context_parts.append("- If you need more history, call get_recent_conversations tool")
            context_parts.append("- Learn from failed attempts (check_tool_logs if needed)")
            context_parts.append("- Catch contradictions (\"You just said X, now saying Y?\")")
            context_parts.append("- Continue multi-step workflows seamlessly")
            context_parts.append("- If context window is too short, you can call get_recent_conversations tool for more history")
            
            return "\n".join(context_parts)
            
        except Exception as e:
            # If context loading fails, gracefully degrade to just current query
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Context loading failed: {e}", file=sys.stderr)
            return current_query
    
    def _build_turn_context(self, original_query: str, conversation_context: list) -> str:
        """
        Build context string for subsequent turns in multi-turn conversation.
        
        Args:
            original_query: The user's original request
            conversation_context: List of previous tool executions and results
            
        Returns:
            Formatted context string for the LLM
        """
        context_parts = [f"Original user request: {original_query}\n"]
        context_parts.append("Tools executed so far:")
        
        for i, ctx in enumerate(conversation_context, 1):
            tool_name = ctx["tool"]
            result = ctx["result"]
            
            # Smart summarization: prioritize error details
            if not result.get("ok", True):
                # For failures, include full error context
                summary_parts = []
                summary_parts.append(f"Status: FAILED")
                if "error" in result:
                    summary_parts.append(f"Error: {result['error']}")
                if "data" in result and isinstance(result["data"], dict):
                    # Include error details from data
                    if "error" in result["data"]:
                        summary_parts.append(f"Details: {result['data']['error']}")
                    if "status_code" in result["data"]:
                        summary_parts.append(f"Status Code: {result['data']['status_code']}")
                result_summary = "\n   ".join(summary_parts)
            else:
                # For success: Pass full result (ok, speech, data, etc.) so LLM sees everything
                # Dynamically adjust truncation based on tool type
                if "search" in tool_name.lower() or "fetch" in tool_name.lower():
                    # Search/fetch tools: need MORE context (3000 chars) to capture movie titles, URLs, descriptions
                    max_chars = 3000
                else:
                    # Other tools: standard truncation (1500 chars)
                    max_chars = 1500
                
                result_summary = json.dumps(result, indent=2)[:max_chars]
            
            context_parts.append(f"\n{i}. {tool_name}")
            context_parts.append(f"   Result: {result_summary}")
        
        context_parts.append("\n\nBased on the above results, determine if you need to:")
        context_parts.append("1. Call another tool to complete the user's request")
        context_parts.append("2. Respond directly to the user (task complete)")
        
        return "\n".join(context_parts)
    
    def _get_learning_insights(self, transcript: str, available_tools: List[str] = None) -> Tuple[str, List[Dict]]:
        """
        Get learned insights to inform routing decisions.
        
        Args:
            transcript: User's query
            available_tools: List of currently available tool names (for filtering)
        
        Returns:
            Tuple of (formatted_prompt_string, list_of_applied_insights)
            The insights list is used later to track if they were helpful.
        """
        try:
            from intelligence_hooks import get_routing_insights, format_insights_for_prompt
            
            insights = get_routing_insights(transcript)
            
            # Only include if we have meaningful insights
            if insights.get('insights') and insights.get('confidence', 0) > 0.3:
                # Pass available_tools to filter out insights for blocked/unavailable tools
                formatted = format_insights_for_prompt(insights, available_tools)
                # Return both formatted string and raw insights for tracking
                return formatted, insights.get('insights', [])
        except Exception as e:
            # Don't let insight failures affect the main flow
            if os.environ.get('JARVIS_DEBUG'):
                print(f"⚠️ Learning insights failed: {e}", file=sys.stderr)
        
        return "", []
    
    def _record_learning_experience(
        self,
        transcript: str,
        tools_used: list,
        result: dict,
        conversation_context: list,
        applied_insights: list = None
    ):
        """
        Record interaction for self-learning intelligence.
        Non-blocking - failures are logged but don't affect response.
        
        Args:
            transcript: User's query
            tools_used: List of tools executed
            result: Final result dict
            conversation_context: Conversation history
            applied_insights: List of insights that were shown to LLM (for tracking)
        """
        try:
            from intelligence_hooks import record_interaction, track_insight_outcomes
            
            record_interaction(
                query=transcript,
                tools_used=tools_used,
                result=result,
                conversation_context=conversation_context
            )
            
            # Track insight usage if insights were applied
            if applied_insights:
                track_insight_outcomes(
                    insights=applied_insights,
                    tools_used=tools_used,
                    result=result
                )
        except Exception as e:
            # Don't let learning failures affect the main flow
            if os.environ.get('JARVIS_DEBUG'):
                print(f"⚠️ Learning recording failed: {e}", file=sys.stderr)
    
    def _log_conversation(self, user_query: str, response: str, tools_used: list, success: bool = True, 
                          execution_time_ms: float = None, token_info: dict = None):
        """Auto-log conversation to memory database with metadata."""
        try:
            # Build metadata
            metadata = {
                "mode": self.mode,
                "provider": getattr(self.router, 'provider_type', 'unknown'),
                "model": getattr(self.router, 'model_name', 'unknown')
            }
            
            # Add timing if available
            if execution_time_ms is not None:
                metadata["execution_time_ms"] = round(execution_time_ms, 2)
            
            # Add token/cost info for cloud providers only
            provider = metadata.get("provider", "")
            if token_info and provider in ["openai", "anthropic"]:
                metadata.update(token_info)
            
            # Add tool count
            metadata["tool_count"] = len(tools_used)
            
            db = get_memory_db()
            db.log_conversation(
                user_query=user_query,
                jarvis_response=response,
                tools_used=tools_used,
                session_id=self.session_id,
                success=success,
                metadata=metadata
            )
            db.close()
        except Exception as e:
            # Silently fail - don't break the main flow
            if sys.stdout.isatty():
                print(f"⚠️ Failed to log conversation: {e}", file=sys.stderr)


def main():
    """CLI interface."""
    if len(sys.argv) < 2:
        print("Usage: orchestrator_v2.py <mode> <transcript> [--json] [--debug-thinking]", file=sys.stderr)
        print("  mode: 'cloud' or 'local'", file=sys.stderr)
        print("  --json: Output only JSON (for scripting)", file=sys.stderr)
        print("  --debug-thinking: Show LLM reasoning (for debugging)", file=sys.stderr)
        print("  --feedback: Ask LLM for feedback about the experience (QA mode)", file=sys.stderr)
        print("\nExample:")
        print("  ./orchestrator_v2.py cloud 'Send a webhook to my server'")
        print("  ./orchestrator_v2.py cloud 'Should I save this?' --debug-thinking")
        print("  ./orchestrator_v2.py cloud 'Test a task' --feedback")
        sys.exit(1)
    
    mode = sys.argv[1]
    
    # Check for --json flag
    json_only = "--json" in sys.argv
    if json_only:
        sys.argv.remove("--json")
        # Set env var to suppress verbose MCP output
        os.environ['JARVIS_JSON_MODE'] = '1'
    
    # Check for --debug-thinking flag
    debug_thinking = "--debug-thinking" in sys.argv
    if debug_thinking:
        sys.argv.remove("--debug-thinking")
        # Set env var for thinking module
        os.environ['JARVIS_DEBUG_THINKING'] = '1'
    
    # Check for --feedback flag (LLM-as-QA mode)
    collect_feedback = "--feedback" in sys.argv
    if collect_feedback:
        sys.argv.remove("--feedback")
    
    transcript = " ".join(sys.argv[2:])
    
    # Load config early for random feedback check
    load_config(mode)
    
    # Random feedback during normal operation (if enabled)
    if not collect_feedback:
        import random
        from config_loader import get_config_value, get_float
        random_enabled = get_config_value('FEEDBACK_RANDOM_ENABLED', 'false').lower() == 'true'
        random_chance = get_float('FEEDBACK_RANDOM_CHANCE', 0.0)  # 0.1 = 10%
        if random_enabled and random.random() < random_chance:
            collect_feedback = True
            if not json_only:
                print("🎲 Random feedback collection triggered")
    
    if not json_only:
        from config_loader import get_config_value
        
        print(f"🎯 Processing: '{transcript}'")
        print(f"📡 Mode: {mode}")
        
        # Show model being used
        if mode == "cloud":
            provider = get_config_value("LLM_PROVIDER", "anthropic")
            if provider == "openai":
                model = get_config_value("CHAT_MODEL", "gpt-4o")
            elif provider == "xai":
                model = get_config_value("XAI_MODEL", "grok-4-1-fast-non-reasoning-latest")
            else:
                model = get_config_value("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        else:
            model = get_config_value("OLLAMA_MODEL", "qwen3-vl")
        print(f"🤖 Model: {model}")
        
        print("=" * 60)
    
    orch = Orchestrator(mode)
    result = orch.process(transcript)
    
    # Collect feedback if requested
    if collect_feedback:
        from feedback import FeedbackCollector
        from config_loader import get_config_value
        
        if not json_only:
            print("\n" + "=" * 60)
            print("🔍 COLLECTING FEEDBACK (LLM-as-QA Mode)")
            print("=" * 60)
        
        collector = FeedbackCollector(mode)
        
        # Get tools used from result
        tools_used = result.get("tools_used", [])
        if isinstance(tools_used, str):
            tools_used = [tools_used]
        
        num_tools = len(orch.registry.list_tools())
        
        # Get the ACTUAL system prompt from router (it's a property)
        system_prompt = orch.router.system_prompt if hasattr(orch.router, 'system_prompt') else None
        
        # Get tool descriptions for tools that were used (and some that should have been)
        tool_descriptions = {}
        relevant_tools = set(tools_used)
        # Add likely relevant tools based on query keywords
        query_lower = transcript.lower()
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
                tool = orch.registry.get_tool(tool_name)
                if tool:
                    tool_descriptions[tool_name] = tool.description
            except:
                pass
        
        # Get intelligence insights that were used (if available)
        intelligence_insights = result.get("intelligence_context", "Intelligence insights not captured in result.")
        
        # Build config context with EXPLANATIONS for style modes
        response_style = get_config_value('JARVIS_RESPONSE_STYLE', 'auto')
        
        # Explain what the style means so feedback LLM doesn't penalize correct behavior
        style_explanations = {
            'casual': 'Short voice-friendly output. URLs are REMOVED, search results summarized to ~25 words.',
            'auto': 'Smart mode. Search tools get condensed (no URLs), complex tools keep full details.',
            'detailed': 'FULL LLM response preserved. URLs ARE INCLUDED. Verbose output is EXPECTED and CORRECT.'
        }
        style_explanation = style_explanations.get(response_style, 'Unknown style')
        
        config_context = f"""
Auto-Context: {'Enabled' if orch.auto_context_enabled else 'Disabled'} (window={orch.auto_context_window}, minutes={orch.auto_context_minutes})
Response Style: {response_style}
  → Style Behavior: {style_explanation}
  → DO NOT penalize verbose output or URLs if style is 'detailed' - that's CORRECT behavior!
Tools Available: {num_tools}
Mode: {mode}
"""
        
        feedback = collector.collect(
            query=transcript,
            result=result,
            tools_used=tools_used,
            num_tools=num_tools,
            system_prompt=system_prompt,
            tool_descriptions=tool_descriptions,
            intelligence_insights=intelligence_insights,
            config_context=config_context,
            session_id=orch.session_id
        )
        
        # Add feedback to result
        result["feedback"] = feedback
        
        if not json_only:
            print(f"\n📊 Feedback Rating: {feedback.get('rating', 'N/A')}/5")
            print(f"📝 Summary: {feedback.get('summary', 'No summary')}")
            
            if feedback.get('issues'):
                print("\n⚠️  Issues Found:")
                for issue in feedback['issues']:
                    print(f"   [{issue.get('category', 'other')}] {issue.get('description', 'No description')}")
                    if issue.get('suggestion'):
                        print(f"      💡 Suggestion: {issue['suggestion']}")
            
            if feedback.get('positive'):
                print(f"\n✅ What Worked: {feedback['positive']}")
            
            print(f"\n📁 Feedback logged to: logs/feedback/feedback-{datetime.now().strftime('%Y-%m-%d')}.jsonl")
    
    if json_only:
        # Output only JSON for scripting
        print(json.dumps(result))
    else:
        # Pretty output for human viewing
        print("=" * 60)
        
        # Display thinking if present and not in JSON mode
        if result.get("thinking") and debug_thinking:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
            from thinking import format_thinking_display
            print(format_thinking_display(result["thinking"]))
        
        print(f"🗣️  Speech Output: {result['speech']}")
        print(f"✓  Status: {'✅ OK' if result['ok'] else '❌ Failed'}")
        
        # Show usage info with cache metrics (cloud mode only)
        if result.get("usage") and mode == "cloud":
            usage = result["usage"]
            print(f"\n💰 Token Usage:")
            print(f"   Input: {usage.get('input_tokens', 0):,} tokens")
            print(f"   Output: {usage.get('output_tokens', 0):,} tokens")
            
            # Show cache metrics if available
            cache_read = usage.get('cache_read_tokens', 0)
            cache_write = usage.get('cache_creation_tokens', 0)
            
            if cache_read > 0:
                print(f"   💾 Cache READ: {cache_read:,} tokens (90% cheaper!)")
                savings = usage.get('cache_savings_usd', 0)
                if savings > 0:
                    print(f"   ✅ Saved: ${savings:.4f}")
            elif cache_write > 0:
                print(f"   💾 Cache WRITE: {cache_write:,} tokens (first request)")
            
            print(f"   💵 Total Cost: ${usage.get('cost_usd', 0):.4f}")
        
        if result.get("data"):
            print(f"\n📊 Data: {json.dumps(result['data'], indent=2)}")
        
        print("\n📄 Full Response:")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

