"""Web admission and request exclusions for tools requiring background execution.

Ordinary foreground tools remain discoverable independently of task readiness.
"""

import functools
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field

from .models import (
    MAX_ARGUMENT_BYTES,
    Admission,
    AdmissionDenied,
    Conflict,
    TaskError,
    canonical_json,
)

logger = logging.getLogger(__name__)


def is_admission(value):
    return isinstance(value, dict) and (
        value.get("result_kind") == "background_admission"
        or (value.get("status") == "accepted" and bool(value.get("job_id")))
    )


def contains_admission(value, depth=0):
    if depth > 16:
        return False
    if is_admission(value):
        return True
    if isinstance(value, dict):
        return bool(value.get("pending_jobs")) or any(
            contains_admission(item, depth + 1)
            for item in value.values()
            if isinstance(item, (dict, list))
        )
    if isinstance(value, list):
        return any(contains_admission(item, depth + 1) for item in value)
    return False


def reject_background_result(value):
    if contains_admission(value):
        return {
            "ok": False,
            "error": "Background admission requires the authorized Web task path",
            "speech": "This caller cannot accept a background task receipt.",
            "error_code": "background_admission_unsupported",
        }
    return value


def background_only_result(tool):
    return {
        'ok': False,
        'error_code': 'background_execution_required',
        'error': 'This tool requires authorized Web background execution',
        'speech': f'{tool} runs only as a background task in Jarvis Web text chat. '
                  'Enable it in Settings → Tools → Background tasks and start its worker/service. '
                  'No work was started.',
    }


def background_only_exclusions(registry, context=None):
    """One readiness snapshot per Web turn; admission still rechecks live policy."""
    if isinstance(context, WebTaskContext):
        with context.lock:
            if context.discovery_exclusions is not None:
                return set(context.discovery_exclusions)
            excluded = _compute_background_only_exclusions(registry, context)
            context.discovery_exclusions = frozenset(excluded)
            return excluded
    return _compute_background_only_exclusions(registry, context)


def _compute_background_only_exclusions(registry, context):
    """Request-time discovery gate; never edits the registry or Tool RAG index."""
    excluded = set()
    names = registry.list_tools() if hasattr(registry, 'list_tools') else getattr(registry, 'tools', {})
    for name in names:
        schema = registry.get_tool(name)
        if not getattr(schema, 'background_required', False):
            continue
        try:
            if not isinstance(context, WebTaskContext) or name not in context.selected:
                raise AdmissionDenied('Background-only tool has no Web permission')
            if context.discovery_check is not None:
                context.discovery_check(name, schema)
            elif context.service is not None:
                context.service.check_ready(context, name, schema)
            else:
                raise AdmissionDenied('Background-only readiness is unavailable')
        except AdmissionDenied as exc:
            if isinstance(context, WebTaskContext) and name in context.selected:
                logger.warning('Background-only tool hidden for this turn tool=%s reason=%s',
                               name, str(exc)[:300])
            excluded.add(name)
        except Exception as exc:
            # Optional task storage/config failures must not abort ordinary chat.
            if isinstance(context, WebTaskContext) and name in context.selected:
                logger.warning('Background-only tool hidden for this turn tool=%s error_type=%s',
                               name, type(exc).__name__)
            excluded.add(name)
    return excluded


def carry_pending_jobs(method):
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        result = method(self, *args, **kwargs)
        context = getattr(self, "background_context", None)
        if not isinstance(context, WebTaskContext):
            return reject_background_result(result)
        if isinstance(result, dict) and context.receipts:
            result["pending_jobs"] = list(context.receipts.values())
            result.setdefault("data", {})["pending_jobs"] = result["pending_jobs"]
        return result

    return wrapped


