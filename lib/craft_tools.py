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
    'photocraft': 'Reuse project_id and the project craft_ref to reopen this layered PhotoCraft project.',
    'pdfcraft': 'Further PDF edits use the exported PDF as a source, via its Stash or Craft reference.',
    'lightcraft': 'Further adjustments use the exported image as a source. This adapter does not retain a native photo library.',
    'filmcraft': 'Each call assembles a new timeline from supplied media. This adapter cannot reopen a saved native timeline; project_id only groups related jobs.',
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
    for output in job['outputs']:
        content = client.download(output)
        saved = StashFile(space).save_binary(content, output['name'], mime_type=output['mime_type'],
                                             tags=['craft', job['operation']['app'], output['role']], tool_origin=tool)
        outputs.append({**output, 'stash_ref': saved['ref'], 'file_path': saved['path'],
                        'craft_ref': f'craft://{job["project_id"]}/{output["id"]}'})
    primary = next(item for item in outputs if item['role'] == 'primary')
    project = client.project(job['project_id'])
    data = {'app': job['operation']['app'], 'app_version': job['app_version'], 'job_id': job['id'],
            'request_id': job['request_id'], 'project_id': job['project_id'], 'project_revision': project['revision'],
            'state': 'succeeded', 'renderer': job.get('renderer'), 'outputs': outputs,
            'stash_ref': primary['stash_ref'], 'file_path': primary['file_path'],
            'filename': primary['name'], 'mime_type': primary['mime_type']}
    data['followup_note'] = FOLLOWUP_NOTES[job['operation']['app']]
    return {'ok': True, 'completion': 'completed', 'speech': 'Craft edit completed. The result and supporting files are saved.', 'data': data}


def execute_tool(tool, args):
    client = CraftClient()
    job = None
    attempted = False
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
        if tool == 'craft_motion' and args.get('sources'):
            raise ValueError('Title creation does not accept sources; use text and composition options')
        capabilities = client.capabilities()
        if not capabilities['apps'][app]['supported'] or args['action'] not in capabilities['apps'][app]['actions']:
            raise ValueError('Selected Craft action is not available on this gateway. Inspect capabilities and install the tested release.')
        project = client.project(args['project_id']) if args.get('project_id') else client.json('POST', '/projects')
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
                     **{key: value for key, value in args.items() if key not in ('action','sources','project_id')}}
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
                'project_id': job.get('project_id') if job else None, 'request_id': getattr(exc, 'request_id', None) or (job.get('request_id') if job else None)}}
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
