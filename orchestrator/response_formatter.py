#!/usr/bin/env python3
"""Final speech/display formatting helpers for the main orchestrator."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import (
    get_config_value,
    DEFAULT_JARVIS_QA_WORD_LIMIT,
    DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT,
)
from model_prompt_overrides import apply_prompt_override_sections
from provider_errors import is_provider_error_text
from user_profile import append_user_profile_card_to_prompt


class ResponseFormatter:
    """Owns final-response shaping for casual/auto/multi-turn speech output."""

    def __init__(
        self,
        *,
        provider,
        prompt_override,
        extract_useful_data_fn: Callable[[dict], str],
    ):
        self.provider = provider
        self.prompt_override = prompt_override
        self._extract_useful_data = extract_useful_data_fn

    @staticmethod
    def looks_like_provider_error_text(text: str) -> bool:
        """Detect provider error strings accidentally returned as normal formatter output."""
        return is_provider_error_text(text)

    def apply_qa_prompt_overrides(self, base_prompt: str) -> str:
        """Apply model-specific QA overlays and synthesis-only profile card."""
        prompt = apply_prompt_override_sections(
            base_prompt,
            self.prompt_override,
            prepend_sections=("qa_prepend",),
            append_sections=("qa_append",),
        )
        return append_user_profile_card_to_prompt(prompt)

    def xai_tts_style_tags_enabled(self) -> bool:
        """Return True when final speech may include xAI TTS style tags."""
        tts_provider = get_config_value("TTS_PROVIDER", "").strip().lower()
        enabled = get_config_value("XAI_TTS_STYLE_TAGS_ENABLED", "true").strip().lower()
        return tts_provider == "xai" and enabled in {"1", "true", "yes", "on"}

    def xai_tts_style_tags_instruction(self) -> str:
        """Small, final-speech-only instruction for xAI expressive TTS tags."""
        if not self.xai_tts_style_tags_enabled():
            return ""
        return (
            "\n\nxAI TTS is active. You may use a few supported TTS tags sparingly in the FINAL SPOKEN RESPONSE only "
            "when they make delivery more natural: [pause], [long-pause], [laugh], [chuckle], [sigh], [breath], "
            "<soft>...</soft>, <whisper>...</whisper>, <slow>...</slow>, <emphasis>...</emphasis>. "
            "Use exact tag syntax: inline tags use square brackets like [pause]; wrapping tags use angle brackets like <slow>text</slow>. "
            "Do not tag every sentence. Do not use tags in factual lists, code, URLs, filenames, IDs, prices, or data. "
            "Keep the configured word limit; tags should not add extra content."
        )

    def format_natural_response(self, user_query: str, tool_name: str, tool_result: dict[str, Any]) -> str:
        """Use the LLM to format tool results into short conversational speech."""
        try:
            data = tool_result.get("data", {})
            context = f"""User asked: "{user_query}"

Tool executed: {tool_name}
Tool result: {json.dumps(data, indent=2)}

Create a short response for voice output (spoken through speakers).

