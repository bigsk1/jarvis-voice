/** Exercise the shipped classic Logs UI without a server or private log files. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const client = path.join(root, 'jarvis-web/client');
const escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
const decodeHtml = value => value.replaceAll('&quot;', '"').replaceAll('&#39;', "'")
  .replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&');

class Element {
  constructor(document) {
    this.document = document;
    this.dataset = {};
    this.attributes = {};
    this.events = {};
    this.nodes = [];
    this.style = {};
    this.value = '';
    this.textContent = '';
    this.classList = { add() {}, remove() {}, toggle() {} };
    this._html = '';
  }
  set innerHTML(value) {
    this._html = String(value);
    this.nodes = [];
    for (const match of this._html.matchAll(/<button\b([^>]*)>/g)) {
      const node = new Element(this.document);
      for (const attribute of match[1].matchAll(/([\w-]+)="([^"]*)"/g)) {
        const [, name, encoded] = attribute;
        const value = decodeHtml(encoded);
        node.attributes[name] = value;
        if (name === 'class') node.className = value;
        if (name.startsWith('data-')) {
          node.dataset[name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = value;
        }
      }
      this.nodes.push(node);
    }
  }
  get innerHTML() { return this._html; }
  addEventListener(name, callback) { this.events[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  querySelectorAll(selector) {
    return this.nodes.filter(node => selector.split(',').some(part => {
      const classes = [...part.matchAll(/\.([\w-]+)/g)].map(match => match[1]);
      if (!classes.every(name => (node.className || '').split(/\s+/).includes(name))) return false;
      return [...part.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)].every(([, name, value]) => (
        Object.hasOwn(node.attributes, name) && (value === undefined || node.attributes[name] === value)
      ));
    }));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  contains(node) { return this === node || this.nodes.includes(node); }
  focus() { this.document.activeElement = this; }
  click() {
    return this.events.click?.({ target: this, currentTarget: this, preventDefault() {}, stopPropagation() {} });
  }
}

function folder(folderPath, extensions = ['log']) {
  return { path: folderPath, name: folderPath.split('/').at(-1) || 'logs',
    label: folderPath || 'logs', file_count: 1, extensions,
    latest_modified_at: '2026-11-01T12:00:00Z', latest_file: 'latest.log' };
}

function setup({ width = 1400, folders = [], files = {} } = {}) {
  const calls = [];
  let folderPayload = folders;
  const elements = new Map();
  const document = { activeElement: null, body: { dataset: {}, style: {} },
    addEventListener() {}, getElementById: id => elements.get(id) || null };
  for (const match of fs.readFileSync(path.join(client, 'logs.html'), 'utf8').matchAll(/id="([^"]+)"/g)) {
    if (match[1] !== 'logsHudLogo') elements.set(match[1], new Element(document));
  }
  const sandbox = vm.createContext({ document, URLSearchParams, console,
    window: { innerWidth: width, addEventListener() {} },
    Utils: { escapeHtml, debounce: callback => callback, toast() {},
      auth: { async fetch(url) {
        calls.push(url);
        const parsed = new URL(url, 'http://test');
        let data;
        if (parsed.pathname === '/api/logs/folders') data = { folders: folderPayload };
        else if (parsed.pathname === '/api/logs/files') {
          const items = files[parsed.searchParams.get('folder')] || [];
          data = { files: items, total: items.length, has_more: false, next_offset: items.length };
        } else if (parsed.pathname === '/api/logs/content') {
          data = { filename: 'latest.log', view_type: 'text-lines', lines: ['sample line'], has_more: false };
        } else throw new Error(`Unexpected request: ${url}`);
        return { ok: true, json: async () => data };
      } }
    } });
  vm.runInContext(fs.readFileSync(path.join(client, 'js/log-viewer.js'), 'utf8'), sandbox);
  const app = vm.runInContext(`(() => {
    const loadFolders = LogsViewerApp.prototype.loadFolders;
    LogsViewerApp.prototype.loadFolders = () => {};
    const app = new LogsViewerApp();
    LogsViewerApp.prototype.loadFolders = loadFolders;
    return app;
  })()`, sandbox);
  const list = elements.get('folderList');
  const visiblePaths = () => list.querySelectorAll('.folder-card')
    .map(node => node.dataset.folder ?? node.dataset.toggleFolder);
  const button = (selector, folderPath) => list.querySelectorAll(selector)
    .find(node => (node.dataset.folder ?? node.dataset.toggleFolder) === folderPath);
  return { app, calls, elements, document, list, visiblePaths, button,
    setFolders(next) {
      folderPayload = next;
      app.state.folders = next;
      app.state.folderTree = app.buildFolderTree(next);
      app.renderFolders();
    },
    setRemoteFolders(next) { folderPayload = next; },
    filter(value) {
      const input = elements.get('folderFilterInput');
      input.value = value;
      input.events.input({ target: input });
    }
  };
}

const tick = () => new Promise(resolve => setImmediate(resolve));
const fileRequests = state => state.calls.filter(url => url.startsWith('/api/logs/files?'));

test('nested run and dependency directories start beneath collapsed synthetic parents', () => {
  const state = setup();
  assert.equal(state.app.state.selectedFolder, null);
  state.setFolders([folder('tests/run-b'), folder('tools'), folder('tests/run-a'),
    folder('dependency-updates/audit/venv/lib/node_modules/npm')]);
  assert.deepEqual(state.visiblePaths(), ['dependency-updates', 'tests', 'tools']);
  assert.equal(state.button('.folder-card', 'tests').getAttribute('aria-expanded'), 'false');

  state.button('.folder-card', 'tests').click();
  assert.deepEqual(state.visiblePaths(), ['dependency-updates', 'tests', 'tests/run-a', 'tests/run-b', 'tools']);
  assert.equal(state.app.state.selectedFolder, null);
  assert.equal(state.button('.folder-card', 'tests').getAttribute('aria-expanded'), 'true');
  assert.equal(state.calls.length, 0, 'Opening a synthetic parent must not fetch files');
  state.button('.folder-card', 'tests').click();
  assert.deepEqual(state.visiblePaths(), ['dependency-updates', 'tests', 'tools']);
});

test('a branch with its own log files keeps independent expand and open actions', async () => {
  const state = setup();
  state.setFolders([folder('services'), folder('services/archive')]);
  const toggle = state.button('.folder-toggle', 'services');
  assert.ok(toggle, 'A file-bearing branch needs a separate disclosure button');
  toggle.click();
  assert.deepEqual(state.visiblePaths(), ['services', 'services/archive']);
  assert.equal(state.app.state.selectedFolder, null);
  assert.equal(state.calls.length, 0);

  await state.button('[data-folder]', 'services').click();
  await tick();
  assert.equal(state.app.state.selectedFolder, 'services');
  assert.equal(fileRequests(state).length, 1);
  assert.equal(new URL(fileRequests(state)[0], 'http://test').searchParams.get('folder'), 'services');
  assert.ok(state.visiblePaths().includes('services/archive'));
});

test('folder search temporarily reveals nested matches and preserves prior expansion', () => {
  const state = setup();
  state.setFolders([folder('tests/run-a'), folder('tests/run-b'), folder('services'), folder('services/archive')]);
  state.app.toggleFolder('services');
  state.filter('run-b');
  assert.deepEqual(state.visiblePaths(), ['tests', 'tests/run-b']);
  assert.deepEqual([...state.app.state.expandedFolders], ['services']);

  state.filter('');
  assert.deepEqual(state.visiblePaths(), ['services', 'services/archive', 'tests']);
  assert.deepEqual([...state.app.state.expandedFolders], ['services']);
  state.filter('no-such-folder');
  assert.match(state.list.innerHTML, /No matching folders/);
});

test('filtered branches can collapse and reopen while retaining disclosure focus', () => {
  const state = setup();
  state.setFolders([folder('tests/run-a'), folder('tests/run-b'), folder('services'), folder('services/archive')]);
  state.app.toggleFolder('services');
  state.filter('run-b');
  const disclosure = state.button('.folder-card', 'tests');
  disclosure.focus();
  disclosure.click();
  assert.deepEqual(state.visiblePaths(), ['tests']);
  const collapsed = state.button('.folder-card', 'tests');
  assert.equal(collapsed.getAttribute('aria-expanded'), 'false');
  assert.equal(state.document.activeElement, collapsed);
  assert.notEqual(collapsed, disclosure, 'Rerendering restores focus onto the replacement disclosure');
  collapsed.click();
  assert.deepEqual(state.visiblePaths(), ['tests', 'tests/run-b']);
  assert.equal(state.document.activeElement, state.button('.folder-card', 'tests'));
  state.filter('');
  assert.deepEqual(state.visiblePaths(), ['services', 'services/archive', 'tests']);
  assert.deepEqual([...state.app.state.expandedFolders], ['services']);
});

test('mobile synthetic expansion stays in folders until a file-bearing folder is selected', async () => {
  const state = setup({ width: 390, folders: [folder('tests/run-a')] });
  await state.app.loadFolders();
  assert.equal(state.app.state.selectedFolder, null);
  assert.equal(state.document.body.dataset.logsStage, 'folders');
  assert.equal(fileRequests(state).length, 0);

  state.button('.folder-card', 'tests').click();
  assert.equal(state.document.body.dataset.logsStage, 'folders');
  assert.equal(fileRequests(state).length, 0);
  await state.button('[data-folder]', 'tests/run-a').click();
  await tick();
  assert.equal(state.app.state.selectedFolder, 'tests/run-a');
  assert.equal(state.document.body.dataset.logsStage, 'files');
  state.elements.get('backToFoldersBtn').click();
  assert.equal(state.document.body.dataset.logsStage, 'folders');
  assert.ok(state.visiblePaths().includes('tests/run-a'));
});

test('root log files remain selectable and are preferred over nested folders on startup', async () => {
  const state = setup({ width: 390,
    folders: [folder('dependency-updates/audit/venv/lib'), folder(''), folder('services')] });
  await state.app.loadFolders();
  await tick();
  assert.equal(state.app.state.selectedFolder, '');
  assert.equal(new URL(fileRequests(state)[0], 'http://test').searchParams.get('folder'), '');
  assert.ok(state.visiblePaths().includes(''));
  assert.ok(!state.visiblePaths().includes('dependency-updates/audit'));
  state.app._syncResponsiveState();
  assert.equal(state.document.body.dataset.logsStage, 'files', 'An empty root path is still a selected folder');
});

test('startup selects an ordinary top-level log folder without opening nested branches', async () => {
  const state = setup({ folders: [folder('dependency-updates/audit/venv/lib'), folder('services')] });
  await state.app.loadFolders();
  await tick();
  assert.equal(state.app.state.selectedFolder, 'services');
  assert.deepEqual(state.visiblePaths(), ['dependency-updates', 'services']);
});

test('refresh keeps selected content and a manually collapsed ancestor, then clears removed selections', async () => {
  const log = { path: 'tests/run-a/latest.log', filename: 'latest.log', extension: 'log',
    modified_at: '2026-11-01T12:00:00Z', size_label: '12 B', tags: [] };
  const state = setup({ width: 390,
    folders: [folder('services'), folder('tests/run-a')], files: { 'tests/run-a': [log] } });
  await state.app.loadFolders();
  await state.app.selectFolder('tests/run-a');
  await state.app.selectFile(log.path);
  assert.ok(state.app.state.expandedFolders.has('tests'));
  state.app.toggleFolder('tests');
  state.app.state.expandedFolders.add('removed-branch');
  state.setRemoteFolders([folder('services'), folder('tests/run-a'), folder('tests/run-b')]);
  await state.app.loadFolders(true);
  await tick();
  assert.equal(state.app.state.selectedFolder, 'tests/run-a');
  assert.equal(state.app.state.selectedFile, log.path);
  assert.equal(state.app.state.contentPath, log.path);
  assert.ok(!state.app.state.expandedFolders.has('tests'));
  assert.ok(!state.app.state.expandedFolders.has('removed-branch'));
  assert.deepEqual(state.visiblePaths(), ['services', 'tests']);

  state.setRemoteFolders([folder('services'), folder('tests/run-b')]);
  await state.app.loadFolders(true);
  await tick();
  assert.equal(state.app.state.selectedFolder, 'services');
  assert.equal(state.app.state.selectedFile, '');
  assert.equal(state.app.state.contentPath, '');

  state.setRemoteFolders([]);
  await state.app.loadFolders(true);
  assert.equal(state.app.state.selectedFolder, null);
  assert.equal(state.app.state.selectedFile, '');
  assert.equal(state.app.state.contentPath, '');
  assert.equal(state.app.state.files.length, 0);
});

test('nested folder names remain escaped when revealed', () => {
  const state = setup();
  const unsafe = 'tests/<img src=x onerror=alert(1)>';
  state.setFolders([folder(unsafe)]);
  state.app.toggleFolder('tests');
  assert.ok(state.list.innerHTML.includes('&lt;img'));
  assert.ok(!state.list.innerHTML.includes('<img'));
  assert.ok(state.button('[data-folder]', unsafe));
});
