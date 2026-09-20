#!/usr/bin/env python3
"""Observe one Browser Use Cloud V4 run without resubmitting after uncertainty."""

from __future__ import annotations

import json
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import UUID

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from config_loader import get_config_value
from remote_completion import RemoteCompletionError, completion_for_error, submission_error
from tool_progress import emit_tool_progress

API_BASE = 'https://api.browser-use.com/api/v4/runs'
BROWSERS_BASE = 'https://api.browser-use.com/api/v4/browsers'
POLL_SECONDS = 3
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_REPORT_CHARS = 28000
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_COST_USD = 3.0
TERMINAL = frozenset({'completed', 'failed', 'cancelled'})
FULL_REPORT = re.compile(r'^Full report:\s*`([^`\r\n]+)`\s*$', re.IGNORECASE | re.MULTILINE)


def _live_url(value):
    """The live URL is a bearer capability; accept only the documented viewer."""
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 3000 \
            or any(c in value for c in '\r\n'):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.hostname != 'live.browser-use.com'
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443)
                or (parsed.path and not parsed.path.startswith('/'))):
            return None
    except ValueError:
        return None
    return value


def _json(response):
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError('Browser Use Cloud response exceeded the result limit')
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError('Browser Use Cloud returned an invalid response')
    return value


def _request(session, method, url, *, timeout, **kwargs):
    response = session.request(method, url, timeout=timeout, allow_redirects=False, **kwargs)
    if not 200 <= response.status_code < 300:
        # No response body is logged; providers can echo task text or credentials.
        raise RuntimeError(f'Browser Use Cloud HTTP {response.status_code}')
    return _json(response)


def _archive(task, report):
    from stash_helper import StashFile, open_space

    space, _ = open_space(scope='session', labels=['browser_use_cloud', 'research'])
    saved = StashFile(space).save_text(
        content=f'# Browser Use Cloud research\n\n## Request\n\n{task}\n\n## Report\n\n{report}\n',
        name='browser-research.md', on_conflict='version',
        tags=['browser_use_cloud', 'research'], tool_origin='browser_use_cloud',
    )
    return saved['ref']


def _full_report_path(report):
    match = FULL_REPORT.search(report)
    if not match:
        return None, None
    path = match.group(1)
    parsed = PurePosixPath(path)
    if (len(path) > 240 or str(parsed) != path or len(parsed.parts) < 2
            or parsed.parts[0] != 'outputs' or '..' in parsed.parts
            or '\\' in path or parsed.suffix.lower() != '.md'):
        return match, None
    return match, path


def _signed_artifact_url(value):
    if not isinstance(value, str) or len(value) > 5000 or value != value.strip() \
            or any(char in value for char in '\r\n'):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and parsed.username is None and parsed.password is None
                and parsed.port in (None, 443) and parsed.fragment == '' and bool(parsed.query)
                and re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.s3\.[a-z0-9-]+\.amazonaws\.com',
                                 parsed.hostname or '') is not None)
    except ValueError:
        return False


def _fetch_full_report(session, workspace_id, path, *, download=requests.get):
    """Import one referenced Markdown file from the run's owned V4 workspace."""
    workspace_id = str(UUID(workspace_id))
    listing = _request(session, 'GET',
                       f'https://api.browser-use.com/api/v4/workspaces/{workspace_id}/files',
                       timeout=8, params={'prefix': path, 'limit': 10, 'includeUrls': 'true'})
    files = listing.get('files')
    if not isinstance(files, list):
        raise ValueError('Browser Use Cloud returned an invalid workspace file list')
    matches = [item for item in files
               if isinstance(item, dict) and item.get('path') == path]
    if len(matches) != 1 or type(matches[0].get('size')) is not int \
            or not 0 < matches[0]['size'] <= MAX_ARTIFACT_BYTES:
        raise ValueError('Browser Use Cloud full report is unavailable or too large')
    url = matches[0].get('url')
    if not _signed_artifact_url(url):
        raise ValueError('Browser Use Cloud full report URL is not an allowed signed storage URL')
    response = download(url, timeout=10, allow_redirects=False, stream=True)
    try:
        if response.status_code != 200:
            raise ValueError('Browser Use Cloud full report download failed')
        length = response.headers.get('Content-Length')
        if length and int(length) > MAX_ARTIFACT_BYTES:
            raise ValueError('Browser Use Cloud full report exceeded the size limit')
        body = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            body.extend(chunk)
            if len(body) > MAX_ARTIFACT_BYTES:
                raise ValueError('Browser Use Cloud full report exceeded the size limit')
        if len(body) != matches[0]['size']:
            raise ValueError('Browser Use Cloud full report size did not match its workspace record')
        content = body.decode('utf-8')
        if not content.strip() or '\0' in content:
            raise ValueError('Browser Use Cloud full report is not valid Markdown text')
        return content
    finally:
        response.close()


