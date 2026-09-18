"""Boot the complete Web app without pytest's repo-root import path."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
import importlib
import runpy
import sys
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

root, scratch = Path(sys.argv[1]), Path(sys.argv[2])
entrypoint = sys.argv[3]
assert str(root) not in sys.path
assert str(root / "lib") not in sys.path

# Execute the real launcher bootstrap; importing only ChatHandler would miss
# the app's module-level route imports and coordinator construction.
runpy.run_path(str(root / "bin/jarvis-web"), run_name="startup_probe")
from server import config
from server.services import conversation_store
import flask_error_logger

# Keep production app/route/handler imports and registration. Redirect only
# operator config/storage/logging and the listener to disposable test I/O.
config.CONFIG_PATH = scratch / "web_config.json"
config.load_jarvis_config = lambda mode="cloud": True
flask_error_logger.LOGS_DIR = scratch / "logs"

@lru_cache(maxsize=1)
def isolated_store():
    from lib.background_tasks import TaskStore
    return conversation_store.ConversationStore(
        conversations_dir=scratch / "conversations",
        background_tasks=TaskStore(scratch / "tasks.db"),
    )

conversation_store.get_conversation_store = isolated_store
assert str(root) not in sys.path
assert "lib" not in sys.modules

with patch("flask_socketio.SocketIO.run") as listener:
    if entrypoint == "launcher":
        sys.argv = [str(root / "bin/jarvis-web"), "cloud", "--host", "127.0.0.1", "--port", "5057"]
        runpy.run_path(sys.argv[0], run_name="__main__")
        listener.assert_called_once()
        assert listener.call_args.kwargs["port"] == 5057
    else:
        module = importlib.import_module("server.app")
        app, socketio = module.create_app()
        listener.assert_not_called()

module = importlib.import_module("server.app")
from lib.background_tasks import TaskStore
from lib.background_tasks.admission import WebTaskContext
from server.services.background_tasks import BackgroundAdmissionService
assert module.app.test_client().get("/login").status_code == 200
assert isinstance(module.chat_handler.background_tasks.store, TaskStore)
assert module.chat_handler.background_tasks.thread is None
assert not (scratch / "tasks.db").exists()
assert "background_tasks" not in sys.modules  # One canonical package/class identity.
assert BackgroundAdmissionService.authorize.__globals__["WebTaskContext"] is WebTaskContext
module.chat_handler.background_tasks.close()
print("Complete Web startup passed without ambient repo paths")
'''


@pytest.mark.parametrize("entrypoint", ["launcher", "factory"])
def test_web_boot_without_ambient_repo_path(entrypoint, tmp_path):
    completed = subprocess.run(
        [sys.executable, "-I", "-c", PROBE, str(ROOT), str(tmp_path), entrypoint],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Complete Web startup passed without ambient repo paths" in completed.stdout
