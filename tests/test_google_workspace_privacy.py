"""Real build archives must exclude Google grants and downloaded OAuth JSON."""

import subprocess
import tarfile
from pathlib import Path

from docker.utils.build import tar

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ['client_secret.json', 'client_secret_123.apps.googleusercontent.com.json',
           'nested/client_secret_456.apps.googleusercontent.com.json',
           'google-workspace/.env', 'google-workspace/client_secret_789.apps.googleusercontent.com.json',
           'google-workspace/data/credentials/dedicated@gmail.com.json', 'google-workspace/data/attachments/private.pdf']
PUBLIC = ['lib/google_workspace.py', 'config/mcp-servers.json', 'config/cloud.env.example']


def test_git_ignore_covers_google_console_download_names():
    result = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'], cwd=ROOT,
                            input='\n'.join(PRIVATE + PUBLIC)+'\n', capture_output=True, text=True, check=True)
    assert set(result.stdout.splitlines()) == set(PRIVATE)


def test_google_service_is_excluded_from_app_archive_and_private_files_from_service_archive(tmp_path):
    service_files = ['google-workspace/Dockerfile', 'google-workspace/entrypoint.py', 'google-workspace/README.md']
    for name in PRIVATE + PUBLIC + service_files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Synthetic secret/context fixture')
    excludes = (ROOT / '.dockerignore').read_text().splitlines()
    with tar(str(tmp_path), exclude=excludes) as archive:
        with tarfile.open(fileobj=archive) as bundle:
            names = set(bundle.getnames())
    assert not names.intersection(PRIVATE + service_files)
    assert set(PUBLIC) <= names
    with tar(str(tmp_path / 'google-workspace'), exclude=(ROOT / 'google-workspace/.dockerignore').read_text().splitlines()) as archive:
        with tarfile.open(fileobj=archive) as bundle:
            assert set(bundle.getnames()) == {'Dockerfile', 'entrypoint.py'}
