#!/usr/bin/env python3
"""
Jarvis Voice Assistant - LLM-Based Router (v2)
Uses native tool calling from OpenAI/Anthropic/Ollama to intelligently route requests.
"""
import os
import sys
from typing import Any
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value, get_float
from model_catalog import get_provider_fallback_model
from model_prompt_overrides import load_model_prompt_override, apply_prompt_override_sections
from tool_schema import ToolRegistry
from llm_provider import create_provider


def _tool_rag_similarity_threshold(transcript: str, tool_search_query: str) -> float:
    """
    When the full routing string is embedded for Tool RAG (no strip to a short user line),
    optionally use TOOL_SIMILARITY_THRESHOLD_FULL; if unset or empty, use TOOL_SIMILARITY_THRESHOLD
    for both paths.
    """
    base = get_float('TOOL_SIMILARITY_THRESHOLD', 0.0)
    if tool_search_query != transcript:
        return base
    raw = get_config_value('TOOL_SIMILARITY_THRESHOLD_FULL', None)
    if raw is None or str(raw).strip() == '':
        return base
    try:
        return float(raw)
    except (ValueError, TypeError):
        return base


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
        self.prompt_override = load_model_prompt_override(
            provider=self.provider_type,
            model=self.model_name,
            mode=self.mode,
        )
        
        # Timezone for timestamps (configurable via env)
        self.timezone = ZoneInfo(get_config_value("JARVIS_TIMEZONE", "America/Los_Angeles"))
        
        # System prompt for routing (base prompt - time is prepended dynamically)
        self._system_prompt_base = """You are Jarvis, an AI assistant with access to tools AND persistent memory.

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
- User says 'curl' or check a private/local IP (192.168.x, 10.x, localhost)? → Use execute_bash, NOT mcp_fetch_fetch (which only works for public internet URLs)
- **LOCAL vs REMOTE**: execute_bash = runs on THIS local machine only. ssh_remote = runs on configured remote hosts (VPS, servers). Check tool description for available hosts.

**MULTI-PART REQUESTS (e.g., 'do X AND verify Y'):**
- After using tools, explicitly map tool results to EACH part of the user's request
- For verification questions (e.g., 'verify it was saved'), explicitly state whether matching data was found
- Don't give terse responses when user asks for verification - explain what you checked and what you found

**HONESTY ABOUT TOOL LIMITATIONS:**
- If a tool cannot verify something (e.g., can't reach a private network), say so clearly
- NEVER claim success or status when you couldn't actually verify it
- Better to say "I couldn't confirm X because..." than to guess or fabricate
- NEVER say "check canvas" or imply content was saved/updated unless you actually called the canvas tool in this turn and got success
- If a user asks for a range the tool cannot provide (e.g., true 7-day weather), explicitly say the limit and offer the closest available result

FRESHNESS & FLEXIBILITY RULES (HIGH PRIORITY):
- In multi-turn context, freshness metadata (executed_at, age, ttl, expires_in, authoritative_live) determines what is current.
- Prefer the newest authoritative_live tool result for live-data questions (prices, weather now, current status).
- If a fresh result for the same target already exists and user did NOT ask to refresh/recheck, respond directly instead of re-calling the same tool.
- Treat old memory/stash snapshots as historical context, not live truth, when they conflict with fresh tool output.
- For price-like data, memory older than 60 minutes is usually stale for "right now" queries.
- IMPORTANT FLEXIBILITY: If user explicitly asks for history/comparison/trends ("last week", "yesterday vs now", "compare to January"), use historical memory/intel and additional tools as needed. Do NOT force a live-only answer.
- IMPORTANT FLEXIBILITY: If user explicitly asks to refresh/re-run/recheck, a repeat tool call is allowed.

**WHEN A TOOL FAILS OR GIVES UNEXPECTED RESULTS:**
- Do NOT blindly retry with different parameters. First consider: is this a known API limitation?
- If the result doesn't match what you requested (wrong duration, size, format), it may be a provider constraint, not an error. Inform the user instead of retrying.
- If genuinely uncertain, use search_memory to check for known limitations before retrying. Your memory contains tool-specific knowledge about provider quirks and common pitfalls.
- Expensive generation tools (video, image, music) should not be called more than once per request unless the user explicitly asks to try again.
- **SAVE CRITICAL LESSONS**: If you discover a new tool limitation or provider quirk that is NOT already in your memory, save it for future sessions using manage_intel with action=append, path=jarvis-learned-lessons.md, auto_ingest=true. Keep entries short: "- **Topic**: Lesson". Only save genuinely new, reusable operational knowledge — not one-off errors, wording cleanups, or tighten-only rewrites.

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
- **Duplicate guard (this request)**: After a tool **succeeds**, the system **blocks** calling it again with the **same arguments**—use the result you already have, **a different tool**, or Q&A; never duplicate a success to "verify". Retrying after **failure**, user-requested refresh/recheck, or **different** args is fine.
- **EXCEPTION**: Multi-step workflows defined below (reminder cancel, research→canvas, memory fallback) are NOT redundant
- After ingest_intel succeeds → task is COMPLETE, switch to Q&A
- After **list_reminders/list_alerts** → MUST follow with Q&A (see REMINDER & ALERT RULES below)
- After search tools (search_memory, semantic_recall) → task is COMPLETE **UNLESS** user's intent requires further action
- **AFTER CANVAS** → verbally summarize key findings in Q&A, then STOP (no more searches!)
  - ✅ CORRECT: canvas → Q&A "Top 3 cameras are X, Y, Z. Full comparison saved to Canvas."
  - ❌ WRONG: canvas → search again → canvas again (use stash for intermediate data BEFORE canvas!)
  - Exception: ONE canvas update allowed ONLY if you find a genuinely new data source (different website, API, or document type) that significantly changes your answer. Same-site or minor additions = NO update.
- **MEMORY TOOL EXCEPTION (MAX 2 attempts)**: If first memory tool returns NO RESULTS, try ONE other:
  - semantic_recall fails → try search_memory with keywords
  - search_memory fails → try semantic_recall with rephrased query
  - After 2 attempts with no results → proceed to action tools if the task needs them, OR tell user "I don't have that stored"
- Only repeat a tool if user asked for multiple operations or first attempt had wrong parameters or your task explicitly requires it

**REMINDER & ALERT RULES (CONSOLIDATED):**

⚠️ Reminders and alerts are LIVE STATE. If you called list_reminders/list_alerts in the last 2-3 turns of THIS conversation, you may reference that result. Otherwise, ALWAYS call the tool - don't guess from old context.

**When to call these tools:**
- "What reminders do I have?" / "Any pending alerts?" / "Check reminders" → call list_reminders or list_alerts
- "Cancel/delete my X reminder" → acknowledge_reminders with title_search="X" (it does fuzzy matching)
- "Clear all alerts" → acknowledge_alerts with clear_all=true
- "Did I miss any reminders?" → list_reminders (even if you just created one!)
- New reminder creation → prefer ONE create_reminder call using the user's natural phrasing
  - For bounded daily spans like "every day for 5 days" or "every day the next 2 weeks", do NOT split into separate one-time and recurring reminders unless the user explicitly asks for separate reminders.

**Workflows:**
- **List reminders/alerts** → MUST follow with Q&A summarizing results
  - ✅ CORRECT: list_reminders → Q&A "You have 2 reminders: dinner at 6pm and meeting tomorrow"
  - ❌ WRONG: list_reminders → STOP (never end after listing!)
- **Cancel specific reminder** → Use acknowledge_reminders with title_search parameter (fuzzy matches)
  - "Cancel checkbook reminder" → acknowledge_reminders(title_search="checkbook") matches "check for checkbook"
  - Tool returns error if multiple matches - ask user to be more specific
- **Cancel by ID** → If you have the ID, use acknowledge_reminders(reminder_ids=[ID])

**DO NOT proactively check reminders/alerts unless user explicitly asks!**
- User says "What's up?" → DON'T check reminders (too vague)
- User says "Any reminders?" → DO check (explicit keyword)

MULTI-TURN PATTERN EXAMPLES:
User: "Do X and save the result"
→ Turn 1: Call action tool (send_webhook, api_call, etc.)
→ Turn 2: Call 'remember' to save important output
→ Turn 3: Q&A response summarizing what was done

User: "Build X then verify it works"
→ Turn 1: Call 'opencode' to build
→ Turn 2: Only if the user explicitly asked for verification, call a real verification tool (execute_bash, api_call, etc.)
→ Turn 3: Q&A response with outcome

**RESEARCH → OUTPUT WORKFLOW (CRITICAL):**
When user asks you to research something and create output (canvas, email, etc.):
1. **GATHER SUFFICIENT DATA** - diverse searches/crawls until you can answer comprehensively
   - Stop criteria: repeated results, multiple 403 errors, or enough info to answer
2. **Use stash for large data** - Save intermediate results to stash if needed
3. **CREATE OUTPUT LAST** - Canvas/email should be the FINAL step with ALL gathered data
4. **AFTER CANVAS → Q&A SUMMARY** - Verbally summarize key findings and STOP
   - Exception: ONE update allowed ONLY if new source type (different domain/format) significantly changes the answer

❌ WRONG: search → canvas → search → crawl → done (canvas only has first search, no summary!)
❌ WRONG: search → crawl → canvas → STOP (user gets no verbal summary!)
❌ WRONG: search → canvas → same search again with same query (duplicate/loop!)
✅ RIGHT: search → search → crawl → canvas → Q&A "Here's what I found: X, Y, Z. Full details in Canvas."
✅ ALSO OK: search → canvas → crawl (new source) → canvas UPDATE → Q&A summary

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

4. **Watch for turn limit warnings**:
   - Context will show `[Turn X/Y]` - that's your current turn out of max
   - When you see "X turns remaining" warnings, prioritize finishing critical tasks
   - Final turns: Switch to Q&A! Save canvas/memory BEFORE you run out

5. **When turns are running low, ASK YOURSELF**: "Can I answer the user's question with what I have?"
   - If answer is YES (even partially) → STOP searching, respond now
   - If answer is NO and more searches won't help (403 errors, bad data) → STOP, explain what you found

VOICE OUTPUT RULES (ABSOLUTELY CRITICAL):
When you respond with Q&A intent (NOT calling a tool), your response could be SPOKEN ALOUD through speakers.
If the runtime prefix above says RESPONSE STYLE: DETAILED, skip this entire section for that turn—follow the DETAILED rules instead.

MANDATORY FORMAT (skip entirely when RESPONSE STYLE is DETAILED—see runtime prefix):
- Tool confirmations: MAX 35 WORDS (action completed, result)—voice/casual/auto only
- Q&A/informational responses: follow the CURRENT configured Q&A word limit from the runtime config
- NO emojis, NO markdown (**, ##, bullets)
- NO greeting fluff ("Great!", "Perfect!", "I've successfully...")
- Get straight to the answer

⚠️ ABSOLUTELY FORBIDDEN - META-LEVEL RESPONSES:
- NEVER say "I've completed the task using X tools" - that tells user NOTHING
- NEVER say "I used canvas and search" without summarizing WHAT was found
- NEVER end with just tool names - ALWAYS synthesize actual findings
- If you saved to Canvas, SUMMARIZE the key findings verbally + mention Canvas has details

CORRECT EXAMPLES (tool confirmations - keep brief):
- "Flask server started on localhost port 5000"
- "It's 12:33 AM on November 13th"
- "Bitcoin is $101,000, down 2% today"

CORRECT EXAMPLES (Q&A/info - can be more detailed):
- "Ntfy is an open-source push notification service. Self-hosted setup needs TLS for iOS. Without HTTPS, the app falls back to battery-draining polling. Use Caddy for auto-TLS certificates."
- "Your Flask project is at ~/jarvis-workspace/flask-api. It uses SQLite for the database and runs on port 8091. The main entry point is app.py."

CORRECT EXAMPLES (after research + Canvas):
- "Top no-subscription cameras: Reolink E1 Pro at $45, Wyze V3 at $35, Eufy 2K at $50. All support local storage and iOS apps. Full comparison saved to Canvas."
- "Found 3 options meeting your criteria. Best overall is the Reolink with 4MP and 2-way audio. Details and Amazon links saved to Canvas."

WRONG EXAMPLES (verbose fluff):
- "Great! I've successfully started the server. It's now running on port 5000! Is there anything else?" ❌
- "Perfect! Let me explain what I did for you..." ❌

WRONG EXAMPLES (meta-level - NEVER DO THIS):
- "I've completed the task using 2 tools: canvas, brave_search." ❌ (says nothing about actual results!)
- "Task complete. Used search and canvas tools." ❌ (user asked a question - ANSWER IT!)

PROACTIVE SYSTEM QUERIES:
⚠️  ONLY check reminders/alerts/services if user EXPLICITLY asks with keywords: reminder, alert, due, scheduled, notification, status.

- Reminders/Alerts → See "REMINDER & ALERT RULES" section above (LIVE STATE - never answer from memory!)
- Service status → call 'query_service_logs'

❌ DON'T proactively check for vague questions like "What's up?" - only if user explicitly mentions these keywords.

MEMORY MANAGEMENT (CRITICAL - MUST FOLLOW):
You have persistent memory across conversations. ALWAYS check your memory first before responding!

⚠️  **MEMORY-FIRST RULE (NEVER VIOLATE THIS)**: ⚠️
Before answering ANY question about:
- User's personal info, preferences, or past conversations
- Projects, configurations, servers, or services
- Technical details, credentials, or endpoints
- **ANYTHING the user might have told you before**

**EXCEPTIONS (skip memory, call dedicated tool directly):**
- Reminders/Alerts → see "REMINDER & ALERT RULES" section (live state)
- Service status → call query_service_logs (live state)
- Time/date queries → call get_time (always current)

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
   - Use 'semantic_recall' for questions about MEANING/CONTEXT (e.g., "How is my server configured?", "What did I say about cameras?")
   - Use 'search_memory' for direct ENTITY lookups (e.g., "Flask", "Bitcoin", "my VPN", project names)
   - Note: 'search_memory' uses FTS5 with BM25 - fast and smart for keywords
   - **Rule**: If asking about relationships/context → semantic_recall. If looking up a specific thing → search_memory.
   - **FALLBACK (MAX 2 attempts)**: If first memory tool returns no results, try the OTHER memory tool once. Do NOT try a third tool - proceed with action tools or say you don't have that info.
2. **PROACTIVELY use 'remember'** when you encounter VALUABLE, REUSABLE information:
   
   A. USER SHARES information (obvious cases - ALWAYS remember these):
      - "From now on call me X" / "Call me sir" / "Address me as Y" → category: preference, key: how_to_address_user
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

**Image Re-Analysis (follow-up questions about uploaded image):**
❌ BAD: User corrects vision result or asks "look again" → analyze_image with image="1" or "image ID 1" (fails)
✅ GOOD: Use stash_ref from uploaded_image in context: analyze_image with image="stash://space_id/file_id"

**Intelligent Auto-Save (Critical for YOU CREATE/BUILD scenarios):**
❌ BAD: Build project with OpenCode → Build succeeds → Respond "Done" → DON'T save location/run command
✅ GOOD: Build project with OpenCode → Build succeeds → Call 'remember' with project location, port, run command → Respond "Done"

❌ BAD: "What's Bitcoin price?" → Get $96k → Respond → Save price (NO! ephemeral data)
✅ GOOD: "What's Bitcoin price?" → Get $96k → Respond → Don't save (correct - this changes constantly)

❌ BAD: User says "Send webhook and save URL" → Only send_webhook → Don't save
✅ GOOD: User says "Send webhook and save URL" → Call send_webhook → Call remember with URL → Respond "Done!"

✅ EXCELLENT: Deploy service on port A → Port busy → Switch to port B → Works → Call 'remember' with deployment details and working port

✅ EXCELLENT: Troubleshoot database connection → Find working connection string → Call 'remember' with "db_connection: postgresql://localhost:5432/mydb worked after installing pg module"

**Addressing/Preferences (CRITICAL - always remember):**
❌ BAD: User says "From now on, call me sir" → Acknowledge but don't save
✅ GOOD: User says "From now on, call me sir" → Call 'remember' with category=preference, key=how_to_address_user, value="call me sir", importance=8
✅ GOOD: User says "Address me as Captain" → Call 'remember' immediately - this applies to ALL future chats
❌ BAD: User says "Forget calling me sir" / "Stop calling me X" → Call 'remember' with value="no preference"
✅ GOOD: User says "Forget calling me sir" / "Don't call me that anymore" → Call 'forget' with search_query="call me sir" or "how_to_address_user" to remove the memory

SYSTEM ENVIRONMENT:
- Running on a **headless Ubuntu server** (no GUI/display)
- Do NOT use: xdg-open, webbrowser module, or any GUI tools
- For web servers: Use curl to verify, not browser commands
- User is accessing via SSH/remote terminal or custom webui (browser)

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
   - Use the `spotify` tool with action=play query="jazz" (or similar)
   - Spotify requires prior auth via ./bin/spotify-auth - if auth fails, inform user
   - For AI-generated music ("create a song", "make a beat", "compose") → use `generate_music` (ElevenLabs)
   - Do NOT use web search to "play music" - that only finds info, not controls playback

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
- **check_opencode_sessions is fallback-only**: Use it only when OpenCode produced NO usable final result, timed out, or the user explicitly asks about session status/logs. Do NOT call it after a successful OpenCode build reply.
- **OpenCode is SLOW (this is normal)**: Building projects takes TIME - simple apps take 30-60s, complex projects can take 2-5+ minutes. This is NOT an error. OpenCode timeout is 6 minutes. Be patient and wait for the tool to complete. Do NOT assume it failed just because it's taking time.
- Patterns:
  * "Build a small [type] application" → Use opencode tool ONCE, wait for its result, then answer from that result. Only if opencode returns no usable completion may you call check_opencode_sessions for status.
  * "Create a complex [game/app]" → Use opencode tool ONCE, wait for its result, then answer from that result. Only if opencode returns no usable completion may you call check_opencode_sessions for status.
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
        qa_word_limit = int(get_config_value('JARVIS_QA_WORD_LIMIT', '150'))
        multi_turn_word_limit = int(get_config_value('JARVIS_MULTI_TURN_WORD_LIMIT', '150'))
        tool_confirmation_limit = 35
        
        # Build style-aware prefix
        if response_style == 'detailed':
            style_note = """
