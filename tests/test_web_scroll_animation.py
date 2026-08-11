#!/usr/bin/env python3
"""Regression coverage for the Jarvis Web chat auto-scroll pacing."""

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
UTILS_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "utils.js"


def test_default_chat_scroll_uses_slower_distance_scaled_duration():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(UTILS_JS))}, 'utf8');
const start = source.indexOf('  scrollToBottom(');
const end = source.indexOf('  /**\\n   * Show toast notification', start);
const methodSource = source.slice(start, end).trim().replace(/,$/, '');
const frames = [];
let frameId = 0;
const sandbox = {{
  window: {{ matchMedia: () => ({{ matches: false }}) }},
  performance: {{ now: () => 0 }},
  requestAnimationFrame: callback => {{
    frames.push(callback);
    frameId += 1;
    return frameId;
  }},
  cancelAnimationFrame: () => {{}}
}};
vm.createContext(sandbox);
const utils = vm.runInContext(
  `({{ _scrollAnimations: new WeakMap(), ${{methodSource}} }})`,
  sandbox
);
const element = {{ scrollTop: 0, scrollHeight: 2100, clientHeight: 100 }};

utils.scrollToBottom(element);
if (frames.length !== 1) process.exit(2);

// A 2,000 px trip now takes 2,200 ms. At the old 1,600 ms duration it must
// still be moving, then land exactly at the target at the new duration.
frames.shift()(1600);
if (!(element.scrollTop > 0 && element.scrollTop < 2000)) process.exit(3);
if (frames.length !== 1) process.exit(4);
frames.shift()(2200);
if (element.scrollTop !== 2000) process.exit(5);
if (frames.length !== 0) process.exit(6);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_scroll_duration_override_and_reduced_motion_remain_immediate_contracts():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(UTILS_JS))}, 'utf8');
const start = source.indexOf('  scrollToBottom(');
const end = source.indexOf('  /**\\n   * Show toast notification', start);
const methodSource = source.slice(start, end).trim().replace(/,$/, '');
const frames = [];
let reducedMotion = false;
const sandbox = {{
  window: {{ matchMedia: () => ({{ matches: reducedMotion }}) }},
  performance: {{ now: () => 0 }},
  requestAnimationFrame: callback => {{ frames.push(callback); return frames.length; }},
  cancelAnimationFrame: () => {{}}
}};
vm.createContext(sandbox);
const utils = vm.runInContext(
  `({{ _scrollAnimations: new WeakMap(), ${{methodSource}} }})`,
  sandbox
);

const overridden = {{ scrollTop: 0, scrollHeight: 1100, clientHeight: 100 }};
utils.scrollToBottom(overridden, true, {{ duration: 400 }});
frames.shift()(400);
if (overridden.scrollTop !== 1000) process.exit(2);

reducedMotion = true;
const reduced = {{ scrollTop: 0, scrollHeight: 1100, clientHeight: 100 }};
utils.scrollToBottom(reduced);
if (reduced.scrollTop !== 1000) process.exit(3);
if (frames.length !== 0) process.exit(4);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)
