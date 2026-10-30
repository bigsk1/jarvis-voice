"""Trusted production bindings. Adding a compatible tool requires review here."""

import sys
from pathlib import Path

from .local_contract import ADAPTER, LOCAL_ADAPTERS, REMOTE_ADAPTER, SKILL_ADAPTERS
from .local_skill import LocalSkillRunner

ROOT = Path(__file__).resolve().parents[2]
# A manifest cannot add itself to this allowlist or select a Python callable.
# Media review: scripts distinguish explicit rejection/terminal completion from
# lost observation. Only confirmed failures release slots; other post-spawn
# errors remain uncertain. No provider cancellation/recovery contract is exposed:
# never equate process-group cancellation with remote cancellation or resubmit.
# MoneyPrinterTurbo also owns the social-clip job independently of this process;
# its existing client polls and saves one output but cannot cancel remote work.
TRUSTED_BINDINGS = {
    'convert_file': ADAPTER,
    'generate_image': REMOTE_ADAPTER,
    'generate_video': REMOTE_ADAPTER,
    'generate_avatar_video': REMOTE_ADAPTER,
    'generate_music': REMOTE_ADAPTER,
    'create_social_clip': REMOTE_ADAPTER,
    'craft_image': REMOTE_ADAPTER,
    'craft_pdf': REMOTE_ADAPTER,
    'craft_photos': REMOTE_ADAPTER,
    'craft_video': REMOTE_ADAPTER,
    'craft_motion': REMOTE_ADAPTER,
    'docling_convert': REMOTE_ADAPTER,
    'browser_use_cloud': REMOTE_ADAPTER,
    'phone_call': REMOTE_ADAPTER,
    'browser_use': 'http_callback_v1',
    'apify_run_actor': 'apify_actor_v1',
}

# Outbound calls retain their dangerous/non-auto-approved manifest policy.
# Only this reviewed tool/adapter pair may use that policy in the shared runner;
# neither a manifest nor another binding may select the exception by itself.
TRUSTED_PERMISSION_POLICIES = {
    'phone_call': {
        'tool': 'phone_call',
        'adapter': REMOTE_ADAPTER,
        'permissions': {
            'dangerous': True, 'auto_approve': False, 'network': True,
            'bash': False, 'filesystem': True,
        },
    },
}

# This provider observer is an external Python process. Give it only its own
# credential and the runtime paths needed for Stash/HTTPS, not the entire mode
# file (which can contain unrelated provider and Jarvis API credentials).
CHILD_ENVIRONMENT_POLICIES = {
    'convert_file': {
        'always': frozenset({
            'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'JARVIS_MODE',
            'STASH_DIR', 'JARVIS_OVERRIDE_STASH_DIR',
            'STASH_DEFAULT_TTL_DAYS', 'STASH_SOURCE_ARTIFACT_TTL_DAYS', 'STASH_GENERATED_MEDIA_TTL_DAYS',
            'STASH_MAX_SPACE_SIZE_MB', 'STASH_MAX_TOTAL_SIZE_GB',
            'STASH_CLEANUP_MAX_SPACES', 'STASH_CLEANUP_MAX_BYTES_MB',
            'MAGICK_MEMORY_LIMIT', 'MAGICK_MAP_LIMIT', 'MAGICK_DISK_LIMIT', 'MAGICK_THREAD_LIMIT',
            'MAGICK_CONFIGURE_PATH', 'MAGICK_TEMPORARY_PATH',
        }),
        'if_true': {},
    },
    'docling_convert': {
        'always': frozenset({
            'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'JARVIS_MODE',
            'DOCLING_BASE_URL', 'DOCLING_API_KEY', 'DOCLING_API_KEY_HEADER', 'DOCLING_TIMEOUT_SECONDS',
            'STASH_DIR', 'JARVIS_OVERRIDE_STASH_DIR',
            'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
        }),
        'if_true': {},
    },
    'browser_use_cloud': {
        'always': frozenset({
            'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ',
            'JARVIS_MODE', 'BROWSER_USE_API_KEY', 'BROWSER_USE_CLOUD_WORKSPACE_ID',
            'STASH_DIR', 'JARVIS_OVERRIDE_STASH_DIR',
            'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
        }),
        'if_true': {'use_profile': 'BROWSER_USE_CLOUD_PROFILE_ID'},
    },
}

