#!/usr/bin/env python3
"""Opt-in Docling Serve client: bounded uploads, async observation and Stash outputs."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from filelock import FileLock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from config_loader import get_config_value, load_config  # noqa: E402
from paths import resolve_local_file_tool_path  # noqa: E402
from remote_completion import RemoteCompletionError, submission_error  # noqa: E402
from stash_helper import StashFile, get_stash_dir, open_space, safe_resolve_file  # noqa: E402
from tool_progress import emit_tool_progress  # noqa: E402

MAX_UPLOAD = 50 * 1024**2
MAX_RESPONSE = 32 * 1024**2
FORMATS = {'md': ('markdown', '.md', 'text/markdown'),
           'json': ('json', '.json', 'application/json'),
           'text': ('text', '.txt', 'text/plain')}
EXTENSIONS = {'.pdf', '.docx', '.pptx', '.xlsx', '.html', '.htm', '.md', '.adoc', '.csv',
              '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
TERMINAL = {'success', 'partial_success', 'failure', 'skipped'}


class DoclingError(RuntimeError):
    """Safe client-authored diagnostics, without remote response bodies."""


def task_id(value):
    if not isinstance(value, str):
        raise ValueError('Supply the exact Docling task_id from a prior response')
    if re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('This looks like a Jarvis background job_id, not a Docling task_id. Wait for automatic background delivery or check the Background Tasks UI; do not poll or resubmit it through Docling.')
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise ValueError('Invalid Docling task_id') from exc
    if parsed != value:
        raise ValueError('Use the complete canonical Docling task_id')
    return value


def source(args):
    if bool(args.get('stash_ref')) == bool(args.get('file_path')):
        raise ValueError('Convert requires exactly one source: stash_ref or file_path')
    if args.get('stash_ref'):
        resolved = safe_resolve_file(stash_ref=args['stash_ref'])
        if not resolved.get('found'):
            raise ValueError('Input Stash file was not found')
        path = Path(resolved['path'])
    else:
        path = resolve_local_file_tool_path(args['file_path'])
    limit = min(MAX_UPLOAD, int(get_config_value('JARVIS_BACKGROUND_MAX_INPUT_BYTES', '') or MAX_UPLOAD))
    if not path.is_file() or path.suffix.lower() not in EXTENSIONS or not 0 < path.stat().st_size <= limit:
        raise ValueError('Unsupported, empty or oversized document; maximum upload is 50 MiB')
    return path


class Client:
    def __init__(self):
        self.base = str(get_config_value('DOCLING_BASE_URL', '')).strip().rstrip('/')
        self.key = str(get_config_value('DOCLING_API_KEY', '')).strip()
        header = str(get_config_value('DOCLING_API_KEY_HEADER', '') or 'X-Api-Key').strip()
        parsed = urlparse(self.base)
        if not self.base or not self.key:
            raise ValueError('Docling is not configured; set DOCLING_BASE_URL and DOCLING_API_KEY in the active mode')
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.path not in ('', '/')
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('DOCLING_BASE_URL must be an HTTP(S) service root without credentials or query parameters')
        if (not re.fullmatch(r'[A-Za-z0-9-]+', header) or header.lower() in
                {'host', 'content-type', 'content-length', 'connection', 'cookie', 'proxy-authorization'}
                or any(ord(char) < 32 or ord(char) > 126 for char in self.key)):
            raise ValueError('Invalid Docling authentication header configuration')
        try:
            self.timeout = max(30, min(900, int(get_config_value('DOCLING_TIMEOUT_SECONDS', '300') or 300)))
        except ValueError as exc:
            raise ValueError('DOCLING_TIMEOUT_SECONDS must be an integer') from exc
        self.deadline = time.monotonic() + self.timeout
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.verify = os.environ.get('REQUESTS_CA_BUNDLE') or os.environ.get('SSL_CERT_FILE') or True
        self.session.headers[header] = self.key
        self.accepted = False
        self.completed = False
        self.task = None
        self.receipt = None
        self.recovery_available = False
        self.exporting = False

    def recovery_path(self, identifier):
        # Separate services cannot collect one another's cached documents.
        host = hashlib.sha256(self.base.encode()).hexdigest()
        return get_stash_dir() / '.docling-recovery' / host / (task_id(identifier) + '.json')

    def cached_result(self, identifier):
        path = self.recovery_path(identifier)
        if not path.is_file():
            return None
        try:
            if path.stat().st_size > MAX_RESPONSE:
                raise ValueError('Saved Docling response exceeds its 32 MiB limit')
            payload = json.loads(path.read_bytes())
            prepare_result(payload)
        except ValueError:
            # Old versions promoted responses before checking exportability.
            # Discard invalid copies so explicit collect can check the provider.
            path.unlink(missing_ok=True)
            self.recovery_available = False
            return None
        self.recovery_available = True
        return payload

    def json(self, method, path, *, submission=False, durable_path=None, **kwargs):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Docling observation budget ended')
        with self.session.request(method, self.base + path, timeout=(min(5, remaining), min(30, remaining)),
                                  allow_redirects=False, stream=True, **kwargs) as response:
            if response.status_code >= 300:
                message = f'Docling request failed (HTTP {response.status_code}); check authentication, service readiness and input options'
                if submission:
                    raise submission_error(response.status_code, message)
                raise DoclingError(message)
            content = bytearray()
            # Open the spool BEFORE a consuming GET, in save_result below.
            for block in response.iter_content(65536):
                content.extend(block)
                if len(content) > MAX_RESPONSE:
                    raise ValueError('Docling JSON response exceeds its 32 MiB limit')
                if durable_path is not None:
                    durable_path.write(block)
                if time.monotonic() >= self.deadline:
                    raise TimeoutError('Docling observation budget ended')
            if durable_path is not None:
                durable_path.flush()
                os.fsync(durable_path.fileno())
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError('Docling returned an invalid JSON object')
            return data

    def job(self, identifier, wait=0):
        data = self.json('GET', '/v1/status/poll/' + task_id(identifier), params={'wait': wait})
        if data.get('task_id') != identifier or data.get('task_type') != 'convert':
            raise ValueError('Docling status does not match this conversion task')
        if data.get('task_status') not in TERMINAL | {'pending', 'started'}:
            raise ValueError('Unknown Docling task status; inspect the task before retrying')
        self.task = data
        self.completed = data['task_status'] in TERMINAL
        return data

    def wait(self, identifier):
        while self.deadline - time.monotonic() > 1:
            job = self.job(identifier, min(5, max(0, self.deadline - time.monotonic() - 1)))
            if job['task_status'] in TERMINAL:
                return job
            time.sleep(min(.5, max(0, self.deadline - time.monotonic() - 1)))
        return self.task


def save_result(client, args):
    identifier = client.task['task_id']
    cache = client.recovery_path(identifier)
    cache.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with FileLock(str(cache) + '.lock', timeout=min(5, max(0, client.deadline - time.monotonic()))):
        result = _save_result(client, args, cache)
        try:
            cache.unlink(missing_ok=True)
        except OSError:
            # Export success remains success if cleanup is temporarily denied.
            pass
        client.recovery_available = False
        return result


def prepare_result(payload):
    """Validate and encode everything needed for export before retaining a copy."""
    if (not isinstance(payload, dict) or payload.get('status') not in ('success', 'partial_success')
            or not isinstance(payload.get('document'), dict)):
        raise ValueError('Docling did not return a successful inline conversion result')
    document = payload['document']
    structured = document.get('json_content')
    if structured is not None and not isinstance(structured, dict):
        raise ValueError('Docling returned invalid structured document JSON')
    if structured and (not isinstance(structured.get('pages', {}), dict)
                       or any(not isinstance(structured.get(key, []), list) for key in ('texts', 'tables'))):
        raise ValueError('Docling returned invalid page, text or table collections')
    if not isinstance(payload.get('errors', []), list):
        raise ValueError('Docling returned invalid conversion errors')
    exports = []
    for format_name, (prefix, suffix, mime) in FORMATS.items():
        value = document.get({'md': 'md_content', 'json': 'json_content', 'text': 'text_content'}[format_name])
        if value is None:
            continue
        if format_name == 'json':
            content = json.dumps(value, ensure_ascii=False, indent=2)
        elif isinstance(value, str):
            content = value
        else:
            raise ValueError('Docling returned an invalid text export')
        if content.strip():
            try:
                encoded = content.encode('utf-8')
            except UnicodeError as exc:
                raise ValueError('Docling returned text that cannot be exported as UTF-8') from exc
            exports.append((prefix, suffix, mime, content, encoded))
    if not exports or not (any(item[0] != 'json' for item in exports)
                           or structured and (structured.get('texts') or structured.get('tables'))):
        raise ValueError('Docling returned no extractable document content; enable OCR for scans')
    return document, structured, exports


def _save_result(client, args, cache):
    identifier = client.task['task_id']
    if client.task['task_status'] in ('failure', 'skipped'):
        raise RemoteCompletionError('Docling conversion failed or was skipped; inspect task_id and source document', 'completed')
    # Preflight Stash and writable durable storage before consuming a single-use
    # provider result. Retain only an exportable response until ALL files save.
    space, _ = open_space(scope='project', labels=['docling', 'document_conversion'])
    output = StashFile(space)
    payload = client.cached_result(identifier)
    if payload is None:
        with tempfile.NamedTemporaryFile(dir=cache.parent, prefix=identifier + '.', delete=False) as spool:
            temporary = Path(spool.name)
            try:
                payload = client.json('GET', '/v1/result/' + task_id(identifier), durable_path=spool)
                document, structured, exports = prepare_result(payload)
                spool.close()
                os.replace(temporary, cache)
                # fsync the directory as well as the completed response.
                if hasattr(os, 'O_DIRECTORY'):
                    descriptor = os.open(cache.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                client.recovery_available = True
            finally:
                spool.close()
                temporary.unlink(missing_ok=True)
    else:
        document, structured, exports = prepare_result(payload)
    name = args.get('output_name') or 'converted-document'
    data = {'task_id': identifier, 'state': payload['status'], 'partial': payload['status'] == 'partial_success',
            'filename': name, 'outputs': [], 'receipt_stash_ref': client.receipt,
            'processing_time': payload.get('processing_time'), 'error_count': len(payload.get('errors', []))}
    client.exporting = True
    for prefix, suffix, mime, text, encoded in exports:
        saved = output.save_binary(encoded, name + suffix, mime_type=mime,
                                   tags=['docling', prefix], tool_origin='docling_convert')
        data[prefix + '_stash_ref'] = saved['ref']
        data[prefix + '_file_id'] = saved['file_id']
        data[prefix + '_char_count'] = len(text)
        data['outputs'].append({'name': name + suffix, 'mime_type': mime, 'stash_ref': saved['ref'], 'file_path': saved['path']})
    preview = document.get('md_content') or document.get('text_content') or ''
    data.update(markdown_excerpt=preview[:4000], content_char_count=len(preview), content_truncated=len(preview) > 4000,
                space_id=space.space_id, filename=data['outputs'][0]['name'], stash_ref=data['outputs'][0]['stash_ref'], file_path=data['outputs'][0]['file_path'],
                file_id=data['outputs'][0]['stash_ref'].rsplit('/', 1)[-1], mime_type=data['outputs'][0]['mime_type'])
    if structured:
        data.update(page_count=len(structured.get('pages', {})), table_count=len(structured.get('tables', [])))
    data['followup_note'] = ('Full exports are saved in Stash. Read markdown_stash_ref/text_stash_ref for complete text; '
                            'json_stash_ref contains Docling layout, tables and provenance, not schema-extracted business fields. '
                            'Partial conversions require review. Keep the original source for page rendering or further conversion.')
    return {'ok': True, 'speech': 'Docling ' + ('partially converted' if data['partial'] else 'converted') +
            ' the document. Full outputs are saved in Stash.', 'data': data}


def execute(args):
    client = None
    submitted = False
    try:
        # Validate before submitting a remote operation, including collected output names.
        if not isinstance(args, dict) or args.keys() - {'action', 'stash_ref', 'file_path', 'task_id',
                'formats', 'do_ocr', 'force_ocr', 'page_start', 'page_end', 'output_name'}:
            raise ValueError('Docling arguments must be an object with only supported fields')
        if any(key in args and type(args[key]) is not bool for key in ('do_ocr', 'force_ocr')):
            raise ValueError('do_ocr and force_ocr must be booleans')
        action = args.get('action', 'convert')
        if action not in ('status', 'convert', 'job', 'collect'):
            raise ValueError('Unknown Docling action')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.get('output_name') or 'converted-document'):
            raise ValueError('output_name must be a safe basename without an extension')
        client = Client()
        if action == 'status':
            ready = client.json('GET', '/ready')
            if ready.get('status') != 'ok':
                raise ValueError('Docling is not ready')
            return {'ok': True, 'speech': 'Docling service is ready.', 'data': {'ready': True}}
        if action in ('job', 'collect'):
            identifier = task_id(args.get('task_id'))
            client.accepted = action == 'collect'
            client.task = {'task_id': identifier}
            if action == 'collect':
                emit_tool_progress({'phase': 'Observing existing Docling task', 'recovery': {'task_id': identifier}})
            payload = None
            cache = client.recovery_path(identifier)
            if action == 'collect' and cache.is_file():
                with FileLock(str(cache) + '.lock', timeout=min(5, max(0, client.deadline - time.monotonic()))):
                    payload = client.cached_result(identifier)
            if payload is not None:
                client.task = {'task_id': identifier, 'task_status': payload['status'], 'task_type': 'convert'}
                client.completed = True
                client.exporting = True
            else:
                client.job(identifier)
            if action == 'job':
                return {'ok': True, 'speech': 'Docling task is ' + client.task['task_status'] + '.',
                        'data': {'task_id': identifier, 'state': client.task['task_status']}}
        else:
            path = source(args)
            if args.get('task_id'):
                raise ValueError('Use collect for an existing task; do not upload the same document again')
            formats = args.get('formats', ['md', 'json', 'text'])
            if (not isinstance(formats, list) or not formats or not all(isinstance(item, str) for item in formats)
                    or len(set(formats)) != len(formats) or not set(formats) <= FORMATS.keys()):
                raise ValueError('formats must select md, json and/or text without duplicates')
            options = {'to_formats': formats, 'do_ocr': str(args.get('do_ocr', True)).lower(),
                       'force_ocr': str(args.get('force_ocr', False)).lower(),
                       'do_table_structure': 'true', 'include_images': 'false', 'include_page_images': 'false',
                       'image_export_mode': 'placeholder', 'target_type': 'inbody'}
            if args.get('force_ocr') and not args.get('do_ocr', True):
                raise ValueError('force_ocr requires do_ocr')
            if args.get('page_start') is not None or args.get('page_end') is not None:
                start, end = args.get('page_start', 1), args.get('page_end')
                if type(start) is not int or type(end) is not int or not 1 <= start <= end:
                    raise ValueError('Supply a positive page_end >= page_start (default 1)')
                options['page_range'] = [str(start), str(end)]
            with path.open('rb') as stream:
                submitted = True
                client.task = client.json('POST', '/v1/convert/file/async', submission=True,
                                         files={'files': (path.name, stream, mimetypes.guess_type(path.name)[0] or 'application/octet-stream')}, data=options)
            identifier = task_id(client.task.get('task_id'))
            client.accepted = True
            emit_tool_progress({'phase': 'Docling conversion accepted', 'recovery': {'task_id': identifier}})
            space, _ = open_space(scope='project', labels=['docling_task'])
            saved = StashFile(space).save_binary(json.dumps({'task_id': identifier,
                    'source_stash_ref': args.get('stash_ref'), 'source_filename': path.name,
                    'followup': 'Use docling_convert job/collect with this task_id; never resubmit an uncertain conversion.'}).encode(),
                    'docling-task.json', mime_type='application/json', tool_origin='docling_convert')
            client.receipt = saved['ref']
            emit_tool_progress({'phase': 'Docling task receipt saved',
                                'recovery': {'task_id': identifier, 'receipt_stash_ref': client.receipt}})
        if not client.completed:
            client.wait(identifier)
        if client.completed:
            result = save_result(client, args)
            if args.get('stash_ref'):
                result['data']['source_stash_ref'] = args['stash_ref']
            return result
        if get_config_value('JARVIS_BACKGROUND_MAX_INPUT_BYTES', ''):
            raise TimeoutError('Docling observation budget ended; remote work may continue. Use job/collect with task_id')
        return {'ok': True, 'speech': 'Docling task is still running; use job/collect with task_id instead of uploading again.',
                'data': {'task_id': identifier, 'state': client.task['task_status'], 'receipt_stash_ref': client.receipt}}
    except Exception as exc:
        completion = 'completed' if client and client.completed else ('unknown' if submitted or client and client.accepted else 'rejected')
        if isinstance(exc, RemoteCompletionError):
            completion = exc.completion
        message = str(exc) if isinstance(exc, (ValueError, TimeoutError, RemoteCompletionError, DoclingError)) else 'Docling request/observation failed; inspect task_id before retrying if a conversion was submitted'
        if client:
            message = message.replace(client.key, '[redacted]')
        recoverable = bool(client and client.recovery_available)
        if recoverable and client.exporting:
            message = 'The completed response is preserved on Jarvis, but export to Stash failed. Use collect with task_id after fixing storage; do not upload again.'
        return {'ok': False, 'completion': completion, 'speech': 'Docling conversion completed; saving outputs needs recovery.' if recoverable and client.exporting else 'Docling could not complete the operation.', 'error': message,
                'data': {'task_id': client.task.get('task_id') if client and client.task else None,
                         'recovery_available': recoverable,
                         'source_stash_ref': args.get('stash_ref') if isinstance(args, dict) else None,
                         'receipt_stash_ref': client.receipt if client else None}}
    finally:
        if client:
            client.session.close()


def main():
    load_config()
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
    result = execute(args)
    print(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
