"""Latest-response action rail regressions."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = (ROOT / "jarvis-web/client/js/chat.js").read_text()
MAIN_CSS = (ROOT / "jarvis-web/client/css/main.css").read_text()


def test_copy_action_stays_leftmost_and_mobile_friendly():
    action_template = CHAT_JS[
        CHAT_JS.index("actions.innerHTML = `", CHAT_JS.index("_attachMessageResponseActions"))
        : CHAT_JS.index("actions.querySelector('.message-copy-btn')", CHAT_JS.index("_attachMessageResponseActions"))
    ]

    assert (
        action_template.index("message-copy-btn")
        < action_template.index("send-to-canvas-btn")
        < action_template.index('data-reaction="up"')
    )
    assert "Copy latest question and response as Markdown" in action_template
    assert "Send this response to Canvas" in action_template
    assert "@media (hover: none), (pointer: coarse)" in MAIN_CSS
    assert "width: 44px;" in MAIN_CSS
    assert "height: 44px;" in MAIN_CSS


def test_copy_latest_exchange_uses_markdown_and_http_fallback():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8');
const chatSource = source.slice(
  source.indexOf('class ChatUI'),
  source.indexOf('// Create global instance')
);
eval(chatSource + '\nglobal.ChatUI = ChatUI;');

let copiedText = '';
let toastText = '';
global.window = {isSecureContext: false};
Object.defineProperty(global, 'navigator', {
  value: {},
  configurable: true
});
global.Utils = {
  copyTextFallback: (text) => { copiedText = text; },
  toast: (text) => { toastText = text; }
};
global.setTimeout = (callback) => {
  callback();
  return 1;
};

const classes = new Set();
const button = {
  innerHTML: '<svg>copy</svg>',
  title: 'Copy latest question and response as Markdown',
  disabled: false,
  classList: {
    add: (name) => classes.add(name),
    remove: (name) => classes.delete(name)
  },
  setAttribute: () => {}
};

const chat = Object.create(global.ChatUI.prototype);
(async () => {
  await chat._copyLatestExchangeAsMarkdown(
    button,
    'How do I run this?',
    'Use `./bin/start`.\n\n- Then open the Web UI.'
  );
  const expected = '## User\n\nHow do I run this?\n\n## Jarvis\n\nUse `./bin/start`.\n\n- Then open the Web UI.\n';
  if (copiedText !== expected) {
    throw new Error(`Unexpected copied Markdown: ${JSON.stringify(copiedText)}`);
  }
  if (toastText !== 'Copied latest exchange as Markdown') {
    throw new Error(`Unexpected toast: ${toastText}`);
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_copy_latest_exchange_prefers_secure_clipboard():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8');
const chatSource = source.slice(
  source.indexOf('class ChatUI'),
  source.indexOf('// Create global instance')
);
eval(chatSource + '\nglobal.ChatUI = ChatUI;');

let copiedText = '';
global.window = {isSecureContext: true};
Object.defineProperty(global, 'navigator', {
  value: {clipboard: {writeText: async (text) => { copiedText = text; }}},
  configurable: true
});
global.Utils = {
  copyTextFallback: () => { throw new Error('fallback should not run'); },
  toast: () => {}
};
global.setTimeout = (callback) => {
  callback();
  return 1;
};

const button = {
  innerHTML: '<svg>copy</svg>',
  title: 'Copy latest question and response as Markdown',
  disabled: false,
  classList: {add: () => {}, remove: () => {}},
  setAttribute: () => {}
};

const chat = Object.create(global.ChatUI.prototype);
(async () => {
  await chat._copyLatestExchangeAsMarkdown(button, 'Question', 'Answer');
  if (copiedText !== '## User\n\nQuestion\n\n## Jarvis\n\nAnswer\n') {
    throw new Error(`Secure clipboard received unexpected text: ${JSON.stringify(copiedText)}`);
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
