"""Browser lifecycle coverage for file-conversion preview URLs."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_convert_preview_blob_urls_are_revoked_on_replace_and_close():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8');
const chatSource = source.slice(
  source.indexOf('class ChatUI'),
  source.indexOf('// Create global instance')
);
eval(chatSource + '\nglobal.ChatUI = ChatUI;');

const created = [];
const revoked = [];
global.URL = {
  createObjectURL: () => {
    const url = `blob:convert-preview-${created.length + 1}`;
    created.push(url);
    return url;
  },
  revokeObjectURL: (url) => revoked.push(url)
};
global.Utils = {toast: () => {}};
global.document = {
  createElement: () => ({style: {}, controls: false, src: ''}),
  getElementById: () => null
};

const preview = {innerHTML: '', appendChild: () => {}};
const chat = Object.create(global.ChatUI.prototype);
Object.assign(chat, {
  convertModal: {classList: {add: () => {}, remove: () => {}}},
  convertFileName: {textContent: ''},
  convertPreview: preview,
  convertPreviewUrl: null,
  _preselectFormat: () => {},
  _updateFormatDescription: () => {},
  _updateConvertOptions: () => {},
  _resetConvertOptions: () => {}
});

(async () => {
  const first = {name: 'first.mp4', size: 1024, type: 'video/mp4'};
  const second = {name: 'second.mp4', size: 1024, type: 'video/mp4'};
  await chat._showConvertModal(first);
  await chat._showConvertModal(second);

  if (JSON.stringify(revoked) !== JSON.stringify([created[0]])) {
    throw new Error(`replacement did not revoke the first preview: ${JSON.stringify({created, revoked})}`);
  }

  chat._hideConvertModal();
  if (JSON.stringify(revoked) !== JSON.stringify(created)) {
    throw new Error(`close did not revoke the current preview: ${JSON.stringify({created, revoked})}`);
  }
  if (chat.convertPreviewUrl !== null || preview.innerHTML !== '') {
    throw new Error('preview state was not cleared');
  }

  chat._hideConvertModal();
  if (revoked.length !== 2) {
    throw new Error(`cleanup was not idempotent: ${JSON.stringify(revoked)}`);
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
