"""Offline local manifests and explicit, isolated live MCP catalog refresh."""
from __future__ import annotations

from pathlib import Path

from config_loader import config_scope
from tool_availability import check_tool_availability
from tool_manifest_files import iter_tool_manifests
from tool_profiles import effective_enabled, load_active_profile_overrides
from tool_schema import ToolSchema
from workflow_policy import (
    BUILDER_EXCLUDED_TOOLS,
    WorkflowPolicyError,
    get_workflow_excluded_tools,
    requires_workflow_confirmation,
    validated_workflow_approval_tools,
)

from .store import BuilderError, BuilderStore


def configured_modes(root: Path) -> list[str]:
    """Advertise only modes with an existing operator configuration file."""
    return [mode for mode in ('cloud', 'local') if (root / 'config' / f'{mode}.env').is_file()]


class CatalogService:
    def __init__(self, root: Path, store: BuilderStore):
        self.root = root
        self.store = store

    def tools(self, mode: str) -> dict:
        if mode not in configured_modes(self.root):
            raise BuilderError('Mode is not configured')
        cached = self.store.catalog(mode)
        tools = {tool['name']: {**tool, 'available': None,
                               'reason': 'Cached MCP schema; availability is rechecked at run time',
                               'permissions_source': 'cached_mcp', 'permissions_verified': False}
                 for tool in (cached or {}).get('tools', []) if tool.get('source') == 'mcp'}
        with config_scope(mode):
            policy_error = ''
            try:
                excluded = get_workflow_excluded_tools(mode) | set(BUILDER_EXCLUDED_TOOLS)
            except WorkflowPolicyError:
                excluded = set(BUILDER_EXCLUDED_TOOLS)
                policy_error = 'Saved tool policy is unavailable; execution is blocked until it is repaired'
            overrides = load_active_profile_overrides()
            # Use the same first-owner rules as ToolRegistry. A personal or
            # generated duplicate cannot silently change approval metadata.
            manifests = list(iter_tool_manifests(self.root / 'skills'))
            names = {document['name'] for _, document in manifests} | set(tools)
            for manifest_path, document in manifests:
                name = document['name']
                availability = check_tool_availability(document, available_tools=names)
                reason = ''
                available = availability.available
                enabled = effective_enabled(name, document.get('enabled', True), overrides)
                if not enabled:
                    available, reason = False, 'Disabled by tool manifest or active tool profile'
                elif name in excluded:
                    available, reason = False, 'Excluded from managed workflows'
                elif not availability.available:
                    reason = availability.setup_hint or ', '.join(availability.missing) or 'Configuration unavailable'
                schema = None
                try:
                    # Constructing a schema reads only this local manifest; it
                    # does not create a registry or connect to MCP/providers.
                    schema = ToolSchema.from_json_file(str(manifest_path))
                except (OSError, TypeError, ValueError, KeyError):
                    available, reason = False, 'Tool schema metadata is invalid'
                permissions = schema.permissions if schema is not None else {}
                execution = document.get('execution', {})
                background = execution.get('background', {}) if isinstance(execution, dict) else {}
                if isinstance(background, dict) and background.get('required') is True:
                    available, reason = False, 'Background-only tools cannot run in workflows'
                tools[name] = {'name': name, 'description': document.get('description', ''),
                               'parameters': document.get('parameters', {'type': 'object', 'properties': {}}),
                               'permissions': permissions, 'auto_approve': permissions.get('auto_approve', False),
                               'requires_approval': requires_workflow_confirmation(schema) if schema is not None else None,
                               'permissions_source': 'local_manifest', 'permissions_verified': schema is not None,
                               'available': available, 'reason': reason, 'unavailable_reason': reason,
                               'background_required': isinstance(background, dict) and background.get('required') is True,
                               'source': 'local'}
            for name, tool in tools.items():
                if policy_error and name not in excluded:
                    tool.update(available=None, reason=policy_error, unavailable_reason=policy_error)
                if name in excluded:
                    tool.update(available=False, reason='Excluded from managed workflows',
                                unavailable_reason='Excluded from managed workflows')
        return {'tools': sorted(tools.values(), key=lambda tool: tool['name']),
                'cached': cached is not None, 'updated_at': cached['updated_at'] if cached else None,
                'policy_error': policy_error or None}

    def publication_compatibility(self, workflow: dict, *, mode: str | None = None) -> dict:
        """Explain managed publication consequences using offline metadata only.

        This analyzes every declared step, including optional/false-condition
        steps, matching the runtime's whole-document unattended approval gate.
        Cached MCP metadata is advisory and cannot establish compatibility.
        """
        configured = configured_modes(self.root)
        if mode is not None and mode not in configured:
            raise BuilderError('Choose a configured mode for publication analysis')
        modes = [mode] if mode is not None else configured
        output = []
        approval_error = None
        try:
            approved_tools = validated_workflow_approval_tools(workflow)
        except WorkflowPolicyError as exc:
            approved_tools = set()
            approval_error = str(exc)
        for selected in modes:
            catalog = self.tools(selected)
            tools = {tool['name']: tool for tool in catalog['tools']}
            approvals = []
            unknown = []
            unavailable = []
            for index, step in enumerate(workflow.get('steps', []) if isinstance(workflow.get('steps'), list) else []):
                if not isinstance(step, dict) or not isinstance(step.get('tool'), str):
                    continue
                name = step['tool']
                metadata = tools.get(name)
                identity = {'index': index, 'step': step.get('step', index + 1), 'tool': name,
                            'label': str(step.get('description') or f"Step {step.get('step', index + 1)}")[:200],
                            'optional': step.get('required', True) is False,
                            'conditional': step.get('condition') is not None,
                            'approval_granted': name in approved_tools}
                if metadata is None:
                    unknown.append({**identity, 'metadata_source': 'missing',
                                    'reason': 'Tool permissions and availability are not in the offline catalog'})
                    continue
                source = metadata.get('permissions_source', 'cached_mcp' if metadata.get('source') == 'mcp' else 'unknown')
                identity['metadata_source'] = source
                verified = metadata.get('permissions_verified') is True
                permission_map = metadata.get('permissions')
                if verified and isinstance(permission_map, dict):
                    # Apply the exact shared policy to the trusted canonical
                    # permission map; no alternate boolean-only approximation.
                    schema = ToolSchema(name=name, description='', parameters={},
                                        script_path='', permissions=permission_map)
                    needs_approval = requires_workflow_confirmation(schema)
                    if needs_approval:
                        approvals.append({**identity, 'enforced': metadata.get('available') is True and name not in approved_tools,
                                          'available': metadata.get('available'),
                                          'reason': ('Explicit approval of this recipe revision covers this tool' if name in approved_tools
                                                     else 'This declared tool requires interactive approval before execution')})
                else:
                    unknown.append({**identity, 'reason': 'Cached or unverified tool permissions; unattended compatibility is unknown'})
                if metadata.get('available') is False:
                    unavailable.append({**identity, 'blocks_execution': not identity['optional'],
                                        'reason': metadata.get('reason') or 'Tool is unavailable'})
                elif metadata.get('available') is None and verified:
                    unknown.append({**identity, 'reason': metadata.get('reason') or 'Effective availability is unverified'})
            rejected = bool(approval_error or catalog.get('policy_error') or any(item['enforced'] for item in approvals)
                            or any(item['blocks_execution'] for item in unavailable))
            status = 'blocked' if rejected else ('unknown' if unknown else 'eligible')
            output.append({'mode': selected, 'unattended': status,
                           'approval_steps': approvals, 'unknown_steps': unknown,
                           'unavailable_steps': unavailable,
                           'affected_surfaces': ['slash', 'api', 'scheduler'],
                           'policy_error': approval_error or catalog.get('policy_error'),
                           'note': ('Managed slash commands, API calls and scheduled runs reject this recipe before any step runs'
                                    if rejected else ('Unattended compatibility cannot be established from the offline catalog'
                                                     if unknown else 'No known unattended approval restriction; runtime availability is checked again'))})
        return {'modes': output, 'checked_modes': modes,
                'requires_builder_approval': any(item['tool'] not in approved_tools for row in output for item in row['approval_steps']),
                'trusted_tools': sorted(approved_tools),
                'trustable_tools': sorted({item['tool'] for row in output for key in ('approval_steps', 'unknown_steps') for item in row[key]}),
                'trust_scope': 'Trust authorizes the listed tools, including runtime-generated arguments and inputs, only for this exact recipe revision. Global blocks and other managed policy remain enforced.',
                'uncertain': not modes or any(row['unknown_steps'] for row in output),
                'note': 'Publication applies managed policy to the full recipe. Optional and conditional tools can still require approval. This preview does not execute tools or verify live MCP availability.'}
