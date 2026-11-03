"""Optional Jarvis workflow editor, preserving the shared UI auth posture."""
from __future__ import annotations

import signal
from pathlib import Path

from config_loader import load_config
from flask import Flask, jsonify, redirect, request, send_from_directory
from flask_cors import CORS
from ui_navigation import register_ui_navigation
from webui_auth import (
    create_token,
    get_auth_status,
    get_token_from_request,
    is_auth_enabled,
    verify_password,
    verify_token,
)

from .catalog import CatalogService, configured_modes
from .recipes import RecipeService
from .runs import RunSupervisor
from .store import BuilderError, BuilderStore

ROOT = Path(__file__).resolve().parents[2]

PUBLIC_ROUTES = {'/login', '/api/status', '/api/auth/status', '/api/auth/login', '/api/auth/verify'}
PUBLIC_EXTENSIONS = {'.css', '.js', '.ico', '.png', '.jpg', '.jpeg', '.svg', '.woff', '.woff2'}


def create_app(*, repo_root: Path | None = None, db_path: Path | None = None,
               workflows_dir: Path | None = None, runner=None, startup_mode: str = 'cloud') -> Flask:
    """Construct an independent Flask app with injectable, temporary test storage."""
    root = Path(repo_root or ROOT)
    client = ROOT / 'jarvis-workflows' / 'client'
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=2 * 1024 * 1024, startup_mode=startup_mode)
    store = BuilderStore(Path(db_path or root / 'data' / 'workflow_builder.db'))
    catalog = CatalogService(root, store)
    recipes = RecipeService(Path(workflows_dir or root / 'data' / 'workflows'), store, catalog=catalog)
    supervisor = runner if runner is not None else RunSupervisor(root, store, recipes, catalog)
    app.extensions.update(workflow_store=store, workflow_recipes=recipes,
                          workflow_catalog=catalog, workflow_runner=supervisor)
    CORS(app, resources={r'/*': {'origins': '*'}})
    register_ui_navigation(app)

    @app.before_request
    def check_auth():
        if not is_auth_enabled() or request.path in PUBLIC_ROUTES:
            return None
        if any(request.path.endswith(extension) for extension in PUBLIC_EXTENSIONS):
            return None
        if verify_token(get_token_from_request(request)):
            return None
        if request.path.startswith('/api/'):
            return jsonify(ok=False, error='Authentication required'), 401
        return redirect('/login')

    @app.errorhandler(BuilderError)
    def builder_error(error):
        return jsonify(ok=False, error=str(error), **error.details), error.status

    @app.errorhandler(500)
    def server_error(_error):
        return jsonify(ok=False, error='Internal server error'), 500

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(ok=False, error='Request exceeds the 2 MB editor limit'), 413

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(ok=False, error='Not found'), 404

    def body() -> dict:
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise BuilderError('A JSON object is required')
        return value

    def document(data: dict) -> dict:
        value = data.get('workflow', data.get('definition'))
        recipes._check_document(value)
        value = dict(value)
        value.pop('builder_unattended_approval', None)
        return value

    def revision(data: dict) -> int:
        value = data.get('revision')
        if type(value) is not int or value < 1:
            raise BuilderError('The current draft revision is required')
        return value

    @app.get('/api/status')
    def status():
        version_path = root / 'VERSION'
        version = version_path.read_text().strip() if version_path.exists() else '0.0.0'
        return jsonify(ok=True, status='running', service='jarvis-workflows',
                       version=version, startup_mode=app.config['startup_mode'])

    @app.get('/api/auth/status')
    def auth_status():
        return jsonify(ok=True, **get_auth_status())

    @app.post('/api/auth/login')
    def login():
        if not is_auth_enabled():
            return jsonify(ok=False, error='Auth not configured'), 400
        password = body().get('password', '')
        if not isinstance(password, str) or not password:
            raise BuilderError('Password required')
        if not verify_password(password):
            return jsonify(ok=False, error='Invalid password'), 401
        token = create_token()
        return jsonify(ok=True, token=token,
                       expires_in_days=get_auth_status()['token_expiry_days'])

    @app.get('/api/auth/verify')
    def verify():
        payload = verify_token(get_token_from_request(request))
        if not payload:
            return jsonify(ok=False, error='Invalid token'), 401
        return jsonify(ok=True, expires_at=payload.get('exp'))

    @app.post('/api/auth/logout')
    def logout():
        return jsonify(ok=True, message='Logged out')

    @app.get('/api/bootstrap')
    def bootstrap():
        return jsonify(ok=True, modes=configured_modes(root), startup_mode=startup_mode,
                       default_deadline=900, max_deadline=3600, active_run=store.active_run())

    @app.get('/api/workflows')
    def inventory():
        return jsonify(ok=True, workflows=recipes.inventory())

    @app.get('/api/workflows/<source_id>')
    def read_workflow(source_id):
        source, workflow = recipes.read(source_id)
        return jsonify(ok=True, source=source, workflow=workflow, definition=workflow)

    @app.delete('/api/workflows/<source_id>/personal')
    def remove_personal(source_id):
        return jsonify(ok=True, **recipes.remove_personal(source_id, body().get('hash')))

    @app.get('/api/drafts')
    def drafts():
        return jsonify(ok=True, drafts=store.list_drafts())

    @app.post('/api/drafts')
    def new_draft():
        data = body()
        draft = recipes.create_draft(source_id=data.get('source_id'),
                                     workflow=data.get('workflow', data.get('definition')))
        return jsonify(ok=True, draft=draft), 201

    @app.get('/api/drafts/<draft_id>')
    def get_draft(draft_id):
        return jsonify(ok=True, draft=store.get_draft(draft_id))

    @app.patch('/api/drafts/<draft_id>')
    def save_draft(draft_id):
        data = body()
        return jsonify(ok=True, draft=store.update_draft(draft_id, document(data), revision(data)))

    @app.post('/api/validate')
    def validate():
        data = body()
        return jsonify(ok=True, **recipes.validate(document(data), data.get('source_id'), mode=data.get('mode')))

    @app.post('/api/drafts/<draft_id>/publish-preview')
    def publication_preview(draft_id):
        data = body()
        return jsonify(ok=True, **recipes.publication_preview(draft_id, revision(data), mode=data.get('mode')))

    @app.post('/api/drafts/<draft_id>/publish')
    def publish(draft_id):
        data = body()
        return jsonify(ok=True, **recipes.publish(draft_id, revision(data), mode=data.get('mode'),
                                                trust_unattended=data.get('trust_unattended', False),
                                                preview_hash=data.get('preview_hash'), trust_tools=data.get('trust_tools')))

    @app.get('/api/tools')
    def tools():
        return jsonify(ok=True, **catalog.tools(request.args.get('mode', startup_mode)))

    @app.post('/api/tools/refresh')
    def refresh():
        return jsonify(ok=True, **supervisor.refresh_catalog(body().get('mode', startup_mode)))

    @app.post('/api/runs/prepare')
    def prepare_run():
        return jsonify(ok=True, **supervisor.prepare(body()))

    @app.post('/api/runs')
    def run():
        return jsonify(ok=True, run=supervisor.start(body())), 202

    @app.get('/api/runs')
    def runs():
        store.prune()
        return jsonify(ok=True, runs=store.list_runs())

    @app.get('/api/runs/<run_id>')
    def get_run(run_id):
        try:
            after = int(request.args.get('after', '0'))
        except ValueError as exc:
            raise BuilderError('Event cursor must be an integer') from exc
        return jsonify(ok=True, run=store.get_run(run_id),
                       events=store.events(run_id, after), approvals=store.approvals(run_id))

    @app.post('/api/runs/<run_id>/cancel')
    def cancel(run_id):
        return jsonify(ok=True, run=store.cancel(run_id))

    @app.post('/api/approvals/<approval_id>')
    def decide(approval_id):
        data = body()
        if type(data.get('approved')) is not bool or not isinstance(data.get('call_hash'), str):
            raise BuilderError('An approval decision and exact call hash are required')
        store.decide(approval_id, data['approved'], data['call_hash'])
        return jsonify(ok=True)

    @app.get('/')
    def index():
        return send_from_directory(client, 'index.html')

    @app.get('/login')
    def login_page():
        return send_from_directory(client, 'login.html')

    @app.get('/fonts/<path:filename>')
    def fonts(filename):
        return send_from_directory(root / 'jarvis-web' / 'client' / 'fonts', filename)

    @app.get('/assets/<path:filename>')
    def assets(filename):
        if (client / 'assets' / filename).is_file():
            return send_from_directory(client / 'assets', filename)
        return send_from_directory(root / 'jarvis-web' / 'client' / 'assets', filename)

    @app.get('/<path:filename>')
    def static_file(filename):
        return send_from_directory(client, filename)

    return app


def run_server(host: str = '0.0.0.0', port: int = 5005, mode: str = 'cloud', debug: bool = False):
    """Opt-in native/Docker entrypoint; network and auth defaults match sibling UIs."""
    load_config(mode)
    app = create_app(startup_mode=mode)
    runner = app.extensions['workflow_runner']

    def stop(_number, _frame):
        runner.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, stop)
    print(f'Jarvis Workflows listening on http://{host}:{port} ({mode})')
    try:
        app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)
    finally:
        runner.close()
