#!/usr/bin/env python3
"""
Tool Name: Speaker Volume Control
Description: Adjust the volume of Jarvis's speaker output
Input: { "action": "set|up|down|get", "level": 50 }
Output: { "ok": bool, "speech": str, "data": { "volume": int } }
"""

import sys
import os
import json
import subprocess
import re

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value


def get_card_name() -> str:
    """Extract card name from OUT_DEV config (e.g., 'plughw:CARD=Generic_1,DEV=0' -> 'Generic_1')."""
    out_dev = get_config_value('OUT_DEV', '')
    
    # Parse CARD= from OUT_DEV
    match = re.search(r'CARD=([^,\s]+)', out_dev)
    if match:
        return match.group(1)
    
    # Fallback to default if not found
    return 'default'


def get_current_volume(card: str) -> int:
    """Get current volume percentage using amixer."""
    try:
        # Try common control names
        for control in ['Master', 'PCM', 'Speaker', 'Headphone']:
            result = subprocess.run(
                ['amixer', '-c', card, 'sget', control],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and '%' in result.stdout:
                # Parse volume percentage from output like "[50%]"
                match = re.search(r'\[(\d+)%\]', result.stdout)
                if match:
                    return int(match.group(1))
        
        # If card-specific failed, try without card
        result = subprocess.run(
            ['amixer', 'sget', 'Master'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            match = re.search(r'\[(\d+)%\]', result.stdout)
            if match:
                return int(match.group(1))
                
    except Exception as e:
        print(f"Error getting volume: {e}", file=sys.stderr)
    
    return -1  # Unknown


def set_volume(card: str, level: int) -> bool:
    """Set volume to specific percentage using amixer."""
    level = max(0, min(100, level))  # Clamp to 0-100
    
    try:
        # Try common control names
        for control in ['Master', 'PCM', 'Speaker', 'Headphone']:
            result = subprocess.run(
                ['amixer', '-c', card, 'sset', control, f'{level}%'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True
        
        # Fallback without card
        result = subprocess.run(
            ['amixer', 'sset', 'Master', f'{level}%'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
        
    except Exception as e:
        print(f"Error setting volume: {e}", file=sys.stderr)
        return False


def adjust_volume(card: str, delta: int) -> tuple[bool, int]:
    """Adjust volume by delta percentage. Returns (success, new_level)."""
    current = get_current_volume(card)
    if current < 0:
        current = 50  # Assume 50% if unknown
    
    new_level = max(0, min(100, current + delta))
    success = set_volume(card, new_level)
    
    return success, new_level


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()
        
        # Get parameters
        action = args.get('action', 'get').lower()
        level = args.get('level')
        
        # Get card name from config
        card = get_card_name()
        
        # Handle actions
        if action == 'get':
            volume = get_current_volume(card)
            if volume >= 0:
                print(json.dumps({
                    "ok": True,
                    "speech": f"Speaker volume is at {volume} percent",
                    "data": {"volume": volume, "card": card}
                }))
            else:
                print(json.dumps({
                    "ok": False,
                    "speech": "Couldn't read the current volume",
                    "error": "Failed to get volume"
                }))
                sys.exit(1)
                
        elif action == 'set':
            if level is None:
                raise ValueError("Level is required for 'set' action")
            
            level = int(level)
            if set_volume(card, level):
                print(json.dumps({
                    "ok": True,
                    "speech": f"Volume set to {level} percent",
                    "data": {"volume": level, "card": card}
                }))
            else:
                print(json.dumps({
                    "ok": False,
                    "speech": "Couldn't change the volume",
                    "error": "Failed to set volume"
                }))
                sys.exit(1)
                
        elif action == 'up':
            # Increase by level% or default 10%
            delta = int(level) if level else 10
            success, new_level = adjust_volume(card, delta)
            
            if success:
                print(json.dumps({
                    "ok": True,
                    "speech": f"Volume increased to {new_level} percent",
                    "data": {"volume": new_level, "card": card}
                }))
            else:
                print(json.dumps({
                    "ok": False,
                    "speech": "Couldn't increase the volume",
                    "error": "Failed to adjust volume"
                }))
                sys.exit(1)
                
        elif action == 'down':
            # Decrease by level% or default 10%
            delta = int(level) if level else 10
            success, new_level = adjust_volume(card, -delta)
            
            if success:
                print(json.dumps({
                    "ok": True,
                    "speech": f"Volume decreased to {new_level} percent",
                    "data": {"volume": new_level, "card": card}
                }))
            else:
                print(json.dumps({
                    "ok": False,
                    "speech": "Couldn't decrease the volume",
                    "error": "Failed to adjust volume"
                }))
                sys.exit(1)
                
        elif action == 'mute':
            if set_volume(card, 0):
                print(json.dumps({
                    "ok": True,
                    "speech": "Speaker muted",
                    "data": {"volume": 0, "card": card, "muted": True}
                }))
            else:
                print(json.dumps({
                    "ok": False,
                    "speech": "Couldn't mute the speaker",
                    "error": "Failed to mute"
                }))
                sys.exit(1)
                
        else:
            raise ValueError(f"Unknown action: {action}. Use: get, set, up, down, mute")
            
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Volume control error: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

