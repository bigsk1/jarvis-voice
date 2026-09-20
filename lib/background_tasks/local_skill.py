"""Shared supervised execution for explicitly reviewed local skill scripts.

No discovery, dynamic imports from manifests, or per-tool execution wrappers.
local_skill_v1 contains effects in the process group. remote_skill_v1 permits
remote work but never equates local termination with provider cancellation.
"""

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from .local_contract import REMOTE_ADAPTER, SKILL_ADAPTERS, execution_settings
from .models import MAX_ARGUMENT_BYTES, MAX_RESULT_BYTES, AdmissionDenied, LostLease, TaskError, canonical_json
from .worker import CancellationRequested, Interrupted, KnownCancelled, KnownFailure, KnownStopped, UncertainOutcome


def bounded_failure(result):
    """Bound a known, stopped failure without reserving an uncertain slot."""
    if not isinstance(result, dict):
        return {'ok': False, 'error': 'Invalid local skill result'}
    try:
        canonical_json(result, MAX_RESULT_BYTES)
        return result
    except TaskError:
        diagnostic = result.get('error') or result.get('speech')
        if not isinstance(diagnostic, str):
            diagnostic = 'The local skill returned failure details that could not be stored.'
        encoded = diagnostic.encode('utf-8', errors='replace')
        if len(encoded) > 8192:
            diagnostic = (encoded[:4096].decode('utf-8', errors='ignore')
                          + '\n[diagnostics truncated]\n'
                          + encoded[-4096:].decode('utf-8', errors='ignore'))
        bounded = {'ok': False, 'speech': 'The background task failed. Diagnostics were truncated.',
                   'error': diagnostic, 'diagnostics_truncated': True}
        if result.get('completion') in ('rejected', 'completed', 'unknown'):
            bounded['completion'] = result['completion']
        return bounded


def argument_validators(parameters, constraints):
    """Use JSON Schema, with no network retrieval and strict top-level arguments."""
    if not isinstance(parameters, dict) or parameters.get('type') != 'object':
        raise AdmissionDenied('Local skill parameters must describe an object')
    schemas = [{**parameters, 'additionalProperties': parameters.get('additionalProperties', False)}]
    if constraints is not None:
        schemas.append(constraints)
    try:
        for schema in schemas:
            Draft202012Validator.check_schema(schema)
        return [Draft202012Validator(schema, registry=Registry()) for schema in schemas]
    except SchemaError as exc:
        raise AdmissionDenied('Invalid local skill argument schema') from exc


def validate_arguments(schema, args):
    """The same bounded, offline validation at admission and at execution."""
    canonical_json(args, MAX_ARGUMENT_BYTES)
    settings = execution_settings(schema.background_execution)
    for validator in argument_validators(schema.parameters, settings.get('argument_constraints')):
        validator.validate(args)


def restrict_child_environment(environment, policy, args, scratch):
    """Apply a trusted per-tool child env policy after worker mode resolution."""
    allowed = set(policy['always'])
    allowed.update(env_key for arg_name, env_key in policy['if_true'].items()
                   if args.get(arg_name) is True)
    narrowed = {key: value for key, value in environment.items() if key in allowed}
    # Prevent requests and other libraries from finding the worker user's
    # .netrc or other home-scoped credentials automatically.
    narrowed['HOME'] = str(scratch)
    return narrowed


