"""Isolated builder worker. Input snapshots and commands are private SQLite IPC."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import BuilderStore


DIAGNOSTIC_PREFIX = '__JARVIS_WORKFLOW_DIAGNOSTIC__:'
STARTUP_PHASES = frozenset({'bootstrap', 'store', 'load_run', 'runtime_import', 'mode_config',
                           'validation', 'tool_registry', 'provider', 'startup'})
EXCEPTION_TYPES = frozenset({'ModuleNotFoundError', 'ImportError', 'SyntaxError', 'IndentationError',
                            'FileNotFoundError', 'PermissionError', 'ValueError', 'RuntimeError',
                            'KeyError', 'AttributeError', 'TypeError', 'OSError', 'OperationalError',
                            'DatabaseError', 'IntegrityError', 'StartupError', 'WorkerExit'})


def normalize_startup_diagnostic(payload: dict) -> dict:
    """Project only safe diagnostic fields; exception text and source lines are excluded."""
    phase = payload.get('phase')
    phase = phase if isinstance(phase, str) and phase in STARTUP_PHASES else 'startup'
    kind = payload.get('exception_type')
    kind = kind if isinstance(kind, str) and kind in EXCEPTION_TYPES else 'StartupError'
    diagnostic = {'type': 'worker_startup_error', 'phase': phase, 'exception_type': kind}
    module = payload.get('module')
    if kind == 'ModuleNotFoundError' and isinstance(module, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]{0,160}', module):
        diagnostic['module'] = module
    frames = []
    candidates = payload.get('frames', [])
    for frame in candidates[-3:] if isinstance(candidates, list) else []:
        if not isinstance(frame, dict):
            continue
        filename, function, line = frame.get('file'), frame.get('function'), frame.get('line')
        if (isinstance(filename, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', filename)
                and isinstance(function, str) and re.fullmatch(r'[A-Za-z0-9_<>]{1,120}', function)
                and type(line) is int and 0 < line < 1000000):
            frames.append({'file': filename, 'function': function, 'line': line})
    if frames:
        diagnostic['frames'] = frames
    exit_code = payload.get('exit_code')
    if type(exit_code) is int and -255 <= exit_code <= 255:
        diagnostic['exit_code'] = exit_code
    message = f"Worker startup failed during {phase.replace('_', ' ')}: {kind}"
    if 'module' in diagnostic:
        message += f"; missing Python module '{diagnostic['module']}'"
    if frames:
        last = frames[-1]
        message += f" at {last['file']}:{last['line']} ({last['function']})"
    if 'exit_code' in diagnostic:
        message += f" (exit code {diagnostic['exit_code']})"
    diagnostic['message'] = message
    return diagnostic


def startup_diagnostic(error: Exception, phase: str) -> dict:
    frames = [{'file': Path(frame.filename).name, 'function': frame.name, 'line': frame.lineno}
              for frame in traceback.extract_tb(error.__traceback__)[-3:]]
    return normalize_startup_diagnostic({
        'phase': phase, 'exception_type': type(error).__name__,
        'module': error.name if isinstance(error, ModuleNotFoundError) else None,
        'frames': frames,
    })


def emit_diagnostic(payload: dict) -> None:
    """A bounded control channel; ordinary stderr is never copied into run history."""
    sys.stderr.write(DIAGNOSTIC_PREFIX + json.dumps(payload, separators=(',', ':')) + '\n')
    sys.stderr.flush()


def _bootstrap():
    """Load this service under its own package name, away from sibling server packages."""
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'lib'))
    package = 'jarvis_workflows_worker_server'
    spec = importlib.util.spec_from_file_location(
        package, Path(__file__).with_name('__init__.py'),
        submodule_search_locations=[str(Path(__file__).parent)])
    if spec is None or spec.loader is None:
        raise RuntimeError('Cannot load workflow worker package')
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    globals()['__package__'] = package


def refresh_catalog(root: Path, store: BuilderStore, mode: str) -> None:
    from config_loader import load_config
    from tool_schema import ToolRegistry

    load_config(mode)
    registry = ToolRegistry(str(root / 'skills'), str(root / 'config' / 'mcp-servers.json'))
    try:
        tools = []
        for name, schema in registry.tools.items():
            tools.append({'name': name, 'description': schema.description,
                          'parameters': schema.parameters, 'permissions': schema.permissions,
                          'auto_approve': schema.permissions.get('auto_approve', False),
                          'available': True, 'reason': '',
                          'background_required': getattr(schema, 'background_required', False),
                          'source': 'mcp' if name.startswith('mcp_') else 'local'})
        store.save_catalog(mode, tools)
    finally:
        registry.cleanup()


def execute_run(root: Path, store: BuilderStore, run_id: str) -> None:
    """Initialize the runtime, then execute one immutable admitted snapshot."""
    phase = 'runtime_import'
    ready = False
    cancelled = False
    executor = None

    def handle_signal(_number, _frame):
        nonlocal cancelled
        cancelled = True

    def cancel_check():
        return cancelled or store.get_run(run_id)['cancel_requested']

    try:
        from config_loader import load_config
        from workflow_policy import BUILDER_EXCLUDED_TOOLS, get_workflow_excluded_tools
        from workflow_validation import validate_workflow_document

        from orchestrator.executor import ToolExecutor
        from orchestrator.pipeline_executor import PipelineExecutor

        from .previews import approval_argument_preview, bounded_preview
        from .processes import process_identity

        phase = 'load_run'
        identity = process_identity(os.getpid())
        if identity:
            store.set_worker_identity(run_id, identity)
        run = store.get_run(run_id, internal=True)
        workflow = run['workflow']
        mode = run['mode']
        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)
        phase = 'mode_config'
        load_config(mode)
        phase = 'validation'
        diagnostics = validate_workflow_document(workflow, builder=True)
        if diagnostics['errors']:
            store.finish_worker(run_id, 'rejected', {'error': 'Managed recipe validation failed',
                                                    'errors': diagnostics['errors']})
            return

        def event(payload):
            store.event(run_id, bounded_preview(payload))

        def progress(event_type, **payload):
            # Save provider receipts before a final result or possible timeout.
            event({'type': event_type, **payload})

        def approve(payload):
            if cancel_check():
                return False
            safe_payload = {key: payload.get(key) for key in ('tool', 'step', 'index', 'item_index',
                                                            'attempt', 'mode', 'recipe_hash',
                                                            'call_hash', 'run_id')}
            safe_payload['arguments'], safe_payload['arguments_preview'] = approval_argument_preview(
                payload.get('arguments', {}), budget=20000)
            approval_id = store.request_approval(run_id, safe_payload)
            event({'type': 'approval_requested', 'approval_id': approval_id,
                   'tool': payload['tool'], 'call_hash': payload['call_hash']})
            while not cancel_check():
                approval = next(item for item in store.approvals(run_id) if item['id'] == approval_id)
                if approval['status'] != 'pending':
                    store.set_status(run_id, 'running')
                    return approval['status'] == 'approved'
                time.sleep(0.1)
            return False

        if cancel_check():
            store.finish_worker(run_id, 'cancelled')
            return
        store.set_status(run_id, 'running')
        phase = 'tool_registry'
        executor = ToolExecutor(mode=mode)
        executor.set_excluded_tools(list(get_workflow_excluded_tools(mode) | set(BUILDER_EXCLUDED_TOOLS)))
        executor.set_cancel_check(cancel_check)
        executor.set_progress_callback(progress)
        phase = 'provider'
        pipeline = PipelineExecutor(mode, executor)
        emit_diagnostic({'type': 'worker_ready'})
        ready = True
        result = pipeline.execute(
            workflow, run['query'], status_callback=lambda text: event({'type': 'status', 'message': text}),
            event_callback=event, approval_callback=approve,
            execution_context={'surface': 'builder', 'run_id': run_id, 'managed': True},
            stop_after=run['stop_after'],
        )
        if cancel_check():
            status = 'cancelled'
        elif result.get('completion') == 'rejected' or result.get('error_code') == 'approval_denied':
            status = 'rejected'
        elif result.get('ok'):
            status = 'partial' if run.get('partial') is True else 'completed'
        else:
            status = 'failed'
        store.finish_worker(run_id, status, bounded_preview(result, budget=16000))
    except Exception as exc:
        if not ready:
            diagnostic = startup_diagnostic(exc, phase)
            store.event(run_id, diagnostic)
            store.finish_worker(run_id, 'cancelled' if cancel_check() else 'failed',
                                {'error': diagnostic['message'], 'error_code': 'worker_startup_failed',
                                 'startup': diagnostic})
            emit_diagnostic(diagnostic)
        else:
            from .previews import bounded_preview
            store.event(run_id, bounded_preview({'type': 'worker_error', 'error': str(exc)}))
            store.finish_worker(run_id, 'cancelled' if cancel_check() else 'failed',
                                {'error': bounded_preview(str(exc))})
    finally:
        if executor is not None:
            executor.registry.cleanup()


def main() -> int:
    from .store import BuilderStore

    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--run')
    parser.add_argument('--lease-fd', type=int)
    parser.add_argument('--refresh', choices=('cloud', 'local'))
    args = parser.parse_args()
    try:
        store = BuilderStore(args.db)
    except Exception as exc:
        emit_diagnostic(startup_diagnostic(exc, 'store'))
        return 1
    if args.refresh:
        refresh_catalog(args.root, store, args.refresh)
    elif args.run:
        execute_run(args.root, store, args.run)
    else:
        parser.error('A run or catalog refresh is required')
    return 0


if __name__ == '__main__':
    try:
        if not __package__:
            _bootstrap()
        emit_diagnostic({'type': 'worker_starting'})
        exit_code = main()
    except Exception as error:
        emit_diagnostic(startup_diagnostic(error, 'bootstrap'))
        exit_code = 1
    raise SystemExit(exit_code)
