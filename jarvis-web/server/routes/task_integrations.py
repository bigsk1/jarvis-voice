"""Same-origin installation-operator administration. No provider credentials in GETs."""
from flask import Blueprint, current_app, jsonify, request

from lib.webhook_integrations.service import IntegrationService

from .background_tasks import operator_required

integrations_bp = Blueprint('task_integrations', __name__)


def service(*, create=False):
    value = IntegrationService(current_app.extensions['jarvis_background_tasks'].store)
    if create:
        value.store.initialize()
    return value


def payload(allowed):
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError('Unexpected integration settings')
    return value


@integrations_bp.get('/api/task-integrations')
@operator_required
def status():
    result = service().status()
    try:
        from lib.webhook_integrations.browser import callback_sources
        managed = {source: tool for tool, source in callback_sources(service().store).items()}
        for source in result['sources']:
            source['managed_tool'] = managed.get(source['id'])
    except Exception:
        pass
    return jsonify(result)


@integrations_bp.patch('/api/task-integrations')
@operator_required
def configure():
    return jsonify(service(create=True).configure(payload({'enabled'}).get('enabled')))


@integrations_bp.post('/api/task-integrations/keys')
@operator_required
def keys():
    action = payload({'action'}).get('action')
    value = service(create=True)
    if action == 'initialize':
        return jsonify(value.initialize_key())
    if action == 'rotate':
        return jsonify(value.rotate_key())
    raise ValueError('Expected initialize or rotate')


@integrations_bp.post('/api/task-integrations')
@operator_required
def create():
    values = payload({'name', 'callback_base', 'submit_url', 'events', 'rate_limit'})
    if not {'name', 'callback_base', 'submit_url'} <= values.keys():
        raise ValueError('Source name, receiver base URL and local submission URL are required')
    return jsonify({'source': service(create=True).create_source(**values)}), 201


@integrations_bp.patch('/api/task-integrations/<source_id>')
@operator_required
def update(source_id):
    values = payload({'revision', 'name', 'enabled', 'events', 'callback_base', 'submit_url', 'rate_limit', 'revoke'})
    revision = values.pop('revision', None)
    return jsonify({'source': service().update_source(source_id, revision, **values)})


@integrations_bp.post('/api/task-integrations/<source_id>/credentials')
@operator_required
def credential(source_id):
    values = payload({'scheme', 'expires_in', 'replace_id', 'overlap_seconds'})
    response = jsonify(service().create_credential(source_id, **values))
    response.headers['Cache-Control'] = 'no-store'
    return response, 201


@integrations_bp.post('/api/task-integrations/<source_id>/credentials/<credential_id>/revoke')
@operator_required
def revoke(source_id, credential_id):
    payload(set())
    service().revoke_credential(source_id, credential_id)
    return jsonify({'ok': True})


@integrations_bp.get('/api/task-integrations/<source_id>/deliveries')
@operator_required
def deliveries(source_id):
    return jsonify(service().deliveries(source_id, offset=int(request.args.get('offset', 0)),
                                        limit=int(request.args.get('limit', 25))))


@integrations_bp.post('/api/task-integrations/<source_id>/deliveries/<event_id>/discard')
@operator_required
def discard(source_id, event_id):
    payload(set())
    service().dispose_event(source_id, event_id, 'discard')
    return jsonify({'ok': True})


@integrations_bp.post('/api/task-integrations/<source_id>/test')
@operator_required
def test(source_id):
    payload(set())
    return jsonify(service().test_source(source_id))
