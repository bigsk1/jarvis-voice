"""Shared local subprocess seam used by foreground and background execution."""

import os
import signal
import subprocess
import threading
import time
from pathlib import Path


class OutputLimitExceeded(RuntimeError):
    pass


class TerminationUnverified(RuntimeError):
    pass


def group_alive(process):
    """A zombie is stopped, even if its adopting init has not reaped it yet."""
    if os.name != "posix":
        return process.poll() is None
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    if Path('/proc').is_dir():
        uncertain = False
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / 'stat').read_text().rsplit(') ', 1)[1].split()
                if int(fields[2]) == process.pid and fields[0] != 'Z':
                    return True
            except FileNotFoundError:
                continue  # Process exited while enumerating.
            except (OSError, ValueError, IndexError):
                uncertain = True
        return uncertain  # Unreadable process metadata is not proof of exit.
    return True


def terminate_verified(process, grace_seconds):
    for sig, wait in ((signal.SIGTERM, grace_seconds), (signal.SIGKILL, 2)):
        if not group_alive(process):
            process.wait(timeout=2)
            return True
        try:
            if os.name == 'posix':
                os.killpg(process.pid, sig)
            else:
                process.send_signal(sig)
        except ProcessLookupError:
            pass
        until = time.monotonic() + wait
        while time.monotonic() < until:
            process.poll()
            if not group_alive(process):
                process.wait(timeout=2)
                return True
            time.sleep(.05)
    return not group_alive(process)


def run_local_process(cmd, input_json, *, python_script, cwd, tool_env, timeout,
                      tool_name, consume_progress, cancel_check, terminate,
                      process_factory=subprocess.Popen, checkpoint=None, max_output_bytes=None,
                      process_started=None, process_stopped=None):
    start_time = time.time()
    if checkpoint:
        checkpoint()
    overflow = threading.Event()
    retained = 0
    retained_lock = threading.Lock()

    def retain(lines, line):
        nonlocal retained
        with retained_lock:
            retained += len(line.encode('utf-8'))
            if max_output_bytes is not None and retained > max_output_bytes:
                overflow.set()
            elif not overflow.is_set():
                lines.append(line)

    process = process_factory(
        cmd,
        stdin=subprocess.PIPE if not python_script else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=tool_env,  # Pass environment so tools see LLM_PROVIDER
        start_new_session=(os.name == "posix"),
    )
    try:
        if process_started:
            process_started(process.pid)
        if not python_script and process.stdin:
            process.stdin.write(input_json)
            process.stdin.close()

        deadline = start_time + timeout
        cancelled = False
        timed_out = False
        stdout = ""
        stderr = ""

        # Drain both pipes concurrently while polling for cancellation/timeout.
        # Structured stderr lines are forwarded immediately; ordinary stderr is
        # retained for the existing final error fallback.
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def read_stdout() -> None:
            if not process.stdout:
                return
            try:
                for line in iter(lambda: process.stdout.readline(65536) if max_output_bytes else process.stdout.readline(), ""):
                    retain(stdout_lines, line)
            except (OSError, ValueError):
                pass

        def read_stderr() -> None:
            if not process.stderr:
                return
            try:
                for line in iter(lambda: process.stderr.readline(65536) if max_output_bytes else process.stderr.readline(), ""):
                    if not consume_progress(line):
                        retain(stderr_lines, line)
            except (OSError, ValueError):
                pass

        stdout_thread = threading.Thread(
            target=read_stdout,
            daemon=True,
            name=f"tool-stdout-{tool_name}",
        )
        stderr_thread = threading.Thread(
            target=read_stderr,
            daemon=True,
            name=f"tool-stderr-{tool_name}",
        )
        stdout_thread.start()
        stderr_thread.start()

        while process.poll() is None:
            if checkpoint:
                checkpoint()
            if overflow.is_set():
                raise OutputLimitExceeded("Tool output exceeded its limit")
            if cancel_check:
                try:
                    if cancel_check():
                        cancelled = True
                        terminate(
                            process,
                            grace_seconds=12 if tool_name == "browser_use" else 6 if tool_name == "opencode" else 3,
                        )
                        break
                except Exception:
                    pass

            if time.time() >= deadline:
                timed_out = True
                terminate(
                    process,
                    grace_seconds=12 if tool_name == "browser_use" else 6 if tool_name == "opencode" else 3,
                )
                break

            time.sleep(0.25)

        drain_timeout = 1 if (cancelled or timed_out) else 5
        drain_deadline = time.monotonic() + drain_timeout
        for drain_thread in (stdout_thread, stderr_thread):
            drain_thread.join(timeout=max(0, drain_deadline - time.monotonic()))
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        # A completed process may win a racing cancellation. finish() still
        # fences the result; no child may remain alive when this seam returns.
        if overflow.is_set():
            raise OutputLimitExceeded("Tool output exceeded its limit")
        if checkpoint and not terminate(process, grace_seconds=0.2, verify=True):
            raise TerminationUnverified("Tool descendants did not stop")
        if checkpoint and process_stopped:
            process_stopped()
        if timed_out:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return stdout, stderr, cancelled
    except BaseException:
        if checkpoint:
            if not terminate(process, grace_seconds=1, verify=True):
                raise TerminationUnverified("Tool termination could not be verified") from None
            if process_stopped:
                process_stopped()
        else:
            terminate(process, grace_seconds=3)
        raise
