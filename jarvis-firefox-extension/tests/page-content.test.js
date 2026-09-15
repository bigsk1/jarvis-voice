import test from 'node:test';
import assert from 'node:assert/strict';
import { capturePageContent, extractPageContent, MAX_PAGE_BYTES } from '../browser/page-content.js';
import { normalizeSource } from '../browser/source.js';

const INLINE = new Set(['SPAN', 'A', 'STRONG', 'EM', 'CODE', 'LABEL', 'SMALL']);

function attach(parent, children) {
  parent.childNodes = children;
  for (const child of children) child.parentNode = parent;
  return parent;
}

function text(value) {
  return { nodeType: 3, nodeValue: value, childNodes: [], parentNode: null };
}

function el(tag, props = {}, children = []) {
  const node = {
    nodeType: 1,
    tagName: String(tag).toUpperCase(),
    hidden: props.hidden === true,
    isContentEditable: props.contenteditable === true || props.contenteditable === '',
    id: props.id || '',
    childNodes: [],
    parentNode: null,
    getAttribute(name) {
      if (name === 'id') return this.id || null;
      if (name === 'role') return props.role ?? null;
      if (name === 'aria-hidden') return props.ariaHidden ?? null;
      if (name === 'contenteditable') {
        if (props.contenteditable === true) return 'true';
        if (props.contenteditable === '') return '';
        if (props.contenteditable === false) return 'false';
        return props.contenteditable ?? null;
      }
      if (name === 'hidden') return this.hidden ? '' : null;
      return Object.hasOwn(props, name) ? String(props[name]) : null;
    },
  };
  return attach(node, children);
}

function selectionFor(nodes, startOffset = 0, endOffset = nodes.at(-1).nodeValue.length) {
  const range = {
    startContainer: nodes[0], startOffset,
    endContainer: nodes.at(-1), endOffset,
    collapsed: false,
    intersectsNode(node) {
      return nodes.some(selected => {
        for (let current = selected; current; current = current.parentNode) {
          if (current === node) return true;
        }
        return false;
      });
    },
  };
  return {rangeCount: 1, getRangeAt: () => range};
}

function mockDocument({ title, url, children, selection = '', styleFor = () => null }) {
  const body = el('body', {}, children);
  if (typeof selection === 'string') {
    const pending = [body];
    let range = null;
    while (selection && pending.length) {
      const node = pending.shift();
      const start = node.nodeType === 3 ? node.nodeValue.indexOf(selection) : -1;
      if (start >= 0) { range = selectionFor([node], start, start + selection.length); break; }
      pending.push(...node.childNodes);
    }
    selection = range;
  }
  return {
    title,
    body,
    defaultView: {
      location: { href: url },
      getSelection: () => selection,
      getComputedStyle(node) {
        const override = styleFor(node);
        if (override) return override;
        const name = String(node.tagName || '').toUpperCase();
        return {
          display: INLINE.has(name) ? 'inline' : 'block',
          visibility: 'visible',
          opacity: '1',
        };
      },
    },
  };
}

function pageDoc(articleText, extras = [], extra = {}) {
  return mockDocument({
    title: extra.title || 'GPU error',
    url: extra.url || 'https://example.test/gpu',
    selection: extra.selection || '',
    styleFor: extra.styleFor,
    children: [
      el('article', {}, [text(articleText)]),
      ...extras,
    ],
  });
}

