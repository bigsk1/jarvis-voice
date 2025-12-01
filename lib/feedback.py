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
from typing import Dict, Any, Optional
from pathlib import Path

# Add lib to path if needed
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import load_config, get_config_value


FEEDBACK_PROMPT = """A task was just completed as a voice assistant. Now provide HONEST, SPECIFIC FEEDBACK to help improve the system.

=== YOUR TASK ===
User Query: {query}

=== RESULT ===
Success: {success}
Tools Used: {tools_used}

**ORIGINAL LLM RESPONSE** (what the LLM generated):
{raw_llm_response}

**FINAL VOICE OUTPUT** (formatted for speakers, ~25 word limit):
{final_speech}

⚠️ IMPORTANT: The voice output is SHORT BY DESIGN - it's spoken aloud through speakers.
The system INTENTIONALLY formats the LLM's response to be concise for voice.
DO NOT penalize for brief voice output - that's correct behavior!
Grade the ORIGINAL LLM RESPONSE for accuracy and completeness.
Grade the VOICE OUTPUT only for whether it's a reasonable summary for speaking.

=== SYSTEM PROMPT THE LLM WAS GIVEN ===
{system_prompt_excerpt}

=== TOOL DESCRIPTIONS (for tools used or should have been used) ===
{tool_descriptions}

=== INTELLIGENCE INSIGHTS PROVIDED ===
{intelligence_insights}

=== CONFIGURATION ===
{config_context}

=== PROVIDE SPECIFIC FEEDBACK ===

Rate your experience (1-5):
- 5 = Perfect, everything worked as expected
- 4 = Minor improvements possible  
- 3 = Some issues but workable
- 2 = Significant issues
- 1 = Major problems

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

4. **Suggestions**: 
   - QUOTE the specific text that should change
   - Provide the improved version

If everything was perfect, say "No issues - task completed smoothly" with rating 5.

FORMAT YOUR RESPONSE AS JSON:
{{
    "rating": <1-5>,
    "summary": "<one sentence summary>",
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
                    model=feedback_model or "claude-sonnet-4-5-20250929"
                )
            elif feedback_provider == "openai":
                self.provider = create_provider(
                    "openai",
                    api_key=get_config_value("OPENAI_API_KEY"),
                    model=feedback_model or "gpt-4o"
                )
            elif feedback_provider == "xai":
                self.provider = create_provider(
                    "xai",
                    api_key=get_config_value("XAI_API_KEY"),
                    model=feedback_model or "grok-4-1-fast-non-reasoning-latest"
                )
            elif feedback_provider == "ollama":
                self.provider = create_provider(
                    "ollama",
                    model=feedback_model or get_config_value("OLLAMA_MODEL", "qwen3:14b"),
                    base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434")
                )
            else:
                raise ValueError(f"Unknown FEEDBACK_PROVIDER: {feedback_provider}. Use: anthropic, openai, xai, ollama")
        else:
            # Fallback: Use same provider as mode (not ideal but works)
            if mode == 'local':
                self.provider_name = "ollama"
                self.model_name = get_config_value("OLLAMA_MODEL", "qwen3:14b")
                self.provider = create_provider(
                    "ollama",
                    model=self.model_name,
                    base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434")
                )
            else:
                # Cloud mode - use default provider
                provider_type = get_config_value("LLM_PROVIDER", "anthropic")
                self.provider_name = provider_type
                
                if provider_type == "xai":
                    self.model_name = get_config_value("XAI_MODEL", "grok-4-1-fast-non-reasoning-latest")
                    self.provider = create_provider(
                        "xai",
                        api_key=get_config_value("XAI_API_KEY"),
                        model=self.model_name
                    )
                elif provider_type == "openai":
                    self.model_name = get_config_value("CHAT_MODEL", "gpt-4o")
                    self.provider = create_provider(
                        "openai",
                        api_key=get_config_value("OPENAI_API_KEY"),
                        model=self.model_name
                    )
                else:
                    self.model_name = get_config_value("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
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
        result: Dict[str, Any],
        tools_used: list = None,
        num_tools: int = 0,
        system_prompt: str = None,
        tool_descriptions: Dict[str, str] = None,
        intelligence_insights: str = None,
        config_context: str = None,
        session_id: str = None
    ) -> Dict[str, Any]:
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
        
        # Format system prompt excerpt (key sections)
        system_prompt_excerpt = system_prompt or "System prompt not provided for analysis."
        if len(system_prompt_excerpt) > 3000:
            # Truncate but keep key sections
            system_prompt_excerpt = system_prompt_excerpt[:3000] + "\n... [truncated for length]"
        
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
        
        # Build the feedback prompt
        prompt = FEEDBACK_PROMPT.format(
            query=query,
            success="Yes" if result.get('ok') else "No",
            raw_llm_response=raw_llm_response,
            final_speech=final_speech,
            tools_used=", ".join(tools_used) if tools_used else "None",
            system_prompt_excerpt=system_prompt_excerpt,
            tool_descriptions=tool_desc_text,
            intelligence_insights=intelligence_insights or "No intelligence insights provided.",
            config_context=config_context or "No configuration context provided."
        )
        
        try:
            # Ask LLM for feedback
            response = self.provider.chat(
                prompt,
                system_prompt="You are a QA analyst reviewing an AI assistant's performance. Provide honest, specific feedback in JSON format. Be constructive but thorough."
            )
            
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
            # Track which LLM did the grading (important for bias analysis)
            feedback["feedback_provider"] = self.provider_name
            feedback["feedback_model"] = self.model_name
            
            # Log feedback if there are issues (rating < 5) or always if configured
            # Also log if there was an error (rating is None or has raw_response error)
            rating = feedback.get("rating")
            has_error = feedback.get("raw_response", "").startswith("Error:") or feedback.get("error")
            
            if has_error or rating is None or rating < 5 or os.environ.get('JARVIS_FEEDBACK_ALWAYS_LOG'):
                self._log_feedback(feedback)
            
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
    
    def _parse_feedback(self, response: str) -> Dict[str, Any]:
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
    
    def _log_feedback(self, feedback: Dict[str, Any]) -> None:
        """Log feedback to JSONL file."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"feedback-{date_str}.jsonl"
        
        with open(log_file, "a") as f:
            f.write(json.dumps(feedback) + "\n")
    
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
    
    def get_issues_summary(self, days: int = 7) -> Dict[str, Any]:
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

