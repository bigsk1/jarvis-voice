#!/usr/bin/env python3
"""
Jarvis Voice Assistant - LLM-Based Router (v2)
Uses native tool calling from OpenAI/Anthropic/Ollama to intelligently route requests.
"""
import os
import sys
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from tool_schema import ToolRegistry
from llm_provider import create_provider


class LLMRouter:
    """Intelligent router using LLM tool calling."""
    
    def __init__(self, mode='cloud', registry=None, provider_override=None, model_override=None):
        """
        Initialize router with LLM provider.
        
        Args:
            mode: 'cloud' or 'local'
            registry: Optional shared ToolRegistry (prevents duplicate MCP servers)
            provider_override: Optional provider override (for web UI)
            model_override: Optional model override (for web UI)
        """
        self.mode = mode
        self._provider_override = provider_override
        self._model_override = model_override
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
        self.provider_type = self._provider_override or get_config_value("LLM_PROVIDER", "unknown")
        self.model_name = self.provider.model if hasattr(self.provider, 'model') else "unknown"
        
        # Timezone for timestamps (configurable via env)
        self.timezone = ZoneInfo(get_config_value("JARVIS_TIMEZONE", "America/Los_Angeles"))
        
        # System prompt for routing (base prompt - time is prepended dynamically)
        self._system_prompt_base = """You are Jarvis, a voice-controlled AI assistant with access to tools AND persistent memory.

AUTO-CONTEXT (SHORT-TERM MEMORY):
You may receive RECENT CONVERSATION HISTORY at the start of the user's message. This shows:
- What the user asked in the last few minutes
- What you responded with
- Which tools you used (or attempted to use)
- Success/failure status of previous tasks
- Model and performance metadata

**CRITICAL - USE THIS CONTEXT TO:**
1. **Avoid redundant tool calls** - If you just checked Bitcoin price, don't call the tool again when asked "did you check it?"
2. **Continue workflows naturally** - "Can you check Boston too?" → understand "check" means weather search from previous conversation
3. **Learn from failures** - See ⚠️ FAILED status? Call check_tool_logs to understand why, then adjust your approach
4. **Catch contradictions** - User said "it's hot" then "it's cold"? Call it out naturally
5. **Reference previous topics** - Use context to provide informed, aware responses

**WHEN CONTEXT IS ENOUGH vs WHEN TO USE TOOLS:**
- Context shows you JUST did something? → Answer from context (no tool call needed)
- Context window too short (only 3 conversations by default)? → Call get_recent_conversations or search_conversations for more history
- Need LIVE/CURRENT data (reminders, alerts, service status)? → ALWAYS use tools, context may be stale
- Context shows a tool FAILED? → Proactively investigate with check_tool_logs and retry with corrected approach
- User says 'curl' or check a private/local IP (192.168.x, 10.x, localhost)? → Use execute_bash, NOT mcp_fetch (which only works for public internet URLs)

**MULTI-PART REQUESTS (e.g., 'do X AND verify Y'):**
- After using tools, explicitly map tool results to EACH part of the user's request
- For verification questions (e.g., 'verify it was saved'), explicitly state whether matching data was found
- Don't give terse responses when user asks for verification - explain what you checked and what you found

**HONESTY ABOUT TOOL LIMITATIONS:**
- If a tool cannot verify something (e.g., can't reach a private network), say so clearly
- NEVER claim success or status when you couldn't actually verify it
- Better to say "I couldn't confirm X because..." than to guess or fabricate

**EXAMPLE - Learning from Failure:**
Context shows: "User asked to install Redis. Tool: execute_bash. Status: FAILED"
You should: Call check_tool_logs → discover "permission denied" → retry with sudo → sudo fails notify user

**EXAMPLE - Avoiding Redundancy:**
Context shows: "User asked Bitcoin price. You replied: $92k. crypto price. Status: SUCCESS"
User now asks: "Did you just check Bitcoin?"
You should: Answer "Yes, Bitcoin is $92k" (NO tool call - use context because it is recent and you just checked it!)

MULTI-TURN CONVERSATIONS:
You can call MULTIPLE tools in sequence to complete complex tasks! After each tool executes:
1. Review the result
2. Decide if you need to call another tool OR if the task is complete
3. If complete, respond with Q&A intent to summarize results to the user
4. If more work needed, call the next tool

CRITICAL - AVOID REDUNDANT TOOL CALLS:
- Do NOT call the same tool multiple times unless explicitly needed
- After ingest_intel succeeds → task is COMPLETE, switch to Q&A
- After **list_reminders/list_alerts** → **MUST follow with Q&A** to summarize results (never stop after list!)
- After search tools (search_memory, semantic_recall) → task is COMPLETE **UNLESS** user's intent requires further action
- **CRITICAL EXCEPTION FOR MEMORY TOOLS**: If a memory search tool returns NO RESULTS, you MUST try a DIFFERENT memory tool:
  - semantic_recall fails → try search_memory (with keywords)
  - search_memory fails → try recall (broader search)
  - This is NOT "calling same tool twice" - it's using DIFFERENT memory search strategies
- **Exception**: "cancel my reminder" = (1) list first, (2) acknowledge, (3) Q&A summary
- Only repeat a tool if user asked for multiple operations or first attempt had wrong parameters or your task explicitly requires it

**MULTI-STEP REMINDER WORKFLOWS:**
- "Cancel my X reminder" → (1) list_reminders to find ID, (2) acknowledge_reminders with that ID
- "Delete my reminder about Y" → (1) list_reminders to find ID, (2) acknowledge_reminders with that ID
- **"What reminders do I have?" / "Show reminders" / "Any pending reminders?"** → (1) list_reminders, (2) **MUST FOLLOW WITH Q&A** summarizing results
  - ✅ CORRECT: Turn 1: list_reminders → Turn 2: Q&A "You have 2 reminders: dinner at 6pm and meeting tomorrow"
  - ❌ WRONG: Turn 1: list_reminders → STOP (never do this!)
- **FUZZY MATCHING**: User says "cancel checkbook reminder" and you see "check for checkbook" in results? THAT'S A MATCH! Look for partial matches in title/description.
- **Always continue to step 2**: After list_reminders returns results with a matching reminder, IMMEDIATELY call acknowledge_reminders with that ID. Don't stop and ask - just do it!

MULTI-TURN PATTERN EXAMPLES:
User: "Do X and save the result"
→ Turn 1: Call action tool (send_webhook, api_call, etc.)
→ Turn 2: Call 'remember' to save important output
→ Turn 3: Q&A response summarizing what was done

User: "Build X then verify it works"
→ Turn 1: Call 'opencode' to build
→ Turn 2: Call verification tool (check_opencode_sessions, execute_bash, api_call, etc.)
→ Turn 3: Q&A response with outcome

SEARCH EFFICIENCY RULES (CRITICAL - AVOID INFINITE LOOPS):
When performing web searches or data gathering:
1. **Evaluate after 2-3 tool calls**: Do you have enough info to answer the user's question?
   - If YES → Stop searching, respond with Q&A
   - If NO → Continue, but be strategic

2. **Stop searching if you encounter repeated failures**:
   - Got 403 errors on 3 websites? Move on, answer with what you found
   - Same results appearing multiple times? You've exhausted available info
   - Searches returning "wrong location" (Sarnia instead of Hillsboro)? Try 1-2 different queries, then answer

3. **Partial answers are BETTER than endless searching**:
   - "Found showtimes for Wicked and Gladiator 2 but couldn't get full list" ✅
   - Better to give 2 good answers than search 10 times for a perfect 3

4. **You have a 10-turn limit**:
   - Turns 1-4: Gather info broadly
   - Turns 5-7: Refine and fill gaps
   - Turns 8-10: You MUST be preparing to answer. Switch to Q&A!

5. **If you're on turn 8+, ASK YOURSELF**: "Can I answer the user's question with what I have?"
   - If answer is YES (even partially) → STOP searching, respond now
   - If answer is NO and more searches won't help (403 errors, bad data) → STOP, explain what you found

VOICE OUTPUT RULES (ABSOLUTELY CRITICAL):
When you respond with Q&A intent (NOT calling a tool), your response will be SPOKEN ALOUD through speakers.

MANDATORY FORMAT:
- MAXIMUM 25 WORDS (hard limit, will be cut off)
- NO emojis, NO markdown (**, ##, bullets)
- NO explanations of process ("I've successfully...", "Here's what I did...")
- STATE ONLY: outcome + essential detail

CORRECT EXAMPLES:
- "Flask server started on localhost port 5000"
- "It's 12:33 AM on November 13th"
- "Bitcoin is $101,000, down 2% today"
- "I found 3 memories about your search"
- "Server is up and running on 192.168.70.228:5000"

WRONG EXAMPLES (TOO VERBOSE):
- "Great! I've successfully started the server. It's now running on port 5000! Is there anything else you need help with?" ❌
- "Perfect! The task is complete. The server has been started and verified. Is there anything else you need help with?" ❌
- "I found the information you requested. Here are the details. Is there anything else you need help with?" ❌

If you need to respond (not call a tool), KEEP IT UNDER 25 WORDS.

PROACTIVE SYSTEM QUERIES (CRITICAL):
⚠️  ONLY check reminders/alerts/services if user EXPLICITLY asks about them with keywords like: reminder, alert, due, scheduled, notification, status, running.

For EXPLICIT questions about REMINDERS, ALERTS, or SERVICE STATUS → call the specific tool, NEVER answer from memory/context:
- "When is my next reminder?" → call 'list_reminders'
- "What reminders do I have?" → call 'list_reminders'
- "Any pending alerts?" → call 'list_alerts'
- "Did I miss any reminders?" → call 'list_reminders'
- "Do I have any reminders?" → call 'list_reminders' (even if you just created one!)
- "What's the status of X service?" → call 'query_service_logs'

❌ DO NOT proactively check reminders/alerts just because:
   - User asks a vague question like "What's up?" or "What should I do?"
   - Previous conversation mentioned reminders
   - You want to be helpful
   
If user doesn't mention reminder/alert/status keywords → DON'T check them!

**WHY**: These systems maintain LIVE STATE that changes independently. Memory/context may be stale. ALWAYS query the current state when explicitly asked.

MEMORY MANAGEMENT (CRITICAL - MUST FOLLOW):
You have persistent memory across conversations. ALWAYS check your memory first before responding!

⚠️  **MEMORY-FIRST RULE (NEVER VIOLATE THIS)**: ⚠️
Before answering ANY question about:
- User's personal info, preferences, or past conversations
- Projects, configurations, servers, or services
- Technical details, credentials, or endpoints
- **ANYTHING the user might have told you before**

YOU MUST:
1. Call semantic_recall (for natural language questions)
2. OR call search_memory (for keyword lookups)
3. Wait for the result
4. THEN respond based on what you found

❌ NEVER say "I don't have X stored" without searching first!
❌ NEVER assume memory is empty without checking!
❌ NEVER use action tools (execute_bash, api_call, query_service_logs) BEFORE checking memory!
✅ ALWAYS search memory FIRST, THEN use action tools if memory has no info
✅ Memory tools are listed FIRST in your tools list for a reason - use them first!
✅ If memory contains an EXACT COMMAND to run (like "curl X.X.X.X:PORT"), USE THAT COMMAND EXACTLY - don't improvise!
✅ Remote servers (other IPs) don't have systemctl access - only check URLs/ports with curl

When to use memory tools:
1. **ALWAYS use 'search_memory' or 'semantic_recall' FIRST** when the user asks "what", "when", "who", "where", "how" questions
   - Use 'semantic_recall' for NATURAL LANGUAGE QUESTIONS (full sentences, 4+ words, uses question words)
   - Use 'search_memory' for simple KEYWORD lookups (1-3 words: project names, topics, concepts)
   - Note: 'search_memory' now uses FTS5 with BM25 ranking - faster and smarter than before
   - Rule of thumb: If it's a sentence/question → semantic_recall. If it's a keyword → search_memory.
   - **CRITICAL FALLBACK**: If semantic_recall returns no results, try search_memory with keywords. If search_memory fails, try recall as last resort.
2. **PROACTIVELY use 'remember'** when you encounter VALUABLE, REUSABLE information:
   
   A. USER SHARES information (obvious cases):
      - Personal info (family, birthdays, relationships)
      - Preferences (favorite places, settings, habits)
      - Important contacts, locations, credentials
   
   B. YOU CREATE/BUILD something (CRITICAL - must save):
      - Project locations and run commands with their paths and execution details
      - URLs, endpoints, ports you just deployed
      - Working solutions (e.g., "Port 8000 was busy, switched to alternate Port 8004 - now works")
      - File paths for projects, configs, scripts you created
   
   C. YOU DISCOVER important facts the user might reference later:
      - Significant events (market records, major announcements)
      - Technical solutions that worked after troubleshooting
      - System configurations that user might need again
   
   D. DO NOT SAVE ephemeral data:
      - Current time (changes every second)
      - Current prices unless significant/requested (Bitcoin at $96k is just noise)
      - Temporary status checks
      - Test URLs to temporary/ephemeral services
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

❌ BAD: User says "Search for X" → You call 'semantic_recall' (overkill for simple keyword)
✅ GOOD: User says "Search for X" → You call 'search_memory' with keyword (FTS5 is fast for this)

❌ BAD: User says "Start the X server" → Searches files, tries random commands
✅ GOOD: User says "Start the X server" → Call 'search_memory' with project name → Use stored run command

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

✅ EXCELLENT: Deploy service on port A → Port busy → Switch to port B → Works → Call 'remember' with deployment details and working port

✅ EXCELLENT: Troubleshoot database connection → Find working connection string → Call 'remember' with "db_connection: postgresql://localhost:5432/mydb worked after installing pg module"

SYSTEM ENVIRONMENT:
- Running on a **headless Ubuntu server** (no GUI/display)
- Do NOT use: xdg-open, webbrowser module, or any GUI tools
- For web servers: Use curl to verify, not browser commands
- User is accessing via SSH/remote terminal

ACTION TOOLS - When the user asks you to perform an ACTION or get REAL-TIME data:
- Use the appropriate tool based on user request
- Tools are dynamically loaded including local tools and MCP servers
- Common patterns: HTTP requests, time queries, price checks, shell commands
- Web access tools available if enabled (search, fetch)

TOOL SELECTION GUIDANCE (From real-world feedback):
1. **TIME QUERIES**: When user asks "what time is it?", "current time", etc. → ALWAYS use get_time tool
   - Even though current date/time is in system prompt, user EXPECTS you to use the tool
   - The system prompt time is for reasoning; explicit time questions need tool verification

2. **NEWS vs FACTS**: News search tools are for recent events, breaking news, current affairs.
   - For official statistics (unemployment rate, economic data, exchange rates) → use fetch with official government sources (bls.gov, treasury.gov, etc.) after one search identifies the authoritative source
   - News articles may contain outdated or incomplete statistical data

3. **MUSIC PLAYBACK**: If user asks to "play music", "put on jazz", "play a playlist":
   - Be HONEST: You cannot directly control music playback on streaming services
   - Offer alternatives: "I can't control your music apps directly. I can search for playlist recommendations or song suggestions for you to play manually."
   - Do NOT pretend to play music or hallucinate success

4. **IMAGE SEARCH**: Image search tools return VISUAL content only.
   - For factual data, nutritional info, text-based answers → use web search instead
   - Image search for: photos, pictures, visual inspiration, design ideas

5. **MEMORY vs EXTERNAL**: search_memory and semantic_recall search YOUR stored knowledge about the user.
   - For external facts (capital cities, historical events, general knowledge) → use web search
   - For user-specific data (their preferences, past conversations, saved info) → use memory tools

OPENCODE - For complex development, coding, or building tasks:
- **Use 'opencode' tool** when user says: "use OpenCode", "build", "create app", "develop", "code", "make website"
- OpenCode handles: coding, building projects, creating files, deploying, complex multi-step tasks
- **OpenCode workspace**: ~/jarvis-workspace/projects/ (all builds go here, NOT in ~/jarvis-voice/)
- **Finding OpenCode projects**: Use bash to list ~/jarvis-workspace/projects/
- **Port selection**: Use NON-STANDARD ports (8091+) to avoid conflicts. Common ports like 8080, 8000, 5000 are often busy. Start at 8091 and increment if needed.
- **CRITICAL - Single OpenCode Call**: Call OpenCode ONCE per user request. Don't call it again to verify or add features - that wastes tokens. If you need to verify/test, use execute_bash or api_call AFTER the build, not another OpenCode session.
- **OpenCode is SLOW (this is normal)**: Building projects takes TIME - simple apps take 30-60s, complex projects can take 2-5+ minutes. This is NOT an error. OpenCode timeout is 6 minutes. Be patient and wait for the tool to complete. Do NOT assume it failed just because it's taking time.
- Patterns:
  * "Build a small [type] application" → Use opencode tool ONCE (wait 30-60s+), then test if needed or no reply from opencode use check_opencode_sessions for more information it could still be building.
  * "Create a complex [game/app]" → Use opencode tool ONCE (wait 1-2 minutes), then test if needed or no reply from opencode use check_opencode_sessions for more information it could still be building.
  * "Start the [project] server" → Search memory for run command first, then execute_bash (NO OpenCode needed)

**DOCUMENT vs SOFTWARE** - Read tool descriptions carefully:
- "Create a PDF/report/document" → Check for pdf_create or stash tools (NOT opencode)
- "Build an app/website/API" → Use opencode
- Tool descriptions have "Use when" and "Do NOT use for" guidance - follow them!

ERROR RECOVERY: If a tool fails, you can:
1. Use check_tool_logs to see what went wrong
2. Retry with corrected parameters based on the error
3. Try a different approach

Only respond conversationally for general knowledge questions, jokes, explanations, or conversation.

Be decisive and proactive - remember what's important, use tools when needed, chain multiple tools to complete complex tasks."""
    
    @property
    def system_prompt(self) -> str:
        """
        Dynamic system prompt with current date/time prepended.
        
        This ensures the LLM knows the CURRENT date/time for:
        - Web searches (use correct year, not training cutoff)
        - Temporal context ("recent", "latest", "this week")
        - Time-sensitive queries ("tomorrow", "next Friday")
        """
        now = datetime.now(self.timezone)
        
        # Get response style - this affects output formatting rules
        response_style = get_config_value('JARVIS_RESPONSE_STYLE', 'casual').lower()
        
        # Build style-aware prefix
        if response_style == 'detailed':
            style_note = """
RESPONSE STYLE: DETAILED (for display/reading - NOT voice synthesis)
- Output will be DISPLAYED, not spoken through TTS
- Markdown formatting IS allowed (links, bold, lists)
- Full URLs with markdown links ARE allowed: [Title](https://...)
- No word limit - provide comprehensive information
- The VOICE OUTPUT RULES section does NOT apply in detailed mode

"""
        else:
            style_note = f"""
RESPONSE STYLE: {response_style.upper()}
- Keep voice output brief (~25 words), no URLs for speech
- The VOICE OUTPUT RULES section applies fully

"""
        
        # Check for native search capabilities
        native_search_note = ""
        xai_search = get_config_value("XAI_SEARCH", "false").lower() == "true"
        anthropic_search = get_config_value("ANTHROPIC_SEARCH", "false").lower() == "true"
        provider_type = self._provider_override or get_config_value("LLM_PROVIDER", "")
        
        if xai_search and provider_type == "xai":
            native_search_note = """
NATIVE SEARCH ENABLED:
You have built-in real-time web/X search. For current info, news, prices, events:
- Use your NATIVE SEARCH (automatic) - DO NOT use mcp_fetch, brave_search, or other external search tools
- Your search results are grounded and cited automatically
- Only use external tools when native search is insufficient or for non-search tasks
"""
        elif anthropic_search and provider_type == "anthropic":
            native_search_note = """
NATIVE SEARCH ENABLED:
You have built-in web search capability. For current info, news, prices, events:
- Use your NATIVE SEARCH - DO NOT use mcp_fetch, brave_search, or other external search tools
- Only use external tools when native search is insufficient or for non-search tasks
"""
        
        time_prefix = f"""CURRENT DATE AND TIME:
Today is {now.strftime('%A, %B %d, %Y')} at {now.strftime('%I:%M %p %Z')}.
Use this for any time-sensitive queries, web searches, or temporal references.
When searching the web, if needed use the CURRENT YEAR ({now.year}) not past years.
{native_search_note}{style_note}"""
        return time_prefix + self._system_prompt_base
    
    def _create_provider(self):
        """Create appropriate LLM provider based on config or overrides."""
        # Use override if provided, otherwise fall back to config
        provider_type = self._provider_override or get_config_value("LLM_PROVIDER", "openai" if self.mode == "cloud" else "ollama")
        
        if provider_type == "openai":
            model = self._model_override or get_config_value("OPENAI_MODEL", "gpt-5-mini-2025-08-07")
            return create_provider(
                "openai",
                api_key=get_config_value("OPENAI_API_KEY"),
                model=model
            )
        elif provider_type == "anthropic":
            model = self._model_override or get_config_value("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
            return create_provider(
                "anthropic",
                api_key=get_config_value("ANTHROPIC_API_KEY"),
                model=model
            )
        elif provider_type == "xai":
            model = self._model_override or get_config_value("XAI_MODEL", "grok-4-1-fast-non-reasoning-latest")
            return create_provider(
                "xai",
                api_key=get_config_value("XAI_API_KEY"),
                model=model
            )
        elif provider_type == "ollama":
            model = self._model_override or get_config_value("OLLAMA_MODEL", "qwen3")
            return create_provider(
                "ollama",
                base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434"),
                model=model
            )
        else:
            raise ValueError(f"Unknown LLM provider: {provider_type}")
    
    def route(self, transcript: str, excluded_tools: list = None) -> Dict[str, Any]:
        """
        Use LLM to determine intent and route appropriately.
        
        Args:
            transcript: User's transcribed speech
            excluded_tools: Optional list of tool names to exclude from selection
            
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
        self._excluded_tools = excluded_tools or []
        
        # Only print if in interactive mode
        if sys.stdout.isatty():
            print(f"🧠 Routing with LLM: '{transcript}'")
        
        # DYNAMIC TOOL RETRIEVAL (The "Tool RAG" System)
        # Instead of loading all tools, we find only the relevant ones
        
        # 1. Determine retrieval limit based on mode
        # Local models (Ollama) have smaller context, so we serve fewer tools
        # Cloud models (Claude/GPT) can handle more choices
        retrieval_limit = 5 if self.mode == 'local' else 15
        
        # 2. Extract the actual user query (remove auto-context if present)
        # Auto-context prepends "=== RECENT CONVERSATION HISTORY ===" which dilutes tool search
        tool_search_query = transcript
        if "=== RECENT CONVERSATION HISTORY ===" in transcript and "Instructions:" in transcript:
            # The actual query is between the last conversation exchange and "Instructions:"
            # Find it by working backwards from "Instructions:"
            before_instructions = transcript.split("Instructions:")[0]
            lines = before_instructions.split('\n')
            # Work backwards to find the first non-empty line that's not part of the context metadata
            for line in reversed(lines):
                line = line.strip()
                if line and not line.startswith('[') and not line.startswith('User:') and \
                   not line.startswith('Assistant:') and not line.startswith('Tools used:') and \
                   not line.startswith('Status:') and not line.startswith('===') and \
                   not line.startswith('Last ') and not line.startswith('Model:') and \
                   not line.startswith('Cost:') and 'conversation(s)' not in line:
                    # This is the user query
                    tool_search_query = line
                    break
        
        # 3. Find relevant tools using vector search
        # This returns ToolSchema objects for the top matches + ghost tools
        relevant_tools = self.registry.find_tools(tool_search_query, limit=retrieval_limit)
        
        # Filter out excluded tools (e.g., tools blocked for web mode)
        if self._excluded_tools:
            original_count = len(relevant_tools)
            relevant_tools = [t for t in relevant_tools if t.name not in self._excluded_tools]
            if len(relevant_tools) < original_count:
                excluded = set(self._excluded_tools) & set(t.name for t in self.registry.find_tools(tool_search_query, limit=retrieval_limit))
                if sys.stdout.isatty():
                    print(f"   🚫 Excluded tools: {', '.join(excluded)}")
        
        # Separate ghost tools from retrieved tools for visibility
        from config_loader import get_config_value
        ghost_tools_str = get_config_value('GHOST_TOOLS', 'search_memory,semantic_recall,remember,check_tool_logs,get_recent_conversations,get_time')
        ghost_list = [t.strip() for t in ghost_tools_str.split(',')]
        
        tool_names = [t.name for t in relevant_tools]
        retrieved = [name for name in tool_names if name not in ghost_list]
        ghosts = [name for name in tool_names if name in ghost_list]
        
        if sys.stdout.isatty():
            print(f"📚 Loaded {len(tool_names)} tools ({len(retrieved)} retrieved + {len(ghosts)} ghost)")
            if retrieved:
                print(f"   Retrieved: {', '.join(retrieved)}")
            if ghosts:
                print(f"   👻 Ghost: {', '.join(ghosts)}")
        
        # ALWAYS log tool retrieval details for debugging
        import logging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        logger.info(f"[TOOL_RAG] Tool search query: {tool_search_query}")
        logger.info(f"[TOOL_RAG] Retrieved {len(retrieved)} tools: {retrieved}")
        logger.info(f"[TOOL_RAG] Ghost tools: {ghosts}")
        logger.info(f"[TOOL_RAG] Total tools sent to LLM: {len(tool_names)}")
        
        # 3. Convert to provider-specific format
        if hasattr(self.provider, '__class__') and 'Anthropic' in self.provider.__class__.__name__:
            tools = [t.to_anthropic_format() for t in relevant_tools]
        else:
            tools = [t.to_openai_format() for t in relevant_tools]
        
        # For Ollama, convert to Anthropic-like format (simpler)
        if hasattr(self.provider, '__class__') and 'Ollama' in self.provider.__class__.__name__:
            tools = [t.to_anthropic_format() for t in relevant_tools]
        
        # Send to LLM
        messages = [{"role": "user", "content": transcript}]
        
        try:
            # Check if thinking mode is enabled
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
            from thinking import should_enable_thinking
            enable_thinking = should_enable_thinking()
            
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Router calling provider.chat_with_tools (thinking={enable_thinking})", file=sys.stderr)
            
            # Track LLM call timing
            import time
            llm_start_time = time.time()
            
            text_response, tool_call, usage_info, thinking = self.provider.chat_with_tools(
                messages=messages,
                tools=tools,
                system_prompt=self.system_prompt,
                enable_thinking=enable_thinking
            )
            
            llm_duration_ms = (time.time() - llm_start_time) * 1000
            
            # Log LLM call for monitoring
            try:
                from llm_logger import get_logger
                llm_logger = get_logger(self.mode)
                llm_logger.log_llm_call(
                    provider=self.provider_type,
                    model=self.model_name,
                    prompt_type="routing",
                    messages=messages,
                    response_text=text_response,
                    tool_call=tool_call,
                    usage_info=usage_info,
                    thinking=thinking,
                    duration_ms=llm_duration_ms,
                    mode=self.mode,
                    user_query=transcript
                )
            except Exception as e:
                if os.environ.get('JARVIS_DEBUG'):
                    print(f"DEBUG: Failed to log LLM call: {e}", file=sys.stderr)
            
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Provider returned: tool_call={tool_call is not None}, usage={usage_info is not None}, thinking={thinking is not None}", file=sys.stderr)
            
            # Tool was called
            if tool_call:
                response = {
                    "intent": "tool",
                    "tool_name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                    "confidence": 1.0,
                    "usage_info": usage_info,  # Include token/cost data
                    "available_tools": tool_names  # Tools shown to LLM for reflection
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
                    "usage_info": usage_info,  # Include token/cost data
                    "available_tools": tool_names  # Tools shown to LLM for reflection
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