@dataclass
class WebTaskContext:
    """Constructed by the authenticated Web service, never deserialized from input."""

    service: object
    authorization_id: str
    selected: tuple[str, ...]
    receipts: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)
    lock: object = field(default_factory=threading.RLock, repr=False)
    authorization: dict | None = field(default=None, repr=False)
    authorize_tool: object = field(default=None, repr=False)
    tool_contexts: dict = field(default_factory=dict, repr=False)
    discovery_check: object = field(default=None, repr=False)
    discovery_exclusions: frozenset[str] | None = field(default=None, repr=False)

    def admit(self, tool, args, invocation_id, schema):
        try:
            with self.lock:
                if self.authorize_tool is None:
                    return self.service.admit(self, tool, args, invocation_id, schema)
                if tool not in self.selected:
                    raise AdmissionDenied("Tool was not selected for background execution")
                if tool not in self.tool_contexts:
                    self.tool_contexts[tool] = self.authorize_tool(tool)
                receipt = self.tool_contexts[tool].admit(tool, args, invocation_id, schema)
                self.receipts[receipt['job_id']] = receipt
                return receipt
        except TaskError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            # A broken optional task store/policy must produce a tool error, not
            # abort the chat turn or silently run selected work in the foreground.
            raise AdmissionDenied("Background task policy or storage is unavailable") from exc