test('extracts article text, drops form secrets, and records selected text', () => {
  const doc = pageDoc(
    'The Tesla P40 hit a thermal limit during inference.',
    [el('input', {}, [text('super-secret-token')]), el('script', {}, [text('alert(1)')])],
    { selection: 'thermal limit' },
  );
  const result = extractPageContent(doc, { capturedAt: '2026-09-15T12:00:00.000Z' });
  assert.equal(result.empty, false);
  assert.equal(result.title, 'GPU error');
  assert.equal(result.url, 'https://example.test/gpu');
  assert.match(result.markdown, /thermal limit during inference/);
  assert.match(result.markdown, /## Selected text/);
  assert.doesNotMatch(result.markdown, /super-secret-token|alert\(1\)/);
  assert.equal(result.truncated, false);
});

test('live visibility and block boundaries are preserved instead of cloned innerText', () => {
  const hidden = el('span', {}, [text('SECRET_CSS_HIDDEN')]);
  const doc = mockDocument({
    title: 'Worker',
    url: 'https://example.test/worker',
    styleFor(node) {
      if (node === hidden) return { display: 'none', visibility: 'hidden', opacity: '0' };
      const name = String(node.tagName || '').toUpperCase();
      return { display: INLINE.has(name) ? 'inline' : 'block', visibility: 'visible', opacity: '1' };
    },
    children: [
      el('article', {}, [
        el('p', {}, [text('visible line one'), hidden]),
        el('p', {}, [text('visible line two')]),
        el('pre', {}, [text('import os\nprint(os.getcwd())')]),
      ]),
    ],
  });
  const result = extractPageContent(doc);
  assert.doesNotMatch(result.markdown, /SECRET_CSS_HIDDEN/);
  assert.match(result.markdown, /visible line one\n+visible line two/);
  assert.match(result.markdown, /import os\nprint\(os\.getcwd\(\)\)/);
});

test('contenteditable drafts are excluded with form controls', () => {
  const doc = mockDocument({
    title: 'Editor',
    url: 'https://example.test/editor',
    children: [
      el('article', {}, [
        el('p', {}, [text('Published incident notes stay in the capture.')]),
        el('div', { contenteditable: true }, [text('Unsent draft that must not upload')]),
      ]),
    ],
  });
  const result = extractPageContent(doc);
  assert.match(result.markdown, /Published incident notes/);
  assert.doesNotMatch(result.markdown, /Unsent draft that must not upload/);
});

test('discussion pages keep later articles instead of stopping at the first', () => {
  const doc = mockDocument({
    title: 'Outage thread',
    url: 'https://example.test/thread',
    children: [
      el('main', {}, [
        el('article', {}, [text('Opening description of the Saturday outage on the inference host.')]),
        el('article', {}, [text('Comment: the worker failed with CUDA OOM after the batch size change.')]),
      ]),
    ],
  });
  const result = extractPageContent(doc);
  assert.match(result.markdown, /Opening description of the Saturday outage/);
  assert.match(result.markdown, /CUDA OOM after the batch size change/);
});

test('root discovery never promotes landmarks inside excluded parents', () => {
  const exclusions = [
    {hidden: true}, {ariaHidden: 'true'}, {contenteditable: true},
    {display: 'none'}, {opacity: '0'},
  ];
  for (const props of exclusions) {
    for (const [tag, attributes] of [['main', {}], ['article', {}], ['div', {role: 'main'}], ['div', {id: 'content'}]]) {
      const excluded = el('div', props, [el(tag, attributes, [text('EXCLUDED_LANDMARK: private text long enough to be selected as the article.')])]);
      const doc = mockDocument({
        children: [excluded, el('p', {}, [text('VISIBLE_CONTENT: the page the user is actually reading.')])],
        styleFor(node) {
          return node === excluded ? {display: props.display || 'block', visibility: 'visible', opacity: props.opacity || '1'} : null;
        },
      });
      const result = extractPageContent(doc);
      assert.match(result.markdown, /VISIBLE_CONTENT/);
      assert.doesNotMatch(result.markdown, /EXCLUDED_LANDMARK/);
    }
  }
});

test('a hidden ancestor above the body excludes both page and selected text', () => {
  const content = text('This entire document must stay out of the captured source.');
  const doc = mockDocument({children: [el('main', {}, [content])], selection: selectionFor([content])});
  attach(el('html', {hidden: true}), [doc.body]);
  assert.equal(extractPageContent(doc).empty, true);
});

test('closed disclosures expose only the first summary, including during root discovery', () => {
  const hidden = text('CLOSED_CONTENT: an article inside the collapsed disclosure must not become the root.');
  const doc = mockDocument({children: [
    el('details', {}, [
      el('summary', {}, [text('VISIBLE_SUMMARY')]),
      el('summary', {}, [text('SECOND_SUMMARY_HIDDEN')]),
      el('article', {}, [hidden]),
    ]),
    el('p', {}, [text('VISIBLE_CONTENT: additional published text outside the disclosure.')]),
  ], selection: selectionFor([hidden])});
  const result = extractPageContent(doc);
  assert.match(result.markdown, /VISIBLE_SUMMARY/);
  assert.match(result.markdown, /VISIBLE_CONTENT/);
  assert.doesNotMatch(result.markdown, /CLOSED_CONTENT|SECOND_SUMMARY_HIDDEN|## Selected text/);
});

test('open disclosures retain content and summaries can still be selected when closed', () => {
  const summary = text('Selected summary');
  const doc = mockDocument({children: [el('main', {}, [
    el('details', {open: ''}, [el('summary', {}, [text('Open section')]), el('p', {}, [text('OPEN_CONTENT')])]),
    el('details', {}, [el('summary', {}, [summary]), el('p', {}, [text('CLOSED_CONTENT')])]),
  ])], selection: selectionFor([summary])});
  const result = extractPageContent(doc);
  assert.match(result.markdown, /OPEN_CONTENT/);
  assert.match(result.markdown, /## Selected text\n\nSelected summary/);
  assert.doesNotMatch(result.markdown, /CLOSED_CONTENT/);
});

test('selections inside excluded editors and controls never reintroduce drafts', () => {
  for (const [tag, props] of [['div', {contenteditable: true}], ['div', {role: 'textbox'}], ['form', {}], ['textarea', {}]]) {
    const draft = text('SELECTED_UNSENT_DRAFT');
    const doc = mockDocument({children: [el('main', {}, [
      el('p', {}, [text('Published incident notes stay in the capture.')]),
      el(tag, props, [el('span', {}, [draft])]),
    ])], selection: selectionFor([draft])});
    const result = extractPageContent(doc);
    assert.match(result.markdown, /Published incident notes/);
    assert.doesNotMatch(result.markdown, /SELECTED_UNSENT_DRAFT|## Selected text/);
  }
});

test('a selection spanning visible and excluded nodes keeps only the selected visible characters', () => {
  const first = text('prefixHELLO');
  const secret = text('HIDDEN_BETWEEN_ENDPOINTS');
  const draft = text('EDITOR_BETWEEN_ENDPOINTS');
  const last = text('WORLDsuffix');
  const doc = mockDocument({children: [el('main', {}, [
    el('p', {}, [first]), el('div', {hidden: true}, [secret]),
    el('div', {contenteditable: true}, [draft]), el('p', {}, [last]),
  ])], selection: selectionFor([first, secret, draft, last], 6, 5)});
  const result = extractPageContent(doc);
  assert.match(result.markdown, /## Selected text\n\nHELLO WORLD\n/);
  assert.doesNotMatch(result.markdown, /HIDDEN_BETWEEN_ENDPOINTS|EDITOR_BETWEEN_ENDPOINTS/);
});

test('truncates oversized pages under the upload byte budget', () => {
  const doc = pageDoc('word '.repeat(5000), [], { title: 'Long', url: 'https://example.test/long' });
  const result = extractPageContent(doc, { maxBytes: 400, capturedAt: '2026-09-15T12:00:00.000Z' });
  assert.equal(result.truncated, true);
  assert.match(result.markdown, /Truncated: yes/);
  assert.ok(new TextEncoder().encode(result.markdown).length <= 400);
  assert.ok(MAX_PAGE_BYTES < 100 * 1024);
});

test('empty documents are marked empty instead of inventing content', () => {
  const doc = pageDoc('', [], { title: 'Blank', url: 'https://example.test/blank' });
  const result = extractPageContent(doc);
  assert.equal(result.empty, true);
  assert.equal(result.markdown, '');
});

function captureFixture() {
  const tab = { id: 7, windowId: 4, url: 'https://example.com/docs', title: 'Docs', active: true, incognito: false };
  const calls = [];
  const browser = {
    tabs: {
      async get(id) { assert.equal(id, tab.id); return { ...tab }; },
    },
    windows: { async get(id) { return { id, type: 'normal', incognito: false }; } },
    scripting: {
      async executeScript({ target, func, args }) {
        calls.push(['script', target.tabId, args]);
        return [{ result: func(null, args[1]) }];
      },
    },
  };
  return { tab, calls, browser, source: normalizeSource(tab) };
}

test('capturePageContent injects a one-shot reader and freezes the source identity', async () => {
  const f = captureFixture();
  const originalDocument = globalThis.document;
  const originalLocation = globalThis.location;
  const originalSelection = globalThis.getSelection;
  globalThis.document = pageDoc('Use uv to install the project environment.', [], {
    title: 'Docs', url: f.tab.url,
  });
  globalThis.location = { href: f.tab.url };
  globalThis.getSelection = () => '';
  try {
    const page = await capturePageContent(f.browser, f.source, { now: () => '2026-09-15T12:00:00.000Z' });
    assert.equal(page.url, f.tab.url);
    assert.equal(page.filename, 'browser-page.md');
    assert.match(page.markdown, /uv to install/);
    assert.match(page.uploadId, /^[0-9a-f-]{36}$/i);
    assert.deepEqual(f.calls[0].slice(0, 2), ['script', 7]);
  } finally {
    globalThis.document = originalDocument;
    globalThis.location = originalLocation;
    globalThis.getSelection = originalSelection;
  }
});

test('capturePageContent refuses a navigation that happens during the script', async () => {
  const f = captureFixture();
  f.browser.scripting.executeScript = async () => {
    f.tab.url = 'https://example.com/other';
    return [{ result: { title: 'Docs', url: 'https://example.com/docs', markdown: '# Docs\n', empty: false } }];
  };
  await assert.rejects(capturePageContent(f.browser, f.source), /changed or navigated/);
});

test('missing tab access produces the same grant-access error as screenshots', async () => {
  const f = captureFixture();
  f.browser.scripting.executeScript = async () => { throw new Error('Missing host permission'); };
  await assert.rejects(capturePageContent(f.browser, f.source), /toolbar icon or its page menu/);
});

test('document location fragments do not fail source identity after capture', async () => {
  const f = captureFixture();
  const originalDocument = globalThis.document;
  const originalLocation = globalThis.location;
  const originalSelection = globalThis.getSelection;
  globalThis.document = pageDoc('Use uv to install the project environment.', [], {
    title: 'Docs', url: `${f.tab.url}#install`,
  });
  globalThis.location = { href: `${f.tab.url}#install` };
  globalThis.getSelection = () => '';
  try {
    const page = await capturePageContent(f.browser, f.source, { now: () => '2026-09-15T12:00:00.000Z' });
    assert.equal(page.url, f.tab.url);
    assert.match(page.markdown, /#install/);
  } finally {
    globalThis.document = originalDocument;
    globalThis.location = originalLocation;
    globalThis.getSelection = originalSelection;
  }
});
