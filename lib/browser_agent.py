"""Jarvis boundary for the pinned, containerized upstream Browser Use agent.

Browser Use owns reasoning/actions/DOM handling. Jarvis owns provider routing,
HTTP policy, Stash and supervision. Only bounded JSON crosses the stdio bridge.
"""
import base64
import contextvars
import html
import ipaddress
import json
import os
import queue
import signal
import socket
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from config_loader import get_active_config_mode, get_config_value
from http_client import build_proxy_url_attempts, proxy_response_indicates_tunnel_failure
from llm_provider import create_configured_provider
from requests.adapters import HTTPAdapter
from stash_helper import SecurityError, StashFile, is_blocked_ip, open_space
from tool_schema import ToolSchema

from lib.webhook_integrations.browser_audit import NullBrowserAudit

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_MAX_FRAME = 8 * 1024 * 1024
MAX_RESOURCE = 3 * 1024 * 1024


class BrowserPreflightError(RuntimeError):
    """Known setup failure before any container or provider request starts."""


class BrowserOutcomeUnknown(RuntimeError):
    """The browser container could not be proven stopped; no terminal claim is safe."""


def resolve_url(url, *, allowed_hosts=()):
    """Validate and resolve once so the subsequent connection can use that peer."""
    if not isinstance(url, str) or '\\' in url:
        raise SecurityError('URL is malformed or contains an ambiguous backslash')
    parts = urlsplit(url)
    if (len(url) > 2048 or parts.scheme not in {'http', 'https'} or not parts.hostname
            or parts.username or parts.password):
        raise ValueError('Expected a public HTTP(S) URL without credentials')
    hostname = parts.hostname.lower()
    try:
        records = socket.getaddrinfo(hostname, parts.port or (443 if parts.scheme == 'https' else 80),
                                     socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SecurityError(f'Cannot resolve browser destination: {hostname}') from exc
    addresses = sorted({record[4][0] for record in records},
                       key=lambda value: (ipaddress.ip_address(value).version != 4, value))
    if not addresses:
        raise SecurityError('Browser destination has no resolved address')
    try:
        ipaddress.ip_address(hostname)
        literal_address = True
    except ValueError:
        literal_address = False
    # A hostname allowlist must not turn a public name into permission to
    # resolve privately later. Local test targets require an explicit IP literal.
    allow_private = literal_address and hostname in {str(item).strip().lower() for item in allowed_hosts}
    if not allow_private and any(is_blocked_ip(address) or not ipaddress.ip_address(address).is_global
                                 for address in addresses):
        raise SecurityError('Browser destination resolves to a blocked IP range')
    return url, addresses[0]


def validate_url(url, *, allowed_hosts=()):
    return resolve_url(url, allowed_hosts=allowed_hosts)[0]


class _PinnedHTTPSAdapter(HTTPAdapter):
    """Connect to a resolved IP while retaining the URL host for SNI/cert checks."""
    def __init__(self, hostname):
        self.hostname = hostname.encode('idna').decode('ascii')
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs.update(server_hostname=self.hostname, assert_hostname=self.hostname)
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs.update(server_hostname=self.hostname, assert_hostname=self.hostname)
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _pinned_destination(url, address):
    parts = urlsplit(url)
    host = f'[{address}]' if ':' in address else address
    if parts.port is not None:
        host += f':{parts.port}'
    pinned = urlunsplit((parts.scheme, host, parts.path or '/', parts.query, ''))
    logical = parts.hostname.encode('idna').decode('ascii')
    host_header = f'[{logical}]' if ':' in logical else logical
    if parts.port is not None:
        host_header += f':{parts.port}'
    return pinned, host_header


@contextmanager
def pinned_http_request(method, url, address, **kwargs):
    """Use one validated address through every proxy/direct attempt."""
    pinned, host_header = _pinned_destination(url, address)
    headers = dict(kwargs.pop('headers', {}))
    headers['Host'] = host_header
    attempts = build_proxy_url_attempts(direct_fallback_default=True)
    last_error = None
    for proxy_url in attempts:
        session = requests.Session()
        session.trust_env = False
        if urlsplit(url).scheme == 'https':
            session.mount('https://', _PinnedHTTPSAdapter(urlsplit(url).hostname))
        proxies = ({'http': proxy_url, 'https': proxy_url} if proxy_url else
                   {'http': None, 'https': None, 'all': None})
        try:
            response = session.request(method, pinned, headers=headers, proxies=proxies, **kwargs)
        except requests.RequestException as exc:
            last_error = exc
            session.close()
            continue
        if proxy_url and proxy_response_indicates_tunnel_failure(response):
            response.close()
            session.close()
            continue
        try:
            yield response
        finally:
            response.close()
            session.close()
        return
    if last_error is not None:
        raise last_error
    raise requests.RequestException('No permitted browser network route is available')


class ResearchArchive:
    """Persist the DOM evidence actually presented to the agent, then its report."""
    def __init__(self, task):
        self.space, _ = open_space(scope='session', labels=['browser_use'])
        self.files = StashFile(self.space)
        self.task, self.pages = task, []
        self.ref = None

    def checkpoint(self, snapshot=None, report=None):
        if snapshot is not None:
            self.pages.append({key: str(snapshot[key])[:40000] for key in ('title', 'url', 'text')})
        content = '# Browser research\n\n' + html.escape(self.task, quote=False) + '\n\n'
        safe_report = html.escape(report or 'Research in progress; the evidence below is incomplete.', quote=False)
        content += '## Report\n\n' + safe_report + '\n\n'
        for index, page in enumerate(self.pages, 1):
            # DOM text contains Browser Use's HTML-like element notation. Keep it
            # literal so the Stash Markdown viewer never interprets page evidence
            # as document markup.
            fence = '```'
            while fence in page['text']:
                fence += '`'
            title = html.escape(page['title'].replace('\n', ' ').replace('\r', ' ').strip(), quote=False)
            url = html.escape(page['url'], quote=False)
            content += (f'## Source {index}\n\n**Page:** {title}\n\n'
                        f'**URL:** {url}\n\n{fence}text\n{page["text"]}\n{fence}\n\n')
        saved = self.files.save_text(content, 'browser-research.md', on_conflict='overwrite',
                                     tags=['browser_use', 'research'], tool_origin='browser_use')
        self.ref = saved['ref']
        return self.ref


def invoke_model(provider, provider_name, payload):
    """Adapt upstream's structured-response protocol to the existing Jarvis factory."""
    system, messages = [], []
    for message in payload['messages']:
        if message['role'] not in {'system', 'user', 'assistant'}:
            raise ValueError('Unsupported browser message role')
        content = message.get('content', '')
        if isinstance(content, list):
            if any(part.get('type') != 'text' for part in content):
                raise ValueError('Browser model bridge is text-only')
            content = '\n'.join(part['text'] for part in content)
        if not isinstance(content, str):
            raise ValueError('Invalid browser message')
        if message['role'] == 'system':
            system.append(content)
        else:
            messages.append({'role': message['role'], 'content': content})
    schema = payload.get('schema')
    tools = []
    if schema is not None:
        tool = ToolSchema('browser_response', 'Return the requested browser agent response.', schema, '')
        tools = [tool.to_anthropic_format() if provider_name in {'ollama', 'helper', 'anthropic'} else tool.to_openai_format()]
        system.append('Return your response by calling browser_response with the required structured fields.')
    text, call, _, _ = provider.chat_with_tools(messages, tools, system_prompt='\n\n'.join(system))
    if schema is None:
        if not isinstance(text, str):
            raise ValueError('Missing browser model response')
        return text
    if isinstance(call, dict) and call.get('name') == 'browser_response':
        return call['arguments']
    # Some supported models return structured text instead of a function call.
    raw = (text or '').strip()
    if raw.startswith('```') and raw.endswith('```'):
        raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
    return json.loads(raw)


class BrowserFetch:
    """Read-only browser transport through the existing proxy and SSRF helpers.

    Chrome has no external network. Redirects are returned to Chrome, then each
    resulting request is checked again. This is not a general forwarding proxy.
    """
    def __init__(self, deadline, allowed_hosts=(), *, audit=None, audit_context=None):
        self.deadline, self.allowed_hosts = deadline, allowed_hosts
        self.audit = audit or NullBrowserAudit()
        self.audit_context = dict(audit_context or {})
        self.lock = threading.Lock()
        self.requests = self.bytes = 0

    def __call__(self, payload):
        raw_url, method = payload.get('url'), payload.get('method')
        resource_type = payload.get('resource_type')
        started = False
        try:
            url, address = resolve_url(raw_url, allowed_hosts=self.allowed_hosts)
            if method not in {'GET', 'HEAD'} or resource_type in {'WebSocket', 'Media'}:
                raise ValueError('Browser request is outside read-only research')
            with self.lock:
                self.requests += 1
                request_count = self.requests
                if request_count > 400 or self.bytes >= 96 * 1024 * 1024:
                    raise ValueError('Browser network budget reached')
            if time.time() >= self.deadline:
                raise TimeoutError('Browser deadline reached')
            self.audit.emit('request_started', url=url, method=method, resource_type=resource_type,
                            request_count=request_count, **self.audit_context)
            started = True
            # No host Authorization, environment secrets or arbitrary headers. Preserve the
            # bounded Chromium identity/navigation headers so the host request is coherent
            # with the browser that produced it.
            allowed = {'accept', 'accept-language', 'user-agent', 'content-type', 'cookie',
                       'referer', 'origin', 'sec-ch-ua', 'sec-ch-ua-mobile',
                       'sec-ch-ua-platform', 'sec-fetch-dest', 'sec-fetch-mode',
                       'sec-fetch-site', 'sec-fetch-user', 'upgrade-insecure-requests'}
            headers = {}
            for key, value in payload.get('headers', {}).items():
                lower = key.lower()
                if lower in allowed and isinstance(value, str) and len(value) <= 8192:
                    # http_request's default-UA guard is case-sensitive.
                    headers['User-Agent' if lower == 'user-agent' else key] = value
            with pinned_http_request(method, url, address, headers=headers, allow_redirects=False, stream=True,
                                     timeout=min(15, max(1, self.deadline - time.time()))) as response:
                body = bytearray()
                for chunk in response.iter_content(65536):
                    if time.time() >= self.deadline or len(body) + len(chunk) > MAX_RESOURCE:
                        raise ValueError('Browser resource exceeds deadline or size limit')
                    body.extend(chunk)
                with self.lock:
                    self.bytes += len(body)
                self.audit.emit('request_completed', url=url, method=method, resource_type=resource_type,
                                request_count=request_count, status_code=response.status_code,
                                bytes=len(body), **self.audit_context)
                # requests has already decompressed bytes; Chrome must not do it again.
                excluded = {'content-encoding', 'content-length', 'transfer-encoding', 'connection',
                            'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'set-cookie'}
                result_headers = [{'name': key, 'value': value} for key, value in response.headers.items()
                                  if key.lower() not in excluded]
                # Preserve separate cookies (a combined comma header corrupts Expires).
                raw_headers = getattr(response.raw, 'headers', None)
                if raw_headers and hasattr(raw_headers, 'getlist'):
                    result_headers.extend({'name': 'Set-Cookie', 'value': value} for value in raw_headers.getlist('Set-Cookie'))
                return {'responseCode': response.status_code, 'responseHeaders': result_headers,
                        'body': base64.b64encode(body).decode('ascii')}
        except Exception as exc:
            self.audit.emit('request_failed' if started else 'request_rejected',
                            level='WARNING', url=raw_url, method=method, resource_type=resource_type,
                            error_type=type(exc).__name__, **self.audit_context)
            raise


def container_command(name):
    return ['docker', 'compose', '-p', 'jarvis-browser', '-f', str(ROOT / 'docker-compose.browser.yml'),
            'run', '--rm', '-T', '--no-deps', '--pull', 'never', '--name', name, 'browser']


def check_runtime():
    """Fail before starting work when Docker or the explicitly pulled image is absent."""
    import yaml

    definition = yaml.safe_load((ROOT / 'docker-compose.browser.yml').read_text())
    image = definition['services']['browser']['image']
    try:
        result = subprocess.run(['docker', 'image', 'inspect', image],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BrowserPreflightError('Docker Engine is unavailable. Start Docker and run bin/jarvis-browser-use check.') from exc
    if result.returncode:
        raise BrowserPreflightError('Browser Use image or Docker Engine unavailable. '
                                    'Start Docker and pull the pinned image with docker compose -f docker-compose.browser.yml pull.')


def observation_deadline(now, job_deadline):
    """Keep time to stop Chrome, archive evidence and deliver the callback."""
    deadline = min(now + 870, job_deadline - 45)
    if deadline <= now:
        raise BrowserPreflightError('Browser task has too little time left to start research.')
    return deadline


def install_runtime():
    """Fetch the pinned optional image during an explicit operator setup action."""
    try:
        check_runtime()
        return False
    except BrowserPreflightError:
        pass
    try:
        engine = subprocess.run(['docker', 'info'], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BrowserPreflightError('Docker Engine is unavailable. Start Docker, then retry setup.') from exc
    if engine.returncode:
        raise BrowserPreflightError('Docker Engine is unavailable. Start Docker, then retry setup.')
    try:
        pulled = subprocess.run(
            ['docker', 'compose', '-f', str(ROOT / 'docker-compose.browser.yml'), 'pull', 'browser'],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BrowserPreflightError('The Browser Use image could not be downloaded. Check Docker and retry setup.') from exc
    if pulled.returncode:
        detail = (pulled.stderr or '').strip().splitlines()
        suffix = f' ({detail[-1][:300]})' if detail else ''
        raise BrowserPreflightError('The Browser Use image could not be downloaded' + suffix)
    check_runtime()
    return True


def run_container(config, *, provider, provider_name, fetch, archive, progress,
                  audit=None, audit_context=None):
    audit, audit_context = audit or NullBrowserAudit(), dict(audit_context or {})
    name = os.environ.get('JARVIS_BROWSER_USE_CONTAINER_NAME') or 'jarvis-browser-job-' + uuid.uuid4().hex
    process = subprocess.Popen(container_command(name), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, cwd=ROOT)
    frames, write_lock = queue.Queue(maxsize=64), threading.Lock()
    pool = ThreadPoolExecutor(max_workers=8)
    active = set()
    stopped = False

    def write(value):
        raw = (json.dumps(value, ensure_ascii=False) + '\n').encode()
        if len(raw) > BRIDGE_MAX_FRAME:
            raise ValueError('Browser bridge response too large')
        with write_lock:
            process.stdin.write(raw)
            process.stdin.flush()

    def read():
        try:
            while True:
                line = process.stdout.readline(BRIDGE_MAX_FRAME + 1)
                if len(line) > BRIDGE_MAX_FRAME:
                    frames.put({'error': 'frame_too_large'})
                    break
                if not line:
                    break
                frames.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            frames.put(None)

    def respond(frame, value=None, error=False):
        write({'id': frame['id'], 'value': value, 'error': error})

    def work(frame):
        event = 'fetch' if frame['method'] == 'fetch' else 'model_call'
        try:
            if event == 'model_call':
                audit.emit('model_call_started', provider=provider_name,
                           model=str(provider.model), **audit_context)
            value = fetch(frame['value']) if frame['method'] == 'fetch' else invoke_model(provider, provider_name, frame['value'])
            respond(frame, value)
            if event == 'model_call':
                audit.emit('model_call_completed', provider=provider_name,
                           model=str(provider.model), **audit_context)
        except Exception as exc:
            if event == 'model_call':
                audit.emit('model_call_failed', level='WARNING', provider=provider_name,
                           model=str(provider.model), error_type=type(exc).__name__, **audit_context)
            respond(frame, error=True)  # Never send provider credentials/errors into Chrome.

    try:
        write(config)
        threading.Thread(target=read, daemon=True).start()
        while time.time() < config['deadline']:
            try:
                frame = frames.get(timeout=.2)
            except queue.Empty:
                continue
            if frame is None or 'error' in frame:
                raise RuntimeError('Browser container stopped without a verified result')
            if 'result' in frame:
                result = frame['result']
                if not isinstance(result, dict) or type(result.get('ok')) is not bool:
                    raise ValueError('Invalid browser completion')
                step_count = result.get('step_count')
                error_count = result.get('error_count')
                audit_fields = {}
                if type(step_count) is int and 0 <= step_count <= 1000:
                    audit_fields['step_count'] = step_count
                if type(error_count) is int and 0 <= error_count <= 1000:
                    audit_fields['error_count'] = error_count
                audit.emit('agent_finished', ok=result['ok'], **audit_fields, **audit_context)
                return result
            method = frame.get('method')
            if method == 'snapshot':
                archive.checkpoint(frame['value'])
                audit.emit('page_observed', url=frame['value'].get('url'),
                           step=frame['value'].get('step'), **audit_context)
                progress(f'Researching; step {frame["value"]["step"]} of {config["max_steps"]}')
                respond(frame, True)
            elif method in {'fetch', 'llm'}:
                active = {future for future in active if not future.done()}
                if len(active) >= 32:
                    respond(frame, error=True)
                    continue
                active.add(pool.submit(contextvars.copy_context().run, work, frame))
            else:
                raise ValueError('Unsupported browser bridge request')
        raise TimeoutError('Browser task deadline reached')
    finally:
        # Removing only this invocation's container is authoritative Chrome stop.
        # The in-container watchdog also stops it if this host process is killed.
        try:
            stopped = subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, timeout=10).returncode == 0
            if not stopped:
                probe = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', name],
                                       capture_output=True, timeout=5)
                stopped = probe.returncode == 1 and b'No such' in probe.stderr
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            for handle in (process.stdin, process.stdout):
                handle.close()
            pool.shutdown(wait=False, cancel_futures=True)
        if not stopped:
            raise BrowserOutcomeUnknown('Browser container stop could not be verified')


def research(arguments, *, progress=lambda phase: None, provider=None, provider_name=None,
             container_runner=run_container, fetch=None, archive_factory=ResearchArchive,
             audit=None, audit_context=None):
    from jsonschema import Draft202012Validator

    manifest = json.loads((ROOT / 'skills/browser_use.tool.json').read_text())
    Draft202012Validator(manifest['parameters']).validate(arguments)
    if container_runner is run_container:
        check_runtime()
    if provider is None:
        provider_name, _, provider = create_configured_provider(mode=get_active_config_mode(), disable_server_side_tools=True)
    if not provider_name:
        raise ValueError('Missing selected provider identity')
    now = time.time()
    deadline = observation_deadline(now, float(get_config_value('JARVIS_BACKGROUND_DEADLINE', now + 900)))
    allowed = tuple(filter(None, (h.strip() for h in str(get_config_value('BROWSER_USE_ALLOWED_HOSTS', '')).split(','))))
    validate_url(arguments['url'], allowed_hosts=allowed)
    audit, audit_context = audit or NullBrowserAudit(), dict(audit_context or {})
    archive = archive_factory(arguments['task'])
    archive.checkpoint()
    config = {**arguments, 'max_steps': arguments.get('max_steps', 15),
              'deadline': deadline, 'model': str(provider.model)}
    progress({'phase': 'Starting Browser Use in Docker', 'stash_ref': archive.ref})
    previous = {}
    if threading.current_thread() is threading.main_thread():
        def interrupted(*_):
            raise InterruptedError('Browser task interrupted')
        for sig in (signal.SIGTERM, signal.SIGHUP):
            previous[sig] = signal.signal(sig, interrupted)
    try:
        result = container_runner(config, provider=provider, provider_name=provider_name,
            fetch=fetch or BrowserFetch(deadline, allowed, audit=audit, audit_context=audit_context),
            archive=archive, progress=progress, audit=audit, audit_context=audit_context)
        report = str(result['report'])[:28000]
        ref = archive.checkpoint(report=report)
        return {'ok': result['ok'], 'speech': f'Saved research: {ref}\n\n{report}',
                'stash_ref': ref, 'space_id': archive.space.space_id, 'sources': result.get('sources', []),
                'provider': provider_name, 'model': str(provider.model)}
    except BrowserOutcomeUnknown as exc:
        return {'ok': False, 'completion': 'unknown', 'error_type': type(exc).__name__,
                'speech': f'Browser research outcome could not be verified. Partial archive: {archive.ref}',
                'stash_ref': archive.ref}
    except Exception as exc:
        sources = []
        for page in getattr(archive, 'pages', []):
            source = page.get('url') if isinstance(page, dict) else None
            if isinstance(source, str) and source not in sources:
                sources.append(source)
        message = ('Browser research stopped before a final report. '
                   'The saved page evidence is partial and may not answer the full request.')
        return {'ok': False, 'completion': 'failed', 'error_type': type(exc).__name__,
                'speech': f'Saved research: {archive.ref}\n\n{message}',
                'stash_ref': archive.ref, 'space_id': archive.space.space_id,
                'sources': sources, 'provider': provider_name, 'model': str(provider.model)}
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
