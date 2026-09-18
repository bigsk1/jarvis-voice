"""Trusted production bindings. Adding a compatible tool requires review here."""

import sys
from pathlib import Path

from .local_contract import ADAPTER, LOCAL_ADAPTERS, REMOTE_ADAPTER
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
}


def bindings():
    return dict(TRUSTED_BINDINGS) if sys.platform == 'linux' else {}


def runner():
    return LocalSkillRunner(ROOT, bindings())


def authorize_tools(selected):
    return runner().authorize_tools(selected)


def worker_adapters():
    # Readiness describes process supervision, not the presence of every skill's
    # optional backend. A missing conversion backend returns a known skill failure.
    return dict.fromkeys(LOCAL_ADAPTERS | {REMOTE_ADAPTER}, runner()) if bindings() else {}
