import test from 'node:test';
import assert from 'node:assert/strict';
import { captureSource, scaledDimensions } from '../browser/capture.js';
import { normalizeSource, resolveCurrentSource, resolveSource } from '../browser/source.js';

function fixture() {
  const tab = { id: 7, windowId: 4, url: 'https://example.com/error', title: 'Error', active: true, incognito: false };
  const calls = [];
  const browser = {
    tabs: {
      async get(id) { assert.equal(id, tab.id); return { ...tab }; },
      async query(query) { calls.push(['query', query]); return [{ ...tab }]; },
      async captureVisibleTab(windowId, options) { calls.push(['capture', windowId, options]); return 'data:image/png;base64,capture'; },
    },
    windows: {
      async get(id) { return { id, type: 'normal', incognito: false }; },
      async getLastFocused(options) { calls.push(['lastFocused', options]); return { id: tab.windowId, type: 'normal' }; },
    },
  };
  const canvas = {
    getContext() { return { fillRect(...args) { calls.push(['fill', ...args]); }, drawImage(...args) { calls.push(['draw', ...args]); } }; },
    toDataURL(...args) { calls.push(['encode', ...args]); return 'data:image/jpeg;base64,preview'; },
  };
  const helpers = {
    async decodeImage(dataUrl) { assert.equal(dataUrl, 'data:image/png;base64,capture'); return { naturalWidth: 3840, naturalHeight: 2160 }; },
    createCanvas() { return canvas; },
    now() { return '2026-09-14T12:00:00.000Z'; },
  };
  return { tab, calls, browser, helpers, canvas, source: normalizeSource(tab) };
}

test('captures the stored browser window and stages a capped JPEG with current source metadata', async () => {
  const f = fixture();
  f.tab.title = 'Current title';
  const result = await captureSource(f.browser, f.source, f.helpers);
  assert.deepEqual(result, {
    previewUrl: 'data:image/jpeg;base64,preview', width: 1024, height: 576,
    source: { ...f.source, title: 'Current title' }, capturedAt: '2026-09-14T12:00:00.000Z',
  });
  assert.deepEqual(f.calls.find(call => call[0] === 'capture'), ['capture', 4, { format: 'png' }]);
  assert.deepEqual(f.calls.find(call => call[0] === 'encode'), ['encode', 'image/jpeg', 0.85]);
  assert.equal(f.canvas.width, 1024);
  assert.equal(f.canvas.height, 576);
});

test('preserves aspect ratio, caps portrait captures, and never upscales', () => {
  assert.deepEqual(scaledDimensions(2000, 4000), { width: 512, height: 1024 });
  assert.deepEqual(scaledDimensions(800, 600), { width: 800, height: 600 });
  assert.deepEqual(scaledDimensions(1, 4000), { width: 1, height: 1024 });
  for (const width of [0, -1, NaN, Infinity]) assert.throws(() => scaledDimensions(width, 600), /invalid dimensions/);
});

test('rejects private tabs and privileged pages before screenshot access', async () => {
  for (const changes of [{ incognito: true }, { url: 'moz-extension://jarvis/ui/chat.html' }, { url: 'about:config' }, { url: 'file:///tmp/private.txt' }]) {
    const f = fixture();
    Object.assign(f.tab, changes);
    await assert.rejects(captureSource(f.browser, f.source, f.helpers), /Private|HTTP or HTTPS/);
    assert.equal(f.calls.filter(call => call[0] === 'capture').length, 0);
  }
});

test('never switches to another tab after the selected source closes, navigates, or loses activation', async () => {
  for (const mutate of [
    f => { f.browser.tabs.get = async () => { throw new Error('Invalid tab ID'); }; },
    f => { f.tab.url = 'https://example.com/other'; },
    f => { f.tab.active = false; },
    f => { f.tab.windowId = 9; },
    f => { f.tab.pendingUrl = 'https://example.com/loading'; },
  ]) {
    const f = fixture();
    mutate(f);
    await assert.rejects(captureSource(f.browser, f.source, f.helpers), /closed|changed|active|navigating/);
    assert.equal(f.calls.filter(call => call[0] === 'capture').length, 0);
    assert.equal(f.calls.filter(call => call[0] === 'query').length, 0);
  }
});