def _stop_owned_browsers(session, agent_session_id):
    """Stop only active browsers tied to the new agent session from this run."""
    listing = _request(session, 'GET', BROWSERS_BASE, timeout=4, params={
        'agentSessionId': agent_session_id, 'filterBy': 'active',
        'pageSize': 100, 'pageNumber': 1,
    })
    items = listing.get('items')
    total = listing.get('totalItems')
    if not isinstance(items, list) or type(total) is not int or total > 100 or total != len(items):
        raise ValueError('Browser Use Cloud returned an invalid browser list')
    browser_ids = []
    for item in items:
        if not isinstance(item, dict) or item.get('agentSessionId') != agent_session_id:
            raise ValueError('Browser Use Cloud browser ownership could not be verified')
        if item.get('status') != 'active':
            raise ValueError('Browser Use Cloud returned an invalid active browser list')
        try:
            browser_ids.append(str(UUID(item['id'])))
        except (KeyError, TypeError, ValueError):
            raise ValueError('Browser Use Cloud returned an invalid browser ID') from None

    unresolved = False
    for browser_id in browser_ids:
        try:
            stopped = _request(session, 'PATCH', f'{BROWSERS_BASE}/{browser_id}', timeout=4,
                               json={'action': 'stop'})
            if stopped.get('id') != browser_id or stopped.get('status') != 'stopped':
                unresolved = True
        except (requests.RequestException, RuntimeError, ValueError):
            # A lost stop receipt may still have stopped the browser. Re-read the
            # active list below rather than issuing another state-changing request.
            unresolved = True

    if not unresolved:
        return

    remaining = _request(session, 'GET', BROWSERS_BASE, timeout=4, params={
        'agentSessionId': agent_session_id, 'filterBy': 'active',
        'pageSize': 100, 'pageNumber': 1,
    })
    if remaining.get('totalItems') != 0 or remaining.get('items') != []:
        raise ValueError('Browser Use Cloud still reports an active browser')


def _usd(value):
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Browser Use Cloud returned an invalid cost') from None
    if not amount.is_finite() or amount < 0:
        raise ValueError('Browser Use Cloud returned an invalid cost')
    return amount


def _costs(session, agent_session_id, run_cost):
    """Read completed run and owned browser/proxy charges without guessing billing."""
    run = _usd(run_cost)
    listing = _request(session, 'GET', BROWSERS_BASE, timeout=4, params={
        'agentSessionId': agent_session_id, 'pageSize': 100, 'pageNumber': 1,
    })
    items = listing.get('items')
    total = listing.get('totalItems')
    if not isinstance(items, list) or type(total) is not int or total > 100 or total != len(items):
        raise ValueError('Browser Use Cloud returned an incomplete browser cost list')
    browser = Decimal(0)
    proxy = Decimal(0)
    for item in items:
        if (not isinstance(item, dict) or item.get('agentSessionId') != agent_session_id
                or item.get('status') != 'stopped'):
            raise ValueError('Browser Use Cloud browser costs are not final')
        browser += _usd(item.get('browserCost'))
        proxy += _usd(item.get('proxyCost'))
    return {key: format(value, 'f') for key, value in {
        'run': run, 'browser': browser, 'proxy': proxy, 'total': run + browser + proxy,
    }.items()}


