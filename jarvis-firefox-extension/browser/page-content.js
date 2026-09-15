import { resolveSource } from './source.js';

/** Stay under Jarvis Web's 100KB UTF-8 text-upload limit, including metadata. */
export const MAX_PAGE_BYTES = 90 * 1024;

/**
 * Closed over nothing so Firefox can clone it into the tab with executeScript.
 * Walks the live document: a detached clone makes innerText behave like textContent
 * and would include CSS-hidden nodes while collapsing block boundaries.
 * Pass `null` as `doc` to use the page document.
 */
export function extractPageContent(doc, options = {}) {
  const documentRef = doc && typeof doc === 'object' ? doc : globalThis.document;
  if (!documentRef) throw new Error('This page has no readable document.');
  const win = documentRef.defaultView || globalThis;
  const maxBytes = Number.isFinite(options.maxBytes) && options.maxBytes > 0 ? options.maxBytes : 90000;
  const capturedAt = typeof options.capturedAt === 'string' && options.capturedAt
    ? options.capturedAt : new Date().toISOString();
  const locationHref = typeof options.locationHref === 'string' && options.locationHref
    ? options.locationHref : String(win.location?.href || '');
  const utf8Bytes = text => new TextEncoder().encode(text).length;
  const ELEMENT = 1;
  const TEXT = 3;
  const skipTags = new Set([
    'SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'IFRAME', 'OBJECT', 'EMBED',
    'SVG', 'CANVAS', 'INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'FORM', 'LINK',
    'META', 'VIDEO', 'AUDIO', 'PICTURE', 'SOURCE', 'TRACK', 'DIALOG',
  ]);
  const blockTags = new Set([
    'ADDRESS', 'ARTICLE', 'ASIDE', 'BLOCKQUOTE', 'BR', 'DD', 'DETAILS', 'DIV',
    'DL', 'DT', 'FIGCAPTION', 'FIGURE', 'FOOTER', 'H1', 'H2', 'H3', 'H4', 'H5',
    'H6', 'HEADER', 'HR', 'LI', 'MAIN', 'NAV', 'OL', 'P', 'PRE', 'SECTION',
    'SUMMARY', 'TABLE', 'TBODY', 'TD', 'TFOOT', 'TH', 'THEAD', 'TR', 'UL',
  ]);

  const tagName = node => String(node && node.tagName || '').toUpperCase();
  const attr = (node, name) => {
    try { return node.getAttribute?.(name); }
    catch { return null; }
  };
  const isClosedDetails = node => tagName(node) === 'DETAILS'
    && node.open !== true && attr(node, 'open') == null;
  const firstSummary = node => Array.from(node.childNodes || [])
    .find(child => tagName(child) === 'SUMMARY');
  const visitChildren = (node, visit) => {
    // Only the first direct summary is rendered in a closed disclosure.
    if (isClosedDetails(node)) {
      const summary = firstSummary(node);
      if (summary) visit(summary);
      return;
    }
    const kids = node && node.childNodes;
    if (!kids) return;
    const length = kids.length;
    if (typeof length === 'number') {
      for (let index = 0; index < length; index += 1) visit(kids[index]);
    } else {
      for (const child of kids) visit(child);
    }
  };
  const containsNode = (parent, child) => {
    if (!parent || !child) return false;
    if (parent === child) return true;
    if (typeof parent.contains === 'function') {
      try { return parent.contains(child); }
      catch { /* fall through for test doubles */ }
    }
    let node = child;
    while (node) {
      if (node === parent) return true;
      node = node.parentNode;
    }
    return false;
  };
  const computed = node => {
    try { return win.getComputedStyle?.(node) || null; }
    catch { return null; }
  };
  const isSkipped = node => {
    if (!node || node.nodeType === TEXT) return false;
    const name = tagName(node);
    if (skipTags.has(name)) return true;
    if (node.hidden === true) return true;
    const hiddenAttr = attr(node, 'hidden');
    if (hiddenAttr != null) return true;
    if (attr(node, 'aria-hidden') === 'true') return true;
    if (attr(node, 'role') === 'textbox') return true;
    if (node.isContentEditable === true) return true;
    const editable = attr(node, 'contenteditable');
    if (typeof editable === 'string' && editable.toLowerCase() !== 'false') return true;
    const style = computed(node);
    if (style) {
      if (style.display === 'none') return true;
      if (style.visibility === 'hidden' || style.visibility === 'collapse') return true;
      if (style.opacity !== '' && style.opacity != null && Number(style.opacity) === 0) return true;
    }
    return false;
  };
  const hasExcludedAncestor = node => {
    for (let current = node; current; current = current.parentNode) {
      if (isSkipped(current)) return true;
      const parent = current.parentNode;
      if (isClosedDetails(parent) && current !== firstSummary(parent)) return true;
    }
    return false;
  };
  const isBlock = node => {
    const name = tagName(node);
    if (name === 'BR') return true;
    const style = computed(node);
    const display = style && typeof style.display === 'string' ? style.display : '';
    if (display) {
      if (display === 'none' || display === 'contents') return false;
      if (display === 'inline' || display.startsWith('inline-')) return false;
      return true;
    }
    return blockTags.has(name);
  };
  const collect = (root, range = null) => {
    if (hasExcludedAncestor(root)) return '';
    const parts = [];
    const walk = (node, preserve) => {
      if (!node) return;
      if (range && !range.intersectsNode(node)) return;
      const type = node.nodeType;
      if (type === TEXT || type === 4) {
        const raw = String(node.nodeValue || '');
        const start = range?.startContainer === node ? range.startOffset : 0;
        const end = range?.endContainer === node ? range.endOffset : raw.length;
        const value = raw.slice(start, end).replace(/\u00a0/g, ' ');
        parts.push(preserve ? value : value.replace(/\s+/g, ' '));
        return;
      }
      if (type && type !== ELEMENT) return;
      if (isSkipped(node)) return;
      const name = tagName(node);
      if (name === 'BR') {
        parts.push('\n');
        return;
      }
      const keep = preserve || name === 'PRE';
      const block = isBlock(node);
      if (block) parts.push('\n');
      visitChildren(node, child => walk(child, keep));
      if (block) parts.push('\n');
    };
    walk(root, false);
    return parts.join('').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  };
  const findElements = (root, match) => {
    const found = [];
    if (hasExcludedAncestor(root)) return found;
    const walk = node => {
      if (!node || isSkipped(node)) return;
      if (!node.nodeType || node.nodeType === ELEMENT) {
        if (match(node)) found.push(node);
        visitChildren(node, walk);
      }
    };
    walk(root);
    return found;
  };
  const substantial = node => collect(node).length >= 40;

  const title = String(documentRef.title || '').replace(/\s+/g, ' ').trim().slice(0, 300);
  const body = documentRef.body;
  let root = body;
  if (body) {
    const articles = findElements(body, node => tagName(node) === 'ARTICLE').filter(substantial);
    const mains = findElements(body, node => tagName(node) === 'MAIN' || attr(node, 'role') === 'main');
    const named = findElements(body, node => {
      const id = node.id || attr(node, 'id');
      return id === 'content' || id === 'main';
    });
    const main = mains.find(substantial) || mains[0];
    if (articles.length > 1) {
      root = main && articles.every(article => containsNode(main, article)) ? main : body;
    } else if (main && substantial(main)) {
      root = main;
    } else if (articles.length === 1) {
      root = articles[0];
    } else {
      const landmark = named.find(substantial);
      if (landmark) root = landmark;
    }
  }
  const pageText = collect(root);
  // Read selected ranges through the same filtered tree. Selection.toString()
  // can include editable drafts or hidden descendants between visible endpoints.
  const selectedParts = [];
  try {
    const selection = win.getSelection?.();
    for (let index = 0; index < (selection?.rangeCount || 0); index += 1) {
      const range = selection.getRangeAt(index);
      if (!range.collapsed) selectedParts.push(collect(body, range));
    }
  } catch { /* If the selection is unavailable, keep only the readable page. */ }
  const selected = selectedParts.join('\n').replace(/\s+/g, ' ').trim().slice(0, 8000);
  if (!pageText && !selected) {
    return {
      title, url: locationHref, markdown: '', text: '', charCount: 0,
      truncated: false, capturedAt, empty: true,
    };
  }

  const heading = title || 'Captured page';
  const sections = [
    `# ${heading}`,
    '',
    `- URL: ${locationHref || '(unknown)'}`,
    `- Captured: ${capturedAt}`,
  ];
  if (selected) sections.push('', '## Selected text', '', selected);
  if (pageText) sections.push('', '## Page', '', pageText);
  let markdown = `${sections.join('\n').trim()}\n`;
  let truncated = false;
  if (utf8Bytes(markdown) > maxBytes) {
    truncated = true;
    const marker = '- Truncated: yes';
    const budget = Math.max(64, maxBytes - utf8Bytes(`\n${marker}`));
    let low = 0;
    let high = markdown.length;
    while (low < high) {
      const mid = Math.ceil((low + high) / 2);
      if (utf8Bytes(markdown.slice(0, mid)) <= budget) low = mid;
      else high = mid - 1;
    }
    let slice = markdown.slice(0, low);
    const breakAt = Math.max(slice.lastIndexOf('\n\n'), slice.lastIndexOf('\n'), slice.lastIndexOf('. '), slice.lastIndexOf(' '));
    if (breakAt > low * 0.7) slice = slice.slice(0, breakAt);
    const lines = slice.trimEnd().split('\n');
    const capturedLine = lines.findIndex(line => line.startsWith('- Captured:'));
    if (capturedLine >= 0) lines.splice(capturedLine + 1, 0, marker);
    else lines.splice(3, 0, marker);
    markdown = `${lines.join('\n').trim()}\n`;
  }
  return {
    title: heading,
    url: locationHref,
    markdown,
    text: pageText || selected,
    charCount: markdown.length,
    truncated,
    capturedAt,
    empty: false,
  };
}

