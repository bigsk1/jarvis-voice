"""Version sync must preserve historical and incidental documentation labels."""

import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('arguments,version', [([], '2.55.8'), (['patch'], '2.55.9')])
@pytest.mark.parametrize('footer_version', ['', ' (v2.55.8)'])
def test_bump_updates_only_the_docs_footer(tmp_path, arguments, version, footer_version):
    scripts = tmp_path / 'bin'
    scripts.mkdir()
    shutil.copyfile(ROOT / 'bin/bump-version', scripts / 'bump-version')
    (tmp_path / 'VERSION').write_text('2.55.8\n')
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion = "2.55.8"\n')
    (tmp_path / 'README.md').write_text('**Current Version:** v2.55.8\n')
    docs = tmp_path / 'docs'
    docs.mkdir()
    old_footer = '**Last Updated:** 2026-09-01' + footer_version
    original = (
        '# Documentation\n\n'
        'Example integration (v1.2.3).\n\n'
        '**2026-07-29 (v2.55.7):** Historical release.\n'
        '**2026-06-27 (v2.54.0):** Earlier release.\n'
        '> **Last Updated:** 2020-01-01 (v1.0.0)\n\n'
        '---\n\n' + old_footer + '\n'
    )
    readme = docs / 'README.md'
    readme.write_text(original)
    # Exercise the real shell script without resolving packages or using the repo.
    fake_uv = scripts / 'uv'
    fake_uv.write_text('#!/bin/sh\nexit 0\n')
    fake_uv.chmod(0o755)
    env = {**os.environ, 'PATH': str(scripts) + os.pathsep + os.environ['PATH']}
    result = subprocess.run(['bash', str(scripts / 'bump-version'), *arguments],
                            env=env, capture_output=True, text=True, timeout=10, check=True)

    assert readme.read_text() == original.replace(
        old_footer, f'**Last Updated:** {date.today().isoformat()} (v{version})')
    assert (tmp_path / 'VERSION').read_text() == version + '\n'
    assert (tmp_path / 'pyproject.toml').read_text() == f'[project]\nversion = "{version}"\n'
    assert (tmp_path / 'README.md').read_text() == f'**Current Version:** v{version}\n'
    assert '[OK] docs/README.md footer' in result.stdout
