#!/usr/bin/env python3
"""
Prompt Evolution Engine

Analyzes feedback to identify prompts needing improvement,
generates candidate improvements, and manages A/B testing.
"""

import os
import sys
import json
import glob
import logging
from datetime import datetime, timedelta
from typing import Any
from dataclasses import dataclass
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import load_config, get_config_value, get_active_config_mode
from prompt_versioning import PromptVersionDB, EVOLUTION_CONFIG


# ==================== Logging Setup ====================

def setup_evolution_logger():
    """Setup logger for evolution events (integrates with Loki/Grafana)."""
    log_dir = Path(__file__).parent.parent / 'logs' / 'evolution'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # JSON Lines format for Loki ingestion
    log_file = log_dir / f"evolution-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    
    logger = logging.getLogger('jarvis.evolution')
    logger.setLevel(logging.INFO)
    
    # Prevent duplicate handlers
    if not logger.handlers:
        handler = logging.FileHandler(log_file)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
    
    return logger

def log_evolution_event(event_type: str, data: dict[str, Any]):
    """Log an evolution event in JSONL format for Grafana/Loki."""
    logger = setup_evolution_logger()
    
    event = {
        "timestamp": datetime.now().isoformat(),
        "event": event_type,
        "service": "jarvis-evolution",
        **data
    }
    
    logger.info(json.dumps(event))


@dataclass
class FeedbackSummary:
    """Summary of feedback for a component."""
    component: str
    total_count: int
    low_rating_count: int
    avg_rating: float
    feedback_ids: list[str]
    common_issues: list[str]
    suggestions: list[str]


@dataclass 
class EvolutionCandidate:
    """A candidate prompt improvement."""
    component: str
    original_content: str
    proposed_content: str
    change_summary: str
    trigger_feedback_ids: list[str]
    confidence: float


