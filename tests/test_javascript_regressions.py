"""Include standalone core UI regressions in the canonical pytest collection."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUITES = sorted((ROOT / 'tests').rglob('*.test.js'))


@pytest.mark.parametrize('suite', SUITES, ids=lambda suite: str(suite.relative_to(ROOT)))
def test_standalone_javascript_regressions(suite):
    result = subprocess.run(
        ['node', '--test', str(suite)], cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
