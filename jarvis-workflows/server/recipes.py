"""Source-aware recipe inventory and personal-only atomic publication."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from workflow_policy import BUILDER_POLICY_VERSION, workflow_approval_hash
from workflow_validation import validate_workflow_document

from .catalog import CatalogService
from .store import BuilderError, BuilderStore, encoded

MAX_RECIPE_BYTES = 2 * 1024 * 1024


def document_hash(document: dict) -> str:
    return hashlib.sha256(encoded(document).encode()).hexdigest()


class RecipeService:
    """Track actual filenames; IDs are never treated as existing source paths."""

    def __init__(self, workflows_dir: Path, store: BuilderStore, *, catalog: CatalogService | None = None):
        self.root = Path(workflows_dir).absolute()
        self.personal = self.root / 'personal'
        self.store = store
        self.catalog = catalog or CatalogService(self.root.parent.parent, store)

    @staticmethod
    def source_id(relative: str) -> str:
        return hashlib.sha256(relative.encode()).hexdigest()[:32]

    def inventory(self) -> list[dict]:
        inventory = []
        paths = [*sorted(self.root.glob('*.json')), *sorted(self.personal.glob('*.json'))]
        winners = {}
        groups = {}
        for path in paths:
            relative = path.relative_to(self.root).as_posix()
            item = {'source_id': self.source_id(relative), 'filename': relative,
                    'tier': 'personal' if path.parent == self.personal else 'shared',
                    'id': None, 'name': path.stem, 'description': '', 'hash': None,
                    'enabled': False, 'effective': False, 'shadowed': False,
                    'errors': [], 'commands': [], 'duplicate': False,
                    'duplicate_id': False, 'managed': False}
            try:
                if path.is_symlink() or path.parent.is_symlink():
                    raise BuilderError('Symlink workflow sources cannot be edited or run')
                with path.open('rb') as stream:
                    raw = stream.read(MAX_RECIPE_BYTES + 1)
                if len(raw) > MAX_RECIPE_BYTES:
                    raise BuilderError('Workflow exceeds the 2 MB editor limit')
                item['hash'] = hashlib.sha256(raw).hexdigest()
                document = json.loads(raw)
                if not isinstance(document, dict):
                    raise BuilderError('Workflow must be a JSON object')
                workflow_id = document.get('id')
                item.update(id=workflow_id if isinstance(workflow_id, str) else None,
                            name=document.get('name') or workflow_id or path.stem,
                            description=document.get('description', ''),
                            enabled=document.get('enabled', True) is not False,
                            managed='builder_policy_version' in document)
                triggers = document.get('triggers', {})
                explicit = triggers.get('explicit', []) if isinstance(triggers, dict) else []
                item['commands'] = [command for command in explicit if isinstance(command, str)] if isinstance(explicit, list) else []
                diagnostics = validate_workflow_document(document)
                item['errors'] = diagnostics['errors']
                if item['id']:
                    groups.setdefault((item['tier'], item['id']), []).append(item)
                    # Mirror loader order and its intentionally minimal acceptance.
                    if item['enabled'] and document.get('steps'):
                        winners[item['id']] = item
                item['filename_mismatch'] = item['id'] is not None and path.stem != item['id']
            except (OSError, ValueError, UnicodeError) as exc:
                item['errors'].append({'path': '', 'message': str(exc)[:300]})
            inventory.append(item)
        for item in inventory:
            item['effective'] = winners.get(item['id']) is item
            item['shadowed'] = bool(item['id'] in winners and not item['effective'])
            group = groups.get((item['tier'], item['id']), [])
            item['duplicate'] = item['duplicate_id'] = len(group) > 1
        return inventory

    def source(self, source_id: str) -> dict:
        item = next((item for item in self.inventory() if item['source_id'] == source_id), None)
        if item is None:
            raise BuilderError('Workflow source not found', 404)
        return item

    def read(self, source_id: str) -> tuple[dict, dict]:
        item = self.source(source_id)
        path = self.root / item['filename']
        if path.is_symlink() or path.parent.is_symlink():
            raise BuilderError('Symlink workflow sources cannot be opened')
        try:
            document = json.loads(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise BuilderError('Workflow source is not valid JSON') from exc
        if not isinstance(document, dict):
            raise BuilderError('Workflow must be a JSON object')
        return item, document

    def create_draft(self, *, source_id=None, workflow=None) -> dict:
        source_hash = None
        if source_id:
            supplied = workflow
            source, original = self.read(source_id)
            source_hash = source['hash']
            workflow = json.loads(encoded(supplied if supplied is not None else original))
            self._check_document(workflow)
            if source['tier'] == 'shared' and supplied is None:
                workflow['allow_workflow_tool'] = False
        elif workflow is None:
            workflow = {'id': 'new_workflow', 'name': 'New workflow', 'enabled': True,
                        'allow_workflow_tool': False, 'triggers': {'explicit': ['/new_workflow']},
                        'variables': {}, 'steps': []}
        else:
            self._check_document(workflow)
            workflow = json.loads(encoded(workflow))
            workflow['allow_workflow_tool'] = False
        workflow.pop('builder_unattended_approval', None)
        return self.store.create_draft(workflow, source_id, source_hash)

    @staticmethod
    def _check_document(workflow) -> None:
        if not isinstance(workflow, dict):
            raise BuilderError('Workflow must be a JSON object')
        if len(encoded(workflow).encode()) > MAX_RECIPE_BYTES:
            raise BuilderError('Workflow exceeds the 2 MB editor limit')

    def validate(self, workflow: dict, source_id=None, *, mode: str | None = None) -> dict:
        self._check_document(workflow)
        current_id = None
        if source_id:
            current_id = self.source(source_id)['id']
        # Same-ID shared sources are intentional override predecessors, not command collisions.
        others = []
        for source in self.inventory():
            if source['effective'] and source['id'] not in {current_id, workflow.get('id')}:
                try:
                    others.append(self.read(source['source_id'])[1])
                except BuilderError:
                    continue
        document = {**workflow, 'builder_policy_version': BUILDER_POLICY_VERSION}
        document.pop('builder_unattended_approval', None)
        diagnostics = validate_workflow_document(document, builder=True, workflows=others)
        for source in self.inventory():
            if source['duplicate'] and source['id'] in {current_id, workflow.get('id')}:
                diagnostics['errors'].append({'path': 'id', 'message': 'Duplicate workflow IDs in one source tier must be resolved before publishing'})
                break
        diagnostics['publication_compatibility'] = self.catalog.publication_compatibility(document, mode=mode)
        return diagnostics

    def publication_preview(self, draft_id: str, revision: int, *, mode: str | None = None) -> dict:
        """Analyze an exact saved draft before publishing changes its callers."""
        draft = self.store.get_draft(draft_id)
        if draft['revision'] != revision:
            raise BuilderError('Draft changed; reload before reviewing publication', 409)
        document = {**draft['workflow'], 'builder_policy_version': BUILDER_POLICY_VERSION}
        document.pop('builder_unattended_approval', None)
        return {'draft_id': draft_id, 'revision': revision, 'recipe_hash': workflow_approval_hash(document),
                **self.validate(document, draft['source_id'], mode=mode)}

    def publish(self, draft_id: str, revision: int, *, mode: str | None = None,
                trust_unattended: bool = False, preview_hash: str | None = None,
                trust_tools: list[str] | None = None) -> dict:
        if type(trust_unattended) is not bool:
            raise BuilderError('Recipe trust must be an explicit boolean decision')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM drafts WHERE id=?', (draft_id,)).fetchone()
            if row is None:
                raise BuilderError('Draft not found', 404)
            if row['revision'] != revision:
                raise BuilderError('Draft changed; reload before publishing', 409)
            draft = self.store._draft(row)
            document = dict(draft['workflow'])
            document['builder_policy_version'] = BUILDER_POLICY_VERSION
            document.pop('builder_unattended_approval', None)
            diagnostics = self.validate(document, draft['source_id'], mode=mode)
            if diagnostics['errors']:
                raise BuilderError('Workflow validation failed', errors=diagnostics['errors'],
                                   warnings=diagnostics['warnings'])
            if trust_unattended:
                expected_hash = workflow_approval_hash(document)
                candidates = diagnostics['publication_compatibility']['trustable_tools']
                if preview_hash != expected_hash:
                    raise BuilderError('Recipe changed since publication review; review and confirm trust again', 409)
                if (not isinstance(trust_tools, list) or any(not isinstance(name, str) for name in trust_tools)
                        or sorted(set(trust_tools)) != candidates or len(set(trust_tools)) != len(trust_tools)):
                    raise BuilderError('Tool approval requirements changed; review the listed recipe tools again', 409)
                document['builder_unattended_approval'] = {'version': 1, 'recipe_hash': expected_hash, 'tools': candidates}
                diagnostics['publication_compatibility'] = self.catalog.publication_compatibility(document, mode=mode)
            original = None
            if draft['source_id']:
                original, old = self.read(draft['source_id'])
                if original['hash'] != draft['base_hash']:
                    raise BuilderError('Source changed outside this draft; reopen it before publishing', 409)
                if document.get('triggers') != old.get('triggers'):
                    diagnostics['warnings'].append({'path': 'triggers', 'message': 'Triggers changed; scheduled tasks and saved commands may need updating'})
                old_variables = old.get('variables', {})
                new_variables = document.get('variables', {})
                if isinstance(old_variables, dict) and isinstance(new_variables, dict) and old_variables != new_variables:
                    removed = sorted(set(old_variables) - set(new_variables))
                    diagnostics['warnings'].append({'path': 'variables', 'message': 'Variable rules changed; scheduled query inputs may need updating' + (': removed ' + ', '.join(removed) if removed else '')})
                if document.get('id') != old.get('id'):
                    raise BuilderError('Existing workflow IDs cannot be changed; import a copy to create a new ID')
            else:
                if not re.fullmatch(r'[a-z0-9_]+', document.get('id', '')):
                    raise BuilderError('New workflow IDs must contain only lowercase letters, digits and underscores')
                if any(item['id'] == document['id'] for item in self.inventory()):
                    raise BuilderError('Workflow ID already exists; open its existing source', 409)
            if self.personal.is_symlink() or self.root.is_symlink():
                raise BuilderError('Workflow directories cannot be symlinks')
            self.personal.mkdir(parents=True, exist_ok=True)
            if original and original['tier'] == 'personal':
                destination = self.root / original['filename']
            else:
                if any(item['tier'] == 'personal' and item['id'] == document['id'] for item in self.inventory()):
                    raise BuilderError('A personal source now provides this ID; reopen that source instead', 409)
                destination = self.personal / f"{document['id']}.json"
                if destination.exists() or destination.is_symlink():
                    raise BuilderError('A personal source already exists at the destination; open it instead', 409)
            if destination.parent.resolve() != self.personal.resolve() or destination.is_symlink():
                raise BuilderError('Personal workflow destination is unsafe')
            if (document.get('enabled', True) is False
                    and any(item['tier'] == 'shared' and item['id'] == document['id'] and item['enabled']
                            for item in self.inventory())):
                raise BuilderError('Disabling this override restores the bundled recipe; remove the override explicitly instead')
            raw = (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode()
            fd, temporary = tempfile.mkstemp(prefix='.builder-', suffix='.tmp', dir=self.personal)
            try:
                with os.fdopen(fd, 'wb') as target:
                    target.write(raw)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, destination)
                directory_fd = os.open(self.personal, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            new_source_id = self.source_id(destination.relative_to(self.root).as_posix())
            new_hash = hashlib.sha256(raw).hexdigest()
            db.execute('UPDATE drafts SET document=?,source_id=?,source_hash=?,revision=revision+1,updated=strftime("%s","now") WHERE id=?',
                       (encoded(document), new_source_id, new_hash, draft_id))
        return {'source': self.source(new_source_id), 'draft': self.store.get_draft(draft_id),
                'workflow': document, 'hash': new_hash, 'warnings': diagnostics['warnings'],
                'publication_compatibility': diagnostics['publication_compatibility']}

    def remove_personal(self, source_id: str, expected_hash: str) -> dict:
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            source = self.source(source_id)
            if source['tier'] != 'personal':
                raise BuilderError('Bundled workflows cannot be removed')
            if source['hash'] != expected_hash:
                raise BuilderError('Source changed; reload before removing it', 409)
            path = self.root / source['filename']
            if path.is_symlink() or self.personal.is_symlink():
                raise BuilderError('Symlink sources cannot be removed')
            path.unlink()
        restored = next((item for item in self.inventory()
                         if item['id'] == source['id'] and item['effective']), None)
        return {'restored': restored}
