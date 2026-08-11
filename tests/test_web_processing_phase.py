"""Jarvis Web processing-label lifecycle regressions."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_processing_label_debounces_fast_tools_and_reviews_long_tool_results():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8');
const chatSource = source.slice(
  source.indexOf('class ChatUI'),
  source.indexOf('// Create global instance')
);
eval(chatSource + '\nglobal.ChatUI = ChatUI;');

const label = {textContent: 'Thinking'};
const indicator = {dataset: {phase: 'thinking'}};
const chat = Object.create(global.ChatUI.prototype);
Object.assign(chat, {
  messagesContainer: {
    querySelector: (selector) => {
      if (selector === '.thinking-label') return label;
      if (selector === '.thinking-indicator') return indicator;
      return null;
    }
  },
  currentMessageId: 'message-1',
  activeToolCalls: new Set(),
  processingPhaseDelayMs: 10,
  _workingLabelTimer: null,
  _workingLabelVisible: false
});

const wait = (milliseconds) => new Promise(resolve => setTimeout(resolve, milliseconds));

(async () => {
  const slowTool = {message_id: 'message-1', tool: 'create_social_clip', call_index: 0};
  chat._markToolStarted(slowTool);
  await wait(20);
  if (label.textContent !== 'Working' || indicator.dataset.phase !== 'working') {
    throw new Error(`Long tool did not switch to Working: ${label.textContent}`);
  }
  chat._markToolFinished(slowTool);
  if (label.textContent !== 'Reviewing results' || indicator.dataset.phase !== 'reviewing') {
    throw new Error(`Completed long tool did not review results: ${label.textContent}`);
  }

  chat._resetProcessingPhase();
  label.textContent = 'Thinking';
  indicator.dataset.phase = 'thinking';
  const fastTool = {message_id: 'message-1', tool: 'weather', call_index: 1};
  chat._markToolStarted(fastTool);
  chat._markToolFinished(fastTool);
  await wait(20);
  if (label.textContent !== 'Thinking' || indicator.dataset.phase !== 'thinking') {
    throw new Error(`Fast tool caused label flicker: ${label.textContent}`);
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_processing_indicator_uses_local_inline_signal_core_with_reduced_motion():
    chat_source = (ROOT / "jarvis-web/client/js/chat.js").read_text(encoding="utf-8")
    css_source = (ROOT / "jarvis-web/client/css/main.css").read_text(encoding="utf-8")

    assert 'class="processing-glyph"' in chat_source
    assert 'data-phase="thinking"' in chat_source
    assert '<span class="thinking-label">Thinking</span>' in chat_source
    assert "thinking-dots" not in chat_source
    assert 'data-phase="working"' in css_source
    assert 'data-phase="reviewing"' in css_source
    assert "signal-core-review-scan" in css_source
    assert "@media (prefers-reduced-motion: reduce)" in css_source
