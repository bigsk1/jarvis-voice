"""Stable supervised-skill identities and reviewed execution settings."""

from .models import AdmissionDenied

ADAPTER = 'local_skill_v1'
REMOTE_ADAPTER = 'remote_skill_v1'
SKILL_ADAPTERS = frozenset({ADAPTER, REMOTE_ADAPTER})
LOCAL_ADAPTERS = frozenset({ADAPTER})
DEFAULT_LIMITS = {
    'memory_bytes': 2 * 1024**3,
    'file_bytes': 512 * 1024**2,
    'input_bytes': 512 * 1024**2,
    'output_bytes': 2 * 1024**2,
}


def execution_settings(background):
    """Fail only background policy; never participate in foreground discovery."""
    allowed = {'supported', 'adapter', 'timeout_seconds', 'completion_scope',
               'progress_label', 'limits', 'argument_constraints'}
    scopes = {ADAPTER: 'process_group', REMOTE_ADAPTER: 'remote_work'}
    if (not isinstance(background, dict) or set(background) - allowed
            or background.get('supported') is not True or background.get('adapter') not in scopes
            or background.get('completion_scope') != scopes[background['adapter']]):
        raise AdmissionDenied('Unsupported local background execution policy')
    timeout = background.get('timeout_seconds')
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise AdmissionDenied('Local background timeout must be 1–86400 seconds')
    label = background.get('progress_label', 'Running local skill')
    if not isinstance(label, str) or not 1 <= len(label) <= 120:
        raise AdmissionDenied('Invalid background progress label')
    limits = background.get('limits', {})
    if not isinstance(limits, dict) or set(limits) - set(DEFAULT_LIMITS):
        raise AdmissionDenied('Unknown local background resource limit')
    limits = {**DEFAULT_LIMITS, **limits}
    ceilings = {'memory_bytes': 32 * 1024**3, 'file_bytes': 8 * 1024**3,
                'input_bytes': 8 * 1024**3, 'output_bytes': 16 * 1024**2}
    if any(type(value) is not int or not 1 <= value <= ceilings[key]
           for key, value in limits.items()):
        raise AdmissionDenied('Invalid local background resource limit')
    return {**background, 'progress_label': label, 'limits': limits}