def run(args, *, session=None, sleep=time.sleep, progress=emit_tool_progress, now=time.time):
    task = args.get('task') if isinstance(args, dict) else None
    if not isinstance(task, str) or not 1 <= len(task.strip()) <= 8000:
        return {'ok': False, 'completion': 'rejected', 'speech': 'A research goal is required.'}
    use_profile = args.get('use_profile', False)
    if type(use_profile) is not bool:
        return {'ok': False, 'completion': 'rejected', 'speech': 'use_profile must be a boolean.'}
    profile_id = None
    if use_profile:
        configured_id = get_config_value('BROWSER_USE_CLOUD_PROFILE_ID', '')
        try:
            profile_id = str(UUID(configured_id.strip()))
        except (AttributeError, ValueError):
            return {'ok': False, 'completion': 'rejected',
                    'speech': 'Browser Use Cloud saved profile is not configured or is invalid.'}
    key = get_config_value('BROWSER_USE_API_KEY', '').strip()
    if not key:
        return {'ok': False, 'completion': 'rejected', 'speech': 'Browser Use Cloud API key is not configured.'}
    deadline_raw = get_config_value('JARVIS_BACKGROUND_DEADLINE', '')
    try:
        deadline = float(deadline_raw)
    except (TypeError, ValueError):
        return {'ok': False, 'completion': 'rejected', 'speech': 'Browser Use Cloud requires a background job deadline.'}
    if deadline - now() < 30:
        return {'ok': False, 'completion': 'rejected', 'speech': 'Not enough time remains to start cloud research.'}

    session = session or requests.Session()
    session.headers.update({'X-Browser-Use-API-Key': key, 'Content-Type': 'application/json'})
    run_id = None
    agent_session_id = None
    live_url = None
    terminal_status = None
    cleanup_warning = None

    def delivered(result):
        if cleanup_warning:
            result['speech'] += ('\n\nBrowser cleanup needs attention: Jarvis could not verify that the '
                                 f'hosted browser stopped. Check run {run_id} in Browser Use Cloud '
                                 'and stop any active browser there.')
            result.setdefault('data', {})['browser_stop_verified'] = False
        return result

    try:
        # One POST only. A lost response is ambiguous and must never start a second run.
        payload = {'task': task.strip(), 'maxCostUsd': MAX_COST_USD}
        if profile_id:
            payload['browserSettings'] = {'profileId': profile_id}
        response = session.request('POST', API_BASE, json=payload,
                                   timeout=min(20, max(1, deadline - now() - 10)), allow_redirects=False)
        if not 200 <= response.status_code < 300:
            if response.status_code == 402:
                raise RemoteCompletionError('Browser Use Cloud has insufficient credits (HTTP 402)', 'rejected')
            raise submission_error(response.status_code, f'Browser Use Cloud rejected the run (HTTP {response.status_code})')
        created = _json(response)
        run_id = created.get('id')
        try:
            run_id = str(UUID(run_id)) if isinstance(run_id, str) else None
        except ValueError:
            run_id = None
        if run_id is None:
            raise ValueError('Browser Use Cloud did not return a valid run ID')
        try:
            agent_session_id = str(UUID(created['sessionId']))
        except (KeyError, TypeError, ValueError):
            # Keep observing the accepted run, but make the missing cleanup
            # identity visible with its final result.
            cleanup_warning = 'missing_session_id'
        progress({'phase': 'Cloud browser starting with saved profile' if use_profile
                   else 'Cloud browser starting', 'run_id': run_id})

        after = 0
        last_status = None
        while deadline - now() > 15:
            timeout = min(15, max(1, deadline - now() - 10))
            if live_url is None:
                try:
                    events = _request(session, 'GET', f'{API_BASE}/{run_id}/events', timeout=timeout,
                                      params={'after': after, 'limit': 100, 'include_output': 'false'})
                    for event in events.get('events', []) if isinstance(events.get('events'), list) else []:
                        if not isinstance(event, dict):
                            continue
                        event_id = event.get('id')
                        if type(event_id) is int and event_id > after:
                            after = event_id
                        if event.get('type') == 'browser.ready':
                            event_data = event.get('data')
                            live_url = _live_url(event_data.get('live_view_url')) if isinstance(event_data, dict) else None
                            if live_url:
                                progress({'phase': 'Browser live; researching', 'run_id': run_id,
                                          'live_view_url': live_url})
                                break
                    # One page per poll is enough for the preview. Always check
                    # status and sleep; a stale hasMore page must not spin.
                except (requests.RequestException, ValueError, RuntimeError):
                    # Preview is optional. The status endpoint remains authoritative.
                    pass
            try:
                status = _request(session, 'GET', f'{API_BASE}/{run_id}/status', timeout=timeout).get('status')
            except (requests.RequestException, ValueError, RuntimeError):
                # Observation GETs are safe to retry; the create POST is not.
                sleep(min(POLL_SECONDS, max(0, deadline - now() - 15)))
                continue
            if status not in TERMINAL | {'queued', 'dispatching', 'running'}:
                raise ValueError('Browser Use Cloud returned an unknown run state')
            if status != last_status:
                last_status = status
                progress({'phase': f'Cloud browser {status}', 'run_id': run_id,
                          **({'live_view_url': live_url} if live_url else {})})
            if status in TERMINAL:
                if terminal_status is None:
                    terminal_status = status
                    if agent_session_id:
                        try:
                            _stop_owned_browsers(session, agent_session_id)
                            progress({'phase': 'Hosted browser stopped', 'run_id': run_id})
                        except (requests.RequestException, RuntimeError, ValueError):
                            cleanup_warning = 'stop_unverified'
                    if cleanup_warning:
                        progress({'phase': 'Browser stop needs verification', 'run_id': run_id})
                try:
                    result = _request(session, 'GET', f'{API_BASE}/{run_id}', timeout=timeout)
                except (requests.RequestException, ValueError, RuntimeError):
                    sleep(min(POLL_SECONDS, max(0, deadline - now() - 15)))
                    continue
                if result.get('id') != run_id or result.get('status') != status:
                    raise ValueError('Browser Use Cloud terminal result did not match its run')
                costs = None
                if agent_session_id and not cleanup_warning and result.get('totalCostUsd') is not None:
                    try:
                        costs = _costs(session, agent_session_id, result['totalCostUsd'])
                    except (requests.RequestException, RuntimeError, ValueError):
                        # Research still belongs in chat if billing metadata is late.
                        pass
                report = result.get('result')
                if not isinstance(report, str) or not report.strip():
                    speech = (f'Browser Use Cloud {status}.' if status != 'completed'
                              else 'Browser Use Cloud finished without a report.')
                    return delivered({'ok': False, 'completion': 'completed', 'speech': speech,
                                      'error': str(result.get('error') or status)[:2000],
                                      'data': {'run_id': run_id}})
                report = report.strip()
                marker, path = _full_report_path(report)
                full_report = None
                if path and result.get('workspaceId') and deadline - now() > 30:
                    try:
                        full_report = _fetch_full_report(session, result['workspaceId'], path)
                    except (requests.RequestException, RuntimeError, ValueError, TypeError, UnicodeError):
                        # The provider summary is still useful and will be saved.
                        pass
                try:
                    stash_ref = _archive(task.strip(), full_report or report)
                except Exception:
                    stash_ref = None
                if marker:
                    if full_report and stash_ref:
                        note = 'Full report saved in Jarvis Stash; use **Open full research** above.'
                    elif stash_ref:
                        note = 'The provider workspace file could not be imported; **Open saved summary** contains the returned text.'
                    else:
                        note = 'The provider workspace file could not be saved in Jarvis Stash.'
                    report = report.replace(marker.group(0), note, 1)
                if len(report) > MAX_REPORT_CHARS:
                    report = report[:MAX_REPORT_CHARS] + '\n\n[Report truncated in chat; open the Stash copy for the full text.]'
                    if stash_ref is None:
                        return delivered({'ok': False, 'completion': 'completed',
                                          'speech': 'Browser Use Cloud finished, but its report exceeded the chat limit and could not be saved.',
                                          'data': {'run_id': run_id}})
                if status != 'completed':
                    report = f'Browser Use Cloud {status}; partial report follows.\n\n{report}'
                return delivered({'ok': status == 'completed',
                        **({'completion': 'completed'} if status != 'completed' else {}),
                        **({'error': str(result.get('error') or status)[:2000]} if status != 'completed' else {}),
                        'speech': (f'Saved research: {stash_ref}\n\n' if stash_ref else '') + report,
                        'data': {'run_id': run_id, 'browser_research': {
                            'kind': 'browser_research', 'stash_ref': stash_ref,
                            'provider': 'Browser Use Cloud', 'model': result.get('model') or 'default',
                            'profile_used': use_profile,
                            'sources': [],
                            **({'full_report_imported': bool(full_report and stash_ref)} if marker else {}),
                            **({'cost_usd': costs} if costs else {}),
                        }}})
            sleep(min(POLL_SECONDS, max(0, deadline - now() - 15)))
        if terminal_status:
            return delivered({'ok': False, 'completion': 'completed',
                              'speech': f'Browser Use Cloud {terminal_status}, but Jarvis could not retrieve its report.',
                              'data': {'run_id': run_id}})
        raise TimeoutError('Browser Use Cloud run did not finish before the background deadline')
    except Exception as exc:
        completion = 'completed' if run_id and terminal_status else completion_for_error(exc)
        return delivered({'ok': False, 'completion': completion,
                'speech': (f'Browser Use Cloud {terminal_status}, but Jarvis could not retrieve its report.'
                           if terminal_status else 'Browser Use Cloud could not confirm the final result.'
                           if run_id else 'Browser Use Cloud could not start.'),
                'error': str(exc)[:2000], 'data': {'run_id': run_id} if run_id else {}})


if __name__ == '__main__':
    try:
        arguments = json.loads(sys.argv[1])
        result = run(arguments)
    except Exception as exc:
        result = {'ok': False, 'completion': 'unknown', 'speech': 'Browser Use Cloud observation failed.',
                  'error': type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False))
