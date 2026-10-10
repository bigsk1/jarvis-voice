import argparse
import json
import os
from pathlib import Path

import uvicorn

from .api import create_app


def main():
    parser = argparse.ArgumentParser(description='Run the optional Craft Gateway')
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.expanduser().read_text())
    if args.config.stat().st_mode & 0o077:
        parser.error('Gateway config contains a credential and must have mode 600')
    os.umask(0o077)
    app = create_app(config)
    options = {'access_log': False, 'log_level': 'warning', 'timeout_keep_alive': 5,
               'limit_concurrency': 32, 'limit_max_requests': None}
    if config.get('unix_socket'):
        socket = Path(config['unix_socket'])
        socket.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        options['uds'] = str(socket)
    else:
        host = config.get('bind', '127.0.0.1')
        if host not in ('127.0.0.1', '::1') and not config.get('tls_cert'):
            parser.error('Non-loopback listener requires TLS; use a Unix socket behind a trusted TLS proxy instead')
        options.update(host=host, port=config.get('port', 19444))
        if config.get('tls_cert'):
            options.update(ssl_certfile=config['tls_cert'], ssl_keyfile=config['tls_key'])
    uvicorn.run(app, **options)

if __name__ == '__main__':
    main()
