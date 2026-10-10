"""Installer trust, credential-file handling and release failure isolation."""
import importlib.util
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

def script(name):
    spec=importlib.util.spec_from_file_location('craft_'+name,ROOT/'scripts'/ (name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_attack_rejected_before_any_write(tmp_path):
    manage=script('manage_apps')
    archive=tmp_path/'unsafe.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        good=tarfile.TarInfo('package/bin/app')
        good.size=2
        tar.addfile(good,io.BytesIO(b'ok'))
        evil=tarfile.TarInfo('package/../../escape')
        evil.size=3
        tar.addfile(evil,io.BytesIO(b'bad'))
    target=tmp_path/'staging'
    target.mkdir()
    with pytest.raises(ValueError):
        manage.extract_package(archive,target)
    assert not list(target.iterdir()) and not (tmp_path/'escape').exists()


def test_failed_candidate_preserves_selected_binary(tmp_path,monkeypatch):
    manage=script('manage_apps')
    directory=tmp_path/'photocraft'
    previous=directory/'releases/v0.5.0'
    previous.mkdir(parents=True)
    (directory/'current').symlink_to('releases/v0.5.0')
    archive=tmp_path/'candidate.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        item=tarfile.TarInfo('package/bin/photocraft-cli')
        item.size=2
        tar.addfile(item,io.BytesIO(b'ok'))
    monkeypatch.setattr(manage,'package_path',lambda *args:archive)
    def failed(*args):
        raise RuntimeError('Candidate failed workflow')
    monkeypatch.setattr(manage,'smoke',failed)
    with pytest.raises(RuntimeError):
        manage.install('photocraft',tmp_path,{'version':'v0.6.0'},tmp_path/'cache')
    assert (directory/'current').resolve()==previous
    assert not (directory/'releases/v0.6.0').exists()


def test_lan_certificate_has_ip_san_and_preserves_ca(tmp_path):
    setup=script('setup_gateway')
    first=setup.certificate(tmp_path,'127.0.0.1')
    ca=(first/'ca.crt').read_bytes()
    server=(first/'server.crt').read_bytes()
    setup.certificate(tmp_path,'127.0.0.1')
    assert (first/'ca.crt').read_bytes()==ca and (first/'server.crt').read_bytes()==server
    text=subprocess.check_output(['openssl','x509','-in',str(first/'server.crt'),'-text','-noout'],text=True)
    assert 'IP Address:127.0.0.1' in text
    subprocess.run(['openssl','verify','-CAfile',str(first/'ca.crt'),str(first/'server.crt')],check=True,capture_output=True)
    with pytest.raises(ValueError):
        setup.certificate(tmp_path,'different-host.example')
    assert (first/'ca.crt').read_bytes()==ca


def test_private_settings_remain_private(tmp_path):
    setup=script('setup_gateway')
    target=tmp_path/'settings.json'
    setup.private_write(target,json.dumps({'api_key':'fixture-only'}))
    assert target.stat().st_mode & 0o777==0o600
    setup.private_write(target,json.dumps({'api_key':'replacement'}))
    assert json.loads(target.read_text())['api_key']=='replacement'
