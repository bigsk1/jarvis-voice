"""Inert local-runner proof; copied into a disposable skills directory by tests."""

import json
import os
import resource
import sys
import time
from pathlib import Path

args = json.loads(sys.argv[1])
root = Path(os.environ['FIXTURE_OUTPUT_ROOT'])
root.mkdir(parents=True, exist_ok=True)
with (root / (args['label'] + '.started')).open('x') as started:
    started.write(str(os.getpgrp()))
time.sleep(args.get('delay', 0))
behavior = args.get('behavior', 'success')
if behavior == 'failure':
    print(json.dumps({'ok': False, 'error': 'head\n' + '\\' * 600000 + '\ntail'}))
elif behavior == 'oversized_success':
    print(json.dumps({'ok': True, 'data': 'x' * 1100000}))
else:
    print(json.dumps({'ok': True, 'speech': 'Local probe finished.', 'data': {
        'label': args['label'], 'cwd': os.getcwd(), 'tmpdir': os.environ['TMPDIR'],
        'mode': os.environ['JARVIS_MODE'], 'token': os.environ.get('FIXTURE_TOKEN'),
        'conversation': os.environ.get('JARVIS_WEB_CONVERSATION_ID'),
        'deadline': os.environ['JARVIS_BACKGROUND_DEADLINE'],
        'input_limit': os.environ['JARVIS_BACKGROUND_MAX_INPUT_BYTES'],
        'memory_limit': resource.getrlimit(resource.RLIMIT_AS)[0],
        'file_limit': resource.getrlimit(resource.RLIMIT_FSIZE)[0],
    }}))