class PromptEvolutionEngine:
    """Engine for evolving prompts based on feedback."""
    
    def __init__(self, mode: str = None):
        """Initialize evolution engine."""
        if mode is None:
            mode = get_active_config_mode()
        
        self.mode = mode
        self.db = PromptVersionDB(mode)
        self.feedback_dir = os.path.join(os.path.dirname(__file__), '..', 'logs', 'feedback')
        self.skills_dir = os.path.join(os.path.dirname(__file__), '..', 'skills')
        
        # Load config
        load_config(mode)
    
    # ==================== Feedback Analysis ====================
    
    def load_feedback(self, days: int = None) -> list[dict]:
        """Load feedback from log files."""
        if days is None:
            days = EVOLUTION_CONFIG['window_days']
        
        feedback_entries = []
        cutoff = datetime.now() - timedelta(days=days)
        
        # Find feedback files
        pattern = os.path.join(self.feedback_dir, 'feedback-*.jsonl')
        for filepath in glob.glob(pattern):
            filename = os.path.basename(filepath)
            # Parse date from filename: feedback-2025-12-01.jsonl
            try:
                date_str = filename.replace('feedback-', '').replace('.jsonl', '')
                file_date = datetime.strptime(date_str, '%Y-%m-%d')
                
                if file_date < cutoff:
                    continue
                
                with open(filepath, 'r') as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            feedback_entries.append(entry)
                        except json.JSONDecodeError:
                            continue
            except (ValueError, IOError):
                continue
        
        return feedback_entries
    
    def analyze_feedback_by_component(self, feedback: list[dict]) -> dict[str, FeedbackSummary]:
        """Analyze feedback grouped by component (tools used).
        
        Uses per-tool ratings when available for accurate attribution.
        Falls back to overall rating for tools without individual ratings.
        System prompt always gets the overall rating.
        """
        component_feedback = {}
        
        for entry in feedback:
            # Rating can be nested (from orchestrator) or flat (from feedback log)
            overall_rating = entry.get('rating')
            if overall_rating is None:
                overall_rating = entry.get('feedback', {}).get('rating')
            if overall_rating is None:
                continue
            
            # Get per-tool ratings if available (more accurate)
            # Can be top-level or nested under 'feedback'
            tool_ratings = entry.get('tool_ratings', {})
            if not tool_ratings:
                tool_ratings = entry.get('feedback', {}).get('tool_ratings', {})
            
            # Get tools used in this interaction
            tools_used = entry.get('tools_used', [])
            feedback_id = entry.get('feedback_id', entry.get('timestamp', 'unknown'))
            
            # System prompt always gets the overall rating
            if 'system_prompt' not in component_feedback:
                component_feedback['system_prompt'] = {
                    'ratings': [],
                    'feedback_ids': [],
                    'issues': [],
                    'suggestions': []
                }
            component_feedback['system_prompt']['ratings'].append(overall_rating)
            component_feedback['system_prompt']['feedback_ids'].append(feedback_id)
            
            # Tools get per-tool ratings if available, otherwise overall rating
            for tool in tools_used:
                component = f"tool:{tool}"
                if component not in component_feedback:
                    component_feedback[component] = {
                        'ratings': [],
                        'feedback_ids': [],
                        'issues': [],
                        'suggestions': []
                    }
                
                # Use per-tool rating if available (more accurate)
                if tool in tool_ratings:
                    tool_rating = tool_ratings[tool].get('rating', overall_rating)
                else:
                    # Fallback to overall rating (less accurate but backwards-compatible)
                    tool_rating = overall_rating
                
                component_feedback[component]['ratings'].append(tool_rating)
                component_feedback[component]['feedback_ids'].append(feedback_id)
            
            # Extract issues and suggestions (can be nested or flat)
            fb = entry.get('feedback', {}) if 'feedback' in entry else entry
            if fb.get('tool_feedback'):
                component_feedback['system_prompt']['issues'].extend(fb['tool_feedback'])
            if fb.get('prompt_suggestions'):
                component_feedback['system_prompt']['suggestions'].extend(fb['prompt_suggestions'])
            # Also capture issues array for system_prompt
            if fb.get('issues'):
                for issue in fb['issues']:
                    suggestion = issue.get('suggestion', '')
                    if suggestion:
                        component_feedback['system_prompt']['suggestions'].append(suggestion)
        
        # Convert to FeedbackSummary objects
        summaries = {}
        threshold = EVOLUTION_CONFIG['low_rating_threshold']
        
        for component, data in component_feedback.items():
            ratings = data['ratings']
            if not ratings:
                continue
            
            low_ratings = [r for r in ratings if r < threshold]
            
            summaries[component] = FeedbackSummary(
                component=component,
                total_count=len(ratings),
                low_rating_count=len(low_ratings),
                avg_rating=sum(ratings) / len(ratings),
                feedback_ids=data['feedback_ids'][:10],  # Keep last 10
                common_issues=list(set(data['issues']))[:5],
                suggestions=list(set(data['suggestions']))[:5]
            )
        
        return summaries
    
    def get_evolution_candidates(self) -> list[FeedbackSummary]:
        """Get components that are candidates for evolution (excludes MCP tools)."""
        feedback = self.load_feedback()
        summaries = self.analyze_feedback_by_component(feedback)
        
        candidates = []
        min_low = EVOLUTION_CONFIG['min_low_ratings']
        
        for component, summary in summaries.items():
            # Skip MCP tools - we can't evolve external tools
            if component.startswith('tool:mcp_'):
                continue
            
            if summary.low_rating_count >= min_low:
                candidates.append(summary)
        
        # Sort by low rating count (worst first)
        candidates.sort(key=lambda x: x.low_rating_count, reverse=True)
        return candidates
    
    def get_mcp_issues(self) -> list[FeedbackSummary]:
        """Get MCP tools with poor performance (candidates for replacement)."""
        feedback = self.load_feedback()
        summaries = self.analyze_feedback_by_component(feedback)
        
        mcp_issues = []
        min_low = EVOLUTION_CONFIG['min_low_ratings']
        
        for component, summary in summaries.items():
            # Only MCP tools
            if not component.startswith('tool:mcp_'):
                continue
            
            if summary.low_rating_count >= min_low:
                mcp_issues.append(summary)
        
        # Sort by low rating count (worst first)
        mcp_issues.sort(key=lambda x: x.low_rating_count, reverse=True)
        return mcp_issues
    
    # ==================== Evolution Generation ====================
    
    def get_current_content(self, component: str) -> str | None:
        """Get current content for a component."""
        if component == 'system_prompt':
            # Get system prompt from recent feedback logs (they capture it)
            feedback = self.load_feedback(days=7)
            for entry in reversed(feedback):  # Most recent first
                entry.get('feedback', entry)
                # Look for system prompt in the feedback entry
                if 'system_prompt' in str(entry):
                    # The feedback logs capture excerpts of system prompt
                    # Return a summary for the LLM to understand
                    return """The system prompt in router_v2.py includes:
- MEMORY-FIRST RULE: Check memory tools before action tools
- Tool selection guidance for different query types  
- Voice output rules (max ~50 words, no markdown)
- Multi-turn orchestration rules
- Current date/time injection
- Response formatting based on JARVIS_RESPONSE_STYLE

Key sections that get low ratings often involve:
- When to use search_memory vs semantic_recall
- Handling private/local network requests
- Being honest when tools can't verify something

See router_v2.py for full content (~200 lines).
For specific improvements, check feedback logs for exact issues reported."""
            return "[System prompt - check feedback logs for specific issues]"
        
        elif component.startswith('tool:'):
            tool_name = component.replace('tool:', '')
            tool_path = os.path.join(self.skills_dir, f'{tool_name}.tool.json')
            try:
                with open(tool_path, 'r') as f:
                    data = json.load(f)
                return data.get('description', '')
            except (IOError, json.JSONDecodeError):
                return None
        
        return None
    
    def generate_improvement(self, summary: FeedbackSummary) -> EvolutionCandidate | None:
        """Generate an improved prompt using the feedback LLM."""
        current_content = self.get_current_content(summary.component)
        if not current_content:
            return None
        
        # Use feedback LLM for generation
        from llm_provider import create_provider
        
        provider_type = get_config_value('FEEDBACK_PROVIDER', 
                                         get_config_value('LLM_PROVIDER', 'anthropic'))
        model = get_config_value('FEEDBACK_MODEL',
                                get_config_value('ANTHROPIC_MODEL', 'claude-sonnet-4-5-20250929'))
        
        print(f"⏳ Generating improvement using {provider_type}/{model}...")
        
        # Build provider - use the model variable we computed above
        if provider_type == 'anthropic':
            provider = create_provider(
                'anthropic',
                api_key=get_config_value('ANTHROPIC_API_KEY'),
                model=model
            )
        elif provider_type == 'xai':
            provider = create_provider(
                'xai',
                api_key=get_config_value('XAI_API_KEY'),
                model=model
            )
        elif provider_type == 'openai':
            provider = create_provider(
                'openai',
                api_key=get_config_value('OPENAI_API_KEY'),
                model=model
            )
        else:
            provider = create_provider(
                'ollama',
                model=model,
                base_url=get_config_value('OLLAMA_BASE_URL', 'http://localhost:11434')
            )
        
        # Build improvement prompt
        prompt = self._build_improvement_prompt(summary, current_content)
        
        try:
            system_prompt = "You are an expert at improving AI assistant prompts and tool descriptions. You make targeted, minimal changes that address specific issues."
            response = provider.chat(prompt, system_prompt=system_prompt)
            
            # Parse response
            improved = self._parse_improvement_response(response, current_content)
            if improved:
                return EvolutionCandidate(
                    component=summary.component,
                    original_content=current_content,
                    proposed_content=improved['content'],
                    change_summary=improved['summary'],
                    trigger_feedback_ids=summary.feedback_ids,
                    confidence=0.7  # Base confidence
                )
        except Exception as e:
            print(f"Error generating improvement: {e}")
        
        return None
    
    def _build_improvement_prompt(self, summary: FeedbackSummary, current_content: str) -> str:
        """Build the prompt for generating improvements."""
        issues_str = "\n".join(f"- {issue}" for issue in summary.common_issues) or "No specific issues noted"
        suggestions_str = "\n".join(f"- {s}" for s in summary.suggestions) or "No specific suggestions"
        
        return f"""Analyze this prompt/description and suggest an improvement based on the feedback.

COMPONENT: {summary.component}

CURRENT CONTENT:
{current_content}

FEEDBACK SUMMARY:
- Total interactions: {summary.total_count}
- Low ratings (<{EVOLUTION_CONFIG['low_rating_threshold']}): {summary.low_rating_count}
- Average rating: {summary.avg_rating:.1f}/10

REPORTED ISSUES:
{issues_str}

SUGGESTIONS FROM FEEDBACK:
{suggestions_str}

RULES:
1. Make MINIMAL changes - only address the specific issues
2. Keep the same structure and style
3. Don't remove existing functionality
4. Be specific and actionable
5. For tool descriptions: explain WHEN to use the tool, not just what it does

⚠️ CRITICAL - CONTEXT LENGTH BUDGET:
- Tool descriptions: MAX 200 words (ideal: 50-100 words)
- Every extra word costs latency, money, and context space
- A concise description that covers 90% of cases is BETTER than verbose 100% coverage
- Prioritize: WHEN to use > WHAT it does > edge cases
- If the current description is already under 100 words, think twice before making it longer

OUTPUT FORMAT (JSON):
{{
  "improved_content": "The improved prompt/description text",
  "change_summary": "Brief description of what changed and why",
  "changes_made": ["change 1", "change 2"]
}}

Only output the JSON, nothing else."""
    
    def _parse_improvement_response(self, response: str, original: str) -> dict | None:
        """Parse the LLM improvement response."""
        try:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
                content = data.get('improved_content', '').strip()
                summary = data.get('change_summary', 'No summary provided')
                
                if content and content != original:
                    return {
                        'content': content,
                        'summary': summary
                    }
        except (json.JSONDecodeError, AttributeError):
            pass
        
        return None
    
    # ==================== Verification ====================
    
    def verify_candidate(self, candidate: EvolutionCandidate) -> tuple[bool, list[str]]:
        """Verify a candidate is valid before deployment."""
        errors = []
        warnings = []
        
        if candidate.component.startswith('tool:'):
            # Verify tool description - enforce context budget
            word_count = len(candidate.proposed_content.split())
            char_count = len(candidate.proposed_content)
            
            if char_count < 20:
                errors.append("Description too short (min 20 chars)")
            if char_count > 1500:
                errors.append(f"Description too long ({char_count} chars, max 1500)")
            if word_count > 200:
                errors.append(f"Description too verbose ({word_count} words, max 200)")
            elif word_count > 150:
                # Warning but allow
                warnings.append(f"Description approaching limit ({word_count}/200 words)")
            
            # Check if it's actually shorter than original (prefer concise)
            original_words = len(candidate.original_content.split())
            if word_count > original_words * 1.5:
                warnings.append(f"New description 50%+ longer than original ({word_count} vs {original_words} words)")
        
        if warnings:
            for w in warnings:
                print(f"    ⚠️  Warning: {w}")
            
            # Check for required elements
            content_lower = candidate.proposed_content.lower()
            if 'use' not in content_lower and 'when' not in content_lower:
                errors.append("Description should explain WHEN to use the tool")
        
        elif candidate.component == 'system_prompt':
            # System prompt verification
            if len(candidate.proposed_content) < 100:
                errors.append("System prompt too short")
        
        return len(errors) == 0, errors
    
    # ==================== Deployment ====================
    
    def deploy_candidate(self, candidate: EvolutionCandidate, activate: bool = True) -> tuple[bool, str]:
        """Deploy an evolution candidate."""
        
        # System prompt requires manual update - save suggestion only
        if candidate.component == 'system_prompt':
            self._save_system_prompt_suggestion(candidate)
            log_evolution_event("system_prompt_suggestion", {
                "mode": self.mode,
                "component": candidate.component,
                "change_summary": candidate.change_summary,
                "action": "saved_for_manual_review"
            })
            return True, "System prompt suggestion saved (requires manual review - see logs/evolution/system_prompt_suggestions.md)"
        
        # Check rate limit
        if not self.db.check_evolution_rate_limit():
            log_evolution_event("evolution_blocked", {
                "mode": self.mode,
                "component": candidate.component,
                "reason": "daily_limit_reached"
            })
            return False, "Daily evolution limit reached"
        
        # Verify
        valid, errors = self.verify_candidate(candidate)
        if not valid:
            log_evolution_event("evolution_verification_failed", {
                "mode": self.mode,
                "component": candidate.component,
                "errors": errors
            })
            return False, f"Verification failed: {', '.join(errors)}"
        
        # Get current active version for backup
        current = self.db.get_active_version(candidate.component)
        if current:
            self.db.create_backup(current.id, 'pre_evolution')
        
        # Determine component type
        if candidate.component == 'system_prompt':
            component_type = 'system'
        else:
            component_type = 'tool_description'
        
        # Create new version
        new_version = self.db.create_version(
            component=candidate.component,
            component_type=component_type,
            content=candidate.proposed_content,
            created_by='auto_evolution',
            parent_version_id=current.id if current else None,
            trigger_feedback_ids=candidate.trigger_feedback_ids,
            change_summary=candidate.change_summary,
            activate=activate
        )
        
        # If it's a tool, update the actual file
        if candidate.component.startswith('tool:') and activate:
            tool_name = candidate.component.replace('tool:', '')
            self._update_tool_file(tool_name, candidate.proposed_content)
        
        # Log the evolution to database
        self.db.log_evolution(
            action='evolution',
            component=candidate.component,
            from_version_id=current.id if current else None,
            to_version_id=new_version.id,
            trigger_type='low_feedback',
            trigger_details={
                'feedback_ids': candidate.trigger_feedback_ids,
                'change_summary': candidate.change_summary
            },
            status='success'
        )
        
        # Log to JSONL for Grafana/Loki
        log_evolution_event("evolution_deployed", {
            "mode": self.mode,
            "component": candidate.component,
            "from_version": current.version if current else None,
            "to_version": new_version.version,
            "change_summary": candidate.change_summary,
            "trigger_feedback_count": len(candidate.trigger_feedback_ids),
            "activated": activate
        })
        
        return True, f"Deployed version {new_version.version} for {candidate.component}"
    
    def _save_system_prompt_suggestion(self, candidate: EvolutionCandidate):
        """Save system prompt improvement suggestion for manual review."""
        suggestions_dir = Path(__file__).parent.parent / 'logs' / 'evolution'
        suggestions_dir.mkdir(parents=True, exist_ok=True)
        
        # Main file (appends all suggestions)
        suggestions_file = suggestions_dir / 'system_prompt_suggestions.md'
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        timestamp_file = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        entry = f"""
## Suggestion - {timestamp}

**Triggered by**: {len(candidate.trigger_feedback_ids)} low ratings

**Summary**: {candidate.change_summary}

**Feedback IDs**: {', '.join(candidate.trigger_feedback_ids[:5])}

### Suggested Changes

```
{candidate.proposed_content[:2000]}
```

---

"""
        
        # Append to main file
        with open(suggestions_file, 'a') as f:
            f.write(entry)
        
        # Also save individual timestamped file for tracking
        individual_file = suggestions_dir / f'system_prompt_suggestion_{timestamp_file}.md'
        with open(individual_file, 'w') as f:
            f.write(f"# System Prompt Suggestion\n")
            f.write(f"**Generated**: {timestamp}\n")
            f.write(f"**Mode**: {self.mode}\n\n")
            f.write(entry)
        
        # Create Canvas page for easy viewing
        self._create_canvas_page(candidate, timestamp)
        
        print(f"    📝 System prompt suggestion saved to: {suggestions_file}")
        print(f"    📄 Individual file: {individual_file}")
    
    def _create_canvas_page(self, candidate: EvolutionCandidate, timestamp: str):
        """Create a Canvas page for the suggestion (visible in Canvas UI)."""
        try:
            canvas_dir = Path(__file__).parent.parent / 'data' / 'canvas'
            canvas_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp_file = datetime.now().strftime('%Y%m%d_%H%M%S')
            page_file = canvas_dir / f'evolution_{timestamp_file}.json'
            
            # Canvas page format
            page_data = {
                "id": f"evolution_{timestamp_file}",
                "title": f"🔄 System Prompt Suggestion - {timestamp}",
                "content": f"""# System Prompt Evolution Suggestion

**Generated**: {timestamp}  
**Mode**: {self.mode}  
**Triggered by**: {len(candidate.trigger_feedback_ids)} low ratings

## Summary
{candidate.change_summary}

## Feedback IDs
{', '.join(candidate.trigger_feedback_ids[:5])}

## Suggested Changes

```
{candidate.proposed_content[:3000]}
```

---
*Review and apply manually to router_v2.py if appropriate.*
""",
                "created": datetime.now().isoformat(),
                "updated": datetime.now().isoformat(),
                "source": "evolution_system",
                "metadata": {
                    "type": "system_prompt_suggestion",
                    "mode": self.mode,
                    "feedback_count": len(candidate.trigger_feedback_ids)
                }
            }
            
            with open(page_file, 'w') as f:
                json.dump(page_data, f, indent=2)
            
            print(f"    🎨 Canvas page created: {page_file.name}")
        except Exception as e:
            # Don't fail the whole operation if canvas fails
            print(f"    ⚠️ Could not create Canvas page: {e}")
    
    def _update_tool_file(self, tool_name: str, new_description: str):
        """Update the tool.json file with new description."""
        tool_path = os.path.join(self.skills_dir, f'{tool_name}.tool.json')
        
        try:
            with open(tool_path, 'r') as f:
                data = json.load(f)
            
            data['description'] = new_description
            
            with open(tool_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            print(f"✅ Updated {tool_name}.tool.json")
            
            # Sync tools to update embeddings
            sync_script = os.path.join(os.path.dirname(__file__), '..', 'bin', 'sync-tools.py')
            if os.path.exists(sync_script):
                import subprocess
                subprocess.run([sys.executable, sync_script, self.mode], capture_output=True)
                print(f"✅ Synced tool embeddings")
                
        except Exception as e:
            print(f"⚠️  Failed to update tool file: {e}")
    
    # ==================== Degradation Detection ====================
    
    def check_degradation(self) -> list[dict]:
        """Check for performance degradation in active prompts."""
        degraded = []
        
        components = self.db.get_all_components()
        for component in components:
            active = self.db.get_active_version(component)
            if not active or active.times_used < 10:  # Need enough data
                continue
            
            # Compare recent vs historical performance
            # For now, use the version's own stats
            # In production, would compare to parent version
            if active.parent_version_id:
                parent = self.db.get_version(active.parent_version_id)
                if parent and parent.avg_rating and active.avg_rating:
                    drop_pct = ((parent.avg_rating - active.avg_rating) / parent.avg_rating) * 100
                    
                    if drop_pct >= EVOLUTION_CONFIG['degradation_rollback_pct']:
                        degraded.append({
                            'component': component,
                            'severity': 'critical',
                            'drop_pct': drop_pct,
                            'action': 'auto_rollback',
                            'current_rating': active.avg_rating,
                            'previous_rating': parent.avg_rating
                        })
                    elif drop_pct >= EVOLUTION_CONFIG['degradation_alert_pct']:
                        degraded.append({
                            'component': component,
                            'severity': 'warning',
                            'drop_pct': drop_pct,
                            'action': 'alert',
                            'current_rating': active.avg_rating,
                            'previous_rating': parent.avg_rating
                        })
        
        return degraded
    
    def auto_rollback_degraded(self) -> list[str]:
        """Automatically rollback critically degraded prompts."""
        degraded = self.check_degradation()
        rolled_back = []
        
        for item in degraded:
            # Log degradation detected
            log_evolution_event("degradation_detected", {
                "mode": self.mode,
                "component": item['component'],
                "severity": item['severity'],
                "drop_pct": item['drop_pct'],
                "current_rating": item['current_rating'],
                "previous_rating": item['previous_rating']
            })
            
            if item['severity'] == 'critical':
                success, msg = self.db.rollback(item['component'])
                if success:
                    rolled_back.append(item['component'])
                    print(f"🔙 Auto-rolled back {item['component']}: {msg}")
                    
                    # Log rollback
                    log_evolution_event("auto_rollback", {
                        "mode": self.mode,
                        "component": item['component'],
                        "reason": "critical_degradation",
                        "drop_pct": item['drop_pct']
                    })
        
        return rolled_back


# ==================== Main Evolution Loop ====================

def run_evolution_check(mode: str = 'cloud', auto_deploy: bool = False, dry_run: bool = True):
    """Run the evolution check process."""
    print(f"\n{'='*60}")
    print(f"Prompt Evolution Check - Mode: {mode}")
    print(f"{'='*60}\n")
    
    # Log check started
    log_evolution_event("evolution_check_started", {
        "mode": mode,
        "auto_deploy": auto_deploy,
        "dry_run": dry_run
    })
    
    engine = PromptEvolutionEngine(mode)
    
    # 1. Check for degradation first
    print("Step 1: Checking for degradation...")
    degraded = engine.check_degradation()
    if degraded:
        for item in degraded:
            print(f"  ⚠️  {item['component']}: {item['severity']} ({item['drop_pct']:.1f}% drop)")
        
        if auto_deploy and not dry_run:
            rolled_back = engine.auto_rollback_degraded()
            if rolled_back:
                print(f"  🔙 Auto-rolled back: {', '.join(rolled_back)}")
    else:
        print("  ✅ No degradation detected")
    
    # 2. Find evolution candidates
    print("\nStep 2: Finding evolution candidates...")
    candidates = engine.get_evolution_candidates()
    
    if not candidates:
        print("  ✅ No components need evolution")
        return
    
    print(f"  Found {len(candidates)} candidates:")
    for c in candidates:
        print(f"    - {c.component}: {c.low_rating_count} low ratings, avg {c.avg_rating:.1f}")
    
    # 3. Generate improvements
    print("\nStep 3: Generating improvements...")
    improvements = []
    
    for candidate in candidates[:3]:  # Limit to top 3
        print(f"  Generating for {candidate.component}...")
        improvement = engine.generate_improvement(candidate)
        if improvement:
            improvements.append(improvement)
            print(f"    ✅ Generated: {improvement.change_summary[:50]}...")
        else:
            print(f"    ⚠️  Could not generate improvement")
    
    if not improvements:
        print("  No improvements generated")
        return
    
    # 4. Deploy (if not dry run)
    print("\nStep 4: Deploying improvements...")
    if dry_run:
        print("  [DRY RUN - not deploying]")
        for imp in improvements:
            valid, errors = engine.verify_candidate(imp)
            status = "✅ VALID" if valid else f"❌ INVALID: {errors}"
            print(f"    - {imp.component}: {status}")
            print(f"      Summary: {imp.change_summary}")
    else:
        for imp in improvements:
            success, msg = engine.deploy_candidate(imp, activate=auto_deploy)
            status = "✅" if success else "❌"
            print(f"    {status} {imp.component}: {msg}")
    
    # 5. Check for capability gaps (potential new tools)
    print("\nStep 5: Checking for capability gaps...")
    gaps = detect_capability_gaps(engine.load_feedback())
    
    if gaps:
        print(f"  Found {len(gaps)} potential capability gaps:")
        for gap in gaps[:3]:  # Show top 3
            print(f"    - {gap['description'][:60]}...")
            print(f"      Mentioned {gap['count']} times, feedback IDs: {gap['feedback_ids'][:2]}")
        
        if auto_deploy and not dry_run:
            # LOOP PREVENTION: Don't build tools if we're already in tool builder context
            if os.environ.get('JARVIS_TOOL_BUILDER_CONTEXT') == 'true':
                print("\n  ⚠️  Skipping tool building (already in tool builder context)")
            else:
                print("\n  🔧 Auto-building tools for gaps...")
                try:
                    from tool_builder import ToolBuilder
                    builder = ToolBuilder(mode=mode)
                    
                    for gap in gaps[:2]:  # Build max 2 tools per run
                        print(f"    Building tool for: {gap['description'][:50]}...")
                        result = builder.build_tool(
                            gap_description=gap['description'],
                            feedback_ids=gap['feedback_ids'],
                            feedback_context=gap.get('context', '')
                        )
                        if result.success:
                            print(f"      ✅ Created: {result.tool_name}")
                        else:
                            print(f"      ⚠️  {result.status}: {result.message[:50]}")
                except Exception as e:
                    print(f"    ❌ Tool builder error: {e}")
        else:
            print("  [DRY RUN - not building tools]")
    else:
        print("  ✅ No capability gaps detected")
    
    print("\n" + "="*60)
    print("Evolution check complete")
    print("="*60)


def detect_capability_gaps(feedback: list[dict]) -> list[dict]:
    """
    Detect capability gaps from feedback - issues suggesting a missing tool.
    
    Looks for patterns like:
    - "no tool for X"
    - "had to use workaround"
    - "couldn't do X"
    - "missing capability"
    """
    import re
    from collections import defaultdict
    
    gap_patterns = [
        r"no tool (?:for|to) (.+?)(?:\.|,|$)",
        r"missing (?:tool|capability) (?:for|to) (.+?)(?:\.|,|$)",
        r"couldn't (?:find a tool|do) (.+?)(?:\.|,|$)",
        r"had to (?:use workaround|manually) (.+?)(?:\.|,|$)",
        r"would be useful to have (.+?)(?:\.|,|$)",
        r"need(?:s|ed)? a tool (?:for|to) (.+?)(?:\.|,|$)",
    ]
    
    gaps = defaultdict(lambda: {"count": 0, "feedback_ids": [], "context": ""})
    
    for entry in feedback:
        # Check issues array
        fb = entry.get('feedback', entry)
        issues = fb.get('issues', [])
        
        for issue in issues:
            desc = issue.get('description', '') + ' ' + issue.get('suggestion', '')
            
            for pattern in gap_patterns:
                match = re.search(pattern, desc.lower())
                if match:
                    gap_desc = match.group(1).strip()
                    # Normalize
                    gap_desc = gap_desc[:100]  # Limit length
                    
                    gaps[gap_desc]["count"] += 1
                    gaps[gap_desc]["feedback_ids"].append(
                        entry.get('feedback_id', entry.get('timestamp', 'unknown'))
                    )
                    gaps[gap_desc]["context"] = desc[:200]
        
        # Also check summary for gap mentions
        summary = fb.get('summary', '')
        for pattern in gap_patterns:
            match = re.search(pattern, summary.lower())
            if match:
                gap_desc = match.group(1).strip()[:100]
                gaps[gap_desc]["count"] += 1
                gaps[gap_desc]["feedback_ids"].append(
                    entry.get('feedback_id', entry.get('timestamp', 'unknown'))
                )
    
    # Filter to gaps mentioned at least 2 times (consistent pattern)
    MIN_GAP_COUNT = int(os.environ.get('EVOLUTION_MIN_GAP_COUNT', 2))
    
    result = []
    for desc, data in gaps.items():
        if data["count"] >= MIN_GAP_COUNT:
            result.append({
                "description": desc,
                "count": data["count"],
                "feedback_ids": list(set(data["feedback_ids"]))[:5],
                "context": data["context"]
            })
    
    # Sort by count (most mentioned first)
    result.sort(key=lambda x: x["count"], reverse=True)
    
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Run prompt evolution')
    parser.add_argument('mode', nargs='?', default='cloud', choices=['cloud', 'local'])
    parser.add_argument('--deploy', action='store_true', help='Actually deploy changes')
    parser.add_argument('--auto', action='store_true', help='Activate deployed changes immediately')
    args = parser.parse_args()
    
    run_evolution_check(
        mode=args.mode,
        auto_deploy=args.auto,
        dry_run=not args.deploy
    )

