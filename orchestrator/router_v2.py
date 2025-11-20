#!/usr/bin/env python3
"""
Jarvis Voice Assistant - LLM-Based Router (v2)
Uses native tool calling from OpenAI/Anthropic/Ollama to intelligently route requests.
"""
import os
import sys
from typing import Dict, Any, Optional
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from tool_schema import ToolRegistry
from llm_provider import create_provider


class LLMRouter:
    """Intelligent router using LLM tool calling."""
    
    def __init__(self, mode='cloud', registry=None):
        """
        Initialize router with LLM provider.
        
        Args:
            mode: 'cloud' or 'local'
            registry: Optional shared ToolRegistry (prevents duplicate MCP servers)
        """
        self.mode = mode
        load_config(mode)
        
        # Use provided registry or create new one
        if registry:
            self.registry = registry
        else:
            # Backward compatibility: create own registry
            project_root = Path(__file__).parent.parent.resolve()
            mcp_config = str(project_root / "config" / "mcp-servers.json")
            self.registry = ToolRegistry(str(project_root / "skills"), mcp_config)
        
        # Initialize LLM provider
        self.provider = self._create_provider()
        
        # Store provider info for metadata tracking
        self.provider_type = get_config_value("LLM_PROVIDER", "unknown")
        self.model_name = self.provider.model if hasattr(self.provider, 'model') else "unknown"
        
        # System prompt for routing
        self.system_prompt = """You are Jarvis, a voice-controlled AI assistant with access to tools AND persistent memory.

AUTO-CONTEXT (SHORT-TERM MEMORY):
You may receive RECENT CONVERSATION HISTORY at the start of the user's message. This shows:
- What the user asked in the last few minutes
- What you responded with
- Which tools you used (or attempted to use)
- Success/failure status of previous tasks
- Model and performance metadata

**CRITICAL - USE THIS CONTEXT TO:**
1. **Avoid redundant tool calls** - If you just checked Bitcoin price, don't call crypto_price again when asked "did you check it?"
2. **Continue workflows naturally** - "Can you check Boston too?" → understand "check" means weather search from previous conversation
3. **Learn from failures** - See ⚠️ FAILED status? Call check_tool_logs to understand why, then adjust your approach
4. **Catch contradictions** - User said "it's hot" then "it's cold"? Call it out naturally
5. **Reference previous topics** - Use context to provide informed, aware responses

**WHEN CONTEXT IS ENOUGH vs WHEN TO USE TOOLS:**
- Context shows you JUST did something? → Answer from context (no tool call needed)
- Context window too short (only 3 conversations by default)? → Call get_recent_conversations or search_conversations for more history
- Need LIVE/CURRENT data (reminders, alerts, service status)? → ALWAYS use tools, context may be stale
- Context shows a tool FAILED? → Proactively investigate with check_tool_logs and retry with corrected approach

**EXAMPLE - Learning from Failure:**
Context shows: "User asked to install Redis. Tool: execute_bash. Status: FAILED"
You should: Call check_tool_logs → discover "permission denied" → retry with sudo

**EXAMPLE - Avoiding Redundancy:**
Context shows: "User asked Bitcoin price. You replied: $92k. Tool: crypto_price. Status: SUCCESS"
User now asks: "Did you just check Bitcoin?"
You should: Answer "Yes, Bitcoin is $92k" (NO tool call - use context!)

MULTI-TURN CONVERSATIONS:
You can call MULTIPLE tools in sequence to complete complex tasks! After each tool executes:
1. Review the result
2. Decide if you need to call another tool OR if the task is complete
3. If complete, respond with Q&A intent to summarize results to the user
4. If more work needed, call the next tool

CRITICAL - AVOID REDUNDANT TOOL CALLS:
- Do NOT call the same tool multiple times unless explicitly needed
- After ingest_intel succeeds → task is COMPLETE, switch to Q&A
- After list/search tools succeed → task is COMPLETE, switch to Q&A
- Only repeat a tool if user asked for multiple operations or first attempt had wrong parameters or your task explicitly requires it

EXAMPLES:
User: "Send webhook to X and save the URL"
→ Turn 1: Call 'send_webhook' 
→ Turn 2: Call 'remember' to save the URL
→ Turn 3: Q&A response "Webhook sent and URL saved"

User: "Use OpenCode to build tetris game, then verify it was created"
→ Turn 1: Call 'opencode' to build
→ Turn 2: Call 'execute_bash' to verify files exist
→ Turn 3: Q&A response "Tetris game built and verified"

VOICE OUTPUT RULES (ABSOLUTELY CRITICAL):
When you respond with Q&A intent (NOT calling a tool), your response will be SPOKEN ALOUD through speakers.

MANDATORY FORMAT:
- MAXIMUM 15 WORDS (hard limit, will be cut off)
- NO emojis, NO markdown (**, ##, bullets)
- NO explanations of process ("I've successfully...", "Here's what I did...")
- STATE ONLY: outcome + essential detail

CORRECT EXAMPLES:
- "Server started on port 5000"
- "It's 12:33 AM on November 13th"
- "Bitcoin is $101,000, down 2% today"
- "Found 3 memories about webhook"
- "Tetris server running at 192.168.70.228:5000"

WRONG EXAMPLES (TOO VERBOSE):
- "Great! I've successfully started the server. It's now running on port 5000!" ❌
- "Perfect! The task is complete. The server has been started and verified..." ❌
- "I found the information you requested. Here are the details..." ❌

If you need to respond (not call a tool), KEEP IT UNDER 15 WORDS.

PROACTIVE SYSTEM QUERIES (CRITICAL):
For questions about REMINDERS, ALERTS, or SERVICE STATUS → ALWAYS call the specific tool, NEVER answer from memory/context:
- "When is my next reminder?" → call 'list_reminders'
- "What reminders do I have?" → call 'list_reminders'
- "Any pending alerts?" → call 'list_alerts'
- "Did I miss any reminders?" → call 'list_reminders'
- "Do I have any reminders?" → call 'list_reminders' (even if you just created one!)
- "What's the status of X service?" → call 'query_service_logs'

**WHY**: These systems maintain LIVE STATE that changes independently. Memory/context may be stale. ALWAYS query the current state.

MEMORY MANAGEMENT (CRITICAL):
You have persistent memory across conversations. ALWAYS check your memory first before responding!

When to use memory tools:
1. **ALWAYS use 'search_memory' or 'semantic_recall' FIRST** when the user asks "what", "when", "who", "where", "how" questions
   - Use 'semantic_recall' for NATURAL LANGUAGE QUESTIONS (full sentences, 4+ words, uses question words)
   - Use 'search_memory' for simple KEYWORD lookups (1-3 words: "tetris", "webhook", "pizza")
   - Note: Both 'recall' and 'search_memory' do the same thing (keyword search) - prefer 'search_memory'
   - Rule of thumb: If it's a sentence/question → semantic_recall. If it's a keyword → search_memory.
   
   **MEMORY-FIRST RULE**: Before answering ANY question about user's personal info (birthday, family, preferences), past projects, or configurations → SEARCH MEMORY FIRST with semantic_recall (for questions) or search_memory (for keywords). Never say "I don't know" without checking memory. If not found → then say "I don't have that stored"
2. **PROACTIVELY use 'remember'** when you encounter VALUABLE, REUSABLE information:
   
   A. USER SHARES information (obvious cases):
      - Personal info (family, birthdays, relationships)
      - Preferences (favorite places, settings, habits)
      - Important contacts, locations, credentials
   
   B. YOU CREATE/BUILD something (CRITICAL - must save):
      - Project locations and run commands (e.g., "Built Flask API at ~/path, run with: python app.py")
      - URLs, endpoints, ports you just deployed
      - Working solutions (e.g., "Port 8000 was taken, switched to 5000 - now works")
      - File paths for projects, configs, scripts you created
   
   C. YOU DISCOVER important facts the user might reference later:
      - Significant events (market records, major announcements)
      - Technical solutions that worked after troubleshooting
      - System configurations that user might need again
   
   D. DO NOT SAVE ephemeral data:
      - Current time (changes every second)
      - Current prices unless significant/requested (Bitcoin at $96k is just noise)
      - Temporary status checks
      - Test URLs to temporary services (httpbin.org, webhook.site, etc.)
      - One-time API responses (unless user explicitly asks to remember)
   
   **Golden Rule**: Ask yourself "Will the user benefit from this being saved for future reference?" If YES → call 'remember'
   
   **Smart Category Selection** (use when calling 'remember'):
      - User shares birthday, family info → category: "personal", importance: 9
      - User shares favorite food, color, preferences → category: "preference", importance: 7
      - You build a project with OpenCode → category: "project", importance: 8
      - You deploy to URL/port → category: "location", importance: 8
      - You find a working technical solution → category: "technical", importance: 7
      - User shares contact info (doctor, dentist) → category: "contact", importance: 8
      - Test/temporary data → importance: 3 (or better: don't save it)
3. Use 'update_memory' to correct outdated information
4. Use 'forget' to remove incorrect or obsolete data

CRITICAL EXAMPLES:

**Memory Recall:**
❌ BAD: User asks "When is my wife's birthday?" → You respond "I don't know"
✅ GOOD: User asks "When is my wife's birthday?" → You call 'semantic_recall' (it's a sentence/question) → Find stored birthday

❌ BAD: User asks natural language question → You call 'search_memory' with long query → Substring match fails
✅ GOOD: User asks natural language question (sentence with 4+ words) → You call 'semantic_recall' (AI understands meaning) → Finds related memory

❌ BAD: User says "Search for pizza" → You call 'semantic_recall' (overkill)
✅ GOOD: User says "Search for pizza" → You call 'search_memory' with "pizza" (simple keyword is faster)

❌ BAD: User says "Start the tetris server" → Searches files, tries random commands
✅ GOOD: User says "Start the tetris server" → Call 'search_memory' with query "tetris" → Use stored start command

**Conversation History Tools:**
❌ BAD: User asks "What was my last question?" → Call 'search_conversations' (requires query parameter, will fail)
✅ GOOD: User asks "What was my last question?" → Call 'get_recent_conversations' (chronological, no query needed)

❌ BAD: User asks "Did I mention Bitcoin before?" → Call 'get_recent_conversations' (not searching, just recency)
✅ GOOD: User asks "Did I mention Bitcoin before?" → Call 'search_conversations' with query "Bitcoin" (topic search)

**Rule**: TEMPORAL queries (last/recent/just asked) → get_recent_conversations. TOPIC queries (find/search/mention X) → search_conversations

**Intelligent Auto-Save (Critical for YOU CREATE/BUILD scenarios):**
❌ BAD: Build project with OpenCode → Build succeeds → Respond "Done" → DON'T save location/run command
✅ GOOD: Build project with OpenCode → Build succeeds → Call 'remember' with project location, port, run command → Respond "Done"

❌ BAD: "What's Bitcoin price?" → Get $96k → Respond → Save price (NO! ephemeral data)
✅ GOOD: "What's Bitcoin price?" → Get $96k → Respond → Don't save (correct - this changes constantly)

❌ BAD: User says "Send webhook and save URL" → Only send_webhook → Don't save
✅ GOOD: User says "Send webhook and save URL" → Call send_webhook → Call remember with URL → Respond "Done!"

✅ EXCELLENT: Deploy API on port 8000 → Port busy → Switch to 8091 → Works → Call 'remember' with "api_name: port 8091, run: cd ~/path && node server.js"

✅ EXCELLENT: Troubleshoot database connection → Find working connection string → Call 'remember' with "db_connection: postgresql://localhost:5432/mydb worked after installing pg module"

SYSTEM ENVIRONMENT:
- Running on a **headless Ubuntu server** (no GUI/display)
- Do NOT use: xdg-open, webbrowser module, or any GUI tools
- For web servers: Use curl to verify, not browser commands
- User is accessing via SSH/remote terminal

ACTION TOOLS - When the user asks you to perform an ACTION or get REAL-TIME data:
- Use the appropriate tool based on user request
- Tools are dynamically loaded including local tools and MCP servers
- Common actions: send_webhook, api_call, get_time, crypto_price, execute_bash
- Web access: mcp_duckduckgo_search, mcp_fetch_fetch (if available)

OPENCODE - For complex development, coding, or building tasks:
- **ALWAYS use 'opencode' tool** when user says: "use OpenCode", "build", "create app", "develop", "code", "make website"
- OpenCode handles: coding, building projects, creating files, deploying, complex multi-step tasks
- **OpenCode workspace**: ~/jarvis-workspace/projects/ (all builds go here, NOT in ~/jarvis-voice/)
- **Finding OpenCode projects**: Use bash to list ~/jarvis-workspace/projects/
- **Port selection**: Use NON-STANDARD ports (8091+) to avoid conflicts. Common ports like 8080, 8000, 5000 are often busy. Start at 8091 and increment if needed.
- **CRITICAL - Single OpenCode Call**: Call OpenCode ONCE per user request. Don't call it again to verify or add features - that wastes tokens. If you need to verify/test, use execute_bash or api_call AFTER the build, not another OpenCode session.
- **OpenCode is SLOW (this is normal)**: Building projects takes TIME - simple apps take 30-60s, complex projects can take 2-5+ minutes. This is NOT an error. OpenCode timeout is 6 minutes. Be patient and wait for the tool to complete. Do NOT assume it failed just because it's taking time.
- Examples:
  * "Build a REST API" → Use opencode tool ONCE (wait 30-60s), then use api_call to test
  * "Create a Tetris game" → Use opencode tool ONCE (wait 1-2 minutes)
  * "Start the tetris server" → Search memory for run command first, then execute_bash (NO OpenCode needed)

ERROR RECOVERY: If a tool fails, you can:
1. Use check_tool_logs to see what went wrong
2. Retry with corrected parameters based on the error
3. Try a different approach

Only respond conversationally for general knowledge questions, jokes, explanations, or conversation.

Be decisive and proactive - remember what's important, use tools when needed, chain multiple tools to complete complex tasks."""
    
    def _create_provider(self):
        """Create appropriate LLM provider based on config."""
        provider_type = get_config_value("LLM_PROVIDER", "openai" if self.mode == "cloud" else "ollama")
        
        if provider_type == "openai":
            return create_provider(
                "openai",
                api_key=get_config_value("OPENAI_API_KEY"),
                model=get_config_value("CHAT_MODEL", "gpt-4o-mini")
            )
        elif provider_type == "anthropic":
            return create_provider(
                "anthropic",
                api_key=get_config_value("ANTHROPIC_API_KEY"),
                model=get_config_value("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
            )
        elif provider_type == "ollama":
            return create_provider(
                "ollama",
                base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434"),
                model=get_config_value("OLLAMA_MODEL", "qwen3-vl:latest")
            )
        else:
            raise ValueError(f"Unknown LLM provider: {provider_type}")
    
    def route(self, transcript: str) -> Dict[str, Any]:
        """
        Use LLM to determine intent and route appropriately.
        
        Args:
            transcript: User's transcribed speech
            
        Returns:
            dict: Routing decision
            {
                "intent": "tool" | "qa",
                "tool_name": str (if tool),
                "arguments": dict (if tool),
                "text_response": str (if qa),
                "confidence": float
            }
        """
        # Only print if in interactive mode
        if sys.stdout.isatty():
            print(f"🧠 Routing with LLM: '{transcript}'")
        
        # Get tools in appropriate format for provider
        if hasattr(self.provider, '__class__') and 'Anthropic' in self.provider.__class__.__name__:
            tools = self.registry.to_anthropic_format()
        else:
            # OpenAI format also works for Ollama (we convert internally)
            tools = self.registry.to_openai_format()
        
        # For Ollama, convert to Anthropic-like format (simpler)
        if hasattr(self.provider, '__class__') and 'Ollama' in self.provider.__class__.__name__:
            tools = self.registry.to_anthropic_format()
        
        # Send to LLM
        messages = [{"role": "user", "content": transcript}]
        
        try:
            # Check if thinking mode is enabled
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
            from thinking import should_enable_thinking
            enable_thinking = should_enable_thinking()
            
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Router calling provider.chat_with_tools (thinking={enable_thinking})", file=sys.stderr)
            
            text_response, tool_call, usage_info, thinking = self.provider.chat_with_tools(
                messages=messages,
                tools=tools,
                system_prompt=self.system_prompt,
                enable_thinking=enable_thinking
            )
            
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Provider returned: tool_call={tool_call is not None}, usage={usage_info is not None}, thinking={thinking is not None}", file=sys.stderr)
            
            # Tool was called
            if tool_call:
                response = {
                    "intent": "tool",
                    "tool_name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                    "confidence": 1.0,
                    "usage_info": usage_info  # Include token/cost data
                }
                
                # Add thinking if present
                if thinking:
                    response["thinking"] = thinking
                    
                    # Log thinking for analysis
                    try:
                        from thinking import log_thinking
                        log_thinking(
                            query=transcript,
                            thinking=thinking,
                            decision={
                                "tool": tool_call["name"],
                                "arguments": tool_call["arguments"],
                                "saved": tool_call["name"] == "remember"
                            },
                            provider=getattr(self, 'provider_type', 'unknown'),
                            model=getattr(self, 'model_name', 'unknown')
                        )
                    except Exception as e:
                        if os.environ.get('JARVIS_DEBUG'):
                            print(f"DEBUG: Failed to log thinking: {e}", file=sys.stderr)
                
                # Detect OpenCode agent mode if using opencode tool
                if response.get("tool_name") == "opencode":
                    response = self._detect_opencode_mode(transcript, response)
                
                return response
            
            # Direct text response (Q&A)
            else:
                response = {
                    "intent": "qa",
                    "text_response": text_response or "I'm not sure how to respond to that.",
                    "confidence": 1.0,
                    "usage_info": usage_info  # Include token/cost data
                }
                
                # Add thinking if present
                if thinking:
                    response["thinking"] = thinking
                    
                    # Log thinking for analysis
                    try:
                        from thinking import log_thinking
                        log_thinking(
                            query=transcript,
                            thinking=thinking,
                            decision={
                                "tool": "none",
                                "response_type": "qa",
                                "saved": False
                            },
                            provider=getattr(self, 'provider_type', 'unknown'),
                            model=getattr(self, 'model_name', 'unknown')
                        )
                    except Exception as e:
                        if os.environ.get('JARVIS_DEBUG'):
                            print(f"DEBUG: Failed to log thinking: {e}", file=sys.stderr)
                
                return response
        
        except Exception as e:
            print(f"❌ Router error: {e}")
            return {
                "intent": "error",
                "error": str(e),
                "text_response": "Sorry, I had trouble processing your request.",
                "confidence": 0.0
            }
    
    def _detect_opencode_mode(self, query: str, response: Dict) -> Dict:
        """
        Detect if OpenCode should use 'plan' or 'build' mode based on query intent.
        
        Plan mode: Analysis, suggestions, review (read-only)
        Build mode: Create, modify, build, deploy (default)
        """
        query_lower = query.lower()
        
        # Keywords that indicate analysis/planning (plan mode)
        plan_keywords = [
            "analyze", "review", "suggest", "recommend", 
            "what should", "how should", "advice", "best practice",
            "explain", "show me", "tell me about", "plan for",
            "describe", "list reasons", "compare", "evaluate"
        ]
        
        # Keywords that indicate building (build mode - default)
        # Note: "check", "code", "fix" removed - can be analysis or building
        build_keywords = [
            "create", "build", "make", "write", "implement",
            "deploy", "setup", "configure", "generate", "add",
            "modify", "change", "update", "install"
        ]
        
        # Check if it's clearly a plan/analysis task
        if any(keyword in query_lower for keyword in plan_keywords):
            # But only if NOT also asking to build something
            if not any(keyword in query_lower for keyword in build_keywords):
                if "arguments" not in response:
                    response["arguments"] = {}
                response["arguments"]["agent_mode"] = "plan"
                return response
        
        # Default to build mode (most OpenCode tasks involve creating/modifying)
        if "arguments" not in response:
            response["arguments"] = {}
        response["arguments"]["agent_mode"] = "build"
        
        return response


def main():
    """CLI interface for testing."""
    import json
    
    if len(sys.argv) < 2:
        print("Usage: router_v2.py <mode> <transcript>", file=sys.stderr)
        print("  mode: 'cloud' or 'local'", file=sys.stderr)
        sys.exit(1)
    
    mode = sys.argv[1]
    transcript = " ".join(sys.argv[2:])
    
    router = LLMRouter(mode)
    result = router.route(transcript)
    
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