test('discards screenshot if source tab changes during the capture promise', async () => {
  for (const mutate of [tab => { tab.url = 'https://example.com/new'; }, tab => { tab.active = false; }, tab => { tab.incognito = true; }]) {
    const f = fixture();
    f.browser.tabs.captureVisibleTab = async () => { mutate(f.tab); return 'data:image/png;base64,capture'; };
    let decoded = false;
    f.helpers.decodeImage = async () => { decoded = true; return { width: 800, height: 600 }; };
    await assert.rejects(captureSource(f.browser, f.source, f.helpers), /changed|active|Private/);
    assert.equal(decoded, false);
  }
});

test('permission loss surfaces an actionable error and produces no preview', async () => {
  const f = fixture();
  f.browser.tabs.captureVisibleTab = async () => { throw new Error('Missing activeTab permission'); };
  await assert.rejects(captureSource(f.browser, f.source, f.helpers), /toolbar icon or its page menu/);
  assert.equal(f.calls.some(call => call[0] === 'encode'), false);
});

test('fallback source selection explicitly chooses a normal browser window', async () => {
  const f = fixture();
  assert.deepEqual(await resolveSource(f.browser), f.source);
  assert.deepEqual(f.calls[0], ['lastFocused', undefined]);
  assert.deepEqual(f.calls[1], ['query', { active: true, windowId: 4 }]);
  f.browser.windows.get = async id => ({ id, type: 'popup' });
  await assert.rejects(resolveSource(f.browser, f.source), /normal browser window/);
});

test('capture requires an explicit source and rejects unreadable source metadata', async () => {
  const f = fixture();
  await assert.rejects(captureSource(f.browser, null, f.helpers), /Select the source tab/);
  delete f.tab.url;
  await assert.rejects(captureSource(f.browser, f.source, f.helpers), /Click the Jarvis toolbar icon on that webpage/);
});

test('a new sidebar capture selects the current tab instead of a previously selected tab', async () => {
  const f = fixture();
  Object.assign(f.tab, { id: 8, url: 'https://example.com/current', title: 'Current tab' });
  const source = await resolveCurrentSource(f.browser, 4);
  const result = await captureSource(f.browser, source, f.helpers);
  assert.equal(result.source.tabId, 8);
  assert.equal(result.source.url, 'https://example.com/current');
  assert.deepEqual(f.calls.filter(call => call[0] === 'query'), [['query', { active: true, windowId: 4 }]]);
  assert.equal(f.calls.some(call => call[0] === 'lastFocused'), false);
  assert.equal(f.source.tabId, 7);
});

test('a new capture accepts completed navigation and freezes the new page identity', async () => {
  const f = fixture();
  f.tab.url = 'https://example.com/next';
  f.tab.title = 'Next page';
  const source = await resolveCurrentSource(f.browser, 4);
  assert.deepEqual(source, { ...f.source, url: f.tab.url, title: 'Next page' });
  const result = await captureSource(f.browser, source, f.helpers);
  assert.deepEqual(result.source, source);
  f.tab.url = 'https://example.com/later';
  await assert.rejects(captureSource(f.browser, source, f.helpers), /changed or navigated/);
  assert.equal(source.url, 'https://example.com/next');
});

test('sidebar window preference wins over another most recently focused window', async () => {
  const f = fixture();
  f.browser.windows.getLastFocused = async () => { throw new Error('The detached window must not be queried'); };
  assert.deepEqual(await resolveCurrentSource(f.browser, 4), f.source);
  assert.deepEqual(f.calls, [['query', { active: true, windowId: 4 }]]);
});

test('detached capture freshly selects the most recent normal window', async () => {
  const f = fixture();
  f.tab.windowId = 12;
  const source = await resolveCurrentSource(f.browser);
  assert.equal(source.windowId, 12);
  assert.deepEqual(f.calls[0], ['lastFocused', undefined]);
  assert.deepEqual(f.calls[1], ['query', { active: true, windowId: 12 }]);
});

test('detached capture finds the sole normal window when the pop-out is focused', async () => {
  const f = fixture();
  f.browser.windows.getLastFocused = async options => {
    assert.equal(options, undefined);
    return { id: 99, type: 'popup', focused: true };
  };
  f.browser.windows.getAll = async options => {
    assert.deepEqual(options, { windowTypes: ['normal'] });
    return [{ id: 99, type: 'popup' }, { id: 4, type: 'normal' }];
  };
  assert.deepEqual(await resolveCurrentSource(f.browser), f.source);
  assert.deepEqual(f.calls, [['query', { active: true, windowId: 4 }]]);
});