# Media credentials, paths and the optional embedding-backed artifact index.
# This is independent of the foreground manifest's restricted environment.
_VIDEO_CHILD_KEYS = frozenset({
    'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'JARVIS_MODE',
    'VIDEO_TOOL_PROVIDER', 'XAI_API_KEY', 'XAI_VIDEO_MODEL',
    'GEMINI_API_KEY', 'GEMINI_VIDEO_MODEL', 'HEYGEN_API_KEY', 'HEYGEN_VIDEO_MODEL',
    'HEYGEN_WAIT_SECONDS', 'STASH_DIR', 'JARVIS_OVERRIDE_STASH_DIR',
    'STASH_DEFAULT_TTL_DAYS', 'STASH_GENERATED_MEDIA_TTL_DAYS', 'STASH_SOURCE_ARTIFACT_TTL_DAYS',
    'STASH_MAX_SPACE_SIZE_MB', 'STASH_MAX_TOTAL_SIZE_GB',
    'STASH_CLEANUP_MAX_SPACES', 'STASH_CLEANUP_MAX_BYTES_MB',
    'OLLAMA_BASE_URL', 'OLLAMA_EMBEDDING_FALLBACK_URL', 'OLLAMA_EMBEDDING_MODEL',
    'OLLAMA_EMBEDDING_MODEL_DIGEST', 'OLLAMA_EMBEDDING_CONTEXT_WINDOW',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
})
CHILD_ENVIRONMENT_POLICIES['generate_video'] = {'always': _VIDEO_CHILD_KEYS, 'if_true': {}}
_HEYGEN_CHILD_KEYS = frozenset({
    'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'JARVIS_MODE',
    'HEYGEN_API_KEY', 'HEYGEN_WAIT_SECONDS', 'STASH_DIR', 'JARVIS_OVERRIDE_STASH_DIR',
    'STASH_DEFAULT_TTL_DAYS', 'STASH_GENERATED_MEDIA_TTL_DAYS', 'STASH_SOURCE_ARTIFACT_TTL_DAYS',
    'STASH_MAX_SPACE_SIZE_MB', 'STASH_MAX_TOTAL_SIZE_GB',
    'STASH_CLEANUP_MAX_SPACES', 'STASH_CLEANUP_MAX_BYTES_MB',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
})
CHILD_ENVIRONMENT_POLICIES['generate_avatar_video'] = {'always': _HEYGEN_CHILD_KEYS, 'if_true': {}}

_PHONE_CHILD_KEYS = frozenset({
    'PATH', 'PYTHONPATH', 'VIRTUAL_ENV', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'JARVIS_MODE',
    'VAPI_API_KEY', 'VAPI_PHONE_NUMBER_ID', 'VAPI_ASSISTANT_ID', 'VAPI_DEFAULT_PERSONA',
    'VAPI_LLM_PROVIDER', 'VAPI_LLM_MODEL', 'VAPI_LLM_REASONING_EFFORT',
    'VAPI_VOICE_ID', 'VAPI_VOICE_MODEL', 'VAPI_FEMALE_VOICE_ID', 'VAPI_ELEVENLABS_KEY',
    'VAPI_VOICEMAIL_ACTION', 'VAPI_WAIT_FOR_CALL', 'VAPI_WAIT_TIMEOUT', 'OWNER_NAME', 'PHONE_CONTACTS',
    'ELEVENLABS_VOICE_ID', 'ELEVENLABS_TTS_VOICE', 'CANVAS_INTERNAL_URL', 'CANVAS_PUBLIC_URL',
    'STASH_DIR', 'JARVIS_OVERRIDE_STASH_DIR', 'STASH_DEFAULT_TTL_DAYS',
    'STASH_SOURCE_ARTIFACT_TTL_DAYS', 'STASH_GENERATED_MEDIA_TTL_DAYS',
    'STASH_MAX_SPACE_SIZE_MB', 'STASH_MAX_TOTAL_SIZE_GB',
    'STASH_CLEANUP_MAX_SPACES', 'STASH_CLEANUP_MAX_BYTES_MB',
    'OLLAMA_BASE_URL', 'OLLAMA_EMBEDDING_FALLBACK_URL', 'OLLAMA_EMBEDDING_MODEL',
    'OLLAMA_EMBEDDING_MODEL_DIGEST', 'OLLAMA_EMBEDDING_CONTEXT_WINDOW', 'OLLAMA_API_KEY',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
    'LOCAL_PROXY', 'LOCAL_PROXY2', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
    'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
})
CHILD_ENVIRONMENT_POLICIES['phone_call'] = {'always': _PHONE_CHILD_KEYS, 'if_true': {}}


