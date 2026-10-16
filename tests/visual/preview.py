#!/usr/bin/env python3
"""Serve production UI assets with public sample data, without application backends."""

import argparse
import json
import mimetypes
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jinja2 import Environment, FileSystemLoader

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WEB = ROOT / 'jarvis-web/client'
CLIENTS = {
    'web': WEB,
    'memory': ROOT / 'jarvis-memory/client',
    'intelligence': ROOT / 'jarvis-intelligence/client',
    'canvas': ROOT / 'jarvis-canvas/client/static',
}
PORTS = {'web': 8761, 'memory': 8762, 'intelligence': 8763, 'canvas': 8764}


class PreviewHandler(BaseHTTPRequestHandler):
    """GET-only fixture server; never proxy requests or import production applications."""

    def __init__(self, *args, surface, **kwargs):
        self.surface = surface
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):
        if args and isinstance(args[1], str) and not args[1].startswith('2'):
            super().log_message(fmt, *args)

    def respond(self, body, content_type, status=200):
        body = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        origin = self.headers.get('Origin')
        if origin in {f'http://127.0.0.1:{port}' for port in PORTS.values()}:
            self.send_header('Access-Control-Allow-Origin', origin)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_POST(self):
        self.respond('{"ok":false,"error":"Sample preview is read-only"}',
                     'application/json', 405)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == '/ui-navigation.js':
            config = {'hostname': '127.0.0.1', 'urls': {
                name: f'http://127.0.0.1:{port}' for name, port in PORTS.items()}}
            script = 'window.__jarvisUINavigationConfig = ' + json.dumps(config) + ';\n'
            return self.respond(script + (ROOT / 'lib/static/ui-navigation.js').read_text(),
                                'application/javascript')
        if self.surface == 'web' and path == '/vendor/socket.io.min.js':
            return self.respond((HERE / 'sample-socket.js').read_text(), 'application/javascript')
        if path.startswith('/api/'):
            data = json.loads((HERE / 'fixtures' / f'{self.surface}.json').read_text())
            if self.surface == 'web':
                data.update(json.loads((HERE / 'fixtures/logs.json').read_text()))
            elif self.surface == 'canvas':
                for item in data.get('/api/pages', []):
                    data['/api/pages/' + item['id']] = item
                data.update({key: body for key, body in
                             json.loads((HERE / 'fixtures/web.json').read_text()).items()
                             if key.startswith('/api/pages/')})
            common = {'/api/auth/status': {'ok': True, 'enabled': False},
                      '/api/health': {'ok': True, 'preview': True}}
            data.update(common)
            if path in data:
                return self.respond(json.dumps(data[path]), 'application/json')
            return self.respond(json.dumps({'ok': False, 'error': 'No sample for ' + path}),
                                'application/json', 404)
        if self.surface == 'canvas' and path in ('/', '/index.html'):
            env = Environment(loader=FileSystemLoader(ROOT / 'jarvis-canvas/client/templates'),
                              autoescape=True)
            return self.respond(env.get_template('canvas.html').render(), 'text/html; charset=utf-8')
        if path == '/':
            path = '/index.html'
        elif self.surface == 'web' and path == '/logs':
            path = '/logs.html'
        if self.surface == 'canvas' and path.startswith('/static/'):
            path = path.removeprefix('/static')
        root = CLIENTS[self.surface]
        if path.startswith(('/fonts/', '/assets/')):
            root = WEB
        elif path.startswith('/vendor/') and not (root / path.lstrip('/')).is_file():
            root = WEB
        elif path.startswith('/docs/images/'):
            root = ROOT
        target = (root / path.lstrip('/')).resolve()
        allowed = [root.resolve(), (WEB / 'fonts').resolve(),
                   (WEB / 'assets').resolve(), (WEB / 'vendor').resolve()]
        if not any(target.is_relative_to(folder) for folder in allowed) or not target.is_file():
            return self.respond('Not found', 'text/plain', 404)
        if root == ROOT and not target.is_relative_to(ROOT / 'docs/images'):
            return self.respond('Not found', 'text/plain', 404)
        mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        return self.respond(target.read_bytes(), mime)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    servers = []
    started = []
    try:
        for surface, port in PORTS.items():
            server = ThreadingHTTPServer(('127.0.0.1', port),
                                         partial(PreviewHandler, surface=surface))
            servers.append(server)
        for surface, server in zip(PORTS, servers, strict=True):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            started.append(server)
            print(f'{surface.capitalize():13} http://127.0.0.1:{server.server_port}', flush=True)
        print('Logs          http://127.0.0.1:8761/logs', flush=True)
        print('Public sample data only. No live services, databases or credentials loaded.', flush=True)
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        for server in started:
            server.shutdown()
        for server in servers:
            server.server_close()


if __name__ == '__main__':
    main()
