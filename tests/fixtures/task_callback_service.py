"""Separate inert loopback service for the callback gate. Never imports Jarvis storage."""
import argparse
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--control', type=Path, required=True)
    args = parser.parse_args()
    control = args.control
    credential = json.loads((control / 'credential.json').read_text())

    def complete(submission):
        while not (control / 'finish').exists():
            time.sleep(.02)
        body = json.dumps({'schema_version': 1, 'event_id': 'fixture-complete',
                           'job_id': submission['job_id'], 'attempt_id': submission['attempt_id'],
                           'type': 'task.completed', 'result': {'summary': 'The separate HTTP service finished.', 'artifacts': []}}).encode()
        statuses = []
        for _ in range(2):
            timestamp = str(int(time.time()))
            headers = {
                'Content-Type': 'application/json',
                'X-Jarvis-Timestamp': timestamp,
                'X-Jarvis-Task-Capability': submission['callback_capability'],
            }
            if credential['scheme'] == 'bearer':
                headers['Authorization'] = credential['authorization']
            else:
                source_id = urlsplit(submission['callback_url']).path.split('/')[-2]
                signed = timestamp.encode() + b'.' + source_id.encode() + b'.' + body
                headers.update({'X-Jarvis-Key-Id': credential['id'], 'X-Jarvis-Signature':
                                hmac.new(credential['secret'].encode(), signed, hashlib.sha256).hexdigest()})
            request = Request(submission['callback_url'], body, headers=headers)
            with urlopen(request, timeout=5) as response:
                statuses.append(response.status)
        (control / 'callback-status.json').write_text(json.dumps(statuses))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if self.path != '/submit' or not 0 < length <= 65536:
                self.send_error(400)
                return
            submission = json.loads(self.rfile.read(length))
            if not submission['callback_url'].startswith('http://127.0.0.1:') or submission['arguments'] != {}:
                self.send_error(400)
                return
            path = control / 'submissions.jsonl'
            with path.open('a') as handle:
                handle.write(json.dumps({'job_id': submission['job_id'], 'attempt_id': submission['attempt_id']}) + '\n')
            threading.Thread(target=complete, args=(submission,), daemon=True).start()
            response = json.dumps({'remote_id': 'fixture-' + submission['attempt_id']}).encode()
            self.send_response(202)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    (control / 'port').write_text(str(server.server_port))
    server.serve_forever()


if __name__ == '__main__':
    main()
