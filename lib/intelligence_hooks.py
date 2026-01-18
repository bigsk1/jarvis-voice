#!/usr/bin/env python3
"""
Intelligence Integration Hooks

Integrates the intelligence layer with the orchestrator:
1. Record experiences after interactions
2. Get learned insights before routing
3. Process reflections asynchronously

Usage:
    from intelligence_hooks import (
        record_interaction,
        get_routing_insights,
        trigger_reflection
    )
"""

import os
import sys
import json
import asyncio
import logging
import concurrent.futures
from typing import Dict, Any, List, Optional
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

logger = logging.getLogger(__name__)


def _run_async(coro):
    """
    Run an async coroutine from sync context.
    
    Handles both standalone execution and when called from within
    an existing event loop (e.g., FastAPI).
    """
    try:
        # Check if there's already a running event loop (e.g., FastAPI)
        loop = asyncio.get_running_loop()
        # Already in async context - run in thread to avoid blocking
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)

# Lazy import to avoid circular dependencies
_intelligence_layer = None
_intelligence_checked = False

def _is_intelligence_enabled() -> bool:
    """Check if intelligence is enabled via config.
    
    Set JARVIS_INTELLIGENCE=false in config/cloud.env or config/local.env to disable.
    """
    from config_loader import get_config_value
    enabled = get_config_value('JARVIS_INTELLIGENCE', 'true').lower()
    return enabled in ('true', '1', 'yes', 'on')

def _get_intel():
    """Lazy load intelligence layer (if enabled)."""
    global _intelligence_layer, _intelligence_checked
    
    # Check if disabled
    if not _is_intelligence_enabled():
        return None
    
    if _intelligence_layer is None and not _intelligence_checked:
        _intelligence_checked = True
        try:
            from intelligence import get_intelligence_layer
            _intelligence_layer = get_intelligence_layer()
            logger.info("Intelligence layer initialized")
        except Exception as e:
            logger.warning(f"Intelligence layer unavailable: {e}")
            _intelligence_layer = False  # Mark as failed, don't retry
    
    return _intelligence_layer if _intelligence_layer else None


# ============================================
# EXPERIENCE RECORDING (After interaction)
# ============================================

def record_interaction(
    query: str,
    tools_used: List[str],
    result: Dict[str, Any],
    conversation_context: Optional[List[Dict]] = None
) -> int:
    """
    Record an interaction as an experience for learning.
    
    Call this after each completed interaction in the orchestrator.
    
    Args:
        query: Original user query
        tools_used: List of tools invoked
        result: The final result dict from orchestrator (contains speech, data, ok, etc.)
        conversation_context: Optional list of conversation turns
    
    Returns:
        Experience ID if recorded successfully, -1 otherwise
    """
    intel = _get_intel()
    if not intel:
        return -1
    
    try:
        # Extract outcome signals
        outcome = {
            'success': result.get('ok', True),
            'turns': len(tools_used),
            'error': result.get('error'),
            'max_turns_reached': result.get('max_turns_reached', False),
            'duplicate_prevented': result.get('duplicate_prevented', False)
        }
        
        # Infer user signals from context
        user_signals = _infer_user_signals(query, result, conversation_context)
        
        # ============================================
        # CRITICAL: Capture LLM response and tool data
        # This enables reflection to evaluate CONTENT quality
        # ============================================
        
        # LLM's final response to user (the speech output)
        llm_response = result.get('speech', '')
        
        # Actual tool results (data returned by tools)
        tool_results = result.get('data', {})
        
        # Tools that were AVAILABLE to the LLM (from Tool RAG + ghost tools)
        # This is critical for reflection - shows what LLM COULD have chosen
        available_tools = result.get('available_tools', [])
        
        # Truncate to prevent DB bloat but keep enough for evaluation
        if len(llm_response) > 2000:
            llm_response = llm_response[:2000] + "... [truncated]"
        
        # Serialize tool results, truncate if too large
        tool_results_str = json.dumps(tool_results, default=str)
        if len(tool_results_str) > 5000:
            tool_results_str = tool_results_str[:5000] + "... [truncated]"
        
        # Context summary with full data
        context = {
            'tools_available': len(tools_used) > 0,
            'multi_turn': len(tools_used) > 1,
            'timestamp': datetime.now().isoformat(),
            # NEW: Include response content for reflection
            'llm_response': llm_response,
            'tool_results': tool_results_str,
            # CRITICAL: What tools the LLM could have chosen from
            'available_tools': available_tools
        }
        
        # Run async in sync context (handles FastAPI and standalone)
        exp_id = _run_async(
            intel.record_experience(
                query=query,
                tools_used=tools_used,
                outcome=outcome,
                context=context,
                user_signals=user_signals
            )
        )
        
        logger.debug(f"Recorded experience {exp_id} for query: {query[:50]}...")
        return exp_id  # Return the experience ID for feedback linking
        
    except Exception as e:
        logger.warning(f"Failed to record experience: {e}")
        return -1


