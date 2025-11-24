#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Main Orchestrator (v2)
Enhanced with LLM-based routing and confirmation flow.
"""
import os
import sys
import json
from typing import Dict, Any
from datetime import datetime

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config
from memory_db import get_memory_db

from router_v2 import LLMRouter
from executor import ToolExecutor


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
                
                # Execute the tool
                result = self.executor.execute(tool_name, arguments)
                
                if result["ok"]:
                    # Success - add to context and continue
                    if sys.stdout.isatty():
                        print(f"✅ Tool succeeded")
                        print(f"📊 Tool result: {json.dumps(result.get('data', {}), indent=2)[:200]}...")
                    
                    # Track tool execution
                    tools_used.append(tool_name)
                    accumulated_data[tool_name] = result.get("data", {})
                    
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
                    
                    # Retry if we haven't exceeded max retries
                    if retry_count < self.max_retries:
                        if sys.stdout.isatty():
                            print(f"🔄 Attempting retry {retry_count + 1}/{self.max_retries}...")
                        
                        # Build error context for retry
                        error_context = f"Tool '{tool_name}' failed with: {error}. Arguments used: {json.dumps(arguments)}"
                        
                        # Recursive retry with error context
                        return self.process(transcript, retry_count + 1, error_context)
                    
                    # Max retries exceeded
                    final_speech = f"{speech}. Error: {error}. I tried {retry_count + 1} time(s) but couldn't complete the task."
                    
                    # Auto-log failed conversation
                    self._log_conversation(transcript, final_speech, tools_used, success=False)
                    
                    return {
                        "speech": final_speech,
                        "ok": False,
                        "error": error,
                        "tools_used": tools_used,
                        "retries": retry_count
                    }
            
            # Handle Q&A (task complete - LLM decided to respond directly)
            elif route["intent"] == "qa":
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
                    "ok": True,
                    "tools_used": tools_used,
                    "data": accumulated_data
                }
                
                # Add token info to response if available (cloud only)
                if token_info:
                    response["usage"] = token_info
                
                # Add thinking to response if available
                if first_thinking:
                    response["thinking"] = first_thinking
                
                return response
            
            # Handle routing errors
            else:
                error = route.get("error", "Unknown routing error")
                speech = route.get("text_response", "Sorry, I had trouble understanding that.")
                if sys.stdout.isatty():
                    print(f"❌ Routing error: {error}")
                
                # Auto-log error
                self._log_conversation(transcript, speech, tools_used, success=False)
                
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
1. MAX 20 WORDS (25 if complex data like search results or errors)
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
                # If already short (<20 words), keep it
                word_count = len(raw_response.split())
                if word_count <= 20:
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

Condense this to ONE SENTENCE (MAX 20 words) for voice output.

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
            
            response = self.router.provider.chat(context, system_prompt="Output ONE sentence, MAX 20 words. No greetings, no emojis.")
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
            context = f"""User asked: "{user_query}"

Tools executed: {', '.join(tools_used)}

Results: {json.dumps(accumulated_data, indent=2)[:500]}

Create a SINGLE SENTENCE response for voice output (will be spoken aloud through speakers).

CRITICAL RULES:
1. MAX 20 WORDS
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
            
            response = self.router.provider.chat(context, system_prompt="You are a voice assistant. Output ONE sentence, MAX 20 words. No explanations.")
            return response.strip()
        except Exception as e:
            # Fallback to LLM's original response
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format multi-turn summary: {e}", file=sys.stderr)
            return llm_response
    
    def _format_max_turns_summary(self, user_query: str, tools_used: list, accumulated_data: dict, max_turns: int) -> str:
        """
        Create intelligent summary when max turns is reached.
        
        Args:
            user_query: Original user request
            tools_used: List of tool names executed
            accumulated_data: Results from all tools
            max_turns: The limit that was hit
            
        Returns:
            Voice-friendly explanation of progress and next steps
        """
        try:
            # Use LLM to create an intelligent progress summary
            context = f"""User asked: "{user_query}"

Tools executed ({len(tools_used)} actions): {', '.join(tools_used)}

Results: {json.dumps(accumulated_data, indent=2)[:5000]}

The task hit the complexity limit ({max_turns} turns). YOU MUST ANSWER THE USER'S QUESTION NOW.

CRITICAL RULES:
1. MAX 25 WORDS (provide actual answer if you have enough data!)
2. If the results contain the answer to the user's question, PROVIDE IT NOW
3. Don't say "hit limit" or list tools - just answer the question if possible
4. Only mention "complexity limit" if you truly cannot answer from the data you have

GOOD EXAMPLES (with data):
- "The top 3 movies are Wicked, Nosferatu, and Gladiator 2 playing at Regal this week"
- "Weather is 45°F and cloudy. Bitcoin is $101k. Your server is running on port 5000"

GOOD EXAMPLES (without enough data):
- "Searched 10 times but got 403 errors. Try checking showtimes.com directly"

BAD EXAMPLES:
- "Completed 8 steps but hit limit check the results" (don't mention technical details!)
- "I made 10 search attempts" (don't list what you did!)

Your response:"""
            
            response = self.router.provider.chat(context, system_prompt="You are a voice assistant. Answer the user's question if you have enough data. MAX 25 words. Don't mention 'complexity limit' unless absolutely necessary.")
            return response.strip()
        except Exception as e:
            # Fallback to simple message
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format max turns summary: {e}", file=sys.stderr)
            return f"Completed {len(tools_used)} actions but reached the complexity limit. Tools used: {', '.join(tools_used)}. Please review or let me know if you'd like me to continue."
    
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
        print("\nExample:")
        print("  ./orchestrator_v2.py cloud 'Send a webhook to my server'")
        print("  ./orchestrator_v2.py cloud 'Should I save this?' --debug-thinking")
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
    
    transcript = " ".join(sys.argv[2:])
    
    # Load config once for displaying model and creating orchestrator
    load_config(mode)
    
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