# Craft clients receive their own connection settings and Stash paths only.
# This policy is separate from foreground manifest child_environment.
_CRAFT_CHILD_KEYS = frozenset({
    'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'JARVIS_MODE',
    'CRAFT_API_URL', 'CRAFT_API_KEY', 'CRAFT_CA_BUNDLE', 'CRAFT_WAIT_SECONDS',
    'STASH_DIR', 'JARVIS_OVERRIDE_STASH_DIR',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
})
for _craft_tool in ('craft_image', 'craft_pdf', 'craft_photos', 'craft_video', 'craft_motion'):
    CHILD_ENVIRONMENT_POLICIES[_craft_tool] = {'always': _CRAFT_CHILD_KEYS, 'if_true': {}}


def bindings():
    if sys.platform != 'linux':
        return {}
    from lib.webhook_integrations.private_bindings import bindings as private_bindings

    return {**TRUSTED_BINDINGS, **private_bindings()}


def runner():
    return LocalSkillRunner(
        ROOT,
        {name: adapter for name, adapter in bindings().items() if adapter in SKILL_ADAPTERS},
        child_environment_policies=CHILD_ENVIRONMENT_POLICIES,
        permission_policies=TRUSTED_PERMISSION_POLICIES,
    )


def authorize_tools(selected):
    result = runner().authorize_tools(selected)
    if 'browser_use' in selected and 'browser_use' in bindings():
        from lib.webhook_integrations.browser import policy
        result['browser_use'] = policy()[1]
    from lib.webhook_integrations.private_bindings import bindings as private_bindings
    from lib.webhook_integrations.private_bindings import policy as private_policy

    for name in set(selected) & private_bindings().keys():
        result[name] = private_policy(name)[1]
    if 'apify_run_actor' in selected and 'apify_run_actor' in bindings():
        from .apify import policy as apify_policy
        result['apify_run_actor'] = apify_policy()[1]
    return result


def callback_sources(store):
    from lib.webhook_integrations.browser import callback_sources as browser_sources
    from lib.webhook_integrations.private_bindings import callback_sources as private_sources

    return {**browser_sources(store), **private_sources(store)}


def callback_readiness(store):
    from lib.webhook_integrations.browser import service_ready as browser_ready
    from lib.webhook_integrations.private_bindings import callback_readiness as private_readiness

    return {'browser_use': lambda: browser_ready(store), **private_readiness(store)}


def worker_adapters(store=None):
    # Readiness describes process supervision, not the presence of every skill's
    # optional backend. A missing conversion backend returns a known skill failure.
    adapters = dict.fromkeys(LOCAL_ADAPTERS | {REMOTE_ADAPTER}, runner()) if bindings() else {}
    if bindings().get('apify_run_actor') == 'apify_actor_v1':
        from .apify import worker_adapter
        adapters['apify_actor_v1'] = worker_adapter()
    if adapters and store is not None:
        import json

        from lib.webhook_integrations.browser import prepare as browser_prepare
        from lib.webhook_integrations.private_bindings import parameters as private_parameters
        from lib.webhook_integrations.private_bindings import prepare as private_prepare
        from lib.webhook_integrations.runner import LocalCallbackRunner
        from lib.webhook_integrations.service import IntegrationService

        def callback_bindings():
            sources = callback_sources(store)
            result = {}
            if 'browser_use' in sources:
                result['browser_use'] = (
                    sources['browser_use'],
                    json.loads((ROOT / 'skills/browser_use.tool.json').read_text())['parameters'],
                )
            for name, parameters in private_parameters(store).items():
                result[name] = (sources[name], parameters)
            return result

        def prepare(context):
            if context.claim.job['admission']['tool'] == 'browser_use':
                return browser_prepare(context)
            return private_prepare(context)

        # Advertise the reviewed runner even before an optional source exists.
        # Bindings are loaded at claim time, so guided setup does not require a
        # second worker restart; admission still requires a ready source.
        adapters['http_callback_v1'] = LocalCallbackRunner(
            IntegrationService(store), callback_bindings(), binding_loader=callback_bindings,
            prepare=prepare,
        )
    return adapters
