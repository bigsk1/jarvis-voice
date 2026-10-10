"""Authenticated streaming API. Run one Uvicorn worker per state directory."""
import asyncio
import hmac
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .models import Submission
from .service import Service
from .store import Conflict

UPLOAD_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.pdf', '.mp4', '.mov', '.webm'}


def create_app(config):
    if len(config.get('api_key', '')) < 32:
        raise ValueError('Gateway requires a private API key of at least 32 characters')
    service = Service(config)
    @asynccontextmanager
    async def lifespan(app):
        service.start()
        try:
            yield
        finally:
            service.close()

    async def authenticate(request: Request):
        supplied = request.headers.get('authorization', '')
        if not hmac.compare_digest(supplied, 'Bearer ' + config['api_key']):
            raise HTTPException(401, 'Valid gateway API key required', headers={'WWW-Authenticate': 'Bearer'})

    app = FastAPI(title='Jarvis Craft Gateway', lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=None, dependencies=[Depends(authenticate)])
    app.add_middleware(RequestLimit, upload_limit=config.get('upload_bytes', 50 * 1024**2))
    app.state.service = service
    upload_lock = asyncio.Lock()

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': 'Requested project, job or artifact does not exist'}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': str(exc)[:1000]}, status_code=409 if isinstance(exc, Conflict) else 422)

    @app.get('/craft-api/v1/capabilities')
    def capabilities():
        return service.public_capabilities()

    @app.post('/craft-api/v1/projects', status_code=201)
    def create_project():
        return service.store.create_project()

    @app.get('/craft-api/v1/projects/{project_id}')
    def project(project_id: str):
        return service.store.project(project_id)

    @app.post('/craft-api/v1/projects/{project_id}/inputs', status_code=201)
    async def upload(project_id: str, request: Request, filename: str):
        service.store.project(project_id)
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}', filename) or Path(filename).suffix.lower() not in UPLOAD_SUFFIXES:
            raise HTTPException(422, 'Use a simple supported raster, PDF or video filename')
        # Serialized admission protects global disk accounting from parallel uploads.
        async with upload_lock:
            limit = config.get('upload_bytes', 50 * 1024**2)
            used = await run_in_threadpool(service.disk_usage)
            with service.store.db() as db:
                active = db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
            remaining = config.get('disk_bytes', 4 * 1024**3) - used - active * config.get('job_disk_bytes', 512 * 1024**2)
            if remaining <= 0:
                raise HTTPException(413, 'Gateway disk quota reached')
            folder = service.store.workspaces / project_id / 'inputs' / uuid.uuid4().hex
            folder.mkdir(parents=True, mode=0o700)
            path = folder / filename
            size = 0
            try:
                with path.open('xb') as stream:
                    async for block in request.stream():
                        size += len(block)
                        if size > min(limit, remaining):
                            raise HTTPException(413, 'Upload exceeds gateway input or disk limit')
                        stream.write(block)
                if size == 0:
                    raise HTTPException(422, 'Empty input')
                with path.open('rb') as stream:
                    magic = stream.read(32)
                ext = path.suffix.lower()
                valid = {'.png': magic.startswith(b'\x89PNG\r\n\x1a\n'), '.pdf': magic.startswith(b'%PDF-'),
                         '.jpg': magic.startswith(b'\xff\xd8\xff'), '.jpeg': magic.startswith(b'\xff\xd8\xff'),
                         '.webp': magic.startswith(b'RIFF') and magic[8:12] == b'WEBP',
                         '.mp4': b'ftyp' in magic, '.mov': any(x in magic for x in (b'ftyp', b'moov', b'mdat')),
                         '.webm': magic.startswith(b'\x1aE\xdf\xa3')}[ext]
                if not valid:
                    raise HTTPException(422, 'Input header does not match its extension')
                return await run_in_threadpool(service.store.add_artifact, project_id, path)
            except BaseException:
                path.unlink(missing_ok=True)
                folder.rmdir()
                raise

    @app.post('/craft-api/v1/jobs', status_code=202)
    def submit(body: Submission):
        # Check for an already accepted request before checking current app version,
        # so retries remain recoverable even after an app update.
        try:
            prior = service.store.job(request_id=body.request_id)
        except KeyError:
            prior = None
        if prior is not None:
            # Store verifies an exact canonical body match; binary is ignored for an existing job.
            return service.store.submit(body, '', '')
        capability = service.capabilities()['apps'][body.operation.app]
        if not capability['supported']:
            raise HTTPException(422, 'Selected app is absent or its version is untested. Inspect gateway capabilities.')
        service.validate_inputs(body)
        # Reserve worst-case scratch space for queued/running jobs as well.
        with service.store.db() as db:
            active = db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
            if service.disk_usage() + (active + 1) * config.get('job_disk_bytes', 512 * 1024**2) > config.get('disk_bytes', 4 * 1024**3):
                raise HTTPException(413, 'Insufficient gateway disk quota for another job')
            job = service.store.submit(body, capability['binary'], capability['version'] or 'unmanaged')
        service.wake.set()
        return job

    @app.get('/craft-api/v1/jobs')
    def recent_jobs():
        return {'jobs': service.store.recent_jobs()}

    @app.get('/craft-api/v1/jobs/by-request/{request_id}')
    def find_request(request_id: str):
        return service.store.job(request_id=request_id)

    @app.get('/craft-api/v1/jobs/{job_id}')
    def job(job_id: str):
        return service.store.job(job_id)

    @app.post('/craft-api/v1/jobs/{job_id}/cancel')
    def cancel(job_id: str):
        return service.store.cancel(job_id)

    @app.get('/craft-api/v1/artifacts/{artifact_id}')
    def download(artifact_id: str):
        record = service.store.artifact(artifact_id)
        if record['job_id'] and service.store.job(record['job_id'])['state'] != 'succeeded':
            raise HTTPException(409, 'Artifact is not published by a successful job')
        return FileResponse(record['path'], media_type=record['mime_type'], filename=record['name'],
                            headers={'X-Content-SHA256': record['sha256']})

    return app


class RequestLimit:
    """Bound request bodies before JSON parsing, including unauthenticated POSTs."""
    def __init__(self, app, upload_limit):
        self.app = app
        self.upload_limit = upload_limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        limit = self.upload_limit if scope['path'].endswith('/inputs') else 1024 * 1024
        consumed = 0
        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get('body', b''))
            if consumed > limit:
                raise HTTPException(413, 'Request body exceeds limit')
            return message
        await self.app(scope, bounded_receive, send)
