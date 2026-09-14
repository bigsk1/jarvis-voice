/** Pure presentation rules shared by the panel and its regression tests. */
export const DEFAULT_SCREENSHOT_PROMPT = 'Analyze this screenshot. Explain what is shown and highlight any errors or useful next steps.';

const TERMINAL_RUN_STATUSES = new Set(['completed', 'complete', 'cancelled', 'canceled', 'failed', 'error', 'interrupted', 'idle', 'not_running']);

export function isRunActive(state) {
  if (state?.connection?.status === 'recovering') return true;
  return Boolean(state?.run && !TERMINAL_RUN_STATUSES.has(state.run.status));
}

export function isBusy(state) {
  return isRunActive(state) || Boolean(state?.pendingMode);
}

export function canSend(state, draftText) {
  return state?.connection?.status === 'connected' && !isBusy(state)
    && Boolean(String(draftText || '').trim() || state?.draft?.attachment || state?.draft?.context);
}

export function safeLinkUrl(value) {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}

export function safePreviewUrl(value) {
  // Preview pixels come from the background. Never fetch server content here.
  return typeof value === 'string' && /^data:image\/(?:png|jpeg|webp|gif);base64,[a-z0-9+/=\r\n]+$/i.test(value) ? value : null;
}

export function displayTime(value, withDate = false) {
  if (!value) return '';
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
  if (Number.isNaN(date.getTime())) return '';
  return withDate
    ? date.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    : date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export function noticeText(notice) {
  if (typeof notice === 'string') return notice;
  return notice?.message || notice?.text || '';
}

/** Local typing must survive unrelated progress, capture and connection updates. */
export class DraftBuffer {
  constructor() { this.value = ''; this.dirty = false; }
  edit(value) { this.value = String(value); this.dirty = true; }
  accept(value, force = false) {
    const remote = String(value || '');
    if (force || !this.dirty) { this.value = remote; this.dirty = false; }
    else if (remote === this.value) this.dirty = false;
    return this.value;
  }
  sent(submittedText, serverText = '') {
    // A new draft typed while Send was pending belongs to the next question.
    if (this.value === submittedText) this.accept(serverText, true);
    return this.value;
  }
}

export function messageBlocks(content) {
  const text = String(content || '');
  const blocks = [];
  const fence = /^```([^\n]*)\n([\s\S]*?)(?:^```[ \t]*(?:\n|$)|$)/gm;
  let start = 0;
  for (const match of text.matchAll(fence)) {
    if (match.index > start) blocks.push({ type: 'text', text: text.slice(start, match.index) });
    blocks.push({ type: 'code', language: match[1].trim().slice(0, 30), text: match[2].replace(/\n$/, '') });
    start = match.index + match[0].length;
  }
  if (start < text.length) blocks.push({ type: 'text', text: text.slice(start) });
  return blocks;
}

export function inlineParts(text) {
  const parts = [];
  const pattern = /(`[^`\n]+`)|\[([^\]\n]+)\]\(([^\s)]+)\)|(\*\*([^*\n]+)\*\*)/g;
  let start = 0;
  for (const match of String(text).matchAll(pattern)) {
    if (match.index > start) parts.push({ type: 'text', text: text.slice(start, match.index) });
    if (match[1]) parts.push({ type: 'code', text: match[1].slice(1, -1) });
    else if (match[2]) {
      const href = safeLinkUrl(match[3]);
      parts.push(href ? { type: 'link', text: match[2], href } : { type: 'text', text: match[0] });
    } else parts.push({ type: 'strong', text: match[5] });
    start = match.index + match[0].length;
  }
  if (start < text.length) parts.push({ type: 'text', text: text.slice(start) });
  return parts;
}
