"""Conservative Docker MCP cleanup within a verified Linux process namespace."""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

OWNER_SCOPE = "io.jarvis.mcp.owner-scope"
OWNER_PID = "io.jarvis.mcp.owner-pid"
OWNER_START = "io.jarvis.mcp.owner-start"


def _process_identity(pid: int) -> tuple[str, str]:
    # comm can contain spaces and parentheses. Fields after its final ')' start
    # with state (field 3); process start time is field 22.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return fields[0], fields[19]


def owner_labels() -> dict[str, str]:
    """Identify an owner without treating another host/namespace's PID as ours."""
    if sys.platform != "linux":
        return {}
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        namespace = os.readlink("/proc/self/ns/pid")
        _, birth = _process_identity(os.getpid())
    except (OSError, ValueError, IndexError):
        return {}
    # hidepid mounts can conceal another user's live process as ENOENT.
    # Only compare owners in our own user/boot/PID-namespace domain.
    scope = hashlib.sha256(f"{boot}:{namespace}:{os.getuid()}".encode()).hexdigest()
    return {OWNER_SCOPE: scope, OWNER_PID: str(os.getpid()), OWNER_START: birth}


def _owner_is_dead(labels: dict[str, str], scope: str) -> bool:
    if labels.get(OWNER_SCOPE) != scope:
        return False
    pid, birth = labels.get(OWNER_PID, ""), labels.get(OWNER_START, "")
    if not pid.isdigit() or int(pid) <= 0 or not birth.isdigit():
        return False
    try:
        state, current_birth = _process_identity(int(pid))
    except (FileNotFoundError, ProcessLookupError):
        return True
    except (OSError, ValueError, IndexError):
        return False  # Unknown ownership is never permission to remove.
    return current_birth != birth or state in {"Z", "X"}


def reap_orphans(labels: dict[str, str], *, env: dict[str, str], timeout: float = 5) -> int:
    """Remove only labeled containers whose owner death can be proved locally."""
    scope = labels.get(OWNER_SCOPE)
    if not scope:
        return 0
    deadline = time.monotonic() + timeout

    def run(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(args, timeout)
        return subprocess.run(args, capture_output=True, text=True, env=env, timeout=remaining)

    try:
        result = run(["docker", "ps", "-aq", "--filter", f"label={OWNER_SCOPE}={scope}"])
        if result.returncode:
            return 0
        ids = [value for value in result.stdout.split() if value.isalnum()][:100]
        if not ids:
            return 0
        result = run([
            "docker", "inspect", "--format",
            '{"id":{{json .Id}},"labels":{{json .Config.Labels}}}', *ids,
        ])
        if result.returncode:
            return 0
        dead = []
        for line in result.stdout.splitlines():
            entry = json.loads(line)
            if (entry.get("id") in ids or any(entry.get("id", "").startswith(i) for i in ids)) and _owner_is_dead(
                entry.get("labels") or {}, scope,
            ):
                dead.append(entry["id"])
        if dead and run(["docker", "rm", "-f", *dead]).returncode == 0:
            return len(dead)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError):
        pass
    return 0
