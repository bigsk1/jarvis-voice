#!/usr/bin/env python3
"""
Jarvis Skill: Execute Bash Command
Executes bash commands with safety checks.
"""
import sys
import json
import subprocess


# Dangerous command patterns to block
BLOCKED_PATTERNS = [
    'rm -rf /',
    'mkfs',
    'dd if=',
    ':(){:|:&};:',  # Fork bomb
    'chmod -R 777 /',
    'rm -rf /*',
    'rm -rf ~/*',
]


def main():
    """Execute bash command safely."""
    # Read input from command line argument
    try:
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return_error("Invalid JSON input")
        return 1
    
    # Extract parameters
    command = input_data.get("command", "").strip()
    working_dir = input_data.get("working_directory", None)
    
    if not command:
        return_error("Command is required")
        return 1
    
    # Safety check: block obviously dangerous commands
    for pattern in BLOCKED_PATTERNS:
        if pattern in command:
            return_error(f"Command blocked for safety: contains '{pattern}'")
            return 1
    
    # Execute command
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=working_dir
        )
        
        # Prepare output
        output = result.stdout.strip()
        error = result.stderr.strip()
        
        if result.returncode == 0:
            # Success
            speech = f"Command executed successfully. Output: {output[:200]}" if output else "Command completed successfully with no output."
            return_success(
                speech=speech,
                data={
                    "command": command,
                    "exit_code": result.returncode,
                    "stdout": output,
                    "stderr": error
                }
            )
            return 0
        else:
            # Command failed
            speech = f"Command failed with exit code {result.returncode}."
            if error:
                speech += f" Error: {error[:100]}"
            
            return_error(
                speech=speech,
                data={
                    "command": command,
                    "exit_code": result.returncode,
                    "stdout": output,
                    "stderr": error
                }
            )
            return 1
            
    except subprocess.TimeoutExpired:
        return_error("Command timed out after 30 seconds")
        return 1
    except Exception as e:
        return_error(f"Failed to execute command: {str(e)}")
        return 1


def return_success(speech, data=None):
    """Return success response."""
    result = {
        "ok": True,
        "speech": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech, data=None):
    """Return error response."""
    result = {
        "ok": False,
        "speech": speech,
        "error": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main())

