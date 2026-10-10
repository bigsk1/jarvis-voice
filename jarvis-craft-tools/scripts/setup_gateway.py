#!/usr/bin/env python3
"""Repeatable Linux gateway installer. State and credentials stay outside the repo."""
import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import platform
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def private_write(path, content):
    temporary = path.with_name(path.name + '.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    temporary.replace(path)
    path.chmod(0o600)


def certificate(root, host):
    """Generate one persistent private CA and a server certificate with proper SAN."""
    if not shutil.which('openssl'):
        raise RuntimeError('Install openssl first, then rerun setup')
    if not host or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:' for c in host):
        raise ValueError('TLS host must be a hostname or IP address without a port')
    tls = root / 'tls'
    tls.mkdir(mode=0o700, exist_ok=True)
    marker = tls / 'hostname.txt'
    if marker.exists():
        if marker.read_text().strip() != host:
            raise ValueError('Existing TLS identity differs. Use the original --tls-host or a separate --root; do not silently replace client trust')
        valid = subprocess.run(['openssl', 'x509', '-in', str(tls / 'server.crt'), '-checkend', '2592000'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if valid.returncode == 0:
            return tls
    try:
        ipaddress.ip_address(host)
        san = 'IP:' + host
    except ValueError:
        san = 'DNS:' + host
    if not (tls / 'ca.crt').exists() and not (tls / 'ca.key').exists():
        run('openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-days', '3650',
            '-keyout', tls / 'ca.key', '-out', tls / 'ca.crt', '-subj', '/CN=Jarvis Craft Local CA',
            '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        if not (tls / 'ca.crt').is_file() or not (tls / 'ca.key').is_file():
            raise ValueError('Incomplete existing CA; inspect it instead of overwriting client trust')
        run('openssl', 'x509', '-in', tls / 'ca.crt', '-checkend', '31536000', stdout=subprocess.DEVNULL)
    run('openssl', 'req', '-new', '-newkey', 'rsa:3072', '-nodes', '-keyout', tls / 'server.key',
        '-out', tls / 'server.csr', '-subj', '/CN=' + host, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    extensions = tls / 'extensions.txt'
    extensions.write_text('subjectAltName=' + san + '\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
    run('openssl', 'x509', '-req', '-in', tls / 'server.csr', '-CA', tls / 'ca.crt', '-CAkey', tls / 'ca.key',
        '-CAcreateserial', '-days', '365', '-out', tls / 'server.crt', '-extfile', extensions,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    marker.write_text(host + '\n')
    for path in tls.iterdir():
        path.chmod(0o600)
    return tls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'apps/craft-gateway')
    parser.add_argument('--apps-root', type=Path, default=Path.home() / 'apps')
    parser.add_argument('--apps', nargs='+', choices=['photocraft','pdfcraft','lightcraft','filmcraft','effectcraft'], default=['photocraft','pdfcraft','lightcraft','filmcraft','effectcraft'])
    parser.add_argument('--skip-app-install', action='store_true', help='Use existing managed app releases')
    parser.add_argument('--bind', default=None, help='Default 127.0.0.1; non-loopback requires --tls-host')
    parser.add_argument('--port', type=int, default=None, help='Default 19444')
    parser.add_argument('--tls-host', help='Generate private LAN TLS identity for this DNS name or IP')
    parser.add_argument('--unix-socket', type=Path, help='Serve through an existing trusted TLS reverse proxy')
    parser.add_argument('--start', action='store_true', help='Install and start a systemd user service')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64' or sys.version_info < (3,12):
        parser.error('Gateway host requires Linux x86_64 and Python 3.12+; Jarvis clients may run elsewhere')
    if args.port is not None and not 1024 <= args.port <= 65535:
        parser.error('Choose an unprivileged port between 1024 and 65535')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        parser.error('Install ffmpeg (including ffprobe) on the processing host before setup; see README prerequisites')
    os.umask(0o077)
    root = args.root.expanduser().resolve()
    apps_root = args.apps_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    config_path = root / 'gateway.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    config.update(api_key=config.get('api_key') or secrets.token_urlsafe(48),
                  state_dir=str(root / 'state'), apps_root=str(apps_root))
    config['bind'] = args.bind or config.get('bind', '127.0.0.1')
    config['port'] = args.port or config.get('port', 19444)
    if args.unix_socket:
        config['unix_socket'] = str(args.unix_socket.expanduser().resolve())
    if args.tls_host:
        tls = certificate(root, args.tls_host)
        config.update(tls_cert=str(tls / 'server.crt'), tls_key=str(tls / 'server.key'), tls_host=args.tls_host)
    if not config.get('unix_socket') and config['bind'] not in ('127.0.0.1', '::1') and not config.get('tls_cert'):
        parser.error('Remote access requires --tls-host HOST or --unix-socket behind a TLS proxy')
    if not args.skip_app_install:
        run(sys.executable, SOURCE / 'scripts/manage_apps.py', 'install', *args.apps, '--root', apps_root)
    if args.start:
        probe = subprocess.run(['systemctl', '--user', 'show-environment'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode:
            raise RuntimeError('No systemd user manager available. Omit --start and use the foreground command in the README')
    # A release snapshot lets the installed service survive relocating/removing
    # the original Jarvis checkout. Omit tests, caches and all personal files.
    digest = hashlib.sha256()
    files = [SOURCE / 'pyproject.toml', SOURCE / 'requirements.lock.txt', *sorted((SOURCE / 'craft_gateway').glob('*.py'))]
    for path in files:
        digest.update(path.read_bytes())
    code = root / 'releases' / digest.hexdigest()[:16]
    code.mkdir(parents=True, exist_ok=True)
    for path in files:
        target = code / path.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    venv = code / '.venv'
    if not (venv / 'bin/python').exists():
        run(sys.executable, '-m', 'venv', venv)
    run(venv / 'bin/python', '-m', 'pip', 'install', '--require-hashes', '-r', code / 'requirements.lock.txt')
    run(venv / 'bin/python', '-m', 'pip', 'install', '--no-deps', '--no-build-isolation', code)
    run(venv / 'bin/python', '-c', 'from craft_gateway.api import create_app; print("Gateway package import passed")')
    private_write(config_path, json.dumps(config, indent=2) + '\n')
    current = root / 'current'
    if current.exists() and not current.is_symlink():
        raise ValueError('Refusing to replace an unmanaged current directory')
    new = root / '.current-new'
    new.unlink(missing_ok=True)
    new.symlink_to(code.relative_to(root))
    new.replace(current)
    if config.get('unix_socket'):
        url = 'https://YOUR-PROXY-HOST:PORT/craft-api/v1'
    else:
        host = config.get('tls_host') or config['bind']
        host = '[' + host + ']' if ':' in host else host
        url = ('https' if config.get('tls_cert') else 'http') + f'://{host}:{config["port"]}/craft-api/v1'
    hints = f'CRAFT_API_URL="{url}"\nCRAFT_API_KEY="{config["api_key"]}"\n'
    if config.get('tls_host'):
        hints += f'CRAFT_CA_BUNDLE="{root / "tls/ca.crt"}"\n'
    private_write(root / 'jarvis-client.env', hints)
    if args.start:
        units = Path.home() / '.config/systemd/user'
        units.mkdir(parents=True, exist_ok=True)
        # systemd quoting is distinct from shell quoting; paths may contain spaces.
        def quote(value):
            return '"' + str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%') + '"'
        unit = '[Unit]\nDescription=Jarvis Craft Gateway\nAfter=network.target\n\n[Service]\n'
        unit += 'ExecStart=' + quote(current / '.venv/bin/craft-gateway') + ' --config ' + quote(config_path) + '\n'
        unit += 'Restart=on-failure\nRestartSec=3\nUMask=0077\nKillMode=control-group\nTimeoutStopSec=20\nNoNewPrivileges=true\nMemoryMax=6G\nMemorySwapMax=0\nCPUQuota=200%\nTasksMax=256\n\n[Install]\nWantedBy=default.target\n'
        (units / 'jarvis-craft-gateway.service').write_text(unit)
        run('systemctl', '--user', 'daemon-reload')
        run('systemctl', '--user', 'enable', 'jarvis-craft-gateway.service')
        run('systemctl', '--user', 'restart', 'jarvis-craft-gateway.service')
        ready = False
        for _ in range(30):
            connection = None
            try:
                if config.get('unix_socket'):
                    connection = http.client.HTTPConnection('localhost', timeout=2)
                    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    connection.sock.settimeout(2)
                    connection.sock.connect(config['unix_socket'])
                elif config.get('tls_cert'):
                    context = ssl.create_default_context(cafile=str(root / 'tls/ca.crt') if (root / 'tls/ca.crt').exists() else None)
                    connection = http.client.HTTPSConnection(config.get('tls_host') or config['bind'], config['port'], context=context, timeout=2)
                else:
                    connection = http.client.HTTPConnection(config['bind'], config['port'], timeout=2)
                connection.request('GET', '/craft-api/v1/capabilities', headers={'Authorization': 'Bearer ' + config['api_key']})
                response = connection.getresponse()
                if response.status == 200 and json.loads(response.read(2*1024**2)).get('protocol_version') == 1:
                    ready = True
                    break
            except (OSError, ValueError, http.client.HTTPException):
                pass
            finally:
                if connection:
                    connection.close()
            time.sleep(.2)
        if not ready:
            raise RuntimeError('Gateway installed but startup verification failed; inspect systemctl --user status and journalctl before configuring Jarvis')
    print(f'Gateway installed at {root}. Private client settings: {root / "jarvis-client.env"} (not printed).')
    print('Copy those settings securely into the chosen Jarvis mode ENV; for a remote client, copy only the public CA and use its client-side path.')
    if not args.start:
        print(f'Run: {current / ".venv/bin/craft-gateway"} --config {config_path}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
