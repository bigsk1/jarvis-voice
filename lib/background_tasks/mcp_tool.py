"""One reviewed MCP call per durable job, through a private client and deadline.

An ordinary MCP response owns completion; no incoming callback, worker replay,
or remote cancellation contract is implied by stopping this observer.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from pathlib import Path

from jsonschema import ValidationError
from referencing.exceptions import Unresolvable

from ..mcp_background_contract import ADAPTER, REGISTRATIONS, execution_for_tool
from .local_skill import argument_validators
from .models import (
    MAX_ARGUMENT_BYTES,
    MAX_RESULT_BYTES,
    AdmissionDenied,
    LostLease,
    TaskError,
    canonical_json,
)
from .worker import CancellationRequested, Interrupted, KnownFailure, UncertainOutcome

ROOT = Path(__file__).resolve().parents[2]


def validate_arguments(schema, arguments):
    """Validate the model-facing schema, never permit an alternate owner field."""
    try:
        canonical_json(arguments, MAX_ARGUMENT_BYTES)
        for validator in argument_validators(schema.parameters, None):
            validator.validate(arguments)
    except (ValidationError, Unresolvable, TaskError):
        raise AdmissionDenied('MCP arguments do not match the reviewed schema; no task was queued') from None


def _hash(value):
    return hashlib.sha256(canonical_json(value, 4 * MAX_RESULT_BYTES).encode()).hexdigest()


def _implementation_hash():
    root = Path(__file__).resolve().parents[2]
    paths = [Path(__file__), root / 'lib/mcp_background_contract.py',
             root / 'lib/mcp_client.py', root / 'lib/http_client.py', root / 'lib/http_observation.py',
             root / 'lib/tool_schema.py']
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def bounded_result(result):
    """Keep a terminal operation terminal even when its response is oversized."""
    try:
        canonical_json(result, MAX_RESULT_BYTES)
        return result
    except TaskError:
        remaining = [64 * 1024]

        def compact(value, depth=0):
            # Containers and depth-limit notices consume space too. Otherwise a
            # wide tree can expand into unbounded notices without spending the
            # text allowance, losing a confirmed terminal outcome on save.
            remaining[0] -= 32
            if remaining[0] <= 0 or depth > 8:
                return '[result truncated]'
            if isinstance(value, str):
                kept = value[:min(8192, remaining[0])]
                remaining[0] -= len(kept)
                return kept + (' [truncated]' if kept != value else '')
            if isinstance(value, float) and not math.isfinite(value):
                return '[invalid non-finite number]'
            if isinstance(value, int) and value.bit_length() > 4096:
                return '[integer truncated]'
            if value is None or isinstance(value, (bool, int, float)):
                remaining[0] -= 16
                return value
            if isinstance(value, list):
                return [compact(item, depth + 1) for item in value[:100] if remaining[0] > 0]
            if isinstance(value, dict):
                entries = {}
                artifact_keys = {'ok', 'completion', 'speech', 'error', 'stash_ref', 'saved',
                                 'files', 'images', 'artifacts', 'references', 'links'}
                items = sorted(value.items(), key=lambda item: item[0] not in artifact_keys)
                for key, item in items[:100]:
                    if remaining[0] <= 0:
                        break
                    key = str(key)[:128]
                    remaining[0] -= len(key) + 8
                    entries[key] = compact(item, depth + 1)
                return entries
            return '[unsupported result value]'

        bounded = compact(result)
        bounded['result_truncated'] = True
        # Certainty is control metadata. Preserve it even if returned data used
        # the full text allowance before these fields appeared in the response.
        bounded.update({key: result[key] for key in ('ok', 'completion') if key in result})
        canonical_json(bounded, MAX_RESULT_BYTES)
        return bounded


class MCPToolRunner:
    def __init__(self, root=ROOT, *, client_factory=None):
        self.root = Path(root).resolve()
        self.client_factory = client_factory

    def connection(self, name):
        """Resolve only the named server's declared settings in the active mode."""
        from config_loader import get_config_value
        from mcp_client import server_configuration_status
        from tool_profiles import effective_enabled, load_active_profile_overrides

        registration = REGISTRATIONS.get(name)
        if registration is None:
            raise AdmissionDenied('MCP tool has no reviewed background registration')
        try:
            data = json.loads((self.root / 'config/mcp-servers.json').read_text())
            config = data.get('mcpServers', {}).get(registration.server)
            if not isinstance(config, dict):
                raise AdmissionDenied('The registered MCP server is not configured')
            available, _reason = server_configuration_status(config)
            if not available or not effective_enabled(name, True, load_active_profile_overrides()):
                raise AdmissionDenied('The MCP server or tool is disabled or missing configuration')
            allowed = config.get('allowed_tools')
            if allowed is not None and (
                not isinstance(allowed, list)
                or any(not isinstance(item, str) or not item.strip() for item in allowed)
                or registration.tool not in allowed
            ):
                raise AdmissionDenied('The MCP server allowlist does not permit this tool')
            transport = str(config.get('type', '')).lower()
            if transport not in registration.transports:
                raise AdmissionDenied('This MCP transport has no reviewed background binding')

            def substitute(values):
                if not isinstance(values, dict) or not all(isinstance(key, str) for key in values):
                    raise AdmissionDenied('Invalid declared MCP connection settings')
                return {key: re.sub(r'\$\{([^}]+)\}',
                    lambda match: str(get_config_value(match[1], '') or ''), str(value))
                    for key, value in values.items()}

            url = config.get('url')
            if config.get('url_env'):
                url = get_config_value(config['url_env'], None) or url
            if not isinstance(url, str) or not url.strip():
                raise AdmissionDenied('The registered MCP endpoint is missing')
            defaults = substitute(config.get('tool_defaults', {}))
            headers = substitute(config.get('headers', {}))
            if registration.server == 'google_workspace' and (
                not defaults.get('user_google_email')
                or defaults['user_google_email'] != str(get_config_value('GOOGLE_ACCOUNT', '') or '')
                or not headers.get('Authorization', '').startswith('Bearer ')
                or not headers['Authorization'].removeprefix('Bearer ').strip()
            ):
                raise AdmissionDenied('The dedicated Google account or service credential is unavailable')
            spec = {'name': registration.server, 'type': transport, 'url': url,
                'headers': headers, 'tool_defaults': defaults,
                'proxy_policy': config.get('proxy_policy', 'inherit'),
                'result_contract': config.get('result_contract'),
                'tool_call_timeout_seconds': config.get('tool_call_timeout_seconds'),
                'tool_call_timeout_overrides': config.get('tool_call_timeout_overrides')}
            return config, spec
        except (OSError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, AdmissionDenied):
                raise
            raise AdmissionDenied('The registered MCP connection policy is unavailable or invalid') from None

    def policy(self, name, *, registry=None, schema=None):
        from config_loader import get_active_config_mode
        from tool_profiles import get_active_profile_name
        from tool_schema import peek_tool_registry

        config, spec = self.connection(name)
        if schema is None:
            registry = registry if registry is not None else peek_tool_registry(get_active_config_mode())
            schema = registry.get_tool(name) if registry is not None else None
        registration = REGISTRATIONS[name]
        execution = execution_for_tool(name, registration.server, registration.tool)['background']
        if (schema is None or schema.name != name
                or schema.script_path != f'__mcp__{registration.server}__{registration.tool}'
                or schema.background_adapter != ADAPTER
                or schema.background_execution != execution):
            raise AdmissionDenied('The reviewed MCP tool is unavailable in the effective registry')
        argument_validators(schema.parameters, None)
        evidence = {
            'adapter': ADAPTER, 'timeout_seconds': registration.timeout_seconds,
            'server_sha256': _hash({'configuration': config, 'connection': spec}),
            'schema_sha256': _hash({'parameters': schema.parameters,
                'permissions': schema.permissions, 'proxy_policy': schema.proxy_policy}),
            'implementation_sha256': _implementation_hash(),
            'profile': get_active_profile_name(),
        }
        return schema, evidence

    def authorize_tools(self, selected, *, registry=None):
        return {name: self.policy(name, registry=registry)[1]
                for name in selected if name in REGISTRATIONS}

    def _authorize(self, context, schema, evidence):
        job = context.claim.job
        name = job['admission']['tool']
        saved = context.store.authorization(job['admission']['authorization_id'])
        if (not saved or saved.get('operator') != 'installation' or saved.get('source') != 'web'
                or name not in saved.get('selected', []) or saved.get('tool_policy') == 'none'
                or job['adapter'] != ADAPTER
                or saved.get('tool_policies', {}).get(name) != evidence
                or job['admission']['timeout_seconds'] != evidence['timeout_seconds']
                or any(saved.get(key) != job['admission'][key]
                       for key in ('conversation_id', 'generation', 'request_id', 'mode'))):
            raise AdmissionDenied('Saved MCP authorization no longer matches the reviewed policy')
        path = self.root / 'jarvis-web/config/web_config.json'
        config = json.loads(path.read_text()) if path.exists() else {}
        if name in config.get('tools', {}).get('blocked', []):
            raise AdmissionDenied('The MCP tool was blocked after admission')
        validate_arguments(schema, job['admission']['arguments'])

    def __call__(self, context):
        from config_loader import config_scope

        with config_scope(context.claim.job['mode'], overrides=context.config_values):
            return self._execute(context)

    def _execute(self, context):
        from mcp_client import MCPDiscoveryError, MCPRemoteClient, probe_remote_tools
        from tool_schema import ToolRegistry

        job = context.claim.job
        name, arguments = job['admission']['tool'], job['admission']['arguments']
        client = None
        stopped, cancelled = threading.Event(), threading.Event()

        def watch_fences():
            while not stopped.wait(0.2):
                try:
                    context.checkpoint()
                except Exception:
                    # An unavailable fence is not continuing execution authority.
                    cancelled.set()
                    return

        watcher = threading.Thread(target=watch_fences, name=f'mcp-fence-{job["id"]}', daemon=True)
        started = False
        try:
            # Validate immutable authorization before even connecting. Schema is
            # then re-fetched from this one isolated server, never the Web client.
            config, spec = self.connection(name)
            saved = context.store.authorization(job['admission']['authorization_id'])
            saved_policy = (saved or {}).get('tool_policies', {}).get(name, {})
            if saved_policy.get('server_sha256') != _hash({'configuration': config, 'connection': spec}):
                raise AdmissionDenied('The MCP endpoint, account or credential changed after admission')
            context.checkpoint()
            factory = self.client_factory or MCPRemoteClient
            client = factory(spec['name'], spec['url'], spec['type'], spec['headers'],
                proxy_policy=spec['proxy_policy'], result_contract=spec['result_contract'],
                tool_call_timeout_seconds=spec['tool_call_timeout_seconds'],
                tool_call_timeout_overrides=spec['tool_call_timeout_overrides'])
            client.tool_defaults = dict(spec['tool_defaults'])
            registration = REGISTRATIONS[name]
            watcher.start()
            remaining = job['deadline'] - context.store.clock()
            try:
                try:
                    infos = probe_remote_tools(client, timeout_seconds=min(3, remaining),
                        deadline=time.monotonic() + remaining, cancel_event=cancelled, raise_on_error=True)
                finally:
                    # Discovery can finish before the polling watcher sees a
                    # stop. Recheck even failed probes, preserving lease and
                    # operator fences ahead of any catalog interpretation.
                    context.checkpoint()
            except (MCPDiscoveryError, Interrupted):
                reason = ('MCP tool discovery could not be completed. '
                          'No remote tool execution was started; no automatic retry was started.')
                raise UncertainOutcome(reason, result={
                    'ok': False, 'completion': 'unknown', 'submission_started': False,
                    'error_code': 'mcp_discovery_incomplete',
                    'error': 'MCP tool discovery could not be completed', 'speech': reason,
                }) from None
            info = next((item for item in infos if item.get('name') == registration.tool), None)
            if info is None:
                raise AdmissionDenied('The registered MCP tool is no longer offered by its server')
            schema = ToolRegistry.schema_from_mcp_tool(registration.server, client, config, info)
            _, evidence = self.policy(name, schema=schema)
            self._authorize(context, schema, evidence)
            context.checkpoint()
            remaining = job['deadline'] - context.store.clock()
            context.progress({'phase': 'Waiting for the remote MCP response'})
            started = True
            call_started_at = time.monotonic()
            result = client.call_tool(registration.tool, arguments,
                timeout_seconds=remaining, deadline=time.monotonic() + remaining,
                cancel_event=cancelled,
                execution_metadata={'job_id': job['id'], 'deadline_unix': job['deadline']})
            if not isinstance(result, dict):
                raise UncertainOutcome('The MCP server returned no usable completion evidence.')
            context.unreviewed_tool_result = result
            # The worker screens the full returned content before any audit
            # writer persists it; log failure cannot change a completed result.
            try:
                from tool_logger import get_logger
                context.stage_tool_log(get_logger(job['mode']).log_tool_call, {
                    'tool_name': name, 'arguments': arguments, 'result': result,
                    'duration_ms': round((time.monotonic() - call_started_at) * 1000),
                    'mode': job['mode'], 'proxy': client.get_proxy_log_metadata(),
                })
            except Exception:
                pass
            result = bounded_result(result)
            if result.get('completion') in {'completed', 'rejected'}:
                if result.get('ok') is True and result['completion'] == 'completed':
                    return result
                raise KnownFailure({**result, 'ok': False})
            raise UncertainOutcome('The MCP response did not confirm remote completion. '
                'The automation may still be running; inspect its existing effects before retrying.',
                result={**result, 'ok': False, 'completion': 'unknown'})
        except (KnownFailure, UncertainOutcome, LostLease, CancellationRequested):
            raise
        except Exception as exc:
            if started:
                raise UncertainOutcome('Observation of the MCP automation ended without proof of completion. '
                    'No automatic retry was started.') from None
            if isinstance(exc, Interrupted):
                reason = ('MCP preparation was interrupted before tool submission. '
                          'No remote tool execution was started; no automatic retry was started.')
                raise UncertainOutcome(reason, result={
                    'ok': False, 'completion': 'unknown', 'submission_started': False,
                    'error_code': 'mcp_preparation_incomplete',
                    'error': 'MCP preparation was interrupted before tool submission', 'speech': reason,
                }) from None
            # Setup, discovery and validation are read-only. Their failure cannot
            # have invoked the paid/side-effecting tools/call operation.
            reason = str(exc) if isinstance(exc, AdmissionDenied) else 'MCP preparation failed before tool submission'
            raise KnownFailure({'ok': False, 'completion': 'rejected', 'error': reason,
                'speech': reason + '. No remote tool execution was started.'}) from None
        finally:
            stopped.set()
            if watcher.ident is not None:
                watcher.join(timeout=1)
            if client is not None:
                try:
                    client.stop()
                except Exception:
                    pass  # Client cleanup cannot change confirmed remote completion.
