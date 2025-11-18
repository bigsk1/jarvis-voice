#!/usr/bin/env python3
"""
Tool Name: query_service_logs
Query background service logs for monitoring and debugging
Input: { "service": "follow_up|self_healing|reminder_scheduler|all", "event_type": "action|error|check|startup|shutdown", "limit": 20 }
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from service_logger import ServiceLogger


def get_service_logs(service_name: str, event_type: str = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Get logs for a specific service."""
    logger = ServiceLogger(service_name)
    
    if event_type:
        return logger.get_logs_by_event(event_type, limit)
    else:
        return logger.get_recent_logs(limit)


def get_service_stats(service_name: str) -> Dict[str, Any]:
    """Get statistics for a service."""
    logger = ServiceLogger(service_name)
    return logger.get_stats()


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        service = args.get('service', 'all')
        event_type = args.get('event_type')
        limit = args.get('limit', 20)
        show_stats = args.get('show_stats', False)
        
        # Validate service
        valid_services = ['follow_up_daemon', 'self_healing_daemon', 'reminder_scheduler', 'all']
        if service not in valid_services and service not in ['follow_up', 'self_healing', 'reminder']:
            # Allow short names
            service_map = {
                'follow_up': 'follow_up_daemon',
                'self_healing': 'self_healing_daemon',
                'reminder': 'reminder_scheduler'
            }
            service = service_map.get(service, service)
        
        # Map short service names to full names
        if service == 'follow_up':
            service = 'follow_up_daemon'
        elif service == 'self_healing':
            service = 'self_healing_daemon'
        elif service == 'reminder':
            service = 'reminder_scheduler'
        
        result_data = {}
        
        # Get stats if requested
        if show_stats:
            if service == 'all':
                stats = {}
                for svc in ['follow_up_daemon', 'self_healing_daemon', 'reminder_scheduler']:
                    stats[svc] = get_service_stats(svc)
                result_data['stats'] = stats
            else:
                result_data['stats'] = get_service_stats(service)
        
        # Get logs
        if service == 'all':
            all_logs = {}
            for svc in ['follow_up_daemon', 'self_healing_daemon', 'reminder_scheduler']:
                all_logs[svc] = get_service_logs(svc, event_type, limit // 3)
            result_data['logs'] = all_logs
        else:
            result_data['logs'] = get_service_logs(service, event_type, limit)
        
        # Build speech response
        speech = build_speech_response(service, result_data, event_type, show_stats)
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": result_data
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to query service logs: {e}"
        }))
        sys.exit(1)


def build_speech_response(service: str, data: Dict[str, Any], event_type: str, show_stats: bool) -> str:
    """Build human-readable speech response."""
    
    if show_stats:
        # Stats summary
        if service == 'all':
            stats = data.get('stats', {})
            total_actions = sum(s.get('total_actions', 0) for s in stats.values())
            total_errors = sum(s.get('total_errors', 0) for s in stats.values())
            
            speech = f"Service statistics: {total_actions} total actions, {total_errors} errors. "
            
            for svc_name, svc_stats in stats.items():
                svc_display = svc_name.replace('_daemon', '').replace('_scheduler', '').replace('_', ' ')
                actions = svc_stats.get('total_actions', 0)
                errors = svc_stats.get('total_errors', 0)
                speech += f"{svc_display}: {actions} actions"
                if errors > 0:
                    speech += f" ({errors} errors)"
                speech += ". "
        else:
            stats = data.get('stats', {})
            svc_display = service.replace('_daemon', '').replace('_scheduler', '').replace('_', ' ')
            actions = stats.get('total_actions', 0)
            errors = stats.get('total_errors', 0)
            
            speech = f"{svc_display} statistics: {actions} actions, {errors} errors"
            
            if errors > 0 and stats.get('last_error'):
                last_error = stats['last_error']
                speech += f". Last error: {last_error.get('error', 'unknown')}"
        
        return speech
    
    # Log summary
    if service == 'all':
        logs = data.get('logs', {})
        total_entries = sum(len(log_list) for log_list in logs.values())
        
        if total_entries == 0:
            return "No recent service logs found"
        
        speech = f"Found {total_entries} log entries across all services. "
        
        # Count errors
        error_count = 0
        for log_list in logs.values():
            error_count += sum(1 for entry in log_list if entry.get('event') == 'error')
        
        if error_count > 0:
            speech += f"Warning: {error_count} error entries found. "
    else:
        logs = data.get('logs', [])
        
        if len(logs) == 0:
            return f"No recent logs found for {service.replace('_', ' ')}"
        
        svc_display = service.replace('_daemon', '').replace('_scheduler', '').replace('_', ' ')
        speech = f"Found {len(logs)} log entries for {svc_display}. "
        
        # Check for recent errors
        error_logs = [entry for entry in logs if entry.get('event') == 'error']
        if len(error_logs) > 0:
            speech += f"Warning: {len(error_logs)} error entries. "
            # Mention most recent error
            if error_logs:
                latest_error = error_logs[0]
                speech += f"Latest error: {latest_error.get('error', 'unknown')}"
        else:
            # Mention recent actions
            action_logs = [entry for entry in logs if entry.get('event') == 'action']
            if action_logs:
                speech += f"{len(action_logs)} actions logged. "
                if len(action_logs) > 0:
                    latest = action_logs[0]
                    action = latest.get('action', 'unknown')
                    speech += f"Latest: {action}"
    
    return speech


if __name__ == "__main__":
    main()

