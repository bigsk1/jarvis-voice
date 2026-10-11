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
    'generate_music': REMOTE_ADAPTER,
    'create_social_clip': REMOTE_ADAPTER,
    'craft_image': REMOTE_ADAPTER,
    'craft_pdf': REMOTE_ADAPTER,
    'craft_photos': REMOTE_ADAPTER,
    'craft_video': REMOTE_ADAPTER,
    'craft_motion': REMOTE_ADAPTER,
    'docling_convert': REMOTE_ADAPTER,
    'browser_use_cloud': REMOTE_ADAPTER,
    'browser_use': 'http_callback_v1',
}

# This provider observer is an external Python process. Give it only its own
# credential and the runtime paths needed for Stash/HTTPS, not the entire mode
# file (which can contain unrelated provider and Jarvis API credentials).
CHILD_ENVIRONMENT_POLICIES = {
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
    )


def authorize_tools(selected):
    result = runner().authorize_tools(selected)
    if 'browser_use' in selected and 'browser_use' in bindings():
        from lib.webhook_integrations.browser import policy
        result['browser_use'] = policy()[1]
    from lib.webhook_integrations.private_bindings import bindings as private_bindings, policy as private_policy

    for name in set(selected) & private_bindings().keys():
        result[name] = private_policy(name)[1]
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
    if adapters and store is not None:
        import json

        from lib.webhook_integrations.browser import prepare as browser_prepare
        from lib.webhook_integrations.private_bindings import parameters as private_parameters, prepare as private_prepare
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
