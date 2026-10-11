"""Shared Jarvis entrypoints and artifact delivery for the optional Craft tools."""
import json
import sys
from pathlib import Path

from config_loader import get_config_value, load_config
from craft_client import CraftClient, CraftError
from paths import resolve_local_file_tool_path
from remote_completion import RemoteCompletionError
from stash_helper import StashFile, open_space, safe_resolve_file

TOOLS = {'craft_image': 'photocraft', 'craft_pdf': 'pdfcraft', 'craft_photos': 'lightcraft',
         'craft_video': 'filmcraft', 'craft_motion': 'effectcraft'}

FOLLOWUP_NOTES = {
    'photocraft': 'For caption/layer revisions always pass editable_project_ref as the tool input and the layer ID from document. Reuse project_revision from the last successful result; rejected requests do not advance it. Omit text to keep the words when changing font_size or placement. Font size uses full SOURCE image pixels, not preview pixels. name only names new layers and is ignored on update_text. stash_ref is the flattened PNG for display/export, not editable text. Wait for any running job before revising.',
    'pdfcraft': 'Further PDF edits use the exported PDF as a source, via its Stash or Craft reference.',
    'lightcraft': 'Further adjustments use the exported image as a source. This adapter does not retain a native photo library.',
    'filmcraft': 'Use editable_project_ref to reopen this FilmCraft timeline with video_edits. For update_text keep clip/layer IDs from document.overlays; omit text to keep the words. Omit start/duration or copy the selected overlay\'s saved values; echoed defaults 0/null also keep timing. Actual timing changes are unsupported. Wait for any running job before revising. clips selects source ranges only when creating a new timeline. Timed captions use editable graphic text overlays.',
    'effectcraft': 'Each call creates a new title composition. This adapter cannot reopen a saved native composition; project_id only groups related jobs.',
}


def source_path(source):
    if source.startswith('stash://'):
        result = safe_resolve_file(stash_ref=source)
        if not result['found']:
            raise ValueError('Source Stash file is missing or expired')
        return Path(result['path'])
    return resolve_local_file_tool_path(source)


def save_outputs(client, job, tool):
    if job['state'] != 'succeeded':
        return {'ok': False, 'completion': 'unknown' if job['state'] in ('running','queued','interrupted') else 'completed',
                'speech': f'Craft job is {job["state"]}.', 'error': job.get('error'), 'data': {**job, 'job_id': job['id']}}
    # Keep saved project references and media together, with source-artifact
    # retention. Never fall back to a temporary path and claim Stash delivery.
    space, _ = open_space(scope='project', labels=['craft_projects', 'source_artifact'])
    outputs = []
    document = None
    for output in job['outputs']:
        content = client.download(output)
        if output['role'] == 'inspection' and output['name'] == 'document.json':
            if len(content) > 256 * 1024:
                raise ValueError('Craft document inspection exceeds its size limit')
            document = json.loads(content)
        saved = StashFile(space).save_binary(content, output['name'], mime_type=output['mime_type'],
                                             tags=['craft', job['operation']['app'], output['role']], tool_origin=tool)
        outputs.append({**output, 'stash_ref': saved['ref'], 'file_path': saved['path'],
                        'craft_ref': f'craft://{job["project_id"]}/{output["id"]}'})
    primary = next(item for item in outputs if item['role'] == 'primary')
    project = client.project(job['project_id'])
    data = {'app': job['operation']['app'], 'app_version': job['app_version'], 'job_id': job['id'],
            'request_id': job['request_id'], 'project_id': job['project_id'], 'project_revision': job.get('revision', project['revision'] - 1) + 1,
            'state': 'succeeded', 'renderer': job.get('renderer'), 'outputs': outputs,
            'stash_ref': primary['stash_ref'], 'file_path': primary['file_path'],
            'filename': primary['name'], 'mime_type': primary['mime_type']}
    data['followup_note'] = FOLLOWUP_NOTES[job['operation']['app']]
    editable = next((item for item in outputs if item['role'] == 'project' and item['name'].endswith(('.pcraft', '.fcproj'))), None)
    if editable:
        data['editable_project_ref'] = editable['craft_ref']
    if document is not None:
        data['document'] = document
    return {'ok': True, 'completion': 'completed', 'speech': 'Craft edit completed. The result and supporting files are saved.', 'data': data}


