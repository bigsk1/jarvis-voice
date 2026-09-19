"""Internal child entrypoint for a durably admitted browser callback job.

The tool-discovery script rejects direct execution. BrowserService alone launches
this child through the shared process supervisor with the admitted runtime env.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'lib')]

from browser_agent import BrowserPreflightError, research  # noqa: E402
from config_loader import load_config  # noqa: E402
from tool_progress import emit_tool_progress  # noqa: E402

from lib.webhook_integrations.browser_audit import BrowserAudit, NullBrowserAudit  # noqa: E402


def main():
    try:
        load_config(os.environ.get('JARVIS_MODE', 'cloud'))
        request = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        if (not isinstance(request, dict) or set(request) != {'arguments', 'job_id', 'attempt_id'}
                or not isinstance(request['arguments'], dict)):
            raise ValueError('Invalid private browser job request')
        directory = os.environ.get('JARVIS_BROWSER_USE_AUDIT_DIR')
        audit = BrowserAudit(directory=directory) if directory else NullBrowserAudit()
        context = {'job_id': request['job_id'], 'attempt_id': request['attempt_id'],
                   'mode': os.environ.get('JARVIS_MODE', ''),
                   'proxy_policy': os.environ.get('JARVIS_TOOL_PROXY_POLICY', '')}
        result = research(request['arguments'], progress=lambda update: emit_tool_progress({
            'tool': 'browser_use', **(update if isinstance(update, dict) else {'phase': update}),
        }), audit=audit, audit_context=context)
    except BrowserPreflightError as exc:
        # Trusted fixed diagnostic, raised before container/model execution.
        result = {'ok': False, 'completion': 'rejected', 'error_code': 'browser_preflight_failed',
                  'speech': str(exc) + ' No browser work was started.'}
    except Exception as exc:
        # research() returns a terminal partial result after a verified stop,
        # or unknown if container termination cannot be established. Escaping
        # preflight exceptions mean no container/model call began.
        result = {'ok': False, 'completion': 'rejected', 'error_type': type(exc).__name__,
                  'speech': 'Browser research could not start. Check its configuration; no browser work was started.'}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
