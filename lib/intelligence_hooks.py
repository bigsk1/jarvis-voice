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
from typing import Dict, Any, List, Optional
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

logger = logging.getLogger(__name__)

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
) -> bool:
    """
    Record an interaction as an experience for learning.
    
    Call this after each completed interaction in the orchestrator.
    
    Args:
        query: Original user query
        tools_used: List of tools invoked
        result: The final result dict from orchestrator
        conversation_context: Optional list of conversation turns
    
    Returns:
        True if recorded successfully, False otherwise
    """
    intel = _get_intel()
    if not intel:
        return False
    
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
        
        # Context summary
        context = {
            'tools_available': len(tools_used) > 0,
            'multi_turn': len(tools_used) > 1,
            'timestamp': datetime.now().isoformat()
        }
        
        # Run async in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            exp_id = loop.run_until_complete(
                intel.record_experience(
                    query=query,
                    tools_used=tools_used,
                    outcome=outcome,
                    context=context,
                    user_signals=user_signals
                )
            )
            logger.debug(f"Recorded experience {exp_id} for query: {query[:50]}...")
            return True
        finally:
            loop.close()
        
    except Exception as e:
        logger.warning(f"Failed to record experience: {e}")
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
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Get tool biases
            biases = loop.run_until_complete(intel.get_tool_biases(query))
            
            # Get relevant insights
            insights = loop.run_until_complete(intel.get_relevant_insights(query, top_k=3))
            
            # Calculate overall confidence
            if insights:
                avg_confidence = sum(i['confidence'] for i in insights) / len(insights)
            else:
                avg_confidence = 0.0
            
            return {
                'tool_biases': biases,
                'insights': [
                    {
                        'description': i['insight'],
                        'applies_to': i['applies_to'],
                        'relevance': round(i['relevance'], 3)
                    }
                    for i in insights
                ],
                'confidence': round(avg_confidence, 3)
            }
        finally:
            loop.close()
            
    except Exception as e:
        logger.warning(f"Failed to get routing insights: {e}")
        return {'tool_biases': {}, 'insights': [], 'confidence': 0.0}


def format_insights_for_prompt(insights: Dict[str, Any]) -> str:
    """
    Format insights as context for the routing prompt.
    
    Returns a string that can be injected into the system prompt.
    """
    if not insights.get('insights'):
        return ""
    
    lines = ["=== LEARNED INSIGHTS ==="]
    lines.append(f"(Confidence: {insights['confidence']:.0%})")
    lines.append("")
    
    for i, insight in enumerate(insights['insights'], 1):
        lines.append(f"{i}. {insight['description']}")
        if insight['applies_to']:
            lines.append(f"   Applies to: {insight['applies_to']}")
    
    if insights.get('tool_biases'):
        lines.append("")
        lines.append("Tool preferences based on past experience:")
        for tool, bias in sorted(insights['tool_biases'].items(), key=lambda x: -x[1]):
            direction = "prefer" if bias > 0 else "avoid"
            lines.append(f"  - {tool}: {direction} ({bias:+.2f})")
    
    lines.append("")
    return "\n".join(lines)


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
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            processed = loop.run_until_complete(
                intel.process_reflection_queue(batch_size)
            )
            if processed > 0:
                logger.info(f"Processed {processed} reflections")
            return processed
        finally:
            loop.close()
            
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
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(intel.evaluate_learning_quality())
        finally:
            loop.close()
            
    except Exception as e:
        logger.warning(f"Learning evaluation failed: {e}")
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

