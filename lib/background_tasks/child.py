"""Linux local skill child: resource ceilings and cleanup if its worker is killed.

Invoked only by the trusted executor seam. Contains no Jarvis imports, config or
network access; the skill and all its children stay in this dedicated process group.
"""

import json
import math
import os
import resource
import signal
import subprocess
import sys
import threading
import time


def main():
    timeout = max(1, min(86400, math.ceil(float(sys.argv[1]))))
    command = sys.argv[2:]
    # Preserve the original CLI for supervisors started before the extraction.
    limits = {'file_bytes': 512 * 1024**2, 'memory_bytes': 2 * 1024**3}
    if command[0] == '--limits':
        limits.update(json.loads(command[1]))
        command = command[2:]
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits['file_bytes'],) * 2)
    resource.setrlimit(resource.RLIMIT_AS, (limits['memory_bytes'],) * 2)
    # RLIMIT_CPU sums CPU time across ffmpeg's threads, not elapsed time.
    # Budget all available CPUs so it cannot reintroduce an earlier wall limit.
    try:
        cpus = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpus = os.cpu_count() or 1
    cpu_budget = timeout * max(1, cpus)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_budget, cpu_budget + 1))
    parent = os.getppid()
    if parent == 1:
        return 1

    def watch():
        while True:
            time.sleep(.2)
            if os.getppid() != parent:
                os.killpg(os.getpgrp(), signal.SIGKILL)

    threading.Thread(target=watch, daemon=True).start()
    child = subprocess.Popen(command)
    return child.wait()


if __name__ == '__main__':
    sys.exit(main())
