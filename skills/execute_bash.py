#!/usr/bin/env python3
"""
Jarvis Skill: Execute Bash Command
Executes bash commands with safety checks.

Security:
- Blocks dangerous command patterns (expanded list)
- Detects command injection attempts
- Blocks interpreter escapes
- Logs all executed commands
"""
import sys
import json
import subprocess
import re
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Dangerous command patterns to block (comprehensive list)
BLOCKED_PATTERNS = [
    # Filesystem destruction
    'rm -rf /',
    'rm -rf /*',
    'rm -rf ~',
    'rm -r -f /',
    'rm -fr /',
    'rmdir /',
    'mkfs',
    'dd if=',
    'dd of=/dev',
    'shred',
    
    # Fork bombs and resource exhaustion
    ':(){:|:&};:',
    ':(){ :|:& };:',
    'fork while fork',
    
    # Permission changes
    'chmod -R 777 /',
    'chmod 777 /',
    'chown -R',
    
    # Sensitive file access
    '/etc/shadow',
    '/etc/passwd',  # Reading is logged, writing blocked
    
    # Network exfiltration patterns
    '| nc ',
    '| netcat ',
    '| curl ',
    '| wget ',
    
    # Reverse shells
    '/dev/tcp/',
    '/dev/udp/',
    'bash -i',
    'sh -i',
    
    # Cron/persistence
    'crontab -',
    '/etc/cron',
    
    # Shutdown/reboot
    'shutdown',
    'reboot',
    'init 0',
    'init 6',
    'poweroff',
    'halt',
]

# Regex patterns for more sophisticated detection
BLOCKED_REGEX_PATTERNS = [
    r'rm\s+(-[rf]+\s+)*/',  # rm with various flag combinations targeting root
    r'>\s*/dev/[sh]d[a-z]',  # Overwriting disk devices
    r'curl\s+.*\|\s*(ba)?sh',  # Download and execute
    r'wget\s+.*\|\s*(ba)?sh',  # Download and execute
    r'python[23]?\s+-c\s+[\'"].*os\.system',  # Python command injection
    r'perl\s+-e\s+[\'"].*system',  # Perl command injection
    r'ruby\s+-e\s+[\'"].*system',  # Ruby command injection
    r'eval\s*\(',  # Eval with subshell
    r'\$\([^)]*rm\s',  # Command substitution with rm
    r'`[^`]*rm\s',  # Backtick substitution with rm
    r'base64\s+-d.*\|\s*(ba)?sh',  # Base64 decode and execute
    r'>\s*/etc/',  # Writing to /etc
    r';\s*rm\s',  # Command chaining with rm
    r'&&\s*rm\s',  # Command chaining with rm
    r'\|\|\s*rm\s',  # Command chaining with rm
]


def is_command_safe(command: str) -> tuple[bool, str]:
    """
    Check if a command is safe to execute.
    
    Returns:
        (is_safe, reason) - tuple of bool and explanation string
    """
    cmd_lower = command.lower()
    
    # Check blocked string patterns
    for pattern in BLOCKED_PATTERNS:
        if pattern.lower() in cmd_lower:
            return False, f"contains blocked pattern '{pattern}'"
    
    # Check regex patterns
    for regex in BLOCKED_REGEX_PATTERNS:
        if re.search(regex, command, re.IGNORECASE):
            return False, f"matches dangerous pattern"
    
    # Check for suspicious command substitution
    if '$(' in command or '`' in command:
        # Allow simple variable expansion, block complex substitution
        if re.search(r'\$\([^)]{20,}\)', command) or re.search(r'`[^`]{20,}`', command):
            return False, "complex command substitution detected"
    
    return True, "ok"


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
    
    # SECURITY: Comprehensive safety check
    is_safe, reason = is_command_safe(command)
    if not is_safe:
        logger.warning(f"BLOCKED command: {command[:200]} - Reason: {reason}")
        return_error(f"Command blocked for safety: {reason}")
        return 1
    
    # Log all executed commands for audit
    logger.info(f"Executing: {command[:500]}")
    
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