def execute_tool(tool, args):
    args = dict(args)
    client = CraftClient()
    job = None
    attempted = False
    rejection_data = {}
    try:
        if tool == 'craft_inspect':
            action = args.get('action', 'capabilities')
            if action == 'capabilities':
                return {'ok': True, 'speech': 'Craft Gateway capabilities retrieved.', 'data': client.capabilities()}
            if action == 'jobs':
                return {'ok': True, 'speech': 'Recent Craft jobs retrieved.', 'data': client.json('GET', '/jobs')}
            if action == 'project':
                return {'ok': True, 'speech': 'Craft project inspected.', 'data': client.project(args.get('project_id'))}
            job = client.job(args.get('job_id'), args.get('request_id'))
            if action == 'cancel':
                job = client.json('POST', '/jobs/' + client.identifier(job['id']) + '/cancel')
            elif action == 'collect':
                return save_outputs(client, job, tool)
            elif action != 'job':
                raise ValueError('Unknown inspection action')
            return {'ok': True, 'speech': f'Craft job is {job["state"]}.', 'data': {**job, 'job_id': job['id']}}
        app = TOOLS[tool]
        native_ref = args.pop('editable_project_ref', None)
        if native_ref:
            if tool not in ('craft_image', 'craft_video') or not isinstance(native_ref, str) or not native_ref.startswith('craft://'):
                raise ValueError('editable_project_ref must select a saved Craft image or video project')
            if args.get('sources') and args['sources'] != [native_ref]:
                raise ValueError('For a project revision use editable_project_ref alone; omit flattened sources')
            args['sources'] = [native_ref]
        if tool == 'craft_motion' and args.get('sources'):
            raise ValueError('Title creation does not accept sources; use text and composition options')
        if tool != 'craft_motion' and not args.get('sources'):
            raise ValueError('Supply sources or the last successful editable_project_ref (project_id alone cannot reopen a document). No edit was submitted; project_revision has not advanced.')
        revision = any(edit.get('action') == 'update_text' for edit in args.get('edits', []) + args.get('video_edits', []))
        if revision and (len(args.get('sources', [])) != 1 or not args['sources'][0].startswith('craft://')):
            raise ValueError('Text revisions require editable_project_ref, not the exported PNG/MP4 or its stash_ref')
        capabilities = client.capabilities()
        if not capabilities['apps'][app]['supported'] or args['action'] not in capabilities['apps'][app]['actions']:
            raise ValueError('Selected Craft action is not available on this gateway. Inspect capabilities and install the tested release.')
        source_projects = {source.removeprefix('craft://').split('/')[0] for source in args.get('sources', []) if source.startswith('craft://')}
        project_id = args.get('project_id') or (next(iter(source_projects)) if len(source_projects) == 1 else None)
        if len(source_projects) > 1 or (source_projects and project_id not in source_projects):
            raise ValueError('Craft sources must belong to one selected project')
        project = client.project(project_id) if project_id else client.json('POST', '/projects')
        if args.get('project_revision') is not None and args['project_revision'] != project['revision']:
            rejection_data = {'project_id': project['id'], 'current_project_revision': project['revision'],
                              'requested_project_revision': args['project_revision'], 'edit_submitted': False}
            raise ValueError(f'Project revision changed: requested {args["project_revision"]}, current {project["revision"]}. No edit was submitted. Inspect the project and use its current saved project reference/revision; rejected calls do not advance it.')
        if revision or native_ref:
            artifact_id = client.identifier(args['sources'][0].removeprefix('craft://').split('/')[-1])
            extension = '.pcraft' if tool == 'craft_image' else '.fcproj'
            if not any(item['id'] == artifact_id and item['role'] == 'project' and item['name'].endswith(extension)
                       for item in project.get('artifacts', [])):
                raise ValueError('Select editable_project_ref for this app; flattened exports have no editable text layers')
        inputs = []
        for source in args.get('sources', []):
            if source.startswith('craft://'):
                parts = source.removeprefix('craft://').split('/')
                if len(parts) != 2 or parts[0] != project['id']:
                    raise ValueError('Craft source must belong to the selected project; supply its project_id')
                inputs.append(client.identifier(parts[1]))
            else:
                inputs.append(client.upload(project['id'], source_path(source))['id'])
        operation = {'app': app, 'action': args['action'], 'inputs': inputs,
                     **{key: value for key, value in args.items() if key not in ('action','sources','project_id','project_revision')}}
        attempted = True
        job = client.submit(project, operation)
        background = bool(get_config_value('JARVIS_BACKGROUND_MAX_INPUT_BYTES', ''))
        wait = 1200 if background else min(110, max(0, int(get_config_value('CRAFT_WAIT_SECONDS', '') or 90)))
        job = client.wait(job, wait)
        if job['state'] in ('queued', 'running'):
            if background:
                raise CraftError('Craft job is still running after the observation budget; inspect or collect it by job ID.', job=job)
            return {'ok': True, 'speech': 'Craft job accepted and still running. Use craft_inspect to check or collect it.',
                    'data': {'job_id': job['id'], 'request_id': job['request_id'], 'project_id': job['project_id'], 'state': job['state']}}
        return save_outputs(client, job, tool)
    except Exception as exc:
        completion = 'completed' if job and job.get('state') in ('succeeded','failed','cancelled') else ('unknown' if attempted or job else 'rejected')
        if isinstance(exc, RemoteCompletionError):
            completion = exc.completion
        if isinstance(exc, CraftError):
            job = exc.job or job
        return {'ok': False, 'completion': completion, 'speech': 'Craft operation could not complete.',
                'error': str(exc), 'data': {'job_id': job.get('id') if job else None,
                'project_id': job.get('project_id') if job else None, 'request_id': getattr(exc, 'request_id', None) or (job.get('request_id') if job else None), **rejection_data}}
    finally:
        client.close()


def main(tool):
    load_config()
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
        result = execute_tool(tool, args)
    except Exception as exc:
        result = {'ok': False, 'completion': 'rejected', 'speech': 'Craft configuration or arguments are invalid.', 'error': str(exc)}
    print(json.dumps(result))
    return 0 if result.get('ok') else 1