CRITICAL RULES:
1. MAX 35 WORDS for tool confirmations
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

            provider_result = self.provider.chat_with_tools(
                messages=[{"role": "user", "content": context}],
                tools=[],
                system_prompt="You are a voice assistant. Output a concise response, MAX 35 words. No greetings, no explanations.",
            )
            text_response = provider_result[0] if provider_result else None

            if text_response and not self.looks_like_provider_error_text(text_response):
                return text_response
            return tool_result.get("speech", "Done")

        except Exception as exc:
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format natural response: {exc}", file=sys.stderr)
            return tool_result.get("speech", "Completed")

    def format_auto_mode(
        self,
        user_query: str,
        tools_used: list,
        accumulated_data: dict,
        raw_response: str,
        turn_num: int,
    ) -> str:
        """Adapt response formatting based on tool type and complexity."""
        try:
            if turn_num > 0:
                return self.format_multi_turn_summary(user_query, tools_used, accumulated_data, raw_response)

            if not tools_used:
                return self.format_single_turn_casual(user_query, raw_response)

            tool_name = tools_used[0] if tools_used else ""
            search_tools = [
                "search_memory", "semantic_recall", "recall", "search_conversations",
                "mcp_brave_search", "mcp_fetch",
            ]
            simple_tools = ["get_time", "crypto_price", "weather"]
            complex_tools = ["opencode", "execute_bash", "send_webhook", "api_call"]

            if any(search in tool_name.lower() for search in search_tools):
                return self.format_single_turn_casual(user_query, raw_response)
            if any(simple in tool_name.lower() for simple in simple_tools):
                if len(raw_response.split()) <= 25:
                    return raw_response
                return self.format_single_turn_casual(user_query, raw_response)
            if any(complex_name in tool_name.lower() for complex_name in complex_tools):
                if len(raw_response.split()) > 75:
                    return raw_response
                return self.format_single_turn_casual(user_query, raw_response)
            return self.format_single_turn_casual(user_query, raw_response)

        except Exception as exc:
            if sys.stdout.isatty():
                print(f"⚠️ Auto mode formatting failed: {exc}", file=sys.stderr)
            return raw_response

    def format_single_turn_casual(self, user_query: str, raw_response: str) -> str:
        """Condense single-turn responses for voice output."""
        qa_limit = int(get_config_value("JARVIS_QA_WORD_LIMIT", str(DEFAULT_JARVIS_QA_WORD_LIMIT)))
        try:
            if len(raw_response.split()) <= qa_limit:
                return raw_response

            context = f"""User asked: "{user_query}"

Your previous response: {raw_response}

Condense this for voice output (MAX {qa_limit} words).

RULES:
1. Keep the core answer with key details
2. Remove: greetings, emojis, markdown, numbered lists
3. For informational queries, include enough context to be useful
4. No URLs unless critical
5. NEVER drop named entities - movie titles, restaurant names, product names, people's names MUST be preserved
6. If user asked for specific items (top 3, best restaurants, etc.), include those by name
7. NEVER speak stash:// references (e.g., stash://space_xxx/f_xxx) - just say "saved to stash" or "image saved"
8. NEVER speak long URLs (>30 chars) - summarize as "link saved" or mention domain only (e.g., "on Wikipedia")
9. Simplify file paths (/home/user/...) to just the filename
10. NEVER speak auto-generated filenames (e.g., "generated_modify_the_previous_20260209.png") - just say "saved" or "saved to stash"
{self.xai_tts_style_tags_instruction()}

EXAMPLES:
Verbose: "Great! I've looked up ntfy. It's an open-source push notification service that lets you..."
Condensed: "Ntfy is an open-source push notification service. Self-hosted setup needs TLS certs for iOS APNs. Without proper HTTPS, it falls back to battery-draining polling. Use Caddy or nginx for auto-TLS."

BAD (drops entities): "Found several restaurants nearby including one Italian and one Thai option."
GOOD (preserves entities): "Top restaurants nearby: Olive Garden for Italian, Thai Orchid for Thai, and Red Robin for burgers."

Your condensed response:"""

            response = self.provider.chat(
                context,
                system_prompt=self.apply_qa_prompt_overrides(
                    f"Condense for voice output. MAX {qa_limit} words. Keep key info. No greetings/emojis."
                    f"{self.xai_tts_style_tags_instruction()}"
                ),
            )
            if not response or self.looks_like_provider_error_text(response):
                return raw_response
            return response.strip()
        except Exception as exc:
            if sys.stdout.isatty():
                print(f"⚠️ Failed to condense response: {exc}", file=sys.stderr)
            words = raw_response.split()
            if len(words) > qa_limit:
                return " ".join(words[:qa_limit]) + "..."
            return raw_response

    def format_multi_turn_summary(
        self,
        user_query: str,
        tools_used: list,
        accumulated_data: dict,
        llm_response: str,
    ) -> str:
        """Condense multi-turn tool results into a concise spoken summary."""
        multi_turn_limit = int(get_config_value("JARVIS_MULTI_TURN_WORD_LIMIT", str(DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT)))
        try:
            has_arrays = any(isinstance(value, list) for value in accumulated_data.values())
            max_chars = 2000 if has_arrays else 800
            context = f"""User asked: "{user_query}"

Tools executed: {', '.join(tools_used)}

LLM's detailed answer (USE NAMES FROM HERE):
{llm_response[:1200]}

Raw tool data (backup for numbers/details):
{json.dumps(accumulated_data, indent=2)[:max_chars]}

Condense into a voice-friendly summary (will be spoken aloud through speakers).

RULES:
1. MAX {multi_turn_limit} WORDS
2. PRESERVE all named entities (restaurant names, movie titles, business names, people) - copy them exactly
3. PRESERVE key numbers (prices, temperatures, percentages, ratings)
4. No emojis, no markdown, no bullet points, no explanations of what tools did
5. If user asked for "top 3" items, include all 3 by name
6. NEVER speak stash:// references (e.g., stash://space_xxx/f_xxx) - just say "saved to stash" or "image generated"
7. NEVER speak long URLs (>30 chars) - summarize as "link saved" or mention domain only
8. Simplify file paths (/home/user/project/file.py) to just the filename (file.py)
9. NEVER speak auto-generated filenames (e.g., "generated_modify_the_previous_20260209.png") - just say "saved" or "saved to stash"
{self.xai_tts_style_tags_instruction()}

GOOD: "Top 3 date night spots: Copper River, BJ's Brewhouse, Thirsty Lion. Tonight: 47°F clear."
GOOD: "Image generated and saved to stash." (NOT "Image saved to stash://space_20260201_xxx/f_abc")
BAD: "[Names from results]" or "Found 3 options" ← Never use placeholders!

Your response:"""

            response = self.provider.chat(
                context,
                system_prompt=self.apply_qa_prompt_overrides(
                    f"Condense to MAX {multi_turn_limit} words. Preserve names, titles, and numbers exactly. No placeholders."
                    f"{self.xai_tts_style_tags_instruction()}"
                ),
            )
            if not response or self.looks_like_provider_error_text(response):
                return llm_response
            return response.strip()
        except Exception as exc:
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format multi-turn summary: {exc}", file=sys.stderr)
            return llm_response

    def format_max_turns_summary(
        self,
        user_query: str,
        tools_used: list,
        accumulated_data: dict,
        max_turns: int,
    ) -> str:
        """Create an intelligent best-effort summary when the max-turn limit is reached."""
        try:
            multi_turn_limit = int(get_config_value("JARVIS_MULTI_TURN_WORD_LIMIT", str(DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT)))
            extracted_data = self._extract_useful_data(accumulated_data)
            context = f"""User asked: "{user_query}"

Tools executed ({len(tools_used)} actions): {', '.join(set(tools_used))}

ALL GATHERED DATA (BEST EFFORT - use this to answer!):
{extracted_data}

IMPORTANT: The task hit a complexity limit after {max_turns} tool calls. 
You MUST provide a BEST EFFORT answer using the data above.

CRITICAL RULES:
1. MAX {multi_turn_limit} WORDS - but ACTUALLY ANSWER the question!
2. If you found ANY relevant info (movie titles, prices, names, etc.) - INCLUDE IT
3. Don't apologize or say "couldn't find" - give the best answer you can
4. If data is incomplete, answer what you CAN and note what's missing briefly
5. NEVER say "hit limit" or mention tool counts
{self.xai_tts_style_tags_instruction()}

GOOD BEST-EFFORT EXAMPLES:
- "Top movies at Regal Hillsboro: Wicked, Avatar Fire and Ash, Zootopia 2. Check fandango.com for exact showtimes."
- "Bitcoin $90k, Solana $143, Ethereum $3k - all up 2-3% today"
- "Found theaters: Regal Evergreen Parkway, AMC Progress Ridge. Current showtimes require checking their websites directly."

BAD EXAMPLES (never do this):
- "I searched 10 times but couldn't find..." (WRONG - use what you found!)
- "Hit complexity limit after 10 tools..." (WRONG - don't mention technical limits!)
- "Unable to find showtimes" (WRONG - at least mention the theaters/movies you DID find!)

Your BEST EFFORT response:"""

            response = self.provider.chat(
                context,
                system_prompt=self.apply_qa_prompt_overrides(
                    f"You are a voice assistant. Provide a BEST EFFORT answer using whatever data you have. "
                    f"MAX {multi_turn_limit} words. ALWAYS include any useful info you found - movie titles, theater names, prices, etc."
                    f"{self.xai_tts_style_tags_instruction()}"
                ),
            )
            if not response or self.looks_like_provider_error_text(response):
                extracted_preview = extracted_data.strip()
                if extracted_preview:
                    return extracted_preview[:400]
                return f"Completed {len(tools_used)} actions. Please review the gathered results."
            return response.strip()
        except Exception as exc:
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format max turns summary: {exc}", file=sys.stderr)
            return (
                f"Completed {len(tools_used)} actions but reached the complexity limit. "
                f"Tools used: {', '.join(tools_used)}. Please review or let me know if you'd like me to continue."
            )
