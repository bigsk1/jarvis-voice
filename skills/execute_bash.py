#!/usr/bin/env python3
"""
Jarvis Skill: Execute Bash Command
Executes bash commands with safety checks.

Security:
- Applies best-effort checks for dangerous commands and sensitive paths
- Detects command injection attempts
- Blocks interpreter escapes
- Logs all executed commands

These checks reduce accidental LLM misuse. They are not a filesystem sandbox or
a security boundary against deliberately obfuscated shell commands.
"""
import os
import sys
import json
import subprocess
import re
import logging
import shlex
from pathlib import Path

# Add lib to path (same pattern as other skills)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib"))
from security_utils import is_path_protected
from paths import (
    get_project_root,
    get_restricted_read_match,
    get_restricted_read_paths,
    is_path_under_prefix,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CD_COMMANDS = frozenset({"cd"})
SEARCH_PATH_COMMANDS = frozenset({"grep", "rg", "ripgrep", "ag", "ack", "find"})
SEARCH_PATTERN_FLAGS = frozenset({"-e", "--regexp"})
SEARCH_FILE_FLAGS = frozenset({"-f", "--file"})
SEARCH_FLAGS_WITH_VALUE = frozenset({
    "-m", "--max-count", "--glob", "-g", "-A", "--after-context",
    "-B", "--before-context", "-C", "--context", "--type", "-t",
    "--include", "--exclude", "--exclude-dir",
})
SEARCH_DEFAULTS_TO_CWD = frozenset({"rg", "ripgrep", "ag", "ack", "find"})
READ_PATH_COMMANDS = frozenset({
    "cat", "head", "tail", "less", "more", "strings", "file", "stat", "ls",
    "du", "wc", "sort", "uniq", "cut", "awk", "sed", "jq", "yq", "xxd",
    "hexdump", "base64", "sqlite3", "tar", "zip", "unzip", "7z", "rsync",
    "scp",
})
READ_EXPRESSION_COMMANDS = frozenset({"awk", "sed", "jq", "yq"})
SHELL_OR_INTERPRETER_COMMANDS = frozenset({
    "bash", "sh", "zsh", "python", "python3", "perl", "ruby", "node",
})


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

# Commands that modify files - used to check against protected paths.
MODIFYING_COMMAND_NAMES = frozenset({
    "rm", "rmdir", "mv", "cp", "touch", "mkdir", "chmod", "chown", "chgrp",
    "tee", "dd", "nano", "vim", "vi", "emacs", "truncate",
})


def is_modifying_command(command: str) -> bool:
    """Check if command modifies files (vs read-only)."""
    # Inspect the command position in each simple shell segment. This avoids
    # treating names such as ``jarvis_memory.db`` or ``/tmp/vi/example`` as
    # editor commands merely because they contain a command substring.
    for segment in re.split(r"&&|\|\||[;|]", command):
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            tokens = segment.split()
        while tokens and "=" in tokens[0] and not tokens[0].startswith(("/", "./", "../")):
            tokens.pop(0)
        if tokens and Path(tokens[0]).name == "sudo":
            tokens.pop(0)
            while tokens and tokens[0].startswith("-"):
                tokens.pop(0)
        if not tokens:
            continue

        command_name = Path(tokens[0]).name.lower()
        if command_name in MODIFYING_COMMAND_NAMES:
            return True
        if command_name == "sed" and any(
            arg == "--in-place" or arg.startswith("-i") for arg in tokens[1:]
        ):
            return True
        if command_name == "git" and len(tokens) > 1 and tokens[1] in {"checkout", "reset", "clean"}:
            return True
    
    # Check for output redirection
    if re.search(r'>\s*[^&]', command):  # > but not >&
        return True
    if '>>' in command:
        return True
    
    return False


def _looks_like_path_token(token: str) -> bool:
    """Heuristic: identify shell tokens that likely reference filesystem paths."""
    if not token or token in {"|", "||", "&&", ";", ">", ">>", "<", "<<", "2>", "2>>"}:
        return False
    if token.startswith("-"):
        return False
    return token.startswith(("~", "/", "./", "../")) or "/" in token


def _resolve_shell_path(part: str, base_dir: Path) -> str:
    normalized = Path(part).expanduser()
    if not normalized.is_absolute():
        normalized = base_dir / normalized
    return str(normalized.resolve())


def _extract_search_roots(tokens: list[str], start: int, base_dir: Path) -> tuple[list[str], int]:
    """Extract search input roots while keeping the search expression out of path checks."""
    command = Path(tokens[start]).name
    if command == "find":
        roots: list[str] = []
        j = start + 1
        while j < len(tokens):
            part = tokens[j]
            if part in {"|", "||", "&&", ";"} or part.startswith(("-", "!", "(")):
                break
            roots.append(_resolve_shell_path(part, base_dir))
            j += 1
        return roots or [str(base_dir)], j

    roots = []
    pattern_supplied = False
    j = start + 1
    while j < len(tokens):
        part = tokens[j]
        if part in {"|", "||", "&&", ";"}:
            break
        if part in SEARCH_PATTERN_FLAGS and j + 1 < len(tokens):
            pattern_supplied = True
            j += 2
            continue
        if part in SEARCH_FILE_FLAGS and j + 1 < len(tokens):
            # A pattern file is itself a local read.
            roots.append(_resolve_shell_path(tokens[j + 1], base_dir))
            pattern_supplied = True
            j += 2
            continue
        if part in SEARCH_FLAGS_WITH_VALUE and j + 1 < len(tokens):
            j += 2
            continue
        if part.startswith("-"):
            j += 1
            continue
        if not pattern_supplied:
            pattern_supplied = True
        else:
            roots.append(_resolve_shell_path(part, base_dir))
        j += 1

    if not roots and command in SEARCH_DEFAULTS_TO_CWD:
        roots.append(str(base_dir))
    return roots, j


def _extract_read_command_paths(tokens: list[str], start: int, base_dir: Path) -> tuple[list[str], int]:
    """Extract likely file operands from common LLM-generated read commands."""
    candidates: list[str] = []
    command = Path(tokens[start]).name
    expression_supplied = command not in READ_EXPRESSION_COMMANDS
    j = start + 1
    while j < len(tokens):
        part = tokens[j]
        if part in {"|", "||", "&&", ";"}:
            break
        if part.startswith("-"):
            j += 1
            continue
        if not expression_supplied:
            expression_supplied = True
            j += 1
            continue
        candidates.append(_resolve_shell_path(part, base_dir))
        j += 1
    return candidates, j


def _extract_candidate_paths(command: str, working_dir: str | None = None) -> list[str]:
    """Extract path-like shell tokens and normalize them against the working directory."""
    base_dir = Path(working_dir or os.getcwd()).expanduser().resolve()
    candidates: list[str] = []

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()

    i = 0
    while i < len(tokens):
        token = tokens[i]

        command_name = Path(token).name

        if command_name in CD_COMMANDS and i + 1 < len(tokens):
            target = tokens[i + 1]
            if not target.startswith("-") and target not in {"|", "||", "&&", ";"}:
                candidates.append(_resolve_shell_path(target, base_dir))
            i += 2
            continue

        if command_name in SEARCH_PATH_COMMANDS:
            roots, j = _extract_search_roots(tokens, i, base_dir)
            candidates.extend(roots)
            i = j
            continue

        if command_name in READ_PATH_COMMANDS:
            paths, j = _extract_read_command_paths(tokens, i, base_dir)
            candidates.extend(paths)
            i = j
            continue

        parts = [token]
        if "=" in token and not token.startswith("/"):
            _, right = token.split("=", 1)
            if _looks_like_path_token(right):
                parts = [right]

        for part in parts:
            if not _looks_like_path_token(part):
                continue
            candidates.append(_resolve_shell_path(part, base_dir))

        i += 1

    return candidates


def _is_execute_bash_blocked_write_path(path: str) -> tuple[bool, str]:
    """Apply execute_bash-specific write restrictions on top of shared security rules."""
    normalized = str(Path(path).expanduser().resolve())
    data_root = str((get_project_root().resolve() / "data").resolve())

    if is_path_under_prefix(normalized, data_root):
        return True, data_root

    protected, matched = is_path_protected(normalized, for_write=True)
    if protected:
        return True, matched or normalized

    return False, ""


def _is_execute_bash_blocked_read_path(path: str) -> tuple[bool, str]:
    """Block shell reads of sensitive subtrees (backups, secrets, live config)."""
    matched = get_restricted_read_match(path)
    if matched:
        return True, matched
    return False, ""


def targets_protected_path(command: str, working_dir: str | None = None) -> tuple[bool, str]:
    """
    Check if command targets a protected path.
    
    Returns:
        (targets_protected, path_matched)
    """
    for candidate in _extract_candidate_paths(command, working_dir):
        protected, matched = _is_execute_bash_blocked_write_path(candidate)
        if protected:
            return True, matched or candidate

    return False, ""


def targets_restricted_read_path(command: str, working_dir: str | None = None) -> tuple[bool, str]:
    """Check if command references a path that must not be read via shell."""
    candidates = _extract_candidate_paths(command, working_dir)
    for candidate in candidates:
        blocked, matched = _is_execute_bash_blocked_read_path(candidate)
        if blocked:
            return True, matched or candidate

    # Search tools recurse from their roots. Reject a root that contains a
    # restricted subtree even though the root itself is not restricted.
    base_dir = Path(working_dir or os.getcwd()).expanduser().resolve()
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    for i, token in enumerate(tokens):
        if Path(token).name not in SEARCH_PATH_COMMANDS:
            continue
        roots, _ = _extract_search_roots(tokens, i, base_dir)
        for root in roots:
            root_path = Path(root).resolve()
            for restricted in get_restricted_read_paths():
                if is_path_under_prefix(restricted, root_path):
                    return True, restricted

    # Catch common shell/interpreter wrappers where the path is embedded in a
    # code string rather than represented as its own shell token.
    command_names = {Path(token).name for token in tokens}
    if command_names & SHELL_OR_INTERPRETER_COMMANDS:
        normalized = command.replace("\\", "/")
        relative_markers = ("config/", "data/backups/", "data/secrets/")
        if any(marker in normalized for marker in relative_markers):
            for restricted in get_restricted_read_paths():
                if Path(restricted).name in normalized or str(Path(restricted).relative_to(get_project_root())) in normalized:
                    return True, restricted

    return False, ""


def is_command_safe(command: str, working_dir: str | None = None) -> tuple[bool, str]:
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
    
    # Block reads of sensitive subtrees (backups, secrets, config)
    if working_dir:
        blocked, matched = _is_execute_bash_blocked_read_path(working_dir)
        if blocked:
            return False, f"cannot use restricted working directory: {matched}"

    targets, path = targets_restricted_read_path(command, working_dir)
    if targets:
        return False, f"cannot read restricted path: {path}"

    # CRITICAL: Check if modifying command targets protected paths
    if is_modifying_command(command):
        targets, path = targets_protected_path(command, working_dir)
        if targets:
            return False, f"cannot modify protected path: {path}"
    
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
    is_safe, reason = is_command_safe(command, working_dir)
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