test('detached capture uses the remembered normal window among multiple candidates', async () => {
  const f = fixture();
  f.tab.windowId = 8;
  f.browser.windows.getLastFocused = async () => ({ id: 99, type: 'popup' });
  f.browser.windows.getAll = async () => [{ id: 4, type: 'normal' }, { id: 8, type: 'normal' }];
  assert.equal((await resolveCurrentSource(f.browser, null, 8)).windowId, 8);
  assert.deepEqual(f.calls, [['query', { active: true, windowId: 8 }]]);
});

test('detached capture never guesses among multiple normal windows without a valid remembered choice', async () => {
  const f = fixture();
  f.browser.windows.getLastFocused = async () => ({ id: 99, type: 'popup' });
  f.browser.windows.getAll = async () => [{ id: 4, type: 'normal' }, { id: 8, type: 'normal' }];
  for (const rememberedWindowId of [null, 123, 99]) {
    await assert.rejects(resolveCurrentSource(f.browser, null, rememberedWindowId), /clicking its Jarvis toolbar icon/);
  }
  assert.deepEqual(f.calls, []);
});

test('detached capture rejects a minimized remembered window instead of selecting another candidate', async () => {
  const f = fixture();
  f.browser.windows.getLastFocused = async () => ({ id: 99, type: 'popup' });
  f.browser.windows.getAll = async () => [{ id: 4, type: 'normal', state: 'minimized' }, { id: 8, type: 'normal' }];
  await assert.rejects(resolveCurrentSource(f.browser, null, 4), /Restore the browser window/);
  assert.deepEqual(f.calls, []);
});

test('closed or unsupported preferred windows never fall back to another window', async () => {
  for (const window of [null, { type: 'popup' }, { type: 'normal', incognito: true }, { type: 'normal', state: 'minimized' }]) {
    const f = fixture();
    f.browser.windows.get = async id => {
      if (!window) throw new Error('Invalid window ID');
      return { id, ...window };
    };
    await assert.rejects(resolveCurrentSource(f.browser, 4), /closed|normal browser window|Minimized/);
    assert.deepEqual(f.calls, []);
    await assert.rejects(captureSource(f.browser, f.source, f.helpers), /closed|normal browser window|Minimized/);
    assert.deepEqual(f.calls, []);
  }
});

test('a missing normal window or active tab fails without screenshot access', async () => {
  const f = fixture();
  f.browser.windows.getLastFocused = async () => { throw new Error('No browser window'); };
  await assert.rejects(resolveCurrentSource(f.browser), /Open a normal Firefox window/);
  for (const tabs of [[], [{ ...f.tab, windowId: 99 }], [f.tab, f.tab]]) {
    f.browser.tabs.query = async () => tabs;
    await assert.rejects(resolveCurrentSource(f.browser, 4), /active browser tab in this window/);
  }
  assert.deepEqual(f.calls, []);
});

test('fresh selection rejects tabs that close, navigate, or deactivate during resolution', async () => {
  for (const mutate of [
    f => { f.browser.tabs.get = async () => { throw new Error('Invalid tab ID'); }; },
    f => { f.tab.url = 'https://example.com/navigated'; },
    f => { f.tab.active = false; },
  ]) {
    const f = fixture();
    f.browser.tabs.query = async () => {
      const selected = { ...f.tab };
      mutate(f);
      return [selected];
    };
    await assert.rejects(resolveCurrentSource(f.browser, 4), /closed|changed|active/);
    assert.equal(f.calls.some(call => call[0] === 'capture'), false);
  }
});

test('minimizing the browser during capture discards the pixels before decoding', async () => {
  const f = fixture();
  let state = 'normal';
  let decoded = false;
  f.browser.windows.get = async id => ({ id, type: 'normal', state });
  f.browser.tabs.captureVisibleTab = async () => { state = 'minimized'; return 'data:image/png;base64,capture'; };
  f.helpers.decodeImage = async () => { decoded = true; return { width: 800, height: 600 }; };
  await assert.rejects(captureSource(f.browser, f.source, f.helpers), /Restore the browser window/);
  assert.equal(decoded, false);
  assert.equal(f.calls.some(call => call[0] === 'encode'), false);
});

test('fresh selection explains the toolbar permission grant when current tab metadata is unreadable', async () => {
  const f = fixture();
  delete f.tab.url;
  await assert.rejects(resolveCurrentSource(f.browser, 4), /Click the Jarvis toolbar icon on that webpage to grant access/);
  f.browser.tabs.query = async () => { throw new Error('Permission denied'); };
  await assert.rejects(resolveCurrentSource(f.browser, 4), /Click the Jarvis toolbar icon on that webpage to grant access/);
  assert.equal(f.calls.some(call => call[0] === 'capture'), false);
});
