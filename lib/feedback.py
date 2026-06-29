#!/usr/bin/env python3
"""
Jarvis Feedback System - LLM-as-QA for self-improvement

This module allows Jarvis to critique its own experience after completing a task,
identifying issues with:
- System prompt and instructions
- Tool descriptions and accuracy
- Context and information provided
- Suggestions for improvement

Usage:
    from feedback import FeedbackCollector
    collector = FeedbackCollector(mode='cloud')
    feedback = collector.collect(query, result, context)
"""

import os
import sys
import json
from datetime import datetime
from typing import Any
from pathlib import Path

# Add lib to path if needed
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import load_config, get_config_value
from model_catalog import get_provider_fallback_model


def _config_bool(name: str, default: str = "false") -> bool:
    """Read env/config booleans using the same loose truthy values as provider adapters."""
    return str(get_config_value(name, default) or default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


FEEDBACK_PROMPT = """A task was just completed as a voice assistant. Now provide HONEST, SPECIFIC FEEDBACK to help improve the system.

📅 CRITICAL - TODAY'S DATE: {current_date}

⚠️ DATE-RELATIVE QUERY RULES (read carefully):
- "this weekend" = the UPCOMING Saturday/Sunday (or Friday-Sunday) from today's date
- "tonight", "today", "tomorrow" = relative to TODAY ({current_date})
- If user asks about "this weekend" and response mentions dates 1-4 days in the future, that is CORRECT
- DO NOT penalize responses that correctly reference upcoming dates
- Example: If today is Jan 15 and response says "Jan 17-18", that IS this weekend = CORRECT
- The assistant CANNOT predict exact future content, but can report what is SCHEDULED
- For streaming/entertainment queries, listing scheduled releases is acceptable behavior

🔴 NATIVE SEARCH CHECK - READ FIRST: {native_search_status}
{native_search_instructions}

=== YOUR TASK ===
User Query: {query}

=== RESULT ===
Success: {success}
Tools Used: {tools_used}

**ORIGINAL LLM RESPONSE** (what the LLM generated):
{raw_llm_response}

**FINAL VOICE OUTPUT** (see style in Configuration - may be short OR detailed):
{final_speech}

**SERVER-SIDE / PROVIDER-NATIVE TOOL METADATA**:
{server_side_tools}

⚠️ IMPORTANT CONTEXT FOR GRADING:

1. **RESPONSE STYLE DETERMINES OUTPUT FORMAT** - check Configuration section FIRST!
   - If style is "casual" or "auto": Apply 25-100 word limit, no URLs, no markdown (voice output)
   - If style is "detailed": Output is for DISPLAY/READING, not voice synthesis
     → Markdown IS allowed (links, bold, lists)
     → Full URLs with markdown links ARE correct
     → No word limit - verbose output is expected
   
2. **DO NOT PENALIZE DETAILED MODE OUTPUT** - When style="detailed":
   - Long responses = CORRECT (output is read, not spoken)
   - URLs with markdown links = CORRECT (displayed, not synthesized)
   - Markdown formatting = CORRECT (**, ##, bullets are fine for display)
   - This is NOT a voice interface in detailed mode - it's a display interface

2b. **RAW RESPONSE VS SPOKEN OUTPUT** - grade these differently:
   - `ORIGINAL LLM RESPONSE` may include provider-native search citations, raw URLs, source blocks, or social links intended for display/debugging.
   - `FINAL VOICE OUTPUT` is the TTS-facing text Jarvis stores for speech.
   - Jarvis speech sanitization strips URLs, markdown noise, source blocks, and social post IDs before TTS.
   - DO NOT penalize raw URLs or source lists in `ORIGINAL LLM RESPONSE` if `FINAL VOICE OUTPUT` is clean, concise, and natural.
   - ONLY penalize URL/source spam when it survives into `FINAL VOICE OUTPUT` or degrades the actual spoken UX.

3. **SHORT SPOKEN RESPONSES ARE CORRECT WHEN CONTENT GOES TO CANVAS/STASH** ⚠️ CRITICAL:
   - This is a VOICE ASSISTANT - responses are SPOKEN OUT LOUD
   - When workflows create canvas pages, stash files, or save to memory, the CONTENT is there
   - The spoken response should be a BRIEF CONFIRMATION, not a summary of all findings
   - Examples of CORRECT short responses:
     → "/dive workflow created canvas" → "Deep dive complete. Canvas summary created." = RATE 5
     → "/research workflow" → "Research complete. I found 5 sources and saved a report to your canvas." = RATE 5
     → "/note workflow" → "Note saved to memory and canvas." = RATE 5
   - DO NOT penalize for "not summarizing findings" when content is in canvas/stash
   - DO NOT expect the assistant to read back the entire canvas content
   - The user will READ the canvas, not listen to it being read aloud
   - A 10-word confirmation + canvas page is BETTER than a 200-word spoken summary

3. **CURRENT DATE/TIME IS INJECTED INTO THE SYSTEM PROMPT** on every request.
   The LLM ALREADY HAS the current date and time in its system prompt.
   Therefore:
   - NOT calling get_time when asked for time is ACCEPTABLE if the LLM uses system prompt time
   - The LLM using time from system prompt instead of calling a tool is EFFICIENT, not wrong
   - Only penalize if the time in the response is INCORRECT, not if get_time wasn't called

4. **NATIVE LIVE SEARCH** ⚠️ CRITICAL - READ THIS CAREFULLY:
   CHECK Configuration section for "Native Search: ENABLED" or "Native Search: DISABLED"
   
   **IF "Native Search: ENABLED"**:
   - The LLM has BUILT-IN web search (xAI Grok live search or Anthropic web_search)
   - It can answer real-time queries (news, stocks, unemployment, Netflix, weather, sports, prices)
     **WITHOUT calling any external tools** - this is CORRECT behavior
   - Native/provider search may also appear in `SERVER-SIDE / PROVIDER-NATIVE TOOL METADATA`
   - Source URLs returned by provider-native search count as evidence, not hallucination
   - "Tools Used: none" + specific details = NATIVE SEARCH WAS USED = RATE 4-5
   - The information WAS verified via native search even though no tool appears in the list
   - DO NOT say "hallucinated" or "unverified" when native search is ENABLED
   - DO NOT penalize for "no tool called" when native search is ENABLED
   - Examples of CORRECT behavior with native search:
     → Query: "What's the unemployment rate?" Response: "4.6% as of November 2025" Tools: none → RATE 5
     → Query: "What's new on Netflix?" Response: lists specific titles Tools: none → RATE 4-5
     → Query: "Latest Bitcoin price?" Response: "$98,500" Tools: none → RATE 5
   
   **IF "Native Search: DISABLED"**:
   - Real-time queries NEED tools (mcp_fetch, search tools, etc.)
   - "Tools Used: none" for real-time data = PROBLEM = rate 1-2

5. **CHECK THE SYSTEM PROMPT BELOW** - it shows what context the LLM had available.
   If data was already in the system prompt, the LLM didn't need to call a tool for it.

6. **CONVERSATION FOLLOW-UP CONTEXT**:
   Check the Configuration "Interface:" line to understand what context the LLM had:
   
   - **"Interface: web"** → Web UI with full conversation history and extracted follow-up data
     (stash_refs, video_ids, memory_ids, providers) from prior tool results in the same chat session.
   - **"Interface: cli/voice (auto-context enabled...)"** → CLI/voice with recent prior
     conversations included (time-limited window). LLM has some prior context.
   - **"Interface: cli/voice (no prior conversation context)"** → Single-shot, no history.
   
   When conversation context IS available, the LLM can act on previous results
   WITHOUT re-calling the original tool. This is CORRECT behavior.
   
   NOTE: On the FIRST message in a new chat session, there is no prior context.
   The LLM calling tools normally on the first turn is expected — not a problem.
   
   Examples of CORRECT follow-up behavior (when context is available):
   → Previous turn used generate_video → User says "make it longer" → LLM calls generate_video
     with the stash_ref from conversation context = CORRECT (no need to search/recall first)
   → Previous turn used pdf_create → User says "email that PDF" → LLM calls send_email
     with the ref from conversation context = CORRECT (tools used: send_email only)
   → Previous turn used remember → User says "update that memory" → LLM calls update_memory
     with the memory_id from context = CORRECT
   → User asks "what was the video stash ref?" → LLM answers from context, no tool = CORRECT
   
   DO NOT penalize for:
   - Not re-calling a tool to "look up" data that was in the conversation context
   - Using stash_refs, IDs, or provider names from previous turns
   - Answering reference questions about previous results without tools

=== SYSTEM PROMPT THE LLM WAS GIVEN ===
{system_prompt_excerpt}

=== TOOL DESCRIPTIONS (for tools used or should have been used) ===
{tool_descriptions}

=== INTELLIGENCE INSIGHTS PROVIDED ===
{intelligence_insights}

=== CONFIGURATION ===
{config_context}

=== COMPLETION GUARD ===
{completion_guard_context}

=== PROVIDE SPECIFIC FEEDBACK ===

7. **COMPLETION GUARD CONTEXT**:
   - If Completion Guard status is `none`, do NOT penalize the system for not using it.
   - If Completion Guard status is `accepted` or `auto_accepted`, grade the final settled answer normally.
   - If Completion Guard status is `tighten_only`, treat it like an accepted answer with minor wording cleanup, not a failed repair.
   - If Completion Guard status is `repaired`, grade the repaired final answer as the settled result, while noting that first-pass recovery was needed.
   - If Completion Guard status is `ticket_created`, `unresolved`, or `cancelled`, this means the system detected incompleteness or could not fully recover. Grade the final settled outcome accordingly, but do not treat the existence of Completion Guard itself as a flaw.
   - If Completion Guard status is `expired` or `superseded`, treat it as neutral manual prompt settlement. Do not infer user dissatisfaction from that status alone.
   - When Completion Guard metadata is present, use it as recovery context, not as a reason to lower the score by itself.

Rate the interaction (1-5) using this STRICT rubric:

⚠️ NATIVE SEARCH RULE: If "Native Search: ENABLED" in Configuration:
   - "Tools Used: none" is CORRECT for real-time queries (the LLM used built-in search)
   - Specific details without tools = native search was used = NOT hallucination
   - Provider-native URLs/citations in the raw answer can be valid evidence
   - Rate 4-5 unless information is demonstrably wrong

**5 = PERFECT** - All criteria met:
  ✓ Correct tool(s) selected (OR no tools when native search handles it)
  ✓ Response accurately addresses the query
  ✓ No hallucinations or incorrect information
  ✓ Output format matches the configured style (check Configuration section!)
  ✓ If native search enabled + real-time query + specific accurate response = 5
  ✓ If workflow created canvas/stash + short confirmation speech = 5 (content is in canvas!)
  
**4 = GOOD with minor issues** - Task completed but:
  - Minor formatting issue (NOT verbosity if style is "detailed"!)
  - Correct but not optimal tool choice
  - Note: In "detailed" style, long responses with URLs are CORRECT, not a flaw
  - Native search response could have included more context/sources
  - Note: Short speech + canvas created = 5, NOT a "minor issue"
  
**3 = ACCEPTABLE with issues** - Task completed but:
  - Response partially addresses query
  - Tool description caused suboptimal selection
  - Some unnecessary steps taken
  
**2 = PROBLEMATIC** - Significant issues:
  - Wrong tool selected due to poor description
  - Response contains inaccuracies
  - Important information missing
  - System prompt guidance not followed
  - Native search DISABLED but no tool used for real-time data
  - Tool failed and LLM retried with same/similar params instead of searching memory for known limitations
  
**1 = FAILURE** - Major problems:
  - Task failed or wrong result
  - Hallucinated information (ONLY if native search is DISABLED)
  - Completely wrong approach taken
  - Expensive tool (video/image/music generation) called multiple times when first result had a provider limitation (e.g., duration ignored)

BE CONSISTENT: Apply this rubric the same way every time.

⚠️ CRITICAL CONSTRAINT - CONTEXT LENGTH BUDGET:
Tool descriptions and system prompts must be CONCISE. Every token costs:
- Latency (slower responses)
- Money (API costs)  
- Context window space (less room for conversation)

When suggesting improvements:
- Tool descriptions: MAX 200 words (ideal: 50-100 words)
- Keep suggestions focused and actionable
- Don't add unnecessary examples or edge cases
- Prioritize: WHEN to use > HOW it works > edge cases

A description that's 50 words and covers 90% of use cases is BETTER than
a 200 word description that covers 100% of use cases.

Provide SPECIFIC, ACTIONABLE feedback:

1. **System Prompt Issues**: 
   - Are any rules contradictory? 
   - Were memory-first rules applied correctly for this query type?

2. **Tool Selection Issues**: 
   - Were the right tools chosen?
   - Did the tool description accurately describe what the tool does?
   - Should the description mention something it doesn't?
   - Would a different description have led to better tool selection?

3. **Intelligence Insights Issues**:
   - Were the learned strategies helpful or misleading?
   - Did known failures help avoid mistakes?
   - Were tool preferences accurate?

4. **Tool Failure Recovery**:
   - If a tool failed or returned unexpected results, did the LLM search memory (search_memory/semantic_recall) for known limitations BEFORE retrying?
   - If a generation tool (video/image/music) was called multiple times, was it because the provider ignored a parameter (API limitation, not fixable by retrying)?
   - Did the LLM inform the user about the limitation instead of silently retrying?
   - Suggestion: "When a tool returns unexpected results, use search_memory to check for known provider limitations before retrying"

5. **Suggestions**: 
   - QUOTE the specific text that should change
   - Provide the improved version

If everything was perfect, say "No issues - task completed smoothly" with rating 5.

FORMAT YOUR RESPONSE AS JSON:
{{
    "rating": <1-5>,
    "summary": "<one sentence summary>",
    "tool_ratings": {{
        "<tool_name>": {{
            "rating": <1-5>,
            "note": "<brief note about this tool's performance>"
        }}
    }},
    "issues": [
        {{
            "category": "system_prompt|tool_description|intelligence_insights|config|other",
            "description": "<specific issue - quote the problematic text>",
            "current_text": "<the actual text that's problematic, if applicable>",
            "suggestion": "<how to fix - provide improved text>"
        }}
    ],
    "positive": "<what worked well, if anything>"
}}

IMPORTANT for tool_ratings:
- Rate EACH tool that was used separately (1-5)
- If a tool worked perfectly: 5
- If a tool had issues: rate accordingly (1-4)
- Example: {{"get_time": {{"rating": 5, "note": "correct"}}, "mcp_fetch_fetch": {{"rating": 2, "note": "couldn't reach private IP"}}}}
"""


class FeedbackCollector:
    """Collects feedback from LLM after task completion.
    
    Uses a SEPARATE LLM provider for feedback to avoid self-grading bias.
    Configure via FEEDBACK_PROVIDER and FEEDBACK_MODEL in your .env file.
    
    If not configured, falls back to the default provider for the mode.
    """
    
    def __init__(self, mode: str = 'cloud'):
        self.mode = mode
        load_config(mode)
        
        from llm_provider import create_provider
        from config_loader import get_config_value
        
        # Check for dedicated feedback provider (recommended for unbiased grading)
        feedback_provider = get_config_value("FEEDBACK_PROVIDER", "")
        feedback_model = get_config_value("FEEDBACK_MODEL", "")
        
        if feedback_provider:
            # Use dedicated feedback provider (different LLM grades the task)
            self.provider_name = feedback_provider
            self.model_name = feedback_model
            
            if feedback_provider == "anthropic":
                self.provider = create_provider(
                    "anthropic",
                    api_key=get_config_value("ANTHROPIC_API_KEY"),
                    model=feedback_model or get_provider_fallback_model("anthropic")
                )
            elif feedback_provider == "openai":
                self.provider = create_provider(
                    "openai",
                    api_key=get_config_value("OPENAI_API_KEY"),
                    model=feedback_model or get_provider_fallback_model("openai")
                )
            elif feedback_provider == "xai":
                self.provider = create_provider(
                    "xai",
                    api_key=get_config_value("XAI_API_KEY"),
                    model=feedback_model or get_provider_fallback_model("xai")
                )
            elif feedback_provider == "ollama":
                from ollama_utils import resolve_ollama_model
                self.provider = create_provider(
                    "ollama",
                    model=resolve_ollama_model(mode, model_override=feedback_model),
                    base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434")
                )
            else:
                raise ValueError(f"Unknown FEEDBACK_PROVIDER: {feedback_provider}. Use: anthropic, openai, xai, ollama")
        else:
            # Fallback: Use same provider as mode (not ideal but works)
            if mode == 'local':
                from ollama_utils import resolve_ollama_model
                self.provider_name = "ollama"
                self.model_name = resolve_ollama_model(mode)
                self.provider = create_provider(
                    "ollama",
                    model=self.model_name,
                    base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434")
                )
            else:
                # Cloud mode - use default provider
                provider_type = get_config_value("LLM_PROVIDER", "anthropic")
                self.provider_name = provider_type
                
                if provider_type == "ollama":
                    from ollama_utils import resolve_ollama_model
                    self.model_name = resolve_ollama_model(mode)
                    self.provider = create_provider(
                        "ollama",
                        model=self.model_name,
                        base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434")
                    )
                elif provider_type == "xai":
                    self.model_name = get_config_value("XAI_MODEL", get_provider_fallback_model("xai"))
                    self.provider = create_provider(
                        "xai",
                        api_key=get_config_value("XAI_API_KEY"),
                        model=self.model_name
                    )
                elif provider_type == "openai":
                    self.model_name = get_config_value("OPENAI_MODEL", get_provider_fallback_model("openai"))
                    self.provider = create_provider(
                        "openai",
                        api_key=get_config_value("OPENAI_API_KEY"),
                        model=self.model_name
                    )
                else:
                    self.model_name = get_config_value("ANTHROPIC_MODEL", get_provider_fallback_model("anthropic"))
                    self.provider = create_provider(
                        "anthropic",
                        api_key=get_config_value("ANTHROPIC_API_KEY"),
                        model=self.model_name
                    )
        
        # Setup logging
        self.log_dir = Path(__file__).parent.parent / "logs" / "feedback"
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def collect(
        self,
        query: str,
        result: dict[str, Any],
        tools_used: list = None,
        num_tools: int = 0,
        system_prompt: str = None,
        tool_descriptions: dict[str, str] = None,
        intelligence_insights: str = None,
        config_context: str = None,
        session_id: str = None,
        completion_guard_context: dict | None = None
    ) -> dict[str, Any]:
        """
        Collect feedback from LLM about the completed task.
        
        Args:
            query: Original user query
            result: Task result (speech, ok, data, etc.)
            tools_used: List of tools that were called
            num_tools: Total number of available tools
            system_prompt: The actual system prompt used (or excerpt)
            tool_descriptions: Dict of tool_name -> description for relevant tools
            intelligence_insights: The intelligence context that was injected
            config_context: Configuration details (auto-context, response style, etc.)
            session_id: Optional session identifier
            
        Returns:
            Feedback dictionary with rating, issues, suggestions
        """
        timestamp = datetime.now().isoformat()
        
        # Format system prompt - provide FULL context for accurate feedback
        # Truncation can lead to missed context and bad evolution decisions
        system_prompt_excerpt = system_prompt or "System prompt not provided for analysis."
        if len(system_prompt_excerpt) > 8000:
            # Only truncate if extremely long, keep most of it
            system_prompt_excerpt = system_prompt_excerpt[:8000] + "\n... [truncated - full prompt is " + str(len(system_prompt)) + " chars]"
        
        # Format tool descriptions
        if tool_descriptions:
            tool_desc_text = "\n".join([
                f"- {name}: {desc}" 
                for name, desc in tool_descriptions.items()
            ])
        else:
            tool_desc_text = "Tool descriptions not provided for analysis."
        
        # Get both the original LLM response and the formatted voice output
        raw_llm_response = result.get('raw_llm_response', result.get('speech', 'No response'))
        final_speech = result.get('speech', 'No response')
        server_side_tools = result.get('server_side_tools') or {}
        if server_side_tools:
            server_side_tools_text = json.dumps(server_side_tools, ensure_ascii=False, indent=2)
            if len(server_side_tools_text) > 3000:
                server_side_tools_text = server_side_tools_text[:3000] + "\n... [truncated]"
        else:
            server_side_tools_text = "None"
        
        # Determine native search status for prominent display
        # Check config_context for native search status or check environment
        native_search_enabled = any(
            str(name) in {"SERVER_SIDE_TOOL_WEB_SEARCH", "SERVER_SIDE_TOOL_X_SEARCH"}
            for name in server_side_tools
        )
        if config_context and "Native Search: ENABLED" in config_context:
            native_search_enabled = True
        elif not native_search_enabled:
            # Fallback to checking environment
            llm_provider = get_config_value("LLM_PROVIDER", "anthropic")
            if llm_provider == "xai":
                native_search_enabled = _config_bool("XAI_SEARCH")
            elif llm_provider == "anthropic":
                native_search_enabled = _config_bool("ANTHROPIC_SEARCH")
            elif llm_provider == "openai":
                native_search_enabled = (
                    str(get_config_value("OPENAI_API_MODE", "chat") or "chat").strip().lower() == "responses"
                    and _config_bool("OPENAI_RESPONSES_SERVER_SIDE_TOOLS")
                    and _config_bool("OPENAI_RESPONSES_WEB_SEARCH")
                )
        
        if native_search_enabled:
            native_search_status = "🟢 ENABLED - LLM has built-in web search"
            native_search_instructions = """The LLM that answered this query HAS BUILT-IN WEB SEARCH.
When "Tools Used: None" appears for real-time queries (news, prices, data), this is CORRECT behavior.
The LLM used its native search capability - this is NOT hallucination.
DO NOT rate poorly for "no tools used" when native search provided specific data.
Rate 4-5 if response contains specific, detailed information that addresses the query."""
        else:
            native_search_status = "🔴 DISABLED - needs tools for real-time data"
            native_search_instructions = """The LLM has NO built-in search.
If real-time data was needed and no tools were used, rate poorly."""
        
        # Build the feedback prompt
        prompt = FEEDBACK_PROMPT.format(
            current_date=datetime.now().strftime("%A, %B %d, %Y"),  # e.g., "Wednesday, January 15, 2026"
            query=query,
            success="Yes" if result.get('ok') else "No",
            raw_llm_response=raw_llm_response,
            final_speech=final_speech,
            tools_used=", ".join(tools_used) if tools_used else "None",
            system_prompt_excerpt=system_prompt_excerpt,
            tool_descriptions=tool_desc_text,
            intelligence_insights=intelligence_insights or "No intelligence insights provided.",
            config_context=config_context or "No configuration context provided.",
            completion_guard_context=json.dumps(completion_guard_context or {"status": "none"}, ensure_ascii=False, indent=2),
            native_search_status=native_search_status,
            native_search_instructions=native_search_instructions,
            server_side_tools=server_side_tools_text
        )
        
        try:
            # Ask LLM for feedback with retry logic for transient errors (529 overload, etc.)
            import time
            max_retries = 3
            response = None
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    response = self.provider.chat(
                        prompt,
                        system_prompt="You are a QA analyst reviewing an AI assistant's performance. Provide honest, specific feedback in JSON format. Be constructive but thorough."
                    )
                    break  # Success
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    # Retry on overload/rate limit errors
                    if '529' in error_str or 'overload' in error_str or '429' in error_str or 'rate' in error_str:
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2  # 2s, 4s, 6s
                            print(f"Feedback API overloaded, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                    raise  # Non-retryable error
            
            if response is None and last_error:
                raise last_error
            
            # Parse JSON response
            feedback = self._parse_feedback(response)
            
            # Add metadata
            feedback["timestamp"] = timestamp
            feedback["session_id"] = session_id
            feedback["query"] = query
            feedback["result_ok"] = result.get('ok', False)
            feedback["raw_llm_response"] = raw_llm_response  # Original LLM response
            feedback["final_speech"] = final_speech  # Formatted for voice
            feedback["tools_used"] = tools_used or []
            feedback["mode"] = self.mode
            feedback["completion_guard"] = completion_guard_context or {"status": "none"}
            # Track which LLM did the grading (important for bias analysis)
            feedback["feedback_provider"] = self.provider_name
            feedback["feedback_model"] = self.model_name
            
            # Log feedback if there are issues (rating < 5) or always if configured
            # Also log if there was an error (rating is None or has raw_response error)
            rating = feedback.get("rating")
            feedback.get("raw_response", "").startswith("Error:") or feedback.get("error")
            
            # Always log feedback - it's valuable for analysis and evolution
            # Rating scale is 1-5: 5 = perfect, 4 = minor issues, 3 = some issues, 2 = significant, 1 = major
            self._log_feedback(feedback)
            
            # Record usage in prompt versioning system for evolution tracking
            # Pass feedback to enable per-tool attribution when multiple tools used
            self._record_prompt_usage(tools_used, rating, feedback)
            
            return feedback
            
        except Exception as e:
            error_feedback = {
                "timestamp": timestamp,
                "session_id": session_id,
                "query": query,
                "error": str(e),
                "rating": None,
                "summary": f"Feedback collection failed: {e}"
            }
            self._log_feedback(error_feedback)
            return error_feedback
    
    def _parse_feedback(self, response: str) -> dict[str, Any]:
        """Parse LLM response into structured feedback."""
        # Try to extract JSON from response
        try:
            # Look for JSON block
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
            elif "{" in response:
                # Find JSON object
                start = response.index("{")
                end = response.rindex("}") + 1
                json_str = response[start:end]
            else:
                json_str = response
            
            return json.loads(json_str)
            
        except (json.JSONDecodeError, ValueError, IndexError):
            # Fallback: return as unstructured feedback
            return {
                "rating": None,
                "summary": response[:200] if len(response) > 200 else response,
                "issues": [],
                "raw_response": response
            }
    
    def _log_feedback(self, feedback: dict[str, Any]) -> None:
        """Log feedback to JSONL file."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"feedback-{date_str}.jsonl"
        
        with open(log_file, "a") as f:
            f.write(json.dumps(feedback) + "\n")
    
    def _record_prompt_usage(self, tools_used: list, rating: float, feedback: dict = None) -> None:
        """Record usage for prompt evolution tracking.
        
        Uses per-tool ratings if available from feedback LLM.
        Falls back to overall rating if per-tool ratings not provided.
        """
        try:
            from prompt_versioning import PromptVersionDB, EVOLUTION_CONFIG
            db = PromptVersionDB(self.mode)
            
            # Record for system prompt (always gets the overall rating)
            db.record_usage('system_prompt', rating)
            
            # Check for per-tool ratings (new structured format)
            tool_ratings = {}
            if feedback and feedback.get('tool_ratings'):
                tool_ratings = feedback['tool_ratings']
            
            # Record ratings for each tool
            for tool in (tools_used or []):
                component = f"tool:{tool}"
                
                if tool in tool_ratings:
                    # Use per-tool rating (more accurate)
                    tool_rating = tool_ratings[tool].get('rating', rating)
                    db.record_usage(component, tool_rating)
                else:
                    # Fallback: use overall rating
                    # This is less accurate but ensures we don't lose data
                    db.record_usage(component, rating)
            
            # Check if auto-evolution is enabled
            if EVOLUTION_CONFIG.get('auto_evolve_enabled', False):
                self._maybe_trigger_auto_evolution()
                
        except Exception:
            # Don't fail feedback collection if versioning fails
            pass
    
    def _maybe_trigger_auto_evolution(self) -> None:
        """Check if we should run auto-evolution based on feedback count."""
        try:
            # LOOP PREVENTION: Don't trigger evolution if we're in tool builder context
            if os.environ.get('JARVIS_TOOL_BUILDER_CONTEXT') == 'true':
                return
            
            from prompt_versioning import EVOLUTION_CONFIG
            
            # Count today's feedback entries
            date_str = datetime.now().strftime("%Y-%m-%d")
            log_file = self.log_dir / f"feedback-{date_str}.jsonl"
            
            if not log_file.exists():
                return
            
            with open(log_file) as f:
                count = sum(1 for _ in f)
            
            threshold = EVOLUTION_CONFIG.get('auto_check_after_feedback', 10)
            
            # Check if we've hit the threshold and haven't run yet today
            marker_file = self.log_dir / f".auto_evolution_run_{date_str}"
            
            if count >= threshold and not marker_file.exists():
                # Run evolution check in background
                import subprocess
                import sys
                
                evolve_script = Path(__file__).parent.parent / 'bin' / 'evolve-prompts'
                
                # Run async - don't block feedback return
                subprocess.Popen(
                    [sys.executable, str(evolve_script), '--mode', self.mode, 'auto', '--deploy', '--activate'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                # Mark as run today
                marker_file.touch()
                
                # Log to stderr so it doesn't interfere with JSON output
                import sys as _sys
                print(f"🧬 Auto-evolution triggered ({count} feedback entries)", file=_sys.stderr)
                
        except Exception:
            # Don't fail if auto-evolution check fails
            pass
    
    def get_recent_feedback(self, days: int = 7) -> list:
        """Get feedback from recent days."""
        from datetime import timedelta
        
        feedback = []
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            log_file = self.log_dir / f"feedback-{date_str}.jsonl"
            
            if log_file.exists():
                with open(log_file) as f:
                    for line in f:
                        try:
                            feedback.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        
        return feedback
    
    def get_issues_summary(self, days: int = 7) -> dict[str, Any]:
        """Summarize issues from recent feedback."""
        feedback = self.get_recent_feedback(days)
        
        categories = {}
        ratings = []
        
        for fb in feedback:
            if fb.get("rating"):
                ratings.append(fb["rating"])
            
            for issue in fb.get("issues", []):
                cat = issue.get("category", "other")
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append({
                    "description": issue.get("description"),
                    "suggestion": issue.get("suggestion"),
                    "query": fb.get("query")
                })
        
        return {
            "total_feedback": len(feedback),
            "average_rating": sum(ratings) / len(ratings) if ratings else None,
            "issues_by_category": categories,
            "low_ratings": [fb for fb in feedback if (fb.get("rating") or 5) <= 2]
        }


def main():
    """CLI for feedback system."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Jarvis Feedback System")
    parser.add_argument("action", choices=["summary", "recent", "test"],
                       help="Action to perform")
    parser.add_argument("--days", type=int, default=7,
                       help="Number of days to look back")
    parser.add_argument("--mode", default="cloud",
                       help="Mode (cloud/local)")
    
    args = parser.parse_args()
    
    collector = FeedbackCollector(args.mode)
    
    if args.action == "summary":
        summary = collector.get_issues_summary(args.days)
        print(json.dumps(summary, indent=2))
    
    elif args.action == "recent":
        feedback = collector.get_recent_feedback(args.days)
        for fb in feedback:
            print(f"\n{'='*60}")
            print(f"Query: {fb.get('query', 'N/A')}")
            print(f"Rating: {fb.get('rating', 'N/A')}/5")
            print(f"Summary: {fb.get('summary', 'N/A')}")
            if fb.get('issues'):
                print("Issues:")
                for issue in fb['issues']:
                    print(f"  - [{issue.get('category')}] {issue.get('description')}")
    
    elif args.action == "test":
        # Test feedback collection with a mock result
        test_result = {
            "ok": True,
            "speech": "Test completed successfully"
        }
        feedback = collector.collect(
            query="This is a test query",
            result=test_result,
            tools_used=["test_tool"],
            num_tools=50
        )
        print(json.dumps(feedback, indent=2))


if __name__ == "__main__":
    main()
