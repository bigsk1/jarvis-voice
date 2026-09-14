export const MENU_IDS = Object.freeze({
  root: 'jarvis',
  capture: 'jarvis-capture',
  selection: 'jarvis-selection',
  link: 'jarvis-link',
});

/** Call at background module startup so Firefox can wake these event listeners. */
export function setupMenus(browserApi, onAction) {
  const menus = browserApi.menus || browserApi.contextMenus;
  let installing = null;
  function ensureMenus() {
    if (installing) return installing;
    installing = (async () => {
      await menus.removeAll();
      menus.create({
        id: MENU_IDS.root,
        title: 'Jarvis',
        contexts: ['page', 'selection', 'link', 'image'],
        documentUrlPatterns: ['http://*/*', 'https://*/*'],
      });
      menus.create({ id: MENU_IDS.capture, parentId: MENU_IDS.root, title: 'Capture page view', contexts: ['page', 'selection', 'link', 'image'] });
      menus.create({ id: MENU_IDS.selection, parentId: MENU_IDS.root, title: 'Ask about selected text', contexts: ['selection'] });
      menus.create({ id: MENU_IDS.link, parentId: MENU_IDS.root, title: 'Ask about this link', contexts: ['link'] });
    })().finally(() => { installing = null; });
    return installing;
  }

  function onClicked(info, tab) {
    const common = { tab, pageUrl: info.pageUrl || tab?.url || '' };
    if (info.menuItemId === MENU_IDS.capture) {
      return onAction({ kind: 'capture', ...common });
    }
    if (info.menuItemId === MENU_IDS.selection && info.selectionText) {
      return onAction({ kind: 'selection', ...common, selectionText: info.selectionText });
    }
    if (info.menuItemId === MENU_IDS.link && info.linkUrl) {
      return onAction({ kind: 'link', ...common, linkUrl: info.linkUrl });
    }
  }

  menus.onClicked.addListener(onClicked);
  browserApi.runtime.onInstalled.addListener(ensureMenus);
  return {
    ensureMenus,
    dispose() {
      menus.onClicked.removeListener(onClicked);
      browserApi.runtime.onInstalled.removeListener(ensureMenus);
    },
  };
}
