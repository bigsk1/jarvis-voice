#!/usr/bin/env python3
"""
Evolution Test Tool

A simple tool for testing the prompt evolution system.
This tool intentionally has a vague description that should
be improved by the evolution system based on feedback.

Input: { "action": "echo|status|fail" }
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import json
from datetime import datetime

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        action = args.get('action', 'status')
        
        if action == 'echo':
            message = args.get('message', 'Hello from evolution test!')
            result = {
                "ok": True,
                "speech": f"Echo: {message}",
                "data": {
                    "action": "echo",
                    "message": message,
                    "timestamp": datetime.now().isoformat()
                }
            }
        
        elif action == 'status':
            result = {
                "ok": True,
                "speech": "Evolution test tool is working correctly",
                "data": {
                    "action": "status",
                    "status": "operational",
                    "version": "1.0",
                    "purpose": "Testing prompt evolution system",
                    "timestamp": datetime.now().isoformat()
                }
            }
        
        elif action == 'fail':
            # Intentionally fail for testing error handling
            raise ValueError("Intentional failure for testing")
        
        else:
            result = {
                "ok": False,
                "speech": f"Unknown action: {action}",
                "data": {"error": f"Unknown action: {action}"}
            }
        
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Evolution test failed: {e}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()

