import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
CHAT_SERVER = (ROOT / "jarvis-web/server/sockets/chat.py").read_text()
CHAT_CLIENT = (ROOT / "jarvis-web/client/js/chat.js").read_text()
MAIN_CSS = (ROOT / "jarvis-web/client/css/main.css").read_text()


def test_web_socket_forwards_structured_opencode_progress():
    assert CHAT_SERVER.count("elif event_type == 'tool_progress':") == 2
    assert "'session_id': kwargs.get('session_id')" in CHAT_SERVER
    assert "'opencode_event_type': kwargs.get('opencode_event_type')" in CHAT_SERVER
    assert "'opencode_tool': kwargs.get('opencode_tool')" in CHAT_SERVER


def test_web_client_shows_latest_phase_timeline_and_session_link():
    assert "_updateOpenCodeProgressCard(cardId, data)" in CHAT_CLIENT
    assert "state.progressEvents.slice(-8)" in CHAT_CLIENT
    assert "this.showProgressStatus(data.status)" in CHAT_CLIENT
    assert "Open session: ${state.sessionId}" in CHAT_CLIENT


def test_opencode_session_link_row_matches_tool_card_inset():
    assert ".tool-card-link-row {" in MAIN_CSS
    assert "padding: var(--space-xs) var(--space-md) var(--space-sm);" in MAIN_CSS
    assert ".tool-card-link-row .tool-card-link {" in MAIN_CSS
    assert "color: var(--text-primary);" in MAIN_CSS


def test_web_client_routes_call_index_and_updates_bounded_card_at_runtime():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8');
const chatSource = source.slice(
  source.indexOf('class ChatUI'),
  source.indexOf('// Create global instance')
);
eval(chatSource + '\nglobal.ChatUI = ChatUI;');

const handlers = {};
global.window = {
  location: {protocol: 'http:', hostname: 'browser-host'},
  jarvisSocket: {on: (name, callback) => { handlers[name] = callback; }}
};

const routed = [];
const listenerChat = Object.create(global.ChatUI.prototype);
Object.assign(listenerChat, {
  _updateOpenCodeProgressCard: (cardId, data) => routed.push({cardId, data}),
  showProgressStatus: () => {}
});
listenerChat._setupSocketListeners();
handlers.toolProgress({
  tool: 'opencode',
  call_index: 2,
  status: 'OpenCode: Running tests',
  phase: 'tool'
});
if (routed.length !== 1 || routed[0].cardId !== 'opencode_2') {
  throw new Error(`call_index routed to wrong card: ${JSON.stringify(routed)}`);
}

const statusEl = {textContent: ''};
const bodyEl = {textContent: ''};
let linkRow = null;
const card = {
  querySelector: (selector) => {
    if (selector === '.tool-card-status') return statusEl;
    if (selector === '.tool-card-body') return bodyEl;
    if (selector === '.tool-card-link-row') return linkRow;
    return null;
  },
  insertBefore: (row) => { linkRow = row; }
};
global.document = {
  getElementById: (id) => id === 'tool-card-opencode_2' ? card : null,
  createElement: (tagName) => ({
    tagName,
    className: '',
    appendChild(child) { this.child = child; }
  })
};

const cardChat = Object.create(global.ChatUI.prototype);
Object.assign(cardChat, {
  pendingTools: {opencode_2: {toolName: 'opencode', status: 'pending'}},
  systemConfig: {OPENCODE_BASE_URL: 'http://localhost:4096'}
});
for (let i = 0; i < 10; i += 1) {
  cardChat._updateOpenCodeProgressCard('opencode_2', {
    status: `phase ${i}`,
    phase: 'tool',
    progress: i === 9 ? 50 : null,
    session_id: 'ses_runtime'
  });
}

const state = cardChat.pendingTools.opencode_2;
if (state.progressEvents.length !== 8 || state.progressEvents[0].status !== 'phase 2') {
  throw new Error(`timeline was not bounded correctly: ${JSON.stringify(state)}`);
}
if (statusEl.textContent !== '⏳ 50% phase 9') {
  throw new Error(`latest status was not rendered: ${statusEl.textContent}`);
}
if (!bodyEl.textContent.includes('phase 2') || !bodyEl.textContent.includes('phase 9')) {
  throw new Error(`timeline body is incomplete: ${bodyEl.textContent}`);
}
if (!linkRow || !linkRow.child || !linkRow.child.href.includes('/Lw/session/ses_runtime')) {
  throw new Error('live OpenCode session link was not rendered');
}
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
