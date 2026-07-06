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

const label = {textContent: 'Thinking...'};
const chat = Object.create(global.ChatUI.prototype);
Object.assign(chat, {
  messagesContainer: {
    querySelector: (selector) => selector === '.thinking-label' ? label : null
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
  if (label.textContent !== 'Working...') {
    throw new Error(`Long tool did not switch to Working: ${label.textContent}`);
  }
  chat._markToolFinished(slowTool);
  if (label.textContent !== 'Reviewing results...') {
    throw new Error(`Completed long tool did not review results: ${label.textContent}`);
  }

  chat._resetProcessingPhase();
  label.textContent = 'Thinking...';
  const fastTool = {message_id: 'message-1', tool: 'weather', call_index: 1};
  chat._markToolStarted(fastTool);
  chat._markToolFinished(fastTool);
  await wait(20);
  if (label.textContent !== 'Thinking...') {
    throw new Error(`Fast tool caused label flicker: ${label.textContent}`);
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