class LocalSkillRunner:
    def __init__(self, root, bindings, *, child_environment_policies=None):
        self.root = Path(root).resolve()
        self.bindings = dict(bindings)
        # Trusted production bindings may restrict what a skill subprocess
        # inherits. Manifest JSON cannot widen this environment.
        self.child_environment_policies = dict(child_environment_policies or {})

    def policy(self, name):
        from tool_availability import check_tool_availability
        from tool_profiles import effective_enabled, load_active_profile_overrides
        from tool_schema import ToolSchema

        adapter = self.bindings.get(name)
        if (adapter not in SKILL_ADAPTERS or not re.fullmatch(r'[A-Za-z0-9_]+', name)
                or name in {'workflow', 'tool_search'} or name.startswith('mcp_')):
            raise AdmissionDenied('Tool has no trusted local skill binding')
        try:
            directory = (self.root / 'skills').resolve()
            manifest_path = directory / f'{name}.tool.json'
            raw = manifest_path.read_bytes()
            manifest = json.loads(raw)
            # Bind name -> sibling script. A JSON path cannot select another
            # skill, escape the directory, or invoke executor special routes.
            script_name = manifest.get('script')
            if script_name not in {f'{name}.py', f'{name}.sh'}:
                raise AdmissionDenied('Local skill script does not match its trusted name')
            script = directory / script_name
            if script.resolve().parent != directory or manifest_path.resolve().parent != directory:
                raise AdmissionDenied('Local skill paths must stay within the skills directory')
            permissions = manifest.get('permissions', {})
            if (manifest.get('name') != name
                    or not effective_enabled(name, manifest.get('enabled', True), load_active_profile_overrides())
                    or not check_tool_availability(manifest).available
                    or permissions.get('dangerous') is not False
                    or permissions.get('auto_approve') is not True
                    or permissions.get('network') is not (adapter == REMOTE_ADAPTER)):
                raise AdmissionDenied('Local skill is no longer permitted by current tool/profile policy')
            settings = execution_settings(manifest.get('execution', {}).get('background'))
            if settings['adapter'] != adapter:
                raise AdmissionDenied('Manifest adapter does not match the trusted binding')
            argument_validators(manifest['parameters'], settings.get('argument_constraints'))
            schema = ToolSchema(name, manifest['description'], manifest['parameters'], str(script),
                                permissions=permissions, execution=manifest['execution'],
                                proxy_policy=manifest.get('proxy_policy', 'inherit'))
            evidence = {'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                        'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
                        'adapter': adapter, 'proxy_policy': schema.proxy_policy,
                        'timeout_seconds': settings['timeout_seconds']}
            return schema, evidence
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            if isinstance(exc, AdmissionDenied):
                raise
            raise AdmissionDenied('Local skill manifest or script is unavailable or invalid') from exc

    def authorize_tools(self, selected):
        return {name: self.policy(name)[1] for name in selected if name in self.bindings}

    @staticmethod
    def _matches_policy(adapter, stored, current):
        return adapter in SKILL_ADAPTERS and adapter == current.get('adapter') and stored == current

    def __call__(self, context):
        # Match ToolExecutor's top-level scope; avoid global ENV hydration.
        from config_loader import config_scope
        from executor import ToolExecutor
        from tool_process import OutputLimitExceeded

        job = context.claim.job
        remote = job['adapter'] == REMOTE_ADAPTER
        name = job['admission']['tool']
        args = job['admission']['arguments']
        authorization = context.store.authorization(job['admission']['authorization_id'])
        try:
            with config_scope(job['mode'], overrides=context.config_values):
                schema, evidence = self.policy(name)
                if (not authorization or authorization.get('operator') != 'installation'
                        or authorization.get('source') != 'web'
                        or name not in authorization.get('selected', [])
                        or authorization.get('tool_policy') == 'none'
                        or not self._matches_policy(job['adapter'],
                            authorization.get('tool_policies', {}).get(name), evidence)
                        or any(authorization.get(key) != job['admission'][key]
                               for key in ('conversation_id', 'generation', 'request_id', 'mode'))):
                    raise AdmissionDenied('Stored local skill authorization no longer matches current policy')
                config_path = self.root / 'jarvis-web/config/web_config.json'
                web_config = json.loads(config_path.read_text()) if config_path.exists() else {}
                if name in web_config.get('tools', {}).get('blocked', []):
                    raise AdmissionDenied('Local skill was blocked after admission')
                settings = execution_settings(schema.background_execution)
                if (job['adapter'] in SKILL_ADAPTERS
                        and job['admission']['timeout_seconds'] != settings['timeout_seconds']):
                    raise AdmissionDenied('Admitted deadline does not match the reviewed local skill policy')
                validate_arguments(schema, args)
                context.checkpoint()
                context.local_execution = settings
                registry = SimpleNamespace(get_tool=lambda requested: schema if requested == name else None,
                                           is_mcp_tool=lambda requested: False)
                executor = ToolExecutor(job['mode'], registry, load_runtime_config=False)
                executor.set_session_context(web_conversation_id=job['conversation_id'])
                executor.set_progress_callback(
                    lambda event_type, **progress: context.progress({'event_type': event_type, **progress}))
                workspace = context.store.path.parent / 'task-workspaces'
                workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix=job['id'] + '-', dir=workspace) as scratch:
                    executor.skills_dir = Path(scratch)
                    limit = str(settings['limits']['input_bytes'])
                    environment = context.environment
                    child_policy = self.child_environment_policies.get(name)
                    if child_policy is not None:
                        environment = restrict_child_environment(environment, child_policy, args, scratch)
                    context.environment = dict(environment, TMPDIR=scratch,
                        JARVIS_BACKGROUND_MAX_INPUT_BYTES=limit,
                        JARVIS_OVERRIDE_JARVIS_BACKGROUND_MAX_INPUT_BYTES=limit,
                        OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
                    result = executor._execute_foreground(name, args, supervision=context)
                if (not isinstance(result, dict) or result.get('ok') is not True
                        or result.get('cancelled')):
                    confirmed_failure = (isinstance(result, dict) and result.get('ok') is False
                        and not result.get('cancelled')
                        and result.get('completion') in ('rejected', 'completed'))
                    if remote and context.local_process_started and not confirmed_failure:
                        raise UncertainOutcome(
                            'Remote skill returned no confirmed success. Provider work may still exist; '
                            'check tool/provider records before reconciling or retrying. Not replayed.')
                    raise KnownFailure(bounded_failure(result))
                return result
        except CancellationRequested as exc:
            # The shared process seam verifies the entire group before raising.
            if remote and context.local_process_started:
                raise UncertainOutcome(
                    'Local observer stopped; provider cancellation is unconfirmed. Not replayed.') from exc
            raise KnownCancelled('Local skill stopped') from exc
        except (Interrupted, LostLease) as exc:
            if remote and context.local_process_started:
                raise UncertainOutcome(
                    'Local observer stopped; provider cancellation is unconfirmed. Not replayed.') from exc
            if not remote and (not context.local_process_started or context.local_process_stopped):
                raise KnownStopped('Local process group stopped or never launched') from exc
            raise
        except (ValidationError, Unresolvable) as exc:
            raise KnownFailure({'ok': False, 'error': 'Arguments do not match the local skill schema'}) from exc
        except (AdmissionDenied, subprocess.TimeoutExpired, OutputLimitExceeded) as exc:
            if remote and context.local_process_started:
                raise UncertainOutcome(
                    'Remote observation ended without a confirmed result. Provider work may continue; '
                    'check provider records before reconciling or retrying. Not replayed.') from exc
            raise KnownFailure(bounded_failure({'ok': False,
                'speech': 'The background task could not complete.',
                'error': str(exc) if isinstance(exc, AdmissionDenied) else type(exc).__name__})) from exc