def update_experience_from_feedback(
    experience_id: int,
    feedback_rating: int,
    feedback_summary: str = None
) -> bool:
    """
    Update experience outcome based on feedback rating.
    
    This is the FEEDBACK → INTELLIGENCE BRIDGE:
    - Rating 4-5: Confirm success (no change needed)
    - Rating 1-2: Mark as failure (retroactive correction)
    - Rating 3: Leave as-is (ambiguous)
    
    Args:
        experience_id: The experience to update
        feedback_rating: Rating from feedback system (1-5)
        feedback_summary: Optional summary from feedback
    
    Returns:
        True if updated, False otherwise
    """
    if experience_id < 0:
        return False
    
    intel = _get_intel()
    if not intel:
        return False
    
    # Only correct on clear failure (rating 1-2)
    # Rating 3 is ambiguous, 4-5 confirms success
    if feedback_rating >= 3:
        logger.debug(f"Experience {experience_id}: rating {feedback_rating} confirms/leaves success")
        return True  # No correction needed
    
    try:
        # Retroactively mark as failure
        cursor = intel.conn.cursor()
        cursor.execute("""
            UPDATE experiences 
            SET outcome_success = 0, 
                user_satisfied = 0
            WHERE id = ?
        """, (experience_id,))
        intel.conn.commit()
        
        rows_updated = cursor.rowcount
        if rows_updated > 0:
            logger.info(f"Experience {experience_id}: corrected to FAILURE based on rating {feedback_rating}")
            
            # Increase priority in reflection queue (failures are valuable learning)
            cursor.execute("""
                UPDATE reflection_queue 
                SET priority = MAX(priority, 0.8)
                WHERE experience_id = ?
            """, (experience_id,))
            intel.conn.commit()
            
        return rows_updated > 0
        
    except Exception as e:
        logger.warning(f"Failed to update experience {experience_id}: {e}")
        return False


def _infer_user_signals(
    query: str,
    result: Dict[str, Any],
    conversation_context: Optional[List[Dict]]
) -> Dict[str, bool]:
    """Infer user satisfaction signals from available data."""
    signals = {
        'thanked': False,
        'clarified': False,
        'retried': False
    }
    
    # Check for failure indicators
    if not result.get('ok', True):
        signals['retried'] = True  # Assume retry if failed
    
    # Check if max turns reached (indicates struggle)
    if result.get('max_turns_reached'):
        signals['clarified'] = True  # Task was complex
    
    # Check conversation context for patterns
    if conversation_context:
        query_lower = query.lower()
        
        # Look for clarification patterns
        clarification_patterns = ['what i meant', 'no i want', 'not that', 'i said']
        for pattern in clarification_patterns:
            if pattern in query_lower:
                signals['clarified'] = True
                break
        
        # Look for retry patterns
        retry_patterns = ['try again', 'one more time', 'retry', 'do it again']
        for pattern in retry_patterns:
            if pattern in query_lower:
                signals['retried'] = True
                break
    
    return signals


# ============================================
# ROUTING INSIGHTS (Before routing)
# ============================================

def get_routing_insights(query: str) -> Dict[str, Any]:
    """
    Get learned insights to inform routing decisions.
    
    Call this before routing to get biases based on past learning.
    
    Args:
        query: The user's query
    
    Returns:
        Dict with:
        - tool_biases: Dict of tool_name -> preference score
        - insights: List of relevant insight descriptions
        - confidence: Overall confidence in these insights
    """
    intel = _get_intel()
    if not intel:
        return {'tool_biases': {}, 'insights': [], 'confidence': 0.0}
    
    try:
        # Get tool biases and insights (handles FastAPI and standalone)
        biases = _run_async(intel.get_tool_biases(query))
        insights = _run_async(intel.get_relevant_insights(query, top_k=3))
        
        # Calculate overall confidence
        if insights:
            avg_confidence = sum(i['confidence'] for i in insights) / len(insights)
        else:
            avg_confidence = 0.0
        
        result = {
            'tool_biases': biases,
            'insights': [
                {
                    'id': i.get('id'),
                    'description': i['insight'],
                    'applies_to': i['applies_to'],
                    'relevance': round(i['relevance'], 3),
                    # PHASE 1: New fields
                    'constraint_type': i.get('constraint_type', 'positive'),
                    'avoided_tools': i.get('avoided_tools', []),
                    'reasoning': i.get('reasoning', '')
                }
                for i in insights
            ],
            'confidence': round(avg_confidence, 3)
        }
        
        # Log when insights are being applied
        if insights or biases:
            try:
                from intelligence import get_intel_logger
                get_intel_logger().log_insights_applied(query, insights, biases)
            except Exception:
                pass  # Don't let logging break the main flow
        
        return result
            
    except Exception as e:
        logger.warning(f"Failed to get routing insights: {e}")
        return {'tool_biases': {}, 'insights': [], 'confidence': 0.0}


