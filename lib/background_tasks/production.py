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
    'browser_use': 'http_callback_v1',
}


def bindings():
    return dict(TRUSTED_BINDINGS) if sys.platform == 'linux' else {}


def runner():
    return LocalSkillRunner(ROOT, {name: adapter for name, adapter in bindings().items() if adapter in SKILL_ADAPTERS})


def authorize_tools(selected):
    result = runner().authorize_tools(selected)
    if 'browser_use' in selected and 'browser_use' in bindings():
        from lib.webhook_integrations.browser import policy
        result['browser_use'] = policy()[1]
    return result


def worker_adapters(store=None):
    # Readiness describes process supervision, not the presence of every skill's
    # optional backend. A missing conversion backend returns a known skill failure.
    adapters = dict.fromkeys(LOCAL_ADAPTERS | {REMOTE_ADAPTER}, runner()) if bindings() else {}
    if adapters and store is not None:
        import json

        from lib.webhook_integrations.browser import callback_sources as browser_sources, prepare as browser_prepare
        from lib.webhook_integrations.runner import LocalCallbackRunner
        from lib.webhook_integrations.service import IntegrationService

        def callback_bindings():
            sources = browser_sources(store)
            return {
                name: (source, json.loads((ROOT / f'skills/{name}.tool.json').read_text())['parameters'])
                for name, source in sources.items()
            }

        # Advertise the reviewed runner even before an optional source exists.
        # Bindings are loaded at claim time, so guided setup does not require a
        # second worker restart; admission still requires a ready source.
        adapters['http_callback_v1'] = LocalCallbackRunner(
            IntegrationService(store), callback_bindings(), binding_loader=callback_bindings,
            prepare={'browser_use': browser_prepare},
        )
    return adapters