class BackgroundAdmissionService:
    def __init__(self, store, *, adapters=None, validate_source=None, ready=None,
                 callback_sources=None, callback_readiness=None):
        self.store = store
        # Bindings are supplied by trusted code. Tests inject an inert fixture;
        # strings from a manifest can never cause dynamic code imports.
        self.adapters = dict(adapters or {})
        self.validate_source = validate_source
        self.ready = ready or (lambda: False)
        self.callback_sources = dict(callback_sources or {})
        self.callback_readiness = dict(callback_readiness or {})

    def supported(self, registry, blocked=()):
        return [
            name
            for name in registry.list_tools()
            if name not in blocked
            and self.adapters.get(name)
            and getattr(registry.get_tool(name), "background_adapter", None) == self.adapters[name]
        ]

    def authorize(self, payload, registry, *, defer_readiness=False):
        selected = payload.get("selected")
        if (
            not isinstance(selected, list)
            or not 1 <= len(selected) <= 128
            or any(not isinstance(name, str) for name in selected)
            or len(set(selected)) != len(selected)
        ):
            raise AdmissionDenied("Expected distinct supported background tools")
        if payload.get("source") != "web" or payload.get("tool_policy") == "none":
            raise AdmissionDenied("Background tasks require a Web tool-enabled request")
        supported = self.supported(registry, payload.get("blocked", []))
        if any(name not in supported for name in selected):
            raise AdmissionDenied("A selected tool has no supported background adapter")
        if not defer_readiness and (not self.store.settings()["background_enabled"] or not self.ready()):
            raise AdmissionDenied(
                "Background admission is disabled or its coordinator is unavailable"
            )
        if not defer_readiness:
            healthy = {name for worker in self.store.healthy_workers() for name in worker["adapters"]}
            if any(self.adapters[name] not in healthy for name in selected):
                raise AdmissionDenied("No healthy worker supports the selected background tools")
        if not self.validate_source or not self.validate_source(payload):
            raise AdmissionDenied("The originating Web run is not current and authorized")
        authorization = {key: value for key, value in payload.items() if key not in {'query', 'callback_sources'}}
        sources = {name: self.callback_sources[name] for name in selected if name in self.callback_sources}
        if sources:
            authorization['callback_sources'] = sources
        return WebTaskContext(self, uuid.uuid4().hex, tuple(selected), authorization=authorization)

    def admit(self, context, tool, args, invocation_id, schema):
        if not isinstance(context, WebTaskContext):
            raise AdmissionDenied("Missing explicit Web invocation context")
        with context.lock:
            try:
                return self._admit(context, tool, args, invocation_id, schema)
            except Exception as exc:
                self.store.events.emit('admission_rejected', component='web', level='WARNING',
                                       tool=tool, error_type=type(exc).__name__)
                raise

    def check_ready(self, context, tool, schema):
        """Read-only eligibility, shared by discovery and admission revalidation."""
        if (
            not isinstance(context, WebTaskContext)
            or context.service is not self
            or tool not in context.selected
        ):
            raise AdmissionDenied("Missing explicit top-level Web invocation context")
        payload = context.authorization or self.store.authorization(context.authorization_id)
        settings = self.store.settings()
        if not settings['background_enabled'] or tool not in settings['background_tools']:
            raise AdmissionDenied('This tool is not enabled in the saved background preferences')
        if (
            not payload
            or tool not in payload["selected"]
            or not self.validate_source(payload)
            or getattr(schema, "background_adapter", None) != self.adapters.get(tool)
        ):
            raise AdmissionDenied("Background authorization or capability is no longer valid")
        if not self.ready():
            raise AdmissionDenied("Background tasks are unavailable. Check Settings → Tools before retrying.")
        healthy = {name for worker in self.store.healthy_workers() for name in worker["adapters"]}
        if self.adapters[tool] not in healthy:
            if getattr(schema, 'background_required', False):
                raise AdmissionDenied('The background worker is offline or has no adapter for this tool. '
                                      'Start its worker/service before retrying in Jarvis Web; this tool has no foreground mode.')
            raise AdmissionDenied("The background worker is offline. Start it or turn off background execution in Settings → Tools.")
        from lib.webhook_integrations.contracts import ADAPTER as CALLBACK_ADAPTER
        if self.adapters[tool] == CALLBACK_ADAPTER:
            from lib.webhook_integrations.service import IntegrationService
            source_id = self.callback_sources.get(tool)
            if not source_id or payload.get('callback_sources', {}).get(tool) != source_id:
                raise AdmissionDenied('Tool has no current trusted callback source binding')
            IntegrationService(self.store).check_source_ready(source_id)
            readiness = self.callback_readiness.get(tool)
            if readiness is not None and not readiness():
                raise AdmissionDenied('The callback service is stopped. Start it in Settings → Tools before retrying.')
        return payload

    def _admit(self, context, tool, args, invocation_id, schema):
        if not invocation_id:
            raise AdmissionDenied('Missing explicit top-level Web invocation context')
        payload = self.check_ready(context, tool, schema)
        work = canonical_json([tool, args], MAX_ARGUMENT_BYTES)
        prior = context.calls.get(invocation_id)
        if prior is not None and prior != work:
            raise Conflict("Invocation identity already belongs to different work")
        # The orchestrator guards repeated tool/arguments within a user request.
        # Admission identity is strictly the invocation, including on redelivery.
        from .local_contract import SKILL_ADAPTERS

        timeout = 900
        from lib.webhook_integrations.contracts import ADAPTER as CALLBACK_ADAPTER
        if self.adapters[tool] == CALLBACK_ADAPTER:
            from .local_skill import argument_validators
            for validator in argument_validators(schema.parameters, None):
                validator.validate(args)
        if self.adapters[tool] in SKILL_ADAPTERS:
            # ToolRegistry can cache a schema across a manifest edit. Use the
            # current policy snapshot saved by the Web authorization service.
            timeout = payload.get('tool_policies', {}).get(tool, {}).get('timeout_seconds')
            if type(timeout) is not int or not 1 <= timeout <= 86400:
                raise AdmissionDenied('Missing reviewed local skill timeout')
        job = self.store.admit(
            Admission(
                conversation_id=payload["conversation_id"],
                generation=payload["generation"],
                request_id=payload["request_id"],
                invocation_id=invocation_id,
                tool=tool,
                adapter=self.adapters[tool],
                mode=payload["mode"],
                arguments=args,
                authorization_id=context.authorization_id,
                source="web",
                timeout_seconds=timeout,
            ),
            authorization=payload,
        )
        receipt = {
            "ok": True,
            "result_kind": "background_admission",
            "status": "accepted",
            "job_id": job["id"],
            "job_state": job["state"],
            "tool": tool,
            "conversation_id": job["conversation_id"],
            "generation": job["generation"],
            "source_message_id": payload["request_id"],
            "invocation_id": invocation_id,
            "revision": job["revision"],
            "speech": "The task is queued. Results will return to this conversation.",
        }
        context.receipts[job["id"]] = receipt
        context.calls[invocation_id] = work
        return dict(receipt)
