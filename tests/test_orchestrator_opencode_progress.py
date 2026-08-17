import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator  # noqa: E402


class RecordingStatusUpdater:
    def __init__(self, dynamic=True):
        self.contexts = []
        self.updates = []
        self.dynamic = dynamic

    def dynamic_summaries_enabled(self):
        return self.dynamic

    def set_context(self, value):
        self.contexts.append(value)

    def update(self, **kwargs):
        self.updates.append(kwargs)


def test_child_opencode_progress_reaches_status_and_web_callbacks():
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.status_updater = RecordingStatusUpdater()
    orchestrator._active_tool_call_index = 2
    emitted = []
    orchestrator.progress_callback = (
        lambda event_type, **kwargs: emitted.append((event_type, kwargs))
    )

    orchestrator._handle_executor_progress(
        "tool_progress",
        tool="opencode",
        phase="tool",
        status="OpenCode: Running tests",
        session_id="ses_test",
    )

    assert orchestrator.status_updater.contexts == []
    assert "custom_message" not in orchestrator.status_updater.updates[0]
    assert orchestrator.status_updater.updates[0]["context"]["detail"] == "OpenCode: Running tests"
    assert emitted[0][0] == "tool_progress"
    assert emitted[0][1]["call_index"] == 2
    assert emitted[0][1]["session_id"] == "ses_test"


def test_child_opencode_progress_skips_general_status_without_status_llm():
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.status_updater = RecordingStatusUpdater(dynamic=False)
    orchestrator._active_tool_call_index = 0
    emitted = []
    orchestrator.progress_callback = (
        lambda event_type, **kwargs: emitted.append((event_type, kwargs))
    )

    orchestrator._handle_executor_progress(
        "tool_progress",
        tool="opencode",
        phase="tool",
        status="OpenCode: Running tests",
    )

    assert orchestrator.status_updater.updates == []
    assert emitted[0][0] == "tool_progress"
    assert emitted[0][1]["status"] == "OpenCode: Running tests"


def test_blocked_opencode_progress_is_high_priority_error_status():
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.status_updater = RecordingStatusUpdater()
    orchestrator._active_tool_call_index = 0
    orchestrator.progress_callback = None

    orchestrator._handle_executor_progress(
        "tool_progress",
        tool="opencode",
        phase="blocked",
        status="OpenCode needs an answer before it can continue",
    )

    update = orchestrator.status_updater.updates[0]
    assert update["category"] == "error"
    assert update["priority"] == "high"
