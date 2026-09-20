"""Resolve a browser follow-up through the conversation-owned task store."""

from uuid import UUID

from .models import AdmissionDenied

BROWSER_TOOLS = frozenset({'browser_use', 'browser_use_cloud'})
TERMINAL = frozenset({'succeeded', 'failed', 'cancelled', 'expired'})


def prior_browser_job(store, current, args):
    """Return the prior job only when this Web conversation owns it."""
    reference = args.get('continue_job_id') if isinstance(args, dict) else None
    if reference is None:
        return None
    if (not isinstance(reference, str) or len(reference) != 32
            or any(char not in '0123456789abcdef' for char in reference)):
        raise AdmissionDenied('Invalid browser follow-up job ID')
    prior = store.get(reference)
    if (not prior or prior['id'] == current.get('id')
            or prior['conversation_id'] != current['conversation_id']
            or prior['generation'] != current['generation']
            or prior['admission']['tool'] != current['tool']
            or prior['admission']['tool'] not in BROWSER_TOOLS):
        raise AdmissionDenied('Browser follow-up must reference an earlier task in this conversation')
    result = prior.get('result')
    result = result if isinstance(result, dict) else {}
    if prior['admission']['tool'] == 'browser_use':
        if (prior['state'] not in TERMINAL
                or not isinstance(prior['admission']['arguments'].get('url'), str)
                or not isinstance(result.get('speech'), str)):
            raise AdmissionDenied('Local browser follow-up needs finished saved research')
    else:
        if prior['state'] not in TERMINAL:
            raise AdmissionDenied('Cloud browser follow-up needs a finished task')
        prior_profile = prior['admission']['arguments'].get('use_profile', False)
        if ('use_profile' in args and args['use_profile'] != prior_profile):
            raise AdmissionDenied('Cloud follow-up must use the same saved-profile setting')
        data = result.get('data') or {}
        if isinstance(data, dict) and data.get('browser_stop_verified') is False:
            raise AdmissionDenied('Prior Cloud browser shutdown needs attention before a follow-up')
        run_id = data.get('run_id') if isinstance(data, dict) else None
        try:
            UUID(run_id)
        except (TypeError, ValueError, AttributeError):
            raise AdmissionDenied('Prior Cloud run has not returned a resumable run ID yet')
    return prior


def prior_cloud_run_id(prior):
    result = prior.get('result') or {}
    return result['data']['run_id']