function validateExtractedPage(payload, source) {
  if (!payload || payload.empty === true || typeof payload.markdown !== 'string' || !payload.markdown.trim()) {
    throw new Error('This page has no readable text. You can still send the screenshot.');
  }
  if (new TextEncoder().encode(payload.markdown).length > 100 * 1024) {
    throw new Error('The captured page text is too large. Capture a shorter page or send a selection.');
  }
  return {
    title: String(payload.title || source.title || 'Captured page').slice(0, 300),
    url: source.url,
    markdown: payload.markdown,
    charCount: Number.isFinite(payload.charCount) ? payload.charCount : payload.markdown.length,
    truncated: payload.truncated === true,
    capturedAt: typeof payload.capturedAt === 'string' ? payload.capturedAt : new Date().toISOString(),
    filename: 'browser-page.md',
    uploadId: crypto.randomUUID(),
    source,
  };
}

/** One-shot isolated read of the selected tab. Sending remains a separate user action. */
export async function capturePageContent(browserApi, source, helpers = {}) {
  if (!source) throw new Error('Select the source tab before capturing.');
  const before = await resolveSource(browserApi, source);
  if (typeof browserApi.scripting?.executeScript !== 'function') {
    throw new Error('Firefox could not read this tab. Reload the Jarvis companion and try again.');
  }
  const capturedAt = (helpers.now || (() => new Date().toISOString()))();
  let results;
  try {
    results = await browserApi.scripting.executeScript({
      target: { tabId: before.tabId },
      func: helpers.extract || extractPageContent,
      args: [null, { maxBytes: helpers.maxBytes || MAX_PAGE_BYTES, capturedAt }],
    });
  } catch {
    throw new Error('Firefox could not read this tab. Click the Jarvis toolbar icon or its page menu to grant access, then try again.');
  }
  const after = await resolveSource(browserApi, before);
  return validateExtractedPage(results?.[0]?.result, after);
}
