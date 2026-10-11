"""Reviewed adapters for pinned native releases. No arbitrary command/script API."""
import json
import os
import select
import shutil
import signal
import subprocess
import time
import zipfile
from contextlib import contextmanager

from .images import execute_image
from .titles import create_title
from .videos import execute_video


class Cancelled(RuntimeError):
    pass

class Engine:
    def __init__(self, binary, workspace, check, started, timeout=900, max_bytes=512 * 1024**2):
        self.binary = str(binary)
        self.workspace = workspace
        self.check = check
        self.started = started
        self.deadline = time.monotonic() + timeout
        self.max_bytes = max_bytes
        self.process = None
        self.buffer = b''
        self.error_stream = None
        # Only runtime/render variables; no gateway token or mode-file secrets.
        self.environment = {k: v for k, v in os.environ.items() if k in
                            ('PATH', 'LANG', 'LC_ALL', 'VK_ICD_FILENAMES', 'NVIDIA_VISIBLE_DEVICES', 'NVIDIA_DRIVER_CAPABILITIES')}
        for name, value in {'HOME': workspace / 'home', 'XDG_CONFIG_HOME': workspace / 'home/config',
                            'XDG_CACHE_HOME': workspace / 'home/cache', 'XDG_DATA_HOME': workspace / 'home/data',
                            'TMPDIR': workspace / 'tmp'}.items():
            value.mkdir(parents=True, exist_ok=True)
            self.environment[name] = str(value)
        self.environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')

    def guard(self):
        if self.check():
            raise Cancelled('Cancellation requested')
        if time.monotonic() > self.deadline:
            raise TimeoutError('Engine exceeded the job timeout')
        errors = self.workspace / 'engine-error.log'
        if errors.is_file() and errors.stat().st_size > 2 * 1024**2:
            raise RuntimeError('Native diagnostic log exceeds its 2 MiB limit')
        size = 0
        for path in self.workspace.rglob('*'):
            if path.is_symlink():
                raise ValueError('Engine created a symbolic link in its workspace')
            if path.is_file():
                size += path.stat().st_size
                if size > self.max_bytes:
                    raise ValueError('Job workspace exceeds its disk limit')

    def start(self, args, stdout, *, executable=None):
        if self.process is not None:
            raise RuntimeError('An engine session is already running; finish it before starting another process')
        self.guard()
        self.error_stream = (self.workspace / 'engine-error.log').open('w+b')
        self.process = subprocess.Popen([executable or self.binary, *map(str, args)], cwd=self.workspace,
                                        env=self.environment, stdin=subprocess.PIPE,
                                        stdout=stdout, stderr=self.error_stream, start_new_session=True)
        self.started(self.process.pid)
        return self.process

    def diagnostic(self):
        path = self.workspace / 'engine-error.log'
        if not path.is_file():
            return ''
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 2048))
            return ' '.join(stream.read(2048).decode('utf-8', errors='replace').split())[-800:]

    def stop(self):
        if self.process is None:
            if self.error_stream:
                self.error_stream.close()
                self.error_stream = None
            return
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.process.wait(timeout=10)
        if self.process.stdin:
            self.process.stdin.close()
        if self.process.stdout:
            self.process.stdout.close()
        self.process = None
        if self.error_stream:
            self.error_stream.close()
            self.error_stream = None

    def run(self, *args, executable=None):
        # A file avoids pipe deadlocks; guard bounds it together with outputs.
        log = self.workspace / 'engine-output.log'
        with log.open('w+b') as output:
            process = self.start(args, output, executable=executable)
            try:
                while process.poll() is None:
                    self.guard()
                    time.sleep(.05)
                self.guard()
                output.seek(0)
                result = output.read(2 * 1024**2 + 1)
                if len(result) > 2 * 1024**2:
                    raise RuntimeError('Engine reply exceeds limit')
                if process.returncode:
                    raise RuntimeError(f'Native engine failed (exit {process.returncode}): ' + (self.diagnostic() or result.decode('utf-8', errors='replace')[-800:] or 'no diagnostic supplied'))
                return result.decode('utf-8')
            finally:
                self.stop()

    def rpc(self, request):
        self.process.stdin.write(json.dumps(request).encode() + b'\n')
        self.process.stdin.flush()
        while True:
            self.guard()
            if b'\n' not in self.buffer:
                readable, _, _ = select.select([self.process.stdout], [], [], .1)
                if not readable:
                    if self.process.poll() is not None:
                        raise RuntimeError('Native MCP process ended unexpectedly: ' + self.diagnostic())
                    continue
                block = os.read(self.process.stdout.fileno(), 65536)
                if not block:
                    raise RuntimeError('Native MCP closed its response channel: ' + self.diagnostic())
                self.buffer += block
                if len(self.buffer) > 2 * 1024**2:
                    raise RuntimeError('Native MCP response exceeds limit')
                continue
            line, self.buffer = self.buffer.split(b'\n', 1)
            response = json.loads(line)
            if response.get('id') == request['id']:
                if 'error' in response:
                    raise RuntimeError('Native MCP rejected an operation: ' + str(response['error'])[:800])
                return response['result']

    @contextmanager
    def mcp(self, *args):
        self.buffer = b''
        self.start(['mcp', *args], subprocess.PIPE)
        try:
            self.rpc({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-06-18', 'capabilities': {},
                'clientInfo': {'name': 'jarvis-craft-gateway', 'version': '0.1.0'}}})
            self.process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            self.process.stdin.flush()
            counter = 1
            def call(name, arguments):
                nonlocal counter
                counter += 1
                result = self.rpc({'jsonrpc': '2.0', 'id': counter, 'method': 'tools/call',
                                   'params': {'name': name, 'arguments': arguments}})
                if result.get('isError'):
                    raise RuntimeError('Native MCP action failed: ' + ' '.join(str(item.get('text', '')) for item in result.get('content', []) if item.get('type') == 'text')[:800])
                for item in result.get('content', []):
                    if item.get('type') == 'text':
                        try:
                            return json.loads(item['text'])
                        except ValueError:
                            pass
                return result
            yield call
        finally:
            self.stop()