def format_insights_for_prompt(insights: Dict[str, Any], available_tools: List[str] = None) -> str:
    """
    Format insights as context for the routing prompt.
    
    PHASE 1 UPGRADES:
    - Separates positive constraints (WHAT TO DO) from negative (WHAT NOT TO DO)
    - LLMs respond better to explicitly labeled failures
    
    PHASE 2 UPGRADE:
    - Filters out insights recommending unavailable/blocked tools
    - Safe for cross-mode sync (cloud→local, local→cloud)
    
    Args:
        insights: Dict with insights, tool_biases, confidence
        available_tools: List of tool names currently available (if None, no filtering)
    
    Returns a string that can be injected into the system prompt.
    """
    if not insights.get('insights'):
        return ""
    
    # Filter insights if available_tools provided
    all_insights = insights['insights']
    if available_tools:
        available_set = set(available_tools)
        
        def insight_has_available_tools(insight):
            """Check if insight references only available tools."""
            # Check applies_to field (tool recommendations)
            applies_to = insight.get('applies_to', '')
            if applies_to:
                # Simple heuristic: if any word in applies_to matches a tool name, check it
                for tool in available_set:
                    if tool in applies_to:
                        return True
                # If applies_to mentions specific tools but none are available, skip
                # But if it's general advice (no tool names), keep it
                for word in applies_to.split():
                    if word.startswith('mcp_') or word.endswith('_tool') or '_' in word:
                        # Looks like a tool name but not in available set
                        return False
            return True  # General advice, keep it
        
        all_insights = [i for i in all_insights if insight_has_available_tools(i)]
    
    # Separate positive and negative constraints
    positive_insights = [i for i in all_insights if i.get('constraint_type', 'positive') == 'positive']
    negative_insights = [i for i in all_insights if i.get('constraint_type') == 'negative']
    
    lines = []
    
    # Positive constraints (what TO do)
    if positive_insights:
        lines.append("=== LEARNED STRATEGIES (WHAT TO DO) ===")
        lines.append(f"(Based on {len(positive_insights)} successful patterns)")
        lines.append("")
        for insight in positive_insights:
            lines.append(f"✅ {insight['description']}")
            if insight.get('applies_to'):
                lines.append(f"   → Applies to: {insight['applies_to']}")
        lines.append("")
    
    # Negative constraints (what NOT to do) - LLMs respond strongly to explicit failures
    if negative_insights:
        lines.append("=== KNOWN FAILURES - AVOID THESE ===")
        lines.append("⚠️  These approaches have FAILED in the past:")
        lines.append("")
        for insight in negative_insights:
            lines.append(f"❌ {insight['description']}")
            if insight.get('avoided_tools'):
                tools = ', '.join(insight['avoided_tools'])
                lines.append(f"   → DO NOT use: {tools}")
            if insight.get('reasoning'):
                # Show full reasoning (truncated was causing confusion - e.g., ending mid-word)
                lines.append(f"   → Why: {insight['reasoning']}")
        lines.append("")
    
    # Tool biases summary (filtered to available tools)
    if insights.get('tool_biases'):
        biases = insights['tool_biases']
        
        # Filter to available tools if list provided
        if available_tools:
            available_set = set(available_tools)
            biases = {k: v for k, v in biases.items() if k in available_set}
        
        prefer_tools = {k: v for k, v in biases.items() if v > 0}
        avoid_tools = {k: v for k, v in biases.items() if v < 0}
        
        if prefer_tools or avoid_tools:
            lines.append("=== TOOL PREFERENCES ===")
            
            if prefer_tools:
                for tool, bias in sorted(prefer_tools.items(), key=lambda x: -x[1]):
                    lines.append(f"  ✅ PREFER: {tool} (+{bias:.2f})")
            
            if avoid_tools:
                for tool, bias in sorted(avoid_tools.items(), key=lambda x: x[1]):
                    lines.append(f"  ❌ AVOID: {tool} ({bias:.2f})")
            
            lines.append("")
    
    # Overall confidence
    if insights.get('confidence', 0) > 0:
        lines.append(f"(Overall confidence in these insights: {insights['confidence']:.0%})")
        lines.append("")
    
    return "\n".join(lines)


