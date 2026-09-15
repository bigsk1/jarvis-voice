import { mergeImageStageText } from '../core/state.js';

/** Pure presentation rules shared by the panel and its regression tests. */
export const DEFAULT_SCREENSHOT_PROMPT = 'Analyze this screenshot. Explain what is shown and highlight any errors or useful next steps.';
export const DEFAULT_PAGE_PROMPT = 'Review this page. Use the screenshot for layout and the attached page text for the actual content.';
export const DEFAULT_TEXT_PROMPT = 'Review the attached page text and answer from that source.';

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
    && Boolean(String(draftText || '').trim() || state?.draft?.attachment || state?.draft?.page || state?.draft?.context);
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

export function notificationPreferences(preferences = {}) {
  return {
    showBadge: typeof preferences?.showBadge === 'boolean' ? preferences.showBadge : true,
    desktopNotifications: preferences?.desktopNotifications === true,
    notificationPreview: preferences?.notificationPreview === true,
  };
}

export function imageContextHint(context, draftText) {
  const text = String(draftText || '').trim();
  return context?.kind === 'image' && typeof context.url === 'string' && context.url
    && text.includes(context.url) && !text.startsWith('/')
    ? 'Image analysis is ready for this URL.' : '';
}

/** Local typing must survive unrelated progress, capture and connection updates. */
export class DraftBuffer {
  constructor() { this.value = ''; this.dirty = false; }
  edit(value) { this.value = String(value); this.dirty = true; }
  mergeImage(context) { this.edit(mergeImageStageText(this.value, context)); }
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

function listMarker(line) {
  const match = /^( {0,3})([-+*]|\d{1,9}[.)])([ \t]+)(.*)$/.exec(line);
  if (!match) return null;
  return {
    indent: match[1].length,
    ordered: /^\d/.test(match[2]),
    start: Number.parseInt(match[2], 10),
    contentIndent: match[1].length + match[2].length + match[3].length,
    text: match[4],
  };
}

/** A small Markdown subset; all text still goes through safe DOM construction. */
export function messageBlocks(content, depth = 0) {
  const lines = String(content || '').replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let paragraph = [];
  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ type: 'text', text: paragraph.join('\n') });
    paragraph = [];
  };
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { flushParagraph(); index += 1; continue; }
    const fence = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    if (fence) {
      flushParagraph();
      const closing = new RegExp(`^ {0,3}${fence[1][0]}{${fence[1].length},}[ \\t]*$`);
      const code = [];
      index += 1;
      while (index < lines.length && !closing.test(lines[index])) code.push(lines[index++]);
      if (index === lines.length && code.at(-1) === '') code.pop();
      if (index < lines.length) index += 1;
      blocks.push({ type: 'code', language: fence[2].trim().slice(0, 30), text: code.join('\n') });
      continue;
    }
    const heading = /^ {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$/.exec(line);
    if (heading) {
      flushParagraph();
      blocks.push({ type: 'heading', level: heading[1].length, text: (heading[2] || '').replace(/[ \t]+#+[ \t]*$/, '').trimEnd() });
      index += 1;
      continue;
    }
    const marker = listMarker(line);
    // Bound nesting so unusually deep provider output remains readable.
    if (marker && depth < 16) {
      flushParagraph();
      const list = { type: 'list', ordered: marker.ordered, start: marker.ordered ? marker.start : 1, items: [] };
      let item = marker;
      while (item && item.indent === marker.indent && item.ordered === marker.ordered) {
        const itemLines = [item.text];
        index += 1;
        while (index < lines.length) {
          if (!lines[index].trim()) { itemLines.push(''); index += 1; continue; }
          const indent = /^ */.exec(lines[index])[0].length;
          if (indent < item.contentIndent) break;
          itemLines.push(lines[index++].slice(item.contentIndent));
        }
        list.items.push(messageBlocks(itemLines.join('\n'), depth + 1));
        item = listMarker(lines[index] || '');
      }
      blocks.push(list);
      continue;
    }
    paragraph.push(line);
    index += 1;
  }
  flushParagraph();
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