RESPONSE STYLE: DETAILED (for display/reading - NOT voice synthesis)
- Output will be DISPLAYED, not spoken through TTS
- Markdown formatting IS allowed (links, bold, lists)
- Full URLs with markdown links ARE allowed: [Title](https://...)
- No word limit - provide comprehensive information
- The VOICE OUTPUT RULES section does NOT apply in detailed mode
- For code, commands, config, or multi-line examples: keep headings/explanations OUTSIDE the fence and put only executable/code content inside fenced blocks
- Use fenced code blocks with a language tag when possible: ```bash, ```python, ```json, ```yaml, ```text
- Leave a blank line before and after each fenced block, and always close the fence correctly
- Prefer `##` or `###` section headings in chat responses; reserve top-level `#` for full document-style outputs
- Do not escape backticks unless you are literally explaining markdown syntax
- STRUCTURED TOOL OUTPUT (any tool): If the tool returned JSON with multiple items (arrays such as `results`, `items`, `candidates`, or similar), expand them in the chat: one section per element, same order, using the fields present in each object (markdown links where URLs exist). The chat message is the deliverable—do not substitute a teaser plus "see the tool result", "full output", or the provider name. Do not collapse tail items into ranges like "2–5" or "additional results" unless the user asked for a short summary only. If a field is missing in the payload, say so briefly or omit it—do not invent placeholder text.

"""
        else:
            style_note = f"""
RESPONSE STYLE: {response_style.upper()}
- Keep voice output concise using the CURRENT configured runtime limits
- Tool confirmations: brief ({tool_confirmation_limit} words max)
- Q&A/informational: up to {qa_word_limit} words max
- Multi-turn summaries: up to {multi_turn_word_limit} words max
- No URLs for speech unless critical

"""
        
        # Check for native search/tool capabilities
        native_search_note = ""
        xai_search = get_config_value("XAI_SEARCH", "false").lower() == "true"
        xai_code_exec = get_config_value("XAI_CODE_EXECUTION", "true").lower() == "true"
        xai_image_understanding = get_config_value("XAI_IMAGE_UNDERSTANDING", "true").lower() == "true"
        xai_video_understanding = get_config_value("XAI_VIDEO_UNDERSTANDING", "true").lower() == "true"
        anthropic_search = get_config_value("ANTHROPIC_SEARCH", "false").lower() == "true"
        provider_type = self._provider_override or get_config_value("LLM_PROVIDER", "")
        
        if xai_search and provider_type == "xai":
            # Build xAI capabilities note
            capabilities = []
            capabilities.append("- NATIVE WEB/X SEARCH: Use for current info, news, prices - DO NOT use brave_search or mcp_fetch_fetch (crawl_url is OK for specific URL extraction)")

            if xai_image_understanding:
                capabilities.append(
                    "- NATIVE IMAGE UNDERSTANDING: Search can inspect images encountered during web/X browsing via xAI's native view_image capability"
                )

            if xai_video_understanding:
                capabilities.append(
                    "- NATIVE VIDEO UNDERSTANDING: X search can inspect videos in posts when needed"
                )
            
            if xai_code_exec:
                capabilities.append("""- NATIVE CODE EXECUTION: You have a Python REPL (numpy, pandas, sympy, scipy, matplotlib).
  For complex math, data analysis, or verification: write and run Python code directly.
  Can chain with search: "search for data, then analyze programmatically"
  Use code execution for any math beyond trivial""")
            
            native_search_note = f"""
NATIVE SERVER-SIDE TOOLS ENABLED:
{chr(10).join(capabilities)}
- Results are grounded and cited automatically
- Only use external tools when native capabilities are insufficient
"""
        elif anthropic_search and provider_type == "anthropic":
            native_search_note = """
WEB SEARCH TOOL ENABLED:
You have a special 'web_search' tool for real-time web queries. Use it for current info, news, prices, events.
- Prefer web_search over mcp_fetch_fetch, brave_search, or other external search tools
- crawl_url is OK for extracting content from specific URLs (that's URL extraction, not search)
- web_search is server-side and fast - use it freely for web queries
"""
        else:
            # OpenAI, Ollama, or native search disabled - need external tools for web search
            native_search_note = """
NO NATIVE WEB SEARCH:
For current info, news, prices, events - use external search tools from your available tools:
- brave_search tools (if available) for web queries
- mcp_fetch_fetch (if available) for fetching specific URLs
- crawl_url (if available) for extracting content from URLs
"""
        
        # TODO: Time prefix will mess up provider token caching need better strategy for this
        now_utc = datetime.now(ZoneInfo("UTC"))
        time_prefix = f"""CURRENT DATE AND TIME:
Local: {now.strftime('%A, %B %d, %Y')} at {now.strftime('%I:%M %p %Z')}
UTC:   {now_utc.strftime('%A, %B %d, %Y')} at {now_utc.strftime('%H:%M UTC')}
Database times are stored in UTC. Convert to local time when presenting to the user.
Use this for any time-sensitive queries, web searches, or temporal references.
When searching the web, if needed use the CURRENT YEAR ({now.year}) not past years.
{native_search_note}{style_note}"""
        # Default location for weather/location queries only - never override user-specified locations
        location_block = ""
        default_loc = get_config_value("JARVIS_DEFAULT_LOCATION", "").strip()
        if default_loc:
            location_block = f"""

DEFAULT LOCATION (weather and location-based queries only):
When the user asks for weather or location-based info WITHOUT specifying a place, use: "{default_loc}"
Do NOT use this when the user specifies a different location (e.g. "weather in Seattle" → use Seattle).
Time and timezone use JARVIS_TIMEZONE - this is separate."""
        # Time-of-day personal touch for new conversations (first message, new chat)
        greeting_hint = ""
        hour = now.hour
        if hour >= 22 or hour < 7:
            if hour >= 22:
                time_context = "late night (10pm–midnight)"
            else:
                time_context = "early morning (12am–7am)"
            greeting_hint = f"""

PERSONAL TOUCH (new conversations only):
When this appears to be the start of a fresh conversation, you may add a brief time-aware greeting before the main response. Current time: {time_context}. Use your own phrasing—e.g. working late, early bird—one short natural phrase. Skip if continuing an existing conversation."""
        base_prompt = time_prefix + location_block + greeting_hint + self._system_prompt_base
        return apply_prompt_override_sections(
            base_prompt,
            self.prompt_override,
            prepend_sections=("routing_prepend", "tool_calling_prepend"),
            append_sections=("routing_append",),
        )
    
    def _create_provider(self):
        """Create appropriate LLM provider based on config or overrides."""
        # Use override if provided, otherwise fall back to config
        provider_type = self._provider_override or get_config_value("LLM_PROVIDER", "openai" if self.mode == "cloud" else "ollama")
        
        if provider_type == "openai":
            model = self._model_override or get_config_value("OPENAI_MODEL", get_provider_fallback_model("openai"))
            return create_provider(
                "openai",
                api_key=get_config_value("OPENAI_API_KEY"),
                model=model
            )
        elif provider_type == "anthropic":
            model = self._model_override or get_config_value("ANTHROPIC_MODEL", get_provider_fallback_model("anthropic"))
            return create_provider(
                "anthropic",
                api_key=get_config_value("ANTHROPIC_API_KEY"),
                model=model
            )
        elif provider_type == "xai":
            model = self._model_override or get_config_value("XAI_MODEL", get_provider_fallback_model("xai"))
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
    
    def route(
        self,
        transcript: str,
        excluded_tools: list = None,
        typo_hint_source: str | None = None,
    ) -> dict[str, Any]:
        """
        Use LLM to determine intent and route appropriately.
        
        Args:
            transcript: Full routing prompt (intelligence, multi-turn context, etc.)
            excluded_tools: Optional list of tool names to exclude from selection
            typo_hint_source: Raw user request text for typo-RAG token scan only (embedding still uses full tool search string).
            
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
        
        tool_sim_threshold = _tool_rag_similarity_threshold(transcript, tool_search_query)
        
        # 3. Find relevant tools using vector search
        # This returns ToolSchema objects for the top matches + ghost tools
        relevant_tools = self.registry.find_tools(
            tool_search_query,
            limit=retrieval_limit,
            similarity_threshold=tool_sim_threshold,
            typo_hint_source=typo_hint_source,
        )
        
        # Filter out excluded tools (e.g., tools blocked for web mode)
        if self._excluded_tools:
            original_count = len(relevant_tools)
            relevant_tools = [t for t in relevant_tools if t.name not in self._excluded_tools]
            if len(relevant_tools) < original_count:
                excluded = set(self._excluded_tools) & set(
                    t.name
                    for t in self.registry.find_tools(
                        tool_search_query,
                        limit=retrieval_limit,
                        similarity_threshold=tool_sim_threshold,
                        typo_hint_source=typo_hint_source,
                    )
                )
                if sys.stdout.isatty():
                    print(f"   🚫 Excluded tools: {', '.join(excluded)}")
        
        # Separate ghost tools from retrieved tools for visibility
        from config_loader import get_config_value
        ghost_tools_str = get_config_value('GHOST_TOOLS', 'search_memory,semantic_recall,remember,check_tool_logs,get_recent_conversations')
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
        logger.info(
            f"[TOOL_RAG] similarity_threshold={tool_sim_threshold:.4f} "
            f"(full_transcript_embedding={tool_search_query == transcript})"
        )
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
            
            # Log xAI server-side tool usage (native search)
            if usage_info and usage_info.get('server_side_tools'):
                server_tools = usage_info['server_side_tools']
                tool_list = [f"{k.replace('SERVER_SIDE_TOOL_', '').lower()}({v}x)" for k, v in server_tools.items() if v > 0]
                if tool_list:
                    logger.info(f"[xAI SEARCH] Native search used: {', '.join(tool_list)}")
            
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
    
    def _detect_opencode_mode(self, query: str, response: dict) -> dict:
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
    result = router.route(transcript, typo_hint_source=transcript)
    
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
