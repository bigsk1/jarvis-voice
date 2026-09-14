import test from 'node:test';
import assert from 'node:assert/strict';
import { MENU_IDS, setupMenus } from '../browser/menus.js';

function event() {
  const listeners = new Set();
  return { listeners, addListener(callback) { listeners.add(callback); }, removeListener(callback) { listeners.delete(callback); } };
}

function fixture() {
  const definitions = new Map();
  let removals = 0;
  const browser = {
    menus: {
      onClicked: event(),
      async removeAll() { removals += 1; definitions.clear(); },
      create(definition) {
        assert.equal(definitions.has(definition.id), false, 'menu IDs must not be registered twice');
        definitions.set(definition.id, definition);
        return definition.id;
      },
    },
    runtime: { onInstalled: event() },
  };
  return { browser, definitions, removals: () => removals };
}

test('registers wake listeners synchronously and installation is repeatable', async () => {
  const f = fixture();
  const controller = setupMenus(f.browser, () => {});
  assert.equal(f.browser.menus.onClicked.listeners.size, 1);
  assert.equal(f.browser.runtime.onInstalled.listeners.size, 1);
  const [onInstalled] = f.browser.runtime.onInstalled.listeners;
  await Promise.all([onInstalled(), controller.ensureMenus()]);
  assert.equal(f.removals(), 1);
  assert.equal(f.definitions.size, 4);
  await onInstalled();
  assert.equal(f.definitions.size, 4);
  assert.deepEqual(f.definitions.get(MENU_IDS.root).documentUrlPatterns, ['http://*/*', 'https://*/*']);
  controller.dispose();
  assert.equal(f.browser.menus.onClicked.listeners.size, 0);
  assert.equal(f.browser.runtime.onInstalled.listeners.size, 0);
});

test('selection and link actions use supplied menu metadata without reading page scripts', async () => {
  const f = fixture();
  const actions = [];
  setupMenus(f.browser, action => actions.push(action));
  const [onClicked] = f.browser.menus.onClicked.listeners;
  const tab = { id: 5, windowId: 3, url: 'https://example.com/page' };
  onClicked({ menuItemId: MENU_IDS.selection, selectionText: 'Error: expected <value>', pageUrl: tab.url }, tab);
  onClicked({ menuItemId: MENU_IDS.link, linkUrl: 'https://example.org/doc?a=1&b=2' }, tab);
  onClicked({ menuItemId: MENU_IDS.capture }, tab);
  assert.deepEqual(actions, [
    { kind: 'selection', tab, pageUrl: tab.url, selectionText: 'Error: expected <value>' },
    { kind: 'link', tab, pageUrl: tab.url, linkUrl: 'https://example.org/doc?a=1&b=2' },
    { kind: 'capture', tab, pageUrl: tab.url },
  ]);
});

test('ignores unknown and empty menu actions', () => {
  const f = fixture();
  const actions = [];
  setupMenus(f.browser, action => actions.push(action));
  const [onClicked] = f.browser.menus.onClicked.listeners;
  for (const menuItemId of ['another-extension', MENU_IDS.root, MENU_IDS.selection, MENU_IDS.link]) {
    onClicked({ menuItemId }, {});
  }
  assert.deepEqual(actions, []);
});