# ============================================
# INSIGHT OUTCOME TRACKING
# ============================================

def track_insight_outcomes(
    insights: List[Dict[str, Any]],
    tools_used: List[str],
    result: Dict[str, Any]
) -> int:
    """
    Track whether applied insights were helpful based on interaction outcome.
    
    This enables:
    - Confidence decay for bad insights
    - Confidence boost for good insights
    - Parameter tuning based on real effectiveness
    
    Args:
        insights: List of insight dicts that were shown to LLM (from get_routing_insights)
        tools_used: List of tools actually used in the interaction
        result: Final result dict with 'ok', 'speech', etc.
    
    Returns:
        Number of insights tracked
    """
    intel = _get_intel()
    if not intel or not insights:
        return 0
    
    tracked = 0
    outcome_success = result.get('ok', True)
    
    try:
        for insight in insights:
            insight_id = insight.get('id')
            if not insight_id:
                continue
            
            # Determine if this insight was helpful
            was_helpful = _evaluate_insight_helpfulness(
                insight=insight,
                tools_used=tools_used,
                outcome_success=outcome_success
            )
            
            # Record the usage (handles FastAPI and standalone)
            _run_async(
                intel.record_insight_usage(
                    insight_id=insight_id,
                    was_helpful=was_helpful,
                    outcome='success' if outcome_success else 'failure'
                )
            )
            tracked += 1
            
            logger.debug(f"Tracked insight {insight_id}: helpful={was_helpful}")
        
        return tracked
            
    except Exception as e:
        logger.warning(f"Failed to track insight outcomes: {e}")
        return tracked


def _evaluate_insight_helpfulness(
    insight: Dict[str, Any],
    tools_used: List[str],
    outcome_success: bool
) -> bool:
    """
    Evaluate whether an insight was helpful for this interaction.
    
    CORRECTED LOGIC (Nov 2025):
    
    POSITIVE insight ("prefer X"):
    - X was used + success → HELPFUL (advice followed, worked)
    - X was used + failure → NOT helpful (advice followed, didn't work)
    - X not used + success → NOT helpful (advice ignored, still worked = advice wasn't needed)
    - X not used + failure → NOT helpful (advice ignored, failed = should have followed?)
    
    NEGATIVE insight ("avoid Y"):
    - Y not used + success → HELPFUL (advice followed, worked)
    - Y not used + failure → NOT helpful (advice followed, still failed)
    - Y was used + success → NOT helpful (advice ignored, still worked = advice was WRONG)
    - Y was used + failure → UNCLEAR, count as helpful (advice was correct, should have avoided)
    
    Key insight: When advice is CONTRADICTED and the outcome is SUCCESS, 
    the advice was WRONG and should be marked NOT helpful.
    """
    constraint_type = insight.get('constraint_type', 'positive')
    avoided_tools = insight.get('avoided_tools', [])
    
    # Parse avoided_tools if it's a string
    if isinstance(avoided_tools, str):
        try:
            avoided_tools = json.loads(avoided_tools) if avoided_tools else []
        except:
            avoided_tools = [avoided_tools] if avoided_tools else []
    
    if constraint_type == 'negative':
        # Negative constraint: "avoid these tools"
        tools_violated = [t for t in avoided_tools if t in tools_used]
        
        if not tools_violated:
            # Followed the advice (avoided the tool)
            # Helpful only if outcome was successful
            return outcome_success
        else:
            # VIOLATED the advice (used the tool we were told to avoid)
            if outcome_success:
                # The tool we were told to avoid actually WORKED!
                # This means the "avoid" advice was WRONG → NOT helpful
                logger.debug(f"Negative insight contradicted: avoided_tools={avoided_tools} were used successfully")
                return False
            else:
                # Used the avoided tool and FAILED
                # The advice was correct (should have avoided) → helpful
                return True
    else:
        # Positive constraint: "prefer these tools"
        # For simplicity, just use outcome success
        # Future enhancement: check if preferred_tools were actually used
        return outcome_success


# ============================================
# REFLECTION PROCESSING (Background)
# ============================================

def trigger_reflection(batch_size: int = 3) -> int:
    """
    Process pending reflections in the queue.
    
    Can be called periodically or after N interactions.
    
    Args:
        batch_size: Number of reflections to process
    
    Returns:
        Number of reflections processed
    """
    intel = _get_intel()
    if not intel:
        return 0
    
    try:
        processed = _run_async(intel.process_reflection_queue(batch_size))
        if processed > 0:
            logger.info(f"Processed {processed} reflections")
        return processed
            
    except Exception as e:
        logger.warning(f"Reflection processing failed: {e}")
        return 0


