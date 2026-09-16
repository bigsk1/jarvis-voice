/** Source identity is explicit so a detached Jarvis window never captures itself. */
export function normalizeSource(tab) {
  if (!tab || !Number.isInteger(tab.id ?? tab.tabId) || !Number.isInteger(tab.windowId)) {
    throw new Error('Choose a browser tab before capturing.');
  }
  if (tab.incognito) {
    throw new Error('Private browsing content is not supported. Jarvis saves uploaded images and conversations.');
  }
  let url;
  try {
    url = new URL(tab.url);
  } catch {
    throw new Error('Firefox could not read this tab. Click the Jarvis toolbar icon on that webpage to grant access, then try again.');
  }
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error('Choose an HTTP or HTTPS webpage. Browser and extension pages cannot be captured.');
  }
  if (tab.pendingUrl && tab.pendingUrl !== tab.url) {
    throw new Error('The source tab is navigating. Wait for the page to finish, then select it again.');
  }
  return {
    tabId: tab.id ?? tab.tabId,
    windowId: tab.windowId,
    title: String(tab.title || ''),
    url: tab.url,
  };
}

function validateCaptureWindow(window) {
  if (!window || !Number.isInteger(window.id) || window.type !== 'normal' || window.incognito) {
    throw new Error('Choose a tab in a normal browser window. Private and extension windows are not supported.');
  }
  if (window.state === 'minimized') {
    throw new Error('Restore the browser window before capturing. Minimized windows cannot be captured.');
  }
  return window;
}

async function getSourceWindow(browserApi, windowId) {
  let window;
  try {
    window = await browserApi.windows.get(windowId);
  } catch {
    throw new Error('The source browser window was closed. Open the webpage again before capturing.');
  }
  return validateCaptureWindow(window);
}

/** Select the page visible now, then freeze its identity for this capture only. */
export async function resolveCurrentSource(browserApi, preferredWindowId = null, rememberedWindowId = null) {
  let window;
  if (preferredWindowId !== null) {
    if (!Number.isInteger(preferredWindowId)) {
      throw new Error('Choose a normal browser window before capturing.');
    }
    // A sidebar belongs to this window; never substitute another if it closes.
    window = await getSourceWindow(browserApi, preferredWindowId);
  } else {
    try {
      window = await browserApi.windows.getLastFocused();
    } catch {
      throw new Error('Open a normal Firefox window with the webpage you want to capture.');
    }
    // Firefox ignores the deprecated getLastFocused window-type filter, so
    // inspect the returned window and resolve a focused pop-out ourselves.
    // Enumerating windows does not give a focus ordering, so never take the first.
    if (window?.type !== 'normal') {
      let windows;
      try {
        windows = await browserApi.windows.getAll({ windowTypes: ['normal'] });
      } catch {
        throw new Error('Open a normal Firefox window with the webpage you want to capture.');
      }
      const candidates = windows.filter(candidate => candidate.type === 'normal');
      window = candidates.find(candidate => candidate.id === rememberedWindowId);
      if (!window) {
        if (candidates.length === 0) {
          throw new Error('Open a normal Firefox window with the webpage you want to capture.');
        }
        if (candidates.length !== 1) {
          throw new Error('Choose the browser window to capture by clicking its Jarvis toolbar icon, then try Capture again.');
        }
        [window] = candidates;
      }
    }
    validateCaptureWindow(window);
  }
  let tabs;
  try {
    tabs = await browserApi.tabs.query({ active: true, windowId: window.id });
  } catch {
    throw new Error('Firefox could not read the active tab. Click the Jarvis toolbar icon on that webpage to grant access, then try Capture again.');
  }
  if (tabs.length !== 1 || tabs[0].windowId !== window.id) {
    throw new Error('Choose an active browser tab in this window to capture.');
  }
  // Re-read after the query so a closed, switched, or navigating tab fails visibly.
  return resolveSource(browserApi, normalizeSource(tabs[0]));
}

/** Resolve a stored tab without silently switching to another page or window. */
export async function resolveSource(browserApi, storedSource = null) {
  if (!storedSource) return resolveCurrentSource(browserApi);
  let tab;
  const expected = normalizeSource(storedSource);
  try {
    tab = await browserApi.tabs.get(expected.tabId);
  } catch {
    throw new Error('The source tab was closed. Select another tab to capture.');
  }
  const source = normalizeSource(tab);
  if (source.tabId !== expected.tabId || source.windowId !== expected.windowId || source.url !== expected.url) {
    throw new Error('The source tab changed or navigated. Select the page again before capturing.');
  }
  await getSourceWindow(browserApi, source.windowId);
  if (tab.active !== true) {
    throw new Error('The source tab is no longer active. Switch back to that tab and try again.');
  }
  return source;
}
