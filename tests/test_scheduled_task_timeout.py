"""Regression coverage for scheduled-task execution deadlines."""

from __future__ import annotations

import operator
import time

import pytest

from services import scheduled_task_runner as runner


def test_scheduled_task_timeout_terminates_hung_worker_and_returns_promptly():
    started = time.monotonic()

    with pytest.raises(
        runner.ScheduledTaskTimeoutError,
        match="timed out after 1 seconds",
    ):
        runner._run_with_timeout(time.sleep, (30,), 1)

    assert time.monotonic() - started < 5


def test_scheduler_can_run_next_task_after_timeout():
    with pytest.raises(runner.ScheduledTaskTimeoutError):
        runner._run_with_timeout(time.sleep, (30,), 1)

    assert runner._run_with_timeout(operator.add, (2, 3), 5) == 5


def test_worker_exceptions_return_without_waiting_for_timeout():
    with pytest.raises(RuntimeError, match="ZeroDivisionError"):
        runner._run_with_timeout(operator.truediv, (1, 0), 5)