def get_learning_stats() -> Dict[str, Any]:
    """Get current learning statistics."""
    intel = _get_intel()
    if not intel:
        return {'status': 'unavailable'}
    
    return intel.get_stats()


# ============================================
# META-COGNITION (Periodic evaluation)
# ============================================

def evaluate_learning() -> Dict[str, Any]:
    """
    Evaluate the quality of the learning process.
    
    Returns analysis of learning quality with potential issues.
    """
    intel = _get_intel()
    if not intel:
        return {'status': 'unavailable'}
    
    try:
        return _run_async(intel.evaluate_learning_quality())
            
    except Exception as e:
        logger.warning(f"Learning evaluation failed: {e}")
        return {'status': 'error', 'error': str(e)}


# ============================================
# MAINTENANCE JOBS
# ============================================

def run_decay_job(force: bool = False) -> Dict[str, Any]:
    """
    Run the confidence decay job.
    
    Reduces confidence of stale/unused insights based on DECAY_RATE.
    
    IMPORTANT: This job should only run once per decay period (default: 7 days).
    Running multiple times will be skipped unless force=True.
    
    Args:
        force: If True, bypass minimum interval check (use with caution!)
    
    Returns:
        Stats about decayed/pruned insights
    """
    intel = _get_intel()
    if not intel:
        return {'status': 'unavailable'}
    
    try:
        return _run_async(intel.run_decay_job(force=force))
    except Exception as e:
        logger.warning(f"Decay job failed: {e}")
        return {'status': 'error', 'error': str(e)}


def run_anomaly_detection() -> Dict[str, Any]:
    """
    Run anomaly detection on recent experiences.
    
    Flags experiences that deviate significantly from norms.
    Uses ANOMALY_THRESHOLD from config.
    
    Returns:
        Stats and list of detected anomalies
    """
    intel = _get_intel()
    if not intel:
        return {'status': 'unavailable'}
    
    try:
        return _run_async(intel.run_anomaly_detection())
    except Exception as e:
        logger.warning(f"Anomaly detection failed: {e}")
        return {'status': 'error', 'error': str(e)}


def run_meta_cognition() -> Dict[str, Any]:
    """
    Run meta-cognition analysis.
    
    Higher-level reflection on the learning process:
    - Detects blind spots (repeated failures)
    - Detects over-generalization
    - Assesses learning quality
    
    Returns:
        Findings and actions taken
    """
    intel = _get_intel()
    if not intel:
        return {'status': 'unavailable'}
    
    try:
        return _run_async(intel.run_meta_cognition())
    except Exception as e:
        logger.warning(f"Meta-cognition failed: {e}")
        return {'status': 'error', 'error': str(e)}


def run_all_maintenance(force: bool = False) -> Dict[str, Any]:
    """
    Run all maintenance jobs (decay, anomaly, meta-cognition).
    
    Args:
        force: If True, bypass minimum interval check for decay job
    
    Returns:
        Combined results from all jobs
    """
    intel = _get_intel()
    if not intel:
        return {'status': 'unavailable'}
    
    try:
        return _run_async(intel.run_all_maintenance(force=force))
    except Exception as e:
        logger.warning(f"Maintenance failed: {e}")
        return {'status': 'error', 'error': str(e)}


# ============================================
# CLI for testing
# ============================================

if __name__ == "__main__":
    # Test the hooks
    print("Testing Intelligence Hooks\n")
    
    print("1. Recording test interaction...")
    success = record_interaction(
        query="What is the price of bitcoin?",
        tools_used=["crypto_price"],
        result={"ok": True, "speech": "Bitcoin is $90,000"}
    )
    print(f"   Recorded: {success}")
    
    print("\n2. Getting routing insights for similar query...")
    insights = get_routing_insights("What's ethereum worth?")
    print(f"   Insights: {json.dumps(insights, indent=4)}")
    
    print("\n3. Formatted for prompt:")
    formatted = format_insights_for_prompt(insights)
    print(formatted if formatted else "   (No insights yet)")
    
    print("\n4. Learning stats:")
    stats = get_learning_stats()
    print(f"   {json.dumps(stats, indent=4)}")
    
    print("\n5. Triggering reflection...")
    processed = trigger_reflection(batch_size=1)
    print(f"   Processed: {processed} reflections")
    
    print("\n6. Learning evaluation:")
    evaluation = evaluate_learning()
    print(f"   {json.dumps(evaluation, indent=4)}")