def execute(engine, operation, inputs):
    """Return (path, role) exports and the actual selected renderer."""
    work = engine.workspace
    op = operation
    exports = []
    if op.app == 'photocraft':
        exports = execute_image(engine, op, inputs)
        renderer = 'cpu'
    elif op.app == 'pdfcraft':
        out = work / ('page.png' if op.action == 'render' else 'document.pdf')
        pages = ','.join(map(str, op.pages))
        if op.action == 'rotate':
            engine.run('edit', inputs[0], '--rotate', f'{pages}:{op.degrees}', '--out', out)
        elif op.action == 'extract':
            engine.run('extract', inputs[0], '--pages', pages, '--out', out)
        elif op.action == 'combine':
            engine.run('combine', *inputs, '--out', out)
        else:
            engine.run('render', inputs[0], '--page', str(op.pages[0]), '--dpi', '96', '--out', out)
        exports = [(out, 'primary')]
        if op.action != 'render':
            engine.run('render', out, '--page', '1', '--dpi', '72', '--out', work / 'preview.png')
            exports.append((work / 'preview.png', 'preview'))
        renderer = 'cpu'
    elif op.app == 'lightcraft':
        engine.run('render', inputs[0], '-o', work / 'photo.png', '--set', f'light.exposure={op.exposure}')
        exports = [(work / 'photo.png', 'primary')]
        renderer = 'cpu'
    elif op.app == 'effectcraft':
        project = work / 'motion.ecproj'
        gpu = ['--gpu'] if op.gpu else []
        with engine.mcp(*gpu) as call:
            metadata = create_title(call, op)
            call('save_project', {'path': str(project)})
            renderer = json.dumps(call('get_project', {}).get('renderer', 'unknown'))
        engine.run('--project', project, 'render-frame', '--time', '0', '--out', work / 'preview.png', *gpu)
        if op.output == 'mp4':
            engine.run('--project', project, 'render', '--out', work / 'motion.mp4', '--format', 'h264', '--audio', 'off', *gpu)
            exports.append((work / 'motion.mp4', 'primary'))
            exports.append((work / 'preview.png', 'preview'))
        else:
            exports.append((work / 'preview.png', 'primary'))
        exports.append((project, 'project'))
        (work / 'document.json').write_text(json.dumps(metadata))
        exports.append((work / 'document.json', 'inspection'))
    else:
        exports = execute_video(engine, op, inputs)
        renderer = 'native-default'
    validate_exports(engine, exports)
    return exports, renderer


def validate_exports(engine, exports):
    """Publish only valid exports, including a fully decoded video, not a header stub."""
    for path, _ in exports:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError('Engine returned without a nonempty output')
        with path.open('rb') as stream:
            header = stream.read(8)
        if path.suffix == '.png' and header != b'\x89PNG\r\n\x1a\n':
            raise RuntimeError('Invalid image output')
        if path.suffix == '.pdf' and not header.startswith(b'%PDF-'):
            raise RuntimeError('Invalid PDF output')
        if path.suffix == '.mp4':
            probe = shutil.which('ffprobe')
            decoder = shutil.which('ffmpeg')
            if not probe or not decoder:
                raise RuntimeError('Video validation requires ffmpeg and ffprobe on the gateway host')
            info = json.loads(engine.run('-v', 'error', '-show_streams', '-show_format', '-of', 'json', path, executable=probe))
            videos = [stream for stream in info.get('streams', []) if stream.get('codec_type') == 'video']
            if (not videos or float(info.get('format', {}).get('duration', 0)) <= 0
                    or any(int(stream.get('width', 0)) <= 0 or int(stream.get('height', 0)) <= 0 for stream in videos)):
                raise RuntimeError('Invalid video output: no timed video stream')
            engine.run('-v', 'error', '-xerror', '-err_detect', 'explode', '-i', path, '-map', '0:v:0',
                       '-f', 'null', '-', executable=decoder)
        if path.suffix == '.zip':
            try:
                with zipfile.ZipFile(path) as archive:
                    if (not {'video.fcproj', 'README.txt'} <= set(archive.namelist())
                            or archive.getinfo('video.fcproj').file_size == 0 or archive.testzip()):
                        raise RuntimeError('Invalid project archive')
            except zipfile.BadZipFile as exc:
                raise RuntimeError('Invalid project archive') from exc
    engine.guard()
